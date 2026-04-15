"""Matrix auto-setup — bot registration, room creation, credential caching.

On first run: registers a bot user via the Matrix registration API, creates
a notification room, and caches credentials in ``.hyperloop/matrix-state.json``.
On subsequent runs: loads from cache and skips registration/room-creation.

Explicit ``token_env`` and ``room_id`` in config always take precedence over
auto-setup and cache.
"""

from __future__ import annotations

import json
import secrets
from typing import TYPE_CHECKING, cast

import httpx
import structlog

if TYPE_CHECKING:
    from pathlib import Path

    from hyperloop.config import MatrixConfig

_log: structlog.stdlib.BoundLogger = structlog.get_logger()

_CACHE_FILE = ".hyperloop/matrix-state.json"


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


def _load_cache(repo_path: Path, homeserver: str) -> dict[str, str] | None:
    """Load cached Matrix credentials if they match the current homeserver."""
    cache_path = repo_path / _CACHE_FILE
    if not cache_path.is_file():
        return None
    try:
        raw: object = json.loads(cache_path.read_text())
        if not isinstance(raw, dict):
            return None
        data: dict[str, object] = cast("dict[str, object]", raw)
        if data.get("homeserver") != homeserver:
            return None
        return {k: str(v) for k, v in data.items()}
    except (json.JSONDecodeError, OSError):
        return None


def _ensure_gitignored(repo_path: Path) -> None:
    """Ensure .hyperloop/ is in the target repo's .gitignore."""
    gitignore = repo_path / ".gitignore"
    entry = ".hyperloop/"
    if not repo_path.is_dir():
        return
    if gitignore.is_file():
        content = gitignore.read_text()
        if entry in content.splitlines():
            return
        if not content.endswith("\n"):
            content += "\n"
        gitignore.write_text(content + entry + "\n")
    else:
        gitignore.write_text(entry + "\n")


def _save_cache(
    repo_path: Path,
    *,
    homeserver: str,
    user_id: str,
    access_token: str,
    room_id: str,
    password: str,
) -> None:
    """Persist Matrix credentials to the cache file."""
    _ensure_gitignored(repo_path)
    cache_path = repo_path / _CACHE_FILE
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(
            {
                "homeserver": homeserver,
                "user_id": user_id,
                "access_token": access_token,
                "room_id": room_id,
                "password": password,
            },
            indent=2,
        )
        + "\n"
    )


# ---------------------------------------------------------------------------
# Matrix API calls
# ---------------------------------------------------------------------------


def _register_bot(
    client: httpx.Client,
    homeserver: str,
    registration_token: str,
    username: str,
    password: str,
) -> tuple[str, str]:
    """Register a bot user via UIA flow. Returns (user_id, access_token).

    Matrix UIA (User-Interactive Authentication) registration:
    1. POST /register without auth → server returns 401 with session + flows.
    2. POST /register with auth (type + token + session) → 200 with credentials.

    If the user already exists (HTTP 400), falls back to login.
    """
    url = f"{homeserver}/_matrix/client/v3/register"
    base_body: dict[str, object] = {
        "username": username,
        "password": password,
        "initial_device_display_name": "hyperloop",
        "inhibit_login": False,
    }

    # Step 1: request without auth to get session
    resp = client.post(url, json=base_body)

    if resp.status_code == 200:
        # Some servers accept registration without UIA
        data = resp.json()
        return str(data["user_id"]), str(data["access_token"])

    if resp.status_code == 400:
        return _login(client, homeserver, username, password)

    # Step 2: server should return 401 with session + flows
    if resp.status_code in (401, 403):
        data = resp.json()
        session = data.get("session", "")
        if session:
            base_body["auth"] = {
                "type": "m.login.registration_token",
                "token": registration_token,
                "session": session,
            }
            resp = client.post(url, json=base_body)
            if resp.status_code == 200:
                data = resp.json()
                return str(data["user_id"]), str(data["access_token"])
            if resp.status_code == 400:
                return _login(client, homeserver, username, password)

    resp.raise_for_status()
    msg = f"Registration failed: {resp.status_code} {resp.text}"
    raise RuntimeError(msg)


def _login(
    client: httpx.Client,
    homeserver: str,
    username: str,
    password: str,
) -> tuple[str, str]:
    """Log in with username/password. Returns (user_id, access_token)."""
    url = f"{homeserver}/_matrix/client/v3/login"
    body = {
        "type": "m.login.password",
        "identifier": {"type": "m.id.user", "user": username},
        "password": password,
        "initial_device_display_name": "hyperloop",
    }

    resp = client.post(url, json=body)
    resp.raise_for_status()
    data = resp.json()
    return str(data["user_id"]), str(data["access_token"])


def _create_room(
    client: httpx.Client,
    homeserver: str,
    access_token: str,
    room_name: str,
    invite_user: str = "",
) -> str:
    """Create a private Matrix room and optionally invite a user. Returns the room_id."""
    url = f"{homeserver}/_matrix/client/v3/createRoom"
    body: dict[str, object] = {
        "name": room_name,
        "topic": "hyperloop orchestrator notifications",
        "visibility": "private",
        "preset": "private_chat",
    }
    if invite_user:
        body["invite"] = [invite_user]

    resp = client.post(
        url,
        json=body,
        headers={"Authorization": f"Bearer {access_token}"},
    )
    resp.raise_for_status()
    data = resp.json()
    return str(data["room_id"])


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _check_token(client: httpx.Client, homeserver: str, access_token: str) -> bool:
    """Verify an access token is still valid via /_matrix/client/v3/account/whoami."""
    import contextlib

    with contextlib.suppress(Exception):
        resp = client.get(
            f"{homeserver}/_matrix/client/v3/account/whoami",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        return resp.status_code == 200
    return False


def ensure_matrix_ready(
    config: MatrixConfig,
    repo_path: Path,
) -> tuple[str, str]:
    """Ensure Matrix credentials and room are available.

    **Access token** resolution:
    1. Explicit ``token_env`` env var → use directly.
    2. Cached token from ``.hyperloop/matrix-state.json`` → validate with
       whoami, reuse if valid.
    3. ``registration_token_env`` → register a new bot, cache credentials.

    **Room ID** resolution:
    1. Explicit ``room_id`` in config.
    2. Cached room_id.
    3. Auto-create via Matrix API (invites ``invite_user``).

    Returns:
        (access_token, room_id) tuple. Either or both may be empty string
        if Matrix cannot be set up (logged as warning, never raises).
    """
    import os

    homeserver = config.homeserver.rstrip("/")
    cache = _load_cache(repo_path, homeserver)
    client = httpx.Client(timeout=30.0)

    try:
        # --- Resolve access token ---
        explicit_token = os.environ.get(config.token_env) if config.token_env else ""
        access_token = explicit_token
        is_new_bot = False

        if not access_token:
            # Try cached token
            cached_token = cache.get("access_token", "") if cache else ""
            if cached_token and _check_token(client, homeserver, cached_token):
                access_token = cached_token
                _log.info("matrix_using_cached_credentials")
            else:
                # Cached token missing or stale — try registration
                registration_token = (
                    os.environ.get(config.registration_token_env)
                    if config.registration_token_env
                    else ""
                )
                if not registration_token:
                    if cached_token:
                        _log.warning(
                            "matrix_credentials_stale",
                            hint="Cached Matrix credentials are invalid. "
                            "Set registration_token_env in .hyperloop.yaml to "
                            "auto-register a new bot, or provide a fresh access "
                            "token via token_env.",
                        )
                    else:
                        _log.warning(
                            "matrix_skipped",
                            reason="no access token, no cache, no registration token",
                        )
                    return "", ""

                try:
                    access_token = _register_bot_and_cache(
                        config, repo_path, homeserver, registration_token, cache
                    )
                    is_new_bot = True
                except Exception:
                    _log.exception("matrix_bot_registration_failed")
                    return "", ""

        if not access_token:
            return "", ""

        # --- Resolve room_id ---
        cached_room = cache.get("room_id", "") if cache else ""
        room_id = config.room_id or cached_room

        if not room_id:
            _log.info("matrix_room_creating")
            try:
                room_id = _auto_create_room(config, repo_path, homeserver, access_token)
            except Exception:
                _log.exception("matrix_room_creation_failed")
                return access_token, ""

        # New bot needs to join the existing room
        if is_new_bot and room_id:
            _log.info("matrix_room_joining", room_id=room_id)
            try:
                _join_room(client, homeserver, access_token, room_id)
            except Exception:
                _log.exception("matrix_room_join_failed", room_id=room_id)

        return access_token, room_id
    finally:
        client.close()


def _register_bot_and_cache(
    config: MatrixConfig,
    repo_path: Path,
    homeserver: str,
    registration_token: str,
    cache: dict[str, str] | None,
) -> str:
    """Register a bot user and cache credentials. Returns access_token."""
    repo_name = repo_path.name
    suffix = secrets.token_hex(4)
    username = f"hyperloop-{repo_name}-{suffix}"
    password = secrets.token_urlsafe(32)

    client = httpx.Client(timeout=30.0)
    try:
        user_id, access_token = _register_bot(
            client, homeserver, registration_token, username, password
        )

        cached_room = cache.get("room_id", "") if cache else ""
        _save_cache(
            repo_path,
            homeserver=homeserver,
            user_id=user_id,
            access_token=access_token,
            room_id=config.room_id or cached_room,
            password=password,
        )

        _log.info("matrix_bot_registered", user_id=user_id)
        return access_token
    finally:
        client.close()


def _join_room(client: httpx.Client, homeserver: str, access_token: str, room_id: str) -> None:
    """Join a room by ID."""
    url = f"{homeserver}/_matrix/client/v3/join/{room_id}"
    resp = client.post(url, json={}, headers={"Authorization": f"Bearer {access_token}"})
    resp.raise_for_status()


def _auto_create_room(
    config: MatrixConfig,
    repo_path: Path,
    homeserver: str,
    access_token: str,
) -> str:
    """Create a room, invite the configured user, and cache room_id. Returns room_id."""
    repo_name = repo_path.name
    client = httpx.Client(timeout=30.0)
    try:
        room_id = _create_room(
            client,
            homeserver,
            access_token,
            f"hyperloop-{repo_name}",
            invite_user=config.invite_user,
        )

        # Update cache with the new room_id
        cache = _load_cache(repo_path, homeserver) or {}
        _save_cache(
            repo_path,
            homeserver=homeserver,
            user_id=cache.get("user_id", ""),
            access_token=cache.get("access_token", access_token),
            room_id=room_id,
            password=cache.get("password", ""),
        )

        _log.info("matrix_room_created", room_id=room_id)
        return room_id
    finally:
        client.close()
