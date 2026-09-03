"""Plain-data execution snapshots for long-running AI requests.

The web request may start with SQLAlchemy models, but provider calls and
GoFastDFS I/O must not depend on those ORM objects. These small dataclasses
make the boundary explicit and keep lazy-loading bugs out of the network
phase.
"""

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Tuple


@dataclass
class ProviderExecutionContext:
    """Provider settings copied before a database connection is released."""

    name: str = ""
    kind: str = ""
    base_url: str = ""
    api_key: str = ""
    generation_path: str = ""
    result_path: str = ""
    balance_path: str = ""
    token_balance_path: str = ""
    auth_header: str = ""
    auth_prefix: str = ""
    timeout: int = 120
    owner_type: str = ""
    dept_id: Optional[int] = None


@dataclass
class ModelExecutionContext:
    """Model protocol settings copied from the catalog/model row."""

    id: Optional[int] = None
    name: str = ""
    model_code: str = ""
    media_type: str = ""
    generation_path: str = ""
    result_path: str = ""
    provider_id: Optional[int] = None


@dataclass
class AssetExecutionContext:
    """The file identity needed by a model request or a later cleanup."""

    id: Optional[int] = None
    public_url: str = ""
    storage_path: str = ""
    original_filename: str = ""
    content_type: str = ""
    checksum: Optional[str] = None
    purpose: str = ""
    retention_policy: str = ""
    expires_at: str = ""


@dataclass
class SkillExecutionContext:
    """Skill text and its optional permanent GoFastDFS file URL."""

    id: Optional[int] = None
    name: str = ""
    prompt: str = ""
    file_url: str = ""


@dataclass
class ProductExecutionContext:
    """Product facts copied into a model request."""

    id: Optional[int] = None
    code: str = ""
    name: str = ""
    context: str = ""


@dataclass
class ExecutionContext:
    """Immutable-in-practice request data used after the DB read phase.

    The class remains mutable for compatibility with existing service code,
    but it intentionally contains only plain Python values and tuples. ORM
    instances must never be stored here.
    """

    task_id: Optional[int] = None
    task_code: str = ""
    user_id: Optional[int] = None
    dept_id: Optional[int] = None
    provider: Optional[ProviderExecutionContext] = None
    model: Optional[ModelExecutionContext] = None
    skill: Optional[SkillExecutionContext] = None
    product: Optional[ProductExecutionContext] = None
    input_assets: Tuple[AssetExecutionContext, ...] = ()
    reference_image_urls: Tuple[str, ...] = ()
    reference_video_urls: Tuple[str, ...] = ()
    source_result_urls: Tuple[str, ...] = ()
    system_prompt: str = ""
    user_prompt: str = ""
    final_prompt: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.input_assets = tuple(self.input_assets or ())
        self.reference_image_urls = tuple(
            str(value or "").strip()
            for value in (self.reference_image_urls or ())
            if str(value or "").strip()
        )
        self.reference_video_urls = tuple(
            str(value or "").strip()
            for value in (self.reference_video_urls or ())
            if str(value or "").strip()
        )
        self.source_result_urls = tuple(
            str(value or "").strip()
            for value in (self.source_result_urls or ())
            if str(value or "").strip()
        )
