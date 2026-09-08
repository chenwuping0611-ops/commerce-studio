import datetime

from applications.extensions import db


AMAZON_TASK_TYPES = (
    "COMPETITOR_ANALYZE",
    "KEYWORD_ANALYZE",
    "REVIEW_ANALYZE",
    "DIFFERENTIATION_GENERATE",
    "BASIC_INFO_CORRECT",
    "LISTING_GENERATE",
    "LISTING_AUDIT",
)

AMAZON_TASK_STATUSES = (
    "PENDING",
    "RUNNING",
    "SUCCEEDED",
    "FAILED",
    "CANCELLED",
)

AMAZON_TASK_TITLES = {
    "COMPETITOR_ANALYZE": "竞品分析",
    "KEYWORD_ANALYZE": "关键词分析",
    "REVIEW_ANALYZE": "Review分析",
    "DIFFERENTIATION_GENERATE": "差异化分析",
    "BASIC_INFO_CORRECT": "基础信息修正",
    "LISTING_GENERATE": "Listing创作",
    "LISTING_AUDIT": "Listing审核",
}


class AmazonAiTask(db.Model):
    """The single durable index for every Amazon AI workspace operation.

    Large model responses are deliberately not stored in this table. The
    result and input JSON fields contain only small references and metadata;
    the actual text lives in GoFastDFS and is read through FileService.
    """

    __tablename__ = "amazon_ai_workspace_task"
    __table_args__ = (
        db.Index(
            "ix_amazon_ai_workspace_task_dept_created",
            "dept_id",
            "created_at",
            "id",
        ),
        db.Index(
            "ix_amazon_ai_workspace_task_dept_type_created",
            "dept_id",
            "task_type",
            "created_at",
            "id",
        ),
        db.Index(
            "ix_amazon_ai_workspace_task_dept_status_created",
            "dept_id",
            "status",
            "created_at",
            "id",
        ),
        db.Index(
            "ix_amazon_ai_workspace_task_retention_expiry",
            "retention_policy",
            "status",
            "storage_cleanup_status",
            "expires_at",
            "id",
        ),
        db.Index(
            "ix_amazon_ai_workspace_task_user_created",
            "user_id",
            "created_at",
            "id",
        ),
        db.Index(
            "ix_amazon_ai_workspace_task_created_id",
            "created_at",
            "id",
        ),
        db.Index(
            "ix_amazon_ai_workspace_task_type_created_id",
            "task_type",
            "created_at",
            "id",
        ),
        db.Index(
            "ix_amazon_ai_workspace_task_type_status_finished",
            "task_type",
            "status",
            "finished_at",
            "id",
        ),
        db.Index(
            "ix_amazon_ai_workspace_task_dept_type_source",
            "dept_id",
            "task_type",
            "source_key",
            "id",
        ),
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    dept_id = db.Column(db.Integer, nullable=True, comment="所属部门")
    task_code = db.Column(db.String(32), nullable=False, unique=True)
    task_type = db.Column(db.String(40), nullable=False)
    title = db.Column(
        db.String(180),
        nullable=False,
        default="Amazon AI任务",
    )
    custom_name = db.Column(
        db.Text,
        nullable=True,
        comment="竞品分析、差异化分析和 Listing 创作的用户自定义名称",
    )
    source_key = db.Column(
        db.String(120),
        nullable=True,
        comment="用于竞品 ASIN、文件名和大数据量检索的短键",
    )
    status = db.Column(db.String(20), nullable=False, default="PENDING")
    priority = db.Column(db.Integer, nullable=False, default=0)
    progress = db.Column(db.Integer, nullable=False, default=0)
    retry_count = db.Column(db.Integer, nullable=False, default=0)
    max_retries = db.Column(db.Integer, nullable=False, default=3)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("admin_user.id", ondelete="SET NULL"),
        nullable=True,
    )
    model_id = db.Column(
        db.Integer,
        db.ForeignKey("studio_model.id", ondelete="SET NULL"),
        nullable=True,
    )
    skill_id = db.Column(
        db.Integer,
        db.ForeignKey("studio_skill.id", ondelete="SET NULL"),
        nullable=True,
    )
    studio_product_id = db.Column(
        db.Integer,
        db.ForeignKey("studio_product.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Small task metadata only. Do not place model output text here.
    source_urls_json = db.Column(db.Text, nullable=True)
    source_identifiers_json = db.Column(db.Text, nullable=True)
    source_task_codes_json = db.Column(db.Text, nullable=True)
    input_asset_ids_json = db.Column(db.Text, nullable=True)
    task_metadata_json = db.Column(db.Text, nullable=True)
    input_refs_json = db.Column(db.Text, nullable=True)
    result_refs_json = db.Column(db.Text, nullable=True)
    file_refs_json = db.Column(
        db.Text,
        nullable=True,
        comment="GoFastDFS input/result file snapshots",
    )

    output_asset_id = db.Column(
        db.Integer,
        db.ForeignKey("studio_asset.id", ondelete="SET NULL"),
        nullable=True,
    )
    output_url = db.Column(db.String(1200), nullable=True)
    output_filename = db.Column(db.String(255), nullable=True)
    output_checksum = db.Column(db.String(128), nullable=True)
    output_expires_at = db.Column(db.DateTime, nullable=True)

    retention_policy = db.Column(
        db.String(20),
        nullable=False,
        default="TTL_7D",
    )
    expires_at = db.Column(db.DateTime, nullable=True)
    storage_cleanup_status = db.Column(
        db.String(20),
        nullable=False,
        default="ACTIVE",
    )
    storage_cleanup_error = db.Column(db.Text, nullable=True)
    storage_deleted_at = db.Column(db.DateTime, nullable=True)
    request_digest = db.Column(db.String(64), nullable=True)
    response_digest = db.Column(db.String(64), nullable=True)
    provider_task_id = db.Column(db.String(255), nullable=True)
    error_code = db.Column(db.String(80), nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    scheduled_at = db.Column(db.DateTime, nullable=True)
    started_at = db.Column(db.DateTime, nullable=True)
    heartbeat_at = db.Column(db.DateTime, nullable=True)
    finished_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.now)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.datetime.now,
        onupdate=datetime.datetime.now,
    )

    model = db.relationship("StudioModel")
    skill = db.relationship("StudioSkill")
    studio_product = db.relationship("StudioProduct")
    source_links = db.relationship(
        "AmazonAiTaskSource",
        back_populates="task",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="(AmazonAiTaskSource.sort, AmazonAiTaskSource.id)",
    )
    dependency_links = db.relationship(
        "AmazonAiTaskDependency",
        foreign_keys="AmazonAiTaskDependency.task_id",
        back_populates="task",
        cascade="all, delete-orphan",
        lazy="select",
        passive_deletes=True,
    )
    upstream_links = db.relationship(
        "AmazonAiTaskDependency",
        foreign_keys="AmazonAiTaskDependency.source_task_id",
        back_populates="source_task",
        lazy="select",
        passive_deletes=True,
    )
    asset_links = db.relationship(
        "AmazonAiTaskAsset",
        back_populates="task",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="(AmazonAiTaskAsset.sort, AmazonAiTaskAsset.id)",
    )


class AmazonAiTaskSource(db.Model):
    """Normalized URL/ASIN sources attached to an Amazon AI task."""

    __tablename__ = "amazon_ai_task_source"
    __table_args__ = (
        db.UniqueConstraint(
            "task_id",
            "source_type",
            "source_key",
            name="uq_amazon_ai_task_source_key",
        ),
        db.Index(
            "ix_amazon_ai_task_source_type_key_task",
            "source_type",
            "source_key",
            "task_id",
        ),
        db.Index(
            "ix_amazon_ai_task_source_task_sort",
            "task_id",
            "sort",
            "id",
        ),
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    task_id = db.Column(
        db.Integer,
        db.ForeignKey("amazon_ai_workspace_task.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_type = db.Column(db.String(30), nullable=False, default="URL")
    source_key = db.Column(db.String(255), nullable=False)
    source_url = db.Column(db.String(2000), nullable=True)
    sort = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=datetime.datetime.now)

    task = db.relationship("AmazonAiTask", back_populates="source_links")


class AmazonAiTaskDependency(db.Model):
    """Normalized task-to-upstream-task dependency relation."""

    __tablename__ = "amazon_ai_task_dependency"
    __table_args__ = (
        db.UniqueConstraint(
            "task_id",
            "source_task_id",
            "relation_type",
            name="uq_amazon_ai_task_dependency",
        ),
        db.Index(
            "ix_amazon_ai_task_dependency_source_task",
            "source_task_id",
            "task_id",
        ),
        db.Index(
            "ix_amazon_ai_task_dependency_task",
            "task_id",
            "source_task_id",
        ),
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    task_id = db.Column(
        db.Integer,
        db.ForeignKey("amazon_ai_workspace_task.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_task_id = db.Column(
        db.Integer,
        db.ForeignKey("amazon_ai_workspace_task.id", ondelete="CASCADE"),
        nullable=False,
    )
    relation_type = db.Column(
        db.String(30),
        nullable=False,
        default="SOURCE_TASK",
    )
    created_at = db.Column(db.DateTime, default=datetime.datetime.now)

    task = db.relationship(
        "AmazonAiTask",
        foreign_keys=[task_id],
        back_populates="dependency_links",
    )
    source_task = db.relationship(
        "AmazonAiTask",
        foreign_keys=[source_task_id],
        back_populates="upstream_links",
    )


class AmazonAiTaskAsset(db.Model):
    """Normalized Amazon task-to-asset relation."""

    __tablename__ = "amazon_ai_task_asset"
    __table_args__ = (
        db.UniqueConstraint(
            "task_id",
            "asset_id",
            "role",
            name="uq_amazon_ai_task_asset_role",
        ),
        db.Index(
            "ix_amazon_ai_task_asset_task_role_sort",
            "task_id",
            "role",
            "sort",
            "asset_id",
        ),
        db.Index(
            "ix_amazon_ai_task_asset_asset_task_role",
            "asset_id",
            "task_id",
            "role",
        ),
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    task_id = db.Column(
        db.Integer,
        db.ForeignKey("amazon_ai_workspace_task.id", ondelete="CASCADE"),
        nullable=False,
    )
    asset_id = db.Column(
        db.Integer,
        db.ForeignKey("studio_asset.id", ondelete="RESTRICT"),
        nullable=False,
    )
    role = db.Column(db.String(30), nullable=False, default="INPUT")
    sort = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=datetime.datetime.now)

    task = db.relationship("AmazonAiTask", back_populates="asset_links")
    asset = db.relationship("StudioAsset", lazy="joined")
