"""Order author requirements by insertion sequence rather than wall-clock time."""

import sqlalchemy as sa

from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("author_requirements", sa.Column("seq", sa.Integer(), nullable=True))
    # Preserve each book's old order; ordering different books by id is arbitrary.
    op.execute(
        "WITH ordered AS ("
        "SELECT id, row_number() OVER (ORDER BY book_id, created_at, id) AS seq "
        "FROM author_requirements) "
        "UPDATE author_requirements r SET seq=ordered.seq FROM ordered WHERE r.id=ordered.id"
    )
    op.alter_column("author_requirements", "seq", existing_type=sa.Integer(), nullable=False)
    op.alter_column(
        "author_requirements", "seq", existing_type=sa.Integer(),
        existing_server_default=None, server_default=sa.Identity(),
    )
    # An empty ledger must start at 1; otherwise the next value follows the backfill.
    op.execute(
        "SELECT setval(pg_get_serial_sequence('author_requirements', 'seq'), "
        "coalesce(max(seq), 1), max(seq) IS NOT NULL) FROM author_requirements"
    )
    op.create_index("ix_author_requirements_seq", "author_requirements", ["seq"])


def downgrade() -> None:
    op.drop_index("ix_author_requirements_seq", table_name="author_requirements")
    # Dropping an identity column also drops its owned sequence.
    op.drop_column("author_requirements", "seq")
