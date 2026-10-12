"""HTML transcript with source links (S9; spec section 12).

The file sits in <data>/sessions/<id>/ and links to materials by relative
path, so the links work when the file is opened from disk and when the app
serves the data directory.
"""

from __future__ import annotations

from datetime import datetime
from html import escape

from collections.abc import Iterable

from pydantic import BaseModel

from groundcast.material_view import chunk_label, material_path
from groundcast.models import Chunk, Material, Script, SentenceKind, SourceLink, speaker_label

_STYLE = """
:root { --fg: #1a1c1e; --muted: #5f666c; --bg: #f7f5f0; --accent: #0f766e; --warn: #b45309;
        --chip: #ebe6dc; --host-a: #0f766e; --host-b: #b45309; }
@media (prefers-color-scheme: dark) {
  :root { --fg: #e9ecee; --muted: #a8b0b7; --bg: #121518; --accent: #2dd4bf; --warn: #fbbf24;
          --chip: #252b30; --host-a: #2dd4bf; --host-b: #fbbf24; }
}
body { font: 18px/1.7 "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif; color: var(--fg);
       background: var(--bg); max-width: 44rem; margin: 0 auto; padding: 2.5rem 1.2rem 4rem; }
h1 { font-size: 2rem; line-height: 1.2; margin-bottom: .3rem; }
h2 { font: 700 .8rem/1.4 system-ui, sans-serif; letter-spacing: .1em; text-transform: uppercase;
     color: var(--muted); margin-top: 2.4rem; }
.meta, .notice { font: .9rem/1.5 system-ui, sans-serif; color: var(--muted); }
.src { font: 700 .62rem system-ui, sans-serif; vertical-align: super; line-height: 0; margin-left: .1rem; }
.src a { color: var(--muted); background: var(--chip); border-radius: 4px; padding: .05rem .25rem;
         text-decoration: none; margin-right: .15rem; }
.src a:hover { color: var(--bg); background: var(--accent); }
.unverified { text-decoration: underline wavy var(--warn); text-underline-offset: 4px; }
.unverified::after { content: " [not verified against your materials]"; font: .8rem system-ui, sans-serif;
                     color: var(--warn); }
.framing { font-style: italic; }
.recall { font-weight: 600; }
.recall::after { content: " (pause)"; font-weight: normal; color: var(--muted); font-size: .85rem; }
.speaker { font: 800 .75rem system-ui, sans-serif; color: var(--host-a); margin-right: .5rem;
           text-transform: uppercase; letter-spacing: .06em; }
p.line { margin: .6rem 0; }
ol.sources { font: .88rem/1.6 system-ui, sans-serif; color: var(--muted); }
ol.sources a { color: var(--accent); }
"""


def source_href(chunk: Chunk, material: Material) -> str:
    return "../../" + material_path(chunk, material)


def source_links(
    chunk_ids: Iterable[str], chunks: dict[str, Chunk], materials: dict[str, Material]
) -> list[SourceLink]:
    """Links for the given chunk IDs, once each, in first-cited order."""
    links = []
    for cid in dict.fromkeys(chunk_ids):
        chunk = chunks[cid]
        material = materials[chunk.material_id]
        links.append(
            SourceLink(chunk_id=cid, label=chunk_label(chunk, material), path=material_path(chunk, material))
        )
    return links


def render_transcript(
    script: Script,
    chunks: dict[str, Chunk],
    materials: dict[str, Material],
    created_at: datetime,
    notice: str,
) -> str:
    numbers: dict[str, int] = {}
    parts = [
        "<!doctype html>",
        # No machine translation: a translated sentence is no longer the text the sources were checked against.
        '<html lang="en" translate="no"><head><meta charset="utf-8"><meta name="google" content="notranslate">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{escape(script.title)}</title><style>{_STYLE}</style></head><body>",
        f"<h1>{escape(script.title)}</h1>",
        f'<p class="meta">{escape(created_at.strftime("%Y-%m-%d %H:%M UTC"))}</p>',
        f'<p class="notice">{escape(notice)}</p>',
    ]
    two_hosts = script.format == "two_hosts"
    for seg in script.segments:
        parts.append(f"<h2>{escape(seg.heading)}</h2>")
        if not two_hosts:
            parts.append("<p>")
        previous_speaker = None
        for s in seg.sentences:
            classes = [s.kind.value]
            if s.unverified:
                classes.append("unverified")
            links = []
            for cid in s.sources:
                chunk = chunks.get(cid)
                material = materials.get(chunk.material_id) if chunk else None
                if chunk is None or material is None:
                    continue
                n = numbers.setdefault(cid, len(numbers) + 1)
                links.append(f'<a href="{escape(source_href(chunk, material))}" title="{escape(cid)}">{n}</a>')
            src = f'<span class="src">{"".join(links)}</span>' if links else ""
            line = f'<span class="{" ".join(classes)}">{escape(s.text)}</span>{src} '
            if two_hosts:
                # One paragraph per turn; consecutive sentences of a host stay together.
                if s.speaker != previous_speaker:
                    if previous_speaker is not None:
                        parts.append("</p>")
                    label = speaker_label(s.speaker) if s.speaker else ""
                    parts.append(f'<p class="line"><span class="speaker">{escape(label)}</span>')
                    previous_speaker = s.speaker
                parts.append(line)
            else:
                parts.append(line)
        parts.append("</p>")
    if numbers:
        parts.append("<h2>Sources</h2><ol class=\"sources\">")
        for cid in numbers:
            chunk = chunks[cid]
            material = materials[chunk.material_id]
            excerpt = chunk.text if len(chunk.text) <= 240 else chunk.text[:237] + "..."
            parts.append(
                f'<li><a href="{escape(source_href(chunk, material))}">{escape(chunk_label(chunk, material))}'
                f"</a>: {escape(excerpt)}</li>"
            )
        parts.append("</ol>")
    parts.append("</body></html>")
    return "\n".join(parts)


class ViewSentence(BaseModel):
    id: str
    text: str
    kind: SentenceKind
    speaker: str = ""  # "Host A" in a two-host script, else ""
    unverified: bool = False
    start_s: float | None = None  # where the sentence starts in session.mp3
    sources: list[int] = []  # 1-based positions in TranscriptView.sources


class ViewSegment(BaseModel):
    id: str
    heading: str
    start_s: float | None = None
    sentences: list[ViewSentence]


class TranscriptView(BaseModel):
    """The transcript as the web app's player shows it, timed against the audio."""

    title: str
    format: str
    segments: list[ViewSegment]
    sources: list[SourceLink]


def transcript_view(
    script: Script,
    timings: list[dict[str, object]],
    chunks: dict[str, Chunk],
    materials: dict[str, Material],
) -> TranscriptView:
    """Sources are numbered in first-cited order, as in the HTML transcript; a gone source is left out."""
    starts = {str(t["sentence_id"]): float(t["start_s"]) for t in timings}  # type: ignore[arg-type]
    numbers: dict[str, int] = {}
    segments = []
    for number, seg in enumerate(script.segments):
        sentences = []
        for s in seg.sentences:
            cited = [cid for cid in s.sources if cid in chunks and chunks[cid].material_id in materials]
            sentences.append(ViewSentence(
                id=s.id, text=s.text, kind=s.kind, speaker=speaker_label(s.speaker) if s.speaker else "",
                unverified=s.unverified, start_s=starts.get(s.id),
                sources=[numbers.setdefault(cid, len(numbers) + 1) for cid in cited],
            ))  # fmt: skip
        # The first chapter starts at 0, since the spoken notice comes before it.
        first = sentences[0].start_s if sentences else None
        segments.append(ViewSegment(id=seg.id, heading=seg.heading, sentences=sentences,
                                    start_s=0.0 if number == 0 and first is not None else first))  # fmt: skip
    return TranscriptView(
        title=script.title, format=script.format, segments=segments, sources=source_links(numbers, chunks, materials)
    )
