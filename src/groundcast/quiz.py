"""Web quizzes on a finished session (S10).

The quiz writer asks multiple-choice questions about what the session taught.
For every option it also writes the sentence that would be true if that
option were the answer. The Verifier checks those sentences against the
materials: the correct option's sentence must be supported and every wrong
option's sentence must be unsupported or contradicted, so a question never
has two right answers or a right answer the materials do not state. Questions that fail are dropped. Options
are shuffled here, since a model tends to put the answer in one place.
"""

from __future__ import annotations

import random
import secrets
from datetime import datetime

from pydantic import BaseModel, Field

from groundcast.config import Settings
from groundcast.llm import LLMBackend, Role
from groundcast.models import Chunk, Label, Material, Script, Sentence, SentenceKind, SourceLink, utc_now
from groundcast.pipeline.common import format_passages, load_prompt
from groundcast.pipeline.verifier import build_items, verify_items
from groundcast.pipeline.writer import clean_sources
from groundcast.profile.concepts import Concept
from groundcast.retrieval import BM25Index
from groundcast.storage import Store, read_model, write_model
from groundcast.transcript import source_links

QUIZ_FILE = "quiz.json"
# A wrong option's statement must be a false claim, not signposting or framing.
WRONG_LABELS = frozenset({Label.UNSUPPORTED, Label.CONTRADICTED})


class DraftOption(BaseModel):
    text: str
    statement: str = Field(description="The full sentence that is true if this option is the answer")


class DraftQuestion(BaseModel):
    question: str
    options: list[DraftOption]
    correct: int = Field(description="Index of the correct option, from 0")
    explanation: str
    sources: list[str] = Field(default_factory=list)
    topic: str = Field(description="The heading of the segment the question is about")
    concepts: list[str] = Field(default_factory=list, description="IDs of the listed concepts the question tests")


class QuizDraft(BaseModel):
    questions: list[DraftQuestion]


class QuizQuestion(BaseModel):
    id: str
    question: str
    options: list[str]
    correct: int
    explanation: str
    sources: list[SourceLink] = Field(default_factory=list)
    topic: str = ""
    concepts: list[str] = Field(default_factory=list)  # concept table IDs


class Quiz(BaseModel):
    id: str
    questions: list[QuizQuestion]
    dropped: int = 0  # questions the Verifier rejected
    created_at: datetime = Field(default_factory=utc_now)


class QuizAttempt(BaseModel):
    id: str
    quiz_id: str
    answers: list[int | None]  # chosen option per question; None when skipped
    score: int
    created_at: datetime = Field(default_factory=utc_now)


class QuizFile(BaseModel):
    quizzes: list[Quiz] = Field(default_factory=list)
    attempts: list[QuizAttempt] = Field(default_factory=list)


class QuestionView(BaseModel):
    id: str
    question: str
    options: list[str]
    topic: str


class QuizView(BaseModel):
    """A quiz as served before it is answered: no answers or explanations."""

    id: str
    questions: list[QuestionView]
    created_at: datetime
    attempts: list[QuizAttempt] = Field(default_factory=list)


class QuestionResult(BaseModel):
    id: str
    chosen: int | None
    correct: int
    right: bool
    explanation: str
    sources: list[SourceLink]


class AttemptResult(BaseModel):
    attempt: QuizAttempt
    results: list[QuestionResult]


def load_quizzes(store: Store, session_id: str) -> QuizFile:
    path = store.session_dir(session_id) / QUIZ_FILE
    return read_model(path, QuizFile) if path.is_file() else QuizFile()


def save_quizzes(store: Store, session_id: str, data: QuizFile) -> None:
    write_model(store.session_dir(session_id) / QUIZ_FILE, data)


def view(quiz: Quiz, attempts: list[QuizAttempt]) -> QuizView:
    return QuizView(
        id=quiz.id,
        questions=[
            QuestionView(id=q.id, question=q.question, options=q.options, topic=q.topic) for q in quiz.questions
        ],
        created_at=quiz.created_at,
        attempts=[a for a in attempts if a.quiz_id == quiz.id],
    )


def _script_text(script: Script) -> str:
    lines = []
    for seg in script.segments:
        lines.append(f"## {seg.heading}")
        lines.extend(f"- {s.text} [{', '.join(s.sources)}]" for s in seg.sentences if s.kind == SentenceKind.CLAIM)
        lines.append("")
    return "\n".join(lines)


def _valid(q: DraftQuestion, options: int) -> bool:
    texts = [o.text.strip().lower() for o in q.options]
    return (
        bool(q.question.strip())
        and len(q.options) == options
        and 0 <= q.correct < options
        and len(set(texts)) == options
        and all(texts)
        and all(o.statement.strip() for o in q.options)
    )


def make_quiz(
    backend: LLMBackend,
    roles: dict[str, Role],
    settings: Settings,
    script: Script,
    chunks: list[Chunk],
    materials: dict[str, Material],
    concepts: list[Concept] | None = None,
) -> Quiz:
    """concepts: the concept table entries of the session's materials, for tagging questions."""
    cfg = settings.quiz
    by_id = {c.id: c for c in chunks}
    cited = list(dict.fromkeys(cid for s in script.sentences() for cid in s.sources if cid in by_id))
    concept_text = "\n".join(f"- {c.id}: {c.name}" for c in concepts or []) or "(none)"
    prompt = (
        f"# Questions wanted\n\n{cfg.questions} questions with {cfg.options} options each.\n\n"
        f"# Session script (the claims it made, with their passage IDs)\n\n{_script_text(script)}\n"
        f"# Concepts (tag each question with the ones it tests)\n\n{concept_text}\n\n"
        f"# Passages\n\n{format_passages(by_id[c] for c in cited)}\n\nWrite the quiz now."
    )
    concept_ids = {c.id for c in concepts or []}
    draft = backend.complete_structured(roles["quiz"], load_prompt("quiz"), prompt, QuizDraft)
    candidates = [q for q in draft.questions if _valid(q, cfg.options)]
    for q in candidates:
        q.sources = clean_sources(q.sources, set(by_id))

    # Every option's statement goes to the Verifier, cited to the question's sources.
    sentences = [
        (Sentence(id=f"q{n}o{m}", text=o.statement.strip(), kind=SentenceKind.CLAIM, sources=q.sources), "")
        for n, q in enumerate(candidates)
        for m, o in enumerate(q.options)
    ]
    index = BM25Index(chunks)
    items = build_items(sentences, by_id, index, settings.pipeline.bm25_top_k, settings.pipeline.retrieval_context)
    verdicts = verify_items(backend, roles["verifier"], items, settings.pipeline.verify_batch_size)

    quiz_id = secrets.token_hex(4)
    rng = random.Random(quiz_id)
    questions = []
    for n, q in enumerate(candidates):
        labels = [verdicts[f"q{n}o{m}"].label for m in range(len(q.options))]
        right = labels[q.correct] == Label.SUPPORTED
        wrong = all(lbl in WRONG_LABELS for m, lbl in enumerate(labels) if m != q.correct)
        if not (right and wrong and q.sources):
            continue
        order = list(range(len(q.options)))
        rng.shuffle(order)
        questions.append(
            QuizQuestion(
                id=f"{quiz_id}-{len(questions) + 1}",
                question=q.question.strip(),
                options=[q.options[i].text.strip() for i in order],
                correct=order.index(q.correct),
                explanation=q.explanation.strip(),
                sources=source_links(q.sources, by_id, materials),
                topic=q.topic.strip(),
                concepts=[c for c in dict.fromkeys(q.concepts) if c in concept_ids],
            )
        )
    return Quiz(id=quiz_id, questions=questions, dropped=len(draft.questions) - len(questions))


def grade(quiz: Quiz, answers: list[int | None]) -> AttemptResult:
    if len(answers) != len(quiz.questions):
        raise ValueError(f"expected {len(quiz.questions)} answers, got {len(answers)}")
    results = []
    for q, chosen in zip(quiz.questions, answers):
        if chosen is not None and not 0 <= chosen < len(q.options):
            raise ValueError(f"answer {chosen} is out of range for question {q.id}")
        results.append(
            QuestionResult(
                id=q.id,
                chosen=chosen,
                correct=q.correct,
                right=chosen == q.correct,
                explanation=q.explanation,
                sources=q.sources,
            )
        )
    attempt = QuizAttempt(
        id=secrets.token_hex(4), quiz_id=quiz.id, answers=answers, score=sum(r.right for r in results)
    )
    return AttemptResult(attempt=attempt, results=results)
