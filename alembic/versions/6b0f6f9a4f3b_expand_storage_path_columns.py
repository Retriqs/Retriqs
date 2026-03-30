"""expand_storage_path_columns

Revision ID: 6b0f6f9a4f3b
Revises: d053498dcad0
Create Date: 2026-03-13 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "6b0f6f9a4f3b"
down_revision: Union[str, None] = "d053498dcad0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("graph_storages") as batch_op:
        batch_op.alter_column(
            "work_dir",
            existing_type=sa.String(length=50),
            type_=sa.String(length=1024),
            existing_nullable=False,
        )

    with op.batch_alter_table("app_settings") as batch_op:
        batch_op.alter_column(
            "value",
            existing_type=sa.String(length=100),
            type_=sa.String(length=1024),
            existing_nullable=True,
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("app_settings") as batch_op:
        batch_op.alter_column(
            "value",
            existing_type=sa.String(length=1024),
            type_=sa.String(length=100),
            existing_nullable=True,
        )

    with op.batch_alter_table("graph_storages") as batch_op:
        batch_op.alter_column(
            "work_dir",
            existing_type=sa.String(length=1024),
            type_=sa.String(length=50),
            existing_nullable=False,
        )
