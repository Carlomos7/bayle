"""rebuild_runs remembers which merges.json entry each row came from (the file stays authoritative).

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("rebuild_runs") as batch:
        batch.add_column(sa.Column("fingerprint", sa.String(64), nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("rebuild_runs") as batch:
        batch.drop_column("fingerprint")
