"""Journal de sécurité : lecture réservée aux administrateurs."""
from flask import Blueprint, current_app, render_template, request

from .auth import admin_required
from .seclog import list_events

security_bp = Blueprint("security", __name__, url_prefix="/security")


@security_bp.route("")
@admin_required
def index():
    event = request.args.get("event", "").strip()[:64] or None
    return render_template("security_log.html", events=list_events(300, event), event_filter=event or "",
                           retention=current_app.config["SECURITY_LOG_RETENTION_DAYS"])
