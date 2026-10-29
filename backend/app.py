import secrets
from flask import Flask, jsonify, request
from backend.config import FRONTEND_DIR, SECRET_KEY_PATH
from backend.database import initialize_database
from backend.security.middleware import init_security


def create_app():
    # backend.config loads deployment settings before the database path is resolved.
    app = Flask(
        __name__, static_folder=str(FRONTEND_DIR), static_url_path='/static'
    )
    if SECRET_KEY_PATH.exists():
        app.secret_key = SECRET_KEY_PATH.read_text().strip()
    else:
        app.secret_key = secrets.token_hex(32)
        SECRET_KEY_PATH.write_text(app.secret_key)
    initialize_database()
    init_security(app)

    from backend.login.routes import bp as login_bp
    from backend.manager_dashboard.routes import bp as manager_bp
    from backend.quotation_tool.routes import bp as quotation_bp
    from backend.quotation_tool.search_routes import bp as search_bp
    from backend.quotation_tool.price_history import bp as price_history_bp
    from backend.quotation_tool.images import bp as images_bp
    from backend.enquiry_sources.routes import bp as sources_bp
    from backend.client_leads.routes import bp as leads_bp
    from backend.client_access.routes import bp as access_bp
    from backend.enquiries.routes import bp as enquiries_bp
    from backend.enquiries.lines import bp as lines_bp
    from backend.orders.routes import bp as orders_bp
    from backend.settings import bp as settings_bp
    from backend.audit.routes import bp as audit_bp
    for blueprint in (
            login_bp, manager_bp, quotation_bp, search_bp, price_history_bp, images_bp, sources_bp,
            leads_bp, access_bp, enquiries_bp, lines_bp, orders_bp, settings_bp, audit_bp):
        app.register_blueprint(blueprint)

    @app.before_request
    def restrict_quotation_user_static_pages():
        """Keep quotation-only accounts from opening other module shells directly."""
        path = request.path
        if not path.startswith('/static/'):
            return None
        from backend.common.auth import get_current_user
        user = get_current_user()
        if (user and user['role'] == 'user'
                and not path.startswith(('/static/common/',
                                         '/static/quotation_tool/'))):
            return jsonify(error='This account can access only the Quotation Tool.'), 403
        return None

    return app
