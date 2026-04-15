from __future__ import annotations

from datetime import datetime, timedelta
from threading import Lock

ACTIVE_WINDOW_SECONDS = 180
_PRUNE_AFTER_SECONDS = 24 * 60 * 60

_active_users: dict[str, dict[str, object]] = {}
_active_users_lock = Lock()


def _now() -> datetime:
    return datetime.now()


def _humanize_seconds(seconds: int) -> str:
    seconds = max(0, int(seconds or 0))
    if seconds < 10:
        return "сега"
    if seconds < 60:
        return f"пред {seconds} сек."

    minutes = seconds // 60
    if minutes < 60:
        return f"пред {minutes} мин."

    hours = minutes // 60
    if hours < 24:
        return f"пред {hours} ч."

    days = hours // 24
    return f"пред {days} ден."


def _prune_locked(now: datetime | None = None) -> None:
    now = now or _now()
    cutoff = now - timedelta(seconds=_PRUNE_AFTER_SECONDS)
    stale_users = [
        username
        for username, payload in _active_users.items()
        if payload.get("last_seen") and payload["last_seen"] < cutoff
    ]
    for username in stale_users:
        _active_users.pop(username, None)


def touch_active_user(username: str, endpoint: str = "", path: str = "", ip_address: str = "", user_agent: str = "") -> None:
    if not username:
        return

    now = _now()
    with _active_users_lock:
        _active_users[username] = {
            "username": username,
            "last_seen": now,
            "endpoint": endpoint or "",
            "path": path or "",
            "ip_address": ip_address or "",
            "user_agent": user_agent or "",
        }
        _prune_locked(now)


def remove_active_user(username: str) -> None:
    if not username:
        return
    with _active_users_lock:
        _active_users.pop(username, None)


def get_active_users(window_seconds: int = ACTIVE_WINDOW_SECONDS) -> list[dict[str, object]]:
    now = _now()
    cutoff = now - timedelta(seconds=max(1, int(window_seconds or ACTIVE_WINDOW_SECONDS)))

    with _active_users_lock:
        _prune_locked(now)
        active_users: list[dict[str, object]] = []
        for payload in _active_users.values():
            last_seen = payload.get("last_seen")
            if not isinstance(last_seen, datetime) or last_seen < cutoff:
                continue

            seconds_ago = int((now - last_seen).total_seconds())
            active_users.append(
                {
                    "username": payload.get("username") or "",
                    "endpoint": payload.get("endpoint") or "",
                    "path": payload.get("path") or "",
                    "ip_address": payload.get("ip_address") or "",
                    "user_agent": payload.get("user_agent") or "",
                    "last_seen": last_seen,
                    "last_seen_display": last_seen.strftime("%d-%m-%Y %H:%M:%S"),
                    "last_seen_relative": _humanize_seconds(seconds_ago),
                    "seconds_ago": seconds_ago,
                }
            )

    active_users.sort(key=lambda user: user.get("last_seen") or datetime.min, reverse=True)
    return active_users


def get_active_usernames(window_seconds: int = ACTIVE_WINDOW_SECONDS) -> set[str]:
    return {
        str(item.get("username", "")).strip()
        for item in get_active_users(window_seconds=window_seconds)
        if str(item.get("username", "")).strip()
    }
