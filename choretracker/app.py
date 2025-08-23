from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

LOGOUT_DURATION = timedelta(minutes=1)

USERS: Dict[str, Optional[str]] = {
    "Dad": "dad",
    "Mom": "mom",
    "Child": None,
    "Viewer": None,
}

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="change-me")

BASE_PATH = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_PATH / "templates"))
templates.env.globals["ALL_USERS"] = list(USERS.keys())
app.mount("/static", StaticFiles(directory=str(BASE_PATH / "static")), name="static")


@app.middleware("http")
async def ensure_user(request: Request, call_next):
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

    if USERS.get(username) and USERS[username] == password:
        request.session["user"] = username
        request.session["last_active"] = datetime.utcnow().timestamp()
        return RedirectResponse(url="/", status_code=303)

    return templates.TemplateResponse(
        "login.html", {"request": request, "error": "Invalid credentials"}, status_code=400
    )


@app.get("/switch/{username}")
async def switch_user(request: Request, username: str):
    if username in USERS:
        request.session["user"] = username
        request.session["last_active"] = datetime.utcnow().timestamp()
    return RedirectResponse(url="/", status_code=303)


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)
