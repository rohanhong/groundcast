"""Audio assembly and MP3 export. ffmpeg runs as a separate program."""

from __future__ import annotations

import re
import subprocess
import wave
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np


class AudioError(RuntimeError):
    pass


def silence(seconds: float, sample_rate: int) -> np.ndarray:
    return np.zeros(int(seconds * sample_rate), dtype=np.float32)


def write_wav(path: Path, samples: np.ndarray, sample_rate: int) -> None:
    pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm.tobytes())


@dataclass(frozen=True)
class Chapter:
    title: str
    start_s: float
    end_s: float


def _ffmetadata_escape(value: str) -> str:
    return re.sub(r"([=;#\\\n])", r"\\\1", value)


def ffmetadata(chapters: Sequence[Chapter]) -> str:
    """Chapters in ffmpeg's metadata file format; the MP3 muxer writes them as ID3 CHAP frames."""
    lines = [";FFMETADATA1"]
    for c in chapters:
        lines += [
            "[CHAPTER]",
            "TIMEBASE=1/1000",
            f"START={round(c.start_s * 1000)}",
            f"END={round(c.end_s * 1000)}",
            f"title={_ffmetadata_escape(c.title)}",
        ]
    return "\n".join(lines) + "\n"


def encode_mp3(
    wav_path: Path,
    mp3_path: Path,
    ffmpeg_bin: str,
    bitrate: str,
    tags: dict[str, str],
    chapters: Sequence[Chapter] = (),
) -> None:
    args = [ffmpeg_bin, "-hide_banner", "-loglevel", "error", "-y", "-i", str(wav_path)]
    meta_path = mp3_path.with_name(mp3_path.name + ".chapters.txt")
    if chapters:
        meta_path.write_text(ffmetadata(chapters), encoding="utf-8")
        args += ["-i", str(meta_path), "-map", "0:a", "-map_chapters", "1"]
    for key, value in tags.items():
        args += ["-metadata", f"{key}={value}"]
    args += ["-id3v2_version", "3", "-codec:a", "libmp3lame", "-b:a", bitrate, str(mp3_path)]
    try:
        proc = subprocess.run(args, capture_output=True, check=False)
    except FileNotFoundError as exc:
        raise AudioError(f"ffmpeg not found ({ffmpeg_bin})") from exc
    finally:
        meta_path.unlink(missing_ok=True)
    if proc.returncode != 0:
        raise AudioError(f"ffmpeg failed: {proc.stderr.decode(errors='replace').strip()}")
