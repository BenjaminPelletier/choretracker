"""Add MQTT settings and Home Assistant discovery cleanup history."""
from alembic import op
import sqlalchemy as sa

revision = "e7f8a9b0c1d2"
down_revision = "d4a3b2c1e5f6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "mqttsettings",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("host", sa.String(), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(), nullable=False),
        sa.Column("password", sa.String(), nullable=False),
        sa.Column("tls", sa.Boolean(), nullable=False),
        sa.Column("sensors", sa.JSON(), nullable=False),
        sa.Column("advertised", sa.JSON(), nullable=False),
    )


def downgrade():
    op.drop_table("mqttsettings")
