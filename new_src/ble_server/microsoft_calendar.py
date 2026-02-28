"""Microsoft Graph calendar fetcher for work Outlook/M365 accounts.

Uses device-code OAuth flow. Token is cached to disk for silent refresh.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import msal
import requests

log = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
SCOPES = ["User.Read", "Calendars.Read"]
EVENTS_URL = f"{GRAPH_BASE}/me/calendar/calendarView"
TITLE_MAX_LEN = 20


def _load_token_cache(cache_path: Path) -> msal.SerializableTokenCache:
    """Load token cache from disk."""
    cache = msal.SerializableTokenCache()
    if cache_path.exists():
        try:
            with open(cache_path) as f:
                cache.deserialize(f.read())
        except (OSError, json.JSONDecodeError) as e:
            log.warning("Token cache load failed: %s", e)
    return cache


def _save_token_cache(cache: msal.SerializableTokenCache, cache_path: Path) -> None:
    """Persist token cache to disk."""
    if cache.has_state_changed:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_path, "w") as f:
            f.write(cache.serialize())


def get_access_token(
    *,
    tenant_id: str,
    client_id: str,
    client_secret: str | None = None,
    token_cache_path: Path | str,
    allow_device_flow: bool = True,
) -> str | None:
    """Acquire access token via device code flow (or silent refresh).

    Returns None on failure.

    When allow_device_flow is False (e.g. headless/background services),
    only uses cached tokens. No interactive device flow is attempted.
    """
    cache_path = Path(token_cache_path)
    cache = _load_token_cache(cache_path)
    authority = f"https://login.microsoftonline.com/{tenant_id}"

    # Public client (device flow) — no client_secret
    # Confidential client (client credentials) would need secret
    # For device flow we use PublicClientApplication; secret is optional for that
    app = msal.PublicClientApplication(
        client_id,
        authority=authority,
        token_cache=cache,
    )

    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(SCOPES, account=accounts[0])
        if result:
            _save_token_cache(cache, cache_path)
            return result["access_token"]
        # Fall through to device flow (or fail fast if not allowed)

    if not allow_device_flow:
        log.info(
            "No valid Microsoft token in cache. Run 'python -m ble_server.sign_in' "
            "to authenticate, then restart the BLE server."
        )
        return None

    flow = app.initiate_device_flow(scopes=SCOPES)
    if not flow:
        log.error("Device flow init failed: %s", flow)
        return None

    print(flow["message"])  # Contains URL and code
    log.info("Device flow: user must complete at %s", flow.get("verification_uri"))

    result = app.acquire_token_by_device_flow(flow)
    _save_token_cache(cache, cache_path)

    if "access_token" in result:
        return result["access_token"]
    log.error("Device flow failed: %s", result.get("error_description", result))
    return None


def _meeting_type(event: dict[str, Any], subject: str) -> str:
    """Map Graph event to BLE meeting type."""
    subj_lower = (subject or "").lower()
    if event.get("recurrence"):
        return "recurring"
    if "focus" in subj_lower:
        return "focus"
    if "personal" in subj_lower:
        return "personal"
    if event.get("isOnlineMeeting"):
        return "call"
    return "live"


def _event_to_meeting(event: dict[str, Any], tz: datetime.tzinfo) -> dict[str, Any] | None:
    """Convert Graph event to BLE meeting dict. Returns None if invalid."""
    start_obj = event.get("start") or {}
    end_obj = event.get("end") or {}
    start_dt_str = start_obj.get("dateTime")
    end_dt_str = end_obj.get("dateTime")

    if not start_dt_str or not end_dt_str:
        return None

    try:
        # ISO 8601 — Graph returns with Z or offset
        start_dt = datetime.fromisoformat(
            start_dt_str.replace("Z", "+00:00")
        ).astimezone(tz)
        end_dt = datetime.fromisoformat(
            end_dt_str.replace("Z", "+00:00")
        ).astimezone(tz)
    except (ValueError, TypeError):
        log.debug("Skipping event with invalid start/end: %s", event.get("id"))
        return None

    duration_min = int((end_dt - start_dt).total_seconds() / 60)
    if duration_min <= 0:
        return None

    subject = (event.get("subject") or "(No title)").strip()
    if len(subject) > TITLE_MAX_LEN:
        subject = subject[: TITLE_MAX_LEN - 1] + "…"

    return {
        "date": start_dt.strftime("%Y-%m-%d"),
        "start_hour": start_dt.hour,
        "start_minute": start_dt.minute,
        "duration_min": duration_min,
        "title": subject,
        "type": _meeting_type(event, subject),
    }


def fetch_upcoming_events(
    access_token: str,
    *,
    time_min: datetime,
    time_max: datetime,
    limit: int = 15,
    tz: datetime.tzinfo | None = None,
) -> list[dict[str, Any]]:
    """Fetch events from Microsoft Graph calendarView. Returns BLE-format meetings."""
    if tz is None:
        tz = time_min.tzinfo or timezone.utc

    params = {
        "startDateTime": time_min.isoformat(),
        "endDateTime": time_max.isoformat(),
        "$top": limit,
        "$orderby": "start/dateTime",
    }
    headers = {"Authorization": f"Bearer {access_token}"}

    try:
        r = requests.get(EVENTS_URL, params=params, headers=headers, timeout=15)
        r.raise_for_status()
        data = r.json()
    except (requests.RequestException, ValueError, KeyError) as e:
        log.warning("Graph calendar fetch failed: %s", e)
        return []

    meetings: list[dict[str, Any]] = []
    for ev in data.get("value", []):
        m = _event_to_meeting(ev, tz)
        if m:
            meetings.append(m)

    return meetings


def get_meetings(
    tenant_id: str,
    client_id: str,
    client_secret: str | None,
    token_cache_path: Path | str,
    *,
    hours_ahead: int = 48,
    limit: int = 5,
    allow_device_flow: bool = True,
) -> list[dict[str, Any]] | None:
    """Fetch upcoming meetings from Microsoft calendar.

    Returns list of BLE-format meetings, or None on auth/fetch failure.
    """
    token = get_access_token(
        tenant_id=tenant_id,
        client_id=client_id,
        client_secret=client_secret,
        token_cache_path=token_cache_path,
        allow_device_flow=allow_device_flow,
    )
    if not token:
        return None

    now = datetime.now(timezone.utc).astimezone()
    time_min = now
    time_max = now + timedelta(hours=hours_ahead)

    meetings = fetch_upcoming_events(
        token,
        time_min=time_min,
        time_max=time_max,
        limit=limit + 5,  # Fetch extra in case some are filtered
        tz=now.tzinfo,
    )
    return meetings[:limit]
