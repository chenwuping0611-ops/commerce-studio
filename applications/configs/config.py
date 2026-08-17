import logging
import os
from urllib.parse import quote_plus


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
    STUDIO_USE_SQLITE = os.getenv("STUDIO_USE_SQLITE", "0") == "1"
    STUDIO_SQLITE_PATH = os.getenv(
        "STUDIO_SQLITE_PATH", "commerce_studio.local.sqlite3"
    )
    if STUDIO_USE_SQLITE:
        SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.path.abspath(STUDIO_SQLITE_PATH)
        SQLALCHEMY_ENGINE_OPTIONS = {}
    else:
        SQLALCHEMY_DATABASE_URI = (
            f"mysql+pymysql://{quote_plus(MYSQL_USERNAME)}:{quote_plus(MYSQL_PASSWORD)}"
            f"@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}"
        )
        SQLALCHEMY_ENGINE_OPTIONS = {
            "pool_pre_ping": True,
            "pool_recycle": 1800,
            "pool_size": int(os.getenv("MYSQL_POOL_SIZE") or 5),
            "max_overflow": int(os.getenv("MYSQL_MAX_OVERFLOW") or 2),
        }

    STUDIO_DEFAULT_PROVIDER_URL = os.getenv(
        "STUDIO_DEFAULT_PROVIDER_URL", "https://toapis.com"
    )
    STUDIO_REQUEST_TIMEOUT = int(os.getenv("STUDIO_REQUEST_TIMEOUT") or 120)
    STUDIO_POLL_INTERVAL = int(os.getenv("STUDIO_POLL_INTERVAL") or 10)
    STUDIO_MAX_IMAGE_REFERENCES = int(os.getenv("STUDIO_MAX_IMAGE_REFERENCES") or 10)
    STUDIO_MAX_VIDEO_REFERENCES = int(os.getenv("STUDIO_MAX_VIDEO_REFERENCES") or 10)

    LOG_LEVEL = logging.WARN
    MAIL_SERVER = os.getenv("MAIL_SERVER") or "smtp.qq.com"
    MAIL_USE_TLS = False
    MAIL_USE_SSL = True
    MAIL_PORT = 465
    MAIL_USERNAME = os.getenv("MAIL_USERNAME") or "123@qq.com"
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD") or "XXXXX"
    MAIL_DEFAULT_SENDER = ("commerce studio", MAIL_USERNAME)


class TestingConfig(BaseConfig):
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {}


class DevelopmentConfig(BaseConfig):
    SQLALCHEMY_TRACK_MODIFICATIONS = True
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
