"""add GoFastDFS-backed batch prompt documents

Revision ID: y8z9a0b1c2d3
Revises: x7y8z9a0b1c2
Create Date: 2026-09-02 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "y8z9a0b1c2d3"
down_revision = "x7y8z9a0b1c2"
branch_labels = None
depends_on = None


TABLE_NAME = "studio_batch_prompt"


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table(TABLE_NAME):
        return

    op.create_table(
        TABLE_NAME,
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("dept_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "media_type",
            sa.String(length=20),
            nullable=False,
            server_default="IMAGE",
        ),
        sa.Column("product_id", sa.Integer(), nullable=True),
        sa.Column("skill_id", sa.Integer(), nullable=True),
        sa.Column("storage_asset_id", sa.Integer(), nullable=True),
        sa.Column("planner_model_id", sa.Integer(), nullable=True),
        sa.Column("planner_model_code", sa.String(length=160), nullable=True),
        sa.Column(
            "product_name_snapshot",
            sa.String(length=160),
            nullable=True,
        ),
        sa.Column("skill_name_snapshot", sa.String(length=160), nullable=True),
        sa.Column("skill_prompt_snapshot", sa.Text(), nullable=True),
        sa.Column("creative_prompt", sa.Text(), nullable=True),
        sa.Column(
            "version_count",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["studio_product.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["skill_id"],
            ["studio_skill.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["storage_asset_id"],
            ["studio_asset.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["planner_model_id"],
            ["studio_model.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_studio_batch_prompt_scope_time",
        TABLE_NAME,
        ["dept_id", "user_id", "media_type", "created_at"],
    )
    op.create_index(
        "ix_studio_batch_prompt_status_time",
        TABLE_NAME,
        ["status", "created_at"],
    )


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(TABLE_NAME):
        return
    op.drop_index(
        "ix_studio_batch_prompt_status_time",
        table_name=TABLE_NAME,
    )
    op.drop_index(
        "ix_studio_batch_prompt_scope_time",
        table_name=TABLE_NAME,
    )
    op.drop_table(TABLE_NAME)
