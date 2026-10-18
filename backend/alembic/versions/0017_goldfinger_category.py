"""金手指单独成一类：原来带「金手指」标签的段落条目搬进「金手指」。

等级体系（阶梯）和自建类别里带标签的不动；世界概况不动；还有下级地方的不动。
降级时一律放回特殊规则（原来在哪一类没有记）。
"""

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE world_entries AS e
        SET category = '金手指', style = 'paragraph', parent_id = NULL
        WHERE e.tags @> '["金手指"]'::jsonb
          AND e.style = 'paragraph'
          AND e.category IN ('特殊规则', '物品与功法', '往事与秘密', '势力划分', '世界与地图')
          AND NOT (e.category = '世界与地图' AND btrim(e.name) = '世界概况')
          AND NOT EXISTS (SELECT 1 FROM world_entries AS c WHERE c.parent_id = e.id)
        """
    )


def downgrade() -> None:
    op.execute("UPDATE world_entries SET category = '特殊规则' WHERE category = '金手指'")
