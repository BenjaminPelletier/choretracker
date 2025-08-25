from datetime import datetime, timedelta
from pathlib import Path
import json
import os
from urllib.parse import urlparse
from heapq import heappush, heappop
from typing import Iterator
from itertools import count
from collections import Counter

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware
from sqlmodel import create_engine
from pydantic.json import pydantic_encoder

from .users import UserStore, init_db, process_profile_picture, pwd_context
from .calendar import (
    CalendarEntry,
    CalendarEntryStore,
    CalendarEntryType,
    ChoreCompletion,
    ChoreCompletionStore,
    Offset,
    Recurrence,
    RecurrenceType,
    TimePeriod,
    enumerate_time_periods,
    find_time_period,
)


LOGOUT_DURATION = timedelta(minutes=1)
MAX_UPCOMING = 5

db_path = os.getenv("CHORETRACKER_DB", "choretracker.db")
engine = create_engine(
    f"sqlite:///{db_path}",
    connect_args={"check_same_thread": False},
    json_serializer=lambda obj: json.dumps(obj, default=pydantic_encoder),
)
init_db(engine)
user_store = UserStore(engine)
calendar_store = CalendarEntryStore(engine)
completion_store = ChoreCompletionStore(engine)
ALL_PERMISSIONS = [
    "chores.read",
    "chores.write",
    "chores.edit_others",
    "chores.complete_on_time",
    "chores.complete_overdue",
    "chores.override_complete",
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
    user_store.list_users(include_viewer=True),
    key=lambda u: (u.username == "Viewer", u.username),
)
templates.env.globals["user_has"] = user_store.has_permission
templates.env.globals["WRITE_PERMS"] = WRITE_PERMS
templates.env.globals["EDIT_OTHER_PERMS"] = EDIT_OTHER_PERMS
templates.env.globals["timedelta"] = timedelta
templates.env.globals["LOGOUT_DURATION"] = LOGOUT_DURATION
def format_datetime(dt: datetime | None, include_day: bool = False) -> str:
    if not dt:
        return ""
    fmt = "%Y-%m-%d %H:%M"
    if include_day:
        fmt = "%A " + fmt
    return dt.strftime(fmt)
templates.env.filters["format_datetime"] = format_datetime


def format_time_range(period: TimePeriod) -> str:
    start = period.start.replace(second=0, microsecond=0)
    end = period.end.replace(second=0, microsecond=0)
    start_str = start.strftime("%Y-%m-%d %H:%M")
    if start.year != end.year:
        end_fmt = "%Y-%m-%d %H:%M"
    elif start.month != end.month:
        end_fmt = "%m-%d %H:%M"
    elif start.day != end.day:
        end_fmt = "%d %H:%M"
    elif start.hour != end.hour:
        end_fmt = "%H:%M"
    else:
        end_fmt = "%M"
    end_str = end.strftime(end_fmt)
    return f"{start_str} - {end_str}"


templates.env.filters["format_time_range"] = format_time_range
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
        now = datetime.now().timestamp()
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
    now = datetime.now()
    overdue: list[tuple[CalendarEntry, TimePeriod]] = []
    current: list[tuple[CalendarEntry, TimePeriod, ChoreCompletion | None]] = []
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
                        current.append((entry, period, completion))
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
                    overdue.append((entry, period))
            elif period.start <= now:
                current.append((entry, period, completion))
                nxt = next(gen, None)
                if nxt:
                    heappush(upcoming_heap, (nxt.start, next(counter), entry, nxt, gen))
                break
            else:
                heappush(upcoming_heap, (period.start, next(counter), entry, period, gen))
                break

    upcoming: list[tuple[CalendarEntry, TimePeriod]] = []
    while upcoming_heap and len(upcoming) < MAX_UPCOMING:
        _, _, entry, period, gen = heappop(upcoming_heap)
        upcoming.append((entry, period))
        nxt = next(gen, None)
        if nxt:
            heappush(upcoming_heap, (nxt.start, next(counter), entry, nxt, gen))

    overdue.sort(key=lambda x: x[1].end)
    current.sort(key=lambda x: x[1].end)

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "overdue": overdue,
            "now_periods": current,
            "upcoming": upcoming,
            "CalendarEntryType": CalendarEntryType,
        },
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
        request.session["last_active"] = datetime.now().timestamp()
        return RedirectResponse(url="/", status_code=303)

    return templates.TemplateResponse(
        "login.html", {"request": request, "error": "Invalid credentials"}, status_code=400
    )


def _switch_target(next: str | None) -> str:
    target = "/"
    if next:
        parsed = urlparse(next)
        if not parsed.scheme and not parsed.netloc:
            target = parsed.path
            if parsed.query:
                target += f"?{parsed.query}"
    return target


@app.get("/switch/{username}")
async def switch_user(request: Request, username: str, next: str | None = None, pin: str | None = None):
    user = user_store.get(username)
    if user and (not user.pin_hash or (pin and pwd_context.verify(pin, user.pin_hash))):
        request.session["user"] = username
        request.session["last_active"] = datetime.now().timestamp()
        return RedirectResponse(url=_switch_target(next), status_code=303)
    request.session["flash"] = "Invalid PIN"
    return RedirectResponse(url=str(request.headers.get("referer", "/")), status_code=303)


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
    request.session["last_active"] = datetime.now().timestamp()
    return JSONResponse({"redirect": _switch_target(next)})


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


@app.get("/users/{username}/profile_picture")
async def profile_picture(username: str):
    user = user_store.get(username)
    if user and user.profile_picture:
        return Response(user.profile_picture, media_type="image/png")
    if username == "Viewer":
        return FileResponse(BASE_PATH / "static" / "viewer_profile.png")
    return FileResponse(BASE_PATH / "static" / "default_profile.png")


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
    counts = Counter(e.title for e in entries)
    for entry in entries:
        if counts[entry.title] > 1:
            entry.title = f"{entry.title} ({format_datetime(entry.first_start, include_day=True)})"
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
    comps: list[tuple[ChoreCompletion, TimePeriod, bool]] = []
    for comp in completion_store.list_for_entry(entry_id):
        period = find_time_period(entry, comp.recurrence_index, comp.instance_index)
        if not period:
            continue
        can_remove = comp.completed_by == current_user or user_store.has_permission(
            current_user, "chores.override_complete"
        )
        comps.append((comp, period, can_remove))
    return templates.TemplateResponse(
        "calendar/view.html",
        {
            "request": request,
            "entry": entry,
            "can_edit": can_edit_entry(current_user, entry),
            "completions": comps,
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
    if rindex >= 0 and rindex < len(entry.recurrences):
        rec = entry.recurrences[rindex]
        is_skipped = iindex in rec.skipped_instances
    current_user = request.session.get("user")
    return templates.TemplateResponse(
        "calendar/timeperiod.html",
        {
            "request": request,
            "entry": entry,
            "period": period,
            "completion": completion,
            "is_skipped": is_skipped,
            "can_edit": can_edit_entry(current_user, entry),
            "now": datetime.now(),
            "CalendarEntryType": CalendarEntryType,
        },
    )


@app.get("/calendar/{entry_id}/edit", response_class=HTMLResponse)
async def edit_calendar_entry(request: Request, entry_id: int):
    entry = calendar_store.get(entry_id)
    if not entry:
        raise HTTPException(status_code=404)
    require_entry_write_permission(request, entry)
    entry_data = json.loads(
        json.dumps(entry.model_dump(), default=pydantic_encoder)
    )
    return templates.TemplateResponse(
        "calendar/form.html",
        {
            "request": request,
            "entry_type": entry.type.value,
            "entry": entry,
            "entry_data": entry_data,
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
                        request.url_for("edit_calendar_entry", entry_id=entry_id)
                    )
                },
            )
    calendar_store.update(entry_id, new_entry)
    return RedirectResponse(
        url=request.url_for("view_calendar_entry", entry_id=entry_id), status_code=303
    )


@app.post("/calendar/{entry_id}/delete")
async def delete_calendar_entry(request: Request, entry_id: int):
    entry = calendar_store.get(entry_id)
    if not entry:
        raise HTTPException(status_code=404)
    require_entry_write_permission(request, entry)
    calendar_store.delete(entry_id)
    return RedirectResponse(
        url=request.url_for("list_calendar_entries", entry_type=entry.type.value),
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
    now = datetime.now()
    if period.start <= now <= period.end:
        perm = "chores.complete_on_time"
    elif period.end <= now:
        perm = "chores.complete_overdue"
    else:
        raise HTTPException(status_code=403)
    user = request.session.get("user")
    if not user_store.has_permission(user, perm):
        raise HTTPException(status_code=403)
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


@app.post("/calendar/{entry_id}/skip")
async def skip_instance(request: Request, entry_id: int):
    entry = calendar_store.get(entry_id)
    if not entry:
        raise HTTPException(status_code=404)
    require_entry_write_permission(request, entry)
    form = await request.form()
    rindex = int(form.get("recurrence_index", -1))
    iindex = int(form.get("instance_index", -1))
    if rindex < 0 or rindex >= len(entry.recurrences):
        raise HTTPException(status_code=400)
    rec = entry.recurrences[rindex]
    if iindex not in rec.skipped_instances:
        rec.skipped_instances.append(iindex)
    calendar_store.update(entry_id, entry)
    referer = request.headers.get(
        "referer",
        str(
            request.url_for(
                "view_time_period", entry_id=entry_id, rindex=rindex, iindex=iindex
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
    if rindex < 0 or rindex >= len(entry.recurrences):
        raise HTTPException(status_code=400)
    rec = entry.recurrences[rindex]
    if iindex in rec.skipped_instances:
        rec.skipped_instances.remove(iindex)
    calendar_store.update(entry_id, entry)
    referer = request.headers.get(
        "referer",
        str(
            request.url_for(
                "view_time_period", entry_id=entry_id, rindex=rindex, iindex=iindex
            )
        ),
    )
    return RedirectResponse(url=referer, status_code=303)


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
    upload = form.get("profile_picture")
    profile_picture = None
    if getattr(upload, "filename", ""):
        data = await upload.read()
        if data:
            profile_picture = process_profile_picture(data)
    if not user_store.create(
        username, password, pin, permissions, profile_picture=profile_picture
    ):
        request.session["flash"] = "User with that name already exists."
        raise HTTPException(
            status_code=303, headers={"Location": str(request.url_for("new_user"))}
        )
    return RedirectResponse(url="/users", status_code=303)


@app.get("/users/{username}/edit", response_class=HTMLResponse)
async def edit_user(request: Request, username: str):
    current_user = request.session.get("user")
    if current_user != username:
        require_permission(request, "iam")
    user = user_store.get(username)
    if not user or user.username == "Viewer":
        raise HTTPException(status_code=404)
    return templates.TemplateResponse("users/form.html", {"request": request, "user": user})


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
                raise HTTPException(status_code=303, headers={"Location": str(request.url_for("edit_user", username=username))})
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
            headers={"Location": str(request.url_for("edit_user", username=username))},
        )
    target = "/users" if current_user != username else "/"
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
            raise HTTPException(status_code=303, headers={"Location": str(request.url_for("list_users"))})
    user_store.delete(username)
    return RedirectResponse(url="/users", status_code=303)

