import datetime

from applications.extensions import db


class StudioSetting(db.Model):
    """Persistent system-level Studio settings."""

    __tablename__ = "studio_setting"

    id = db.Column(db.Integer, primary_key=True)
    setting_key = db.Column(db.String(120), nullable=False)
    dept_id = db.Column(db.Integer, nullable=True, comment="部门ID")
    setting_value = db.Column(db.String(255), nullable=True)
    description = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.now)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.datetime.now,
        onupdate=datetime.datetime.now,
    )
    __table_args__ = (
        db.UniqueConstraint(
            "setting_key",
            "dept_id",
            name="uq_studio_setting_key_dept",
        ),
    )


class StudioProvider(db.Model):
    """Configurable API provider, including official endpoints and relay services."""

    __tablename__ = "studio_provider"

    id = db.Column(db.Integer, primary_key=True)
    dept_id = db.Column(db.Integer, nullable=True, comment="所属部门")
    owner_type = db.Column(
        db.String(20),
        nullable=False,
        default="DEPARTMENT",
        comment="供应商归属：真实部门",
    )
    name = db.Column(db.String(120), nullable=False)
    kind = db.Column(db.String(30), default="relay", nullable=False)
    base_url = db.Column(db.String(500), nullable=False)
    api_key = db.Column(db.Text, nullable=True)
    generation_path = db.Column(db.String(255), default="/v1/images/generations")
    result_path = db.Column(db.String(255), default="/v1/images/generations/{task_id}")
    balance_path = db.Column(db.String(255), default="/v1/user/balance")
    token_balance_path = db.Column(db.String(255), default="/v1/balance")
    auth_header = db.Column(db.String(80), default="Authorization")
    auth_prefix = db.Column(db.String(80), default="Bearer")
    timeout = db.Column(db.Integer, default=120)
    enabled = db.Column(db.Integer, default=1)
    description = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.now)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.datetime.now,
        onupdate=datetime.datetime.now,
    )

    models = db.relationship(
        "StudioModel",
        back_populates="provider",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class StudioModel(db.Model):
    """A media model and its request field schema."""

    __tablename__ = "studio_model"

    id = db.Column(db.Integer, primary_key=True)
    provider_id = db.Column(
        db.Integer,
        db.ForeignKey("studio_provider.id", ondelete="CASCADE"),
        nullable=False,
    )
    name = db.Column(db.String(120), nullable=False)
    model_code = db.Column(db.String(160), nullable=False)
    media_type = db.Column(db.String(20), nullable=False, default="IMAGE")
    generation_path = db.Column(db.String(255), nullable=True)
    result_path = db.Column(db.String(255), nullable=True)
    parameter_schema = db.Column(db.Text, nullable=False, default="[]")
    capabilities = db.Column(db.Text, nullable=True)
    description = db.Column(db.String(500), nullable=True)
    enabled = db.Column(db.Integer, default=1)
    created_at = db.Column(db.DateTime, default=datetime.datetime.now)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.datetime.now,
        onupdate=datetime.datetime.now,
    )

    provider = db.relationship("StudioProvider", back_populates="models")
    tasks = db.relationship("StudioGenerationTask", back_populates="model")


class StudioProduct(db.Model):
    """Product memory used to enrich prompts and reference assets."""

    __tablename__ = "studio_product"

    id = db.Column(db.Integer, primary_key=True)
    dept_id = db.Column(db.Integer, nullable=True, comment="所属部门")
    # Listing extraction may not find an explicit product identity. Keep
    # these fields nullable so the operator can complete them later.
    code = db.Column(db.String(80), unique=True, nullable=True)
    name = db.Column(db.String(160), nullable=True)
    brand = db.Column(db.String(160), nullable=True)
    description = db.Column(db.Text, nullable=True)
    product_profile = db.Column(db.Text, nullable=True)
    core_selling_points = db.Column(
        db.Text,
        nullable=True,
        comment="Amazon AI 基础信息修正后确认的核心卖点",
    )
    product_memory = db.Column(db.Text, nullable=True)
    generation_rules = db.Column(db.Text, nullable=True)
    forbidden_rules = db.Column(db.Text, nullable=True)
    asset_urls = db.Column(db.Text, nullable=True)
    enabled = db.Column(db.Integer, default=1)
    created_by = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.now)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.datetime.now,
        onupdate=datetime.datetime.now,
    )

    assets = db.relationship(
        "StudioProductAsset",
        back_populates="product",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    tasks = db.relationship("StudioGenerationTask", back_populates="product")


class StudioProductAsset(db.Model):
    """A URL-based product reference asset."""

    __tablename__ = "studio_product_asset"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(
        db.Integer,
        db.ForeignKey("studio_product.id", ondelete="CASCADE"),
        nullable=False,
    )
    name = db.Column(db.String(160), nullable=False)
    # ``url`` is retained for old external/legacy rows. For GoFastDFS
    # records, ``storage_asset_id`` is the source of truth.
    url = db.Column(db.String(1000), nullable=True)
    external_url = db.Column(db.String(1000), nullable=True)
    asset_type = db.Column(db.String(20), default="IMAGE")
    role = db.Column(db.String(40), default="reference")
    sort = db.Column(db.Integer, default=0)
    enabled = db.Column(db.Integer, default=1)
    storage_asset_id = db.Column(
        db.Integer,
        db.ForeignKey("studio_asset.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = db.Column(db.DateTime, default=datetime.datetime.now)

    product = db.relationship("StudioProduct", back_populates="assets")
    storage_asset = db.relationship(
        "StudioAsset",
        foreign_keys=[storage_asset_id],
        back_populates="product_links",
        lazy="joined",
    )


class StudioSkill(db.Model):
    """Reusable prompt or instruction package imported from text files."""

    __tablename__ = "studio_skill"

    id = db.Column(db.Integer, primary_key=True)
    dept_id = db.Column(db.Integer, nullable=True, comment="所属部门")
    name = db.Column(db.String(160), nullable=False)
    code = db.Column(db.String(100), unique=True, nullable=False)
    media_type = db.Column(db.String(20), default="BOTH")
    version = db.Column(db.String(40), default="1.0.0")
    tags = db.Column(db.String(500), nullable=True)
    prompt_template = db.Column(db.Text, nullable=True)
    negative_prompt = db.Column(db.Text, nullable=True)
    file_name = db.Column(db.String(255), nullable=True)
    file_type = db.Column(db.String(30), nullable=True)
    content = db.Column(db.Text, nullable=True)
    storage_asset_id = db.Column(
        db.Integer,
        db.ForeignKey("studio_asset.id", ondelete="SET NULL"),
        nullable=True,
    )
    enabled = db.Column(db.Integer, default=1)
    created_by = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.now)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.datetime.now,
        onupdate=datetime.datetime.now,
    )

    storage_asset = db.relationship(
        "StudioAsset",
        foreign_keys=[storage_asset_id],
        back_populates="skill_links",
        lazy="joined",
    )


class StudioBatchPromptStyle(db.Model):
    """A reusable visual style option for the batch-prompt composer."""

    __tablename__ = "studio_batch_prompt_style"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False, unique=True)
    sort = db.Column(db.Integer, nullable=False, default=0)
    created_by = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.now)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.datetime.now,
        onupdate=datetime.datetime.now,
    )


class StudioBatchPrompt(db.Model):
    """A versioned batch-prompt document stored in GoFastDFS."""

    __tablename__ = "studio_batch_prompt"
    __table_args__ = (
        db.Index(
            "ix_studio_batch_prompt_scope_time",
            "dept_id",
            "user_id",
            "media_type",
            "created_at",
        ),
        db.Index(
            "ix_studio_batch_prompt_status_time",
            "status",
            "created_at",
        ),
        db.Index(
            "ix_studio_batch_prompt_product_run",
            "product_id",
            "run_number",
        ),
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    dept_id = db.Column(db.Integer, nullable=False, comment="所属部门")
    user_id = db.Column(db.Integer, nullable=False, comment="创建用户")
    name = db.Column(
        db.String(160),
        nullable=True,
        default="批量提示词",
        comment="批量提示词历史显示名称",
    )
    media_type = db.Column(db.String(20), nullable=False, default="IMAGE")
    product_id = db.Column(
        db.Integer,
        db.ForeignKey("studio_product.id", ondelete="SET NULL"),
        nullable=True,
    )
    skill_id = db.Column(
        db.Integer,
        db.ForeignKey("studio_skill.id", ondelete="SET NULL"),
        nullable=True,
    )
    storage_asset_id = db.Column(
        db.Integer,
        db.ForeignKey("studio_asset.id", ondelete="SET NULL"),
        nullable=True,
    )
    planner_model_id = db.Column(
        db.Integer,
        db.ForeignKey("studio_model.id", ondelete="SET NULL"),
        nullable=True,
    )
    planner_model_code = db.Column(db.String(160), nullable=True)
    product_name_snapshot = db.Column(db.String(160), nullable=True)
    skill_name_snapshot = db.Column(db.String(160), nullable=True)
    skill_prompt_snapshot = db.Column(db.Text, nullable=True)
    creative_prompt = db.Column(db.Text, nullable=True)
    creative_style = db.Column(
        db.String(160),
        nullable=True,
        comment="批量创作提示词的视觉风格约束",
    )
    image_resolution = db.Column(
        db.String(10),
        nullable=True,
        default="2k",
        comment="图片批量处理默认质量：1k、2k 或 4k",
    )
    image_aspect_ratio = db.Column(
        db.String(20),
        nullable=True,
        default="2.44:1",
        comment="图片批量处理默认画布比例",
    )
    file_name = db.Column(
        db.String(255),
        nullable=True,
        comment="批量提示词历史文件名",
    )
    run_number = db.Column(
        db.Integer,
        nullable=True,
        comment="同一产品批量提示词运行序号",
    )
    version_count = db.Column(db.Integer, nullable=False, default=1)
    status = db.Column(db.String(20), nullable=False, default="PENDING")
    error_message = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.now)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.datetime.now,
        onupdate=datetime.datetime.now,
    )
    completed_at = db.Column(db.DateTime, nullable=True)

    product = db.relationship("StudioProduct")
    skill = db.relationship("StudioSkill")
    storage_asset = db.relationship(
        "StudioAsset",
        foreign_keys=[storage_asset_id],
        back_populates="batch_prompt_links",
        lazy="joined",
    )
    planner_model = db.relationship("StudioModel")


class StudioGenerationTask(db.Model):
    """Internal task record linked to an upstream asynchronous generation task."""

    __tablename__ = "studio_generation_task"

    id = db.Column(db.Integer, primary_key=True)
    dept_id = db.Column(db.Integer, nullable=True, comment="所属部门")
    task_code = db.Column(db.String(7), unique=True, nullable=False)
    user_id = db.Column(db.Integer, nullable=True)
    media_type = db.Column(db.String(20), nullable=False)
    product_id = db.Column(
        db.Integer,
        db.ForeignKey("studio_product.id", ondelete="SET NULL"),
        nullable=True,
    )
    model_id = db.Column(
        db.Integer,
        db.ForeignKey("studio_model.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Keep a snapshot because a Skill can later be edited or disabled.
    skill_id = db.Column(
        db.Integer,
        db.ForeignKey("studio_skill.id", ondelete="SET NULL"),
        nullable=True,
    )
    skill_name = db.Column(db.String(160), nullable=True)
    skill_prompt = db.Column(db.Text, nullable=True)
    prompt = db.Column(db.Text, nullable=False)
    final_prompt = db.Column(db.Text, nullable=True)
    negative_prompt = db.Column(db.Text, nullable=True)
    request_body = db.Column(db.Text, nullable=True)
    workflow_metadata = db.Column(
        db.Text,
        nullable=True,
        comment="生成工作流元数据",
    )
    provider_task_id = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(30), default="PENDING", nullable=False)
    progress = db.Column(db.Integer, default=0)
    result_payload = db.Column(db.Text, nullable=True)
    output_url = db.Column(db.String(1000), nullable=True)
    output_format = db.Column(db.String(40), nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    retention_policy = db.Column(
        db.String(20),
        nullable=False,
        default="TEMPORARY",
    )
    expires_at = db.Column(db.DateTime, nullable=True)
    storage_cleanup_status = db.Column(
        db.String(20),
        nullable=False,
        default="ACTIVE",
    )
    storage_cleanup_error = db.Column(db.Text, nullable=True)
    storage_deleted_at = db.Column(db.DateTime, nullable=True)
    poll_claim_token = db.Column(db.String(64), nullable=True)
    poll_claimed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.now)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.datetime.now,
        onupdate=datetime.datetime.now,
    )
    completed_at = db.Column(db.DateTime, nullable=True)

    product = db.relationship("StudioProduct", back_populates="tasks")
    model = db.relationship("StudioModel", back_populates="tasks")
    skill = db.relationship("StudioSkill")
    comments = db.relationship(
        "StudioGenerationComment",
        back_populates="task",
        cascade="all, delete-orphan",
        lazy="select",
    )
    detail = db.relationship(
        "StudioGenerationTaskDetail",
        back_populates="task",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="select",
    )
    asset_links = db.relationship(
        "StudioGenerationTaskAsset",
        back_populates="task",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="(StudioGenerationTaskAsset.sort, StudioGenerationTaskAsset.id)",
    )


class StudioGenerationTaskDetail(db.Model):
    """Cold, potentially large request/response fields for one generation."""

    __tablename__ = "studio_generation_task_detail"

    task_id = db.Column(
        db.Integer,
        db.ForeignKey("studio_generation_task.id", ondelete="CASCADE"),
        primary_key=True,
    )
    skill_prompt = db.Column(db.Text, nullable=True)
    prompt = db.Column(db.Text, nullable=True)
    final_prompt = db.Column(db.Text, nullable=True)
    negative_prompt = db.Column(db.Text, nullable=True)
    request_body = db.Column(db.Text, nullable=True)
    result_payload = db.Column(db.Text, nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.now)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.datetime.now,
        onupdate=datetime.datetime.now,
    )

    task = db.relationship("StudioGenerationTask", back_populates="detail")


class StudioGenerationTaskAsset(db.Model):
    """Many-to-many relationship between a generation and stored assets."""

    __tablename__ = "studio_generation_task_asset"
    __table_args__ = (
        db.UniqueConstraint(
            "generation_task_id",
            "asset_id",
            "role",
            name="uq_studio_generation_task_asset_role",
        ),
        db.Index(
            "ix_studio_generation_task_asset_task_role_sort",
            "generation_task_id",
            "role",
            "sort",
            "asset_id",
        ),
        db.Index(
            "ix_studio_generation_task_asset_asset_task",
            "asset_id",
            "generation_task_id",
        ),
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    generation_task_id = db.Column(
        db.Integer,
        db.ForeignKey("studio_generation_task.id", ondelete="CASCADE"),
        nullable=False,
    )
    asset_id = db.Column(
        db.Integer,
        db.ForeignKey("studio_asset.id", ondelete="RESTRICT"),
        nullable=False,
    )
    role = db.Column(db.String(30), nullable=False, default="REFERENCE")
    sort = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=datetime.datetime.now)

    task = db.relationship("StudioGenerationTask", back_populates="asset_links")
    asset = db.relationship(
        "StudioAsset",
        back_populates="generation_links",
        lazy="joined",
    )


class StudioGenerationComment(db.Model):
    """Persistent AI analysis or operator comment attached to a generation task."""

    __tablename__ = "studio_generation_comment"

    id = db.Column(db.Integer, primary_key=True)
    generation_task_id = db.Column(
        db.Integer,
        db.ForeignKey("studio_generation_task.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = db.Column(db.Integer, nullable=True)
    dept_id = db.Column(db.Integer, nullable=True, comment="创建时部门快照")
    model_id = db.Column(
        db.Integer,
        db.ForeignKey("studio_model.id", ondelete="SET NULL"),
        nullable=True,
    )
    comment_type = db.Column(db.String(30), nullable=False, default="AI_ANALYSIS")
    status = db.Column(db.String(20), nullable=False, default="PENDING")
    content = db.Column(db.Text, nullable=True)
    request_body = db.Column(db.Text, nullable=True)
    response_payload = db.Column(db.Text, nullable=True)
    # JSON object containing model-proposed product field updates. New
    # feedback is applied automatically; the explicit apply endpoint remains
    # for older comments and operator retries.
    suggested_updates = db.Column(db.Text, nullable=True)
    applied_update_fields = db.Column(db.Text, nullable=True)
    applied_at = db.Column(db.DateTime, nullable=True)
    applied_by = db.Column(db.Integer, nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.now)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.datetime.now,
        onupdate=datetime.datetime.now,
    )

    task = db.relationship("StudioGenerationTask", back_populates="comments")
    model = db.relationship("StudioModel")


class StudioAsset(db.Model):
    """Stored file metadata and retention state."""

    __tablename__ = "studio_asset"

    id = db.Column(db.Integer, primary_key=True)
    dept_id = db.Column(db.Integer, nullable=True, comment="所属部门")
    asset_type = db.Column(db.String(20), nullable=False, default="FILE")
    purpose = db.Column(db.String(40), nullable=False, default="FILE")
    retention_policy = db.Column(db.String(20), nullable=False, default="PERMANENT")
    storage_path = db.Column(db.String(1000), nullable=False)
    public_url = db.Column(db.String(1200), nullable=False)
    original_filename = db.Column(db.String(255), nullable=True)
    content_type = db.Column(db.String(160), nullable=True)
    file_size = db.Column(db.BigInteger, nullable=True)
    checksum = db.Column(db.String(128), nullable=True)
    generation_task_id = db.Column(db.Integer, nullable=True)
    created_by = db.Column(db.Integer, nullable=True)
    status = db.Column(db.String(20), nullable=False, default="ACTIVE")
    error_message = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.now)
    expires_at = db.Column(db.DateTime, nullable=True)
    deleted_at = db.Column(db.DateTime, nullable=True)

    generation_links = db.relationship(
        "StudioGenerationTaskAsset",
        back_populates="asset",
        cascade="all, delete-orphan",
        lazy="select",
    )
    product_links = db.relationship(
        "StudioProductAsset",
        foreign_keys="StudioProductAsset.storage_asset_id",
        back_populates="storage_asset",
        lazy="select",
    )
    skill_links = db.relationship(
        "StudioSkill",
        foreign_keys="StudioSkill.storage_asset_id",
        back_populates="storage_asset",
        lazy="select",
    )
    batch_prompt_links = db.relationship(
        "StudioBatchPrompt",
        foreign_keys="StudioBatchPrompt.storage_asset_id",
        back_populates="storage_asset",
        lazy="select",
    )
