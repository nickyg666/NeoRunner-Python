"""Flask application factory and modular structure for NeoRunner."""

from flask import Flask
from flask_cors import CORS
from .dashboard.blueprint import dashboard_bp
from .utils.config import get_config
from .utils.server_status import get_server_status


def create_app():
    """Create and configure Flask application."""
    app = Flask(__name__)
    
    # Enable CORS for all routes
    CORS(app)
    
    # Load configuration
    config = get_config()
    app.config.update(config)
    
    # Register blueprints
    app.register_blueprint(dashboard_bp)
    
    # Register error handlers
    @app.errorhandler(404)
    def not_found(error):
        return {"error": "Not found"}, 404
    
    @app.errorhandler(500)
    def internal_error(error):
        return {"error": "Internal server error"}, 500
    
    return app