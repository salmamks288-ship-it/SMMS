"""S2 Collection & Exhibition Management (FR-08..FR-16, FR-25)."""
import secrets, io
from flask import Blueprint, current_app, g, jsonify, request, send_file
from ..db import q, x, tx, iso, local_now
from ..security import require_auth
from .audit import log_event
from .integration import read_tag

bp = Blueprint("collection", __name__)
now = lambda: current_app.config["NOW"]()
STATUSES = ("onDisplay", "inStorage", "onLoan", "underRestoration")
CONDITIONS = ("excellent", "good", "fair", "poor")
MANDATORY = ("title", "category_id", "description", "period", "origin", "condition", "location", "status")
EDITABLE = ("title", "category_id", "description", "period", "origin", "condition", "location", "status",
            "dimensions", "acquisition_details", "image_url", "inspection_date", "rfid_tag_id")
STAFF = ("Staff",)

@bp.get("/api/categories")
@require_auth()
def categories():
    return jsonify(q("SELECT * FROM category ORDER BY name"))

@bp.post("/api/categories")
@require_auth("Staff")
def add_category():
    n = (request.get_json(force=True).get("name") or "").strip()
    if not n: return jsonify(error="name required"), 400
    try: cid = x("INSERT INTO category(name) VALUES (?)", (n,))
    except Exception: return jsonify(error="category exists"), 409
    return jsonify(category_id=cid), 201

# ---------------- artifacts ----------------
@bp.post("/api/artifacts")
@require_auth("Staff")
def create_artifact():
    """FR-08: mandatory fields title, category, description, period, origin, condition, location, status."""
    d = request.get_json(force=True)
    missing = [f for f in MANDATORY if d.get(f) in (None, "")]
    if missing: return jsonify(error="missing fields", fields=missing), 400
    if d["condition"] not in CONDITIONS or d["status"] not in STATUSES: return jsonify(error="invalid condition or status"), 400
    if not q("SELECT 1 FROM category WHERE category_id=?", (d["category_id"],), one=True): return jsonify(error="unknown category"), 400
    qr = "ART-" + secrets.token_hex(4).upper()                    # FR-11 unique QR value
    aid = x("""INSERT INTO artifact(title,category_id,description,period,origin,condition,location,status,dimensions,acquisition_details,
               image_url,inspection_date,qr_code_value,rfid_tag_id,created_by,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (d["title"], d["category_id"], d["description"], d["period"], d["origin"], d["condition"], d["location"], d["status"],
             d.get("dimensions"), d.get("acquisition_details"), d.get("image_url"), d.get("inspection_date"), qr, d.get("rfid_tag_id"),
             g.user["id"], iso(now())))
    log_event("artifactChange", g.user["id"], f"artifact {aid} created")
    return jsonify(artifact_id=aid, qr_code_value=qr), 201

def _artifact(aid):
    return q("SELECT * FROM artifact WHERE artifact_id=?", (aid,), one=True)

@bp.get("/api/artifacts")
@require_auth("Staff", "Manager")
def search_artifacts():
    """FR-13: search/filter by ID, title, category, location, status, condition - filters can be combined."""
    sql, args = "SELECT artifact_id,title,category_id,location,status,condition,is_archived,qr_code_value FROM artifact WHERE 1=1", []
    a = request.args
    if a.get("id"): sql += " AND artifact_id=?"; args.append(a["id"])
    if a.get("title"): sql += " AND title LIKE ?"; args.append("%" + a["title"] + "%")
    for f in ("category_id", "location", "status", "condition"):
        if a.get(f): sql += f" AND {f}=?"; args.append(a[f])
    if a.get("include_archived") != "1": sql += " AND is_archived=0"
    return jsonify(q(sql + " ORDER BY artifact_id LIMIT 500", args))

@bp.get("/api/artifacts/<int:aid>")
@require_auth("Staff", "Manager")
def get_artifact(aid):
    a = _artifact(aid)
    return (jsonify(a) if a else (jsonify(error="not found"), 404))

@bp.get("/api/scan/<path:tag>")
@require_auth("Staff")
def scan(tag):
    """FR-12: identify an artifact from a QR value or RFID tag ID; archived artifacts open read-only (E2)."""
    t = read_tag(tag)
    a = q("SELECT * FROM artifact WHERE qr_code_value=? OR rfid_tag_id=?", (t, t), one=True)
    if not a: return jsonify(error="tag not registered", can_create=True), 404
    a["read_only"] = bool(a["is_archived"])
    return jsonify(a)

@bp.patch("/api/artifacts/<int:aid>")
@require_auth("Staff")
def update_artifact(aid):
    """FR-09/FR-14: edit with history log; E3: if another user saved meanwhile (version mismatch) latest values are returned."""
    d = request.get_json(force=True)
    a = _artifact(aid)
    if not a: return jsonify(error="not found"), 404
    if a["is_archived"]: return jsonify(error="artifact is archived (read-only)"), 409
    if d.get("version") and d["version"] != a["updated_at"]:
        return jsonify(error="record changed by another user", latest=a), 409
    if d.get("condition", a["condition"]) not in CONDITIONS or d.get("status", a["status"]) not in STATUSES:
        return jsonify(error="invalid condition or status"), 400
    changes = {f: d[f] for f in EDITABLE if f in d and d[f] != a[f]}
    with tx():
        for f, new in changes.items():
            x("INSERT INTO status_history(artifact_id,field_name,old_value,new_value,changed_by,changed_at) VALUES (?,?,?,?,?,?)",
              (aid, f, None if a[f] is None else str(a[f]), None if new is None else str(new), g.user["id"], iso(now())))
        if changes:
            sets = ", ".join(f"{f}=?" for f in changes)
            x(f"UPDATE artifact SET {sets}, updated_by=?, updated_at=? WHERE artifact_id=?", (*changes.values(), g.user["id"], iso(now()), aid))
    if changes:
        log_event("artifactChange", g.user["id"], f"artifact {aid}: " + ", ".join(f"{f} {a[f]}->{v}" for f, v in changes.items()))
    return jsonify(message="saved", changed=list(changes), alert=(d.get("condition", a["condition"]) == "poor"))

@bp.get("/api/artifacts/<int:aid>/history")
@require_auth("Staff", "Manager")
def history(aid):
    return jsonify(q("SELECT * FROM status_history WHERE artifact_id=? ORDER BY history_id", (aid,)))

@bp.post("/api/artifacts/<int:aid>/archive")
@require_auth("Staff")
def archive(aid):
    """FR-10: archived with a recorded reason, hidden from visitors, never physically deleted."""
    reason = (request.get_json(force=True).get("reason") or "").strip()
    if not reason: return jsonify(error="reason required"), 400
    if not _artifact(aid): return jsonify(error="not found"), 404
    x("UPDATE artifact SET is_archived=1, archive_reason=?, updated_by=?, updated_at=? WHERE artifact_id=?", (reason, g.user["id"], iso(now()), aid))
    log_event("artifactChange", g.user["id"], f"artifact {aid} archived: {reason}")
    return jsonify(message="archived")

@bp.post("/api/artifacts/<int:aid>/condition-report")
@require_auth("Staff")
def condition_report(aid):
    d = request.get_json(force=True)
    if d.get("rating") not in CONDITIONS: return jsonify(error="invalid rating"), 400
    x("INSERT INTO condition_report(artifact_id,rating,notes,reported_by,reported_at) VALUES (?,?,?,?,?)", (aid, d["rating"], d.get("notes"), g.user["id"], iso(now())))
    x("UPDATE artifact SET condition=?, updated_at=? WHERE artifact_id=?", (d["rating"], iso(now()), aid))
    return jsonify(message="report stored", alert=d["rating"] == "poor"), 201

@bp.get("/api/alerts")
@require_auth("Staff", "Manager")
def alerts():
    """FR-15: alert when condition is 'poor' or the inspection date has passed."""
    today = iso(local_now())[:10]
    return jsonify(q("""SELECT artifact_id,title,condition,inspection_date,
                        CASE WHEN condition='poor' THEN 'condition poor' ELSE 'inspection overdue' END AS reason
                        FROM artifact WHERE is_archived=0 AND (condition='poor' OR (inspection_date IS NOT NULL AND inspection_date < ?))""", (today,)))

@bp.get("/api/artifacts/<int:aid>/qr.png")
@require_auth("Staff")
def artifact_qr(aid):
    """FR-11: downloadable/printable QR code image."""
    a = _artifact(aid)
    if not a: return jsonify(error="not found"), 404
    try: import qrcode
    except ImportError: return jsonify(error="install the 'qrcode' package (see requirements.txt)"), 501
    buf = io.BytesIO(); qrcode.make(a["qr_code_value"]).save(buf, format="PNG"); buf.seek(0)
    return send_file(buf, mimetype="image/png")

# ---------------- exhibitions, ticket types, slots (FR-16, FR-25) ----------------
@bp.get("/api/exhibitions")
def list_exhibitions():
    """FR-17 (public): exhibitions with opening dates; no login required."""
    return jsonify(q("SELECT * FROM exhibition WHERE end_date >= ? ORDER BY start_date", (iso(local_now())[:10],)))

@bp.post("/api/exhibitions")
@require_auth("Staff")
def create_exhibition():
    d = request.get_json(force=True)
    for f in ("title", "gallery", "start_date", "end_date"):
        if not d.get(f): return jsonify(error=f"{f} required"), 400
    if d["end_date"] < d["start_date"]: return jsonify(error="end date before start date"), 400
    return jsonify(exhibition_id=x("INSERT INTO exhibition(title,gallery,start_date,end_date,description) VALUES (?,?,?,?,?)",
                                   (d["title"], d["gallery"], d["start_date"], d["end_date"], d.get("description")))), 201

@bp.patch("/api/exhibitions/<int:eid>")
@require_auth("Staff")
def edit_exhibition(eid):
    d = request.get_json(force=True)
    for f in ("title", "gallery", "start_date", "end_date", "description"):
        if f in d: x(f"UPDATE exhibition SET {f}=? WHERE exhibition_id=?", (d[f], eid))
    return jsonify(message="updated")

@bp.post("/api/exhibitions/<int:eid>/items")
@require_auth("Staff")
def assign_artifact(eid):
    d = request.get_json(force=True)
    try: x("INSERT INTO exhibition_item(exhibition_id,artifact_id,display_start_date,display_end_date) VALUES (?,?,?,?)",
           (eid, d["artifact_id"], d["display_start_date"], d["display_end_date"]))
    except Exception as e: return jsonify(error="cannot assign artifact", detail=str(e)), 400
    return jsonify(message="assigned"), 201

@bp.get("/api/exhibitions/<int:eid>/items")
def exhibition_items(eid):
    return jsonify(q("""SELECT a.artifact_id,a.title,i.display_start_date,i.display_end_date FROM exhibition_item i
                        JOIN artifact a ON a.artifact_id=i.artifact_id WHERE i.exhibition_id=? AND a.is_archived=0""", (eid,)))

@bp.post("/api/exhibitions/<int:eid>/ticket-types")
@require_auth("Staff")
def add_ticket_type(eid):
    d = request.get_json(force=True)
    try:
        if float(d["price"]) < 0: raise ValueError
        tid = x("INSERT INTO ticket_type(exhibition_id,name,price,per_booking_limit) VALUES (?,?,?,?)", (eid, d["name"], d["price"], d.get("per_booking_limit", 10)))
    except Exception: return jsonify(error="invalid ticket type (name unique per exhibition, price >= 0)"), 400
    return jsonify(ticket_type_id=tid), 201

@bp.get("/api/exhibitions/<int:eid>/ticket-types")
def ticket_types(eid):
    return jsonify(q("SELECT * FROM ticket_type WHERE exhibition_id=?", (eid,)))

@bp.post("/api/exhibitions/<int:eid>/slots")
@require_auth("Staff")
def add_slot(eid):
    d = request.get_json(force=True)
    try:
        if int(d["capacity"]) <= 0: raise ValueError
        sid = x("INSERT INTO time_slot(exhibition_id,slot_date,start_time,end_time,capacity) VALUES (?,?,?,?,?)", (eid, d["slot_date"], d["start_time"], d["end_time"], d["capacity"]))
    except Exception: return jsonify(error="invalid or duplicate slot (capacity must be > 0)"), 400
    return jsonify(slot_id=sid), 201
