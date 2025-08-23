from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Set
import types
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
from sqlalchemy import Column, JSON


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class User(SQLModel, table=True):
    """Database representation of a user."""

    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True)
    password_hash: str
    pin_hash: str
    permissions: List[str] = Field(default_factory=list, sa_column=Column(JSON))


def hash_secret(secret: str) -> str:
    """Hash a password or PIN using bcrypt."""

    return pwd_context.hash(secret)


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

    def create(
        self, username: str, password: Optional[str], pin: Optional[str], permissions: Set[str]
    ) -> None:
        if username == "Viewer":
            return
        with Session(self.engine) as session:
            user = User(
                username=username,
                password_hash=hash_secret(password) if password else "",
                pin_hash=hash_secret(pin) if pin else "",
                permissions=list(permissions),
            )
            session.add(user)
            session.commit()

    def update(
        self,
        old_username: str,
        new_username: str,
        password: Optional[str],
        pin: Optional[str],
        permissions: Set[str],
        remove_password: bool = False,
        remove_pin: bool = False,
    ) -> None:
        if old_username == "Viewer":
            return
        with Session(self.engine) as session:
            user = session.exec(select(User).where(User.username == old_username)).first()
            if not user:
                return
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
            session.add(user)
            session.commit()

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

    def verify(self, username: str, password: str) -> bool:
        user = self.get(username)
        if not user or not user.password_hash:
            return False
        return pwd_context.verify(password, user.password_hash)


def init_db(engine) -> None:
    """Create tables and populate a default admin user on first run."""

    db_path = Path(engine.url.database)
    first_run = not db_path.exists()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        if first_run:
            admin = User(
                username="Admin",
                password_hash=hash_secret("admin"),
                pin_hash=hash_secret("0000"),
                permissions=["admin", "iam"],
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

