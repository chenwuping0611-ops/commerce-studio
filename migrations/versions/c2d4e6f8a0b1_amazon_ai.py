"""add Amazon AI workspace tables

Revision ID: c2d4e6f8a0b1
Revises: b7c9d1e2f3a4
Create Date: 2026-08-24 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "c2d4e6f8a0b1"
down_revision = "b7c9d1e2f3a4"
branch_labels = None
depends_on = None


def _has_table(table_name):
    return sa.inspect(op.get_bind()).has_table(table_name)


def _create_index(index_name, table_name, columns):
    inspector = sa.inspect(op.get_bind())
    if not _has_table(table_name):
        return
    existing = {
        index.get("name")
        for index in inspector.get_indexes(table_name)
    }
    if index_name not in existing:
        op.create_index(index_name, table_name, columns)


def upgrade():
    if not _has_table("amazon_listing_project"):
        op.create_table(
            "amazon_listing_project",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("project_code", sa.String(length=64), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("site", sa.String(length=40), nullable=False),
            sa.Column("language", sa.String(length=32), nullable=True),
            sa.Column("asin", sa.String(length=32), nullable=True),
            sa.Column("sku", sa.String(length=120), nullable=True),
            sa.Column("category", sa.String(length=255), nullable=True),
            sa.Column("studio_product_id", sa.Integer(), nullable=True),
            sa.Column("owner_id", sa.Integer(), nullable=True),
            sa.Column(
                "status",
                sa.String(length=30),
                nullable=False,
                server_default="DRAFT",
            ),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(
                ["studio_product_id"],
                ["studio_product.id"],
                ondelete="SET NULL",
            ),
            sa.ForeignKeyConstraint(
                ["owner_id"],
                ["admin_user.id"],
                ondelete="SET NULL",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("project_code"),
        )

    if not _has_table("amazon_competitor"):
        op.create_table(
            "amazon_competitor",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("listing_project_id", sa.Integer(), nullable=True),
            sa.Column("site", sa.String(length=40), nullable=False),
            sa.Column("asin", sa.String(length=32), nullable=True),
            sa.Column("brand", sa.String(length=160), nullable=True),
            sa.Column("title", sa.String(length=500), nullable=True),
            sa.Column("product_url", sa.String(length=1200), nullable=True),
            sa.Column("price", sa.Numeric(18, 2), nullable=True),
            sa.Column("currency", sa.String(length=12), nullable=True),
            sa.Column("rating", sa.Numeric(4, 2), nullable=True),
            sa.Column("review_count", sa.Integer(), nullable=True),
            sa.Column("bullet_points", sa.Text(), nullable=True),
            sa.Column("feature_summary", sa.Text(), nullable=True),
            sa.Column("analysis_text", sa.Text(), nullable=True),
            sa.Column("raw_data_json", sa.Text(), nullable=True),
            sa.Column("source_url", sa.String(length=1200), nullable=True),
            sa.Column("collected_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(
                ["listing_project_id"],
                ["amazon_listing_project.id"],
                ondelete="SET NULL",
            ),
            sa.PrimaryKeyConstraint("id"),
        )

    if not _has_table("amazon_keyword"):
        op.create_table(
            "amazon_keyword",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("listing_project_id", sa.Integer(), nullable=True),
            sa.Column("site", sa.String(length=40), nullable=False),
            sa.Column("language", sa.String(length=32), nullable=True),
            sa.Column("keyword", sa.String(length=255), nullable=False),
            sa.Column("normalized_keyword", sa.String(length=255), nullable=False),
            sa.Column("search_volume", sa.Numeric(18, 4), nullable=True),
            sa.Column("competition", sa.Numeric(10, 4), nullable=True),
            sa.Column("relevance", sa.Numeric(10, 4), nullable=True),
            sa.Column("cpc", sa.Numeric(18, 4), nullable=True),
            sa.Column("intent", sa.String(length=80), nullable=True),
            sa.Column("source", sa.String(length=120), nullable=True),
            sa.Column("analysis_text", sa.Text(), nullable=True),
            sa.Column("raw_data_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(
                ["listing_project_id"],
                ["amazon_listing_project.id"],
                ondelete="SET NULL",
            ),
            sa.PrimaryKeyConstraint("id"),
        )

    if not _has_table("amazon_review"):
        op.create_table(
            "amazon_review",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("listing_project_id", sa.Integer(), nullable=True),
            sa.Column("site", sa.String(length=40), nullable=False),
            sa.Column("asin", sa.String(length=32), nullable=True),
            sa.Column("external_review_id", sa.String(length=160), nullable=True),
            sa.Column("rating", sa.Numeric(4, 2), nullable=True),
            sa.Column("title", sa.String(length=500), nullable=True),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("language", sa.String(length=32), nullable=True),
            sa.Column("sentiment", sa.String(length=40), nullable=True),
            sa.Column("pain_points", sa.Text(), nullable=True),
            sa.Column("praise_points", sa.Text(), nullable=True),
            sa.Column("analysis_text", sa.Text(), nullable=True),
            sa.Column("raw_data_json", sa.Text(), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(
                ["listing_project_id"],
                ["amazon_listing_project.id"],
                ondelete="SET NULL",
            ),
            sa.PrimaryKeyConstraint("id"),
        )

    if not _has_table("amazon_listing_version"):
        op.create_table(
            "amazon_listing_version",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("listing_project_id", sa.Integer(), nullable=False),
            sa.Column("version_no", sa.Integer(), nullable=False),
            sa.Column(
                "status",
                sa.String(length=30),
                nullable=False,
                server_default="DRAFT",
            ),
            sa.Column("title", sa.String(length=500), nullable=True),
            sa.Column("bullet_points", sa.Text(), nullable=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("search_terms", sa.Text(), nullable=True),
            sa.Column("backend_keywords", sa.Text(), nullable=True),
            sa.Column("aplus_content", sa.Text(), nullable=True),
            sa.Column("content_json", sa.Text(), nullable=True),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(
                ["listing_project_id"],
                ["amazon_listing_project.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["created_by"],
                ["admin_user.id"],
                ondelete="SET NULL",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "listing_project_id",
                "version_no",
                name="uq_amazon_listing_version_project_no",
            ),
        )

    if not _has_table("amazon_listing_audit"):
        op.create_table(
            "amazon_listing_audit",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("listing_project_id", sa.Integer(), nullable=False),
            sa.Column("listing_version_id", sa.Integer(), nullable=False),
            sa.Column("audit_type", sa.String(length=40), nullable=False),
            sa.Column("score", sa.Numeric(8, 2), nullable=True),
            sa.Column("issues_json", sa.Text(), nullable=True),
            sa.Column("suggestions_json", sa.Text(), nullable=True),
            sa.Column(
                "status",
                sa.String(length=30),
                nullable=False,
                server_default="COMPLETED",
            ),
            sa.Column("summary", sa.Text(), nullable=True),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(
                ["listing_project_id"],
                ["amazon_listing_project.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["listing_version_id"],
                ["amazon_listing_version.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["created_by"],
                ["admin_user.id"],
                ondelete="SET NULL",
            ),
            sa.PrimaryKeyConstraint("id"),
        )

    if not _has_table("amazon_ai_task"):
        op.create_table(
            "amazon_ai_task",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("task_code", sa.String(length=32), nullable=False),
            sa.Column("task_type", sa.String(length=40), nullable=False),
            sa.Column(
                "status",
                sa.String(length=20),
                nullable=False,
                server_default="PENDING",
            ),
            sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("max_retries", sa.Integer(), nullable=False, server_default="3"),
            sa.Column("user_id", sa.Integer(), nullable=True),
            sa.Column("model_id", sa.Integer(), nullable=True),
            sa.Column("skill_id", sa.Integer(), nullable=True),
            sa.Column("studio_product_id", sa.Integer(), nullable=True),
            sa.Column("input_refs_json", sa.Text(), nullable=True),
            sa.Column("result_refs_json", sa.Text(), nullable=True),
            sa.Column("request_digest", sa.String(length=64), nullable=True),
            sa.Column("response_digest", sa.String(length=64), nullable=True),
            sa.Column("provider_task_id", sa.String(length=255), nullable=True),
            sa.Column("error_code", sa.String(length=80), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("scheduled_at", sa.DateTime(), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("heartbeat_at", sa.DateTime(), nullable=True),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(
                ["user_id"],
                ["admin_user.id"],
                ondelete="SET NULL",
            ),
            sa.ForeignKeyConstraint(
                ["model_id"],
                ["studio_model.id"],
                ondelete="SET NULL",
            ),
            sa.ForeignKeyConstraint(
                ["skill_id"],
                ["studio_skill.id"],
                ondelete="SET NULL",
            ),
            sa.ForeignKeyConstraint(
                ["studio_product_id"],
                ["studio_product.id"],
                ondelete="SET NULL",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("task_code"),
        )

    if not _has_table("amazon_ai_task_target"):
        op.create_table(
            "amazon_ai_task_target",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("task_id", sa.Integer(), nullable=False),
            sa.Column("relation_type", sa.String(length=12), nullable=False),
            sa.Column("target_type", sa.String(length=40), nullable=False),
            sa.Column("competitor_id", sa.Integer(), nullable=True),
            sa.Column("keyword_id", sa.Integer(), nullable=True),
            sa.Column("review_id", sa.Integer(), nullable=True),
            sa.Column("listing_project_id", sa.Integer(), nullable=True),
            sa.Column("listing_version_id", sa.Integer(), nullable=True),
            sa.Column("listing_audit_id", sa.Integer(), nullable=True),
            sa.Column("sort", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(
                ["task_id"],
                ["amazon_ai_task.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["competitor_id"],
                ["amazon_competitor.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["keyword_id"],
                ["amazon_keyword.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["review_id"],
                ["amazon_review.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["listing_project_id"],
                ["amazon_listing_project.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["listing_version_id"],
                ["amazon_listing_version.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["listing_audit_id"],
                ["amazon_listing_audit.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
        )

    _create_index(
        "ix_amazon_ai_task_status_created",
        "amazon_ai_task",
        ["status", "created_at"],
    )
    _create_index(
        "ix_amazon_ai_task_type_status",
        "amazon_ai_task",
        ["task_type", "status"],
    )
    _create_index(
        "ix_amazon_ai_task_user_created",
        "amazon_ai_task",
        ["user_id", "created_at"],
    )
    _create_index(
        "ix_amazon_ai_task_target_task_relation",
        "amazon_ai_task_target",
        ["task_id", "relation_type"],
    )
    _create_index(
        "ix_amazon_ai_task_target_competitor",
        "amazon_ai_task_target",
        ["competitor_id"],
    )
    _create_index(
        "ix_amazon_ai_task_target_keyword",
        "amazon_ai_task_target",
        ["keyword_id"],
    )
    _create_index(
        "ix_amazon_ai_task_target_review",
        "amazon_ai_task_target",
        ["review_id"],
    )
    _create_index(
        "ix_amazon_ai_task_target_listing_project",
        "amazon_ai_task_target",
        ["listing_project_id"],
    )
    _create_index(
        "ix_amazon_ai_task_target_listing_version",
        "amazon_ai_task_target",
        ["listing_version_id"],
    )
    _create_index(
        "ix_amazon_ai_task_target_listing_audit",
        "amazon_ai_task_target",
        ["listing_audit_id"],
    )
    _create_index(
        "ix_amazon_competitor_site_asin",
        "amazon_competitor",
        ["site", "asin"],
    )
    _create_index(
        "ix_amazon_competitor_project_created",
        "amazon_competitor",
        ["listing_project_id", "created_at"],
    )
    _create_index(
        "ix_amazon_keyword_site_normalized",
        "amazon_keyword",
        ["site", "normalized_keyword"],
    )
    _create_index(
        "ix_amazon_keyword_project_created",
        "amazon_keyword",
        ["listing_project_id", "created_at"],
    )
    _create_index(
        "ix_amazon_review_site_asin",
        "amazon_review",
        ["site", "asin"],
    )
    _create_index(
        "ix_amazon_review_project_created",
        "amazon_review",
        ["listing_project_id", "created_at"],
    )
    _create_index(
        "ix_amazon_listing_project_site_status",
        "amazon_listing_project",
        ["site", "status"],
    )
    _create_index(
        "ix_amazon_listing_project_product",
        "amazon_listing_project",
        ["studio_product_id"],
    )
    _create_index(
        "ix_amazon_listing_version_project_status",
        "amazon_listing_version",
        ["listing_project_id", "status"],
    )
    _create_index(
        "ix_amazon_listing_audit_project_version",
        "amazon_listing_audit",
        ["listing_project_id", "listing_version_id"],
    )
    _create_index(
        "ix_amazon_listing_audit_status_created",
        "amazon_listing_audit",
        ["status", "created_at"],
    )


def downgrade():
    for table_name in (
        "amazon_ai_task_target",
        "amazon_ai_task",
        "amazon_listing_audit",
        "amazon_listing_version",
        "amazon_review",
        "amazon_keyword",
        "amazon_competitor",
        "amazon_listing_project",
    ):
        if _has_table(table_name):
            op.drop_table(table_name)
