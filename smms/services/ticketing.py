"""S3 Ticketing & Visitor Management (FR-17..FR-24, FR-26)."""
import hashlib, hmac, io, secrets
from datetime import datetime, timedelta
from flask import Blueprint, current_app, g, jsonify, request, send_file
from ..db import q, x, tx, iso, local_now
from ..security import require_auth
from .audit import log_event
from .integration import request_payment, GatewayUnavailable, notify

bp = Blueprint("ticketing", __name__)
now = lambda: current_app.config["NOW"]()
CANCEL_HOURS = 24      # museum policy: cancellation/rescheduling allowed until 24 h before the slot

# ---------------- helpers ----------------
def expire_holds():
    """Holds expire after 10 minutes and return their seats to the slot (FR-19)."""
    x("UPDATE seat_hold SET status='expired' WHERE status='active' AND expires_at < ?", (iso(now()),))
    x("UPDATE booking SET status='cancelled' WHERE status='pending' AND booking_id IN (SELECT booking_id FROM seat_hold WHERE status='expired')")

def remaining(slot_id):
    s = q("SELECT capacity, confirmed_seats FROM time_slot WHERE slot_id=?", (slot_id,), one=True)
    holds = q("SELECT COALESCE(SUM(quantity),0) AS n FROM seat_hold WHERE slot_id=? AND status='active'", (slot_id,), one=True)["n"]
    return s["capacity"] - s["confirmed_seats"] - holds

def _slot_start(slot):
    return datetime.strptime(f"{slot['slot_date']} {slot['start_time']}", "%Y-%m-%d %H:%M")

def _sign(body):
    return hmac.new(current_app.config["SECRET_KEY"].encode(), body.encode(), hashlib.sha256).hexdigest()[:20]

def _new_token(ticket_id):
    body = f"{ticket_id}.{secrets.token_hex(8)}"
    return f"{body}.{_sign(body)}"

def _verify_token(tok):
    try:
        body, sig = tok.rsplit(".", 1)
        return hmac.compare_digest(sig, _sign(body))
    except Exception:
        return False

# ---------------- browse (FR-17, public) ----------------
@bp.get("/api/exhibitions/<int:eid>/availability")
def availability(eid):
    expire_holds()
    sql, args = "SELECT * FROM time_slot WHERE exhibition_id=?", [eid]
    if request.args.get("date"): sql += " AND slot_date=?"; args.append(request.args["date"])
    slots = q(sql + " ORDER BY slot_date, start_time", args)
    for s in slots: s["remaining"] = remaining(s["slot_id"])
    return jsonify(slots=slots, ticket_types=q("SELECT ticket_type_id,name,price,per_booking_limit FROM ticket_type WHERE exhibition_id=?", (eid,)))

# ---------------- booking with capacity control (FR-18, FR-19) ----------------
@bp.post("/api/bookings")
@require_auth("Visitor")
def create_booking():
    d = request.get_json(force=True)
    try: slot_id, tt_id, qty = int(d["slot_id"]), int(d["ticket_type_id"]), int(d["quantity"])
    except Exception: return jsonify(error="slot_id, ticket_type_id and quantity required"), 400
    with tx():                                   # one transaction: check + hold (NFR-12)
        expire_holds()
        slot = q("SELECT * FROM time_slot WHERE slot_id=?", (slot_id,), one=True)
        tt = q("SELECT * FROM ticket_type WHERE ticket_type_id=?", (tt_id,), one=True)
        if not slot or not tt or tt["exhibition_id"] != slot["exhibition_id"]: return jsonify(error="unknown slot or ticket type"), 404
        if qty < 1 or qty > tt["per_booking_limit"]: return jsonify(error=f"quantity must be between 1 and {tt['per_booking_limit']}"), 400
        if slot["slot_date"] < iso(local_now())[:10]: return jsonify(error="slot is in the past"), 400
        rem = remaining(slot_id)
        if qty > rem:
            return jsonify(error="not enough capacity", remaining=rem,
                           other_slots=[{"slot_id": s["slot_id"], "start_time": s["start_time"], "remaining": remaining(s["slot_id"])}
                                        for s in q("SELECT * FROM time_slot WHERE exhibition_id=? AND slot_date=? AND slot_id<>?", (slot["exhibition_id"], slot["slot_date"], slot_id))]), 409
        ref = "BK-" + secrets.token_hex(3).upper()
        total = round(tt["price"] * qty, 2)
        bid = x("INSERT INTO booking(booking_reference,visitor_id,slot_id,ticket_type_id,quantity,total_price,status,created_at) VALUES (?,?,?,?,?,?,?,?)",
                (ref, g.user["id"], slot_id, tt_id, qty, total, "pending", iso(now())))
        exp = iso(now() + timedelta(minutes=current_app.config["HOLD_MINUTES"]))
        x("INSERT INTO seat_hold(booking_id,slot_id,quantity,expires_at,status) VALUES (?,?,?,?,?)", (bid, slot_id, qty, exp, "active"))
    return jsonify(booking_id=bid, booking_reference=ref, total_price=total, hold_expires_at=exp, remaining_after_hold=rem - qty), 201

def _own(bid):
    b = q("SELECT * FROM booking WHERE booking_id=?", (bid,), one=True)
    return b if b and b["visitor_id"] == g.user["id"] else None

def _confirm(booking_id, gw):
    """Confirm a booking only after the gateway reported success (FR-20): capacity counter, payment record and
    one ticket per seat are written in ONE transaction (NFR-12: no overbooking, no duplicate ticket, no payment without ticket)."""
    with tx():
        b = q("SELECT * FROM booking WHERE booking_id=?", (booking_id,), one=True)
        if b["status"] == "confirmed":
            return b, "already confirmed"                       # idempotent: repeated callback creates nothing
        h = q("SELECT * FROM seat_hold WHERE booking_id=?", (booking_id,), one=True)
        if b["status"] != "pending":
            return b, "booking not payable"
        if h["status"] != "active" or h["expires_at"] < iso(now()):
            if h["status"] != "active" and remaining(b["slot_id"]) < b["quantity"]:
                x("UPDATE booking SET status='cancelled' WHERE booking_id=?", (booking_id,))
                return b, "hold expired"
            x("UPDATE seat_hold SET status='active', expires_at=? WHERE booking_id=?", (iso(now() + timedelta(minutes=1)), booking_id))
        x("UPDATE seat_hold SET status='converted' WHERE booking_id=?", (booking_id,))
        x("UPDATE time_slot SET confirmed_seats = confirmed_seats + ? WHERE slot_id=?", (b["quantity"], b["slot_id"]))
        x("UPDATE booking SET status='confirmed' WHERE booking_id=?", (booking_id,))
        x("INSERT INTO payment_record(booking_id,gateway_status,amount,currency,transaction_ref,paid_at) VALUES (?,?,?,?,?,?)",
          (booking_id, "successful", b["total_price"], "AED", gw["transaction_ref"], iso(now())))
        for _ in range(b["quantity"]):
            tid = x("INSERT INTO digital_ticket(booking_id,token,status,issued_at) VALUES (?,?,?,?)", (booking_id, "tmp-" + secrets.token_hex(6), "unused", iso(now())))
            x("UPDATE digital_ticket SET token=? WHERE ticket_id=?", (_new_token(tid), tid))
    notify(b["visitor_id"], "confirmation", f"Booking {b['booking_reference']} confirmed", f"{b['quantity']} ticket(s) issued", booking_id=booking_id)
    return q("SELECT * FROM booking WHERE booking_id=?", (booking_id,), one=True), None

@bp.post("/api/bookings/<int:bid>/pay")
@require_auth("Visitor")
def pay(bid):
    """FR-20: payment via external gateway. Body carries only a gateway token, never card data (NFR-18)."""
    expire_holds()
    b = _own(bid)
    if not b: return jsonify(error="booking not found"), 404
    if b["status"] == "confirmed":
        return jsonify(message="already paid", booking_reference=b["booking_reference"])
    if b["status"] != "pending": return jsonify(error="hold expired - start a new booking"), 410
    token = (request.get_json(force=True) or {}).get("gateway_token", "")
    try:
        gw = request_payment(b["total_price"], b["booking_reference"], token)
    except GatewayUnavailable:
        return jsonify(error="payment service unavailable, please try again later (no booking was confirmed)"), 503   # NFR-13
    if gw["status"] != "successful":
        return jsonify(error="payment declined", reason=gw.get("reason"), hold_kept_until=q("SELECT expires_at FROM seat_hold WHERE booking_id=?", (bid,), one=True)["expires_at"]), 402
    b2, problem = _confirm(bid, gw)
    if problem == "hold expired": return jsonify(error="hold expired before payment completed - refund will be issued"), 410
    tickets = q("SELECT ticket_id,token,status FROM digital_ticket WHERE booking_id=?", (bid,))
    return jsonify(booking_reference=b2["booking_reference"], status=b2["status"], tickets=tickets)

@bp.post("/api/payments/callback")
def payment_callback():
    """Signed gateway callback (idempotent: a repeated callback cannot create a second payment or ticket)."""
    d = request.get_json(force=True)
    body = f"{d.get('booking_reference')}|{d.get('transaction_ref')}|{d.get('status')}"
    if not hmac.compare_digest(request.headers.get("X-Signature", ""), _sign(body)): return jsonify(error="bad signature"), 403
    b = q("SELECT * FROM booking WHERE booking_reference=?", (d.get("booking_reference"),), one=True)
    if not b: return jsonify(error="unknown booking"), 404
    if d.get("status") == "successful":
        _confirm(b["booking_id"], {"transaction_ref": d["transaction_ref"]})
    return jsonify(message="ok")

@bp.get("/api/bookings")
@require_auth("Visitor")
def my_bookings():
    expire_holds()
    return jsonify(q("""SELECT b.booking_id,b.booking_reference,b.quantity,b.total_price,b.status,s.slot_date,s.start_time,e.title
                        FROM booking b JOIN time_slot s ON s.slot_id=b.slot_id JOIN exhibition e ON e.exhibition_id=s.exhibition_id
                        WHERE b.visitor_id=? ORDER BY b.booking_id DESC""", (g.user["id"],)))

@bp.get("/api/bookings/<int:bid>")
@require_auth("Visitor")
def get_booking(bid):
    b = _own(bid)
    if not b: return jsonify(error="booking not found"), 404
    b["tickets"] = q("SELECT ticket_id,token,status FROM digital_ticket WHERE booking_id=?", (bid,))
    return jsonify(b)

@bp.patch("/api/bookings/<int:bid>")
@require_auth("Visitor")
def change_booking(bid):
    """FR-22: cancel or reschedule until the museum-policy deadline; capacity of the old slot is released."""
    expire_holds()
    b = _own(bid); d = request.get_json(force=True)
    if not b: return jsonify(error="booking not found"), 404
    slot = q("SELECT * FROM time_slot WHERE slot_id=?", (b["slot_id"],), one=True)
    if b["status"] not in ("pending", "confirmed"): return jsonify(error="booking cannot be changed"), 409
    if b["status"] == "confirmed" and local_now() > _slot_start(slot) - timedelta(hours=CANCEL_HOURS):
        return jsonify(error=f"deadline passed ({CANCEL_HOURS} h before the slot)"), 409
    action = d.get("action")
    with tx():
        if action == "cancel":
            if b["status"] == "confirmed":
                x("UPDATE time_slot SET confirmed_seats = confirmed_seats - ? WHERE slot_id=?", (b["quantity"], b["slot_id"]))
                x("UPDATE digital_ticket SET status='cancelled' WHERE booking_id=?", (bid,))
            else:
                x("UPDATE seat_hold SET status='released' WHERE booking_id=?", (bid,))
            x("UPDATE booking SET status='cancelled' WHERE booking_id=?", (bid,))
            refund = "refund pending" if b["status"] == "confirmed" else "no payment taken"
        elif action == "reschedule" and b["status"] == "confirmed":
            new = q("SELECT * FROM time_slot WHERE slot_id=?", (d.get("new_slot_id"),), one=True)
            if not new or new["exhibition_id"] != slot["exhibition_id"]: return jsonify(error="invalid new slot"), 400
            if _slot_start(new) < local_now(): return jsonify(error="new slot is in the past"), 400
            if remaining(new["slot_id"]) < b["quantity"]: return jsonify(error="not enough capacity in the new slot", remaining=remaining(new["slot_id"])), 409
            x("UPDATE time_slot SET confirmed_seats = confirmed_seats - ? WHERE slot_id=?", (b["quantity"], b["slot_id"]))
            x("UPDATE time_slot SET confirmed_seats = confirmed_seats + ? WHERE slot_id=?", (b["quantity"], new["slot_id"]))
            x("UPDATE booking SET slot_id=? WHERE booking_id=?", (new["slot_id"], bid))
            refund = None
        else:
            return jsonify(error="action must be cancel or reschedule (reschedule needs a confirmed booking)"), 400
    notify(b["visitor_id"], "cancellation" if action == "cancel" else "confirmation", f"Booking {b['booking_reference']} {action}led" if action == "cancel" else f"Booking {b['booking_reference']} rescheduled", "", booking_id=bid)
    return jsonify(message=action + " done", refund_status=refund)

@bp.get("/api/tickets/<int:tid>/qr.png")
@require_auth("Visitor")
def ticket_qr(tid):
    t = q("SELECT t.token,b.visitor_id FROM digital_ticket t JOIN booking b ON b.booking_id=t.booking_id WHERE t.ticket_id=?", (tid,), one=True)
    if not t or t["visitor_id"] != g.user["id"]: return jsonify(error="not found"), 404
    try: import qrcode
    except ImportError: return jsonify(error="install the 'qrcode' package"), 501
    buf = io.BytesIO(); qrcode.make(t["token"]).save(buf, format="PNG"); buf.seek(0)
    return send_file(buf, mimetype="image/png")

# ---------------- entry validation (FR-24, FR-26) ----------------
def _reject(ticket_id, staff_id, reason):
    if ticket_id:
        x("INSERT INTO entry_validation(ticket_id,staff_id,result,reason,validated_at) VALUES (?,?,?,?,?)", (ticket_id, staff_id, "rejected", reason, iso(now())))
    log_event("ticketValidation", staff_id, f"rejected: {reason}")
    return jsonify(result="rejected", reason=reason), 200

@bp.post("/api/entry/validate")
@require_auth("Staff")
def validate_ticket():
    """SPEC-3: verify signature, find ticket, check date/slot (with grace) and status; accepted only once."""
    tok = (request.get_json(force=True).get("token") or "").strip(); sid = g.user["id"]
    if not _verify_token(tok): return _reject(None, sid, "unknown")
    t = q("SELECT * FROM digital_ticket WHERE token=?", (tok,), one=True)
    if not t: return _reject(None, sid, "unknown")
    b = q("SELECT * FROM booking WHERE booking_id=?", (t["booking_id"],), one=True)
    slot = q("SELECT * FROM time_slot WHERE slot_id=?", (b["slot_id"],), one=True)
    ttype = q("SELECT name FROM ticket_type WHERE ticket_type_id=?", (b["ticket_type_id"],), one=True)["name"]
    if t["status"] == "cancelled" or b["status"] == "cancelled": return _reject(t["ticket_id"], sid, "cancelled")
    if t["status"] == "used": return _reject(t["ticket_id"], sid, "already used")
    start = _slot_start(slot); grace = timedelta(minutes=current_app.config["ENTRY_GRACE_MINUTES"])
    end = datetime.strptime(f"{slot['slot_date']} {slot['end_time']}", "%Y-%m-%d %H:%M")
    n = local_now()                                      # slot times are museum wall-clock time
    if n.date() > start.date() or (n.date() == start.date() and n > end + grace):
        x("UPDATE digital_ticket SET status='expired' WHERE ticket_id=?", (t["ticket_id"],)); return _reject(t["ticket_id"], sid, "expired")
    if n.date() < start.date() or n < start - grace: return _reject(t["ticket_id"], sid, "wrong date or slot")
    with tx():
        if q("SELECT status FROM digital_ticket WHERE ticket_id=?", (t["ticket_id"],), one=True)["status"] == "used":   # race guard
            return _reject(t["ticket_id"], sid, "already used")
        x("UPDATE digital_ticket SET status='used' WHERE ticket_id=?", (t["ticket_id"],))
        x("INSERT INTO entry_validation(ticket_id,staff_id,result,reason,validated_at) VALUES (?,?,?,?,?)", (t["ticket_id"], sid, "valid", None, iso(now())))
        today = iso(n)[:10]
        if q("SELECT 1 FROM live_visitor_counter WHERE counter_date=?", (today,), one=True):
            x("UPDATE live_visitor_counter SET visitors_in=visitors_in+1, updated_at=? WHERE counter_date=?", (iso(now()), today))
        else:
            x("INSERT INTO live_visitor_counter(counter_date,visitors_in,updated_at) VALUES (?,?,?)", (today, 1, iso(now())))
    log_event("ticketValidation", sid, f"ticket {t['ticket_id']} valid")
    live = q("SELECT visitors_in FROM live_visitor_counter WHERE counter_date=?", (today,), one=True)["visitors_in"]
    return jsonify(result="valid", ticket_type=ttype, quantity=1, booking_reference=b["booking_reference"], visitors_in_museum=live)

@bp.get("/api/visitors/live")
@require_auth("Staff", "Manager")
def live_count():
    r = q("SELECT visitors_in FROM live_visitor_counter WHERE counter_date=?", (iso(local_now())[:10],), one=True)
    return jsonify(visitors_in_museum=r["visitors_in"] if r else 0)

@bp.post("/api/entry/exit")
@require_auth("Staff")
def visitor_exit():
    """Keeps the live count correct when visitors leave (counter never goes below zero)."""
    today = iso(local_now())[:10]
    x("UPDATE live_visitor_counter SET visitors_in = MAX(visitors_in-1,0), updated_at=? WHERE counter_date=?", (iso(now()), today))
    return live_count.__wrapped__() if hasattr(live_count, "__wrapped__") else jsonify(message="ok")
