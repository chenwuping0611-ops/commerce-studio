"""remove the unused Studio generation audit log table"""

from alembic import op
import sqlalchemy as sa


revision = "k4l5m6n7o8p9"
down_revision = "j3k4l5m6n7"
branch_labels = None
depends_on = None


TABLE_NAME = "studio_generation_audit_log"


def _has_table():
    return sa.inspect(op.get_bind()).has_table(TABLE_NAME)


def _has_index(index_name):
    if not _has_table():
        return False
    return any(
        index["name"] == index_name
        for index in sa.inspect(op.get_bind()).get_indexes(TABLE_NAME)
    )


def upgrade():
    if _has_table():
        op.drop_table(TABLE_NAME)


def downgrade():
    if not _has_table():
        op.create_table(
            TABLE_NAME,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("trace_code", sa.String(length=40), nullable=True),
            sa.Column("generation_task_id", sa.Integer(), nullable=True),
            sa.Column("user_id", sa.Integer(), nullable=True),
            sa.Column(
                "media_type",
                sa.String(length=20),
                nullable=False,
                server_default="IMAGE",
            ),
            sa.Column("event_type", sa.String(length=40), nullable=False),
            sa.Column(
                "status",
                sa.String(length=20),
                nullable=False,
                server_default="PENDING",
            ),
            sa.Column("provider_id", sa.Integer(), nullable=True),
            sa.Column("model_id", sa.Integer(), nullable=True),
            sa.Column("product_id", sa.Integer(), nullable=True),
            sa.Column("skill_id", sa.Integer(), nullable=True),
            sa.Column("summary", sa.String(length=500), nullable=True),
            sa.Column("request_payload", sa.Text(), nullable=True),
            sa.Column("response_payload", sa.Text(), nullable=True),
            sa.Column("context_payload", sa.Text(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(
                ["generation_task_id"],
                ["studio_generation_task.id"],
                ondelete="CASCADE",
            ),
        )
    if not _has_index("ix_studio_generation_audit_log_trace_code"):
        op.create_index(
            "ix_studio_generation_audit_log_trace_code",
            TABLE_NAME,
            ["trace_code"],
            unique=False,
        )
    if not _has_index("ix_studio_generation_audit_log_generation_task_id"):
        op.create_index(
            "ix_studio_generation_audit_log_generation_task_id",
            TABLE_NAME,
            ["generation_task_id"],
            unique=False,
        )
    if not _has_index("ix_studio_generation_audit_log_user_id"):
        op.create_index(
            "ix_studio_generation_audit_log_user_id",
            TABLE_NAME,
            ["user_id"],
            unique=False,
        )
