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

    if creds and not creds.valid:
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                with open(token_file, "w", encoding="utf-8") as f:  # persist the refreshed token
                    f.write(creds.to_json())
            except Exception:
                creds = None
        else:
            creds = None  # invalid and not refreshable (e.g. scopes changed): sign in again

    # Previously an invalid-but-present credential skipped this and was returned as if usable.
    if not creds or not creds.valid:
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
    # "Today" is the user's local day. UTC midnight bounds showed the wrong events
    # (e.g. yesterday's until 05:30 AM in India).
    now = datetime.now().astimezone()
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
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
        msg = service.users().messages().get(
            userId="me", id=m["id"], format="metadata", metadataHeaders=["From", "Subject"]
        ).execute()
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
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return "all day"  # all-day events carry a date only; parsing it gave "12:00 AM"
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo:
            dt = dt.astimezone()  # show the user's local time
        return dt.strftime("%I:%M %p").lstrip("0")
    except Exception:
        return value


_TIME_RE = r"\d{1,2}(?::\d{2})?\s*(?:[ap]\.?\s?m\.?)?"


def _split_clock(value: str):
    """Return (hour24_or_12, minute, meridiem|None) for "3", "3:30", "3 pm", "3 p.m."; None if invalid."""
    normalized = re.sub(r"[.\s]", "", value.lower())
    match = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?(am|pm)?", normalized)
    if not match:
        return None
    hour, minute, meridiem = int(match.group(1)), int(match.group(2) or 0), match.group(3)
    if minute > 59 or (meridiem and not 1 <= hour <= 12) or (not meridiem and hour > 23):
        return None
    return hour, minute, meridiem


def _parse_clock_time(value: str, base_date: datetime, default_meridiem: str | None = None) -> datetime | None:
    parts = _split_clock(value)
    if not parts:
        return None
    hour, minute, meridiem = parts
    meridiem = meridiem or (default_meridiem if hour <= 12 else None)
    if meridiem:
        hour = hour % 12 + (12 if meridiem == "pm" else 0)
    local_tz = datetime.now().astimezone().tzinfo or timezone.utc
    return datetime.combine(base_date.date(), datetime.min.time().replace(hour=hour, minute=minute), tzinfo=local_tz)


def _parse_calendar_request(text: str) -> Dict[str, Any] | None:
    match = re.search(r"(?:create calendar event|create event|schedule meeting|add to calendar)\s*(.*)", text, re.IGNORECASE)
    if not match:
        return None

    content = match.group(1).strip()
    day_offset = 1 if re.search(r"\btomorrow\b", content, re.IGNORECASE) else 0
    content = re.sub(r"\b(?:tomorrow|today)\b", "", content, flags=re.IGNORECASE)
    content = re.sub(r"\s+", " ", content).strip()
    if not content:
        return None

    base = datetime.now().astimezone() + timedelta(days=day_offset)

    # "<title> from <start> to <end>" - anchored on real clock times so a "to"/"from"
    # inside the title ("talk to John") can't be mistaken for the range separator.
    range_match = re.search(rf"\bfrom\s+({_TIME_RE})\s+(?:to|until|till)\s+({_TIME_RE})\s*[.]?$", content, re.IGNORECASE)
    at_match = None if range_match else re.search(rf"\b(?:at|for)\s+({_TIME_RE})\s*[.]?$", content, re.IGNORECASE)

    if range_match:
        start_text, end_text = range_match.group(1), range_match.group(2)
        title_part = content[:range_match.start()]
        end_dt = _parse_clock_time(end_text, base)
        end_parts = _split_clock(end_text)
        start_parts = _split_clock(start_text)
        start_dt = _parse_clock_time(start_text, base)
        # "from 3 to 4 pm": the start has no am/pm, so borrow it from the end time.
        if start_parts and end_parts and not start_parts[2] and end_parts[2] and end_dt:
            other = "am" if end_parts[2] == "pm" else "pm"
            for meridiem in (end_parts[2], other):
                candidate = _parse_clock_time(start_text, base, meridiem)
                if candidate and candidate < end_dt:
                    start_dt = candidate
                    break
        if not start_dt or not end_dt:
            return None
        if end_dt <= start_dt:
            end_dt += timedelta(days=1)
    elif at_match:
        start_dt = _parse_clock_time(at_match.group(1), base)
        if not start_dt:
            return None
        end_dt = start_dt + timedelta(hours=1)  # default length
        title_part = content[:at_match.start()]
    else:
        return None

    title = re.sub(r"\b(?:called|titled|named)\b", "", title_part, flags=re.IGNORECASE).strip(" ,:-")
    return {"summary": title or "Calendar event", "start": start_dt, "end": end_dt}


def _normalize_email_address(raw: str) -> str | None:
    """Turn dictated "alex at example dot com" into alex@example.com; None if not a valid address."""
    candidate = raw.strip().lower()
    candidate = re.sub(r"\s+at\s+", "@", candidate)
    candidate = re.sub(r"\s+dot\s+", ".", candidate)
    candidate = re.sub(r"\s+", "", candidate)
    return candidate if re.fullmatch(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", candidate) else None


def _display_sender(raw: str) -> str:
    """'Jane Doe <jane@x.com>' -> 'Jane Doe' (angle brackets sound terrible read aloud)."""
    match = re.match(r'\s*"?([^"<]+?)"?\s*<[^>]+>', raw or "")
    return match.group(1).strip() if match else (raw or "")


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
    user_name = (config or {}).get("user_name", "Sir")
    try:
        return _execute(text, config, trigger)
    except ImportError:
        return f"The Google libraries aren't installed, {user_name}. Run pip install google-api-python-client google-auth-oauthlib."
    except FileNotFoundError as e:
        return f"Google isn't set up yet, {user_name}. {e}"
    except Exception:
        logger.exception("Calendar/Gmail plugin error")
        return f"I couldn't complete that Google request, {user_name}."


def _execute(text: str, config: Dict[str, Any] | None, trigger: Dict[str, Any] | None) -> str:
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
            sender = _display_sender(email_item.get("from")) or "unknown sender"
            subject = email_item.get("subject") or "(no subject)"
            lines.append(f"from {sender}, subject {subject}")
        return f"Your latest unread emails are: {'; '.join(lines)}, {user_name}."

    if trigger_name == "gmail_send_email" or any(phrase in text_lower for phrase in ["send an email", "compose email", "email to"]):
        request = _parse_email_request(text)
        if not request:
            return f"I need a recipient and the message body to send the email, {user_name}. Try: send an email to alex@example.com subject update message meeting moved to 3 pm."

        address = _normalize_email_address(request["to"])
        if not address:
            return f"I couldn't turn '{request['to']}' into an email address, {user_name}. Please say it like alex at example dot com."

        send_email(address, request["subject"], request["body"])
        return f"Email sent to {address}, {user_name}."

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
