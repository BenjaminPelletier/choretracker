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
                return 1

            # Clamp existing values to the valid range of 1-15 minutes. Older
            # databases may contain out-of-range values (e.g. 0) which would
            # cause the frontend to refresh constantly. Correct the stored
            # value so the application behaves consistently.
            if setting.value < 1:
                setting.value = 1
                session.add(setting)
                session.commit()
            elif setting.value > 15:
                setting.value = 15
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
