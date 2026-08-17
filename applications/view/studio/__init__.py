from flask import Flask

from .routes import studio_bp


def register_studio_views(app: Flask):
    app.register_blueprint(studio_bp)
