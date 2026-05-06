from flask import Flask

from .assets import asset_css_urls, asset_url
from .config import Config
from .errors import register_error_handlers
from .extensions import db, migrate


def create_app(config_class=Config):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_class)

    db.init_app(app)
    migrate.init_app(app, db)
    register_error_handlers(app)

    from .main.routes import main_bp
    from .api.routes import api_bp
    from .prompts.routes import prompts_bp
    from .rag.routes import rag_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(rag_bp)
    app.register_blueprint(prompts_bp)

    app.jinja_env.globals["asset_url"] = asset_url
    app.jinja_env.globals["asset_css_urls"] = asset_css_urls

    return app
