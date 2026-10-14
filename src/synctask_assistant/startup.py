from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass

from dotenv import load_dotenv

FIRESTORE_EMULATOR_VAR = "FIRESTORE_EMULATOR_HOST"
AUTH_EMULATOR_VAR = "FIREBASE_AUTH_EMULATOR_HOST"
PROJECT_ID_VAR = "FIREBASE_PROJECT_ID"
DEFAULT_EMULATOR_PROJECT_ID = "demo-synctask-assistant"


class StartupError(RuntimeError):
    """Raised when the environment is not safe to start in."""


@dataclass(frozen=True)
class Environment:
    emulator: bool
    project_id: str


def _get(env: Mapping[str, str], name: str) -> str:
    return env.get(name, "").strip()


def check_startup(env: Mapping[str, str] | None = None) -> Environment:
    env = os.environ if env is None else env
    project_id = _get(env, PROJECT_ID_VAR)

    if _get(env, FIRESTORE_EMULATOR_VAR):
        return Environment(emulator=True, project_id=project_id or DEFAULT_EMULATOR_PROJECT_ID)

    if not project_id:
        raise StartupError(
            f"Refusing to start: {FIRESTORE_EMULATOR_VAR} is not set, so this would target a "
            f"non-emulator project, and {PROJECT_ID_VAR} is not set. Start the emulators and set "
            f"{FIRESTORE_EMULATOR_VAR} (see .env.example), or set {PROJECT_ID_VAR} explicitly."
        )
    return Environment(emulator=False, project_id=project_id)


def main() -> int:
    load_dotenv()
    try:
        result = check_startup()
    except StartupError as error:
        print(error, file=sys.stderr)
        return 1
    mode = "emulator" if result.emulator else "NON-EMULATOR (explicit project id)"
    print(f"OK: {mode}, project id {result.project_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
