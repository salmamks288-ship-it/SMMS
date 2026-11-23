"""S5 AR Content Service (FR-34..FR-36). The AR client (Unity) calls these endpoints; the web client shows the fallback viewer."""
from flask import Blueprint, current_app, g, jsonify, request
from ..db import q, x, iso
from ..security import require_auth

bp = Blueprint("ar", __name__)
now = lambda: current_app.config["NOW"]()

@bp.post("/api/ar-content")
@require_auth("Staff")
def add_content():
    d = request.get_json(force=True)
    try: mb = float(d["file_size_mb"]); aid = int(d["artifact_id"])
    except Exception: return jsonify(error="artifact_id and file_size_mb required"), 400
    if mb > current_app.config["MAX_AR_MB"]: return jsonify(error=f"AR content is limited to {current_app.config['MAX_AR_MB']} MB (NFR-05)"), 400
    if not d.get("model_url"): return jsonify(error="model_url required"), 400
    try: cid = x("INSERT INTO ar_content(artifact_id,model_url,file_size_mb,overlay_text,published,updated_at) VALUES (?,?,?,?,0,?)", (aid, d["model_url"], mb, d.get("overlay_text"), iso(now())))
    except Exception: return jsonify(error="artifact unknown or already has AR content"), 409
    return jsonify(content_id=cid), 201

@bp.get("/api/ar-content")
@require_auth("Staff")
def list_content():
    return jsonify(q("""SELECT c.content_id,c.artifact_id,a.title,c.model_url,c.file_size_mb,c.overlay_text,c.published
                        FROM ar_content c JOIN artifact a ON a.artifact_id=c.artifact_id ORDER BY c.content_id"""))

@bp.patch("/api/ar-content/<int:cid>")
@require_auth("Staff")
def edit_content(cid):
    d = request.get_json(force=True)
    for f in ("model_url", "overlay_text", "published"):
        if f in d: x(f"UPDATE ar_content SET {f}=?, updated_at=? WHERE content_id=?", (d[f], iso(now()), cid))
    return jsonify(message="updated")

@bp.get("/api/ar/<int:aid>")
@require_auth("Visitor")
def launch(aid):
    """FR-34/FR-35: AR data for an exhibit; fallback (images, text, 3D viewer) when AR is unsupported or permission refused."""
    a = q("SELECT title,description,image_url FROM artifact WHERE artifact_id=? AND is_archived=0", (aid,), one=True)
    if not a: return jsonify(error="not found"), 404
    c = q("SELECT content_id,model_url,overlay_text FROM ar_content WHERE artifact_id=? AND published=1", (aid,), one=True)
    if c and request.args.get("supports_ar", "1") == "1" and request.args.get("camera_permission", "1") == "1":
        return jsonify(ar=True, **c)
    return jsonify(ar=False, fallback={"title": a["title"], "text": a["description"], "image_url": a["image_url"], "viewer_3d": c["model_url"] if c else None})

@bp.post("/api/ar/sessions")
@require_auth("Visitor")
def record_session():
    """Anonymised AR session record - the visitor ID is deliberately not stored (FR-41)."""
    d = request.get_json(force=True)
    if not q("SELECT 1 FROM ar_content WHERE content_id=?", (d.get("content_id"),), one=True): return jsonify(error="unknown content"), 404
    x("INSERT INTO ar_session(content_id,started_at,duration_seconds,device_type,used_fallback) VALUES (?,?,?,?,?)",
      (d["content_id"], iso(now()), d.get("duration_seconds"), d.get("device_type"), 1 if d.get("used_fallback") else 0))
    return jsonify(message="session recorded"), 201
