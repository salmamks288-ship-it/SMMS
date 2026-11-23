"""One-command acceptance check: replays the manual checklist on a throw-away database and prints PASS/FAIL per requirement.
Run from the project folder:  python tools/acceptance_check.py     (no server needs to be running; your smms.db is not touched)"""
import os, sys, tempfile, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from datetime import datetime, date, time, timedelta
from smms.app import create_app
from smms.seed import seed
from smms.security import totp
from smms.db import q

class Clock:
    def __init__(self): self.t = datetime.combine(date.today(), time(9, 0))
    def __call__(self): return self.t
clock = Clock()
fd, path = tempfile.mkstemp(suffix=".db"); os.close(fd); os.remove(path)
app = create_app({"DATABASE": path, "NOW": clock, "MUSEUM_UTC_OFFSET_HOURS": 0})
sec = seed(app); c = app.test_client(); PW = "Passw0rd1"
results = []
def check(req, what, cond, detail=""):
    results.append(bool(cond)); print(f"[{'PASS' if cond else 'FAIL'}] {req:<12} {what}" + ("" if cond else f"   <-- {detail}"))
def H(t): return {"Authorization": f"Bearer {t}"}
def call(m, url, tok=None, **j): return getattr(c, m)(url, json=j or None, headers=H(tok) if tok else {})
def login(email, otp=True):
    b = {"email": email, "password": PW}
    if sec.get(email) and otp: b["otp"] = totp(sec[email])
    r = c.post("/api/auth/login", json=b); return r.get_json().get("token")
def sql(s, a=()):
    with app.app_context(): return q(s, a)
try:
    V, S, M, A = (login(e) for e in ("visitor@smms.example", "staff@smms.example", "manager@smms.example", "admin@smms.example"))
    # --- accounts and security
    r = call("post", "/api/auth/register", email="new@example.com", password="Secret123", display_name="New", consent_personalisation=True)
    check("FR-01", "registration works, account needs e-mail verification", r.status_code == 201 and call("post", "/api/auth/login", email="new@example.com", password="Secret123").status_code == 403)
    call("post", "/api/auth/verify", token=r.get_json()["verification_token"])
    check("FR-01", "login works after the e-mail link is opened", call("post", "/api/auth/login", email="new@example.com", password="Secret123").status_code == 200)
    check("FR-03", "staff login asks for a one-time code; wrong code rejected", c.post("/api/auth/login", json={"email": "staff@smms.example", "password": PW}).get_json().get("mfa_required") is True
          and c.post("/api/auth/login", json={"email": "staff@smms.example", "password": PW, "otp": "000000"}).status_code == 401)
    for _ in range(5): c.post("/api/auth/login", json={"email": "new@example.com", "password": "wrong1234"})
    check("NFR-16", "account locks after 5 wrong passwords", c.post("/api/auth/login", json={"email": "new@example.com", "password": "Secret123"}).status_code == 423)
    st_old = S; clock.t += timedelta(minutes=16)
    check("NFR-16", "staff session expires after 15 min, visitor session still valid", call("get", "/api/alerts", st_old).status_code == 401 and call("get", "/api/me", V).status_code == 200)
    clock.t -= timedelta(minutes=16)
    check("NFR-17", "roles are enforced (visitor cannot use staff/manager/admin APIs)", all(call("get", u, V).status_code == 403 for u in ("/api/artifacts", "/api/analytics/summary", "/api/audit")))
    # --- ticketing
    ex = call("get", "/api/exhibitions").get_json()[0]["exhibition_id"]
    s_new = call("post", f"/api/exhibitions/{ex}/slots", S, slot_date=str(clock.t.date()), start_time="09:00", end_time="11:00", capacity=5).get_json()["slot_id"]
    r = call("post", "/api/bookings", V, slot_id=s_new, ticket_type_id=1, quantity=4); bid = r.get_json()["booking_id"]
    check("FR-19", "booking holds seats for 10 minutes and shows the total", r.status_code == 201 and r.get_json()["total_price"] == 120)
    r2 = call("post", "/api/bookings", V, slot_id=s_new, ticket_type_id=1, quantity=2)
    check("FR-19/NFR-12", "no overbooking: 2 more seats refused when only 1 is left", r2.status_code == 409 and r2.get_json()["remaining"] == 1)
    check("FR-20", "declined card keeps the hold and issues no ticket", call("post", f"/api/bookings/{bid}/pay", V, gateway_token="tok_declined").status_code == 402 and not sql("SELECT 1 FROM digital_ticket"))
    p = call("post", f"/api/bookings/{bid}/pay", V, gateway_token="tok_success").get_json()
    check("FR-20/21", "payment confirms the booking and issues one ticket per seat", p["status"] == "confirmed" and len(p["tickets"]) == 4)
    check("NFR-18", "no card data is stored", not {"card_number", "expiry", "cvv", "cvc"} & {r["name"] for r in sql("PRAGMA table_info(payment_record)")})
    r3 = call("post", "/api/bookings", V, slot_id=s_new, ticket_type_id=1, quantity=1); clock.t += timedelta(minutes=11)
    call("get", f"/api/exhibitions/{ex}/availability")
    check("FR-19", "an unpaid hold expires after 10 minutes and the seat returns", sql("SELECT status FROM booking WHERE booking_id=?", (r3.get_json()["booking_id"],))[0]["status"] == "cancelled")
    clock.t -= timedelta(minutes=11)
    far = sql("SELECT * FROM time_slot WHERE slot_date >= ? ORDER BY slot_date, start_time", (str(clock.t.date() + timedelta(days=3)),))
    b2 = call("post", "/api/bookings", V, slot_id=far[0]["slot_id"], ticket_type_id=1, quantity=1).get_json(); call("post", f"/api/bookings/{b2['booking_id']}/pay", V, gateway_token="tok_success")
    check("FR-22", "reschedule then cancel a booking more than 24 h ahead (refund pending)", call("patch", f"/api/bookings/{b2['booking_id']}", V, action="reschedule", new_slot_id=far[1]["slot_id"]).status_code == 200
          and call("patch", f"/api/bookings/{b2['booking_id']}", V, action="cancel").get_json()["refund_status"] == "refund pending")
    near = sql("SELECT * FROM time_slot WHERE slot_id<>? AND slot_date=? ORDER BY start_time", (s_new, str(clock.t.date())))[-1]
    b3 = call("post", "/api/bookings", V, slot_id=near["slot_id"], ticket_type_id=1, quantity=1).get_json(); call("post", f"/api/bookings/{b3['booking_id']}/pay", V, gateway_token="tok_success")
    check("FR-22", "cancellation less than 24 h before the slot is refused", call("patch", f"/api/bookings/{b3['booking_id']}", V, action="cancel").status_code == 409)
    # --- entry validation
    tok = p["tickets"][0]["token"]; vv = lambda t: call("post", "/api/entry/validate", S, token=t).get_json()
    first, second = vv(tok), vv(tok)
    check("FR-24/26", "ticket accepted once, live visitor count increases", first["result"] == "valid" and first["visitors_in_museum"] == 1)
    check("FR-24", "same ticket rejected the second time ('already used')", second.get("reason") == "already used")
    check("FR-24", "forged ticket rejected", vv("1.abcdef.0000")["result"] == "rejected")
    clock.t += timedelta(hours=3); S_late = login("staff@smms.example")          # new login: the old 15-minute session has expired
    check("FR-24", "ticket after the slot has ended is rejected ('expired')", call("post", "/api/entry/validate", S_late, token=p["tickets"][1]["token"]).get_json().get("reason") == "expired"); clock.t -= timedelta(hours=3)
    # --- collection
    sc = call("get", "/api/scan/ART-DEMO00", S).get_json()
    check("FR-12", "scan of QR value identifies the artifact", sc.get("title") == "Bronze Age Mask")
    u = call("patch", f"/api/artifacts/{sc['artifact_id']}", S, condition="poor", version=sc["updated_at"]).get_json()
    check("FR-14/15", "change is saved with history and a 'poor condition' alert is raised", u.get("alert") is True and any(h["field_name"] == "condition" for h in call("get", f"/api/artifacts/{sc['artifact_id']}/history", S).get_json())
          and any(a["artifact_id"] == sc["artifact_id"] for a in call("get", "/api/alerts", S).get_json()))
    check("FR-08", "creating an artifact without mandatory fields is refused", call("post", "/api/artifacts", S, title="x").status_code == 400)
    check("FR-10", "archiving needs a reason and never deletes the record", call("post", "/api/artifacts/8/archive", S, reason="").status_code == 400
          and call("post", "/api/artifacts/8/archive", S, reason="duplicate").status_code == 200 and sql("SELECT 1 FROM artifact WHERE artifact_id=8"))
    # --- AR, chatbot, recommendations
    check("NFR-05", "AR content over 20 MB is refused", call("post", "/api/ar-content", S, artifact_id=3, model_url="/m.glb", file_size_mb=25).status_code == 400)
    check("FR-35", "AR fallback is returned when AR is unsupported", call("get", "/api/ar/1?supports_ar=0", V).get_json()["ar"] is False)
    a1 = call("post", "/api/chat", V, question="what time are you open?", language="EN").get_json(); a2 = call("post", "/api/chat", V, question="who painted the Mona Lisa?", language="EN").get_json()
    check("FR-31", "chatbot answers from the knowledge base and names the source", not a1["fallback"] and a1.get("source"))
    check("FR-32", "out-of-scope question gets the fallback with help-desk contact", a2["fallback"] and "Help desk" in a2["answer"])
    call("patch", "/api/me", V, interests=["Textiles"], consent_personalisation=True); rec = call("get", "/api/recommendations", V).get_json()
    check("FR-29", "at least 5 recommendations, each with a reason", len(rec["items"]) >= 5 and all(i["reason"] for i in rec["items"]))
    call("patch", "/api/me", V, consent_personalisation=False)
    check("FR-07", "after consent is withdrawn only popular exhibits are shown", call("get", "/api/recommendations", V).get_json()["mode"].startswith("popular"))
    # --- analytics
    sm = call("get", "/api/analytics/summary", M).get_json()
    check("FR-37", "dashboard totals match the bookings made (tickets and revenue)", sm["tickets_sold"] >= 4 and sm["revenue"] >= 120)
    pdf, csv_ = call("post", "/api/reports/export", M, format="PDF"), call("post", "/api/reports/export", M, format="CSV")
    check("FR-40", "PDF and CSV reports are produced", pdf.data.startswith(b"%PDF") and csv_.get_data(as_text=True).startswith("Section"))
    check("FR-41", "reports contain no e-mail addresses or names", "@" not in csv_.get_data(as_text=True))
    # --- administration
    sid = sql("SELECT account_id FROM account WHERE email='staff@smms.example'")[0]["account_id"]
    call("patch", f"/api/admin/accounts/{sid}", A, role="Manager")
    check("FR-42/04", "role change applies at once (old staff token no longer works for staff actions)", call("post", "/api/categories", S, name="zzz").status_code == 403)
    call("patch", f"/api/admin/accounts/{sid}", A, role="Staff", is_active=False)
    check("FR-42", "deactivated account is locked out immediately", call("get", "/api/alerts", S).status_code == 401)
    check("FR-43", "audit log records failed logins and role changes", {e["event_type"] for e in call("get", "/api/audit", A).get_json()} >= {"failedLogin", "roleChange"})
    check("FR-44", "health check reports all components OK", call("get", "/api/health", A).get_json()["alerts"] == [])
    n = len(sql("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"))
    check("Phase 4", f"database has the 32 tables of Table 33 (found {n})", n == 32, f"found {n}")
finally:
    if os.path.exists(path): os.remove(path)
print(f"\n{sum(results)} of {len(results)} checks passed" + ("  -> the system behaves as specified" if all(results) else "  -> see FAIL lines above"))
sys.exit(0 if all(results) else 1)
