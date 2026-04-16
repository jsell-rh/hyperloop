"""AmbientRuntime — runs workers as Ambient Code Platform sessions via acpctl.

Shells out to the ``acpctl`` CLI for all Ambient operations. Each parallel
worker gets a remote session; serial agents block the main thread.

Turn completion is detected via AG-UI Server-Sent Events streamed from
``acpctl session events``.  Results are collected by ``git fetch`` + review
file parsing from the remote ref.
"""

from __future__ import annotations

import atexit
import json
import re
import subprocess
import threading
import time
from typing import TYPE_CHECKING, cast

import structlog
import yaml

from hyperloop.domain.model import Verdict, WorkerHandle, WorkerResult

if TYPE_CHECKING:
    from hyperloop.compose import AgentTemplate
    from hyperloop.ports.runtime import WorkerPollStatus

log: structlog.stdlib.BoundLogger = structlog.get_logger()

_BACKOFF_SCHEDULE: tuple[float, ...] = (1.0, 2.0, 4.0, 8.0, 16.0)
_SERIAL_TIMEOUT_S: float = 600.0


class AmbientRuntime:
    """Runtime implementation using the Ambient Code Platform via acpctl.

    One Ambient agent per role (persistent). One session per spawn (ephemeral).
    Standing instructions set via agent prompt. Per-task context via inbox.
    """

    def __init__(
        self,
        repo_path: str,
        project_id: str,
        acpctl: str = "acpctl",
        base_branch: str = "main",
    ) -> None:
        self._repo_path = repo_path
        self._project_id = project_id
        self._acpctl = acpctl
        self._base_branch = base_branch

        self._agents: dict[str, str] = {}  # role name -> Ambient agent ID
        self._sessions: dict[str, str] = {}  # task_id -> session ID
        self._completion: dict[str, str] = {}  # session_id -> "done" | "failed"
        self._sse_threads: dict[str, threading.Thread] = {}  # session_id -> thread
        self._lock = threading.Lock()
        self._run_finished_data: dict[str, dict[str, object]] = {}  # session_id -> result

        # Register shutdown hook — stop all sessions on exit (crash or clean)
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

    # -- Agent lifecycle ------------------------------------------------------

    def sync_agents(self, templates: dict[str, AgentTemplate]) -> None:
        """Create/update Ambient agents from resolved templates.

        Called at startup and after process-improver rebuilds templates.
        Concatenates prompt + guidelines into the agent's prompt field.

        Uses create-or-update: tries ``agent update`` first, falls back
        to ``agent create`` if the agent doesn't exist yet.
        """
        for role, template in templates.items():
            agent_name = f"hyperloop-{role}"
            prompt = template.prompt
            if template.guidelines:
                prompt = f"{prompt}\n\n## Guidelines\n{template.guidelines}"

            labels = json.dumps(
                {
                    "hyperloop.io/managed": "true",
                    "hyperloop.io/role": role,
                }
            )

            agent_id = self._create_or_update_agent(agent_name, prompt, labels)
            self._agents[role] = agent_id
            log.info("ambient_agent_synced", role=role, agent_id=agent_id)

    def _create_or_update_agent(self, agent_name: str, prompt: str, labels: str) -> str:
        """Create or update an Ambient agent, returning its ID."""
        # Try update first
        try:
            self._run_acpctl(
                [
                    "agent",
                    "update",
                    agent_name,
                    "--project-id",
                    self._project_id,
                    "--prompt",
                    prompt,
                    "--labels",
                    labels,
                ]
            )
            # Fetch the agent to get its ID
            agent_data = self._run_acpctl(
                ["agent", "get", agent_name, "--project-id", self._project_id, "-o", "json"],
                parse_json=True,
            )
            data = cast("dict[str, object]", agent_data)
            return str(data.get("id", agent_name))
        except subprocess.CalledProcessError:
            pass

        # Agent doesn't exist — create it
        result = self._run_acpctl(
            [
                "agent",
                "create",
                "--name",
                agent_name,
                "--project-id",
                self._project_id,
                "--prompt",
                prompt,
                "--labels",
                labels,
                "-o",
                "json",
            ],
            parse_json=True,
        )
        data = cast("dict[str, object]", result)
        return str(data.get("id", agent_name))

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
        """Start an Ambient session for a task.

        1. Update agent annotations with task/branch.
        2. Send inbox message with per-task context.
        3. Start session.
        4. Start background SSE thread.
        """
        agent_id = self._agents[role]
        agent_name = f"hyperloop-{role}"

        # Update annotations
        annotations = json.dumps(
            {
                "hyperloop.io/task-id": task_id,
                "hyperloop.io/branch": branch,
            }
        )
        self._run_acpctl(
            [
                "agent",
                "update",
                agent_name,
                "--project-id",
                self._project_id,
                "--annotations",
                annotations,
            ]
        )

        # Send inbox message
        self._run_acpctl(
            [
                "inbox",
                "send",
                "--project-id",
                self._project_id,
                "--pa-id",
                agent_id,
                "--body",
                prompt,
                "--from-name",
                "hyperloop-orchestrator",
            ]
        )

        # Start session (use `agent start` which supports -o json)
        start_result = self._run_acpctl(
            [
                "agent",
                "start",
                agent_name,
                "--project-id",
                self._project_id,
                "-o",
                "json",
            ],
            parse_json=True,
        )
        start_data = cast("dict[str, object]", start_result)
        session_id = str(start_data["id"])

        self._sessions[task_id] = session_id

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
            agent_id=agent_id,
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

        1. Git fetch branch with exponential backoff.
        2. Read review file from remote ref.
        3. Stop session.
        4. Clean up.
        """
        task_id = handle.task_id
        session_id = handle.session_id or ""
        branch = self._get_branch_for_task(task_id)

        # Git fetch with backoff
        fetched = self._git_fetch_with_backoff(branch)
        if not fetched:
            self._stop_session(session_id)
            self._cleanup(task_id, session_id)
            return WorkerResult(
                verdict=Verdict.ERROR,
                findings=0,
                detail="branch not fetchable after push",
            )

        # Read review from remote ref
        result = self._read_review_from_ref(f"origin/{branch}", task_id)
        if result is None:
            result = WorkerResult(
                verdict=Verdict.PASS,
                findings=0,
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

        Checks each managed agent for a current_session_id whose annotations
        match the given task_id.
        """
        for role, agent_id in self._agents.items():
            agent_name = f"hyperloop-{role}"
            try:
                agent_data = self._run_acpctl(
                    ["agent", "get", agent_name, "--project-id", self._project_id, "-o", "json"],
                    parse_json=True,
                )
            except subprocess.CalledProcessError:
                continue

            data = cast("dict[str, object]", agent_data)
            current_session = data.get("current_session_id")
            if not current_session:
                continue

            raw_annotations = data.get("annotations")
            if isinstance(raw_annotations, str):
                try:
                    raw_annotations = json.loads(raw_annotations)
                except json.JSONDecodeError:
                    continue
            if not isinstance(raw_annotations, dict):
                continue

            ann = cast("dict[str, str]", raw_annotations)
            if ann.get("hyperloop.io/task-id") != task_id:
                continue

            # Found an orphaned session
            session_id = str(current_session)
            self._sessions[task_id] = session_id

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
                role=role,
                session_id=session_id,
            )

            return WorkerHandle(
                task_id=task_id,
                role=role,
                agent_id=agent_id,
                session_id=session_id,
            )

        return None

    def run_serial(self, role: str, prompt: str) -> bool:
        """Run a serial agent blocking the main thread.

        Streams SSE in the foreground until RUN_FINISHED or timeout.
        Then fetches and fast-forwards trunk.
        """
        agent_id = self._agents[role]

        # Send inbox
        self._run_acpctl(
            [
                "inbox",
                "send",
                "--project-id",
                self._project_id,
                "--pa-id",
                agent_id,
                "--body",
                prompt,
                "--from-name",
                "hyperloop-orchestrator",
            ]
        )

        # Start session (use `agent start` which supports -o json)
        agent_name = f"hyperloop-{role}"
        start_result = self._run_acpctl(
            [
                "agent",
                "start",
                agent_name,
                "--project-id",
                self._project_id,
                "-o",
                "json",
            ],
            parse_json=True,
        )
        start_data = cast("dict[str, object]", start_result)
        session_id = str(start_data["id"])

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
        for SSE immediately after ``agent start`` returns.
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
        """Foreground SSE stream for serial agents. Blocks until done or timeout.

        Retries the connection with backoff — the session may not be ready
        for SSE immediately after ``agent start`` returns.
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

    def _read_review_from_ref(self, ref: str, task_id: str) -> WorkerResult | None:
        """Read and parse a review file from a git ref (e.g. origin/branch).

        Uses ``git ls-tree`` to find review files and ``git show`` to read them.
        """
        try:
            ls_result = subprocess.run(
                [
                    "git",
                    "-C",
                    self._repo_path,
                    "ls-tree",
                    "--name-only",
                    ref,
                    ".hyperloop/state/reviews/",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError:
            return None

        # Find matching review files for this task
        prefix = f"{task_id}-round-"
        matches = sorted(
            name
            for name in ls_result.stdout.strip().splitlines()
            if name.split("/")[-1].startswith(prefix)
        )
        if not matches:
            return None

        review_path = matches[-1]
        try:
            show_result = subprocess.run(
                ["git", "-C", self._repo_path, "show", f"{ref}:{review_path}"],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError:
            return None

        content = show_result.stdout
        match = re.match(r"^---\n(.*?\n)---\n(.*)", content, re.DOTALL)
        if match is None:
            return None

        fm_raw = yaml.safe_load(match.group(1))
        if not isinstance(fm_raw, dict):
            return None

        fm = cast("dict[str, object]", fm_raw)
        body = match.group(2)
        return WorkerResult(
            verdict=Verdict(str(fm["verdict"])),
            findings=int(str(fm["findings"])),
            detail=body.strip(),
        )

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
        thread = self._sse_threads.pop(session_id, None)
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        with self._lock:
            self._completion.pop(session_id, None)
            self._run_finished_data.pop(session_id, None)

    def _get_branch_for_task(self, task_id: str) -> str:
        """Look up the branch for a task from acpctl agent annotations.

        Falls back to task_id as branch name if annotation lookup fails.
        """
        for role in self._agents:
            agent_name = f"hyperloop-{role}"
            try:
                agent_data = self._run_acpctl(
                    ["agent", "get", agent_name, "--project-id", self._project_id, "-o", "json"],
                    parse_json=True,
                )
            except subprocess.CalledProcessError:
                continue

            data = cast("dict[str, object]", agent_data)
            raw_annotations = data.get("annotations")
            if isinstance(raw_annotations, str):
                try:
                    raw_annotations = json.loads(raw_annotations)
                except json.JSONDecodeError:
                    continue
            if not isinstance(raw_annotations, dict):
                continue

            ann = cast("dict[str, str]", raw_annotations)
            if ann.get("hyperloop.io/task-id") == task_id:
                return ann.get("hyperloop.io/branch", task_id)

        return task_id
