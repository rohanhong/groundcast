"""Settings: defaults, then an optional TOML file, then environment variables.

Environment variables win. Each setting maps to ``GROUNDCAST_<SECTION>_<KEY>``
(for example ``GROUNDCAST_LLM_WRITER_MODEL``); top-level settings drop the
section (``GROUNDCAST_DATA_DIR``). The TOML file is read from
``GROUNDCAST_CONFIG`` when set, otherwise from ``config.toml`` in the per-user
config directory of the OS. ``config/groundcast.example.toml`` lists every key.
"""

from __future__ import annotations

import ipaddress
import os
import tomllib
from pathlib import Path
from typing import Any, Literal

import platformdirs
from pydantic import BaseModel, ConfigDict, Field, field_validator

APP_NAME = "groundcast"
ENV_PREFIX = "GROUNDCAST_"
CONFIG_ENV = "GROUNDCAST_CONFIG"


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ServerSettings(_Section):
    host: str = "127.0.0.1"
    port: int = 8765

    @field_validator("host")
    @classmethod
    def _loopback_only(cls, value: str) -> str:
        # N1: the app serves the owner only, on the local machine.
        if value != "localhost" and not ipaddress.ip_address(value).is_loopback:
            raise ValueError(f"server.host must be a loopback address, got {value!r}")
        return value


class LLMSettings(_Section):
    backend: Literal["claude-cli", "anthropic-api"] = "claude-cli"
    claude_bin: str = "claude"
    api_key_env: str = "ANTHROPIC_API_KEY"
    api_max_tokens: int = 32000
    # Mode A maps the CLI-style model aliases below to API model IDs; a full
    # model ID in a *_model setting passes through unchanged.
    api_models: dict[str, str] = Field(
        default_factory=lambda: {"opus": "claude-opus-5-5", "sonnet": "claude-sonnet-5-5", "haiku": "claude-haiku-5-5"}
    )
    # The Verifier uses a different model tier from the Writer (spec section 7).
    writer_model: str = "opus"
    writer_effort: str = "high"
    verifier_model: str = "sonnet"
    verifier_effort: str = "medium"
    editor_model: str = "opus"
    editor_effort: str = "medium"
    # Answers the learner's typed questions (S10 text Q&A).
    tutor_model: str = "sonnet"
    tutor_effort: str = "medium"
    # Writes multiple-choice quizzes on a finished session.
    quiz_model: str = "sonnet"
    quiz_effort: str = "medium"
    timeout_s: int = 900
    max_attempts: int = 3
    # Wait before retry n is n times this; errors that cannot be fixed by
    # retrying (usage limit, sign-in) are never retried.
    retry_backoff_s: float = 10.0


class IngestSettings(_Section):
    pdftotext_bin: str = "pdftotext"
    chunk_max_words: int = 180


class PipelineSettings(_Section):
    # Spoken words per minute of finished audio at tts.speed 1.0, pauses
    # included; sets the Writer's length target. Measured on 2026-10-11 with
    # Kokoro voice af_heart: 504 words gave 241 s. Each session's log reports
    # its own pace, so this can be re-calibrated for another voice.
    words_per_minute: int = 125
    bm25_top_k: int = 4
    verify_batch_size: int = 20
    max_revise_rounds: int = 2
    # Upper bound on material text given to the Writer; larger selections are
    # cut down to the chunks that best match the brief.
    writer_max_source_words: int = 60000
    # Questions in the closing recall segment when a brief asks for recall prompts.
    recall_questions: int = Field(default=3, ge=1, le=10)
    # What happens to a sentence still failing after max_revise_rounds.
    unresolved: Literal["drop", "mark"] = "drop"


class TTSSettings(_Section):
    engine: Literal["kokoro", "silent"] = "kokoro"
    voice: str = "af_heart"
    # Host B's voice in two-host sessions; Host A and the narrator use voice.
    second_voice: str = "am_michael"
    lang_code: str = "a"
    speed: float = Field(default=1.0, gt=0.25, le=4.0)
    device: str = "auto"
    repo_id: str = "hexgrad/Kokoro-82M"
    sample_rate: int = 24000
    sentence_pause_s: float = 0.35
    segment_pause_s: float = 1.2
    # Silence after a recall question, for the listener to answer before the answer is spoken.
    recall_pause_s: float = 6.0
    # Optional pronunciation fallback for words Kokoro's lexicon lacks. It runs
    # the espeak-ng program as a separate process (GPL; never imported).
    espeak_bin: str = ""
    # Spoken at the start of every session and stored in the MP3 tags (10.4).
    disclaimer: str = "This is an AI-generated audio session, written from your own study materials."


class AudioSettings(_Section):
    ffmpeg_bin: str = "ffmpeg"
    mp3_bitrate: str = "96k"


class QASettings(_Section):
    # Passages of the session's materials given to the Tutor per question.
    top_k: int = Field(default=6, ge=1)
    # Earlier exchanges shown with a question, for follow-ups.
    history_turns: int = Field(default=3, ge=0)
    # Check every answer sentence with the Verifier; failures are shown with a warning.
    verify: bool = True
    max_question_chars: int = Field(default=1000, ge=1)


class QuizSettings(_Section):
    # Questions asked for; the Verifier may drop some.
    questions: int = Field(default=5, ge=1, le=20)
    options: int = Field(default=4, ge=2, le=6)


class EvaluationSettings(_Section):
    # Pass thresholds for `groundcast eval`, on the means over all runs (spec
    # section 13). Set on 2026-10-11 from the M1 baseline on evals/seeded/.
    min_detection_rate: float = Field(default=0.95, ge=0.0, le=1.0)
    max_false_flag_rate: float = Field(default=0.08, ge=0.0, le=1.0)
    # Seeded errors carrying this tag must also reach min_hard_detection_rate.
    hard_tag: str = "hard"
    min_hard_detection_rate: float = Field(default=0.90, ge=0.0, le=1.0)


class Settings(_Section):
    data_dir: Path = Field(default_factory=lambda: Path(platformdirs.user_data_dir(APP_NAME, appauthor=False)))
    model_dir: Path = Field(default_factory=lambda: Path(platformdirs.user_cache_dir(APP_NAME, appauthor=False)) / "models")
    server: ServerSettings = Field(default_factory=ServerSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    ingest: IngestSettings = Field(default_factory=IngestSettings)
    pipeline: PipelineSettings = Field(default_factory=PipelineSettings)
    tts: TTSSettings = Field(default_factory=TTSSettings)
    audio: AudioSettings = Field(default_factory=AudioSettings)
    qa: QASettings = Field(default_factory=QASettings)
    quiz: QuizSettings = Field(default_factory=QuizSettings)
    evaluation: EvaluationSettings = Field(default_factory=EvaluationSettings)


def default_config_path() -> Path:
    return Path(platformdirs.user_config_dir(APP_NAME, appauthor=False)) / "config.toml"


def _env_overrides(environ: dict[str, str]) -> dict[str, Any]:
    """Collect GROUNDCAST_* variables that name a known setting."""
    overrides: dict[str, Any] = {}
    for name, field in Settings.model_fields.items():
        annotation = field.annotation
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            for key in annotation.model_fields:
                env_name = f"{ENV_PREFIX}{name}_{key}".upper()
                if env_name in environ:
                    overrides.setdefault(name, {})[key] = environ[env_name]
        else:
            env_name = f"{ENV_PREFIX}{name}".upper()
            if env_name in environ:
                overrides[name] = environ[env_name]
    return overrides


def _merge(base: dict[str, Any], top: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in top.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_settings(config_path: Path | None = None, environ: dict[str, str] | None = None) -> Settings:
    environ = dict(os.environ if environ is None else environ)
    if config_path is None:
        config_path = Path(environ[CONFIG_ENV]) if CONFIG_ENV in environ else default_config_path()
    data: dict[str, Any] = {}
    if config_path.is_file():
        with config_path.open("rb") as fh:
            data = tomllib.load(fh)
    elif CONFIG_ENV in environ:
        raise FileNotFoundError(f"{CONFIG_ENV} points to a missing file: {config_path}")
    return Settings.model_validate(_merge(data, _env_overrides(environ)))
