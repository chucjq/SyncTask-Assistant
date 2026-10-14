from __future__ import annotations

from typing import Any


def emulator_firestore_client(project_id: str) -> Any:
    from google.auth.credentials import AnonymousCredentials
    from google.cloud import firestore

    return firestore.Client(project=project_id, credentials=AnonymousCredentials())


def get_or_init_app(name: str, project_id: str) -> Any:
    import firebase_admin

    try:
        return firebase_admin.get_app(name)
    except ValueError:
        return firebase_admin.initialize_app(options={"projectId": project_id}, name=name)
