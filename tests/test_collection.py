from .base import Base

ART = {"title": "Test Vase", "category_id": 1, "description": "A vase", "period": "1900", "origin": "UAE", "condition": "good", "location": "Gallery 1", "status": "onDisplay"}

class TestCollection(Base):
    def make(self, tok, **kw):
        r = self.post("/api/artifacts", tok, {**ART, **kw}); self.assertEqual(r.status_code, 201, r.get_data(as_text=True)); return r.get_json()

    def test_TC_FR_08_create_requires_mandatory_fields_and_generates_qr_value(self):
        s = self.staff
        r = self.post("/api/artifacts", s, {"title": "x"})
        self.assertEqual(r.status_code, 400); self.assertIn("category_id", r.get_json()["fields"])
        a, b = self.make(s), self.make(s)
        self.assertNotEqual(a["qr_code_value"], b["qr_code_value"])                      # FR-11 unique QR value

    def test_TC_FR_09_FR_14_update_stores_history_old_and_new_value(self):
        s = self.staff; a = self.make(s)
        r = self.patch(f"/api/artifacts/{a['artifact_id']}", s, {"location": "Gallery 3", "status": "underRestoration"})
        self.assertEqual(r.status_code, 200)
        h = self.get(f"/api/artifacts/{a['artifact_id']}/history", s).get_json()
        loc = [x for x in h if x["field_name"] == "location"][0]
        self.assertEqual((loc["old_value"], loc["new_value"]), ("Gallery 1", "Gallery 3")); self.assertTrue(loc["changed_by"] and loc["changed_at"])

    def test_TC_FR_09_concurrent_edit_returns_latest_values(self):
        s = self.staff; a = self.make(s); aid = a["artifact_id"]
        v = self.get(f"/api/artifacts/{aid}", s).get_json()["updated_at"]
        self.clock.advance(seconds=5)
        self.patch(f"/api/artifacts/{aid}", s, {"notes": None, "location": "Gallery 2"})   # another user saves first
        r = self.patch(f"/api/artifacts/{aid}", s, {"location": "Gallery 4", "version": v})
        self.assertEqual(r.status_code, 409); self.assertEqual(r.get_json()["latest"]["location"], "Gallery 2")

    def test_TC_FR_10_archive_needs_reason_and_is_never_deleted(self):
        s = self.staff; a = self.make(s); aid = a["artifact_id"]
        self.assertEqual(self.post(f"/api/artifacts/{aid}/archive", s, {}).status_code, 400)
        self.assertEqual(self.post(f"/api/artifacts/{aid}/archive", s, {"reason": "sold"}).status_code, 200)
        self.assertEqual(len(self.sql("SELECT 1 FROM artifact WHERE artifact_id=?", (aid,))), 1)       # row still exists
        self.assertEqual(self.patch(f"/api/artifacts/{aid}", s, {"location": "x"}).status_code, 409)    # read-only
        self.assertNotIn(aid, [x["artifact_id"] for x in self.get("/api/artifacts", s).get_json()])      # hidden from lists
        self.assertEqual(self.get(f"/api/exhibits/{aid}", self.visitor).status_code, 404)                 # hidden from visitors

    def test_TC_FR_12_scan_identifies_by_qr_or_rfid(self):
        s = self.staff; a = self.make(s, rfid_tag_id="RFID-777")
        self.assertEqual(self.get(f"/api/scan/{a['qr_code_value']}", s).get_json()["artifact_id"], a["artifact_id"])
        self.assertEqual(self.get("/api/scan/RFID-777", s).get_json()["artifact_id"], a["artifact_id"])
        r = self.get("/api/scan/UNKNOWN", s); self.assertEqual(r.status_code, 404); self.assertTrue(r.get_json()["can_create"])

    def test_TC_FR_13_search_filters_can_be_combined(self):
        s = self.staff
        self.make(s, title="Blue Jar", location="Gallery 9", status="inStorage"); self.make(s, title="Blue Plate", location="Gallery 9", status="onDisplay")
        r = self.get("/api/artifacts?title=Blue&location=Gallery 9&status=inStorage", s).get_json()
        self.assertEqual([x["title"] for x in r], ["Blue Jar"])

    def test_TC_FR_15_poor_condition_and_overdue_inspection_raise_alerts(self):
        s = self.staff; a = self.make(s); aid = a["artifact_id"]
        self.assertTrue(self.patch(f"/api/artifacts/{aid}", s, {"condition": "poor"}).get_json()["alert"])
        b = self.make(s, inspection_date="2000-01-01")
        reasons = {x["artifact_id"]: x["reason"] for x in self.get("/api/alerts", s).get_json()}
        self.assertEqual(reasons[aid], "condition poor"); self.assertEqual(reasons[b["artifact_id"]], "inspection overdue")
        self.assertTrue(self.post(f"/api/artifacts/{aid}/condition-report", s, {"rating": "poor", "notes": "crack"}).get_json()["alert"])

    def test_TC_FR_16_FR_25_exhibition_ticket_types_and_slots(self):
        s = self.staff
        e = self.post("/api/exhibitions", s, {"title": "New", "gallery": "L2", "start_date": "2026-12-01", "end_date": "2026-11-01"})
        self.assertEqual(e.status_code, 400)                                            # end before start
        eid = self.post("/api/exhibitions", s, {"title": "New", "gallery": "L2", "start_date": "2026-12-01", "end_date": "2027-01-01"}).get_json()["exhibition_id"]
        self.assertEqual(self.post(f"/api/exhibitions/{eid}/ticket-types", s, {"name": "Adult", "price": 25}).status_code, 201)
        self.assertEqual(self.post(f"/api/exhibitions/{eid}/ticket-types", s, {"name": "Adult", "price": 25}).status_code, 400)   # unique name
        self.assertEqual(self.post(f"/api/exhibitions/{eid}/slots", s, {"slot_date": "2026-12-02", "start_time": "10:00", "end_time": "11:00", "capacity": 0}).status_code, 400)
        self.assertEqual(self.post(f"/api/exhibitions/{eid}/slots", s, {"slot_date": "2026-12-02", "start_time": "10:00", "end_time": "11:00", "capacity": 30}).status_code, 201)
        a = self.make(s)
        self.assertEqual(self.post(f"/api/exhibitions/{eid}/items", s, {"artifact_id": a["artifact_id"], "display_start_date": "2026-12-01", "display_end_date": "2027-01-01"}).status_code, 201)
        self.assertEqual(len(self.get(f"/api/exhibitions/{eid}/items").get_json()), 1)
