"""Audio assembly and MP3 export. ffmpeg runs as a separate program."""

from __future__ import annotations

import subprocess
import wave
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


def encode_mp3(wav_path: Path, mp3_path: Path, ffmpeg_bin: str, bitrate: str, tags: dict[str, str]) -> None:
    args = [ffmpeg_bin, "-hide_banner", "-loglevel", "error", "-y", "-i", str(wav_path)]
    for key, value in tags.items():
        args += ["-metadata", f"{key}={value}"]
    args += ["-id3v2_version", "3", "-codec:a", "libmp3lame", "-b:a", bitrate, str(mp3_path)]
    try:
        proc = subprocess.run(args, capture_output=True, check=False)
    except FileNotFoundError as exc:
        raise AudioError(f"ffmpeg not found ({ffmpeg_bin})") from exc
    if proc.returncode != 0:
        raise AudioError(f"ffmpeg failed: {proc.stderr.decode(errors='replace').strip()}")
