from pathlib import Path

import pytest
from pydantic import ValidationError

from groundcast.config import Settings, load_settings

EXAMPLE = Path(__file__).resolve().parent.parent / "config" / "groundcast.example.toml"


def test_defaults_without_file(tmp_path: Path) -> None:
    s = load_settings(tmp_path / "missing.toml", environ={})
    assert s.server.host == "127.0.0.1"
    assert s.llm.backend == "claude-cli"
    assert s.llm.writer_model != s.llm.verifier_model


def test_toml_then_env_override(tmp_path: Path) -> None:
    config = tmp_path / "c.toml"
    config.write_text("[llm]\nwriter_model = 'sonnet'\nverifier_model = 'haiku'\n[tts]\nspeed = 1.1\n")
    env = {"GROUNDCAST_LLM_VERIFIER_MODEL": "opus", "GROUNDCAST_DATA_DIR": str(tmp_path / "d")}
    s = load_settings(config, environ=env)
    assert s.llm.writer_model == "sonnet"
    assert s.llm.verifier_model == "opus"
    assert s.tts.speed == 1.1
    assert s.data_dir == tmp_path / "d"


def test_config_env_var_must_exist(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_settings(environ={"GROUNDCAST_CONFIG": str(tmp_path / "nope.toml")})


def test_non_loopback_host_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        load_settings(tmp_path / "x.toml", environ={"GROUNDCAST_SERVER_HOST": "0.0.0.0"})


def test_unknown_key_rejected(tmp_path: Path) -> None:
    config = tmp_path / "c.toml"
    config.write_text("[llm]\nwritter_model = 'typo'\n")
    with pytest.raises(ValidationError):
        load_settings(config, environ={})


def test_example_config_lists_the_defaults() -> None:
    example = load_settings(EXAMPLE, environ={})
    dirs = {"data_dir", "model_dir"}
    assert example.model_dump(exclude=dirs) == Settings().model_dump(exclude=dirs)


def test_eval_set_found_outside_the_repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from groundcast.cli import _default_eval_set

    monkeypatch.chdir(tmp_path)
    assert _default_eval_set() == EXAMPLE.parent.parent / "evals" / "seeded" / "items.json"
