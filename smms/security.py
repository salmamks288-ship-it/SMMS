"""Authentication helpers: password hashing, TOTP, JWT, AES-256-GCM, role decorator (FR-02..FR-04, NFR-15..NFR-18)."""
import base64, calendar, hashlib, hmac, os, re, struct, time
from datetime import timedelta
from functools import wraps
import jwt
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from flask import current_app, g, jsonify, request

def hash_password(pw):
    salt = os.urandom(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return "scrypt$%s$%s" % (base64.b64encode(salt).decode(), base64.b64encode(h).decode())

def check_password(pw, stored):
    try:
        _, s, h = stored.split("$")
        calc = hashlib.scrypt(pw.encode(), salt=base64.b64decode(s), n=2**14, r=8, p=1, dklen=32)
        return hmac.compare_digest(calc, base64.b64decode(h))
    except Exception:
        return False

def password_ok(pw):
    """At least 8 characters with letters and numbers (NFR-15)."""
    return bool(pw) and len(pw) >= 8 and re.search(r"[A-Za-z]", pw) and re.search(r"\d", pw)

# --- TOTP (RFC 6238, 30 s steps, 6 digits) for the second factor (FR-03) ---
def new_totp_secret():
    return base64.b32encode(os.urandom(10)).decode()

def totp(secret, at=None, step=30):
    counter = int((at if at is not None else time.time()) // step)
    key = base64.b32decode(secret)
    d = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    o = d[-1] & 0x0F
    return "%06d" % ((struct.unpack(">I", d[o:o+4])[0] & 0x7FFFFFFF) % 10**6)

def totp_ok(secret, code, at=None):
    t = at if at is not None else time.time()
    return any(hmac.compare_digest(totp(secret, t + d * 30), str(code)) for d in (-1, 0, 1))

# --- AES-256-GCM for personal data at rest (NFR-18) ---
def _key():
    return hashlib.sha256(current_app.config["SECRET_KEY"].encode()).digest()

def encrypt(text):
    if text is None: return None
    nonce = os.urandom(12)
    return base64.b64encode(nonce + AESGCM(_key()).encrypt(nonce, text.encode(), None)).decode()

def decrypt(blob):
    if blob is None: return None
    raw = base64.b64decode(blob)
    return AESGCM(_key()).decrypt(raw[:12], raw[12:], None).decode()

# --- JWT sessions (NFR-16) ---
def make_token(account_id, role):
    mins = current_app.config["SESSION_MINUTES"][role]
    now = current_app.config["NOW"]()
    return jwt.encode({"sub": str(account_id), "role": role, "iat": now, "exp": now + timedelta(minutes=mins)},
                      current_app.config["SECRET_KEY"], algorithm="HS256")

def decode_token(tok):
    return jwt.decode(tok, current_app.config["SECRET_KEY"], algorithms=["HS256"], options={"verify_exp": False, "verify_iat": False})

def require_auth(*roles):
    """Role-based access control on every protected endpoint (FR-04, NFR-17). Empty roles = any logged-in user."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            from .services.audit import log_event
            hdr = request.headers.get("Authorization", "")
            if not hdr.startswith("Bearer "):
                return jsonify(error="authentication required"), 401
            try:
                p = decode_token(hdr[7:])
            except Exception:
                return jsonify(error="invalid token"), 401
            # NOW() is naive UTC: convert with timegm (naive .timestamp() would assume the server's local zone and
            # stretch or shrink every session by the UTC offset - NFR-16).
            now = calendar.timegm(current_app.config["NOW"]().utctimetuple())
            if now > p["exp"]:
                return jsonify(error="session expired"), 401
            from .db import q
            acc = q("SELECT role, is_active FROM account WHERE account_id=?", (int(p["sub"]),), one=True)
            if not acc or not acc["is_active"]:
                return jsonify(error="account deactivated"), 401          # FR-42: deactivation takes effect at once
            g.user = {"id": int(p["sub"]), "role": acc["role"]}           # FR-04/NFR-17: role comes from the database, not the old token
            if roles and g.user["role"] not in roles:
                log_event("accessDenied", g.user["id"], f"{request.method} {request.path}")
                return jsonify(error="forbidden"), 403
            return fn(*a, **kw)
        return wrapper
    return deco
