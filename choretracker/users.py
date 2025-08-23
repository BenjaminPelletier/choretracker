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

    def list_users(self) -> List[User]:
        with Session(self.engine) as session:
            return session.exec(select(User)).all()

    def get(self, username: str) -> Optional[User]:
        with Session(self.engine) as session:
            return session.exec(select(User).where(User.username == username)).first()

    def create(
        self, username: str, password: Optional[str], pin: Optional[str], permissions: Set[str]
    ) -> None:
        with Session(self.engine) as session:
            user = User(
                username=username,
                password_hash=hash_secret(password or ""),
                pin_hash=hash_secret(pin or ""),
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
    ) -> None:
        with Session(self.engine) as session:
            user = session.exec(select(User).where(User.username == old_username)).first()
            if not user:
                return
            user.username = new_username
            if password:
                user.password_hash = hash_secret(password)
            if pin:
                user.pin_hash = hash_secret(pin)
            user.permissions = list(permissions)
            session.add(user)
            session.commit()

    def delete(self, username: str) -> None:
        with Session(self.engine) as session:
            user = session.exec(select(User).where(User.username == username)).first()
            if user:
                session.delete(user)
                session.commit()

    def has_permission(self, username: str, permission: str) -> bool:
        user = self.get(username)
        return permission in user.permissions if user else False

    def verify(self, username: str, password: str) -> bool:
        user = self.get(username)
        return pwd_context.verify(password, user.password_hash) if user else False


def init_db(engine) -> None:
    """Create tables and populate a default admin user on first run."""

    db_path = Path(engine.url.database)
    first_run = not db_path.exists()
    SQLModel.metadata.create_all(engine)
    if first_run:
        with Session(engine) as session:
            admin = User(
                username="Admin",
                password_hash=hash_secret("admin"),
                pin_hash=hash_secret("0000"),
                permissions=["admin", "iam"],
            )
            session.add(admin)
            session.commit()

