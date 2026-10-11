"""S8 Voice direction: speech settings per segment, from explicit rules (spec 10.3).

The base voice and speed come from the preferences. On top of them, a
segment dense with numbers is read a little slower, and a closing recap a
little faster, since the listener has heard its content once already.
Learned adaptation would need feedback data the profile does not have yet.
Every change is reported in the session log, and tts.adapt_pace (or the
matching preference) switches it off.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from groundcast.config import TTSSettings
from groundcast.models import Script, Segment, SentenceKind

_NUMBER = re.compile(
    r"\b(\d[\d,.]*|zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|"
    r"sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|"
    r"thousand|million|billion|percent|half|quarter|third)\b",
    re.IGNORECASE,
)
_RECAP = re.compile(r"\b(recap\w*|summary|sum(ming)? up|wrap(ping)? up|key points|takeaways?|in short)\b", re.I)
MIN_SPEED, MAX_SPEED = 0.5, 2.0


@dataclass(frozen=True)
class Direction:
    speed: float  # absolute speed for the segment's sentences
    reason: str = ""  # empty when the segment keeps the base speed


def numbers_per_100_words(segment: Segment) -> float:
    words = sum(len(s.text.split()) for s in segment.sentences)
    found = sum(len(_NUMBER.findall(s.text)) for s in segment.sentences)
    return 100.0 * found / words if words else 0.0


def is_recap(segment: Segment, last_content: bool) -> bool:
    """A segment headed as a recap, or a last segment that opens as one ("To sum up, ...")."""
    if _RECAP.search(segment.heading):
        return True
    return last_content and bool(segment.sentences) and bool(_RECAP.search(segment.sentences[0].text))


def direct(script: Script, tts: TTSSettings, adapt: bool | None = None) -> dict[str, Direction]:
    """Speed for each segment, by segment ID."""
    base = tts.speed
    on = tts.adapt_pace if adapt is None else adapt
    content = [seg for seg in script.segments if not any(s.kind == SentenceKind.RECALL for s in seg.sentences)]
    last_id = content[-1].id if content else None
    out = {}
    for seg in script.segments:
        factor, reason = 1.0, ""
        if on:
            density = numbers_per_100_words(seg)
            if is_recap(seg, seg.id == last_id):
                factor, reason = 1.0 + tts.recap_speedup, "recap, heard once already"
            elif density >= tts.dense_numbers:
                factor, reason = 1.0 - tts.dense_slowdown, f"dense: {density:.1f} numbers per 100 words"
        speed = min(MAX_SPEED, max(MIN_SPEED, round(base * factor, 3)))
        out[seg.id] = Direction(speed, reason)
    return out
