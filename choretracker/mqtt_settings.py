from __future__ import annotations

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel


class MQTTSettings(SQLModel, table=True):
    """One installation's broker configuration and discovery cleanup history."""

    id: int = Field(default=1, primary_key=True)
    host: str = ""
    port: int = 1883
    username: str = ""
    password: str = ""
    tls: bool = False
    sensors: dict[str, list[int]] = Field(default_factory=dict, sa_column=Column(JSON))
    advertised: dict[str, list[int]] = Field(default_factory=dict, sa_column=Column(JSON))
