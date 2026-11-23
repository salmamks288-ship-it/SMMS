"""S1 Identity & Access (FR-01..FR-07, FR-42)."""
import secrets, hashlib
from datetime import timedelta
from flask import Blueprint, current_app, g, jsonify, request
from ..db import q, x, tx, iso
from ..security import (hash_password, check_password, password_ok, new_totp_secret, totp_ok, make_token,
                        require_auth, encrypt, decrypt)
from .audit import log_event
from .integration import notify

bp = Blueprint("iam", __name__)
now = lambda: current_app.config["NOW"]()
ROLES = ("Visitor", "Staff", "Manager", "ITAdmin")

def _token(account_id, purpose, minutes):
    raw = secrets.token_urlsafe(24)
    x("INSERT INTO verification_token(token_hash,account_id,purpose,expires_at) VALUES (?,?,?,?)",
      (hashlib.sha256(raw.encode()).hexdigest(), account_id, purpose, iso(now() + timedelta(minutes=minutes))))
    return raw

def _use_token(raw, purpose):
    h = hashlib.sha256(raw.encode()).hexdigest()
    t = q("SELECT * FROM verification_token WHERE token_hash=? AND purpose=?", (h, purpose), one=True)
    if not t or t["used_at"] or t["expires_at"] < iso(now()):
        return None
    x("UPDATE verification_token SET used_at=? WHERE token_hash=?", (iso(now()), h))
    return t["account_id"]

@bp.post("/api/auth/register")
def register():
    """FR-01: visitor registration; account active only after the e-mail link is opened."""
    d = request.get_json(force=True)
    email, pw, name = (d.get("email") or "").strip().lower(), d.get("password"), (d.get("display_name") or "").strip()
    if "@" not in email or not name: return jsonify(error="name and valid e-mail required"), 400
    if not password_ok(pw): return jsonify(error="password needs at least 8 characters with letters and numbers"), 400
    if q("SELECT 1 FROM account WHERE email=?", (email,), one=True): return jsonify(error="e-mail already registered"), 409
    with tx():
        aid = x("INSERT INTO account(email,password_hash,role,is_active,email_verified) VALUES (?,?,?,?,?)",
                (email, hash_password(pw), "Visitor", 1, 0))
        x("INSERT INTO visitor(visitor_id,display_name,mobile_number,preferred_language,consent_personalisation) VALUES (?,?,?,?,?)",
          (aid, name, encrypt(d.get("mobile_number")), d.get("preferred_language", "EN"), 1 if d.get("consent_personalisation") else 0))
        x("INSERT INTO interest_profile(visitor_id,updated_at) VALUES (?,?)", (aid, iso(now())))
        raw = _token(aid, "verify_email", 60 * 24)
    notify(aid, "confirmation", "Verify your SMMS account", f"Open /verify?token={raw}", channels=("email",))
    out = {"message": "verification link sent"}
    if current_app.config["DEV_MODE"]: out["verification_token"] = raw
    return jsonify(out), 201

@bp.post("/api/auth/verify")
def verify():
    aid = _use_token((request.get_json(force=True) or {}).get("token", ""), "verify_email")
    if not aid: return jsonify(error="invalid or expired link"), 400
    x("UPDATE account SET email_verified=1 WHERE account_id=?", (aid,))
    return jsonify(message="account activated")

@bp.post("/api/auth/login")
def login():
    """FR-02/FR-03/NFR-16: password + one-time code for staff, manager and admin; lock after 5 failures for 15 min."""
    d = request.get_json(force=True)
    email = (d.get("email") or "").strip().lower()
    a = q("SELECT * FROM account WHERE email=?", (email,), one=True)
    if not a:
        log_event("failedLogin", None, f"unknown e-mail {email}")
        return jsonify(error="invalid credentials"), 401
    if a["lock_until"] and a["lock_until"] > iso(now()):
        return jsonify(error="account locked, try again later"), 423
    ok = check_password(d.get("password") or "", a["password_hash"])
    if not ok:
        n = a["failed_login_count"] + 1
        lock = iso(now() + timedelta(minutes=current_app.config["LOCK_MINUTES"])) if n >= current_app.config["LOCK_AFTER_FAILURES"] else None
        x("UPDATE account SET failed_login_count=?, lock_until=? WHERE account_id=?", (0 if lock else n, lock, a["account_id"]))
        log_event("failedLogin", a["account_id"], "wrong password" + (" - account locked" if lock else ""))
        return jsonify(error="invalid credentials"), 401
    if not a["is_active"]: return jsonify(error="account deactivated"), 403
    if a["role"] == "Visitor" and not a["email_verified"]: return jsonify(error="e-mail not verified"), 403
    if a["mfa_enabled"]:
        if not d.get("otp"): return jsonify(mfa_required=True), 200
        if not totp_ok(a["mfa_secret"], d["otp"]):
            log_event("failedLogin", a["account_id"], "wrong one-time code")
            return jsonify(error="invalid one-time code"), 401
    x("UPDATE account SET failed_login_count=0, lock_until=NULL WHERE account_id=?", (a["account_id"],))
    log_event("login", a["account_id"], "login ok")
    return jsonify(token=make_token(a["account_id"], a["role"]), role=a["role"])

@bp.post("/api/auth/logout")
@require_auth()
def logout():
    log_event("login", g.user["id"], "logout")
    return jsonify(message="logged out")   # token is discarded by the client; it also expires by itself

@bp.post("/api/auth/password-reset")
def reset_request():
    """FR-05: single-use link, valid 30 minutes. The answer is the same whether or not the e-mail exists."""
    email = ((request.get_json(force=True) or {}).get("email") or "").lower()
    a = q("SELECT account_id FROM account WHERE email=?", (email,), one=True)
    out = {"message": "if the e-mail exists, a link was sent"}
    if a:
        raw = _token(a["account_id"], "reset_password", current_app.config["RESET_LINK_MINUTES"])
        notify(a["account_id"], "passwordReset", "Reset your password", f"/reset?token={raw}", channels=("email",))
        if current_app.config["DEV_MODE"]: out["reset_token"] = raw
    return jsonify(out)

@bp.post("/api/auth/password-reset/confirm")
def reset_confirm():
    d = request.get_json(force=True)
    if not password_ok(d.get("password")): return jsonify(error="weak password"), 400
    aid = _use_token(d.get("token", ""), "reset_password")
    if not aid: return jsonify(error="invalid or expired link"), 400
    x("UPDATE account SET password_hash=?, failed_login_count=0, lock_until=NULL WHERE account_id=?", (hash_password(d["password"]), aid))
    return jsonify(message="password changed")

@bp.get("/api/me")
@require_auth()
def me():
    a = q("SELECT account_id,email,role FROM account WHERE account_id=?", (g.user["id"],), one=True)
    if a["role"] == "Visitor":
        v = q("SELECT * FROM visitor WHERE visitor_id=?", (a["account_id"],), one=True)
        v["mobile_number"] = decrypt(v["mobile_number"])
        a["profile"] = v
        a["interests"] = [r["name"] for r in q("SELECT c.name FROM profile_category pc JOIN interest_profile ip ON ip.profile_id=pc.profile_id JOIN category c ON c.category_id=pc.category_id WHERE ip.visitor_id=?", (a["account_id"],))]
    return jsonify(a)

@bp.patch("/api/me")
@require_auth("Visitor")
def update_profile():
    """FR-06 profile/preferences and FR-07 consent."""
    d = request.get_json(force=True); vid = g.user["id"]
    if "preferred_language" in d and d["preferred_language"] not in ("EN", "AR"): return jsonify(error="language must be EN or AR"), 400
    for f in ("display_name", "preferred_language", "text_size", "high_contrast"):
        if f in d: x(f"UPDATE visitor SET {f}=? WHERE visitor_id=?", (d[f], vid))
    if "mobile_number" in d: x("UPDATE visitor SET mobile_number=? WHERE visitor_id=?", (encrypt(d["mobile_number"]), vid))
    if "consent_personalisation" in d:
        c = 1 if d["consent_personalisation"] else 0
        x("UPDATE visitor SET consent_personalisation=?, consent_withdrawn_at=? WHERE visitor_id=?", (c, None if c else iso(now()), vid))
    if "interests" in d:
        pid = q("SELECT profile_id FROM interest_profile WHERE visitor_id=?", (vid,), one=True)["profile_id"]
        with tx():
            x("DELETE FROM profile_category WHERE profile_id=?", (pid,))
            for name in d["interests"]:
                c = q("SELECT category_id FROM category WHERE name=?", (name,), one=True)
                if c: x("INSERT INTO profile_category(profile_id,category_id) VALUES (?,?)", (pid, c["category_id"]))
            x("UPDATE interest_profile SET updated_at=? WHERE profile_id=?", (iso(now()), pid))
    return jsonify(message="profile updated")

@bp.delete("/api/me")
@require_auth("Visitor")
def delete_me():
    """FR-07: deletion request - personal data is removed and the account anonymised (NFR-21)."""
    vid = g.user["id"]
    with tx():
        pid = q("SELECT profile_id FROM interest_profile WHERE visitor_id=?", (vid,), one=True)["profile_id"]
        x("DELETE FROM profile_category WHERE profile_id=?", (pid,))
        x("DELETE FROM feedback WHERE visitor_id=?", (vid,)); x("DELETE FROM recommendation WHERE visitor_id=?", (vid,))
        x("DELETE FROM chat_turn WHERE session_id IN (SELECT session_id FROM chat_session WHERE visitor_id=?)", (vid,))
        x("DELETE FROM chat_session WHERE visitor_id=?", (vid,)); x("DELETE FROM notification WHERE account_id=?", (vid,))
        x("UPDATE visitor SET display_name='Deleted visitor', mobile_number=NULL, consent_personalisation=0 WHERE visitor_id=?", (vid,))
        x("UPDATE account SET email=?, is_active=0 WHERE account_id=?", (f"deleted-{vid}@deleted.invalid", vid))
    return jsonify(message="account and personal data deleted")

# ---------------- administration (FR-42) ----------------
@bp.get("/api/admin/accounts")
@require_auth("ITAdmin")
def list_accounts():
    return jsonify(q("SELECT account_id,email,role,is_active,mfa_enabled FROM account ORDER BY account_id"))

@bp.post("/api/admin/accounts")
@require_auth("ITAdmin")
def create_staff():
    d = request.get_json(force=True)
    role = d.get("role")
    if role not in ("Staff", "Manager", "ITAdmin"): return jsonify(error="role must be Staff, Manager or ITAdmin"), 400
    if not password_ok(d.get("password")): return jsonify(error="weak password"), 400
    email = (d.get("email") or "").lower()
    if q("SELECT 1 FROM account WHERE email=?", (email,), one=True): return jsonify(error="e-mail already registered"), 409
    secret = new_totp_secret()
    with tx():
        aid = x("INSERT INTO account(email,password_hash,role,is_active,email_verified,mfa_enabled,mfa_secret) VALUES (?,?,?,?,?,?,?)",
                (email, hash_password(d["password"]), role, 1, 1, 1, secret))
        if role == "Staff": x("INSERT INTO staff(staff_id,full_name,department) VALUES (?,?,?)", (aid, d.get("full_name", email), d.get("department")))
        elif role == "Manager": x("INSERT INTO manager(manager_id,full_name) VALUES (?,?)", (aid, d.get("full_name", email)))
        else: x("INSERT INTO it_admin(admin_id) VALUES (?)", (aid,))
    log_event("roleChange", g.user["id"], f"created {role} account {aid}")
    return jsonify(account_id=aid, mfa_secret=secret), 201     # secret is shown once, to enrol the authenticator app

@bp.patch("/api/admin/accounts/<int:aid>")
@require_auth("ITAdmin")
def change_account(aid):
    d = request.get_json(force=True)
    a = q("SELECT * FROM account WHERE account_id=?", (aid,), one=True)
    if not a: return jsonify(error="not found"), 404
    if "is_active" in d:
        x("UPDATE account SET is_active=? WHERE account_id=?", (1 if d["is_active"] else 0, aid))
        log_event("roleChange", g.user["id"], f"account {aid} active={bool(d['is_active'])}")
    if "role" in d:
        if d["role"] not in ROLES or a["role"] == "Visitor" or d["role"] == "Visitor":
            return jsonify(error="only staff-type accounts can change between Staff, Manager, ITAdmin"), 400
        with tx():
            x("UPDATE account SET role=? WHERE account_id=?", (d["role"], aid))
            # Old role rows are kept: artifacts, history and validations still reference staff(staff_id) (FR-09/FR-14),
            # so deleting them fails with a foreign-key error. account.role alone decides what the user may do.
            nm = d.get("full_name", a["email"])
            if d["role"] == "Staff": x("INSERT OR IGNORE INTO staff(staff_id,full_name) VALUES (?,?)", (aid, nm))
            elif d["role"] == "Manager": x("INSERT OR IGNORE INTO manager(manager_id,full_name) VALUES (?,?)", (aid, nm))
            else: x("INSERT OR IGNORE INTO it_admin(admin_id) VALUES (?)", (aid,))
        log_event("roleChange", g.user["id"], f"account {aid} role {a['role']} -> {d['role']}")
    return jsonify(message="updated")
