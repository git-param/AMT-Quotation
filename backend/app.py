import secrets
from flask import Flask
from backend.config import FRONTEND_DIR, SECRET_KEY_PATH
from backend.database import initialize_database


def create_app():
    app = Flask(
        __name__, static_folder=str(FRONTEND_DIR), static_url_path='/static'
    )
    if SECRET_KEY_PATH.exists():
        app.secret_key = SECRET_KEY_PATH.read_text().strip()
    else:
        app.secret_key = secrets.token_hex(32)
        SECRET_KEY_PATH.write_text(app.secret_key)
    initialize_database()

    from backend.login.routes import bp as login_bp
    from backend.manager_dashboard.routes import bp as manager_bp
    from backend.quotation_tool.routes import bp as quotation_bp
    from backend.quotation_tool.search_routes import bp as search_bp
    from backend.enquiry_sources.routes import bp as sources_bp
    for blueprint in (
            login_bp, manager_bp, quotation_bp, search_bp, sources_bp):
        app.register_blueprint(blueprint)
    return app
