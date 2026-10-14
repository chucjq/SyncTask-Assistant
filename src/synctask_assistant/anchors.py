from __future__ import annotations

import calendar
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo

Clock = Callable[[], datetime]


@dataclass(frozen=True)
class Span:
    start: date
    end: date


@dataclass(frozen=True)
class DateAnchors:
    today: date
    yesterday: date
    tomorrow: date
    this_week: Span
    last_week: Span
    this_month: Span
    last_month: Span
    this_year: Span
    last_year: Span


def _month(year: int, month: int) -> Span:
    return Span(date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1]))


def anchors_for(today: date, week_start: int = 0) -> DateAnchors:
    this_week_start = today - timedelta(days=(today.weekday() - week_start) % 7)
    previous_month = (
        _month(today.year - 1, 12) if today.month == 1 else _month(today.year, today.month - 1)
    )
    return DateAnchors(
        today=today,
        yesterday=today - timedelta(days=1),
        tomorrow=today + timedelta(days=1),
        this_week=Span(this_week_start, this_week_start + timedelta(days=6)),
        last_week=Span(this_week_start - timedelta(days=7), this_week_start - timedelta(days=1)),
        this_month=_month(today.year, today.month),
        last_month=previous_month,
        this_year=Span(date(today.year, 1, 1), date(today.year, 12, 31)),
        last_year=Span(date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)),
    )


def current_anchors(zone: tzinfo, week_start: int = 0, clock: Clock | None = None) -> DateAnchors:
    now = clock() if clock else datetime.now(zone)
    return anchors_for(now.astimezone(zone).date(), week_start)


def phrases(anchors: DateAnchors) -> dict[str, tuple[date, ...]]:
    return {
        "today": (anchors.today,),
        "yesterday": (anchors.yesterday,),
        "tomorrow": (anchors.tomorrow,),
        "this week": (anchors.this_week.start, anchors.this_week.end),
        "last week": (anchors.last_week.start, anchors.last_week.end),
        "this month": (anchors.this_month.start, anchors.this_month.end),
        "last month": (anchors.last_month.start, anchors.last_month.end),
        "this year": (anchors.this_year.start, anchors.this_year.end),
        "last year": (anchors.last_year.start, anchors.last_year.end),
    }


def render(anchors: DateAnchors) -> str:
    lines = [f"- today: {anchors.today} ({anchors.today:%A})"]
    for name, dates in phrases(anchors).items():
        if name == "today":
            continue
        shown = str(dates[0]) if len(dates) == 1 else f"{dates[0]} to {dates[1]}"
        lines.append(f"- {name}: {shown}")
    return "\n".join(lines)
