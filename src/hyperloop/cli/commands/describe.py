from __future__ import annotations

import json
import sys
from collections import Counter
from enum import StrEnum

import click

from hyperloop.cli.formatters.table import format_table
from hyperloop.cli.formatters.time import format_relative_time
from hyperloop.reconciliation.models.event import Event
from hyperloop.reconciliation.models.plan import Plan
from hyperloop.reconciliation.models.spec_plan import SpecPlan
from hyperloop.reconciliation.models.task import Task, TaskStatus
from hyperloop.reconciliation.ports.plan_store import PlanStore


class OutputFormat(StrEnum):
    JSON = "json"


@click.group()
def describe() -> None:
    pass


@describe.command()
@click.argument("path")
@click.option("--output", "output_format", type=click.Choice(["json"]), default=None)
@click.pass_obj
def spec(store: PlanStore, path: str, output_format: str | None) -> None:
    plan = store.get_plan()
    target = _find_spec(plan, path)
    if target is None:
        click.echo(f"spec {path} not found", err=True)
        sys.exit(1)

    if output_format == OutputFormat.JSON:
        click.echo(json.dumps(_spec_to_full_dict(target), indent=2, default=str))
        return

    _render_spec(target)


@describe.command()
@click.argument("task_id", type=int)
@click.option("--output", "output_format", type=click.Choice(["json"]), default=None)
@click.pass_obj
def task(store: PlanStore, task_id: int, output_format: str | None) -> None:
    plan = store.get_plan()
    target = _find_task(plan, task_id)
    if target is None:
        click.echo(f"task {task_id} not found", err=True)
        sys.exit(1)

    if output_format == OutputFormat.JSON:
        click.echo(json.dumps(_task_to_full_dict(target), indent=2, default=str))
        return

    _render_task(target)


def _find_spec(plan: Plan, path: str) -> SpecPlan | None:
    for sp in plan.spec_plans:
        if sp.path == path and not sp.superseded:
            return sp
    return None


def _find_task(plan: Plan, task_id: int) -> Task | None:
    for sp in plan.spec_plans:
        for t in sp.tasks:
            if t.id == task_id:
                return t
    return None


def _render_spec(sp: SpecPlan) -> None:
    click.echo(f"Name:           {sp.path}")
    click.echo(f"Blob SHA:       {sp.blob_sha}")
    click.echo(f"Status:         {sp.status.value}")
    click.echo(f"Superseded:     {str(sp.superseded).lower()}")
    click.echo(f"Attempts:       {sp.reconciliation_attempts}")
    click.echo(f"Redecomposed:   {str(sp.has_redecomposed).lower()}")

    status_counts: Counter[TaskStatus] = Counter()
    for t in sp.tasks:
        status_counts[t.status] += 1
    total = len(sp.tasks)
    summary_parts = [
        f"{count} {status.value}" for status, count in status_counts.items()
    ]
    summary = ", ".join(summary_parts) + f" ({total} total)"
    click.echo(f"Tasks:          {summary}")
    click.echo()

    click.echo("Tasks:")
    headers = ["ID", "NAME", "STATUS", "RETRIES"]
    rows = [[str(t.id), t.name, t.status.value, str(len(t.events))] for t in sp.tasks]
    click.echo(_indent(format_table(headers, rows)), nl=False)
    click.echo()

    _render_events(sp.events)


def _render_task(t: Task) -> None:
    click.echo(f"ID:             {t.id}")
    click.echo(f"Name:           {t.name}")
    click.echo(f"Spec:           {t.spec_path}")
    click.echo(f"Blob SHA:       {t.spec_blob_sha}")
    click.echo(f"Status:         {t.status.value}")
    click.echo(f"Dependencies:   {t.depends_on}")
    click.echo()

    _render_events(t.events)


def _render_events(events: list[Event]) -> None:
    if not events:
        return
    click.echo("Events:")
    headers = ["Type", "Reason", "Count", "First Seen", "Last Seen", "Message"]
    rows = [
        [
            event.type.value,
            event.reason,
            str(event.count),
            format_relative_time(event.first_timestamp),
            format_relative_time(event.last_timestamp),
            event.message,
        ]
        for event in events
    ]
    click.echo(_indent(format_table(headers, rows)), nl=False)


def _indent(text: str, spaces: int = 2) -> str:
    prefix = " " * spaces
    return "\n".join(prefix + line for line in text.split("\n"))


def _spec_to_full_dict(sp: SpecPlan) -> dict[str, object]:
    return {
        "path": sp.path,
        "blob_sha": sp.blob_sha,
        "status": sp.status.value,
        "superseded": sp.superseded,
        "reconciliation_attempts": sp.reconciliation_attempts,
        "has_redecomposed": sp.has_redecomposed,
        "tasks": [_task_to_full_dict(t) for t in sp.tasks],
        "events": [_event_to_dict(e) for e in sp.events],
    }


def _task_to_full_dict(t: Task) -> dict[str, object]:
    return {
        "id": t.id,
        "name": t.name,
        "spec_path": t.spec_path,
        "spec_blob_sha": t.spec_blob_sha,
        "status": t.status.value,
        "depends_on": t.depends_on,
        "events": [_event_to_dict(e) for e in t.events],
    }


def _event_to_dict(event: Event) -> dict[str, object]:
    return {
        "type": event.type.value,
        "reason": event.reason,
        "count": event.count,
        "first_timestamp": event.first_timestamp.isoformat(),
        "last_timestamp": event.last_timestamp.isoformat(),
        "message": event.message,
    }
