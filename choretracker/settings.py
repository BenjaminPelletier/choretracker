from __future__ import annotations

from sqlmodel import Field, Session, SQLModel


class Setting(SQLModel, table=True):
    key: str = Field(primary_key=True)
    value: int


class SettingsStore:
    """CRUD helper for :class:`Setting` objects."""

    def __init__(self, engine):
        self.engine = engine

    def get_logout_duration(self) -> int:
        with Session(self.engine) as session:
            setting = session.get(Setting, "logout_duration_minutes")
            if not setting:
                setting = Setting(key="logout_duration_minutes", value=1)
                session.add(setting)
                session.commit()
            return setting.value

    def set_logout_duration(self, minutes: int) -> None:
        with Session(self.engine) as session:
            setting = session.get(Setting, "logout_duration_minutes")
            if setting:
                setting.value = minutes
            else:
                setting = Setting(key="logout_duration_minutes", value=minutes)
            session.add(setting)
            session.commit()
