"""Kokoro-82M speech synthesis (Apache-2.0 code and weights).

The kokoro package imports misaki.espeak at module load, which imports the
GPL phonemizer package and loads the espeak-ng library into this process.
groundcast runs GPL programs only as separate processes (spec section 15),
so a stub replaces misaki.espeak before kokoro is imported. Words missing
from Kokoro's lexicon then go to EspeakCLIFallback, which runs the espeak-ng
program in its own process, when tts.espeak_bin is set; otherwise they are
skipped.
"""

from __future__ import annotations

import re
import subprocess
import sys
import types
from pathlib import Path
from typing import Any

import numpy as np

from groundcast.tts.base import Synthesizer, TTSError

# espeak IPA to Kokoro phoneme mapping, adapted from misaki.espeak.EspeakFallback
# (misaki, Copyright hexgrad, Apache-2.0).
_E2M = sorted(
    {
        "\u0294\u02ccn\u0329": "\u0294n",
        "\u0294n\u0329": "\u0294n",
        "a^\u026a": "I",
        "a^\u028a": "W",
        "d^\u0292": "\u02a4",
        "e^\u026a": "A",
        "e": "A",
        "t^\u0283": "\u02a7",
        "\u0254^\u026a": "Y",
        "\u0259^l": "\u1d4al",
        "\u02b2o": "jo",
        "\u02b2\u0259": "j\u0259",
        "\u02b2": "",
        "\u025a": "\u0259\u0279",
        "r": "\u0279",
        "x": "k",
        "\u00e7": "k",
        "\u0250": "\u0259",
        "\u026c": "l",
        "\u0303": "",
    }.items(),
    key=lambda kv: -len(kv[0]),
)


def espeak_to_kokoro(ipa: str, british: bool) -> str:
    """Convert espeak-ng IPA (tie character "^") to Kokoro phonemes."""
    ps = ipa.strip()
    for old, new in _E2M:
        ps = ps.replace(old, new)
    ps = re.sub(r"(\S)\u0329", "\u1d4a\\1", ps).replace(chr(809), "")
    if british:
        ps = ps.replace("e^\u0259", "\u025b\u02d0").replace("i\u0259", "\u026a\u0259").replace("\u0259^\u028a", "Q")
    else:
        ps = ps.replace("o^\u028a", "O").replace("\u025c\u02d0\u0279", "\u025c\u0279").replace("\u025c\u02d0", "\u025c\u0279")
        ps = ps.replace("\u026a\u0259", "i\u0259").replace("\u02d0", "")
    ps = ps.replace("o", "\u0254")
    ps = ps.replace("\u027e", "T").replace("\u0294", "t")
    return ps.replace("^", "")


class EspeakCLIFallback:
    """misaki G2P fallback that runs the espeak-ng program per unknown word."""

    def __init__(self, espeak_bin: str, british: bool) -> None:
        self.espeak_bin = espeak_bin
        self.british = british
        self.voice = "en-gb" if british else "en-us"

    def __call__(self, token: Any) -> tuple[str | None, int | None]:
        text = token.text.strip()
        if not text:
            return None, None
        try:
            proc = subprocess.run(
                [self.espeak_bin, "-q", "--ipa", "--tie=^", "-v", self.voice, text],
                capture_output=True,
                check=False,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None, None
        ipa = proc.stdout.decode("utf-8", errors="replace").strip()
        if proc.returncode != 0 or not ipa:
            return None, None
        return espeak_to_kokoro(" ".join(ipa.split()), self.british), 2


def _block_inprocess_espeak() -> None:
    if "kokoro.pipeline" in sys.modules:
        return
    stub = types.ModuleType("misaki.espeak")
    stub.__doc__ = "groundcast stub: espeak-ng runs only as a separate process."

    def _disabled(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("in-process espeak-ng is disabled by groundcast")

    stub.EspeakFallback = _disabled  # type: ignore[attr-defined]
    stub.EspeakG2P = _disabled  # type: ignore[attr-defined]
    sys.modules["misaki.espeak"] = stub
    import misaki

    misaki.espeak = stub  # type: ignore[attr-defined]


class KokoroSynthesizer(Synthesizer):
    def __init__(
        self, repo_id: str, lang_code: str, device: str, model_dir: Path, sample_rate: int, espeak_bin: str
    ) -> None:
        try:
            _block_inprocess_espeak()
            from huggingface_hub import hf_hub_download
            from kokoro import KModel, KPipeline
        except ImportError as exc:
            raise TTSError('Kokoro needs the "tts" extra: pip install -e ".[tts]"') from exc
        import torch

        self._download = lambda name: hf_hub_download(repo_id, name, cache_dir=model_dir)
        resolved = None if device == "auto" else device
        if resolved is None:
            resolved = "cuda" if torch.cuda.is_available() else "cpu"
        if repo_id not in KModel.MODEL_NAMES:
            raise TTSError(f"unknown Kokoro repository: {repo_id}")
        config_path = self._download("config.json")
        model_path = self._download(KModel.MODEL_NAMES[repo_id])
        model = KModel(repo_id=repo_id, config=config_path, model=model_path).to(resolved).eval()
        self.pipeline = KPipeline(lang_code=lang_code, repo_id=repo_id, model=model)
        if espeak_bin:
            self.pipeline.g2p.fallback = EspeakCLIFallback(espeak_bin, british=lang_code == "b")
        self.sample_rate = sample_rate
        self._voices: dict[str, str] = {}
        self._torch = torch

    def _voice_path(self, voice: str) -> str:
        if voice not in self._voices:
            if not re.fullmatch(r"[a-z]{2}_[a-z]+", voice):
                raise TTSError(f"invalid Kokoro voice name: {voice!r}")
            self._voices[voice] = self._download(f"voices/{voice}.pt")
        return self._voices[voice]

    def synthesize(self, text: str, voice: str, speed: float) -> np.ndarray:
        parts = []
        with self._torch.inference_mode():
            for result in self.pipeline(text, voice=self._voice_path(voice), speed=speed):
                if result.audio is not None:
                    parts.append(result.audio.detach().cpu().numpy().astype(np.float32))
        if not parts:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(parts)

    def close(self) -> None:
        self.pipeline = None  # type: ignore[assignment]
        if self._torch.cuda.is_available():
            self._torch.cuda.empty_cache()
