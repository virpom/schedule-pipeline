"""sent_message: id отправленного — чтобы ошибочную рассылку можно было отозвать

План 104. Bot API не отдаёт id уже отправленного сообщения, поэтому
отозвать вчерашнюю рассылку было нечем: 26.10.2026 ушло 3220 сообщений,
и удалить их можно было только руками у каждого получателя.

Удалить сообщение можно лишь в течение 48 часов, поэтому старые строки
чистит poller — держать их дольше незачем.

Создание новой таблицы: существующие не меняются.

Revision ID: 0012_sent_message
Revises: 0011_drop_bell_notify
Create Date: 2026-10-28
"""
from alembic import op
import sqlalchemy as sa

revision = "0012_sent_message"
down_revision = "0011_drop_bell_notify"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if "sent_message" in _tables():
        return
    op.create_table(
        "sent_message",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False,
                  server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sent_message_chat_id", "sent_message", ["chat_id"])
    op.create_index("ix_sent_message_created_at", "sent_message", ["created_at"])


def downgrade() -> None:
    if "sent_message" in _tables():
        op.drop_table("sent_message")
