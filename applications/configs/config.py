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
    STUDIO_ASSET_TTL_DAYS = int(os.getenv("STUDIO_ASSET_TTL_DAYS") or 7)
    STUDIO_ASSET_CLEANUP_INTERVAL = int(
        os.getenv("STUDIO_ASSET_CLEANUP_INTERVAL") or 3600
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
    LOG_LEVEL = logging.ERROR


config = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}
