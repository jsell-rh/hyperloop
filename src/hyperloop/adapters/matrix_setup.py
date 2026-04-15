"""Matrix auto-setup — bot registration, room creation, credential caching.

On first run: registers a bot user via the Matrix registration API, creates
a notification room, and caches credentials in ``.hyperloop/matrix-state.json``.
On subsequent runs: loads from cache and skips registration/room-creation.

Explicit ``token_env`` and ``room_id`` in config always take precedence over
auto-setup and cache.
"""

from __future__ import annotations

import json
import logging
import secrets
from typing import TYPE_CHECKING, cast

import httpx

if TYPE_CHECKING:
    from pathlib import Path

    from hyperloop.config import MatrixConfig

_log = logging.getLogger(__name__)

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
    """Register a bot user. Returns (user_id, access_token).

    Uses Synapse's shared-secret registration flow. If the user already
    exists (HTTP 400), falls back to login with the given password.
    """
    url = f"{homeserver}/_matrix/client/v3/register"
    body = {
        "username": username,
        "password": password,
        "auth": {
            "type": "m.login.registration_token",
            "token": registration_token,
        },
        "initial_device_display_name": "hyperloop",
        "inhibit_login": False,
    }

    resp = client.post(url, json=body)

    if resp.status_code == 200:
        data = resp.json()
        return str(data["user_id"]), str(data["access_token"])

    if resp.status_code == 401:
        # Server requires a different auth flow — try the flows it offers
        data = resp.json()
        flows = data.get("flows", [])
        session = data.get("session", "")

        # Check if m.login.registration_token is among the available flows
        for flow in flows:
            stages = flow.get("stages", [])
            if "m.login.registration_token" in stages:
                body["auth"] = {
                    "type": "m.login.registration_token",
                    "token": registration_token,
                    "session": session,
                }
                resp = client.post(url, json=body)
                if resp.status_code == 200:
                    data = resp.json()
                    return str(data["user_id"]), str(data["access_token"])

    if resp.status_code == 400:
        # User likely already exists — try login
        return _login(client, homeserver, username, password)

    resp.raise_for_status()
    msg = f"Unexpected registration response: {resp.status_code}"
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
) -> str:
    """Create a private Matrix room. Returns the room_id."""
    url = f"{homeserver}/_matrix/client/v3/createRoom"
    body = {
        "name": room_name,
        "topic": "hyperloop orchestrator notifications",
        "visibility": "private",
        "preset": "private_chat",
    }

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


def ensure_matrix_ready(
    config: MatrixConfig,
    repo_path: Path,
) -> tuple[str, str]:
    """Ensure Matrix credentials and room are available.

    Resolution order:
    1. Explicit ``token_env`` + ``room_id`` in config → use directly (no setup).
    2. Cached credentials in ``.hyperloop/matrix-state.json`` → reuse.
    3. ``registration_token`` → register bot, create room, cache.

    Returns:
        (access_token, room_id) tuple. Either or both may be empty string
        if Matrix cannot be set up (logged as warning, never raises).
    """
    import os

    homeserver = config.homeserver.rstrip("/")

    # 1. Explicit token from env takes precedence
    explicit_token = os.environ.get(config.token_env) if config.token_env else ""
    explicit_room = config.room_id

    if explicit_token and explicit_room:
        return explicit_token, explicit_room

    # 2. Try cache
    cache = _load_cache(repo_path, homeserver)
    if cache is not None:
        cached_token = cache.get("access_token", "")
        cached_room = cache.get("room_id", "")
        # Allow explicit overrides to supplement cache
        token = explicit_token or cached_token
        room_id = explicit_room or cached_room
        if token and room_id:
            return token, room_id

    # 3. Auto-setup via registration_token from env
    registration_token = (
        os.environ.get(config.registration_token_env) if config.registration_token_env else ""
    )
    if not registration_token:
        _log.warning(
            "Matrix: no access token, no cached credentials, and no registration token — skipping"
        )
        return "", ""

    try:
        return _auto_setup(config, repo_path, homeserver, registration_token, cache)
    except Exception:
        _log.exception("Matrix auto-setup failed — skipping Matrix notifications")
        return "", ""


def _auto_setup(
    config: MatrixConfig,
    repo_path: Path,
    homeserver: str,
    registration_token: str,
    cache: dict[str, str] | None,
) -> tuple[str, str]:
    """Register bot, create room, cache credentials. Returns (token, room_id)."""
    # Derive bot username
    repo_name = repo_path.name
    username = config.bot_username or f"hyperloop-{repo_name}"

    # Reuse cached password if available, otherwise generate one
    password = cache.get("password", "") if cache else ""
    if not password:
        password = secrets.token_urlsafe(32)

    client = httpx.Client(timeout=30.0)
    try:
        # Register or login
        user_id, access_token = _register_bot(
            client, homeserver, registration_token, username, password
        )

        # Create room if needed
        room_id = config.room_id
        if not room_id:
            room_id = _create_room(client, homeserver, access_token, f"hyperloop-{repo_name}")

        # Cache for next run
        _save_cache(
            repo_path,
            homeserver=homeserver,
            user_id=user_id,
            access_token=access_token,
            room_id=room_id,
            password=password,
        )

        _log.info("Matrix auto-setup complete: user=%s room=%s", user_id, room_id)
        return access_token, room_id
    finally:
        client.close()
