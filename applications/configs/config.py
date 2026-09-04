import logging
import os
from urllib.parse import quote_plus


def _mysql_uri(database):
    """Build the only supported SQLAlchemy connection URI."""

    username = os.getenv("MYSQL_USERNAME") or "root"
    password = os.getenv("MYSQL_PASSWORD") or "123456"
    host = os.getenv("MYSQL_HOST") or "127.0.0.1"
    port = int(os.getenv("MYSQL_PORT") or 3306)
    return (
        f"mysql+pymysql://{quote_plus(username)}:{quote_plus(password)}"
        f"@{host}:{port}/{quote_plus(database)}"
    )


def _mysql_engine_options():
    """Keep MySQL connections healthy for a small long-running Flask service."""

    return {
        "pool_pre_ping": True,
        "pool_recycle": 1800,
        "pool_size": int(os.getenv("MYSQL_POOL_SIZE") or 5),
        "max_overflow": int(os.getenv("MYSQL_MAX_OVERFLOW") or 10),
        "pool_timeout": int(os.getenv("MYSQL_POOL_TIMEOUT") or 20),
        "pool_use_lifo": True,
        "connect_args": {
            "connect_timeout": int(os.getenv("MYSQL_CONNECT_TIMEOUT") or 10),
        },
    }


class BaseConfig:
    SYSTEM_NAME = os.getenv("SYSTEM_NAME", "Commerce Studio")
    SYSTEM_PANEL_LINKS = [
        {
            "icon": "layui-icon layui-icon-website",
            "title": "Pear Admin",
            "href": "https://github.com/pearadmin/pear-admin-flask",
        },
        {
            "icon": "layui-icon layui-icon-link",
            "title": "ToAPIs 文档",
            "href": "https://docs.toapis.com",
        },
    ]

    UPLOADED_PHOTOS_DEST = "static/upload"
    UPLOADED_FILES_ALLOW = ["gif", "jpg", "jpeg", "png", "webp"]
    JSON_AS_ASCII = False
    SECRET_KEY = os.getenv("SECRET_KEY", "commerce-studio-local-key")

    LOG_DIR = os.getenv("LOG_DIR") or "logs"
    APP_LOG_FILE = os.getenv("APP_LOG_FILE") or ""
    LOG_STRICT = os.getenv("LOG_STRICT", "false").lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    LOG_TO_CONSOLE = os.getenv("LOG_TO_CONSOLE", "true").lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    LOG_FORMAT = os.getenv("LOG_FORMAT") or (
        "%(asctime)s %(levelname)-8s [%(process)d] "
        "[%(name)s] %(message)s"
    )
    ALEMBIC_LOG_LEVEL = os.getenv("ALEMBIC_LOG_LEVEL") or "INFO"
    SQLALCHEMY_LOG_LEVEL = os.getenv("SQLALCHEMY_LOG_LEVEL") or "WARNING"

    REDIS_HOST = os.getenv("REDIS_HOST") or "127.0.0.1"
    REDIS_PORT = int(os.getenv("REDIS_PORT") or 6379)

    MYSQL_USERNAME = os.getenv("MYSQL_USERNAME") or "root"
    MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD") or "123456"
    MYSQL_HOST = os.getenv("MYSQL_HOST") or "127.0.0.1"
    MYSQL_PORT = int(os.getenv("MYSQL_PORT") or 3306)
    MYSQL_DATABASE = os.getenv("MYSQL_DATABASE") or "PearAdminFlask"
    MYSQL_TEST_DATABASE = os.getenv("MYSQL_TEST_DATABASE") or (
        f"{MYSQL_DATABASE}_test"
    )
    SQLALCHEMY_DATABASE_URI = _mysql_uri(MYSQL_DATABASE)
    SQLALCHEMY_ENGINE_OPTIONS = _mysql_engine_options()

    STUDIO_DEFAULT_PROVIDER_URL = os.getenv(
        "STUDIO_DEFAULT_PROVIDER_URL", "https://toapis.com"
    )
    STUDIO_REQUEST_TIMEOUT = int(os.getenv("STUDIO_REQUEST_TIMEOUT") or 120)
    STUDIO_POLL_INTERVAL = int(os.getenv("STUDIO_POLL_INTERVAL") or 10)
    STUDIO_MAX_IMAGE_REFERENCES = int(os.getenv("STUDIO_MAX_IMAGE_REFERENCES") or 14)
    STUDIO_MAX_VIDEO_REFERENCES = int(os.getenv("STUDIO_MAX_VIDEO_REFERENCES") or 10)
    # Temporary generation/Amazon assets use explicit expiry timestamps.
    # Keep the legacy setting as a compatibility fallback for old rows.
    STUDIO_TEMPORARY_RETENTION_DAYS = int(
        os.getenv("STUDIO_TEMPORARY_RETENTION_DAYS")
        or os.getenv("STUDIO_ASSET_TTL_DAYS")
        or 30
    )
    STUDIO_ASSET_TTL_DAYS = STUDIO_TEMPORARY_RETENTION_DAYS
    ADMIN_LOG_RETENTION_DAYS = int(
        os.getenv("ADMIN_LOG_RETENTION_DAYS") or 90
    )
    ADMIN_LOG_CLEANUP_INTERVAL = int(
        os.getenv("ADMIN_LOG_CLEANUP_INTERVAL") or 86400
    )
    STUDIO_CLEANUP_BATCH_SIZE = int(
        os.getenv("STUDIO_CLEANUP_BATCH_SIZE") or 100
    )
    STUDIO_POLL_BATCH_SIZE = int(
        os.getenv("STUDIO_POLL_BATCH_SIZE") or 20
    )
    STUDIO_POLL_MAX_WORKERS = int(
        os.getenv("STUDIO_POLL_MAX_WORKERS") or 5
    )
    STUDIO_HTTP_POOL_SIZE = int(
        os.getenv("STUDIO_HTTP_POOL_SIZE") or 10
    )
    STUDIO_HTTP_MAX_RETRIES = int(
        os.getenv("STUDIO_HTTP_MAX_RETRIES") or 2
    )
    # One provider operation gets its initial request plus this many business
    # retries. Submission retries reuse the same local task row.
    STUDIO_PROVIDER_RETRY_COUNT = int(
        os.getenv("STUDIO_PROVIDER_RETRY_COUNT") or 3
    )
    STUDIO_PROVIDER_RETRY_BACKOFF = float(
        os.getenv("STUDIO_PROVIDER_RETRY_BACKOFF") or 0.5
    )
    STUDIO_OUTPUT_UPLOAD_ATTEMPTS = max(
        1,
        int(os.getenv("STUDIO_OUTPUT_UPLOAD_ATTEMPTS") or 2),
    )
    STUDIO_ASSET_CLEANUP_INTERVAL = int(
        os.getenv("STUDIO_ASSET_CLEANUP_INTERVAL") or 3600
    )
    AMAZON_AI_MAX_TEXT_BYTES = int(
        os.getenv("AMAZON_AI_MAX_TEXT_BYTES") or 120000
    )
    AMAZON_AI_MAX_INPUT_FILES = int(
        os.getenv("AMAZON_AI_MAX_INPUT_FILES") or 10
    )
    # OpenAI Files API allows one file up to 512 MB. Keep Amazon AI input
    # uploads at or below that limit even when the storage server allows more.
    AMAZON_AI_OPENAI_FILE_MAX_BYTES = 512 * 1024 * 1024
    AMAZON_AI_MAX_UPLOAD_FILE_BYTES = min(
        max(
            int(
                os.getenv("AMAZON_AI_MAX_UPLOAD_FILE_BYTES")
                or AMAZON_AI_OPENAI_FILE_MAX_BYTES
            ),
            1,
        ),
        AMAZON_AI_OPENAI_FILE_MAX_BYTES,
    )
    AMAZON_AI_MAX_COMBINED_CONTEXT_BYTES = int(
        os.getenv("AMAZON_AI_MAX_COMBINED_CONTEXT_BYTES") or 280000
    )
    AMAZON_AI_MAX_OUTPUT_TOKENS = min(
        max(int(os.getenv("AMAZON_AI_MAX_OUTPUT_TOKENS") or 128000), 1),
        128000,
    )

    GOFASTDFS_INTERNAL_URL = os.getenv("GOFASTDFS_INTERNAL_URL") or ""
    GOFASTDFS_PUBLIC_URL = os.getenv("GOFASTDFS_PUBLIC_URL") or ""
    GOFASTDFS_GROUP = os.getenv("GOFASTDFS_GROUP") or "group1"
    GOFASTDFS_TIMEOUT = int(os.getenv("GOFASTDFS_TIMEOUT") or 120)
    GOFASTDFS_MAX_FILE_SIZE = int(
        os.getenv("GOFASTDFS_MAX_FILE_SIZE") or 536870912
    )
    GOFASTDFS_VERIFY_SSL = os.getenv("GOFASTDFS_VERIFY_SSL", "true")
    GOFASTDFS_UPLOAD_ENDPOINT = os.getenv(
        "GOFASTDFS_UPLOAD_ENDPOINT", "/{group}/upload"
    )
    GOFASTDFS_DELETE_ENDPOINT = os.getenv(
        "GOFASTDFS_DELETE_ENDPOINT", "/{group}/delete"
    )

    LOG_LEVEL = logging.WARN
    MAIL_SERVER = os.getenv("MAIL_SERVER") or "smtp.qq.com"
    MAIL_USE_TLS = False
    MAIL_USE_SSL = True
    MAIL_PORT = 465
    MAIL_USERNAME = os.getenv("MAIL_USERNAME") or "123@qq.com"
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD") or "XXXXX"
    MAIL_DEFAULT_SENDER = ("commerce studio", MAIL_USERNAME)


class TestingConfig(BaseConfig):
    MYSQL_DATABASE = BaseConfig.MYSQL_TEST_DATABASE
    SQLALCHEMY_DATABASE_URI = _mysql_uri(MYSQL_DATABASE)
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = _mysql_engine_options()


class DevelopmentConfig(BaseConfig):
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ECHO = False


class ProductionConfig(BaseConfig):
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ECHO = False
    SQLALCHEMY_POOL_RECYCLE = 1800
    # Production logging deliberately uses separate PEAR_AI_* variables.
    # This prevents a development .flaskenv value such as LOG_DIR=logs from
    # sending a production service back into the project directory.
    LOG_LEVEL = os.getenv("PEAR_AI_LOG_LEVEL") or logging.INFO
    LOG_DIR = os.getenv("PEAR_AI_LOG_DIR") or "/var/log/pear-ai"
    APP_LOG_FILE = os.getenv("PEAR_AI_APP_LOG_FILE") or (
        "/var/log/pear-ai/pear-ai.log"
    )
    LOG_STRICT = os.getenv("PEAR_AI_LOG_STRICT", "true").lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    LOG_TO_CONSOLE = os.getenv("PEAR_AI_LOG_TO_CONSOLE", "false").lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


config = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}
