"""AmbientRuntime — runs workers as Ambient Code Platform sessions via acpctl.

Shells out to the ``acpctl`` CLI for all Ambient operations.  Each worker
gets a session created via ``acpctl create session`` with ``--repo-url``
so the agent gets the repo cloned into its workspace.

Turn completion is detected via AG-UI Server-Sent Events streamed from
``acpctl session events``.  Verdict is read from ``.hyperloop/worker-result.yaml``
on the fetched branch ref (runtime-agnostic file transport).

No Ambient agents or inbox — sessions carry the full composed prompt directly.
"""

from __future__ import annotations

import atexit
import json
import subprocess
import threading
import time
from typing import TYPE_CHECKING, cast

import structlog

from hyperloop.domain.model import Verdict, WorkerHandle, WorkerResult

if TYPE_CHECKING:
    from hyperloop.ports.runtime import WorkerPollStatus

log: structlog.stdlib.BoundLogger = structlog.get_logger()

_BACKOFF_SCHEDULE: tuple[float, ...] = (1.0, 2.0, 4.0, 8.0, 16.0)
_SERIAL_TIMEOUT_S: float = 3600.0


class AmbientRuntime:
    """Runtime implementation using the Ambient Code Platform via acpctl.

    Sessions-only model: each spawn creates a session with the full composed
    prompt and repo_url.  No Ambient agents, no inbox — the session carries
    everything.
    """

    def __init__(
        self,
        repo_path: str,
        project_id: str,
        acpctl: str = "acpctl",
        base_branch: str = "main",
        repo_url: str = "",
    ) -> None:
        self._repo_path = repo_path
        self._project_id = project_id
        self._acpctl = acpctl
        self._base_branch = base_branch
        self._repo_url = repo_url

        self._sessions: dict[str, str] = {}  # task_id -> session ID
        self._branches: dict[str, str] = {}  # task_id -> branch name
        self._completion: dict[str, str] = {}  # session_id -> "done" | "failed"
        self._sse_threads: dict[str, threading.Thread] = {}  # session_id -> thread
        self._lock = threading.Lock()
        self._run_finished_data: dict[str, dict[str, object]] = {}

        # Stop all sessions on exit (crash or clean)
        atexit.register(self._shutdown)

    def _shutdown(self) -> None:
        """Stop all running sessions. Called on interpreter exit via atexit."""
        session_ids = list(self._sessions.values())
        if not session_ids:
            return
        log.info("ambient_shutdown", sessions=len(session_ids))
        for session_id in session_ids:
            self._stop_session(session_id)

    # -- acpctl helper --------------------------------------------------------

    def _run_acpctl(
        self,
        args: list[str],
        *,
        parse_json: bool = False,
    ) -> str | dict[str, object]:
        """Shell out to acpctl and return stdout or parsed JSON."""
        cmd = [self._acpctl, *args]
        result = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
        )
        if parse_json:
            parsed: dict[str, object] = json.loads(result.stdout)
            return parsed
        return result.stdout.strip()

    # -- Project lifecycle ----------------------------------------------------

    def ensure_project(self) -> None:
        """Create the Ambient project if it doesn't exist.

        Called at startup before any sessions are created.
        """
        try:
            self._run_acpctl(
                ["project", "update", self._project_id, "--description", "hyperloop-managed"],
            )
            log.info("ambient_project_exists", project_id=self._project_id)
            return
        except subprocess.CalledProcessError:
            pass

        self._run_acpctl(
            [
                "create",
                "project",
                "--name",
                self._project_id,
                "--description",
                "hyperloop-managed",
            ]
        )
        log.info("ambient_project_created", project_id=self._project_id)

    # -- Runtime protocol -----------------------------------------------------

    def worker_epilogue(self) -> str:
        """Return push instruction for Ambient workers."""
        return "Push your branch when your work is complete."

    def push_branch(self, branch: str) -> None:
        """Push branch to remote for Ambient agent access."""
        try:
            subprocess.run(
                ["git", "-C", self._repo_path, "push", "-u", "origin", branch],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            log.warning("push_branch_failed", branch=branch, error=str(exc))

    def spawn(self, task_id: str, role: str, prompt: str, branch: str) -> WorkerHandle:
        """Create an Ambient session for a task.

        Uses ``acpctl create session`` with the full composed prompt and
        repo_url.  The session auto-starts (operator sets phase=Pending→Running).
        """
        session_name = f"hyperloop-{task_id}-{role}"

        # Build create session args
        args = [
            "create",
            "session",
            "--name",
            session_name,
            "--prompt",
            prompt,
            "-o",
            "json",
        ]
        if self._repo_url:
            args.extend(["--repo-url", self._repo_url])

        result = self._run_acpctl(args, parse_json=True)
        data = cast("dict[str, object]", result)
        session_id = str(data["id"])

        self._sessions[task_id] = session_id
        self._branches[task_id] = branch

        # Start SSE background thread
        thread = threading.Thread(
            target=self._stream_sse,
            args=(session_id,),
            daemon=True,
        )
        self._sse_threads[session_id] = thread
        thread.start()

        log.info(
            "ambient_worker_spawned",
            task_id=task_id,
            role=role,
            session_id=session_id,
        )

        return WorkerHandle(
            task_id=task_id,
            role=role,
            agent_id=session_name,
            session_id=session_id,
        )

    def poll(self, handle: WorkerHandle) -> WorkerPollStatus:
        """Check session completion state from SSE thread."""
        session_id = handle.session_id
        if session_id is None:
            return "failed"
        with self._lock:
            status = self._completion.get(session_id)
        if status is None:
            return "running"
        if status == "done":
            return "done"
        return "failed"

    def reap(self, handle: WorkerHandle) -> WorkerResult:
        """Collect result from a finished session.

        Reads verdict from .hyperloop/worker-result.yaml on the fetched
        branch ref. Falls back to FAIL if no verdict file exists and
        the session ended in failure, PASS otherwise.
        The verdict file is stripped from the branch later by rebase_branch.
        """
        from hyperloop.adapters.verdict import read_verdict_from_ref

        task_id = handle.task_id
        session_id = handle.session_id or ""
        branch = self._branches.get(task_id, task_id)

        # Git fetch with backoff
        fetched = self._git_fetch_with_backoff(branch)
        if not fetched:
            self._stop_session(session_id)
            self._cleanup(task_id, session_id)
            return WorkerResult(
                verdict=Verdict.FAIL,
                detail="branch not fetchable after push",
            )

        result = read_verdict_from_ref(self._repo_path, f"origin/{branch}")

        if result is None:
            with self._lock:
                status = self._completion.get(session_id, "")
            if status == "failed":
                result = WorkerResult(
                    verdict=Verdict.FAIL,
                    detail="Agent session failed without writing verdict",
                )
            else:
                result = WorkerResult(
                    verdict=Verdict.PASS,
                    detail="Agent completed",
                )

        # Stop session and clean up
        self._stop_session(session_id)
        self._cleanup(task_id, session_id)

        return result

    def cancel(self, handle: WorkerHandle) -> None:
        """Stop a running session and clean up."""
        task_id = handle.task_id
        session_id = handle.session_id or ""

        self._stop_session(session_id)
        self._cleanup(task_id, session_id)

    def find_orphan(self, task_id: str, branch: str) -> WorkerHandle | None:
        """Find an orphaned session from a previous orchestrator run.

        Scans all running sessions in the project for one whose name
        matches the hyperloop naming convention for this task.
        """
        try:
            result = self._run_acpctl(
                ["get", "sessions", "--project-id", self._project_id, "-o", "json"],
                parse_json=True,
            )
        except subprocess.CalledProcessError:
            return None

        data = cast("dict[str, object]", result)
        items = data.get("items")
        if not isinstance(items, list):
            return None

        prefix = f"hyperloop-{task_id}-"
        for item_raw in cast("list[object]", items):
            if not isinstance(item_raw, dict):
                continue
            item = cast("dict[str, object]", item_raw)
            name = str(item.get("name", ""))
            phase = str(item.get("phase", ""))
            session_id = str(item.get("id", ""))

            if not name.startswith(prefix):
                continue
            if phase != "Running":
                continue

            # Found an orphaned session
            self._sessions[task_id] = session_id
            self._branches[task_id] = branch

            # Start SSE thread for recovery
            thread = threading.Thread(
                target=self._stream_sse,
                args=(session_id,),
                daemon=True,
            )
            self._sse_threads[session_id] = thread
            thread.start()

            log.info(
                "ambient_orphan_found",
                task_id=task_id,
                session_id=session_id,
            )

            return WorkerHandle(
                task_id=task_id,
                role="unknown",
                agent_id=name,
                session_id=session_id,
            )

        return None

    def run_serial(self, role: str, prompt: str) -> bool:
        """Run a serial session blocking the main thread.

        Creates a session with the full prompt, streams SSE until
        RUN_FINISHED, then fetches and fast-forwards trunk.
        """
        session_name = f"hyperloop-serial-{role}"

        args = [
            "create",
            "session",
            "--name",
            session_name,
            "--prompt",
            prompt,
            "-o",
            "json",
        ]
        if self._repo_url:
            args.extend(["--repo-url", self._repo_url])

        result = self._run_acpctl(args, parse_json=True)
        data = cast("dict[str, object]", result)
        session_id = str(data["id"])

        log.info("ambient_serial_started", role=role, session_id=session_id)

        # Stream SSE in foreground (blocking)
        success = self._stream_sse_foreground(session_id)

        if success:
            # Fetch and fast-forward trunk
            fetched = self._git_fetch_with_backoff(self._base_branch)
            if fetched:
                try:
                    subprocess.run(
                        [
                            "git",
                            "-C",
                            self._repo_path,
                            "merge",
                            "--ff-only",
                            f"origin/{self._base_branch}",
                        ],
                        check=True,
                        capture_output=True,
                        text=True,
                    )
                except subprocess.CalledProcessError as exc:
                    log.warning("serial_ff_merge_failed", error=str(exc))
                    success = False
            else:
                success = False

        # Stop session
        self._stop_session(session_id)

        log.info("ambient_serial_completed", role=role, success=success)
        return success

    # -- Private helpers -------------------------------------------------------

    def _stream_sse(self, session_id: str) -> None:
        """Background thread: stream AG-UI events and watch for RUN_FINISHED.

        Retries the connection with backoff — the session may not be ready
        for SSE immediately after creation.
        """
        for attempt, delay in enumerate(_BACKOFF_SCHEDULE):
            try:
                if self._stream_sse_once(session_id):
                    return  # RUN_FINISHED received
            except Exception:
                log.warning(
                    "sse_connect_retry",
                    session_id=session_id,
                    attempt=attempt + 1,
                )
            time.sleep(delay)

        log.warning("sse_stream_exhausted", session_id=session_id)
        with self._lock:
            self._completion[session_id] = "failed"

    def _stream_sse_once(self, session_id: str) -> bool:
        """Attempt one SSE stream connection. Returns True if RUN_FINISHED seen."""
        proc = subprocess.Popen(
            [self._acpctl, "session", "events", session_id],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            if proc.stdout is None:
                return False

            got_any_event = False
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    raw_event: object = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if not isinstance(raw_event, dict):
                    continue
                event = cast("dict[str, object]", raw_event)
                got_any_event = True
                if event.get("type") == "RUN_FINISHED":
                    with self._lock:
                        self._completion[session_id] = "done"
                        result_payload = event.get("result")
                        if isinstance(result_payload, dict):
                            self._run_finished_data[session_id] = cast(
                                "dict[str, object]", result_payload
                            )
                    return True

            # Process exited without RUN_FINISHED — log stderr for diagnostics
            if not got_any_event and proc.stderr is not None:
                stderr = proc.stderr.read().strip()
                if stderr:
                    log.warning("sse_empty_stream", session_id=session_id, stderr=stderr)
            return got_any_event  # Retry only if we got nothing
        finally:
            proc.terminate()
            proc.wait()

    def _stream_sse_foreground(self, session_id: str) -> bool:
        """Foreground SSE stream for serial sessions. Blocks until done or timeout.

        Retries the connection with backoff — the session may not be ready
        for SSE immediately after creation.
        """
        deadline = time.monotonic() + _SERIAL_TIMEOUT_S

        for attempt, delay in enumerate(_BACKOFF_SCHEDULE):
            if time.monotonic() > deadline:
                log.warning("serial_sse_timeout", session_id=session_id)
                return False

            result = self._stream_sse_foreground_once(session_id, deadline)
            if result is not None:
                return result  # True = RUN_FINISHED, False = timeout

            log.warning(
                "serial_sse_connect_retry",
                session_id=session_id,
                attempt=attempt + 1,
            )
            time.sleep(delay)

        log.warning("serial_sse_exhausted", session_id=session_id)
        return False

    def _stream_sse_foreground_once(self, session_id: str, deadline: float) -> bool | None:
        """One SSE attempt. Returns True (done), False (timeout), None (retry)."""
        try:
            proc = subprocess.Popen(
                [self._acpctl, "session", "events", session_id],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                if proc.stdout is None:
                    return None

                got_any_event = False
                for line in proc.stdout:
                    if time.monotonic() > deadline:
                        log.warning("serial_sse_timeout", session_id=session_id)
                        return False

                    line = line.strip()
                    if not line:
                        continue
                    try:
                        raw_event: object = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    if not isinstance(raw_event, dict):
                        continue
                    fg_event = cast("dict[str, object]", raw_event)
                    got_any_event = True
                    if fg_event.get("type") == "RUN_FINISHED":
                        return True

                # Process exited without RUN_FINISHED — log stderr for diagnostics
                if not got_any_event and proc.stderr is not None:
                    stderr = proc.stderr.read().strip()
                    if stderr:
                        log.warning("serial_sse_empty_stream", session_id=session_id, stderr=stderr)
                return None if not got_any_event else False
            finally:
                proc.terminate()
                proc.wait()
        except Exception:
            log.exception("serial_sse_error", session_id=session_id)
            return None

    def _git_fetch_with_backoff(self, branch: str) -> bool:
        """Fetch a branch from origin with exponential backoff."""
        for delay in _BACKOFF_SCHEDULE:
            try:
                subprocess.run(
                    ["git", "-C", self._repo_path, "fetch", "origin", branch],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                return True
            except subprocess.CalledProcessError:
                time.sleep(delay)
        return False

    def _stop_session(self, session_id: str) -> None:
        """Stop an Ambient session (best-effort)."""
        if not session_id:
            return
        try:
            self._run_acpctl(["stop", session_id])
        except subprocess.CalledProcessError:
            log.warning("session_stop_failed", session_id=session_id)

    def _cleanup(self, task_id: str, session_id: str) -> None:
        """Remove internal tracking state for a task/session."""
        self._sessions.pop(task_id, None)
        self._branches.pop(task_id, None)
        thread = self._sse_threads.pop(session_id, None)
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        with self._lock:
            self._completion.pop(session_id, None)
            self._run_finished_data.pop(session_id, None)
