from argparse import Namespace
from pathlib import Path

import installer


def test_write_env_preserves_custom_embedding_configuration(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = {
        "db_backend": "sqlite",
        "openai_key": "lm-studio",
        "embedding_base_url": "http://127.0.0.1:1234/v1",
        "embedding_model": "google/embedding-gemma-300m",
        "embedding_dimensions": 768,
        "host": "127.0.0.1",
        "port": "8377",
        "project": "main",
        "llm_base_url": "",
        "llm_model": "",
        "llm_api_key": "",
    }

    installer.write_env(cfg, "opaque-test-token")
    values = dict(
        line.split("=", 1)
        for line in Path(".env").read_text().splitlines()
        if line
    )

    assert values["OPENAI_API_BASE"] == "http://127.0.0.1:1234/v1"
    assert values["ZIKRA_EMBEDDING_MODEL"] == "google/embedding-gemma-300m"
    assert values["ZIKRA_EMBEDDING_DIMENSIONS"] == "768"
    assert Path(".env").stat().st_mode & 0o777 == 0o600


def test_postgres_default_embedding_model_matches_default_dimensions(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = {
        "db_backend": "postgres",
        "openai_key": "test-key",
        "embedding_base_url": "",
        "embedding_model": "",
        "embedding_dimensions": 1536,
        "host": "127.0.0.1",
        "port": "8377",
        "project": "main",
        "llm_base_url": "",
        "llm_model": "",
        "llm_api_key": "",
        "pg_host": "localhost",
        "pg_port": "5432",
        "pg_name": "zikra",
        "pg_user": "zikra",
        "pg_password": "test-password",
    }

    installer.write_env(cfg, "opaque-test-token")
    values = dict(line.split("=", 1) for line in Path(".env").read_text().splitlines() if line)
    assert values["ZIKRA_EMBEDDING_MODEL"] == "text-embedding-3-small"
    assert values["ZIKRA_EMBEDDING_DIMENSIONS"] == "1536"


def test_interactive_gather_preserves_embedding_flags(monkeypatch):
    answers = iter(["1", "1", "sk-testkey", "", "", "main", "127.0.0.1", "8377", "1"])
    monkeypatch.setattr(installer, "_ask", lambda *args, **kwargs: next(answers))
    choices = iter(["1", "1", "1"])
    monkeypatch.setattr(installer, "_ask_choice", lambda *args, **kwargs: next(choices))
    monkeypatch.setattr(installer.shutil, "which", lambda _name: None)
    args = Namespace(
        embedding_base_url="http://127.0.0.1:1234/v1",
        embedding_model="local-embedding",
        embedding_dimensions=768,
        with_gemini=False,
    )

    cfg = installer.gather_interactive(args)
    assert cfg["embedding_base_url"] == "http://127.0.0.1:1234/v1"
    assert cfg["embedding_model"] == "local-embedding"
    assert cfg["embedding_dimensions"] == 768
