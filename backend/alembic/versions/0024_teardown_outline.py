"""拆书第二批：补原书分卷标记、拆书模型分工及同书单任务约束。"""

import sqlalchemy as sa

from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE books SET teardown = teardown || jsonb_build_object('original_volumes', "
        "(teardown->>'open_volume_id') IS NULL) "
        "WHERE source = 'teardown' AND teardown->>'stage' <> 'confirming' "
        "AND NOT (teardown ? 'original_volumes')"
    )
    op.execute("INSERT INTO role_assignments (role, profile_id) VALUES ('teardown', NULL) ON CONFLICT DO NOTHING")
    op.create_index(
        "ix_jobs_one_active_teardown",
        "jobs",
        ["book_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'teardown' AND status IN ('queued', 'running')"),
    )


def downgrade() -> None:
    op.drop_index("ix_jobs_one_active_teardown", table_name="jobs")
    op.execute("DELETE FROM role_assignments WHERE role = 'teardown'")
    op.execute("UPDATE books SET teardown = teardown - 'original_volumes' WHERE source = 'teardown'")
