from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import date
from typing import Any

from google.api_core import exceptions as api_errors
from google.cloud.firestore_v1.base_query import FieldFilter

STATUSES = ("todo", "in_progress", "blocked", "completed")
PROJECT_FIELDS = ["name", "deadline", "members", "memberIds"]
TITLE_CHARS = 120
DESCRIPTION_CHARS = 160
NAME_CHARS = 60
LISTING_HEADER_CHARS = 200
NO_DEADLINE = "9999-12-31"
DATABASE_MESSAGE = "The database could not read the project data right now."


class ExecutionError(RuntimeError):
    """The database could not be reached or failed. The message is safe to show."""


@dataclass(frozen=True)
class Context:
    text: str
    projects: int
    tasks_total: int
    tasks_listed: int

    @property
    def truncated(self) -> bool:
        return self.tasks_listed < self.tasks_total


def _clean(value: Any, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value if value is not None else "")).strip()
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _returned(schema: dict[str, Any], collection: str) -> list[str]:
    fields = schema["collections"][collection]["fields"]
    return [name for name, field in fields.items() if field.get("returned") and name != "id"]


def load_member_projects(db: Any, user_id: str) -> list[tuple[str, dict[str, Any]]]:
    try:
        query = (
            db.collection("projects")
            .where(filter=FieldFilter("memberIds", "array_contains", user_id))
            .select(PROJECT_FIELDS)
        )
        found = []
        for snapshot in query.stream():
            doc = snapshot.to_dict() or {}
            if user_id in (doc.get("memberIds") or []):
                found.append((snapshot.id, doc))
    except api_errors.GoogleAPICallError as error:
        raise ExecutionError(DATABASE_MESSAGE) from error
    return sorted(found, key=lambda item: item[0])


def load_tasks(db: Any, project_id: str, fields: list[str]) -> list[dict[str, Any]]:
    try:
        tasks = db.collection("projects").document(project_id).collection("tasks")
        rows = []
        for snapshot in tasks.select(fields).stream():
            rows.append({**(snapshot.to_dict() or {}), "id": snapshot.id, "projectId": project_id})
    except api_errors.GoogleAPICallError as error:
        raise ExecutionError(DATABASE_MESSAGE) from error
    return rows


def _members(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    members = doc.get("members")
    if not isinstance(members, dict):
        return {}
    return {uid: info for uid, info in members.items() if isinstance(info, dict)}


def _user_name(projects: list[tuple[str, dict[str, Any]]], user_id: str) -> str:
    for _, doc in projects:
        info = _members(doc).get(user_id)
        if info is not None and _clean(info.get("name"), NAME_CHARS):
            return _clean(info.get("name"), NAME_CHARS)
    return "the user"


def _person(task: dict[str, Any], members: dict[str, dict[str, Any]]) -> str:
    assignee = task.get("assignedTo")
    if not assignee:
        return "unassigned"
    info = members.get(assignee)
    if info is None:
        return "unknown member"
    return _clean(info.get("name"), NAME_CHARS) or "unnamed member"


def _assignment(task: dict[str, Any], members: dict[str, dict[str, Any]], user_id: str) -> str:
    if not task.get("assignedTo"):
        return "unassigned"
    if task.get("assignedTo") == user_id:
        return "assigned to you"
    return f"assigned to {_person(task, members)}"


def _is_open(task: dict[str, Any]) -> bool:
    return task.get("status") != "completed"


def _is_overdue(task: dict[str, Any], today_iso: str) -> bool:
    deadline = task.get("deadline")
    return _is_open(task) and isinstance(deadline, str) and bool(deadline) and deadline < today_iso


def _project_summary(
    doc: dict[str, Any],
    tasks: list[dict[str, Any]],
    members: dict[str, dict[str, Any]],
    user_id: str,
    today_iso: str,
) -> str:
    name = _clean(doc.get("name"), NAME_CHARS) or "(unnamed)"
    deadline = _clean(doc.get("deadline"), 10) or "none"
    member_text = ", ".join(
        f"{_clean(info.get('name'), NAME_CHARS)} ({_clean(info.get('role'), 20)})"
        for info in members.values()
    ) or "none"
    counts = Counter(t.get("status") if t.get("status") in STATUSES else "other" for t in tasks)
    status_text = ", ".join(f"{s} {counts[s]}" for s in STATUSES)
    if counts["other"]:
        status_text += f", other {counts['other']}"
    overdue = sum(1 for t in tasks if _is_overdue(t, today_iso))
    open_by_person = Counter(_person(t, members) for t in tasks if _is_open(t))
    open_text = ", ".join(
        f"{person} {n}" for person, n in sorted(open_by_person.items(), key=lambda p: (-p[1], p[0]))
    ) or "none"
    mine = [t for t in tasks if t.get("assignedTo") == user_id]
    mine_open = sum(1 for t in mine if _is_open(t))
    mine_overdue = sum(1 for t in mine if _is_overdue(t, today_iso))
    return "\n".join(
        [
            f'PROJECT "{name}" | deadline {deadline} | members: {member_text}',
            f"  tasks: {len(tasks)} ({status_text}) | overdue: {overdue}",
            f"  open tasks per person: {open_text}",
            f"  the user's tasks: {len(mine)} ({mine_open} open, {len(mine) - mine_open} "
            f"completed, {mine_overdue} overdue)",
        ]
    )


def _task_line(
    project_name: str,
    members: dict[str, dict[str, Any]],
    titles: dict[str, str],
    task: dict[str, Any],
    user_id: str,
    today_iso: str,
) -> str:
    title = _clean(task.get("title"), TITLE_CHARS) or "(untitled)"
    status = task.get("status") if task.get("status") in STATUSES else "other"
    deadline = task.get("deadline") if isinstance(task.get("deadline"), str) else ""
    parts = [
        f'"{title}"',
        f'project "{project_name}"',
        f"status {status}",
        _assignment(task, members, user_id),
        f"due {deadline or 'no date'}" + (" OVERDUE" if _is_overdue(task, today_iso) else ""),
    ]
    if task.get("dependsOnTaskId"):
        target = titles.get(str(task["dependsOnTaskId"]))
        parts.append(f'depends on "{target}"' if target else "depends on an unknown task")
    checklist = task.get("checklist") if isinstance(task.get("checklist"), list) else []
    if checklist:
        done = sum(
            1 for item in checklist if isinstance(item, dict) and item.get("completed") is True
        )
        parts.append(f"checklist {done}/{len(checklist)} done")
    description = _clean(task.get("description"), DESCRIPTION_CHARS)
    if description:
        parts.append(f'description "{description}"')
    return "- " + " | ".join(parts)


def _listing_order(
    item: tuple[str, dict[str, Any], dict[str, str], dict[str, Any]],
) -> tuple[Any, ...]:
    _, _, _, task = item
    deadline = task.get("deadline") if isinstance(task.get("deadline"), str) else ""
    return (
        not _is_open(task),
        deadline or NO_DEADLINE,
        str(task.get("projectId")),
        str(task.get("id")),
    )


def build_context(
    db: Any,
    user_id: str,
    schema: dict[str, Any],
    today: date,
    max_tasks: int,
    max_chars: int,
) -> Context:
    """Assemble the data block for one question. Counts cover every task; the listing is capped."""
    today_iso = today.isoformat()
    projects = load_member_projects(db, user_id)
    fields = _returned(schema, "tasks")

    summaries: list[str] = []
    listing: list[tuple[str, dict[str, Any], dict[str, str], dict[str, Any]]] = []
    total = 0
    for _project_id, doc in projects:
        tasks = load_tasks(db, _project_id, fields)
        total += len(tasks)
        members = _members(doc)
        project_name = _clean(doc.get("name"), NAME_CHARS) or "(unnamed)"
        titles = {str(t["id"]): _clean(t.get("title"), TITLE_CHARS) for t in tasks}
        summaries.append(_project_summary(doc, tasks, members, user_id, today_iso))
        listing.extend((project_name, members, titles, task) for task in tasks)

    header = [
        f"Today is {today_iso} ({today:%A}).",
        f"The user is {_user_name(projects, user_id)}. Tasks assigned to the user are marked "
        '"assigned to you". "I", "me" and "my" refer to the user.',
        f"Projects the user is a member of: {len(projects)}. Tasks in those projects: {total}.",
    ]
    lines: list[str] = []
    if total:
        budget = max_chars - len("\n".join(header + summaries)) - LISTING_HEADER_CHARS
        for project_name, members, titles, task in sorted(listing, key=_listing_order):
            if len(lines) >= max_tasks:
                break
            line = _task_line(project_name, members, titles, task, user_id, today_iso)
            if len(line) + 1 > budget:
                break
            lines.append(line)
            budget -= len(line) + 1

    parts = header + summaries
    if total:
        parts.append(
            f"TASKS (listed {len(lines)} of {total}; open tasks first, earliest deadline first; "
            "the counts above cover all tasks)"
        )
        parts.extend(lines)
    return Context(
        text="\n".join(parts),
        projects=len(projects),
        tasks_total=total,
        tasks_listed=len(lines),
    )
