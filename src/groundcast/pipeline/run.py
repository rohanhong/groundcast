"""Fixed, code-driven pipeline S3 to S7 (spec sections 5 and 6)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from groundcast.config import Settings
from groundcast.llm import LLMBackend, Role
from groundcast.models import Brief, Chunk, Label, Script, Sentence, SentenceKind, Verdict
from groundcast.pipeline.common import Progress, no_progress
from groundcast.pipeline.editor import edit_script
from groundcast.pipeline.verifier import CheckItem, build_items, passages_for, verify_items
from groundcast.pipeline.writer import (
    clean_sources,
    draft_to_script,
    revise_sentences,
    select_sources,
    Pacing,
    shorten_draft,
    write_script,
)
from groundcast.retrieval import BM25Index


class ReportEntry(BaseModel):
    sentence_id: str
    text: str
    stage: str  # verify, revise-<n>, unresolved, edit
    outcome: str  # e.g. replaced, dropped, marked, reverted, kept
    label: Label | None = None
    rationale: str = ""


class VerificationReport(BaseModel):
    target_words: int = 0
    pacing: str = ""  # where the words-per-second estimate came from
    draft_words: list[int] = Field(default_factory=list)  # the first draft, then each shortened one
    writer_sentences: int = 0
    first_pass: dict[str, int] = Field(default_factory=dict)
    revise_rounds: int = 0
    final: dict[str, int] = Field(default_factory=dict)
    edits_applied: int = 0
    edits_reverted: int = 0
    events: list[ReportEntry] = Field(default_factory=list)
    verdicts: dict[str, Verdict] = Field(default_factory=dict)


class PipelineResult(BaseModel):
    script: Script
    report: VerificationReport


def _count(verdicts: dict[str, Verdict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for v in verdicts.values():
        counts[v.label.value] = counts.get(v.label.value, 0) + 1
    return counts


def _with_context(script: Script, ids: set[str] | None = None) -> list[tuple[Sentence, str]]:
    pairs = []
    for seg in script.segments:
        previous = ""
        for s in seg.sentences:
            if ids is None or s.id in ids:
                pairs.append((s, previous))
            previous = s.line()
    return pairs


def _followers(script: Script, ids: set[str]) -> set[str]:
    """The sentence right after each run of ids in a segment.

    Its context changes when those sentences are dropped or rewritten: an
    answer such as "Two of them." means nothing without its question.
    """
    out: set[str] = set()
    for seg in script.segments:
        after = False
        for s in seg.sentences:
            if s.id in ids:
                after = True
            elif after:
                out.add(s.id)
                after = False
    return out


def _orphan_recall(script: Script) -> set[str]:
    """Recall questions not followed, in their segment, by an answer."""
    out: set[str] = set()
    for seg in script.segments:
        for s, nxt in zip(seg.sentences, seg.sentences[1:] + [None]):
            if s.kind == SentenceKind.RECALL and (nxt is None or nxt.kind == SentenceKind.RECALL):
                out.add(s.id)
    return out


def _remove(script: Script, ids: set[str]) -> None:
    for seg in script.segments:
        seg.sentences = [s for s in seg.sentences if s.id not in ids]
    script.segments = [seg for seg in script.segments if seg.sentences]


class Pipeline:
    def __init__(
        self, settings: Settings, backend: LLMBackend, roles: dict[str, Role], pacing: Pacing | None = None
    ) -> None:
        self.settings = settings
        self.backend = backend
        self.roles = roles
        # Without a measured pace, the configured words per minute stands in.
        self.pacing = pacing or Pacing.configured(settings.pipeline.words_per_minute, settings.tts.speed)

    def run(self, brief: Brief, chunks: list[Chunk], progress: Progress = no_progress) -> PipelineResult:
        cfg = self.settings.pipeline
        if not chunks:
            raise ValueError("the brief selects no material text")
        index = BM25Index(chunks)
        by_id = {c.id: c for c in chunks}
        valid = set(by_id)
        report = VerificationReport()

        def verify(pairs: list[tuple[Sentence, str]]) -> dict[str, Verdict]:
            items = build_items(pairs, by_id, index, cfg.bm25_top_k, cfg.retrieval_context)
            return verify_items(self.backend, self.roles["verifier"], items, cfg.verify_batch_size)

        # S3 Write
        sources = select_sources(chunks, index, f"{brief.title} {brief.focus}", cfg.writer_max_source_words)
        progress("write", f"Writing a {brief.minutes}-minute script from {len(sources)} passages")
        target = self.pacing.target_words(brief, cfg.recall_questions, self.settings.tts.recall_pause_s)
        report.target_words = target
        report.pacing = self.pacing.source
        draft = write_script(self.backend, self.roles["writer"], brief, sources, target, cfg.recall_questions)
        report.draft_words.append(draft.word_count())

        # Length check: a model asked for a length tends to run over it.
        for _ in range(cfg.max_trim_rounds):
            words = draft.word_count()
            if words <= target * (1 + cfg.length_tolerance):
                break
            progress("trim", f"The draft has {words} words for a {target}-word target; shortening it")
            shorter = shorten_draft(self.backend, self.roles["writer"], brief, draft, target, cfg.recall_questions)
            report.draft_words.append(shorter.word_count())
            # Keep the draft when shortening did not help or cut recall questions.
            if not 0 < shorter.word_count() < words or shorter.recall_count() < draft.recall_count():
                break
            draft = shorter
        script = draft_to_script(draft, valid, brief.format)
        report.writer_sentences = len(script.sentences())
        if not report.writer_sentences:
            raise ValueError("the Writer returned an empty script")

        # S4 Verify
        progress("verify", f"Checking {report.writer_sentences} sentences against the materials")
        verdicts = verify(_with_context(script))
        report.first_pass = _count(verdicts)

        # S5 Revise, bounded
        for round_no in range(1, cfg.max_revise_rounds + 1):
            failed_ids = {sid for sid, v in verdicts.items() if not v.passed}
            if not failed_ids:
                break
            report.revise_rounds = round_no
            progress("revise", f"Round {round_no}: revising {len(failed_ids)} sentences that failed verification")
            failed = [
                (s, ctx, verdicts[s.id], passages_for(s.text, s.sources, by_id, index, cfg.bm25_top_k,
                                                       ctx if cfg.retrieval_context else ""))
                for s, ctx in _with_context(script, failed_ids)
            ]
            revisions = {r.sentence_id: r for r in revise_sentences(self.backend, self.roles["writer"], failed).revisions}
            dropped: set[str] = set()
            replaced: set[str] = set()
            for s, _, verdict, _ in failed:
                rev = revisions.get(s.id)
                if rev is None or rev.action == "drop" or not rev.text.strip():
                    dropped.add(s.id)
                    report.events.append(
                        ReportEntry(sentence_id=s.id, text=s.text, stage=f"revise-{round_no}", outcome="dropped",
                                    label=verdict.label, rationale=verdict.rationale)
                    )  # fmt: skip
                    continue
                report.events.append(
                    ReportEntry(sentence_id=s.id, text=s.text, stage=f"revise-{round_no}", outcome="replaced",
                                label=verdict.label, rationale=verdict.rationale)
                )  # fmt: skip
                s.text = rev.text.strip()
                s.kind = rev.kind
                s.sources = clean_sources(rev.sources, valid)
                replaced.add(s.id)
            recheck = replaced | _followers(script, dropped | replaced)
            _remove(script, dropped)
            for sid in dropped:
                verdicts.pop(sid, None)
            if recheck:
                verdicts.update(verify(_with_context(script, recheck)))

        # Sentences still failing after the last round. Dropping them changes
        # the context of the sentences that follow, which are checked again;
        # any that now fail go the same way.
        unresolved = {sid for sid, v in verdicts.items() if not v.passed}
        while unresolved:
            for s, _ in _with_context(script, unresolved):
                v = verdicts[s.id]
                outcome = "dropped" if cfg.unresolved == "drop" else "marked"
                report.events.append(
                    ReportEntry(sentence_id=s.id, text=s.text, stage="unresolved", outcome=outcome,
                                label=v.label, rationale=v.rationale)
                )  # fmt: skip
                s.unverified = True
            if cfg.unresolved != "drop":
                break
            followers = _followers(script, unresolved)
            _remove(script, unresolved)
            for sid in unresolved:
                verdicts.pop(sid, None)
            rechecked = verify(_with_context(script, followers)) if followers else {}
            verdicts.update(rechecked)
            unresolved = {sid for sid, v in rechecked.items() if not v.passed}
        # A recall question whose answer was dropped would leave a pause with no answer.
        orphans = _orphan_recall(script)
        for s, _ in _with_context(script, orphans):
            report.events.append(
                ReportEntry(sentence_id=s.id, text=s.text, stage="recall", outcome="dropped",
                            rationale="Its answer did not pass verification.")
            )  # fmt: skip
        _remove(script, orphans)
        for sid in orphans:
            verdicts.pop(sid, None)
        if not script.sentences():
            raise ValueError("no sentence passed verification")

        # S6 Edit
        progress("edit", "Editing for fluency")
        edits = edit_script(self.backend, self.roles["editor"], script)
        headings = {h.segment_id: h.heading.strip() for h in edits.headings if h.heading.strip()}
        for seg in script.segments:
            seg.heading = headings.get(seg.id, seg.heading)
        current = {s.id: s for s in script.sentences()}
        originals: dict[str, str] = {}
        for e in edits.sentences:
            s = current.get(e.sentence_id)
            # Marked sentences keep their unverified text; the Editor may not rescue them.
            if s is None or s.unverified or not e.text.strip() or e.text.strip() == s.text:
                continue
            originals[s.id] = s.text
            s.text = e.text.strip()

        # S7 Re-verify only the changed sentences; a failing edit is reverted.
        if originals:
            progress("reverify", f"Re-checking {len(originals)} edited sentences")
            edited_verdicts = verify(_with_context(script, set(originals)))
            for sid, v in edited_verdicts.items():
                s = current[sid]
                if v.passed:
                    verdicts[sid] = v
                    report.edits_applied += 1
                else:
                    report.events.append(
                        ReportEntry(sentence_id=sid, text=s.text, stage="edit", outcome="reverted",
                                    label=v.label, rationale=v.rationale)
                    )  # fmt: skip
                    s.text = originals[sid]
                    report.edits_reverted += 1

        report.final = _count(verdicts)
        report.verdicts = verdicts
        return PipelineResult(script=script, report=report)


def check_sentences(
    backend: LLMBackend, role: Role, settings: Settings, chunks: list[Chunk], sentences: list[tuple[Sentence, str]]
) -> dict[str, Verdict]:
    """Verify given sentences outside a session (used by the evaluation)."""
    index = BM25Index(chunks)
    by_id = {c.id: c for c in chunks}
    cfg = settings.pipeline
    items: list[CheckItem] = build_items(sentences, by_id, index, cfg.bm25_top_k, cfg.retrieval_context)
    return verify_items(backend, role, items, settings.pipeline.verify_batch_size)
