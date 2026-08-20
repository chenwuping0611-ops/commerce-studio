import datetime

from applications.extensions import db


class StudioProvider(db.Model):
    """Configurable API provider, including official endpoints and relay services."""

    __tablename__ = "studio_provider"

    id = db.Column(db.Integer, primary_key=True)
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
        lazy="select",
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
    code = db.Column(db.String(80), unique=True, nullable=False)
    name = db.Column(db.String(160), nullable=False)
    brand = db.Column(db.String(160), nullable=True)
    description = db.Column(db.Text, nullable=True)
    product_profile = db.Column(db.Text, nullable=True)
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
        lazy="select",
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
    url = db.Column(db.String(1000), nullable=False)
    asset_type = db.Column(db.String(20), default="IMAGE")
    role = db.Column(db.String(40), default="reference")
    sort = db.Column(db.Integer, default=0)
    enabled = db.Column(db.Integer, default=1)
    storage_asset_id = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.now)

    product = db.relationship("StudioProduct", back_populates="assets")


class StudioSkill(db.Model):
    """Reusable prompt or instruction package imported from text files."""

    __tablename__ = "studio_skill"

    id = db.Column(db.Integer, primary_key=True)
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
    storage_asset_id = db.Column(db.Integer, nullable=True)
    enabled = db.Column(db.Integer, default=1)
    created_by = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.now)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.datetime.now,
        onupdate=datetime.datetime.now,
    )


class StudioGenerationTask(db.Model):
    """Internal task record linked to an upstream asynchronous generation task."""

    __tablename__ = "studio_generation_task"

    id = db.Column(db.Integer, primary_key=True)
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
    prompt = db.Column(db.Text, nullable=False)
    final_prompt = db.Column(db.Text, nullable=True)
    negative_prompt = db.Column(db.Text, nullable=True)
    request_body = db.Column(db.Text, nullable=True)
    provider_task_id = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(30), default="PENDING", nullable=False)
    progress = db.Column(db.Integer, default=0)
    result_payload = db.Column(db.Text, nullable=True)
    output_url = db.Column(db.String(1000), nullable=True)
    output_format = db.Column(db.String(40), nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.now)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.datetime.now,
        onupdate=datetime.datetime.now,
    )
    completed_at = db.Column(db.DateTime, nullable=True)

    product = db.relationship("StudioProduct", back_populates="tasks")
    model = db.relationship("StudioModel", back_populates="tasks")
    comments = db.relationship(
        "StudioGenerationComment",
        back_populates="task",
        cascade="all, delete-orphan",
        lazy="select",
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
    # JSON object containing model-proposed product field updates. These are
    # suggestions only; the product is changed only through an explicit apply
    # action from the operator.
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
