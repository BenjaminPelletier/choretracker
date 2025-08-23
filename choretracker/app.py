from datetime import datetime, timedelta
from pathlib import Path
import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware
from sqlmodel import create_engine

from .users import UserStore, init_db


LOGOUT_DURATION = timedelta(minutes=1)

db_path = os.getenv("CHORETRACKER_DB", "choretracker.db")
engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
init_db(engine)
user_store = UserStore(engine)

app = FastAPI()

BASE_PATH = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_PATH / "templates"))
templates.env.globals["all_users"] = lambda: [u.username for u in user_store.list_users()]
templates.env.globals["user_has"] = user_store.has_permission
app.mount("/static", StaticFiles(directory=str(BASE_PATH / "static")), name="static")


def require_permission(request: Request, permission: str) -> None:
    username = request.session.get("user")
    if not username or not user_store.has_permission(username, permission):
        raise HTTPException(status_code=403)


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
    return templates.TemplateResponse("index.html", {"request": request})


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
    permissions = {"iam"} if form.get("iam") else set()
    user_store.create(username, password, pin, permissions)
    return RedirectResponse(url="/users", status_code=303)


@app.get("/users/{username}/edit", response_class=HTMLResponse)
async def edit_user(request: Request, username: str):
    require_permission(request, "iam")
    user = user_store.get(username)
    if not user:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse("users/form.html", {"request": request, "user": user})


@app.post("/users/{username}/edit")
async def update_user(request: Request, username: str):
    require_permission(request, "iam")
    form = await request.form()
    new_username = form.get("username", "").strip()
    password = form.get("password") or None
    pin = form.get("pin") or None
    permissions = {"iam"} if form.get("iam") else set()
    user_store.update(username, new_username, password, pin, permissions)
    return RedirectResponse(url="/users", status_code=303)


@app.post("/users/{username}/delete")
async def delete_user(request: Request, username: str):
    require_permission(request, "iam")
    user_store.delete(username)
    return RedirectResponse(url="/users", status_code=303)

