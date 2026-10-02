"""${message}"""
from alembic import op
import sqlalchemy as sa
${imports if imports else ""}
revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}

def upgrade() -> None:
    """场景 1.2：升级结构。"""
    ${upgrades if upgrades else "pass"}

def downgrade() -> None:
    """场景 1.2：回退结构。"""
    ${downgrades if downgrades else "pass"}
