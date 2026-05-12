from __future__ import annotations

import json
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
    TABLE = "table"
    JSON = "json"


@click.group()
def get() -> None:
    pass


@get.command()
@click.option("--all", "show_all", is_flag=True, help="Include superseded specs")
@click.option("--output", "output_format", type=click.Choice(["json"]), default=None)
@click.pass_obj
def specs(store: PlanStore, show_all: bool, output_format: str | None) -> None:
    plan = store.get_plan()
    spec_plans = plan.spec_plans
    if not show_all:
        spec_plans = [sp for sp in spec_plans if not sp.superseded]

    if output_format == OutputFormat.JSON:
        data = [_spec_plan_to_dict(sp) for sp in spec_plans]
        click.echo(json.dumps(data, indent=2, default=str))
        return

    headers = ["PATH", "BLOB SHA", "STATUS", "TASKS"]
    rows = [_spec_plan_to_row(sp) for sp in spec_plans]
    click.echo(format_table(headers, rows), nl=False)


def _completed_count(sp: SpecPlan) -> int:
    return sum(1 for t in sp.tasks if t.status == TaskStatus.COMPLETE)


def _spec_display_status(sp: SpecPlan) -> str:
    if sp.superseded:
        return "Superseded"
    return sp.status.value


def _spec_plan_to_row(sp: SpecPlan) -> list[str]:
    completed = _completed_count(sp)
    total = len(sp.tasks)
    return [
        sp.path,
        sp.blob_sha,
        _spec_display_status(sp),
        f"{completed}/{total}",
    ]


def _spec_plan_to_dict(sp: SpecPlan) -> dict[str, object]:
    return {
        "path": sp.path,
        "blob_sha": sp.blob_sha,
        "status": _spec_display_status(sp),
        "superseded": sp.superseded,
        "tasks": [_task_to_dict(t) for t in sp.tasks],
    }


@get.command()
@click.option("--spec", "spec_filter", default=None, help="Filter by spec path")
@click.option("--output", "output_format", type=click.Choice(["json"]), default=None)
@click.pass_obj
def tasks(store: PlanStore, spec_filter: str | None, output_format: str | None) -> None:
    plan = store.get_plan()
    all_tasks = _collect_tasks(plan, spec_filter)

    if output_format == OutputFormat.JSON:
        data = [_task_to_dict(t) for t in all_tasks]
        click.echo(json.dumps(data, indent=2, default=str))
        return

    headers = ["ID", "NAME", "SPEC", "STATUS"]
    rows = [_task_to_row(t) for t in all_tasks]
    click.echo(format_table(headers, rows), nl=False)


def _collect_tasks(plan: Plan, spec_filter: str | None) -> list[Task]:
    result: list[Task] = []
    for sp in plan.spec_plans:
        if spec_filter and sp.path != spec_filter:
            continue
        result.extend(sp.tasks)
    return result


def _task_to_row(task: Task) -> list[str]:
    return [
        str(task.id),
        task.name,
        task.spec_path,
        task.status.value,
    ]


def _task_to_dict(task: Task) -> dict[str, object]:
    return {
        "id": task.id,
        "name": task.name,
        "spec_path": task.spec_path,
        "spec_blob_sha": task.spec_blob_sha,
        "status": task.status.value,
        "depends_on": task.depends_on,
    }


@get.command()
@click.option("--output", "output_format", type=click.Choice(["json"]), default=None)
@click.pass_obj
def events(store: PlanStore, output_format: str | None) -> None:
    plan = store.get_plan()
    collected = _collect_all_events(plan)
    collected.sort(key=lambda e: e[1].last_timestamp, reverse=True)

    if output_format == OutputFormat.JSON:
        data = [_event_to_dict(obj_ref, event) for obj_ref, event in collected]
        click.echo(json.dumps(data, indent=2, default=str))
        return

    headers = ["LAST SEEN", "TYPE", "REASON", "OBJECT", "MESSAGE"]
    rows = [_event_to_row(obj_ref, event) for obj_ref, event in collected]
    click.echo(format_table(headers, rows), nl=False)


def _collect_all_events(plan: Plan) -> list[tuple[str, Event]]:
    result: list[tuple[str, Event]] = []
    for event in plan.events:
        result.append(("plan", event))
    for sp in plan.spec_plans:
        obj_ref = f"spec/{sp.path}"
        for event in sp.events:
            result.append((obj_ref, event))
        for task in sp.tasks:
            task_ref = f"task/{task.id}"
            for event in task.events:
                result.append((task_ref, event))
    return result


def _event_to_row(obj_ref: str, event: Event) -> list[str]:
    return [
        format_relative_time(event.last_timestamp),
        event.type.value,
        event.reason,
        obj_ref,
        event.message,
    ]


def _event_to_dict(obj_ref: str, event: Event) -> dict[str, object]:
    return {
        "type": event.type.value,
        "reason": event.reason,
        "count": event.count,
        "first_timestamp": event.first_timestamp.isoformat(),
        "last_timestamp": event.last_timestamp.isoformat(),
        "object": obj_ref,
        "message": event.message,
    }
