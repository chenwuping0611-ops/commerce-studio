from flask import Flask

from .routes import amazon_ai_bp


def register_amazon_ai_views(app: Flask):
    app.register_blueprint(amazon_ai_bp)
