"""Speech recognition for video and audio materials (faster-whisper, local).

Recognised speech is grouped into passages: a pause of asr.paragraph_gap_s,
the chunk word limit, or asr.max_passage_s starts a new one. Each passage is
its own unit with locator t<start second>, so a source link can open the
recording at that moment. Every passage keeps the mean probability of its
words, which the review step shows before the text can be used (spec S0).
"""

from __future__ import annotations

import gc
import importlib.util
import logging
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from statistics import fmean
from typing import Protocol

import numpy as np

from groundcast.config import Settings
from groundcast.ingest.units import ExtractionError, Unit

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000  # what Whisper models expect
Progress = Callable[[str], None]


@dataclass
class Spoken:
    """One stretch of recognised speech."""

    start: float  # seconds
    end: float
    text: str
    confidence: float  # mean word probability, 0 to 1
    uncertain: list[str] = field(default_factory=list)  # words below the review threshold


class Transcriber(Protocol):
    def transcribe(self, path: Path, progress: Progress) -> tuple[list[Spoken], float]:
        """Return the recognised speech and the duration of the recording in seconds."""
        ...


def add_cuda_runtime_dirs() -> None:
    """Let CTranslate2 find the CUDA 12 runtime installed as pip wheels (nvidia-cublas-cu12, nvidia-cudnn-cu12).

    On Windows, CTranslate2 loads cuBLAS and cuDNN by name at run time, so
    their bin folders must be on the DLL search path. PyTorch's own CUDA
    libraries are a different major version and do not count.
    """
    if sys.platform != "win32":
        return
    spec = importlib.util.find_spec("nvidia")
    for root in (spec.submodule_search_locations or []) if spec else []:
        for name in ("cublas", "cudnn", "cuda_nvrtc"):
            folder = os.path.join(root, name, "bin")
            if os.path.isdir(folder) and folder not in os.environ.get("PATH", ""):
                os.add_dll_directory(folder)
                os.environ["PATH"] = folder + os.pathsep + os.environ.get("PATH", "")


class WhisperTranscriber:
    """faster-whisper on the GPU when one works, else on the CPU; unloaded after each file."""

    def __init__(self, settings: Settings) -> None:
        self.cfg = settings.asr
        self.ffmpeg = settings.audio.ffmpeg_bin
        self.download_root = settings.model_dir / "whisper"

    def _decode(self, path: Path) -> np.ndarray:
        """Mono 16 kHz samples through ffmpeg, which reads any container the app accepts."""
        cmd = [self.ffmpeg, "-nostdin", "-loglevel", "error", "-i", str(path), "-vn", "-ac", "1",
               "-ar", str(SAMPLE_RATE), "-f", "f32le", "-"]  # fmt: skip
        try:
            proc = subprocess.run(cmd, capture_output=True, check=False)
        except FileNotFoundError as exc:
            raise ExtractionError(f"ffmpeg not found ({self.ffmpeg})") from exc
        if proc.returncode != 0:
            raise ExtractionError(f"could not read the audio: {proc.stderr.decode(errors='replace').strip()}")
        return np.frombuffer(proc.stdout, dtype=np.float32)

    def _model(self, device: str):  # type: ignore[no-untyped-def]
        from faster_whisper import WhisperModel

        compute = self.cfg.compute_type
        if compute == "auto":
            compute = "float16" if device == "cuda" else "int8"
        self.download_root.mkdir(parents=True, exist_ok=True)
        return WhisperModel(self.cfg.model, device=device, compute_type=compute,
                            download_root=str(self.download_root))  # fmt: skip

    def _devices(self) -> list[str]:
        if self.cfg.device != "auto":
            return [self.cfg.device]
        try:
            import ctranslate2

            return ["cuda", "cpu"] if ctranslate2.get_cuda_device_count() > 0 else ["cpu"]
        except Exception:  # noqa: BLE001 (no usable CUDA runtime)
            return ["cpu"]

    def transcribe(self, path: Path, progress: Progress) -> tuple[list[Spoken], float]:
        add_cuda_runtime_dirs()
        try:
            import faster_whisper  # noqa: F401
        except ImportError as exc:
            raise ExtractionError('speech recognition needs faster-whisper: pip install -e ".[asr]"') from exc
        progress("Reading the audio track")
        audio = self._decode(path)
        duration = len(audio) / SAMPLE_RATE
        if not len(audio):
            raise ExtractionError(f"{path.name} has no audio track")
        devices = self._devices()
        for n, device in enumerate(devices):
            model = None
            try:
                progress(f"Loading speech recognition model {self.cfg.model} on {device}")
                model = self._model(device)
                segments, _ = model.transcribe(
                    audio,
                    language="en",  # N5: English only
                    beam_size=self.cfg.beam_size,
                    vad_filter=self.cfg.vad_filter,
                    word_timestamps=True,
                )
                spoken = []
                for seg in segments:  # a generator: recognition happens here
                    words = seg.words or []
                    confidence = fmean(w.probability for w in words) if words else 0.0
                    if seg.text.strip():
                        low = [w.word.strip() for w in words if w.probability < self.cfg.review_below]
                        spoken.append(Spoken(seg.start, seg.end, seg.text.strip(), confidence, low))
                    progress(f"Recognised {seg.end:.0f} of {duration:.0f} s")
                return spoken, duration
            except RuntimeError as exc:
                # A GPU without the CUDA libraries CTranslate2 needs fails here; the CPU still works.
                if n + 1 < len(devices):
                    log.warning("speech recognition on %s failed (%s); retrying on %s", device, exc, devices[n + 1])
                    continue
                raise ExtractionError(f"speech recognition failed: {exc}") from exc
            finally:
                del model
                gc.collect()  # free the GPU memory before speech synthesis needs it
        raise ExtractionError("speech recognition found no device")


def make_transcriber(settings: Settings) -> Transcriber:
    if settings.asr.engine == "none":
        raise ExtractionError("speech recognition is switched off (asr.engine = none)")
    return WhisperTranscriber(settings)


def passages(spoken: list[Spoken], max_words: int, gap_s: float, max_s: float) -> list[Unit]:
    """Group recognised speech into passages, one unit each."""
    units: list[Unit] = []
    group: list[Spoken] = []

    def flush() -> None:
        if not group:
            return
        text = " ".join(s.text for s in group)
        words = len(text.split())
        # Weigh each stretch by its length in words.
        confidence = sum(s.confidence * len(s.text.split()) for s in group) / max(words, 1)
        locator = f"t{int(group[0].start)}"
        low = [w for s in group for w in s.uncertain]
        if units and units[-1].locator == locator:
            units[-1].blocks.append(text)
            units[-1].block_uncertain = (units[-1].block_uncertain or []) + [low]
        else:
            units.append(Unit(locator, [text], round(confidence, 3), block_uncertain=[low]))
        group.clear()

    for s in spoken:
        if group:
            words = sum(len(g.text.split()) for g in group) + len(s.text.split())
            if s.start - group[-1].end >= gap_s or words > max_words or s.end - group[0].start > max_s:
                flush()
        group.append(s)
    flush()
    return units
