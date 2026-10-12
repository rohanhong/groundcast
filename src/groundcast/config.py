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
    # On stop, how long open connections (a playing audio stream) may hold the process before they are cut.
    shutdown_timeout_s: float = Field(default=2.0, ge=0)

    @field_validator("host")
    @classmethod
    def _loopback_only(cls, value: str) -> str:
        # The app serves its owner only, on the local machine.
        if value != "localhost" and not ipaddress.ip_address(value).is_loopback:
            raise ValueError(f"server.host must be a loopback address, got {value!r}")
        return value


class LauncherSettings(_Section):
    """`groundcast launch`, which the desktop shortcut runs: start the service, open a window, stop when closed."""

    # app: a browser window without tabs or address bar; browser: a tab in the default browser; none: no window.
    window: Literal["app", "browser", "none"] = "app"
    # Browsers tried in order for the app window: a path (%VARS% and ~ are expanded) or a program name on PATH.
    browsers: list[str] = Field(
        default_factory=lambda: [
            r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
            r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
            r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
            r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
            r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe",
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
            "microsoft-edge",
            "google-chrome",
            "google-chrome-stable",
            "chromium",
            "chromium-browser",
        ]
    )
    ready_timeout_s: float = Field(default=60.0, gt=0)  # how long the service may take to start
    # Stop the service once no groundcast page has been open for close_grace_s and no work is running.
    stop_when_closed: bool = True
    close_grace_s: float = Field(default=15.0, ge=0)
    heartbeat_s: float = Field(default=20.0, gt=0)  # how often an open page checks in
    # A page silent this long counts as closed (a crashed or frozen tab); browsers check hidden tabs once a minute.
    page_timeout_s: float = Field(default=600.0, gt=0)
    shortcut_name: str = "Groundcast"


class LLMSettings(_Section):
    backend: Literal["claude-cli", "codex-cli", "anthropic-api"] = "claude-cli"
    claude_bin: str = "claude"
    # The Codex backend runs codex_bin from PATH, else the newest match of these
    # patterns (the desktop app keeps its CLI in a versioned folder off PATH).
    codex_bin: str = "codex"
    codex_bin_globs: list[str] = Field(default_factory=lambda: ["$LOCALAPPDATA/OpenAI/Codex/bin/*/codex.exe"])
    # Maps the model aliases below to Codex model IDs; a full ID passes through.
    codex_models: dict[str, str] = Field(
        default_factory=lambda: {"opus": "gpt-6-astra", "sonnet": "gpt-6.1-sol", "haiku": "gpt-6-luna"}
    )
    # Codex features switched off so each call is a plain completion with no
    # agent tools; names this Codex version does not list are skipped.
    codex_disable_features: list[str] = Field(
        default_factory=lambda: [
            "shell_tool", "unified_exec", "apps", "plugins", "remote_plugin", "browser_use", "browser_use_external",
            "in_app_browser", "computer_use", "image_generation", "view_image", "multi_agent", "skill_search",
            "tool_suggest", "goals", "sleep_tool", "hooks", "code_mode_host", "workspace_dependencies",
        ]  # fmt: skip
    )
    # Further `codex exec -c key=value` overrides, the value in TOML.
    codex_config: list[str] = Field(default_factory=lambda: ['web_search="disabled"', "include_apply_patch_tool=false"])
    api_key_env: str = "ANTHROPIC_API_KEY"
    api_max_tokens: int = 32000
    # The API backend maps the CLI-style model aliases below to API model IDs; a full
    # model ID in a *_model setting passes through unchanged.
    api_models: dict[str, str] = Field(
        default_factory=lambda: {"opus": "claude-opus-5-5", "sonnet": "claude-sonnet-5-5", "haiku": "claude-haiku-5-5"}
    )
    # The Verifier uses a different model tier from the Writer.
    writer_model: str = "opus"
    writer_effort: str = "high"
    verifier_model: str = "sonnet"
    verifier_effort: str = "medium"
    editor_model: str = "opus"
    editor_effort: str = "medium"
    # Turns a rough request into a brief through a short dialogue; fast replies matter.
    elicitor_model: str = "sonnet"
    elicitor_effort: str = "low"
    # Answers the learner's typed questions.
    tutor_model: str = "sonnet"
    tutor_effort: str = "medium"
    # Extracts concepts from materials and matches them to the concept table.
    concepts_model: str = "sonnet"
    concepts_effort: str = "medium"
    # Writes multiple-choice quizzes on a finished session.
    quiz_model: str = "sonnet"
    quiz_effort: str = "medium"
    # Scores scripts in `groundcast eval-quality`; a different tier from the Writer.
    judge_model: str = "sonnet"
    judge_effort: str = "high"
    timeout_s: int = 900
    max_attempts: int = 3
    # Wait before retry n is n times this; errors that cannot be fixed by
    # retrying (usage limit, sign-in) are never retried.
    retry_backoff_s: float = 10.0


class IngestSettings(_Section):
    pdftotext_bin: str = "pdftotext"
    chunk_max_words: int = 180
    # PowerPoint speaker notes join their slide's text.
    slide_notes: bool = True
    # Web pages added by address.
    fetch_timeout_s: float = Field(default=30.0, gt=0)
    fetch_max_bytes: int = Field(default=20_000_000, ge=1)
    user_agent: str = "groundcast (local study tool)"


class ASRSettings(_Section):
    """Speech recognition for video and audio materials (faster-whisper)."""

    engine: Literal["faster-whisper", "none"] = "faster-whisper"
    model: str = "large-v3-turbo"  # a faster-whisper model name, downloaded into model_dir
    device: str = "auto"  # auto, cpu, or cuda
    compute_type: str = "auto"  # auto: float16 on the GPU, int8 on the CPU
    beam_size: int = Field(default=5, ge=1)
    vad_filter: bool = True  # skip long silences and music
    # A pause this long, or a passage this long, starts a new passage.
    paragraph_gap_s: float = Field(default=2.0, gt=0)
    max_passage_s: float = Field(default=90.0, gt=0)
    # Passages whose mean word probability is lower are highlighted for review.
    review_below: float = Field(default=0.8, ge=0.0, le=1.0)


class OCRSettings(_Section):
    """Text recognition for images and PDF pages without a text layer (Tesseract)."""

    engine: Literal["tesseract", "none"] = "tesseract"
    tesseract_bin: str = "tesseract"
    pdftoppm_bin: str = "pdftoppm"  # renders PDF pages for recognition (poppler)
    pdfimages_bin: str = "pdfimages"  # finds the scanned pages of a PDF (poppler)
    language: str = "eng"  # Tesseract language data
    tessdata_dir: str = ""  # another language data folder, for example the slower, better tessdata_best
    psm: int = Field(default=3, ge=0, le=13)  # Tesseract page segmentation mode; 3 finds the layout
    dpi: int = Field(default=300, ge=72)
    # A PDF page is a scan when its text layer has fewer characters than
    # min_page_chars and it holds an image of at least min_image_pixels.
    min_page_chars: int = Field(default=10, ge=0)
    min_image_pixels: int = Field(default=250_000, ge=1)
    timeout_s: float = Field(default=300.0, gt=0)  # per page
    # Paragraphs whose mean word confidence is lower are highlighted for review.
    review_below: float = Field(default=0.8, ge=0.0, le=1.0)


class PipelineSettings(_Section):
    # Spoken words per minute of finished audio at tts.speed 1.0, pauses
    # included; sets the Writer's length target. Measured with Kokoro voice
    # af_heart: 504 words gave 241 s. Each session's log reports
    # its own pace, so this can be re-calibrated for another voice.
    words_per_minute: int = 125
    # Once a voice has spoken pace_min_words in rendered sessions, its measured
    # pace replaces words_per_minute. Each new session keeps this share of the
    # weight of the earlier ones.
    pace_min_words: int = Field(default=150, ge=1)
    pace_decay: float = Field(default=0.7, ge=0.0, le=1.0)
    bm25_top_k: int = 4
    # Retrieve passages for a sentence with the line before it in the query.
    retrieval_context: bool = True
    verify_batch_size: int = 20
    max_revise_rounds: int = 2
    # Upper bound on material text given to the Writer; larger selections are
    # cut down to the chunks that best match the brief.
    writer_max_source_words: int = 60000
    # A draft longer than the word target by more than this share is sent back
    # to the Writer to shorten, at most max_trim_rounds times. Drafts tend to
    # run about a third over when only asked for a length.
    length_tolerance: float = Field(default=0.15, ge=0.0)
    max_trim_rounds: int = Field(default=2, ge=0)
    # Questions in the closing recall segment when a brief asks for recall prompts.
    recall_questions: int = Field(default=3, ge=1, le=10)
    # What happens to a sentence still failing after max_revise_rounds.
    unresolved: Literal["drop", "mark"] = "drop"


class TTSSettings(_Section):
    engine: Literal["kokoro", "piper", "silent"] = "kokoro"
    voice: str = "af_heart"
    # Host B's voice in two-host sessions; Host A and the narrator use voice.
    second_voice: str = "am_michael"
    lang_code: str = "a"
    # Voices offered as preferences; only those starting with lang_code are shown.
    voice_choices: list[str] = Field(
        default_factory=lambda: [
            "af_heart", "af_alloy", "af_aoede", "af_bella", "af_jessica", "af_kore", "af_nicole", "af_nova",
            "af_river", "af_sarah", "af_sky", "am_adam", "am_echo", "am_eric", "am_fenrir", "am_liam",
            "am_michael", "am_onyx", "am_puck", "am_santa", "bf_alice", "bf_emma", "bf_isabella", "bf_lily",
            "bm_daniel", "bm_fable", "bm_george", "bm_lewis"
        ]
    )
    speed: float = Field(default=1.0, gt=0.25, le=4.0)
    # Voice direction: a segment with at least dense_numbers numbers per
    # 100 words is read dense_slowdown slower; a closing recap recap_speedup faster.
    adapt_pace: bool = True
    dense_numbers: float = Field(default=4.0, gt=0)
    dense_slowdown: float = Field(default=0.07, ge=0.0, lt=1.0)
    recap_speedup: float = Field(default=0.05, ge=0.0, lt=1.0)
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
    # Piper, the fallback engine (GPL, run as a separate program). With
    # engine = "piper", voice and second_voice name Piper voices in
    # piper_voices_dir (default: <model_dir>/piper).
    piper_command: list[str] = Field(default_factory=lambda: ["piper"])
    piper_voices_dir: str = ""
    piper_timeout_s: float = Field(default=60.0, gt=0)
    # Spoken at the start of every session and stored in the MP3 tags (10.4).
    disclaimer: str = "This is an AI-generated audio session, written from your own study materials."


class AudioSettings(_Section):
    ffmpeg_bin: str = "ffmpeg"
    mp3_bitrate: str = "96k"


class ConceptsSettings(_Section):
    # Extract a material's concepts when a session first uses it.
    extract_on_session: bool = True
    # Material words read per extraction call.
    batch_words: int = Field(default=4000, ge=100)
    # Existing concepts shown with each batch, those sharing the most words with it.
    candidates: int = Field(default=100, ge=0)
    max_per_material: int = Field(default=20, ge=1)
    # Event log entries shown in the web app.
    events_shown: int = Field(default=50, ge=1)


class ElicitSettings(_Section):
    # Questions the Elicitor may ask before it must propose a brief.
    max_questions: int = Field(default=3, ge=0)
    # Words of outline per material shown to the Elicitor.
    outline_words: int = Field(default=80, ge=0)
    max_message_chars: int = Field(default=2000, ge=1)


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


class SuggestSettings(_Section):
    """Inferred preferences and ranked suggestions at session start."""

    infer: bool = True  # learn brief defaults from past sessions; the learner can switch it off
    half_life_days: float = Field(default=30.0, gt=0)  # a session's weight halves this often
    min_evidence: float = Field(default=3.0, gt=0)  # sessions' worth of weight for full confidence
    min_confidence: float = Field(default=0.6, ge=0.0, le=1.0)  # below this, an inferred value is only shown
    weak_mastery: float = Field(default=0.6, ge=0.0, le=1.0)  # concepts below this are suggested for revision
    weak_topics: int = Field(default=3, ge=1)  # concepts in one revision suggestion
    max_suggestions: int = Field(default=4, ge=1)
    # Session feedback: "too short" or "too long" scales the repeated session's
    # length by this factor; a rating at or below low_rating ranks it last.
    length_step: float = Field(default=1.25, gt=1.0)
    low_rating: int = Field(default=2, ge=1, le=5)


class TrashSettings(_Section):
    # Deleted materials, sessions, questions, quizzes, and concepts are deleted for good this many days later,
    # when the service starts; 0 keeps them until the trash is emptied by hand.
    keep_days: float = Field(default=30.0, ge=0)


class EvaluationSettings(_Section):
    # Pass thresholds for `groundcast eval`, on the means over all runs,
    # set from the Verifier's measured rates on evals/seeded/.
    min_detection_rate: float = Field(default=0.95, ge=0.0, le=1.0)
    max_false_flag_rate: float = Field(default=0.08, ge=0.0, le=1.0)
    # Seeded errors carrying this tag must also reach min_hard_detection_rate.
    hard_tag: str = "hard"
    min_hard_detection_rate: float = Field(default=0.90, ge=0.0, le=1.0)


class Settings(_Section):
    data_dir: Path = Field(default_factory=lambda: Path(platformdirs.user_data_dir(APP_NAME, appauthor=False)))
    model_dir: Path = Field(default_factory=lambda: Path(platformdirs.user_cache_dir(APP_NAME, appauthor=False)) / "models")
    server: ServerSettings = Field(default_factory=ServerSettings)
    launcher: LauncherSettings = Field(default_factory=LauncherSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    ingest: IngestSettings = Field(default_factory=IngestSettings)
    asr: ASRSettings = Field(default_factory=ASRSettings)
    ocr: OCRSettings = Field(default_factory=OCRSettings)
    pipeline: PipelineSettings = Field(default_factory=PipelineSettings)
    tts: TTSSettings = Field(default_factory=TTSSettings)
    audio: AudioSettings = Field(default_factory=AudioSettings)
    concepts: ConceptsSettings = Field(default_factory=ConceptsSettings)
    elicit: ElicitSettings = Field(default_factory=ElicitSettings)
    qa: QASettings = Field(default_factory=QASettings)
    quiz: QuizSettings = Field(default_factory=QuizSettings)
    suggest: SuggestSettings = Field(default_factory=SuggestSettings)
    trash: TrashSettings = Field(default_factory=TrashSettings)
    evaluation: EvaluationSettings = Field(default_factory=EvaluationSettings)


def default_config_path() -> Path:
    return Path(platformdirs.user_config_dir(APP_NAME, appauthor=False)) / "config.toml"


def config_file_path(explicit: str | Path | None = None) -> Path:
    """The settings file in use: an explicit path, else GROUNDCAST_CONFIG, else the per-user file."""
    return Path(explicit or os.environ.get(CONFIG_ENV) or default_config_path())


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
