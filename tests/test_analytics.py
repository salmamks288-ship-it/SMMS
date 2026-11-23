import csv, io
from datetime import timedelta
from .base import Base

class TestAnalytics(Base):
    def setUp(self):
        super().setUp()
        self.clock.t = self.clock.t.replace(hour=9, minute=0)
        v, st = self.visitor, self.staff
        slots = self.sql("SELECT * FROM time_slot ORDER BY slot_date,start_time")
        for i, qty in enumerate((2, 3)):
            self.book_and_pay(v, slots[i]["slot_id"], qty)
        self.m = self.manager

    def test_TC_FR_37_dashboard_totals_by_date_slot_type(self):
        r = self.get("/api/analytics/summary", self.m).get_json()
        self.assertEqual(r["tickets_sold"], 5); self.assertEqual(r["revenue"], 150.0)
        self.assertEqual(r["by_ticket_type"][0]["ticket_type"], "Adult"); self.assertTrue(r["by_slot"]); self.assertTrue(r["peak_hours"])

    def test_TC_FR_40_filters_by_date_exhibition_and_ticket_type(self):
        r = self.get("/api/analytics/summary?ticket_type_id=2", self.m).get_json(); self.assertEqual(r["tickets_sold"], 0)
        r = self.get("/api/analytics/summary?exhibition_id=1&from=2000-01-01&to=2100-01-01", self.m).get_json(); self.assertEqual(r["tickets_sold"], 5)

    def test_TC_FR_38_engagement_metrics_present(self):
        v = self.visitor; self.post("/api/chat", v, {"question": "zzz unrelated", "language": "EN"})
        r = self.get("/api/analytics/summary", self.m).get_json()
        for k in ("most_viewed_exhibits", "recommendation_click_through_rate", "chatbot_unanswered_rate", "ar_sessions"): self.assertIn(k, r)
        self.assertEqual(r["chatbot_unanswered_rate"], 1.0)

    def test_TC_FR_39_inventory_summary_for_manager_and_staff(self):
        self.patch("/api/artifacts/1", self.staff, {"inspection_date": "2001-01-01"})
        for tok in (self.m, self.staff):
            r = self.get("/api/analytics/inventory", tok).get_json()
            self.assertTrue(r["by_status"]); self.assertEqual(r["inspection_overdue"][0]["artifact_id"], 1)
        self.assertEqual(self.get("/api/analytics/inventory", self.visitor).status_code, 403)

    def test_TC_FR_41_NL4_no_personal_identifiers_in_dashboard_or_exports(self):
        txt = self.get("/api/analytics/summary", self.m).get_data(as_text=True)
        csvtxt = self.post("/api/reports/export", self.m, {"format": "CSV"}).get_data(as_text=True)
        pdf = self.post("/api/reports/export", self.m, {"format": "PDF"}).get_data()
        for needle in ("@", "visitor@smms", "Demo Visitor", "display_name", "email"):
            self.assertNotIn(needle, txt); self.assertNotIn(needle, csvtxt)
        self.assertNotIn(b"visitor@smms", pdf)

    def test_TC_FR_40_export_pdf_and_csv(self):
        c = self.post("/api/reports/export", self.m, {"format": "CSV"})
        rows = list(csv.reader(io.StringIO(c.get_data(as_text=True)))); self.assertEqual(rows[0], ["Section", "Item", "Value", "Extra"])
        p = self.post("/api/reports/export", self.m, {"format": "PDF"}); self.assertTrue(p.get_data().startswith(b"%PDF"))
        self.assertEqual(self.post("/api/reports/export", self.m, {"format": "DOC"}).status_code, 400)
        self.assertEqual(len(self.sql("SELECT 1 FROM report_export")), 2)

    def test_TC_FR_43_FR_44_audit_search_and_health_alerts(self):
        a = self.admin
        self.assertTrue(self.get("/api/audit?event_type=login", a).get_json())
        self.integration.STATE["payment_up"] = False
        h = self.get("/api/health", a).get_json(); self.assertIn("payment_gateway not available", h["alerts"])
        self.integration.STATE["payment_up"] = True; self.assertEqual(self.get("/api/health", a).get_json()["alerts"], [])

    def test_TC_NFR_06_dashboard_with_many_records_under_5_seconds(self):
        import time
        with self.app.app_context():
            from smms.db import get_db
            db = get_db(); db.execute("BEGIN")
            db.executemany("INSERT INTO booking(booking_reference,visitor_id,slot_id,ticket_type_id,quantity,total_price,status,created_at) VALUES (?,?,?,?,?,?,?,?)",
                           [(f"LOAD{i}", 1, 1 + i % 20, 1, 1, 30.0, "confirmed", "2026-01-01 10:00:00") for i in range(20000)])
            db.execute("COMMIT")
        t0 = time.perf_counter(); self.get("/api/analytics/summary", self.m); self.assertLess(time.perf_counter() - t0, 5.0)

    def test_TC_FR_40_report_follows_table_36_layout(self):
        m = self.m                                     # setUp booked 2 + 3 tickets (2 bookings, AED 150)
        d = self.get("/api/analytics/summary", m).get_json()
        for k in ("avg_booking_value", "peak_hour", "change_vs_previous_pct"): self.assertIn(k, d)
        self.assertEqual(d["avg_booking_value"], 75.0); self.assertEqual(d["by_ticket_type"][0]["share_pct"], 100.0)
        csvtxt = self.post("/api/reports/export", m, {"format": "CSV"}).get_data(as_text=True)
        for label in ("Average booking value", "Peak hour", "Change vs previous period", "Top exhibits"): self.assertIn(label, csvtxt)
        pdf = self.post("/api/reports/export", m, {"format": "PDF", "from": "2000-01-01", "to": "2100-01-01"})
        self.assertEqual(pdf.status_code, 200); self.assertTrue(pdf.data.startswith(b"%PDF"))

    def test_TC_FR_43_audit_log_older_than_12_months_is_purged(self):
        with self.app.app_context():
            from smms.db import x, iso
            from smms.services.audit import purge_old
            x("INSERT INTO audit_log(event_type,user_id,event_time,details) VALUES ('login',1,?,'old')", (iso(self.clock() - timedelta(days=400)),))
            x("INSERT INTO audit_log(event_type,user_id,event_time,details) VALUES ('login',1,?,'recent')", (iso(self.clock() - timedelta(days=30)),))
            purge_old(force=True)
        d = [r["details"] for r in self.sql("SELECT details FROM audit_log")]
        self.assertNotIn("old", d); self.assertIn("recent", d)
