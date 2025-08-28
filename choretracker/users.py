from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Set
import io
import types
import re
import bcrypt

# Work around older Windows wheels lacking ``_bcrypt.__about__`` by
# populating it with the package version so Passlib's backend check
# doesn't emit a traceback. This is harmless if the attributes already
# exist.
if not hasattr(bcrypt, "__about__"):
    bcrypt.__about__ = types.SimpleNamespace(__version__=bcrypt.__version__)
if hasattr(bcrypt, "_bcrypt") and not hasattr(bcrypt._bcrypt, "__about__"):
    bcrypt._bcrypt.__about__ = bcrypt.__about__

from passlib.context import CryptContext
from sqlmodel import Field, Session, SQLModel, select
from sqlalchemy import Column, JSON, LargeBinary, text, func

from .calendar import CalendarEntry, Recurrence, ChoreCompletion
from sqlalchemy.exc import OperationalError
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from PIL import Image, ImageDraw


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


USERNAME_RE = re.compile(r"^[A-Za-z0-9._~-]+$")


def is_url_safe(username: str) -> bool:
    return bool(USERNAME_RE.fullmatch(username))


class User(SQLModel, table=True):
    """Database representation of a user."""

    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True)
    password_hash: str
    pin_hash: str
    permissions: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    profile_picture: Optional[bytes] = Field(
        default=None, sa_column=Column(LargeBinary)
    )


def hash_secret(secret: str) -> str:
    """Hash a password or PIN using bcrypt."""

    return pwd_context.hash(secret)


def process_profile_picture(data: bytes) -> bytes:
    """Process uploaded profile picture according to requirements."""

    with Image.open(io.BytesIO(data)) as img:
        img = img.convert("RGBA")
        width, height = img.size
        size = min(width, height)
        left = (width - size) // 2
        top = (height - size) // 2
        img = img.crop((left, top, left + size, top + size))
        img = img.resize((128, 128))
        mask = Image.new("L", (128, 128), 0)
        draw = ImageDraw.Draw(mask)
        draw.ellipse((0, 0, 128, 128), fill=255)
        img.putalpha(mask)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()


class UserStore:
    """CRUD helper for :class:`User` objects."""

    def __init__(self, engine):
        self.engine = engine

    def list_users(self, include_viewer: bool = False) -> List[User]:
        with Session(self.engine) as session:
            stmt = select(User)
            if not include_viewer:
                stmt = stmt.where(User.username != "Viewer")
            return session.exec(stmt).all()

    def get(self, username: str) -> Optional[User]:
        with Session(self.engine) as session:
            return session.exec(select(User).where(User.username == username)).first()

    def get_case_insensitive(self, username: str) -> Optional[User]:
        with Session(self.engine) as session:
            return session.exec(
                select(User).where(func.lower(User.username) == username.lower())
            ).first()

    def create(
        self,
        username: str,
        password: Optional[str],
        pin: Optional[str],
        permissions: Set[str],
        profile_picture: Optional[bytes] = None,
    ) -> bool:
        if username == "Viewer" or not is_url_safe(username):
            return False
        with Session(self.engine) as session:
            if session.exec(select(User).where(User.username == username)).first():
                return False
            user = User(
                username=username,
                password_hash=hash_secret(password) if password else "",
                pin_hash=hash_secret(pin) if pin else "",
                permissions=list(permissions),
                profile_picture=profile_picture,
            )
            session.add(user)
            session.commit()
            return True

    def update(
        self,
        old_username: str,
        new_username: str,
        password: Optional[str],
        pin: Optional[str],
        permissions: Set[str],
        remove_password: bool = False,
        remove_pin: bool = False,
        profile_picture: Optional[bytes] = None,
    ) -> bool:
        if old_username == "Viewer" or not is_url_safe(new_username):
            return False
        with Session(self.engine) as session:
            if new_username != old_username and session.exec(
                select(User).where(User.username == new_username)
            ).first():
                return False
            user = session.exec(select(User).where(User.username == old_username)).first()
            if not user:
                return False
            username_changed = new_username != old_username
            user.username = new_username
            if remove_password:
                user.password_hash = ""
            elif password:
                user.password_hash = hash_secret(password)
            if remove_pin:
                user.pin_hash = ""
            elif pin:
                user.pin_hash = hash_secret(pin)
            user.permissions = list(permissions)
            if profile_picture is not None:
                user.profile_picture = profile_picture
            session.add(user)

            if username_changed:
                entries = session.exec(select(CalendarEntry)).all()
                for entry in entries:
                    changed = False
                    if old_username in entry.managers:
                        entry.managers = [
                            new_username if u == old_username else u for u in entry.managers
                        ]
                        changed = True
                    if old_username in entry.responsible:
                        entry.responsible = [
                            new_username if u == old_username else u for u in entry.responsible
                        ]
                        changed = True
                    recurrences: List[Recurrence] = []
                    for rec in entry.recurrences:
                        rec_obj = (
                            rec if isinstance(rec, Recurrence) else Recurrence.model_validate(rec)
                        )
                        rec_changed = False
                        if old_username in rec_obj.responsible:
                            rec_obj.responsible = [
                                new_username if u == old_username else u
                                for u in rec_obj.responsible
                            ]
                            rec_changed = True
                        for deleg in rec_obj.delegations:
                            if old_username in deleg.responsible:
                                deleg.responsible = [
                                    new_username if u == old_username else u
                                    for u in deleg.responsible
                                ]
                                rec_changed = True
                        recurrences.append(rec_obj)
                        if rec_changed:
                            changed = True
                    if changed:
                        entry.recurrences = recurrences
                        session.add(entry)

                completions = session.exec(
                    select(ChoreCompletion).where(
                        ChoreCompletion.completed_by == old_username
                    )
                ).all()
                for comp in completions:
                    comp.completed_by = new_username
                    session.add(comp)

            session.commit()
            return True

    def delete(self, username: str) -> None:
        if username == "Viewer":
            return
        with Session(self.engine) as session:
            user = session.exec(select(User).where(User.username == username)).first()
            if user:
                session.delete(user)
                session.commit()

    def has_permission(self, username: str, permission: str) -> bool:
        user = self.get(username)
        return bool(user) and ("admin" in user.permissions or permission in user.permissions)

    def verify(self, username: str, password: str) -> Optional[User]:
        user = self.get_case_insensitive(username)
        if not user or not user.password_hash:
            return None
        if pwd_context.verify(password, user.password_hash):
            return user
        return None


def init_db(engine) -> None:
    """Create tables, verify schema revision and populate default users."""

    db_path = Path(engine.url.database)
    first_run = not db_path.exists()

    cfg = Config(str(Path(__file__).resolve().parent.parent / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", str(engine.url))
    if first_run:
        SQLModel.metadata.create_all(engine)
        command.stamp(cfg, "head")

    script = ScriptDirectory.from_config(cfg)
    head = script.get_current_head()
    with engine.connect() as conn:
        try:
            row = conn.execute(text("SELECT version_num FROM alembic_version")).first()
        except OperationalError as exc:
            raise RuntimeError(
                "Database schema is missing Alembic version information. "
                "Run 'uv run alembic upgrade head' before starting the server. "
                "See README.md under 'Database migrations'."
            ) from exc
    if not row or row[0] != head:
        raise RuntimeError(
            "Database schema is out of date. Run 'uv run alembic upgrade head' "
            "before starting the server. See README.md under 'Database migrations'."
        )

    with Session(engine) as session:
        users = session.exec(select(User)).all()
        if not any("admin" in u.permissions for u in users):
            admin = next((u for u in users if u.username == "Admin"), None)
            if admin:
                admin.password_hash = hash_secret("admin")
                admin.pin_hash = hash_secret("0000")
                admin.permissions = ["admin"]
            else:
                admin = User(
                    username="Admin",
                    password_hash=hash_secret("admin"),
                    pin_hash=hash_secret("0000"),
                    permissions=["admin"],
                )
            session.add(admin)

        viewer_perms = ["chores.read", "events.read", "reminders.read"]
        viewer = session.exec(select(User).where(User.username == "Viewer")).first()
        if not viewer:
            viewer = User(
                username="Viewer",
                password_hash="",
                pin_hash="",
                permissions=viewer_perms,
            )
            session.add(viewer)
        else:
            viewer.password_hash = ""
            viewer.pin_hash = ""
            viewer.permissions = viewer_perms
            session.add(viewer)
        session.commit()

