"""MatrixProbe — posts probe calls as formatted messages to a Matrix room.

Uses the Matrix client-server API (PUT ``/_matrix/client/v3/rooms/{room_id}/
send/m.room.message/{txn_id}``) via ``httpx``. Each task's messages are
threaded together using Matrix ``m.thread`` relations.

Signal filtering follows specs/observability.md: high-signal events are always
sent, verbose-only events require ``verbose=True``, and noisy events are never
sent.
"""

from __future__ import annotations

import logging
from uuid import uuid4

import httpx

_log = logging.getLogger(__name__)


class MatrixProbe:
    """Sends formatted probe messages to a Matrix room.

    Constructor arguments:
        homeserver: Matrix homeserver URL (e.g. ``https://matrix.example.com``).
        room_id: Target room ID (e.g. ``!abc123:example.com``).
        access_token: Bearer token for authentication.
        verbose: When ``True``, send verbose-only signals in addition to
            high-signal ones.
    """

    def __init__(
        self,
        homeserver: str,
        room_id: str,
        access_token: str,
        verbose: bool = False,
    ) -> None:
        self._homeserver = homeserver.rstrip("/")
        self._room_id = room_id
        self._access_token = access_token
        self._verbose = verbose
        self._client = httpx.Client(timeout=10.0)
        self._thread_roots: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _send(self, body: str, task_id: str | None = None) -> None:
        """Send a message to the Matrix room.

        If *task_id* is provided and a previous message exists for that task,
        the new message is sent as a thread reply.  Errors are logged and
        swallowed — Matrix failures must never propagate to the orchestrator.
        """
        txn_id = str(uuid4())
        url = (
            f"{self._homeserver}/_matrix/client/v3/rooms/"
            f"{self._room_id}/send/m.room.message/{txn_id}"
        )

        content: dict[str, object] = {
            "msgtype": "m.text",
            "body": body,
        }

        # Thread reply if we have a root event for this task
        if task_id is not None and task_id in self._thread_roots:
            root_event_id = self._thread_roots[task_id]
            content["m.relates_to"] = {
                "rel_type": "m.thread",
                "event_id": root_event_id,
            }

        try:
            response = self._client.put(
                url,
                json=content,
                headers={"Authorization": f"Bearer {self._access_token}"},
            )
            response.raise_for_status()
            data = response.json()
            event_id = data.get("event_id")

            # Track the first message for each task as the thread root
            if (
                task_id is not None
                and task_id not in self._thread_roots
                and isinstance(event_id, str)
            ):
                self._thread_roots[task_id] = event_id

        except Exception:
            _log.exception("matrix_send_failed room_id=%s", self._room_id)

    # ------------------------------------------------------------------
    # High-signal: always sent
    # ------------------------------------------------------------------

    def worker_reaped(self, **kw: object) -> None:
        task_id = str(kw.get("task_id", ""))
        verdict = str(kw.get("verdict", ""))
        role = str(kw.get("role", ""))
        rnd = kw.get("round", 0)
        duration_s = kw.get("duration_s", 0.0)
        detail = str(kw.get("detail", ""))
        cost_usd = kw.get("cost_usd")

        dur = round(float(duration_s), 1) if isinstance(duration_s, int | float) else duration_s
        emoji = "✅" if verdict == "pass" else "❌"
        cost_suffix = f", ${cost_usd:.2f}" if isinstance(cost_usd, int | float) else ""
        header = f"{emoji} {task_id} · {role} {verdict} (round {rnd}, {dur}s{cost_suffix})"
        body = f"{header}\n{detail}"
        self._send(body, task_id=task_id)

    def task_retried(self, **kw: object) -> None:
        task_id = str(kw.get("task_id", ""))
        rnd = kw.get("round", 0)
        preview = str(kw.get("findings_preview", ""))

        body = f"\U0001f501 {task_id} · retried (round {rnd})\n> {preview}"
        self._send(body, task_id=task_id)

    def task_completed(self, **kw: object) -> None:
        task_id = str(kw.get("task_id", ""))
        total_rounds = kw.get("total_rounds", 0)
        total_cycles = kw.get("total_cycles", 0)

        body = f"\U0001f389 {task_id} · complete ({total_rounds} round(s), {total_cycles} cycle(s))"
        self._send(body, task_id=task_id)

    def task_failed(self, **kw: object) -> None:
        task_id = str(kw.get("task_id", ""))
        reason = str(kw.get("reason", ""))

        body = f"❌ {task_id} · FAILED\n{reason}"
        self._send(body, task_id=task_id)

    def task_reset(self, **kw: object) -> None:
        task_id = str(kw.get("task_id", ""))
        reason = str(kw.get("reason", ""))
        prior_round = kw.get("prior_round", 0)

        body = f"⚠️ {task_id} · RESET (was at round {prior_round})\n{reason}"
        self._send(body, task_id=task_id)

    def merge_attempted(self, **kw: object) -> None:
        task_id = str(kw.get("task_id", ""))
        outcome = str(kw.get("outcome", ""))
        branch = str(kw.get("branch", ""))

        if outcome == "merged":
            body = f"\U0001f500 {task_id} · merged ({branch})"
        else:
            body = f"⚠️ {task_id} · merge {outcome} ({branch})"
        self._send(body, task_id=task_id)

    def orphan_found(self, **kw: object) -> None:
        task_id = str(kw.get("task_id", ""))
        branch = str(kw.get("branch", ""))

        body = f"⚠️ orphan found: {task_id} on {branch}"
        self._send(body, task_id=task_id)

    def orchestrator_halted(self, **kw: object) -> None:
        reason = str(kw.get("reason", ""))
        total_cycles = kw.get("total_cycles", 0)
        completed = kw.get("completed_tasks", 0)
        failed = kw.get("failed_tasks", 0)

        emoji = "\U0001f3c1" if "complete" in reason else "\U0001f6d1"
        body = (
            f"{emoji} orchestrator halted: {reason}\n"
            f"cycles={total_cycles}  completed={completed}  failed={failed}"
        )
        self._send(body)

    def worker_crash_detected(self, **kw: object) -> None:
        task_id = str(kw.get("task_id", ""))
        role = str(kw.get("role", ""))
        branch = str(kw.get("branch", ""))

        body = f"⚠️ worker crash detected: {task_id} ({role}) on {branch}"
        self._send(body, task_id=task_id)

    # ------------------------------------------------------------------
    # Verbose-only: sent when verbose=True
    # ------------------------------------------------------------------

    def worker_spawned(self, **kw: object) -> None:
        if not self._verbose:
            return
        task_id = str(kw.get("task_id", ""))
        role = str(kw.get("role", ""))
        rnd = kw.get("round", 0)

        body = f"\U0001f680 {task_id} · spawned {role} (round {rnd})"
        self._send(body, task_id=task_id)

    def cycle_completed(self, **kw: object) -> None:
        if not self._verbose:
            return
        cycle = kw.get("cycle", 0)
        duration_s = kw.get("duration_s", 0.0)
        dur = round(float(duration_s), 1) if isinstance(duration_s, int | float) else duration_s

        body = f"\U0001f504 cycle {cycle} completed ({dur}s)"
        self._send(body)

    def intake_ran(self, **kw: object) -> None:
        if not self._verbose:
            return
        created = kw.get("created_tasks", 0)
        duration_s = kw.get("duration_s", 0.0)
        dur = round(float(duration_s), 1) if isinstance(duration_s, int | float) else duration_s

        body = f"\U0001f4e5 intake ran: {created} task(s) created ({dur}s)"
        self._send(body)

    def process_improver_ran(self, **kw: object) -> None:
        if not self._verbose:
            return
        duration_s = kw.get("duration_s", 0.0)
        dur = round(float(duration_s), 1) if isinstance(duration_s, int | float) else duration_s

        body = f"\U0001f527 process-improver ran ({dur}s)"
        self._send(body)

    def orchestrator_started(self, **kw: object) -> None:
        if not self._verbose:
            return
        task_count = kw.get("task_count", 0)
        max_workers = kw.get("max_workers", 0)

        body = f"\U0001f680 orchestrator started: {task_count} task(s), {max_workers} max workers"
        self._send(body)

    def recovery_started(self, **kw: object) -> None:
        if not self._verbose:
            return
        in_progress = kw.get("in_progress_tasks", 0)

        body = f"♻️ recovery started: {in_progress} in-progress task(s)"
        self._send(body)

    def worker_message(self, **kw: object) -> None:
        if not self._verbose:
            return
        task_id = str(kw.get("task_id", ""))
        role = str(kw.get("role", ""))
        msg_type = str(kw.get("message_type", ""))
        content = str(kw.get("content", ""))

        # Truncate long content for Matrix readability
        if len(content) > 300:
            content = content[:297] + "..."

        icons = {
            "text": "\U0001f4ac",
            "tool_use": "\U0001f527",
            "tool_result": "\U0001f4cb",
            "result": "\U0001f3c1",
        }
        icon = icons.get(msg_type, "•")
        body = f"{icon} {task_id} · {role} [{msg_type}] {content}"
        self._send(body, task_id=task_id)

    def spawn_failed(self, **kw: object) -> None:
        task_id = str(kw.get("task_id", ""))
        role = str(kw.get("role", ""))
        attempt = kw.get("attempt", 0)
        max_attempts = kw.get("max_attempts", 3)
        cooldown = kw.get("cooldown_cycles", 0)
        body = f"⚠️ Spawn failed: {task_id} ({role}) attempt {attempt}/{max_attempts}"
        if cooldown:
            body += f" — cooling down for {cooldown} cycles"
        self._send(body)

    def drift_detected(self, **kw: object) -> None:
        if not self._verbose:
            return
        spec_path = str(kw.get("spec_path", ""))
        drift_type = str(kw.get("drift_type", ""))
        detail = str(kw.get("detail", ""))

        body = f"\U0001f50d drift detected: {spec_path} ({drift_type})\n{detail}"
        self._send(body)

    def reconcile_started(self, **kw: object) -> None:
        if not self._verbose:
            return
        cycle = kw.get("cycle", 0)

        body = f"\U0001f504 reconcile started (cycle {cycle})"
        self._send(body)

    def reconcile_completed(self, **kw: object) -> None:
        if not self._verbose:
            return
        cycle = kw.get("cycle", 0)
        duration_s = kw.get("duration_s", 0.0)
        dur = round(float(duration_s), 1) if isinstance(duration_s, int | float) else duration_s
        drift_count = kw.get("drift_count", 0)
        audits_run = kw.get("audits_run", 0)
        gc_pruned = kw.get("gc_pruned", 0)

        body = (
            f"\U0001f504 reconcile completed (cycle {cycle}, {dur}s)\n"
            f"drifts={drift_count}  audits={audits_run}  gc_pruned={gc_pruned}"
        )
        self._send(body)

    def auditors_started(self, **kw: object) -> None:
        if not self._verbose:
            return
        count = kw.get("count", 0)
        cycle = kw.get("cycle", 0)

        body = f"\U0001f50d auditors started: {count} auditor(s) launched (cycle {cycle})"
        self._send(body)

    def audit_started(self, **kw: object) -> None:
        if not self._verbose:
            return
        spec_ref = str(kw.get("spec_ref", ""))
        cycle = kw.get("cycle", 0)

        body = f"\U0001f50d audit started: {spec_ref} (cycle {cycle})"
        self._send(body)

    def audit_ran(self, **kw: object) -> None:
        if not self._verbose:
            return
        spec_ref = str(kw.get("spec_ref", ""))
        result = str(kw.get("result", ""))
        duration_s = kw.get("duration_s", 0.0)
        dur = round(float(duration_s), 1) if isinstance(duration_s, int | float) else duration_s

        body = f"\U0001f4cb audit ran: {spec_ref} result={result} ({dur}s)"
        self._send(body)

    def gc_ran(self, **kw: object) -> None:
        if not self._verbose:
            return
        pruned_count = kw.get("pruned_count", 0)

        body = f"\U0001f5d1️ GC ran: {pruned_count} pruned"
        self._send(body)

    def convergence_marked(self, **kw: object) -> None:
        if not self._verbose:
            return
        spec_path = str(kw.get("spec_path", ""))
        spec_ref = str(kw.get("spec_ref", ""))

        body = f"✅ convergence marked: {spec_path} ({spec_ref})"
        self._send(body)

    # ------------------------------------------------------------------
    # Never sent (too noisy)
    # ------------------------------------------------------------------

    def collect_started(self, **kw: object) -> None:
        pass

    def collect_completed(self, **kw: object) -> None:
        pass

    def advance_started(self, **kw: object) -> None:
        pass

    def advance_completed(self, **kw: object) -> None:
        pass

    def spawn_started(self, **kw: object) -> None:
        pass

    def spawn_completed(self, **kw: object) -> None:
        pass

    def cycle_started(self, **kw: object) -> None:
        pass

    def task_advanced(self, **kw: object) -> None:
        pass

    def prompt_composed(self, **kw: object) -> None:
        pass

    def pr_created(self, **kw: object) -> None:
        pr_url = kw.get("pr_url", "")
        task_id = kw.get("task_id", "")
        self._send(f"PR created for {task_id}: {pr_url}")

    def pr_marked_ready(self, **kw: object) -> None:
        pass

    def state_synced(self, **kw: object) -> None:
        pass

    def state_sync_failed(self, **kw: object) -> None:
        error = str(kw.get("error", ""))
        body = f"⚠️ state sync failed — state exists only locally\n{error}"
        self._send(body)

    def trunk_push_failed(self, **kw: object) -> None:
        branch = str(kw.get("branch", ""))
        error = str(kw.get("error", ""))
        body = f"⚠️ trunk push failed — {branch} diverged from remote\n{error}"
        self._send(body)

    def step_executed(self, **kw: object) -> None:
        pass

    def feedback_checked(self, **kw: object) -> None:
        count = kw.get("unprocessed_count", 0)
        if not count:
            return
        task_id = str(kw.get("task_id", ""))
        allowed = kw.get("allowed_authors", ())
        authors = ", ".join(str(a) for a in allowed) if isinstance(allowed, (tuple, list)) else ""  # type: ignore[reportUnknownVariableType,reportUnknownArgumentType]
        body = f"\U0001f4ac {task_id} · {count} unprocessed feedback comment(s) from {authors}"
        self._send(body, task_id=task_id)

    def agent_retried(self, **kw: object) -> None:
        if not self._verbose:
            return
        role = str(kw.get("role", ""))
        operation = str(kw.get("operation", ""))
        attempt = kw.get("attempt", 0)
        max_attempts = kw.get("max_attempts", 0)
        error = str(kw.get("error", ""))

        body = f"⚠️ agent retry: {role}/{operation} attempt {attempt}/{max_attempts}\n{error}"
        self._send(body)

    def signal_checked(self, **kw: object) -> None:
        pass
