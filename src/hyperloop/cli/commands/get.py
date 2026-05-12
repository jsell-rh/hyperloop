from __future__ import annotations

import json
import shutil

import click

from hyperloop.cli.formatters.table import format_table
from hyperloop.cli.formatters.time import format_relative_time
from hyperloop.cli.output_format import OutputFormat
from hyperloop.cli.serializers import (
    completed_count,
    event_to_dict,
    spec_display_status,
    spec_plan_to_dict,
    task_to_dict,
)
from hyperloop.reconciliation.models.event import Event
from hyperloop.reconciliation.models.plan import Plan
from hyperloop.reconciliation.models.spec_plan import SpecPlan
from hyperloop.reconciliation.models.task import Task
from hyperloop.reconciliation.ports.plan_store import PlanStore


def _terminal_width() -> int:
    return shutil.get_terminal_size(fallback=(80, 24)).columns


@click.group()
def get() -> None:
    pass


@get.command()
@click.option("--all", "show_all", is_flag=True, help="Include superseded specs")
@click.option(
    "--output",
    "output_format",
    type=click.Choice([fmt.value for fmt in OutputFormat if fmt != OutputFormat.TABLE]),
    default=None,
)
@click.pass_obj
def specs(store: PlanStore, show_all: bool, output_format: str | None) -> None:
    plan = store.get_plan()
    spec_plans = plan.spec_plans
    if not show_all:
        spec_plans = [sp for sp in spec_plans if not sp.superseded]

    if output_format == OutputFormat.JSON:
        data = [spec_plan_to_dict(sp) for sp in spec_plans]
        click.echo(json.dumps(data, indent=2, default=str))
        return

    headers = ["PATH", "BLOB SHA", "STATUS", "TASKS", "AGE"]
    rows = [_spec_plan_to_row(sp) for sp in spec_plans]
    click.echo(format_table(headers, rows, max_width=_terminal_width()), nl=False)


def _spec_plan_to_row(sp: SpecPlan) -> list[str]:
    completed = completed_count(sp)
    total = len(sp.tasks)
    return [
        sp.path,
        sp.blob_sha,
        spec_display_status(sp),
        f"{completed}/{total}",
        format_relative_time(sp.created_at),
    ]


@get.command()
@click.option("--spec", "spec_filter", default=None, help="Filter by spec path")
@click.option(
    "--output",
    "output_format",
    type=click.Choice([fmt.value for fmt in OutputFormat if fmt != OutputFormat.TABLE]),
    default=None,
)
@click.pass_obj
def tasks(store: PlanStore, spec_filter: str | None, output_format: str | None) -> None:
    plan = store.get_plan()
    all_tasks = _collect_tasks(plan, spec_filter)

    if output_format == OutputFormat.JSON:
        data = [task_to_dict(t) for t in all_tasks]
        click.echo(json.dumps(data, indent=2, default=str))
        return

    headers = ["ID", "NAME", "SPEC", "STATUS", "RETRIES", "AGE"]
    rows = [_task_to_row(t) for t in all_tasks]
    click.echo(format_table(headers, rows, max_width=_terminal_width()), nl=False)


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
        str(task.retry_count),
        format_relative_time(task.created_at),
    ]


@get.command()
@click.option(
    "--output",
    "output_format",
    type=click.Choice([fmt.value for fmt in OutputFormat if fmt != OutputFormat.TABLE]),
    default=None,
)
@click.pass_obj
def events(store: PlanStore, output_format: str | None) -> None:
    plan = store.get_plan()
    collected = _collect_all_events(plan)
    collected.sort(key=lambda e: e[1].last_timestamp, reverse=True)

    if output_format == OutputFormat.JSON:
        data = [event_to_dict(event, obj_ref=obj_ref) for obj_ref, event in collected]
        click.echo(json.dumps(data, indent=2, default=str))
        return

    headers = ["LAST SEEN", "TYPE", "REASON", "OBJECT", "MESSAGE"]
    rows = [_event_to_row(obj_ref, event) for obj_ref, event in collected]
    click.echo(format_table(headers, rows, max_width=_terminal_width()), nl=False)


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
