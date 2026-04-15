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


def _ensure_gitignored(repo_path: Path) -> None:
    """Ensure .hyperloop/ is in the target repo's .gitignore."""
    gitignore = repo_path / ".gitignore"
    entry = ".hyperloop/"
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


def ensure_matrix_ready(
    config: MatrixConfig,
    repo_path: Path,
) -> tuple[str, str]:
    """Ensure Matrix credentials and room are available.

    Resolution order for **access_token**:
    1. Explicit ``token_env`` env var
    2. Cached token from ``.hyperloop/matrix-state.json``
    3. Auto-register via ``registration_token_env``

    Resolution order for **room_id**:
    1. Explicit ``room_id`` in config
    2. Cached room_id
    3. Auto-create via Matrix API

    Returns:
        (access_token, room_id) tuple. Either or both may be empty string
        if Matrix cannot be set up (logged as warning, never raises).
    """
    import os

    homeserver = config.homeserver.rstrip("/")
    cache = _load_cache(repo_path, homeserver)

    # --- Resolve access token ---
    explicit_token = os.environ.get(config.token_env) if config.token_env else ""
    cached_token = cache.get("access_token", "") if cache else ""
    access_token = explicit_token or cached_token

    if not access_token:
        # Try auto-registration
        registration_token = (
            os.environ.get(config.registration_token_env) if config.registration_token_env else ""
        )
        if registration_token:
            try:
                access_token = _auto_register(
                    config, repo_path, homeserver, registration_token, cache
                )
            except Exception:
                _log.exception("Matrix bot registration failed")
        else:
            _log.warning("Matrix: no access token and no registration token — skipping")
            return "", ""

    if not access_token:
        return "", ""

    # --- Resolve room_id ---
    cached_room = cache.get("room_id", "") if cache else ""
    room_id = config.room_id or cached_room

    if not room_id:
        try:
            room_id = _auto_create_room(config, repo_path, homeserver, access_token)
        except Exception:
            _log.exception("Matrix room creation failed")
            return access_token, ""

    return access_token, room_id


def _auto_register(
    config: MatrixConfig,
    repo_path: Path,
    homeserver: str,
    registration_token: str,
    cache: dict[str, str] | None,
) -> str:
    """Register a bot user and cache credentials. Returns access_token."""
    import os

    repo_name = repo_path.name
    username = config.bot_username or f"hyperloop-{repo_name}"

    # Password priority: env var > cache > generate new
    env_password = os.environ.get(config.bot_password_env) if config.bot_password_env else ""
    cached_password = cache.get("password", "") if cache else ""
    password = env_password or cached_password or secrets.token_urlsafe(32)

    client = httpx.Client(timeout=30.0)
    try:
        user_id, access_token = _register_bot(
            client, homeserver, registration_token, username, password
        )

        _save_cache(
            repo_path,
            homeserver=homeserver,
            user_id=user_id,
            access_token=access_token,
            room_id=config.room_id,
            password=password,
        )

        _log.info("Matrix bot registered: %s", user_id)
        return access_token
    finally:
        client.close()


def _auto_create_room(
    config: MatrixConfig,
    repo_path: Path,
    homeserver: str,
    access_token: str,
) -> str:
    """Create a room, invite the configured user, and update the cache. Returns room_id."""
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

        _log.info("Matrix room created: %s", room_id)
        return room_id
    finally:
        client.close()
