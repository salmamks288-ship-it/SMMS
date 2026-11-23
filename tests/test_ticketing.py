import hashlib, hmac, threading
from datetime import datetime, timedelta
from .base import Base

class TestTicketing(Base):
    def test_TC_FR_17_availability_is_public_and_shows_remaining(self):
        r = self.get("/api/exhibitions/1/availability").get_json()                       # no login
        self.assertEqual(r["slots"][0]["remaining"], 20); self.assertEqual(len(r["ticket_types"]), 3)

    def test_TC_FR_18_FR_19_booking_holds_seats_and_shows_total(self):
        v = self.visitor; s = self.slot()
        r = self.book(v, s["slot_id"], 3); b = r.get_json()
        self.assertEqual(r.status_code, 201); self.assertEqual(b["total_price"], 90.0); self.assertEqual(b["remaining_after_hold"], 17)
        self.assertEqual(self.get("/api/exhibitions/1/availability").get_json()["slots"][0]["remaining"], 17)

    def test_TC_FR_19_refuses_when_capacity_insufficient_and_offers_other_slots(self):
        v = self.visitor; s = self.slot(); v2 = self.new_visitor()
        self.assertEqual(self.book(v, s["slot_id"], 10).status_code, 201)
        self.assertEqual(self.book(v2, s["slot_id"], 10).status_code, 201)             # slot capacity 20 is now fully held
        r = self.book(v2, s["slot_id"], 1)
        self.assertEqual(r.status_code, 409); self.assertEqual(r.get_json()["remaining"], 0)
        self.assertTrue(r.get_json()["other_slots"])

    def test_TC_FR_19_per_booking_limit_and_invalid_quantity(self):
        v = self.visitor; s = self.slot()
        self.assertEqual(self.book(v, s["slot_id"], 0).status_code, 400)
        self.assertEqual(self.book(v, s["slot_id"], 11).status_code, 400)

    def test_TC_FR_19_hold_expires_after_10_minutes_and_returns_seats(self):
        v = self.visitor; s = self.slot()
        b = self.book(v, s["slot_id"], 5).get_json()
        self.clock.advance(minutes=11)
        self.assertEqual(self.get("/api/exhibitions/1/availability").get_json()["slots"][0]["remaining"], 20)
        r = self.post(f"/api/bookings/{b['booking_id']}/pay", v, {"gateway_token": "tok_success"})
        self.assertEqual(r.status_code, 410)                                             # E2: restart booking

    def test_TC_FR_20_FR_21_payment_confirms_booking_and_issues_one_ticket_per_seat(self):
        v = self.visitor; s = self.slot()
        b, p = self.book_and_pay(v, s["slot_id"], 3)
        self.assertEqual(p["status"], "confirmed"); self.assertEqual(len(p["tickets"]), 3)
        self.assertEqual(len({t["token"] for t in p["tickets"]}), 3)                      # unique tokens
        self.assertEqual(self.sql("SELECT confirmed_seats FROM time_slot WHERE slot_id=?", (s["slot_id"],))[0]["confirmed_seats"], 3)
        self.assertEqual(self.sql("SELECT amount,currency FROM payment_record")[0]["amount"], 90.0)
        self.assertTrue([m for m in self.integration.STATE["outbox"] if "confirmed" in m["subject"]])  # FR-23
        # paying again is idempotent: no second payment or ticket
        self.post(f"/api/bookings/{b['booking_id']}/pay", v, {"gateway_token": "tok_success"})
        self.assertEqual(len(self.sql("SELECT 1 FROM digital_ticket")), 3); self.assertEqual(len(self.sql("SELECT 1 FROM payment_record")), 1)

    def test_TC_FR_20_no_card_data_stored_anywhere(self):
        cols = [c["name"].lower() for t in self.sql("SELECT name FROM sqlite_master WHERE type='table'") for c in self.sql(f"PRAGMA table_info({t['name']})")]
        for bad in ("card", "cvv", "cvc", "expiry", "pan"): self.assertFalse([c for c in cols if bad in c], bad)
        v = self.visitor; s = self.slot(); self.book_and_pay(v, s["slot_id"], 1)
        dump = str(self.sql("SELECT * FROM payment_record")) + str(self.sql("SELECT * FROM audit_log"))
        self.assertNotIn("4242", dump)

    def test_TC_FR_20_declined_payment_keeps_hold_no_ticket(self):
        v = self.visitor; s = self.slot(); b = self.book(v, s["slot_id"], 2).get_json()
        r = self.post(f"/api/bookings/{b['booking_id']}/pay", v, {"gateway_token": "tok_declined"})
        self.assertEqual(r.status_code, 402); self.assertEqual(len(self.sql("SELECT 1 FROM digital_ticket")), 0)
        self.assertEqual(self.sql("SELECT status FROM seat_hold")[0]["status"], "active")
        r = self.post(f"/api/bookings/{b['booking_id']}/pay", v, {"gateway_token": "tok_success"})   # retry works
        self.assertEqual(r.status_code, 200)

    def test_TC_NFR_13_gateway_unavailable_gives_message_and_other_functions_work(self):
        v = self.visitor; s = self.slot(); b = self.book(v, s["slot_id"], 1).get_json()
        self.integration.STATE["payment_up"] = False
        r = self.post(f"/api/bookings/{b['booking_id']}/pay", v, {"gateway_token": "tok_success"})
        self.assertEqual(r.status_code, 503); self.assertIn("unavailable", r.get_json()["error"])
        self.assertEqual(self.sql("SELECT status FROM booking")[0]["status"], "pending")
        self.assertEqual(self.get("/api/exhibitions").status_code, 200)                  # rest of the system still works
        self.assertEqual(self.get("/api/recommendations", v).status_code, 200)

    def test_TC_UC04_E4_email_failure_retries_three_times_tickets_stay_available(self):
        self.integration.STATE["notify_up"] = False
        v = self.visitor; s = self.slot(); b, p = self.book_and_pay(v, s["slot_id"], 1)
        n = self.sql("SELECT attempts,status FROM notification WHERE channel='email'")[-1]
        self.assertEqual((n["attempts"], n["status"]), (3, "failed"))
        self.assertEqual(len(self.get(f"/api/bookings/{b['booking_id']}", v).get_json()["tickets"]), 1)

    def test_TC_NFR_12_concurrent_bookings_never_overbook(self):
        """30 visitors race for a slot with capacity 20 (1 seat each): exactly 20 succeed, 0 overbooked, 0 duplicate tickets."""
        s = self.slot(); toks = [self.new_visitor(f"u{i}@example.com") for i in range(30)]
        res = []
        def work(tok):
            c = self.app.test_client()
            b = c.post("/api/bookings", json={"slot_id": s["slot_id"], "ticket_type_id": 1, "quantity": 1}, headers=self.h(tok))
            if b.status_code == 201:
                p = c.post(f"/api/bookings/{b.get_json()['booking_id']}/pay", json={"gateway_token": "tok_success"}, headers=self.h(tok)); res.append(p.status_code)
            else: res.append(b.status_code)
        th = [threading.Thread(target=work, args=(t,)) for t in toks]
        [t.start() for t in th]; [t.join() for t in th]
        self.assertEqual(res.count(200), 20); self.assertEqual(res.count(409), 10)
        row = self.sql("SELECT capacity,confirmed_seats FROM time_slot WHERE slot_id=?", (s["slot_id"],))[0]
        self.assertEqual(row["confirmed_seats"], 20); self.assertLessEqual(row["confirmed_seats"], row["capacity"])
        self.assertEqual(len(self.sql("SELECT 1 FROM digital_ticket")), 20); self.assertEqual(len(self.sql("SELECT 1 FROM payment_record")), 20)

    def test_TC_FR_22_cancel_releases_capacity_and_reschedule_moves_seats(self):
        v = self.visitor; s0, s1 = self.slot(0), self.slot(1)
        # use slots >24h away: pick next-day slots
        slots = self.sql("SELECT * FROM time_slot WHERE slot_date > ? ORDER BY slot_date,start_time", (str(self.clock().date()),))
        a, b = slots[0], slots[1]
        bk, _ = self.book_and_pay(v, a["slot_id"], 2)
        r = self.patch(f"/api/bookings/{bk['booking_id']}", v, {"action": "reschedule", "new_slot_id": b["slot_id"]})
        self.assertEqual(r.status_code, 200)
        conf = lambda sid: self.sql("SELECT confirmed_seats FROM time_slot WHERE slot_id=?", (sid,))[0]["confirmed_seats"]
        self.assertEqual((conf(a["slot_id"]), conf(b["slot_id"])), (0, 2))
        r = self.patch(f"/api/bookings/{bk['booking_id']}", v, {"action": "cancel"})
        self.assertEqual(r.get_json()["refund_status"], "refund pending"); self.assertEqual(conf(b["slot_id"]), 0)
        self.assertEqual(self.sql("SELECT DISTINCT status FROM digital_ticket")[0]["status"], "cancelled")

    def test_TC_FR_22_cancel_deadline_enforced(self):
        self.clock.t = self.clock.t.replace(hour=8, minute=0)
        v = self.visitor; s = self.slot(); bk, _ = self.book_and_pay(v, s["slot_id"], 1)
        self.clock.t = self.clock.t.replace(hour=9, minute=30); v = self.visitor           # same day, <24 h before the 10:00 slot
        r = self.patch(f"/api/bookings/{bk['booking_id']}", v, {"action": "cancel"})
        self.assertEqual(r.status_code, 409)

    def test_TC_FR_24_entry_validation_all_outcomes(self):
        self.clock.t = self.clock.t.replace(hour=9, minute=0)
        v, st = self.visitor, self.staff; s = self.slot()
        _, p = self.book_and_pay(v, s["slot_id"], 2); t1, t2 = p["tickets"][0]["token"], p["tickets"][1]["token"]
        v1 = lambda tok: self.post("/api/entry/validate", st, {"token": tok}).get_json()
        self.assertEqual(v1("garbage.token.sig")["reason"], "unknown")
        self.assertEqual(v1("1.deadbeef.0000000000")["reason"], "unknown")
        self.assertEqual(v1(t1)["reason"], "wrong date or slot")                          # too early (09:00 for a 10:00 slot -> grace is 15 min)
        self.clock.t = self.clock.t.replace(hour=10, minute=5); st = self.staff
        ok = v1(t1); self.assertEqual(ok["result"], "valid"); self.assertEqual(ok["visitors_in_museum"], 1)
        self.assertEqual(v1(t1)["reason"], "already used")                                 # accepted only once
        self.clock.t = self.clock.t.replace(hour=12, minute=0); st = self.staff
        self.assertEqual(v1(t2)["reason"], "expired")
        self.assertEqual(self.get("/api/visitors/live", st).get_json()["visitors_in_museum"], 1)
        self.assertTrue(self.sql("SELECT 1 FROM audit_log WHERE event_type='ticketValidation'"))

    def test_TC_FR_24_cancelled_ticket_rejected(self):
        v, st = self.visitor, self.staff
        slots = self.sql("SELECT * FROM time_slot WHERE slot_date > ? ORDER BY slot_date,start_time", (str(self.clock().date()),))
        bk, p = self.book_and_pay(v, slots[0]["slot_id"], 1)
        self.patch(f"/api/bookings/{bk['booking_id']}", v, {"action": "cancel"})
        self.assertEqual(self.post("/api/entry/validate", st, {"token": p["tickets"][0]["token"]}).get_json()["reason"], "cancelled")

    def test_TC_FR_24_visitor_cannot_validate(self):
        self.assertEqual(self.post("/api/entry/validate", self.visitor, {"token": "x"}).status_code, 403)

    def test_TC_NFR_07_validation_response_time_under_2_seconds(self):
        import time
        self.clock.t = self.clock.t.replace(hour=10, minute=0)
        v, st = self.visitor, self.staff; s = self.slot()
        _, p = self.book_and_pay(v, s["slot_id"], 1)
        t0 = time.perf_counter(); self.post("/api/entry/validate", st, {"token": p["tickets"][0]["token"]}); self.assertLess(time.perf_counter() - t0, 2.0)

    def test_signed_payment_callback_is_idempotent(self):
        v = self.visitor; s = self.slot(); b = self.book(v, s["slot_id"], 1).get_json()
        body = {"booking_reference": b["booking_reference"], "transaction_ref": "TX-9", "status": "successful"}
        sig = lambda: hmac.new(self.app.config["SECRET_KEY"].encode(), f"{body['booking_reference']}|TX-9|successful".encode(), hashlib.sha256).hexdigest()[:20]
        self.assertEqual(self.c.post("/api/payments/callback", json=body, headers={"X-Signature": "bad"}).status_code, 403)
        for _ in range(3): self.assertEqual(self.c.post("/api/payments/callback", json=body, headers={"X-Signature": sig()}).status_code, 200)
        self.assertEqual(len(self.sql("SELECT 1 FROM payment_record")), 1); self.assertEqual(len(self.sql("SELECT 1 FROM digital_ticket")), 1)

    def test_TC_FR_24_slot_times_use_museum_local_time_not_utc(self):
        # museum is UTC+4: a 10:00 local slot is 06:00 UTC. Validation at 06:05 UTC must be accepted, at 10:05 UTC must be "expired".
        self.app.config["MUSEUM_UTC_OFFSET_HOURS"] = 4
        today_local = (self.clock.t + timedelta(hours=4)).date()
        self.clock.t = datetime.combine(today_local, datetime.min.time()).replace(hour=1)        # 01:00 UTC = 05:00 local
        s = self.sql("SELECT * FROM time_slot WHERE slot_date=? ORDER BY start_time", (str(today_local),))
        if not s: self.skipTest("no slot for local today")
        v, st = self.visitor, self.staff
        _, p = self.book_and_pay(v, s[0]["slot_id"], 1)
        self.clock.t = self.clock.t.replace(hour=6, minute=5); st = self.staff
        self.assertEqual(self.post("/api/entry/validate", st, {"token": p["tickets"][0]["token"]}).get_json()["result"], "valid")

    def test_TC_FR_22_cannot_reschedule_into_the_past(self):
        v = self.visitor
        slots = self.sql("SELECT * FROM time_slot WHERE slot_date > ? ORDER BY slot_date,start_time", (str(self.clock().date() + timedelta(days=1)),))
        bk, _ = self.book_and_pay(v, slots[0]["slot_id"], 1)                       # 2 days ahead: still inside the cancel/reschedule window
        self.clock.t = self.clock.t.replace(hour=12, minute=0)
        past = self.sql("SELECT * FROM time_slot WHERE slot_date=? ORDER BY start_time", (str(self.clock().date()),))[0]
        self.assertEqual(self.patch(f"/api/bookings/{bk['booking_id']}", self.visitor, {"action": "reschedule", "new_slot_id": past["slot_id"]}).status_code, 400)
