from groundcast.config import Settings
from groundcast.models import Script, Segment, Sentence, SentenceKind
from groundcast.voice_direction import direct


def _seg(seg_id: str, heading: str, *texts: str, kind: SentenceKind = SentenceKind.CLAIM) -> Segment:
    return Segment(id=seg_id, heading=heading,
                   sentences=[Sentence(id=f"{seg_id}.{n}", text=t, kind=kind) for n, t in enumerate(texts)])  # fmt: skip


SCRIPT = Script(title="Lake", segments=[
    _seg("g1", "Why the lake matters", "The lake feeds the town and the farms around it."),
    _seg("g2", "The numbers", "It is 42 metres deep and covers twelve square kilometres in 2019."),
    _seg("g3", "Wrapping up", "So the lake is deep and large."),
    _seg("g4", "Recall", "How deep is the lake?", kind=SentenceKind.RECALL),
])  # fmt: skip


def test_dense_segments_slow_down_and_recaps_speed_up(settings: Settings) -> None:
    settings.tts.speed = 1.2
    d = direct(SCRIPT, settings.tts)
    assert d["g1"].speed == 1.2 and d["g1"].reason == ""
    assert d["g2"].speed == round(1.2 * 0.93, 3) and "dense" in d["g2"].reason
    assert d["g3"].speed == round(1.2 * 1.05, 3) and "recap" in d["g3"].reason
    assert d["g4"].speed == 1.2  # recall questions keep the base speed
    assert all(x.speed == 1.2 for x in direct(SCRIPT, settings.tts, adapt=False).values())
