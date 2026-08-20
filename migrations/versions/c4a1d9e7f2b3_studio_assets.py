"""add Commerce Studio tables and storage metadata

Revision ID: c4a1d9e7f2b3
Revises: 7634e028e338
Create Date: 2026-08-18 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "c4a1d9e7f2b3"
down_revision = "7634e028e338"
branch_labels = None
depends_on = None


def _has_table(table_name):
    return sa.inspect(op.get_bind()).has_table(table_name)


def _has_column(table_name, column_name):
    if not _has_table(table_name):
        return False
    return any(
        column["name"] == column_name
        for column in sa.inspect(op.get_bind()).get_columns(table_name)
    )


def _create_table_if_missing(*args, **kwargs):
    """Handle databases that already contain the earlier Studio tables."""

    if not _has_table(args[0]):
        op.create_table(*args, **kwargs)


def _create_index_if_missing(index_name, table_name, columns):
    indexes = sa.inspect(op.get_bind()).get_indexes(table_name)
    if not any(index.get("name") == index_name for index in indexes):
        op.create_index(index_name, table_name, columns)


def upgrade():
    if not _has_column("admin_photo", "storage_path"):
        op.add_column(
            "admin_photo",
            sa.Column("storage_path", sa.String(length=1000), nullable=True),
        )

    _create_table_if_missing(
        "studio_provider",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("base_url", sa.String(length=500), nullable=False),
        sa.Column("api_key", sa.Text(), nullable=True),
        sa.Column("generation_path", sa.String(length=255), nullable=True),
        sa.Column("result_path", sa.String(length=255), nullable=True),
        sa.Column("balance_path", sa.String(length=255), nullable=True),
        sa.Column("token_balance_path", sa.String(length=255), nullable=True),
        sa.Column("auth_header", sa.String(length=80), nullable=True),
        sa.Column("auth_prefix", sa.String(length=80), nullable=True),
        sa.Column("timeout", sa.Integer(), nullable=True),
        sa.Column("enabled", sa.Integer(), nullable=True),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    _create_table_if_missing(
        "studio_model",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("model_code", sa.String(length=160), nullable=False),
        sa.Column("media_type", sa.String(length=20), nullable=False),
        sa.Column("generation_path", sa.String(length=255), nullable=True),
        sa.Column("result_path", sa.String(length=255), nullable=True),
        sa.Column("parameter_schema", sa.Text(), nullable=False),
        sa.Column("capabilities", sa.Text(), nullable=True),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("enabled", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["provider_id"], ["studio_provider.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    _create_table_if_missing(
        "studio_product",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("brand", sa.String(length=160), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("product_profile", sa.Text(), nullable=True),
        sa.Column("product_memory", sa.Text(), nullable=True),
        sa.Column("generation_rules", sa.Text(), nullable=True),
        sa.Column("forbidden_rules", sa.Text(), nullable=True),
        sa.Column("asset_urls", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    _create_table_if_missing(
        "studio_skill",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column("media_type", sa.String(length=20), nullable=True),
        sa.Column("version", sa.String(length=40), nullable=True),
        sa.Column("tags", sa.String(length=500), nullable=True),
        sa.Column("prompt_template", sa.Text(), nullable=True),
        sa.Column("negative_prompt", sa.Text(), nullable=True),
        sa.Column("file_name", sa.String(length=255), nullable=True),
        sa.Column("file_type", sa.String(length=30), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("storage_asset_id", sa.Integer(), nullable=True),
        sa.Column("enabled", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    _create_table_if_missing(
        "studio_generation_task",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_code", sa.String(length=7), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("media_type", sa.String(length=20), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=True),
        sa.Column("model_id", sa.Integer(), nullable=True),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("final_prompt", sa.Text(), nullable=True),
        sa.Column("negative_prompt", sa.Text(), nullable=True),
        sa.Column("request_body", sa.Text(), nullable=True),
        sa.Column("provider_task_id", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=True),
        sa.Column("result_payload", sa.Text(), nullable=True),
        sa.Column("output_url", sa.String(length=1000), nullable=True),
        sa.Column("output_format", sa.String(length=40), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["model_id"], ["studio_model.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["product_id"], ["studio_product.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_code"),
    )
    _create_table_if_missing(
        "studio_product_asset",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("url", sa.String(length=1000), nullable=False),
        sa.Column("asset_type", sa.String(length=20), nullable=True),
        sa.Column("role", sa.String(length=40), nullable=True),
        sa.Column("sort", sa.Integer(), nullable=True),
        sa.Column("enabled", sa.Integer(), nullable=True),
        sa.Column("storage_asset_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["product_id"], ["studio_product.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    _create_table_if_missing(
        "studio_asset",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("asset_type", sa.String(length=20), nullable=False),
        sa.Column("purpose", sa.String(length=40), nullable=False),
        sa.Column("retention_policy", sa.String(length=20), nullable=False),
        sa.Column("storage_path", sa.String(length=1000), nullable=False),
        sa.Column("public_url", sa.String(length=1200), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=True),
        sa.Column("content_type", sa.String(length=160), nullable=True),
        sa.Column("file_size", sa.BigInteger(), nullable=True),
        sa.Column("checksum", sa.String(length=128), nullable=True),
        sa.Column("generation_task_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    if not _has_column("studio_skill", "storage_asset_id"):
        op.add_column(
            "studio_skill",
            sa.Column("storage_asset_id", sa.Integer(), nullable=True),
        )
    if not _has_column("studio_product_asset", "storage_asset_id"):
        op.add_column(
            "studio_product_asset",
            sa.Column("storage_asset_id", sa.Integer(), nullable=True),
        )

    _create_index_if_missing(
        "ix_studio_asset_retention",
        "studio_asset",
        ["retention_policy", "status", "expires_at"],
    )
    _create_index_if_missing(
        "ix_studio_asset_generation_task",
        "studio_asset",
        ["generation_task_id", "purpose", "status"],
    )


def downgrade():
    op.drop_index("ix_studio_asset_generation_task", table_name="studio_asset")
    op.drop_index("ix_studio_asset_retention", table_name="studio_asset")
    op.drop_table("studio_asset")
    op.drop_table("studio_product_asset")
    op.drop_table("studio_generation_task")
    op.drop_table("studio_skill")
    op.drop_table("studio_product")
    op.drop_table("studio_model")
    op.drop_table("studio_provider")
    op.drop_column("admin_photo", "storage_path")
