import os

from flask import Flask

from applications.common.script import init_script
from applications.extensions import init_plugs
from applications.extensions.init_dotenv import init_dotenv
from applications.view import init_view


def create_app(config_name=None):
    app = Flask(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

    # Load local environment values before constructing SQLAlchemy.
    init_dotenv()
    from applications.configs import config

    config_name = config_name or os.getenv("FLASK_CONFIG", "development")
    app.config.from_object(config[config_name])

    init_plugs(app)
    init_view(app)
    init_script(app)

    if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        logo()

    return app


def logo():
    print(
        r"""
 _____                              _           _         ______ _           _
|  __ \                    /\      | |         (_)       |  ____| |         | |
| |__) |__  __ _ _ __     /  \   __| |_ __ ___  _ _ __   | |__  | | __ _ ___| | __
|  ___/ _ \/ _` | '__|   / /\ \ / _` | '_ ` _ \| | '_ \  |  __| | |/ _` / __| |/ /
| |  |  __/ (_| | |     / ____ \ (_| | | | | | | | | | | |    | | (_| \__ \   <
|_|   \___|\__,_|_|    /_/    \_\__,_|_| |_| |_|_|_| |_| |_|    |_|\__,_|___/_|_\
"""
    )
