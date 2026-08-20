"""add persistent AI analysis comments for generation tasks

Revision ID: f17a6c5e8d42
Revises: c4a1d9e7f2b3
Create Date: 2026-08-19 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "f17a6c5e8d42"
down_revision = "c4a1d9e7f2b3"
branch_labels = None
depends_on = None


def _has_table(table_name):
    return sa.inspect(op.get_bind()).has_table(table_name)


def upgrade():
    if _has_table("studio_generation_comment"):
        return
    op.create_table(
        "studio_generation_comment",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("generation_task_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("model_id", sa.Integer(), nullable=True),
        sa.Column(
            "comment_type",
            sa.String(length=30),
            nullable=False,
            server_default="AI_ANALYSIS",
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("request_body", sa.Text(), nullable=True),
        sa.Column("response_payload", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["generation_task_id"],
            ["studio_generation_task.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["model_id"],
            ["studio_model.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade():
    if _has_table("studio_generation_comment"):
        op.drop_table("studio_generation_comment")
