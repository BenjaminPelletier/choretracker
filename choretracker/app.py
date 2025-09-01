from datetime import datetime, timedelta, date
from pathlib import Path
import json
import os
import subprocess
from urllib.parse import urlparse
from heapq import heappush, heappop
from typing import Iterator
from itertools import count
from collections import Counter
import secrets
import logging

from fastapi import FastAPI, HTTPException, Request
from starlette.requests import Request as StarletteRequest
from fastapi.responses import HTMLResponse, RedirectResponse, Response, FileResponse, JSONResponse
from fastapi.exception_handlers import http_exception_handler
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware
from sqlmodel import create_engine, Session, select
from sqlalchemy import event
from pydantic.json import pydantic_encoder
from markdown import markdown as md
from markupsafe import Markup
import bleach
import base64
import posixpath
from jinja2 import pass_context

from .time_utils import get_now, parse_datetime, ensure_tz
from .users import (
    UserStore,
    init_db,
    process_profile_picture,
    pwd_context,
    is_url_safe,
)
from .calendar import (
    CalendarEntry,
    CalendarEntryStore,
    CalendarEntryType,
    ChoreCompletion,
    ChoreCompletionStore,
    Delegation,
    InstanceDuration,
    InstanceNote,
    Offset,
    Recurrence,
    RecurrenceType,
    TimePeriod,
    enumerate_time_periods,
    find_time_period,
    find_delegation,
    find_instance_duration,
    find_instance_note,
    responsible_for,
)
from .settings import SettingsStore


LOGOUT_DURATION = timedelta(minutes=1)
MAX_UPCOMING = 5

db_path = os.getenv("CHORETRACKER_DB", "choretracker.db")
engine = create_engine(
    f"sqlite:///{db_path}",
    connect_args={"check_same_thread": False},
    json_serializer=lambda obj: json.dumps(obj, default=pydantic_encoder),
)
@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()
init_db(engine)
user_store = UserStore(engine)
calendar_store = CalendarEntryStore(engine)
completion_store = ChoreCompletionStore(engine)
settings_store = SettingsStore(engine)
LOGOUT_DURATION = timedelta(minutes=settings_store.get_logout_duration())
ALL_PERMISSIONS = [
    "chores.read",
    "chores.write",
    "chores.complete_on_time",
    "chores.complete_overdue",
    "chores.override_complete",
    "events.read",
    "events.write",
    "reminders.read",
    "reminders.write",
    "iam",
]

READ_PERMS = {
    CalendarEntryType.Event: "events.read",
    CalendarEntryType.Reminder: "reminders.read",
    CalendarEntryType.Chore: "chores.read",
}

WRITE_PERMS = {
    CalendarEntryType.Event: "events.write",
    CalendarEntryType.Reminder: "reminders.write",
    CalendarEntryType.Chore: "chores.write",
}

app = FastAPI()

logger = logging.getLogger(__name__)

BASE_PATH = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_PATH / "templates"))
templates.env.globals["all_users"] = lambda: sorted(
    user_store.list_users(include_viewer=True),
    key=lambda u: (u.username == "Viewer", u.username),
)
templates.env.globals["user_has"] = user_store.has_permission
templates.env.globals["WRITE_PERMS"] = WRITE_PERMS
templates.env.globals["timedelta"] = timedelta
templates.env.globals["LOGOUT_DURATION"] = LOGOUT_DURATION


def _make_relative(current_path: str, target_path: str) -> str:
    """Return ``target_path`` relative to ``current_path``."""
    cur_dir = current_path if current_path.endswith("/") else current_path.rsplit("/", 1)[0] + "/"
    rel_path = posixpath.relpath(target_path, start=cur_dir)
    if rel_path == ".":
        # ``posixpath.relpath`` collapses paths like ``/calendar/new`` relative to
        # ``/calendar/new/Chore`` to ``.``. Returning ``/`` would incorrectly point
        # to the site root; instead return the absolute target path so forms post
        # to the intended endpoint.
        return target_path
    if not rel_path.startswith("."):
        rel_path = "./" + rel_path
    return rel_path


def relative_url_for(request: Request, name: str, /, **path_params: str) -> str:
    target = str(request.app.url_path_for(name, **path_params))
    return _make_relative(request.url.path, target)


@pass_context
def _jinja_url_for(context, name: str, /, **path_params: str) -> str:  # type: ignore[override]
    request: Request = context["request"]
    return relative_url_for(request, name, **path_params)


templates.env.globals["url_for"] = _jinja_url_for
def format_datetime(dt: datetime | None, include_day: bool = False) -> str:
    if not dt:
        return ""
    fmt = "%Y-%m-%d %H:%M"
    if include_day:
        fmt = "%A " + fmt
    return dt.strftime(fmt)
templates.env.filters["format_datetime"] = format_datetime


def format_completion_time(completed: datetime, due: datetime) -> str:
    """Format ``completed`` dropping leading parts common with ``due``."""
    due_str = format_datetime(due, include_day=True)
    comp_str = format_datetime(completed, include_day=True)
    due_parts = due_str.split(" ")
    comp_parts = comp_str.split(" ")
    prefix = 0
    for d, c in zip(due_parts, comp_parts):
        if d == c:
            prefix += len(d) + 1  # account for trailing space
        else:
            break
    return comp_str[prefix:]


templates.env.filters["format_completion_time"] = format_completion_time


def format_duration(td: timedelta | None) -> str:
    if not td:
        return ""
    td = td - timedelta(seconds=td.seconds % 60, microseconds=td.microseconds)
    s = str(td)
    if s.endswith(":00"):
        s = s[:-3]
    return s


def format_offset(offset: Offset | None) -> str:
    if not offset:
        return ""
    parts: list[str] = []
    if offset.years:
        parts.append(f"{offset.years}Y")
    if offset.months:
        parts.append(f"{offset.months}M")
    if offset.exact_duration_seconds:
        td = timedelta(seconds=offset.exact_duration_seconds)
        days = td.days
        hours, remainder = divmod(td.seconds, 3600)
        minutes = remainder // 60
        if days:
            parts.append(f"{days}d")
        if hours:
            parts.append(f"{hours}h")
        if minutes:
            parts.append(f"{minutes}m")
    return "".join(parts)


templates.env.filters["format_duration"] = format_duration
templates.env.filters["format_offset"] = format_offset


ALLOWED_TAGS = bleach.sanitizer.ALLOWED_TAGS | {
    "p",
    "pre",
    "code",
    "hr",
    "br",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
}

ALLOWED_ATTRIBUTES = {
    **bleach.sanitizer.ALLOWED_ATTRIBUTES,
    "a": ["href", "title", "rel"],
    "img": ["src", "alt", "title"],
}


def render_markdown(text: str) -> Markup:
    if not text:
        return Markup("")
    html = md(text)
    sanitized = bleach.clean(html, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRIBUTES, strip=True)
    return Markup(sanitized)


templates.env.filters["markdown"] = render_markdown


def b64encode_filter(s: str) -> str:
    return base64.b64encode(s.encode()).decode()


templates.env.filters["b64encode"] = b64encode_filter

def time_range_summary(start: datetime | None, end: datetime | None) -> str:
    if not start:
        return ""
    start = start.replace(second=0, microsecond=0)
    start_str = start.strftime("%a %Y-%m-%d %H:%M")
    if end is None:
        return f"From {start_str}, indefinitely"
    end = end.replace(second=0, microsecond=0)
    if start.year != end.year:
        end_fmt = "%a %Y-%m-%d"
    elif start.month != end.month or start.day != end.day:
        end_fmt = "%a %m-%d"
    else:
        end_fmt = ""
    if start.hour != end.hour or start.minute != end.minute:
        end_fmt = f"{end_fmt + ' ' if end_fmt else ''}%H:%M"
    end_str = end.strftime(end_fmt).strip()
    return f"{start_str} to {end_str}"


templates.env.globals["time_range_summary"] = time_range_summary
app.mount("/static", StaticFiles(directory=str(BASE_PATH / "static")), name="static")


def entry_time_bounds(entry: CalendarEntry) -> tuple[datetime, datetime | None]:
    periods = enumerate_time_periods(entry)
    first = next(periods, None)
    if not first:
        return (entry.first_start, None)
    start = first.start
    end = first.end
    if entry.none_after is None and any(
        rec.type != RecurrenceType.OneTime for rec in entry.recurrences
    ):
        return (start, None)
    for p in periods:
        end = p.end
    return (start, end)


def has_past_instances(entry: CalendarEntry, now: datetime | None = None) -> bool:
    if now is None:
        now = get_now()
    for period in enumerate_time_periods(entry, include_skipped=True):
        if period.start < now:
            return True
        break
    return False


def require_permission(request: Request, permission: str) -> None:
    username = request.session.get("user")
    if not username or not user_store.get(username):
        request.session.clear()
        raise HTTPException(
            status_code=303, headers={"Location": relative_url_for(request, "login")}
        )
    if not user_store.has_permission(username, permission):
        request.session["flash"] = "You are not allowed to perform that action."
        raise HTTPException(
            status_code=303, headers={"Location": relative_url_for(request, "index")}
        )


def server_version() -> str:
    env_ver = os.getenv("CHORETRACKER_VERSION")
    if env_ver:
        return env_ver
    try:
        repo_root = BASE_PATH.parent
        commit = (
            subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=repo_root)
            .decode()
            .strip()
        )
        status = subprocess.check_output(["git", "status", "--porcelain"], cwd=repo_root).decode()
        dirty = "-dirty" if status.strip() else ""
        return f"Commit: {commit}{dirty}"
    except Exception:
        return "Unknown"


def can_edit_entry(username: str, entry: CalendarEntry) -> bool:
    if not username:
        return False
    if username in entry.managers:
        return True
    return user_store.has_permission(username, "admin")


def split_entry_if_past(entry_id: int, entry: CalendarEntry, now: datetime | None = None) -> tuple[int, CalendarEntry, bool]:
    """Split ``entry`` at ``now`` if it has instances in the past.

    Returns ``(new_id, entry_obj, did_split)`` where ``entry_obj`` is the
    original entry if no split occurred or the new entry if it did.
    """
    if now is None:
        now = get_now()
    has_past = False
    for period in enumerate_time_periods(entry):
        if period.start < now:
            has_past = True
        else:
            break
    if has_past:
        new_entry = calendar_store.split(entry_id, now)
        if not new_entry:
            raise HTTPException(status_code=404)
        return new_entry.id, new_entry, True
    return entry_id, entry, False


def require_entry_read_permission(request: Request, entry_type: CalendarEntryType) -> None:
    require_permission(request, READ_PERMS[entry_type])


def require_entry_write_permission(request: Request, entry: CalendarEntry) -> None:
    username = request.session.get("user")
    if not can_edit_entry(username, entry):
        request.session["flash"] = "You are not allowed to perform that action."
        raise HTTPException(status_code=303, headers={"Location": relative_url_for(request, "index")})


class EnsureUserMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        session = request.session
        path = request.url.path

        user = session.get("user")
        now = get_now().timestamp()
        if user:
            if not user_store.get(user):
                session.clear()
                if not (path == "/login" or path.startswith("/static")):
                    return RedirectResponse(url=relative_url_for(request, "login"))
            else:
                last = session.get("last_active", now)
                if user != "Viewer" and now - last > LOGOUT_DURATION.total_seconds():
                    session["user"] = "Viewer"
                    user = "Viewer"
                session["last_active"] = now
        elif not (path == "/login" or path.startswith("/static")):
            return RedirectResponse(url=relative_url_for(request, "login"))

        response = await call_next(request)
        return response


class CSRFMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if os.getenv("CHORETRACKER_DISABLE_CSRF") == "1":
            return await call_next(request)
        session = request.session
        token = session.get("csrf_token")
        if not token:
            token = secrets.token_urlsafe(32)
            session["csrf_token"] = token
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            body = await request.body()
            content_type = request.headers.get("content-type", "")
            csrf_token = request.headers.get("x-csrf-token") or request.query_params.get(
                "csrf_token"
            )
            def make_receive():
                sent = False

                async def receive():
                    nonlocal sent
                    if sent:
                        return {"type": "http.request", "body": b"", "more_body": False}
                    sent = True
                    return {
                        "type": "http.request",
                        "body": body,
                        "more_body": False,
                    }

                return receive

            if not csrf_token and (
                content_type.startswith("application/x-www-form-urlencoded")
                or content_type.startswith("multipart/form-data")
            ):
                form_request = StarletteRequest(request.scope, make_receive())
                form = await form_request.form()
                csrf_token = form.get("csrf_token")

            request._receive = make_receive()

            if not csrf_token or csrf_token != session.get("csrf_token"):
                logger.warning(
                    "Invalid CSRF token for %s %s", request.method, request.url.path
                )
                if request.url.path == "/login":
                    return templates.TemplateResponse(
                        request,
                        "login.html",
                        {"error": "Invalid CSRF token"},
                        status_code=400,
                    )
                return JSONResponse({"error": "Invalid CSRF token"}, status_code=400)
        return await call_next(request)


app.add_middleware(EnsureUserMiddleware)
app.add_middleware(CSRFMiddleware)
session_secret = os.getenv("CHORETRACKER_SECRET_KEY")
if not session_secret:
    raise RuntimeError("CHORETRACKER_SECRET_KEY environment variable is not set")
app.add_middleware(SessionMiddleware, secret_key=session_secret)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    now = get_now()
    overdue: list[tuple[CalendarEntry, TimePeriod, list[str], bool]] = []
    current: list[
        tuple[CalendarEntry, TimePeriod, ChoreCompletion | None, list[str], bool]
    ] = []
    upcoming_heap: list[tuple[datetime, int, CalendarEntry, TimePeriod, Iterator[TimePeriod]]] = []
    counter = count()

    for entry in calendar_store.list_entries():
        gen = enumerate_time_periods(entry)
        for period in gen:
            completion = None
            if entry.type == CalendarEntryType.Chore:
                completion = completion_store.get(
                    entry.id, period.recurrence_index, period.instance_index
                )
                if completion:
                    if period.end <= now:
                        continue
                    if period.start <= now:
                        current.append(
                            (
                                entry,
                                period,
                                completion,
                                responsible_for(
                                    entry,
                                    period.recurrence_index,
                                    period.instance_index,
                                ),
                                bool(
                                    find_instance_note(
                                        entry,
                                        period.recurrence_index,
                                        period.instance_index,
                                    )
                                ),
                            )
                        )
                        nxt = next(gen, None)
                        if nxt:
                            heappush(
                                upcoming_heap,
                                (nxt.start, next(counter), entry, nxt, gen),
                            )
                        break
                    else:
                        continue
            if period.end <= now:
                if entry.type == CalendarEntryType.Chore:
                    overdue.append(
                        (
                            entry,
                            period,
                            responsible_for(
                                entry,
                                period.recurrence_index,
                                period.instance_index,
                            ),
                            bool(
                                find_instance_note(
                                    entry,
                                    period.recurrence_index,
                                    period.instance_index,
                                )
                            ),
                        )
                    )
            elif period.start <= now:
                current.append(
                    (
                        entry,
                        period,
                        completion,
                        responsible_for(
                            entry,
                            period.recurrence_index,
                            period.instance_index,
                        ),
                        bool(
                            find_instance_note(
                                entry,
                                period.recurrence_index,
                                period.instance_index,
                            )
                        ),
                    )
                )
                nxt = next(gen, None)
                if nxt:
                    heappush(upcoming_heap, (nxt.start, next(counter), entry, nxt, gen))
                break
            else:
                heappush(
                    upcoming_heap,
                    (period.start, next(counter), entry, period, gen),
                )
                break

    upcoming: list[tuple[CalendarEntry, TimePeriod, list[str], bool]] = []
    while upcoming_heap and len(upcoming) < MAX_UPCOMING:
        _, _, entry, period, gen = heappop(upcoming_heap)
        upcoming.append(
            (
                entry,
                period,
                responsible_for(entry, period.recurrence_index, period.instance_index),
                bool(
                    find_instance_note(
                        entry, period.recurrence_index, period.instance_index
                    )
                ),
            )
        )
        nxt = next(gen, None)
        if nxt:
            heappush(upcoming_heap, (nxt.start, next(counter), entry, nxt, gen))

    overdue.sort(key=lambda x: (x[1].end, x[0].title))
    current.sort(key=lambda x: (x[2] is not None, x[1].end, x[0].title))

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "overdue": overdue,
            "now_periods": current,
            "upcoming": upcoming,
            "CalendarEntryType": CalendarEntryType,
            "now_ts": now.timestamp(),
        },
    )


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if request.session.get("user"):
        return RedirectResponse(url=relative_url_for(request, "index"), status_code=303)
    return templates.TemplateResponse(request, "login.html")


@app.post("/login")
async def login(request: Request):
    form = await request.form()
    username = form.get("username", "")
    password = form.get("password", "")

    user = user_store.verify(username, password)
    if user:
        request.session["user"] = user.username
        request.session["last_active"] = get_now().timestamp()
        return RedirectResponse(url=relative_url_for(request, "index"), status_code=303)

    return templates.TemplateResponse(
        request,
        "login.html",
        {"error": "Invalid credentials"},
        status_code=400,
    )


@app.exception_handler(HTTPException)
async def handle_http_exception(request: Request, exc: HTTPException):
    if exc.status_code == 400 and request.url.path == "/login":
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": exc.detail},
            status_code=400,
        )
    return await http_exception_handler(request, exc)


def _switch_target(request: Request, next: str | None) -> str:
    target = relative_url_for(request, "index")
    if next:
        parsed = urlparse(next)
        if not parsed.scheme and not parsed.netloc:
            path = posixpath.normpath(parsed.path)
            if not path.startswith("//"):
                norm_parsed = urlparse(path)
                if not norm_parsed.scheme and not norm_parsed.netloc:
                    target = path
                    if parsed.query:
                        target += f"?{parsed.query}"
    return target


@app.get("/switch/{username}")
async def switch_user(request: Request, username: str, next: str | None = None, pin: str | None = None):
    user = user_store.get(username)
    if user and (not user.pin_hash or (pin and pwd_context.verify(pin, user.pin_hash))):
        request.session["user"] = username
        request.session["last_active"] = get_now().timestamp()
        return RedirectResponse(url=_switch_target(request, next), status_code=303)
    request.session["flash"] = "Invalid PIN"
    referer = request.headers.get("referer") or relative_url_for(request, "index")
    return RedirectResponse(url=referer, status_code=303)


@app.post("/switch/{username}")
async def switch_user_post(request: Request, username: str, next: str | None = None):
    form = await request.form()
    pin = form.get("pin", "")
    user = user_store.get(username)
    if not user:
        raise HTTPException(status_code=404)
    if user.pin_hash and not (pin and pwd_context.verify(pin, user.pin_hash)):
        return JSONResponse({"error": "Invalid PIN"}, status_code=400)
    request.session["user"] = username
    request.session["last_active"] = get_now().timestamp()
    return JSONResponse({"redirect": _switch_target(request, next)})


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url=relative_url_for(request, "login"), status_code=303)


@app.get("/system", response_class=HTMLResponse)
async def system(request: Request):
    require_permission(request, "admin")
    return templates.TemplateResponse(
        request,
        "system.html",
        {
            "version": server_version(),
            "logout_minutes": int(LOGOUT_DURATION.total_seconds() // 60),
        },
    )


@app.post("/system/logout_duration")
async def update_logout_duration(request: Request):
    require_permission(request, "admin")
    data = await request.json()
    minutes = data.get("minutes")
    if not isinstance(minutes, int) or minutes < 1 or minutes > 15:
        return JSONResponse({"error": "Invalid value"}, status_code=400)
    settings_store.set_logout_duration(minutes)
    global LOGOUT_DURATION
    LOGOUT_DURATION = timedelta(minutes=minutes)
    templates.env.globals["LOGOUT_DURATION"] = LOGOUT_DURATION
    return JSONResponse({"ok": True})


@app.get("/users/{username}/profile_picture")
async def profile_picture(username: str):
    headers = {"Cache-Control": "no-cache, no-store, max-age=0"}
    user = user_store.get(username)
    if user and user.profile_picture:
        return Response(user.profile_picture, media_type="image/png", headers=headers)
    if username == "Viewer":
        return FileResponse(BASE_PATH / "static" / "viewer_profile.png", headers=headers)
    return FileResponse(BASE_PATH / "static" / "default_profile.png", headers=headers)


@app.get("/calendar/new/{entry_type}", response_class=HTMLResponse)
async def new_calendar_entry(request: Request, entry_type: str):
    if entry_type not in {"Event", "Reminder", "Chore"}:
        raise HTTPException(status_code=404)
    perm_map = {
        "Event": "events.write",
        "Reminder": "reminders.write",
        "Chore": "chores.write",
    }
    require_permission(request, perm_map[entry_type])
    current_user = request.session.get("user")
    return templates.TemplateResponse(
        request,
        "calendar/form.html",
        {
            "entry_type": entry_type,
            "entry": None,
            "current_user": current_user,
            "RecurrenceType": RecurrenceType,
        },
    )


@app.post("/calendar/new")
async def create_calendar_entry(request: Request):
    form = await request.form()
    title = form.get("title", "").strip()
    description = form.get("description", "").strip()
    entry_type_str = form.get("type", "Event")
    try:
        entry_type = CalendarEntryType(entry_type_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid entry type")
    perm_map = {
        CalendarEntryType.Event: "events.write",
        CalendarEntryType.Reminder: "reminders.write",
        CalendarEntryType.Chore: "chores.write",
    }
    require_permission(request, perm_map[entry_type])
    current_user = request.session.get("user")
    first_start_str = form.get("first_start")
    if not first_start_str:
        raise HTTPException(status_code=400, detail="first_start required")
    first_start = parse_datetime(first_start_str)

    duration = timedelta(
        days=int(form.get("duration_days") or 0),
        hours=int(form.get("duration_hours") or 0),
        minutes=int(form.get("duration_minutes") or 0),
    )
    if duration <= timedelta(0):
        raise HTTPException(status_code=400, detail="Duration must be greater than 0")

    recurrence_types = form.getlist("recurrence_type[]")
    offset_days = form.getlist("offset_days[]")
    offset_months = form.getlist("offset_months[]")
    offset_years = form.getlist("offset_years[]")
    offset_hours = form.getlist("offset_hours[]")
    offset_minutes = form.getlist("offset_minutes[]")
    rec_resp_json = form.getlist("recurrence_responsible[]")
    rec_del_json = form.getlist("recurrence_delegations[]")

    recurrences = []
    for i, rtype in enumerate(recurrence_types):
        days = int(offset_days[i]) if i < len(offset_days) and offset_days[i] else 0
        months = int(offset_months[i]) if i < len(offset_months) and offset_months[i] else 0
        years = int(offset_years[i]) if i < len(offset_years) and offset_years[i] else 0
        hours = int(offset_hours[i]) if i < len(offset_hours) and offset_hours[i] else 0
        minutes = int(offset_minutes[i]) if i < len(offset_minutes) and offset_minutes[i] else 0

        off = None
        if days or months or years or hours or minutes:
            dur = timedelta(days=days, hours=hours, minutes=minutes)
            off = Offset(
                exact_duration_seconds=int(dur.total_seconds()) if (days or hours or minutes) else None,
                months=months or None,
                years=years or None,
            )
        responsible_users: list[str] = []
        if i < len(rec_resp_json) and rec_resp_json[i]:
            responsible_users = json.loads(rec_resp_json[i])
        delegations: list[Delegation] = []
        if i < len(rec_del_json) and rec_del_json[i]:
            delegations = [Delegation.model_validate(d) for d in json.loads(rec_del_json[i])]
        recurrences.append(
            Recurrence(
                type=RecurrenceType(rtype),
                offset=off,
                skipped_instances=[],
                responsible=responsible_users,
                delegations=delegations,
            )
        )

    none_after_str = form.get("none_after")
    none_after = parse_datetime(none_after_str) if none_after_str else None
    none_before_str = form.get("none_before")
    none_before = parse_datetime(none_before_str) if none_before_str else None

    responsible = form.getlist("responsible")
    managers = form.getlist("managers")
    if not managers:
        raise HTTPException(status_code=400, detail="At least one manager required")
    if entry_type == CalendarEntryType.Chore and not responsible:
        raise HTTPException(status_code=400, detail="At least one responsible user required")
    if entry_type == CalendarEntryType.Chore:
        for rec in recurrences:
            for d in rec.delegations:
                if not d.responsible:
                    raise HTTPException(status_code=400, detail="Delegations must have responsible users")

    entry = CalendarEntry(
        title=title,
        description=description,
        type=entry_type,
        first_start=first_start,
        duration_seconds=int(duration.total_seconds()),
        recurrences=recurrences,
        none_after=none_after,
        none_before=none_before,
        responsible=responsible,
        managers=managers,
    )
    if not user_store.has_permission(current_user, "admin") and has_past_instances(entry):
        raise HTTPException(status_code=400, detail="Cannot create entry in the past")
    calendar_store.create(entry)
    return RedirectResponse(url=relative_url_for(request, "index"), status_code=303)


@app.get("/calendar/list/{entry_type}", response_class=HTMLResponse)
async def list_calendar_entries(request: Request, entry_type: str):
    try:
        etype = CalendarEntryType(entry_type)
    except ValueError:
        raise HTTPException(status_code=404)
    require_entry_read_permission(request, etype)
    entries = [e for e in calendar_store.list_entries() if e.type == etype]
    counts = Counter(e.title for e in entries)
    now = get_now()
    active_entries = []
    past_entries = []
    start_map = {}
    can_delete_map: dict[int, bool] = {}
    for entry in entries:
        start, end = entry_time_bounds(entry)
        start_map[entry.id] = start
        can_delete_map[entry.id] = (
            not completion_store.list_for_entry(entry.id)
            and not any(rec.delegations for rec in entry.recurrences)
        )
        if counts[entry.title] > 1:
            entry.title = f"{entry.title} ({time_range_summary(start, end)})"
        if end is None or end > now:
            active_entries.append(entry)
        else:
            past_entries.append(entry)
    active_entries.sort(key=lambda e: start_map[e.id], reverse=True)
    past_entries.sort(key=lambda e: start_map[e.id], reverse=True)
    current_user = request.session.get("user")
    return templates.TemplateResponse(
        request,
        "calendar/list.html",
        {
            "active_entries": active_entries,
            "past_entries": past_entries,
            "entry_type": etype,
            "current_user": current_user,
            "can_delete": can_delete_map,
        },
    )


@app.get("/chore_completions", response_class=HTMLResponse)
async def list_chore_completions(
    request: Request,
    limit: int = 15,
    after: str | None = None,
    before: str | None = None,
    on: str | None = None,
):
    require_permission(request, "chores.read")
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 15
    limit = max(0, limit)
    after_dt = parse_datetime(after) if after else None
    before_dt = parse_datetime(before) if before else None
    on_date = date.fromisoformat(on) if on else None
    tz = get_now().tzinfo
    with Session(engine) as session:
        stmt = select(ChoreCompletion).order_by(ChoreCompletion.completed_at.desc())
        if after_dt:
            stmt = stmt.where(ChoreCompletion.completed_at > after_dt)
        if before_dt:
            stmt = stmt.where(ChoreCompletion.completed_at < before_dt)
        if on_date:
            start = datetime.combine(on_date, datetime.min.time()).replace(tzinfo=tz)
            end = start + timedelta(days=1)
            stmt = stmt.where(
                (ChoreCompletion.completed_at >= start)
                & (ChoreCompletion.completed_at < end)
            )
        stmt = stmt.limit(limit)
        comps = session.exec(stmt).all()
    now = get_now()
    today = now.date()
    yesterday = today - timedelta(days=1)
    today_list = []
    yesterday_list = []
    earlier_list = []
    for comp in comps:
        comp.completed_at = ensure_tz(comp.completed_at)
        if comp.completed_at > now and comp.completed_at.date() != today:
            continue
        entry = calendar_store.get(comp.entry_id)
        if not entry:
            continue
        has_note = bool(
            find_instance_note(entry, comp.recurrence_index, comp.instance_index)
        )
        item = (entry, comp, has_note)
        cdate = comp.completed_at.date()
        if cdate == today:
            today_list.append(item)
        elif cdate == yesterday:
            yesterday_list.append(item)
        else:
            earlier_list.append(item)
    return templates.TemplateResponse(
        request,
        "completions/list.html",
        {"today": today_list, "yesterday": yesterday_list, "earlier": earlier_list},
    )


@app.get("/calendar/entry/{entry_id}", response_class=HTMLResponse)
async def view_calendar_entry(
    request: Request, entry_id: int, past_entries: int = 5, upcoming_entries: int = 5
):
    entry = calendar_store.get(entry_id)
    if not entry:
        raise HTTPException(status_code=404)
    require_entry_read_permission(request, entry.type)
    entry_start, entry_end = entry_time_bounds(entry)
    prev_entry = (
        calendar_store.get(entry.previous_entry) if entry.previous_entry else None
    )
    next_entry = (
        calendar_store.get(entry.next_entry) if entry.next_entry else None
    )
    prev_start = prev_end = next_start = next_end = None
    if prev_entry:
        prev_start, prev_end = entry_time_bounds(prev_entry)
    if next_entry:
        next_start, next_end = entry_time_bounds(next_entry)
    current_user = request.session.get("user")
    comps_list = completion_store.list_for_entry(entry_id)
    comp_map = {(c.recurrence_index, c.instance_index): c for c in comps_list}
    completion_periods: list[
        tuple[TimePeriod, ChoreCompletion, bool, bool, list[str], bool]
    ] = []
    for comp in comps_list:
        period = find_time_period(
            entry, comp.recurrence_index, comp.instance_index, include_skipped=True
        )
        if not period:
            continue
        can_remove = comp.completed_by == current_user or user_store.has_permission(
            current_user, "chores.override_complete"
        )
        is_skipped = False
        if 0 <= comp.recurrence_index < len(entry.recurrences):
            rec = entry.recurrences[comp.recurrence_index]
            if not isinstance(rec, Recurrence):
                rec = Recurrence.model_validate(rec)
                entry.recurrences[comp.recurrence_index] = rec
            is_skipped = comp.instance_index in rec.skipped_instances
        responsible = responsible_for(
            entry, comp.recurrence_index, comp.instance_index
        )
        has_note = bool(
            find_instance_note(entry, comp.recurrence_index, comp.instance_index)
        )
        completion_periods.append(
            (period, comp, can_remove, is_skipped, responsible, has_note)
        )
    now = get_now()
    past_noncompleted: list[
        tuple[TimePeriod, ChoreCompletion | None, bool, bool, list[str], bool]
    ] = []
    upcoming: list[
        tuple[TimePeriod, ChoreCompletion | None, bool, bool, list[str], bool]
    ] = []
    for period in enumerate_time_periods(entry, include_skipped=True):
        key = (period.recurrence_index, period.instance_index)
        if key in comp_map:
            continue
        is_skipped = False
        if 0 <= period.recurrence_index < len(entry.recurrences):
            rec = entry.recurrences[period.recurrence_index]
            if not isinstance(rec, Recurrence):
                rec = Recurrence.model_validate(rec)
                entry.recurrences[period.recurrence_index] = rec
            is_skipped = period.instance_index in rec.skipped_instances
        responsible = responsible_for(
            entry, period.recurrence_index, period.instance_index
        )
        has_note = bool(
            find_instance_note(entry, period.recurrence_index, period.instance_index)
        )
        if period.end < now:
            past_noncompleted.append(
                (period, None, False, is_skipped, responsible, has_note)
            )
        else:
            if len(upcoming) < upcoming_entries:
                upcoming.append(
                    (period, None, False, is_skipped, responsible, has_note)
                )
            else:
                break
    past_instances = past_noncompleted + completion_periods
    past_instances.sort(key=lambda x: x[0].start)
    past_instances = past_instances[-past_entries:]
    upcoming.sort(key=lambda x: x[0].start)
    can_delete = (
        not comps_list and not any(rec.delegations for rec in entry.recurrences)
    )
    return templates.TemplateResponse(
        request,
        "calendar/view.html",
        {
            "entry": entry,
            "can_edit": can_edit_entry(current_user, entry),
            "can_delete": can_delete,
            "past_instances": past_instances,
            "upcoming_instances": upcoming,
            "past_entries": past_entries,
            "upcoming_entries": upcoming_entries,
            "CalendarEntryType": CalendarEntryType,
            "RecurrenceType": RecurrenceType,
            "entry_start": entry_start,
            "entry_end": entry_end,
            "prev_entry": prev_entry,
            "next_entry": next_entry,
            "prev_start": prev_start,
            "prev_end": prev_end,
            "next_start": next_start,
            "next_end": next_end,
        },
    )


@app.get(
    "/calendar/entry/{entry_id}/period/{rindex}/{iindex}",
    response_class=HTMLResponse,
)
async def view_time_period(
    request: Request, entry_id: int, rindex: int, iindex: int
):
    entry = calendar_store.get(entry_id)
    if not entry:
        raise HTTPException(status_code=404)
    require_entry_read_permission(request, entry.type)
    period = find_time_period(
        entry, rindex, iindex, include_skipped=True
    )
    if not period:
        raise HTTPException(status_code=404)
    completion = None
    if entry.type == CalendarEntryType.Chore:
        completion = completion_store.get(entry_id, rindex, iindex)
    is_skipped = False
    if 0 <= rindex < len(entry.recurrences):
        rec = entry.recurrences[rindex]
        if not isinstance(rec, Recurrence):
            rec = Recurrence.model_validate(rec)
            entry.recurrences[rindex] = rec
        is_skipped = iindex in rec.skipped_instances
    delegation = find_delegation(entry, rindex, iindex)
    note_obj = find_instance_note(entry, rindex, iindex)
    note = note_obj.note if note_obj else None
    dur_obj = find_instance_duration(entry, rindex, iindex)
    dur_override = (
        timedelta(seconds=dur_obj.duration_seconds) if dur_obj else None
    )
    current_user = request.session.get("user")
    return templates.TemplateResponse(
        request,
        "calendar/timeperiod.html",
        {
            "entry": entry,
            "period": period,
            "completion": completion,
            "is_skipped": is_skipped,
            "can_edit": can_edit_entry(current_user, entry),
            "now": get_now(),
            "CalendarEntryType": CalendarEntryType,
            "responsible": responsible_for(entry, rindex, iindex),
            "delegation": delegation,
            "note": note,
            "duration_override": dur_override,
        },
    )


@app.get("/calendar/{entry_id}/edit", response_class=HTMLResponse)
async def edit_calendar_entry(request: Request, entry_id: int):
    entry = calendar_store.get(entry_id)
    if not entry:
        raise HTTPException(status_code=404)
    require_entry_write_permission(request, entry)
    entry_dict = entry.model_dump()
    entry_dict["first_start"] = entry.first_start
    entry_dict["duration_seconds"] = entry.duration_seconds
    entry_data = json.loads(json.dumps(entry_dict, default=pydantic_encoder))
    current_user = request.session.get("user")
    return templates.TemplateResponse(
        request,
        "calendar/form.html",
        {
            "entry_type": entry.type.value,
            "entry": entry,
            "entry_data": entry_data,
            "current_user": current_user,
            "RecurrenceType": RecurrenceType,
        },
    )


@app.post("/calendar/{entry_id}/edit")
async def update_calendar_entry(request: Request, entry_id: int):
    existing = calendar_store.get(entry_id)
    if not existing:
        raise HTTPException(status_code=404)
    require_entry_write_permission(request, existing)
    current_user = request.session.get("user")

    form = await request.form()
    title = form.get("title", "").strip()
    description = form.get("description", "").strip()
    entry_type = existing.type

    first_start_str = form.get("first_start")
    if not first_start_str:
        raise HTTPException(status_code=400, detail="first_start required")
    first_start = parse_datetime(first_start_str)

    duration = timedelta(
        days=int(form.get("duration_days") or 0),
        hours=int(form.get("duration_hours") or 0),
        minutes=int(form.get("duration_minutes") or 0),
    )
    if duration <= timedelta(0):
        raise HTTPException(status_code=400, detail="Duration must be greater than 0")

    recurrence_types = form.getlist("recurrence_type[]")
    offset_days = form.getlist("offset_days[]")
    offset_months = form.getlist("offset_months[]")
    offset_years = form.getlist("offset_years[]")
    offset_hours = form.getlist("offset_hours[]")
    offset_minutes = form.getlist("offset_minutes[]")
    rec_resp_json = form.getlist("recurrence_responsible[]")
    rec_del_json = form.getlist("recurrence_delegations[]")

    recurrences = []
    for i, rtype in enumerate(recurrence_types):
        days = int(offset_days[i]) if i < len(offset_days) and offset_days[i] else 0
        months = int(offset_months[i]) if i < len(offset_months) and offset_months[i] else 0
        years = int(offset_years[i]) if i < len(offset_years) and offset_years[i] else 0
        hours = int(offset_hours[i]) if i < len(offset_hours) and offset_hours[i] else 0
        minutes = int(offset_minutes[i]) if i < len(offset_minutes) and offset_minutes[i] else 0

        off = None
        if days or months or years or hours or minutes:
            dur = timedelta(days=days, hours=hours, minutes=minutes)
            off = Offset(
                exact_duration_seconds=int(dur.total_seconds()) if (days or hours or minutes) else None,
                months=months or None,
                years=years or None,
            )
        responsible_users: list[str] = []
        if i < len(rec_resp_json) and rec_resp_json[i]:
            responsible_users = json.loads(rec_resp_json[i])
        delegations: list[Delegation] = []
        if i < len(rec_del_json) and rec_del_json[i]:
            delegations = [Delegation.model_validate(d) for d in json.loads(rec_del_json[i])]
        recurrences.append(
            Recurrence(
                type=RecurrenceType(rtype),
                offset=off,
                skipped_instances=[],
                responsible=responsible_users,
                delegations=delegations,
            )
        )

    none_after_str = form.get("none_after")
    none_after = parse_datetime(none_after_str) if none_after_str else None
    none_before_str = form.get("none_before")
    none_before = parse_datetime(none_before_str) if none_before_str else None

    responsible = form.getlist("responsible")
    managers = form.getlist("managers")
    if entry_type == CalendarEntryType.Chore and not responsible:
        raise HTTPException(status_code=400, detail="At least one responsible user required")
    if entry_type == CalendarEntryType.Chore:
        for rec in recurrences:
            for d in rec.delegations:
                if not d.responsible:
                    raise HTTPException(status_code=400, detail="Delegations must have responsible users")

    new_entry = CalendarEntry(
        title=title,
        description=description,
        type=entry_type,
        first_start=first_start,
        duration_seconds=int(duration.total_seconds()),
        recurrences=recurrences,
        none_after=none_after,
        none_before=none_before,
        responsible=responsible,
        managers=managers,
    )
    if not user_store.has_permission(current_user, "admin") and has_past_instances(new_entry):
        raise HTTPException(status_code=400, detail="Cannot modify entry with past instances")
    for comp in completion_store.list_for_entry(entry_id):
        old_period = find_time_period(
            existing, comp.recurrence_index, comp.instance_index
        )
        new_period = find_time_period(
            new_entry, comp.recurrence_index, comp.instance_index
        )
        if (
            not old_period
            or not new_period
            or old_period.start != new_period.start
            or old_period.end != new_period.end
        ):
            request.session["flash"] = "Cannot modify entry with existing completions."
            raise HTTPException(
                status_code=303,
                headers={
                    "Location": str(
                        relative_url_for(request, "edit_calendar_entry", entry_id=entry_id)
                    )
                },
            )
    calendar_store.update(entry_id, new_entry)
    return RedirectResponse(
        url=relative_url_for(request, "view_calendar_entry", entry_id=entry_id), status_code=303
    )


@app.post("/calendar/{entry_id}/update")
async def inline_update_calendar_entry(request: Request, entry_id: int):
    entry = calendar_store.get(entry_id)
    if not entry:
        raise HTTPException(status_code=404)
    require_entry_write_permission(request, entry)
    username = request.session.get("user")
    is_admin = user_store.has_permission(username, "admin")
    if not is_admin and has_past_instances(entry):
        raise HTTPException(status_code=400, detail="Cannot modify entry with past instances")
    data = await request.json()
    split_fields = {
        "description",
        "title",
        "type",
        "first_start",
        "duration_days",
        "duration_hours",
        "duration_minutes",
    }
    did_split = False
    if split_fields & set(data.keys()):
        entry_id, entry, did_split = split_entry_if_past(entry_id, entry)

    if "first_start" in data:
        entry.first_start = parse_datetime(data["first_start"])
    if "description" in data:
        entry.description = data["description"].strip()
    if "title" in data:
        entry.title = data["title"].strip()
    if "type" in data:
        entry.type = CalendarEntryType(data["type"])
    if (
        "duration_days" in data
        or "duration_hours" in data
        or "duration_minutes" in data
    ):
        days = int(data.get("duration_days", 0))
        hours = int(data.get("duration_hours", 0))
        minutes = int(data.get("duration_minutes", 0))
        entry.duration = timedelta(days=days, hours=hours, minutes=minutes)
    if "none_after" in data:
        na = data["none_after"]
        entry.none_after = parse_datetime(na) if na else None
    if "none_before" in data:
        nb = data["none_before"]
        entry.none_before = parse_datetime(nb) if nb else None
    if "responsible" in data:
        entry.responsible = data["responsible"]
    if "managers" in data:
        managers = list(data["managers"])
        if not managers:
            raise HTTPException(status_code=400, detail="At least one manager required")
        entry.managers = managers
    if not is_admin and has_past_instances(entry):
        raise HTTPException(status_code=400, detail="Cannot modify entry with past instances")
    calendar_store.update(entry_id, entry)
    resp = {"status": "ok"}
    if did_split:
        resp["redirect"] = str(
            relative_url_for(request, "view_calendar_entry", entry_id=entry.id)
        )
    return JSONResponse(resp)


@app.post("/calendar/{entry_id}/recurrence/update")
async def update_recurrence(request: Request, entry_id: int):
    entry = calendar_store.get(entry_id)
    if not entry:
        raise HTTPException(status_code=404)
    require_entry_write_permission(request, entry)
    username = request.session.get("user")
    is_admin = user_store.has_permission(username, "admin")
    if not is_admin and has_past_instances(entry):
        raise HTTPException(status_code=400, detail="Cannot modify entry with past instances")
    data = await request.json()
    rindex = int(data.get("recurrence_index", -1))
    if rindex < 0 or rindex >= len(entry.recurrences):
        raise HTTPException(status_code=400)
    entry_id, entry, did_split = split_entry_if_past(entry_id, entry)
    rec = entry.recurrences[rindex]
    if not isinstance(rec, Recurrence):
        rec = Recurrence.model_validate(rec)
        entry.recurrences[rindex] = rec
    if "type" in data:
        rec.type = RecurrenceType(data["type"])
    days = int(data.get("offset_days") or 0)
    hours = int(data.get("offset_hours") or 0)
    minutes = int(data.get("offset_minutes") or 0)
    if days or hours or minutes:
        rec.offset = Offset(exact_duration_seconds=days * 86400 + hours * 3600 + minutes * 60)
    else:
        rec.offset = None
    if "responsible" in data:
        rec.responsible = list(data["responsible"])
    if not is_admin and has_past_instances(entry):
        raise HTTPException(status_code=400, detail="Cannot modify entry with past instances")
    calendar_store.update(entry_id, entry)
    resp = {"status": "ok"}
    if did_split:
        resp["redirect"] = str(
            relative_url_for(request, "view_calendar_entry", entry_id=entry.id)
        )
    return JSONResponse(resp)


@app.post("/calendar/{entry_id}/recurrence/add")
async def add_recurrence(request: Request, entry_id: int):
    entry = calendar_store.get(entry_id)
    if not entry:
        raise HTTPException(status_code=404)
    require_entry_write_permission(request, entry)
    username = request.session.get("user")
    is_admin = user_store.has_permission(username, "admin")
    if not is_admin and has_past_instances(entry):
        raise HTTPException(status_code=400, detail="Cannot modify entry with past instances")
    data = await request.json()
    if "type" not in data:
        raise HTTPException(status_code=400)
    entry_id, entry, did_split = split_entry_if_past(entry_id, entry)
    rtype = RecurrenceType(data["type"])
    days = int(data.get("offset_days") or 0)
    hours = int(data.get("offset_hours") or 0)
    minutes = int(data.get("offset_minutes") or 0)
    offset = None
    if days or hours or minutes:
        offset = Offset(exact_duration_seconds=days * 86400 + hours * 3600 + minutes * 60)
    rec = Recurrence(
        type=rtype,
        offset=offset,
        responsible=list(data.get("responsible") or []),
        first_start=entry.first_start,
        duration_seconds=entry.duration_seconds,
    )
    entry.recurrences.append(rec)
    if not is_admin and has_past_instances(entry):
        raise HTTPException(status_code=400, detail="Cannot modify entry with past instances")
    calendar_store.update(entry_id, entry)
    resp = {"status": "ok", "recurrence_index": len(entry.recurrences) - 1}
    if did_split:
        resp["redirect"] = str(
            relative_url_for(request, "view_calendar_entry", entry_id=entry.id)
        )
    return JSONResponse(resp)


@app.post("/calendar/{entry_id}/recurrence/delete")
async def delete_recurrence(request: Request, entry_id: int):
    entry = calendar_store.get(entry_id)
    if not entry:
        raise HTTPException(status_code=404)
    require_entry_write_permission(request, entry)
    username = request.session.get("user")
    is_admin = user_store.has_permission(username, "admin")
    if not is_admin and has_past_instances(entry):
        raise HTTPException(status_code=400, detail="Cannot modify entry with past instances")
    data = await request.json()
    rindex = int(data.get("recurrence_index", -1))
    if rindex < 0 or rindex >= len(entry.recurrences):
        raise HTTPException(status_code=400)
    entry_id, entry, did_split = split_entry_if_past(entry_id, entry)
    removed = entry.recurrences.pop(rindex)
    if not entry.recurrences:
        entry.recurrences.append(
            Recurrence(
                type=RecurrenceType.OneTime,
                first_start=removed.first_start,
                duration_seconds=removed.duration_seconds,
            )
        )
    if not is_admin and has_past_instances(entry):
        raise HTTPException(status_code=400, detail="Cannot modify entry with past instances")
    calendar_store.update(entry_id, entry)
    # Remove completions for this recurrence and shift higher indices
    comps = completion_store.list_for_entry(entry_id)
    for comp in comps:
        if comp.recurrence_index == rindex:
            completion_store.delete(entry_id, comp.recurrence_index, comp.instance_index)
        elif comp.recurrence_index > rindex:
            completion_store.delete(entry_id, comp.recurrence_index, comp.instance_index)
            completion_store.create(
                entry_id,
                comp.recurrence_index - 1,
                comp.instance_index,
                comp.completed_by,
                comp.completed_at,
            )
    resp = {"status": "ok"}
    if did_split:
        resp["redirect"] = str(
            relative_url_for(request, "view_calendar_entry", entry_id=entry.id)
        )
    return JSONResponse(resp)


@app.post("/calendar/{entry_id}/delete")
async def delete_calendar_entry(request: Request, entry_id: int):
    entry = calendar_store.get(entry_id)
    if not entry:
        raise HTTPException(status_code=404)
    require_entry_write_permission(request, entry)
    if not calendar_store.delete(entry_id):
        raise HTTPException(status_code=400, detail="Entry has completions or delegations")
    return RedirectResponse(
        url=relative_url_for(request, "list_calendar_entries", entry_type=entry.type.value),
        status_code=303,
    )


@app.post("/calendar/{entry_id}/completion")
async def complete_chore(request: Request, entry_id: int):
    entry = calendar_store.get(entry_id)
    if not entry or entry.type != CalendarEntryType.Chore:
        raise HTTPException(status_code=404)
    data = await request.json()
    rindex = int(data.get("recurrence_index"))
    iindex = int(data.get("instance_index"))
    period = find_time_period(entry, rindex, iindex)
    if not period:
        raise HTTPException(status_code=400)
    now = get_now()
    if period.start <= now <= period.end:
        perm = "chores.complete_on_time"
    elif period.end <= now:
        perm = "chores.complete_overdue"
    else:
        raise HTTPException(status_code=403)
    user = request.session.get("user")
    if not user_store.has_permission(user, perm):
        return JSONResponse(
            {
                "status": "forbidden",
                "message": f"{user} isn't authorized to complete this instance",
            },
            status_code=403,
        )
    if completion_store.get(entry_id, rindex, iindex):
        return {"status": "exists"}
    completion_store.create(entry_id, rindex, iindex, user)
    return {"status": "ok"}


@app.post("/calendar/{entry_id}/completion/remove")
async def remove_completion(request: Request, entry_id: int):
    entry = calendar_store.get(entry_id)
    if not entry or entry.type != CalendarEntryType.Chore:
        raise HTTPException(status_code=404)
    data = await request.json()
    rindex = int(data.get("recurrence_index"))
    iindex = int(data.get("instance_index"))
    completion = completion_store.get(entry_id, rindex, iindex)
    if not completion:
        raise HTTPException(status_code=404)
    user = request.session.get("user")
    if not (
        completion.completed_by == user
        or user_store.has_permission(user, "chores.override_complete")
    ):
        raise HTTPException(status_code=403)
    completion_store.delete(entry_id, rindex, iindex)
    return {"status": "ok"}


@app.post("/calendar/{entry_id}/delegation")
async def delegate_instance(request: Request, entry_id: int):
    entry = calendar_store.get(entry_id)
    if not entry:
        raise HTTPException(status_code=404)
    require_entry_write_permission(request, entry)
    form = await request.form()
    rindex = int(form.get("recurrence_index", -1))
    iindex = int(form.get("instance_index", -1))
    responsible = form.getlist("responsible[]")
    if not responsible:
        raise HTTPException(status_code=400)
    if 0 <= rindex < len(entry.recurrences):
        rec = entry.recurrences[rindex]
        if not isinstance(rec, Recurrence):
            rec = Recurrence.model_validate(rec)
            entry.recurrences[rindex] = rec
        existing = find_delegation(entry, rindex, iindex)
        if existing:
            existing.responsible = responsible
        else:
            rec.delegations.append(
                Delegation(instance_index=iindex, responsible=responsible)
            )
        calendar_store.update(entry_id, entry)
    else:
        raise HTTPException(status_code=400)
    referer = request.headers.get(
        "referer",
        str(
            relative_url_for(
                request,
                "view_time_period",
                entry_id=entry_id,
                rindex=rindex,
                iindex=iindex,
            )
        ),
    )
    return RedirectResponse(url=referer, status_code=303)


@app.post("/calendar/{entry_id}/delegation/remove")
async def remove_delegation(request: Request, entry_id: int):
    entry = calendar_store.get(entry_id)
    if not entry:
        raise HTTPException(status_code=404)
    require_entry_write_permission(request, entry)
    form = await request.form()
    rindex = int(form.get("recurrence_index", -1))
    iindex = int(form.get("instance_index", -1))
    if 0 <= rindex < len(entry.recurrences):
        rec = entry.recurrences[rindex]
        if not isinstance(rec, Recurrence):
            rec = Recurrence.model_validate(rec)
            entry.recurrences[rindex] = rec
        for idx, d in enumerate(rec.delegations):
            if not isinstance(d, Delegation):
                d = Delegation.model_validate(d)
                rec.delegations[idx] = d
            if d.instance_index == iindex:
                del rec.delegations[idx]
                break
        calendar_store.update(entry_id, entry)
    else:
        raise HTTPException(status_code=400)
    referer = request.headers.get(
        "referer",
        str(
            relative_url_for(
                request,
                "view_time_period",
                entry_id=entry_id,
                rindex=rindex,
                iindex=iindex,
            )
        ),
    )
    return RedirectResponse(url=referer, status_code=303)


@app.post("/calendar/{entry_id}/duration")
async def set_instance_duration(request: Request, entry_id: int):
    entry = calendar_store.get(entry_id)
    if not entry:
        raise HTTPException(status_code=404)
    require_entry_write_permission(request, entry)
    form = await request.form()
    rindex = int(form.get("recurrence_index", -1))
    iindex = int(form.get("instance_index", -1))

    def to_int(value: str | None) -> int:
        try:
            return int(value) if value is not None and value != "" else 0
        except ValueError:
            return 0

    days = to_int(form.get("duration_days"))
    hours = to_int(form.get("duration_hours"))
    minutes = to_int(form.get("duration_minutes"))
    duration = timedelta(days=days, hours=hours, minutes=minutes)
    if duration <= timedelta(0):
        raise HTTPException(status_code=400)
    seconds = int(duration.total_seconds())
    if 0 <= rindex < len(entry.recurrences):
        rec = entry.recurrences[rindex]
        if not isinstance(rec, Recurrence):
            rec = Recurrence.model_validate(rec)
            entry.recurrences[rindex] = rec
        existing = find_instance_duration(entry, rindex, iindex)
        if existing:
            existing.duration_seconds = seconds
        else:
            rec.duration_overrides.append(
                InstanceDuration(instance_index=iindex, duration_seconds=seconds)
            )
        calendar_store.update(entry_id, entry)
    else:
        raise HTTPException(status_code=400)
    referer = request.headers.get(
        "referer",
        str(
            relative_url_for(
                request,
                "view_time_period",
                entry_id=entry_id,
                rindex=rindex,
                iindex=iindex,
            )
        ),
    )
    return RedirectResponse(url=referer, status_code=303)


@app.post("/calendar/{entry_id}/duration/remove")
async def remove_instance_duration(request: Request, entry_id: int):
    entry = calendar_store.get(entry_id)
    if not entry:
        raise HTTPException(status_code=404)
    require_entry_write_permission(request, entry)
    form = await request.form()
    rindex = int(form.get("recurrence_index", -1))
    iindex = int(form.get("instance_index", -1))
    if 0 <= rindex < len(entry.recurrences):
        rec = entry.recurrences[rindex]
        if not isinstance(rec, Recurrence):
            rec = Recurrence.model_validate(rec)
            entry.recurrences[rindex] = rec
        for idx, d in enumerate(rec.duration_overrides):
            if not isinstance(d, InstanceDuration):
                d = InstanceDuration.model_validate(d)
                rec.duration_overrides[idx] = d
            if d.instance_index == iindex:
                del rec.duration_overrides[idx]
                break
        calendar_store.update(entry_id, entry)
    else:
        raise HTTPException(status_code=400)
    referer = request.headers.get(
        "referer",
        str(
            relative_url_for(
                request,
                "view_time_period",
                entry_id=entry_id,
                rindex=rindex,
                iindex=iindex,
            )
        ),
    )
    return RedirectResponse(url=referer, status_code=303)


@app.post("/calendar/{entry_id}/note")
async def add_instance_note(request: Request, entry_id: int):
    entry = calendar_store.get(entry_id)
    if not entry:
        raise HTTPException(status_code=404)
    require_entry_write_permission(request, entry)
    form = await request.form()
    rindex = int(form.get("recurrence_index", -1))
    iindex = int(form.get("instance_index", -1))
    note = (form.get("note", "").strip())
    if not note:
        raise HTTPException(status_code=400)
    if 0 <= rindex < len(entry.recurrences):
        rec = entry.recurrences[rindex]
        if not isinstance(rec, Recurrence):
            rec = Recurrence.model_validate(rec)
            entry.recurrences[rindex] = rec
        existing = find_instance_note(entry, rindex, iindex)
        if existing:
            existing.note = note
        else:
            rec.notes.append(InstanceNote(instance_index=iindex, note=note))
        calendar_store.update(entry_id, entry)
    else:
        raise HTTPException(status_code=400)
    referer = request.headers.get(
        "referer",
        str(
            relative_url_for(
                request,
                "view_time_period",
                entry_id=entry_id,
                rindex=rindex,
                iindex=iindex,
            )
        ),
    )
    return RedirectResponse(url=referer, status_code=303)


@app.post("/calendar/{entry_id}/note/remove")
async def remove_instance_note(request: Request, entry_id: int):
    entry = calendar_store.get(entry_id)
    if not entry:
        raise HTTPException(status_code=404)
    require_entry_write_permission(request, entry)
    form = await request.form()
    rindex = int(form.get("recurrence_index", -1))
    iindex = int(form.get("instance_index", -1))
    if 0 <= rindex < len(entry.recurrences):
        rec = entry.recurrences[rindex]
        if not isinstance(rec, Recurrence):
            rec = Recurrence.model_validate(rec)
            entry.recurrences[rindex] = rec
        for idx, n in enumerate(rec.notes):
            if not isinstance(n, InstanceNote):
                n = InstanceNote.model_validate(n)
                rec.notes[idx] = n
            if n.instance_index == iindex:
                del rec.notes[idx]
                break
        calendar_store.update(entry_id, entry)
    else:
        raise HTTPException(status_code=400)
    referer = request.headers.get(
        "referer",
        str(
            relative_url_for(
                request,
                "view_time_period",
                entry_id=entry_id,
                rindex=rindex,
                iindex=iindex,
            )
        ),
    )
    return RedirectResponse(url=referer, status_code=303)


@app.post("/calendar/{entry_id}/skip")
async def skip_instance(request: Request, entry_id: int):
    entry = calendar_store.get(entry_id)
    if not entry:
        raise HTTPException(status_code=404)
    require_entry_write_permission(request, entry)
    form = await request.form()
    rindex = int(form.get("recurrence_index", -1))
    iindex = int(form.get("instance_index", -1))
    if 0 <= rindex < len(entry.recurrences):
        rec = entry.recurrences[rindex]
        if iindex not in rec.skipped_instances:
            rec.skipped_instances.append(iindex)
        for idx, d in enumerate(rec.delegations):
            if not isinstance(d, Delegation):
                d = Delegation.model_validate(d)
                rec.delegations[idx] = d
            if d.instance_index == iindex:
                del rec.delegations[idx]
                break
        for idx, n in enumerate(rec.notes):
            if not isinstance(n, InstanceNote):
                n = InstanceNote.model_validate(n)
                rec.notes[idx] = n
            if n.instance_index == iindex:
                del rec.notes[idx]
                break
        calendar_store.update(entry_id, entry)
    else:
        raise HTTPException(status_code=400)
    referer = request.headers.get(
        "referer",
        str(
            relative_url_for(
                request,
                "view_time_period",
                entry_id=entry_id,
                rindex=rindex,
                iindex=iindex,
            )
        ),
    )
    return RedirectResponse(url=referer, status_code=303)


@app.post("/calendar/{entry_id}/skip/remove")
async def unskip_instance(request: Request, entry_id: int):
    entry = calendar_store.get(entry_id)
    if not entry:
        raise HTTPException(status_code=404)
    require_entry_write_permission(request, entry)
    form = await request.form()
    rindex = int(form.get("recurrence_index", -1))
    iindex = int(form.get("instance_index", -1))
    if 0 <= rindex < len(entry.recurrences):
        rec = entry.recurrences[rindex]
        if iindex in rec.skipped_instances:
            rec.skipped_instances.remove(iindex)
        calendar_store.update(entry_id, entry)
    else:
        raise HTTPException(status_code=400)
    referer = request.headers.get(
        "referer",
        str(
            relative_url_for(
                request,
                "view_time_period",
                entry_id=entry_id,
                rindex=rindex,
                iindex=iindex,
            )
        ),
    )
    return RedirectResponse(url=referer, status_code=303)


@app.get("/users", response_class=HTMLResponse)
async def list_users(request: Request):
    require_permission(request, "iam")
    users = user_store.list_users()
    entries = calendar_store.list_entries()
    with Session(engine) as session:
        completion_users = {
            row[0] for row in session.exec(select(ChoreCompletion.completed_by)).all()
        }
    undeletable = {
        u.username
        for u in users
        if any(
            u.username in e.managers or u.username in e.responsible for e in entries
        )
        or u.username in completion_users
    }
    return templates.TemplateResponse(
        request,
        "users/list.html",
        {"users": users, "undeletable": undeletable},
    )


@app.get("/users/new", response_class=HTMLResponse)
async def new_user(request: Request):
    require_permission(request, "iam")
    return templates.TemplateResponse(request, "users/form.html", {"user": None})


@app.post("/users/new")
async def create_user(request: Request):
    require_permission(request, "iam")
    form = await request.form()
    username = form.get("username", "").strip()
    password = form.get("password") or None
    pin = form.get("pin") or None
    permissions = {p for p in ALL_PERMISSIONS if form.get(p)}
    if form.get("admin") and user_store.has_permission(request.session.get("user"), "admin"):
        permissions.add("admin")
    upload = form.get("profile_picture")
    profile_picture = None
    if getattr(upload, "filename", ""):
        data = await upload.read()
        if data:
            profile_picture = process_profile_picture(data)
    if not is_url_safe(username):
        request.session["flash"] = "Username must be URL-safe."
        raise HTTPException(
            status_code=303, headers={"Location": relative_url_for(request, "new_user")}
        )
    if not user_store.create(
        username, password, pin, permissions, profile_picture=profile_picture
    ):
        request.session["flash"] = "User with that name already exists."
        raise HTTPException(
            status_code=303, headers={"Location": relative_url_for(request, "new_user")}
        )
    return RedirectResponse(url=relative_url_for(request, "list_users"), status_code=303)


@app.get("/users/{username}", response_class=HTMLResponse)
async def view_user(request: Request, username: str):
    current_user = request.session.get("user")
    if current_user != username:
        require_permission(request, "iam")
    user = user_store.get(username)
    if not user or user.username == "Viewer":
        raise HTTPException(status_code=404)
    with Session(engine) as session:
        stmt = (
            select(ChoreCompletion)
            .where(ChoreCompletion.completed_by == username)
            .order_by(ChoreCompletion.completed_at.desc())
        )
        comps = session.exec(stmt).all()
    completion_entries = []
    for comp in comps:
        entry = calendar_store.get(comp.entry_id)
        if entry:
            has_note = bool(
                find_instance_note(entry, comp.recurrence_index, comp.instance_index)
            )
            completion_entries.append((entry, comp, has_note))
    entries = calendar_store.list_entries()
    responsible_entries = [
        CalendarEntry.model_validate(e.model_dump())
        for e in entries
        if (username in e.responsible)
        or any(username in r.responsible for r in e.recurrences)
    ]
    managed_entries = [
        CalendarEntry.model_validate(e.model_dump())
        for e in entries
        if username in e.managers
    ]

    def _prep(entries_list: list[CalendarEntry]) -> list[CalendarEntry]:
        counts = Counter(e.title for e in entries_list)
        start_map = {}
        for e in entries_list:
            start, end = entry_time_bounds(e)
            start_map[e.id] = start
            if counts[e.title] > 1:
                e.title = f"{e.title} ({time_range_summary(start, end)})"
        entries_list.sort(key=lambda e: start_map[e.id], reverse=True)
        return entries_list

    responsible_entries = _prep(responsible_entries)
    managed_entries = _prep(managed_entries)

    return templates.TemplateResponse(
        request,
        "users/view.html",
        {
            "user": user,
            "completions": completion_entries,
            "responsible_entries": responsible_entries,
            "managed_entries": managed_entries,
            "current_user": current_user,
        },
    )


@app.get("/users/{username}/edit", response_class=HTMLResponse)
async def edit_user(request: Request, username: str):
    current_user = request.session.get("user")
    if current_user != username:
        require_permission(request, "iam")
    user = user_store.get(username)
    if not user or user.username == "Viewer":
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(request, "users/form.html", {"user": user})


@app.post("/users/{username}/edit")
async def update_user(request: Request, username: str):
    current_user = request.session.get("user")
    if current_user != username:
        require_permission(request, "iam")
    form = await request.form()
    new_username = form.get("username", "").strip()
    password = form.get("password") or None
    pin = form.get("pin") or None
    remove_password = bool(form.get("remove_password"))
    remove_pin = bool(form.get("remove_pin"))
    upload = form.get("profile_picture")
    profile_picture = None
    if getattr(upload, "filename", ""):
        data = await upload.read()
        if data:
            profile_picture = process_profile_picture(data)
    existing = user_store.get(username)
    if not existing or existing.username == "Viewer":
        raise HTTPException(status_code=404)
    if not is_url_safe(new_username):
        request.session["flash"] = "Username must be URL-safe."
        raise HTTPException(
            status_code=303,
            headers={"Location": relative_url_for(request, "edit_user", username=username)},
        )
    if user_store.has_permission(current_user, "iam"):
        permissions = {p for p in ALL_PERMISSIONS if form.get(p)}
        if form.get("admin") and user_store.has_permission(current_user, "admin"):
            permissions.add("admin")
        elif "admin" in existing.permissions:
            permissions.add("admin")
        if "admin" in existing.permissions and "admin" not in permissions:
            admins = [u for u in user_store.list_users() if "admin" in u.permissions and u.username != username]
            if not admins:
                request.session["flash"] = "Cannot remove the last admin user."
                raise HTTPException(
                    status_code=303,
                    headers={"Location": relative_url_for(request, "edit_user", username=username)},
                )
    else:
        permissions = set(existing.permissions)
    if not user_store.update(
        username,
        new_username,
        password,
        pin,
        permissions,
        remove_password=remove_password,
        remove_pin=remove_pin,
        profile_picture=profile_picture,
    ):
        request.session["flash"] = "User with that name already exists."
        raise HTTPException(
            status_code=303,
            headers={"Location": relative_url_for(request, "edit_user", username=username)},
        )
    if current_user == username:
        request.session["user"] = new_username
    target = (
        relative_url_for(request, "list_users")
        if current_user != username
        else relative_url_for(request, "index")
    )
    return RedirectResponse(url=target, status_code=303)


@app.post("/users/{username}/delete")
async def delete_user(request: Request, username: str):
    require_permission(request, "iam")
    user = user_store.get(username)
    if not user or user.username == "Viewer":
        raise HTTPException(status_code=404)
    if "admin" in user.permissions:
        admins = [u for u in user_store.list_users() if "admin" in u.permissions and u.username != username]
        if not admins:
            request.session["flash"] = "Cannot delete the last admin user."
            raise HTTPException(status_code=303, headers={"Location": relative_url_for(request, "list_users")})
    for entry in calendar_store.list_entries():
        if username in entry.managers or username in entry.responsible:
            request.session["flash"] = "Cannot delete user with calendar responsibilities."
            raise HTTPException(status_code=303, headers={"Location": relative_url_for(request, "list_users")})
    with Session(engine) as session:
        stmt = select(ChoreCompletion).where(ChoreCompletion.completed_by == username)
        if session.exec(stmt).first():
            request.session["flash"] = "Cannot delete user with chore completions."
            raise HTTPException(status_code=303, headers={"Location": relative_url_for(request, "list_users")})
    user_store.delete(username)
    return RedirectResponse(url=relative_url_for(request, "list_users"), status_code=303)

