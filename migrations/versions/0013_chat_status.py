"""chats: когда видели и может ли бот писать

Экран «Чаты» показывал только то, что админ привязал руками через
/setgroup. Бот при этом молча сидел в десятках групп, про которые в
базе не было ни строки: узнать, где он есть и где ему запретили
писать, было нечем.

Две колонки:
  status      — «member» / «left» / «kicked» по последней проверке;
  checked_at  — когда проверяли. Колонка нужна, чтобы отличать чат,
                где бота выгнали, от чата, который ещё не проверяли.

Всё nullable: старые строки остаются валидными.
"""
from alembic import op
import sqlalchemy as sa

revision = "0013_chat_status"
down_revision = "0012_sent_message"
branch_labels = None
depends_on = None


def _cols() -> set[str]:
    insp = sa.inspect(op.get_bind())
    return {c["name"] for c in insp.get_columns("chats")}


def upgrade() -> None:
    have = _cols()
    if "status" not in have:
        op.add_column("chats", sa.Column("status", sa.String(16), nullable=True))
    if "checked_at" not in have:
        op.add_column("chats", sa.Column("checked_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    have = _cols()
    if "checked_at" in have:
        op.drop_column("chats", "checked_at")
    if "status" in have:
        op.drop_column("chats", "status")
