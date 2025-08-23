from datetime import datetime, timedelta
from pathlib import Path
import json
import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware
from sqlmodel import create_engine
from pydantic.json import pydantic_encoder
from itertools import islice

from .users import UserStore, init_db
from .calendar import (
    CalendarEntry,
    CalendarEntryStore,
    CalendarEntryType,
    Offset,
    Recurrence,
    RecurrenceType,
    enumerate_time_periods,
)


LOGOUT_DURATION = timedelta(minutes=1)

db_path = os.getenv("CHORETRACKER_DB", "choretracker.db")
engine = create_engine(
    f"sqlite:///{db_path}",
    connect_args={"check_same_thread": False},
    json_serializer=lambda obj: json.dumps(obj, default=pydantic_encoder),
)
init_db(engine)
user_store = UserStore(engine)
calendar_store = CalendarEntryStore(engine)
ALL_PERMISSIONS = [
    "chores.read",
    "chores.write",
    "chores.edit_others",
    "events.read",
    "events.write",
    "events.edit_others",
    "reminders.read",
    "reminders.write",
    "reminders.edit_others",
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

EDIT_OTHER_PERMS = {
    CalendarEntryType.Event: "events.edit_others",
    CalendarEntryType.Reminder: "reminders.edit_others",
    CalendarEntryType.Chore: "chores.edit_others",
}

app = FastAPI()

BASE_PATH = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_PATH / "templates"))
templates.env.globals["all_users"] = lambda: sorted(
    [u.username for u in user_store.list_users(include_viewer=True)],
    key=lambda name: (name != "Viewer", name),
)
templates.env.globals["user_has"] = user_store.has_permission
templates.env.globals["WRITE_PERMS"] = WRITE_PERMS
templates.env.globals["EDIT_OTHER_PERMS"] = EDIT_OTHER_PERMS
templates.env.globals["timedelta"] = timedelta
app.mount("/static", StaticFiles(directory=str(BASE_PATH / "static")), name="static")


def require_permission(request: Request, permission: str) -> None:
    username = request.session.get("user")
    if not username or not user_store.has_permission(username, permission):
        request.session["flash"] = "You are not allowed to perform that action."
        raise HTTPException(
            status_code=303, headers={"Location": str(request.url_for("index"))}
        )


def can_edit_entry(username: str, entry: CalendarEntry) -> bool:
    if not username:
        return False
    if not user_store.has_permission(username, WRITE_PERMS[entry.type]):
        return False
    if entry.owner == username:
        return True
    return user_store.has_permission(username, EDIT_OTHER_PERMS[entry.type])


def require_entry_read_permission(request: Request, entry_type: CalendarEntryType) -> None:
    require_permission(request, READ_PERMS[entry_type])


def require_entry_write_permission(request: Request, entry: CalendarEntry) -> None:
    username = request.session.get("user")
    if not can_edit_entry(username, entry):
        request.session["flash"] = "You are not allowed to perform that action."
        raise HTTPException(status_code=303, headers={"Location": str(request.url_for("index"))})


class EnsureUserMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        session = request.session
        path = request.url.path

        user = session.get("user")
        now = datetime.utcnow().timestamp()
        if user:
            last = session.get("last_active", now)
            if user != "Viewer" and now - last > LOGOUT_DURATION.total_seconds():
                session["user"] = "Viewer"
                user = "Viewer"
            session["last_active"] = now
        elif not (path == "/login" or path.startswith("/static")):
            return RedirectResponse(url="/login")

        response = await call_next(request)
        return response


app.add_middleware(EnsureUserMiddleware)
app.add_middleware(SessionMiddleware, secret_key="change-me")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    entries_with_periods = []
    for entry in calendar_store.list_entries():
        periods = list(islice(enumerate_time_periods(entry), 8))
        entries_with_periods.append((entry, periods))
    return templates.TemplateResponse(
        "index.html", {"request": request, "entries": entries_with_periods}
    )


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if request.session.get("user"):
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login")
async def login(request: Request):
    form = await request.form()
    username = form.get("username", "")
    password = form.get("password", "")

    if user_store.verify(username, password):
        request.session["user"] = username
        request.session["last_active"] = datetime.utcnow().timestamp()
        return RedirectResponse(url="/", status_code=303)

    return templates.TemplateResponse(
        "login.html", {"request": request, "error": "Invalid credentials"}, status_code=400
    )


@app.get("/switch/{username}")
async def switch_user(request: Request, username: str):
    if user_store.get(username):
        request.session["user"] = username
        request.session["last_active"] = datetime.utcnow().timestamp()
    return RedirectResponse(url="/", status_code=303)


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


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
    return templates.TemplateResponse(
        "calendar/form.html", {"request": request, "entry_type": entry_type, "entry": None}
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

    first_start_str = form.get("first_start")
    if not first_start_str:
        raise HTTPException(status_code=400, detail="first_start required")
    first_start = datetime.fromisoformat(first_start_str)

    duration = timedelta(
        weeks=int(form.get("duration_weeks") or 0),
        days=int(form.get("duration_days") or 0),
        hours=int(form.get("duration_hours") or 0),
        minutes=int(form.get("duration_minutes") or 0),
    )

    recurrence_types = form.getlist("recurrence_type[]")
    offset_days = form.getlist("offset_days[]")
    offset_months = form.getlist("offset_months[]")
    offset_years = form.getlist("offset_years[]")
    offset_hours = form.getlist("offset_hours[]")
    offset_minutes = form.getlist("offset_minutes[]")

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
        recurrences.append(Recurrence(type=RecurrenceType(rtype), offset=off, skipped_instances=[]))

    none_after_str = form.get("none_after")
    none_after = datetime.fromisoformat(none_after_str) if none_after_str else None

    responsible = form.getlist("responsible")

    entry = CalendarEntry(
        title=title,
        description=description,
        type=entry_type,
        first_start=first_start,
        duration_seconds=int(duration.total_seconds()),
        recurrences=recurrences,
        none_after=none_after,
        responsible=responsible,
        owner=request.session.get("user", ""),
    )
    calendar_store.create(entry)
    return RedirectResponse(url="/", status_code=303)


@app.get("/calendar/list/{entry_type}", response_class=HTMLResponse)
async def list_calendar_entries(request: Request, entry_type: str):
    try:
        etype = CalendarEntryType(entry_type)
    except ValueError:
        raise HTTPException(status_code=404)
    require_entry_read_permission(request, etype)
    entries = [e for e in calendar_store.list_entries() if e.type == etype]
    current_user = request.session.get("user")
    return templates.TemplateResponse(
        "calendar/list.html",
        {
            "request": request,
            "entries": entries,
            "entry_type": etype,
            "current_user": current_user,
        },
    )


@app.get("/calendar/entry/{entry_id}", response_class=HTMLResponse)
async def view_calendar_entry(request: Request, entry_id: int):
    entry = calendar_store.get(entry_id)
    if not entry:
        raise HTTPException(status_code=404)
    require_entry_read_permission(request, entry.type)
    current_user = request.session.get("user")
    return templates.TemplateResponse(
        "calendar/view.html",
        {
            "request": request,
            "entry": entry,
            "can_edit": can_edit_entry(current_user, entry),
        },
    )


@app.get("/calendar/{entry_id}/edit", response_class=HTMLResponse)
async def edit_calendar_entry(request: Request, entry_id: int):
    entry = calendar_store.get(entry_id)
    if not entry:
        raise HTTPException(status_code=404)
    require_entry_write_permission(request, entry)
    entry_json = json.dumps(entry.model_dump(), default=pydantic_encoder)
    return templates.TemplateResponse(
        "calendar/form.html",
        {
            "request": request,
            "entry_type": entry.type.value,
            "entry": entry,
            "entry_json": entry_json,
        },
    )


@app.post("/calendar/{entry_id}/edit")
async def update_calendar_entry(request: Request, entry_id: int):
    existing = calendar_store.get(entry_id)
    if not existing:
        raise HTTPException(status_code=404)
    require_entry_write_permission(request, existing)

    form = await request.form()
    title = form.get("title", "").strip()
    description = form.get("description", "").strip()
    entry_type = existing.type

    first_start_str = form.get("first_start")
    if not first_start_str:
        raise HTTPException(status_code=400, detail="first_start required")
    first_start = datetime.fromisoformat(first_start_str)

    duration = timedelta(
        weeks=int(form.get("duration_weeks") or 0),
        days=int(form.get("duration_days") or 0),
        hours=int(form.get("duration_hours") or 0),
        minutes=int(form.get("duration_minutes") or 0),
    )

    recurrence_types = form.getlist("recurrence_type[]")
    offset_days = form.getlist("offset_days[]")
    offset_months = form.getlist("offset_months[]")
    offset_years = form.getlist("offset_years[]")
    offset_hours = form.getlist("offset_hours[]")
    offset_minutes = form.getlist("offset_minutes[]")

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
        recurrences.append(Recurrence(type=RecurrenceType(rtype), offset=off, skipped_instances=[]))

    none_after_str = form.get("none_after")
    none_after = datetime.fromisoformat(none_after_str) if none_after_str else None

    responsible = form.getlist("responsible")

    new_entry = CalendarEntry(
        title=title,
        description=description,
        type=entry_type,
        first_start=first_start,
        duration_seconds=int(duration.total_seconds()),
        recurrences=recurrences,
        none_after=none_after,
        responsible=responsible,
        owner=existing.owner,
    )
    calendar_store.update(entry_id, new_entry)
    return RedirectResponse(
        url=request.url_for("view_calendar_entry", entry_id=entry_id), status_code=303
    )


@app.get("/users", response_class=HTMLResponse)
async def list_users(request: Request):
    require_permission(request, "iam")
    return templates.TemplateResponse(
        "users/list.html", {"request": request, "users": user_store.list_users()}
    )


@app.get("/users/new", response_class=HTMLResponse)
async def new_user(request: Request):
    require_permission(request, "iam")
    return templates.TemplateResponse("users/form.html", {"request": request, "user": None})


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
    user_store.create(username, password, pin, permissions)
    return RedirectResponse(url="/users", status_code=303)


@app.get("/users/{username}/edit", response_class=HTMLResponse)
async def edit_user(request: Request, username: str):
    require_permission(request, "iam")
    user = user_store.get(username)
    if not user or user.username == "Viewer":
        raise HTTPException(status_code=404)
    return templates.TemplateResponse("users/form.html", {"request": request, "user": user})


@app.post("/users/{username}/edit")
async def update_user(request: Request, username: str):
    require_permission(request, "iam")
    form = await request.form()
    new_username = form.get("username", "").strip()
    password = form.get("password") or None
    pin = form.get("pin") or None
    remove_password = bool(form.get("remove_password"))
    remove_pin = bool(form.get("remove_pin"))
    existing = user_store.get(username)
    if not existing or existing.username == "Viewer":
        raise HTTPException(status_code=404)
    permissions = {p for p in ALL_PERMISSIONS if form.get(p)}
    current_user = request.session.get("user")
    if form.get("admin") and user_store.has_permission(current_user, "admin"):
        permissions.add("admin")
    elif "admin" in existing.permissions:
        permissions.add("admin")
    if "admin" in existing.permissions and "admin" not in permissions:
        admins = [u for u in user_store.list_users() if "admin" in u.permissions and u.username != username]
        if not admins:
            request.session["flash"] = "Cannot remove the last admin user."
            raise HTTPException(status_code=303, headers={"Location": str(request.url_for("edit_user", username=username))})
    user_store.update(
        username,
        new_username,
        password,
        pin,
        permissions,
        remove_password=remove_password,
        remove_pin=remove_pin,
    )
    return RedirectResponse(url="/users", status_code=303)


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
            raise HTTPException(status_code=303, headers={"Location": str(request.url_for("list_users"))})
    user_store.delete(username)
    return RedirectResponse(url="/users", status_code=303)

