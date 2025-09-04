import importlib
from datetime import datetime

import sqlalchemy as sa
from alembic import op

migration = importlib.import_module(
    "migrations.versions.16f872f43a3c_apply_entry_times_to_recurrences"
)


def test_migration_applies_times_and_stores_array(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    metadata = sa.MetaData()
    calendarentry = sa.Table(
        "calendarentry",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("first_start", sa.DateTime()),
        sa.Column("duration_seconds", sa.Integer()),
        sa.Column("recurrences", sa.JSON()),
    )
    metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(
            sa.insert(calendarentry),
            {
                "id": 1,
                "first_start": datetime(2000, 1, 1),
                "duration_seconds": 3600,
                "recurrences": [{"type": "Weekly"}],
            },
        )
        original_get_bind = op.get_bind
        op.get_bind = lambda: conn
        try:
            migration.upgrade()
        finally:
            op.get_bind = original_get_bind
        result = conn.execute(
            sa.select(calendarentry.c.recurrences).where(calendarentry.c.id == 1)
        ).scalar_one()
        assert isinstance(result, list)
        assert result[0]["first_start"] == "2000-01-08T00:00:00"
        assert result[0]["duration_seconds"] == 3600
