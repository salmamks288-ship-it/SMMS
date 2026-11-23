"""S8 Audit & Monitoring (FR-43, FR-44, NFR-20)."""
from flask import Blueprint, current_app, jsonify, request
from ..db import q, x, iso
from ..security import require_auth

bp = Blueprint("audit", __name__)

_last_purge = [None]

def purge_old(force=False):
    """FR-43: the audit log is kept for 12 months; older rows are removed (checked at most once an hour)."""
    from datetime import timedelta
    n = current_app.config["NOW"]()
    if not force and _last_purge[0] and n - _last_purge[0] < timedelta(hours=1): return
    _last_purge[0] = n
    x("DELETE FROM audit_log WHERE event_time < ?", (iso(n - timedelta(days=current_app.config["AUDIT_RETENTION_DAYS"])),))

def log_event(event_type, user_id, details=""):
    purge_old()
    x("INSERT INTO audit_log(event_type,user_id,event_time,details) VALUES (?,?,?,?)",
      (event_type, user_id, iso(current_app.config["NOW"]()), details))

@bp.get("/api/audit")
@require_auth("ITAdmin")
def search_audit():
    sql, args = "SELECT * FROM audit_log WHERE 1=1", []
    if request.args.get("event_type"): sql += " AND event_type=?"; args.append(request.args["event_type"])
    if request.args.get("user_id"): sql += " AND user_id=?"; args.append(request.args["user_id"])
    if request.args.get("text"): sql += " AND details LIKE ?"; args.append("%" + request.args["text"] + "%")
    sql += " ORDER BY log_id DESC LIMIT 200"
    return jsonify(q(sql, args))

@bp.get("/api/health")
@require_auth("ITAdmin")
def health():
    """FR-44: health of critical components; a failed connection is reported as an alert."""
    from .integration import gateway_status
    checks = {"database": "OK"}
    try: q("SELECT 1")
    except Exception: checks["database"] = "DOWN"
    checks.update(gateway_status())
    alerts = [f"{k} not available" for k, v in checks.items() if v != "OK"]
    return jsonify(components=checks, alerts=alerts)
