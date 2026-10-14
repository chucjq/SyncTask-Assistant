"""Settings read from the environment (dates in 5.1, model in 6.1)."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, tzinfo
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .startup import StartupError

TIMEZONE_VAR = "ASSISTANT_TIMEZONE"
WEEK_START_VAR = "ASSISTANT_WEEK_START"
DEFAULT_TIMEZONE = "UTC"
WEEK_STARTS = {"monday": 0, "sunday": 6}

CONTEXT_TASKS_VAR = "ASSISTANT_CONTEXT_TASKS"
CONTEXT_CHARS_VAR = "ASSISTANT_CONTEXT_CHARS"
DEFAULT_CONTEXT_TASKS = 150
DEFAULT_CONTEXT_CHARS = 24000

MODEL_VAR = "ASSISTANT_MODEL"
OLLAMA_HOST_VAR = "OLLAMA_HOST"
TEMPERATURE_VAR = "ASSISTANT_TEMPERATURE"
TOP_P_VAR = "ASSISTANT_TOP_P"
TIMEOUT_VAR = "ASSISTANT_MODEL_TIMEOUT"
NUM_CTX_VAR = "ASSISTANT_NUM_CTX"
THINK_VAR = "ASSISTANT_THINK"
ANSWER_TOKENS_VAR = "ASSISTANT_ANSWER_TOKENS"
CORS_ORIGINS_VAR = "CORS_ORIGINS"
DEFAULT_MODEL = "gemma4:e2b"
DEFAULT_HOST = "http://127.0.0.1:11434"
DEFAULT_TEMPERATURE = 0.2
DEFAULT_TIMEOUT = 60.0
DEFAULT_NUM_CTX = 16384
DEFAULT_ANSWER_TOKENS = 2048


@dataclass(frozen=True)
class ModelSettings:
    model: str
    host: str
    temperature: float
    top_p: float | None
    timeout: float
    num_ctx: int | None = None
    think: bool | None = None


@dataclass(frozen=True)
class Settings:
    timezone: tzinfo
    week_start: int
    model: ModelSettings | None
    context_tasks: int = DEFAULT_CONTEXT_TASKS
    context_chars: int = DEFAULT_CONTEXT_CHARS
    answer_tokens: int = DEFAULT_ANSWER_TOKENS
    cors_origins: tuple[str, ...] = ()


def _named_zone(zone_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(zone_name)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise StartupError(
            f"{TIMEZONE_VAR}={zone_name!r} is not an IANA time zone (for example Europe/Berlin). "
            "On Windows the tzdata package must be installed (pip install -e .)."
        ) from error


def _origins(env: Mapping[str, str]) -> tuple[str, ...]:
    origins = []
    for item in env.get(CORS_ORIGINS_VAR, "").split(","):
        origin = item.strip().rstrip("/")
        if not origin:
            continue
        if origin == "*":
            raise StartupError(f"{CORS_ORIGINS_VAR} must list exact origins, not '*'.")
        parts = urlsplit(origin)
        if parts.scheme not in ("http", "https") or not parts.netloc or parts.path:
            raise StartupError(
                f"each {CORS_ORIGINS_VAR} entry must look like http://localhost:8081, "
                f"got {origin!r}."
            )
        origins.append(origin)
    return tuple(origins)


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if env is None else env
    zone_name = env.get(TIMEZONE_VAR, "").strip() or DEFAULT_TIMEZONE
    zone: tzinfo = UTC if zone_name.upper() == "UTC" else _named_zone(zone_name)
    week = env.get(WEEK_START_VAR, "").strip().lower() or "monday"
    if week not in WEEK_STARTS:
        raise StartupError(f"{WEEK_START_VAR} must be monday or sunday, got {week!r}.")
    return Settings(
        timezone=zone,
        week_start=WEEK_STARTS[week],
        model=load_model_settings(env),
        context_tasks=_integer(env, CONTEXT_TASKS_VAR, DEFAULT_CONTEXT_TASKS, 1, 2000),
        context_chars=_integer(env, CONTEXT_CHARS_VAR, DEFAULT_CONTEXT_CHARS, 2000, 200000),
        answer_tokens=_integer(env, ANSWER_TOKENS_VAR, DEFAULT_ANSWER_TOKENS, 128, 8192),
        cors_origins=_origins(env),
    )


def _number(
    env: Mapping[str, str], name: str, default: float | None, low: float, high: float
) -> float | None:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as error:
        raise StartupError(f"{name} must be a number, got {raw!r}.") from error
    if not low <= value <= high:
        raise StartupError(f"{name} must be between {low} and {high}, got {value}.")
    return value


def _integer(env: Mapping[str, str], name: str, default: int, low: int, high: int) -> int:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as error:
        raise StartupError(f"{name} must be a whole number, got {raw!r}.") from error
    if not low <= value <= high:
        raise StartupError(f"{name} must be between {low} and {high}, got {value}.")
    return value


def _think(env: Mapping[str, str]) -> bool | None:
    raw = env.get(THINK_VAR, "").strip().lower()
    if raw in ("", "on", "true", "1"):
        return None
    if raw in ("off", "false", "0"):
        return False
    raise StartupError(f"{THINK_VAR} must be on or off, got {raw!r}.")


def load_model_settings(env: Mapping[str, str]) -> ModelSettings:
    model = env.get(MODEL_VAR, "").strip() or DEFAULT_MODEL
    host = env.get(OLLAMA_HOST_VAR, "").strip() or DEFAULT_HOST
    if not host.startswith(("http://", "https://")):
        raise StartupError(f"{OLLAMA_HOST_VAR} must start with http:// or https://.")
    temperature = _number(env, TEMPERATURE_VAR, DEFAULT_TEMPERATURE, 0.0, 2.0)
    top_p = _number(env, TOP_P_VAR, None, 0.0, 1.0)
    timeout = _number(env, TIMEOUT_VAR, DEFAULT_TIMEOUT, 1.0, 600.0)
    num_ctx = _integer(env, NUM_CTX_VAR, DEFAULT_NUM_CTX, 2048, 262144)
    return ModelSettings(
        model,
        host,
        DEFAULT_TEMPERATURE if temperature is None else temperature,
        top_p,
        DEFAULT_TIMEOUT if timeout is None else timeout,
        num_ctx,
        _think(env),
    )
