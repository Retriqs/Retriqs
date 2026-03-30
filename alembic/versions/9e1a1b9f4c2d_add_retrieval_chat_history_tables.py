"""add_retrieval_chat_history_tables

Revision ID: 9e1a1b9f4c2d
Revises: 6b0f6f9a4f3b
Create Date: 2026-03-23 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9e1a1b9f4c2d"
down_revision: Union[str, None] = "6b0f6f9a4f3b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "retrieval_chats",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("storage_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["storage_id"], ["graph_storages.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_retrieval_chats_storage_id"),
        "retrieval_chats",
        ["storage_id"],
        unique=False,
    )

    op.create_table(
        "retrieval_chat_messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("chat_id", sa.Integer(), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("role IN ('user', 'assistant', 'system')"),
        sa.ForeignKeyConstraint(
            ["chat_id"], ["retrieval_chats.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("chat_id", "sequence_no"),
    )
    op.create_index(
        op.f("ix_retrieval_chat_messages_chat_id"),
        "retrieval_chat_messages",
        ["chat_id"],
        unique=False,
    )

    op.create_table(
        "retrieval_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=True),
        sa.Column("data", sa.JSON(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("references", sa.JSON(), nullable=True),
        sa.Column("trace", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["message_id"], ["retrieval_chat_messages.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("message_id"),
    )
    op.create_index(
        op.f("ix_retrieval_snapshots_message_id"),
        "retrieval_snapshots",
        ["message_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f("ix_retrieval_snapshots_message_id"), table_name="retrieval_snapshots"
    )
    op.drop_table("retrieval_snapshots")

    op.drop_index(
        op.f("ix_retrieval_chat_messages_chat_id"),
        table_name="retrieval_chat_messages",
    )
    op.drop_table("retrieval_chat_messages")

    op.drop_index(op.f("ix_retrieval_chats_storage_id"), table_name="retrieval_chats")
    op.drop_table("retrieval_chats")

