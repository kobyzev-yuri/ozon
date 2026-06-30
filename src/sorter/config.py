"""Загрузка config.env (паттерн scinikel / 3dtoday)."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG_ENV = ROOT / "config.env"
DOT_ENV = ROOT / ".env"


def load_env_files() -> None:
    """Подгружает config.env и .env в os.environ (не перезаписывает уже заданные)."""
    for path in (CONFIG_ENV, DOT_ENV):
        if path.is_file():
            _load_file(path)


def _load_file(path: Path) -> None:
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def gemini_api_key() -> str | None:
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("OPENAI_API_KEY")


def gemini_base_url() -> str:
    return os.environ.get("GEMINI_BASE_URL", "https://api.proxyapi.ru/google").rstrip("/")


def gemini_model() -> str:
    return os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
