"""
plugins/calendar_email.py
-------------------------
Google Calendar and Gmail plugin using google-api-python-client.

Capabilities:
- Read today's calendar events
- Create new calendar events
- Read last 5 unread Gmail messages
- Send an email

This module expects a `GOOGLE_CREDENTIALS_PATH` entry in the
project `config.json` pointing to a Google OAuth client secrets
JSON file (installed app). OAuth tokens are stored in `token.json`
next to the project root.

The plugin exposes `TRIGGERS` so a plugin loader can discover
available commands/triggers.
"""
from __future__ import annotations

import json
import os
import base64
import logging
import re
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from pathlib import Path
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _load_config() -> Dict[str, Any]:
    cfg_path = _project_root() / "config.json"
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _credentials_path() -> Path:
    cfg = _load_config()
    cred_path = cfg.get("GOOGLE_CREDENTIALS_PATH")
    if not cred_path:
        raise FileNotFoundError("GOOGLE_CREDENTIALS_PATH is not set in config.json")
    p = Path(cred_path)
    # If a relative path is provided, resolve relative to project root
    if not p.is_absolute():
        p = (_project_root() / p).resolve()
    if not p.exists():
        raise FileNotFoundError(f"Google credentials file not found: {p}")
    return p


def _token_path() -> Path:
    return _project_root() / "token.json"


def get_credentials():
    """Obtain valid user credentials, storing a `token.json` locally.

    This will perform the installed app flow if no token is present.
    """
    try:
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
    except Exception as e:
        raise ImportError("google-auth libraries are required: pip install google-auth google-auth-oauthlib google-api-python-client") from e

    token_file = _token_path()
    creds = None
    if token_file.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)
        except Exception:
            creds = None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                creds = None

    if not creds:
        flow = InstalledAppFlow.from_client_secrets_file(str(_credentials_path()), SCOPES)
        creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open(token_file, "w", encoding="utf-8") as f:
            f.write(creds.to_json())

    return creds


def _build_service(api_name: str, api_version: str):
    try:
        from googleapiclient.discovery import build
    except Exception as e:
        raise ImportError("google-api-python-client is required: pip install google-api-python-client") from e

    creds = get_credentials()
    return build(api_name, api_version, credentials=creds)


def read_todays_events(max_results: int = 10) -> List[Dict[str, Any]]:
    """Return a list of today's calendar events (start time, end time, summary)."""
    service = _build_service("calendar", "v3")
    now = datetime.now(timezone.utc)
    start_of_day = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    end_of_day = start_of_day + timedelta(days=1)

    events_result = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=start_of_day.isoformat(),
            timeMax=end_of_day.isoformat(),
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )

    events = events_result.get("items", [])
    parsed = []
    for ev in events:
        start = ev.get("start", {}).get("dateTime") or ev.get("start", {}).get("date")
        end = ev.get("end", {}).get("dateTime") or ev.get("end", {}).get("date")
        parsed.append({"summary": ev.get("summary", "(no title)"), "start": start, "end": end})
    return parsed


def create_event(summary: str, start_dt: datetime, end_dt: datetime, timezone_str: str | None = None) -> Dict[str, Any]:
    """Create a calendar event in the user's primary calendar.

    `start_dt` and `end_dt` should be timezone-aware datetimes. Returns the created event.
    """
    service = _build_service("calendar", "v3")

    event = {
        "summary": summary,
        "start": {"dateTime": start_dt.isoformat()},
        "end": {"dateTime": end_dt.isoformat()},
    }
    if timezone_str:
        event["start"]["timeZone"] = timezone_str
        event["end"]["timeZone"] = timezone_str

    created = service.events().insert(calendarId="primary", body=event).execute()
    return created


def _get_gmail_messages(q: str = "is:unread", max_results: int = 5) -> List[Dict[str, Any]]:
    service = _build_service("gmail", "v1")
    msgs = []
    res = service.users().messages().list(userId="me", q=q, maxResults=max_results).execute()
    for m in res.get("messages", []):
        msg = service.users().messages().get(userId="me", id=m["id"], format="full").execute()
        msgs.append(msg)
    return msgs


def read_unread_emails(max_results: int = 5) -> List[Dict[str, str]]:
    """Return a list of simple email summaries (from, subject, snippet) for the last unread messages."""
    msgs = _get_gmail_messages(q="is:unread", max_results=max_results)
    out = []
    for m in msgs:
        headers = {h["name"].lower(): h["value"] for h in m.get("payload", {}).get("headers", [])}
        out.append({
            "id": m.get("id"),
            "from": headers.get("from", ""),
            "subject": headers.get("subject", "(no subject)"),
            "snippet": m.get("snippet", ""),
        })
    return out


def send_email(to: str, subject: str, body: str) -> Dict[str, Any]:
    """Send an email via Gmail API.

    Returns the API response JSON.
    """
    service = _build_service("gmail", "v1")
    message = MIMEText(body)
    message["To"] = to
    message["From"] = "me"
    message["Subject"] = subject

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    body_obj = {"raw": raw}
    sent = service.users().messages().send(userId="me", body=body_obj).execute()
    return sent


def _format_event_time(value: str | None) -> str:
    if not value:
        return "all day"
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.strftime("%I:%M %p").lstrip("0")
    except Exception:
        return value


def _parse_clock_time(value: str, base_date: datetime) -> datetime | None:
    normalized = value.lower().replace(".", "").strip()
    formats = ["%I:%M %p", "%I %p", "%H:%M", "%H"]
    for fmt in formats:
        try:
            parsed = datetime.strptime(normalized, fmt).time()
            local_tz = datetime.now().astimezone().tzinfo or timezone.utc
            return datetime.combine(base_date.date(), parsed, tzinfo=local_tz)
        except ValueError:
            continue
    return None


def _parse_calendar_request(text: str) -> Dict[str, Any] | None:
    match = re.search(r"(?:create event|create calendar event|schedule meeting|add to calendar)\s*(.*)", text, re.IGNORECASE)
    if not match:
        return None

    content = match.group(1).strip()
    if not content:
        return None

    title = content
    start_text = ""
    end_text = ""

    from_match = re.search(r"\bfrom\b", content, re.IGNORECASE)
    to_match = re.search(r"\bto\b", content, re.IGNORECASE)
    if from_match and to_match and from_match.start() < to_match.start():
        title = content[:from_match.start()].strip(" ,:-") or "Calendar event"
        start_text = content[from_match.end():to_match.start()].strip(" ,:-")
        end_text = content[to_match.end():].strip(" ,:-")
    else:
        title = re.sub(r"\b(?:called|titled|named)\b", "", content, flags=re.IGNORECASE).strip(" ,:-")

    if not start_text or not end_text:
        return None

    base = datetime.now().astimezone()
    start_dt = _parse_clock_time(start_text, base)
    end_dt = _parse_clock_time(end_text, base)
    if not start_dt or not end_dt:
        return None

    if end_dt <= start_dt:
        end_dt = end_dt + timedelta(days=1)

    return {"summary": title or "Calendar event", "start": start_dt, "end": end_dt}


def _parse_email_request(text: str) -> Dict[str, str] | None:
    normalized = text.strip()
    recipient = ""
    subject = "Voice command email"
    body = ""

    to_match = re.search(r"\bto\b\s+(.*?)(?:\bsubject\b|\babout\b|\bmessage\b|\bbody\b|\bsaying\b|\bthat\b|$)", normalized, re.IGNORECASE)
    if to_match:
        recipient = to_match.group(1).strip(" ,:-")

    subject_match = re.search(r"\b(?:subject|about)\b\s+(.*?)(?:\bmessage\b|\bbody\b|\bsaying\b|$)", normalized, re.IGNORECASE)
    if subject_match:
        subject = subject_match.group(1).strip(" ,:-") or subject

    body_match = re.search(r"\b(?:message|body|saying|that)\b\s+(.*)$", normalized, re.IGNORECASE)
    if body_match:
        body = body_match.group(1).strip(" ,:-")

    if not recipient or not body:
        return None

    return {"to": recipient, "subject": subject, "body": body}


def execute(text: str, config: Dict[str, Any] | None = None, trigger: Dict[str, Any] | None = None, alarm_manager=None, handler=None) -> str:
    """Execute the matched plugin action for the provided voice command."""
    config = config or {}
    user_name = config.get("user_name", "Sir")
    trigger_name = (trigger or {}).get("name", "")
    text_lower = text.lower().strip()

    if trigger_name == "calendar_read_today" or "calendar" in text_lower and any(phrase in text_lower for phrase in ["what's on", "what is on", "read my events", "what do i have today", "today's events"]):
        events = read_todays_events(10)
        if not events:
            return f"You have no calendar events today, {user_name}."

        parts = []
        for event in events:
            parts.append(f"{_format_event_time(event.get('start'))}: {event.get('summary', '(no title)')}")
        return f"Today's calendar events are: {'; '.join(parts)}, {user_name}."

    if trigger_name == "calendar_create_event" or any(phrase in text_lower for phrase in ["create event", "schedule meeting", "add to calendar", "create calendar event"]):
        request = _parse_calendar_request(text)
        if not request:
            return f"I need a title plus start and end times for the event, {user_name}. Try: create event team sync from 3 pm to 4 pm."

        created = create_event(request["summary"], request["start"], request["end"])
        return f"Created calendar event '{created.get('summary', request['summary'])}', {user_name}."

    if trigger_name == "gmail_read_unread" or any(phrase in text_lower for phrase in ["read my emails", "check my email", "new emails", "read inbox"]):
        emails = read_unread_emails(5)
        if not emails:
            return f"You have no unread emails right now, {user_name}."

        lines = []
        for email_item in emails:
            sender = email_item.get("from") or "unknown sender"
            subject = email_item.get("subject") or "(no subject)"
            lines.append(f"from {sender}, subject {subject}")
        return f"Your latest unread emails are: {'; '.join(lines)}, {user_name}."

    if trigger_name == "gmail_send_email" or any(phrase in text_lower for phrase in ["send an email", "compose email", "email to"]):
        request = _parse_email_request(text)
        if not request:
            return f"I need a recipient and the message body to send the email, {user_name}. Try: send an email to alex@example.com subject update message meeting moved to 3 pm."

        sent = send_email(request["to"], request["subject"], request["body"])
        message_id = sent.get("id", "")
        suffix = f" Message id {message_id}." if message_id else ""
        return f"Email sent to {request['to']}, {user_name}.{suffix}"

    return ""


# Plugin discovery / registration hints
TRIGGERS = [
    {
        "name": "calendar_read_today",
        "description": "Read today's Google Calendar events",
        "phrases": [
            "what's on my calendar",
            "what is on my calendar",
            "read my events",
            "what do i have today",
            "today's events",
        ],
        "handler": "read_todays_events",
    },
    {
        "name": "calendar_create_event",
        "description": "Create a calendar event",
        "phrases": ["create event", "schedule meeting", "add to calendar", "create calendar event"],
        "handler": "create_event",
    },
    {
        "name": "gmail_read_unread",
        "description": "Read last unread emails",
        "phrases": ["read my emails", "check my email", "new emails", "read inbox"],
        "handler": "read_unread_emails",
    },
    {
        "name": "gmail_send_email",
        "description": "Send an email",
        "phrases": ["send an email", "compose email", "email to"],
        "handler": "send_email",
    },
]


if __name__ == "__main__":
    # quick local smoke tests (will run OAuth flow if no token)
    try:
        events = read_todays_events(5)
        print("Today's events:")
        for e in events:
            print(e)
    except Exception as e:
        print("Calendar test failed:", e)
