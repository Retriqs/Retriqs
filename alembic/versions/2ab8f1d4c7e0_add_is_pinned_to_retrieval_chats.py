"""add_is_pinned_to_retrieval_chats

Revision ID: 2ab8f1d4c7e0
Revises: 9e1a1b9f4c2d
Create Date: 2026-03-23 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "2ab8f1d4c7e0"
down_revision: Union[str, None] = "9e1a1b9f4c2d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("retrieval_chats") as batch_op:
        batch_op.add_column(
            sa.Column(
                "is_pinned",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            )
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("retrieval_chats") as batch_op:
        batch_op.drop_column("is_pinned")

