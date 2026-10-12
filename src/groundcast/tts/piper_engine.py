"""Piper speech synthesis, the fallback engine.

Piper is GPL-3.0, so groundcast never imports it: each sentence goes to the
piper program in its own process, which writes a WAV file. A voice is an
ONNX model file named after the voice (for example en_US-lessac-medium.onnx,
with its .onnx.json) in tts.piper_voices_dir. Each voice has its own
licence; check it on the voice's model card before use.
"""

from __future__ import annotations

import subprocess
import tempfile
import wave
from collections.abc import Callable
from pathlib import Path

import numpy as np

from groundcast.tts.base import Line, Synthesizer, TTSError


def piper_voices(voices_dir: Path) -> list[str]:
    """Voices whose model and config are both present."""
    if not voices_dir.is_dir():
        return []
    return sorted(p.stem for p in voices_dir.glob("*.onnx") if p.with_suffix(".onnx.json").is_file())


def _read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as w:
        if w.getsampwidth() != 2:
            raise TTSError(f"piper wrote {8 * w.getsampwidth()}-bit audio; 16-bit expected")
        rate, frames = w.getframerate(), w.readframes(w.getnframes())
        channels = w.getnchannels()
    samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    return samples, rate


def _resample(samples: np.ndarray, rate: int, target: int) -> np.ndarray:
    if rate == target or not len(samples):
        return samples
    n = int(round(len(samples) * target / rate))
    return np.interp(np.linspace(0, len(samples) - 1, n), np.arange(len(samples)), samples).astype(np.float32)


class PiperSynthesizer(Synthesizer):
    """One piper process per voice and speed: loading a voice takes longer than reading a sentence."""

    def __init__(self, command: list[str], voices_dir: Path, sample_rate: int, timeout_s: float) -> None:
        self.command = command
        self.voices_dir = voices_dir
        self.sample_rate = sample_rate  # Piper voices differ (often 22050 Hz); output is resampled to this
        self.timeout_s = timeout_s

    def synthesize(self, text: str, voice: str, speed: float) -> np.ndarray:
        return self.synthesize_many([(text, voice, speed)])[0]

    def _run(self, texts: list[str], voice: str, speed: float) -> list[np.ndarray]:
        """Each text as one line to one piper process, which writes one WAV per line, named in order."""
        model = self.voices_dir / f"{voice}.onnx"
        if not model.is_file():
            raise TTSError(
                f"no Piper voice {voice!r} in {self.voices_dir}; download it with: "
                f"python -m piper.download_voices {voice} --data-dir {self.voices_dir}"
            )
        with tempfile.TemporaryDirectory(prefix="groundcast-piper-") as tmp:
            out_dir = Path(tmp)
            cmd = [*self.command, "-m", str(model), "-d", str(out_dir), "--length-scale", f"{1.0 / speed:.3f}"]
            data = "".join(" ".join(t.split()) + "\n" for t in texts).encode("utf-8")
            try:
                proc = subprocess.run(cmd, input=data, capture_output=True, check=False,
                                      timeout=self.timeout_s * len(texts))  # fmt: skip
            except FileNotFoundError as exc:
                raise TTSError(f"piper not found ({self.command[0]}); install it with: pip install piper-tts") from exc
            except subprocess.TimeoutExpired as exc:
                raise TTSError(f"piper took longer than {self.timeout_s:.0f} s per sentence") from exc
            files = sorted(out_dir.glob("*.wav"), key=lambda p: int(p.stem) if p.stem.isdigit() else p.stem)
            if proc.returncode == 0 and len(files) != len(texts) and len(texts) > 1:
                # Files are named by a clock that ticks coarsely on some systems, so two short lines
                # can overwrite each other; then read the lines one process at a time.
                return [self._run([t], voice, speed)[0] for t in texts]
            if proc.returncode != 0 or len(files) != len(texts):
                detail = proc.stderr.decode(errors="replace").strip()[-500:]
                raise TTSError(f"piper wrote {len(files)} of {len(texts)} lines: {detail}")
            out = []
            for path in files:
                samples, rate = _read_wav(path)
                out.append(_resample(samples, rate, self.sample_rate))
            return out

    def synthesize_many(self, lines: list[Line], done: Callable[[int], None] | None = None) -> list[np.ndarray]:
        results: list[np.ndarray | None] = [None] * len(lines)
        groups: dict[tuple[str, float], list[int]] = {}
        for i, (text, voice, speed) in enumerate(lines):
            if text.split():
                groups.setdefault((voice, speed), []).append(i)
            else:
                results[i] = np.zeros(0, dtype=np.float32)  # piper skips empty lines
        finished = len(lines) - sum(len(g) for g in groups.values())
        for (voice, speed), indices in groups.items():
            for i, samples in zip(indices, self._run([lines[i][0] for i in indices], voice, speed)):
                results[i] = samples
            finished += len(indices)
            if done:
                done(finished)
        return [r for r in results if r is not None]
