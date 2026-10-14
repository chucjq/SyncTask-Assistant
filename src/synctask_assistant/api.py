from __future__ import annotations

import logging
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .anchors import current_anchors
from .answer import answer
from .config import Settings, load_model_settings, load_settings
from .context import ExecutionError, build_context
from .model import Chat, ModelError, OllamaChat
from .schema import load_schema
from .startup import StartupError, check_startup

log = logging.getLogger("synctask_assistant")
MAX_QUESTION_CHARS = 500
AUTH_FAILED = "Authentication required: send a valid Firebase ID token."
MODEL_UNAVAILABLE = "The assistant is unavailable right now. Try again in a moment."
DATABASE_UNAVAILABLE = "The database could not answer right now. Try again in a moment."
BEARER = {"WWW-Authenticate": "Bearer"}

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class AuthFailed(Exception):
    """The token is missing, malformed, expired, revoked or invalid."""


class Unavailable(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class Services:
    verify: Callable[[str], str]
    db: Any
    chat: Chat
    settings: Settings
    schema: dict[str, Any]


def create_app(services: Services) -> FastAPI:
    app = FastAPI(title="SyncTask assistant", docs_url=None, redoc_url=None, openapi_url=None)
    if services.settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(services.settings.cors_origins),
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type"],
            allow_credentials=False,
        )

    @app.exception_handler(Unavailable)
    async def unavailable(_: Request, error: Unavailable) -> JSONResponse:
        return JSONResponse({"status": "unavailable", "message": error.message}, status_code=503)

    @app.get("/health")
    def health() -> dict[str, Any]:
        model = services.settings.model
        return {
            "status": "ok",
            "model": model.model if model else None,
            "think": "off" if model and model.think is False else "model default",
            "answer_tokens": services.settings.answer_tokens,
        }

    @app.post("/ask")
    async def ask(request: Request) -> JSONResponse:
        uid = _authenticate(services, request.headers)
        question = _question_from(await _json(request))
        result = await run_in_threadpool(_answer_question, services, uid, question)
        return JSONResponse(result)

    return app


def _authenticate(services: Services, headers: Mapping[str, str]) -> str:
    scheme, _, token = headers.get("authorization", "").partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(401, AUTH_FAILED, headers=BEARER)
    try:
        uid = services.verify(token)
    except AuthFailed:
        raise HTTPException(401, AUTH_FAILED, headers=BEARER) from None
    except Exception:
        log.exception("token verification failed unexpectedly")
        raise HTTPException(401, AUTH_FAILED, headers=BEARER) from None
    if not uid:
        raise HTTPException(401, AUTH_FAILED, headers=BEARER)
    return uid


async def _json(request: Request) -> Any:
    try:
        return await request.json()
    except ValueError:
        raise HTTPException(422, "The body must be JSON with a question.") from None


def _question_from(body: Any) -> str:
    if not isinstance(body, dict):
        raise HTTPException(422, "The body must be a JSON object with a question.")
    question = body.get("question")
    if not isinstance(question, str):
        raise HTTPException(422, "question must be text.")
    question = question.strip()
    if not 1 <= len(question) <= MAX_QUESTION_CHARS:
        raise HTTPException(422, f"question must be 1 to {MAX_QUESTION_CHARS} characters.")
    return question


def _answer_question(services: Services, uid: str, question: str) -> dict[str, Any]:
    settings = services.settings
    anchors = current_anchors(settings.timezone, settings.week_start)
    try:
        context = build_context(
            services.db,
            uid,
            services.schema,
            anchors.today,
            settings.context_tasks,
            settings.context_chars,
        )
    except ExecutionError:
        raise Unavailable(DATABASE_UNAVAILABLE) from None
    try:
        text = answer(question, context.text, services.chat, services.settings.answer_tokens)
    except ModelError:
        raise Unavailable(MODEL_UNAVAILABLE) from None
    return {
        "status": "ok",
        "answer": text,
        "scope": {
            "projects": context.projects,
            "tasks": context.tasks_total,
            "tasks_listed": context.tasks_listed,
            "truncated": context.truncated,
        },
    }


def firebase_verifier(app: Any) -> Callable[[str], str]:
    from firebase_admin import auth

    def verify(token: str) -> str:
        try:
            decoded = auth.verify_id_token(token, app=app)
        except (
            auth.ExpiredIdTokenError,
            auth.RevokedIdTokenError,
            auth.InvalidIdTokenError,
            auth.CertificateFetchError,
            ValueError,
        ) as error:
            raise AuthFailed(type(error).__name__) from error
        return str(decoded.get("uid", ""))

    return verify


def build_services(env: Mapping[str, str] | None = None) -> Services:
    from firebase_admin import firestore

    from .firebase_apps import emulator_firestore_client, get_or_init_app

    env = os.environ if env is None else env
    environment = check_startup(env)
    settings = load_settings(env)
    app = get_or_init_app("synctask-assistant-api", environment.project_id)
    db = (
        emulator_firestore_client(environment.project_id)
        if environment.emulator
        else firestore.client(app=app)
    )
    return Services(
        verify=firebase_verifier(app),
        db=db,
        chat=OllamaChat(load_model_settings(env)),
        settings=settings,
        schema=load_schema(),
    )


def load_environment_file(path: Path = ENV_FILE) -> None:
    load_dotenv(path)


def create_default_app() -> FastAPI:
    load_environment_file()
    return create_app(build_services())


def server_address(env: Mapping[str, str] | None = None) -> tuple[str, int]:
    env = os.environ if env is None else env
    host = env.get("HOST", "").strip() or "127.0.0.1"
    raw_port = env.get("PORT", "").strip() or "8000"
    try:
        port = int(raw_port)
    except ValueError as error:
        raise StartupError(f"PORT must be a whole number, got {raw_port!r}.") from error
    if not 1 <= port <= 65535:
        raise StartupError(f"PORT must be between 1 and 65535, got {port}.")
    return host, port


def main() -> int:
    import uvicorn

    try:
        app = create_default_app()
        host, port = server_address()
    except StartupError as error:
        print(error)
        return 1
    uvicorn.run(app, host=host, port=port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
