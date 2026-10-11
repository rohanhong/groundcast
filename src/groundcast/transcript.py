"""HTML transcript with source links (S9; spec section 12).

The file sits in <data>/sessions/<id>/ and links to materials by relative
path, so the links work when the file is opened from disk and when the app
serves the data directory.
"""

from __future__ import annotations

from datetime import datetime
from html import escape

from groundcast.models import Chunk, Material, Script, speaker_label

_STYLE = """
:root { --fg: #1d1f23; --muted: #5d6470; --bg: #ffffff; --accent: #3b5bdb; --warn: #b54708; }
@media (prefers-color-scheme: dark) {
  :root { --fg: #e6e8eb; --muted: #9aa3ae; --bg: #15171a; --accent: #8ea6ff; --warn: #f5a35c; }
}
body { font: 17px/1.6 system-ui, sans-serif; color: var(--fg); background: var(--bg);
       max-width: 46rem; margin: 0 auto; padding: 1.5rem 1rem 4rem; }
h1 { font-size: 1.6rem; margin-bottom: .2rem; }
h2 { font-size: 1.15rem; margin-top: 2rem; }
.meta, .notice { color: var(--muted); font-size: .9rem; }
.src { font-size: .72rem; vertical-align: super; margin-left: .15rem; }
.src a { color: var(--accent); text-decoration: none; margin-right: .2rem; }
.unverified { color: var(--warn); }
.unverified::after { content: " [not verified against your materials]"; font-size: .8rem; }
.framing { font-style: italic; }
.speaker { font-weight: 600; color: var(--muted); margin-right: .4rem; }
p.line { margin: .35rem 0; }
ol.sources { font-size: .85rem; color: var(--muted); }
"""


def source_href(chunk: Chunk, material: Material) -> str:
    href = f"../../materials/{material.stored_name}"
    if material.kind == "pdf" and chunk.locator.startswith("p"):
        href += f"#page={chunk.locator[1:]}"
    return href


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
        '<html lang="en"><head><meta charset="utf-8">',
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
                f'<li><a href="{escape(source_href(chunk, material))}">{escape(material.filename)}, '
                f"{escape(chunk.locator)}</a>: {escape(excerpt)}</li>"
            )
        parts.append("</ol>")
    parts.append("</body></html>")
    return "\n".join(parts)
