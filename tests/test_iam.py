import unittest
from datetime import timedelta
from .base import Base
from smms.security import totp

class TestIAM(Base):
    def test_TC_FR_01_registration_requires_email_verification(self):
        r = self.c.post("/api/auth/register", json={"email": "new@example.com", "password": self.PW, "display_name": "New"})
        self.assertEqual(r.status_code, 201)
        # not active before the link is opened
        self.assertEqual(self.c.post("/api/auth/login", json={"email": "new@example.com", "password": self.PW}).status_code, 403)
        self.assertEqual(self.c.post("/api/auth/verify", json={"token": r.get_json()["verification_token"]}).status_code, 200)
        self.assertEqual(self.c.post("/api/auth/login", json={"email": "new@example.com", "password": self.PW}).status_code, 200)

    def test_TC_FR_01_rejects_weak_password_and_duplicate_email(self):
        bad = self.c.post("/api/auth/register", json={"email": "a@b.com", "password": "short", "display_name": "x"})
        self.assertEqual(bad.status_code, 400)                                           # NFR-15
        self.assertEqual(self.c.post("/api/auth/register", json={"email": "visitor@smms.example", "password": self.PW, "display_name": "x"}).status_code, 409)

    def test_TC_FR_02_wrong_password_rejected_and_audited(self):
        r = self.c.post("/api/auth/login", json={"email": "visitor@smms.example", "password": "Wrong1234"})
        self.assertEqual(r.status_code, 401)
        self.assertTrue(self.sql("SELECT 1 FROM audit_log WHERE event_type='failedLogin'"))

    def test_TC_NFR_16_lock_after_five_failures_for_15_minutes(self):
        for _ in range(5): self.c.post("/api/auth/login", json={"email": "visitor@smms.example", "password": "Wrong1234"})
        ok = {"email": "visitor@smms.example", "password": self.PW}
        self.assertEqual(self.c.post("/api/auth/login", json=ok).status_code, 423)      # locked even with the right password
        self.clock.advance(minutes=16)
        self.assertEqual(self.c.post("/api/auth/login", json=ok).status_code, 200)

    def test_TC_FR_03_mfa_required_for_staff(self):
        body = {"email": "staff@smms.example", "password": self.PW}
        self.assertTrue(self.c.post("/api/auth/login", json=body).get_json()["mfa_required"])
        body["otp"] = "000000"
        self.assertEqual(self.c.post("/api/auth/login", json=body).status_code, 401)
        body["otp"] = totp(self.secrets["staff@smms.example"])
        self.assertEqual(self.c.post("/api/auth/login", json=body).status_code, 200)

    def test_TC_NFR_16_session_expiry_15_staff_30_visitor(self):
        st, vt = self.staff, self.visitor
        self.clock.advance(minutes=16)
        self.assertEqual(self.get("/api/alerts", st).status_code, 401)                  # staff expired
        self.assertEqual(self.get("/api/me", vt).status_code, 200)                      # visitor still valid
        self.clock.advance(minutes=15)
        self.assertEqual(self.get("/api/me", vt).status_code, 401)

    def test_TC_NFR_17_rbac_every_role_pair(self):
        v, s, m, a = self.visitor, self.staff, self.manager, self.admin
        checks = [("/api/artifacts", {"Staff": 200, "Manager": 200, "Visitor": 403, "ITAdmin": 403}),
                  ("/api/analytics/summary", {"Manager": 200, "Staff": 403, "Visitor": 403, "ITAdmin": 403}),
                  ("/api/audit", {"ITAdmin": 200, "Staff": 403, "Manager": 403, "Visitor": 403}),
                  ("/api/admin/accounts", {"ITAdmin": 200, "Staff": 403, "Manager": 403, "Visitor": 403}),
                  ("/api/recommendations", {"Visitor": 200, "Staff": 403, "Manager": 403, "ITAdmin": 403})]
        toks = {"Visitor": v, "Staff": s, "Manager": m, "ITAdmin": a}
        for url, exp in checks:
            for role, code in exp.items():
                self.assertEqual(self.get(url, toks[role]).status_code, code, f"{url} as {role}")
        self.assertEqual(self.get("/api/audit").status_code, 401)                       # no token

    def test_TC_FR_05_password_reset_single_use_30_minutes(self):
        r = self.c.post("/api/auth/password-reset", json={"email": "visitor@smms.example"}).get_json()
        tok = r["reset_token"]
        self.assertEqual(self.c.post("/api/auth/password-reset/confirm", json={"token": tok, "password": "NewPass123"}).status_code, 200)
        self.assertEqual(self.c.post("/api/auth/password-reset/confirm", json={"token": tok, "password": "Other12345"}).status_code, 400)   # single use
        tok2 = self.c.post("/api/auth/password-reset", json={"email": "visitor@smms.example"}).get_json()["reset_token"]
        self.clock.advance(minutes=31)
        self.assertEqual(self.c.post("/api/auth/password-reset/confirm", json={"token": tok2, "password": "Another123"}).status_code, 400)  # expired
        self.assertNotIn("reset_token", self.c.post("/api/auth/password-reset", json={"email": "nobody@x.com"}).get_json())

    def test_TC_FR_06_FR_07_profile_consent_and_deletion(self):
        v = self.visitor
        self.assertEqual(self.patch("/api/me", v, {"preferred_language": "AR", "text_size": "large", "mobile_number": "+9715000", "interests": ["Textiles"]}).status_code, 200)
        me = self.get("/api/me", v).get_json()
        self.assertEqual(me["profile"]["preferred_language"], "AR"); self.assertEqual(me["interests"], ["Textiles"])
        self.assertNotEqual(self.sql("SELECT mobile_number FROM visitor WHERE visitor_id=?", (me["account_id"],))[0]["mobile_number"], "+9715000")  # encrypted at rest
        self.patch("/api/me", v, {"consent_personalisation": False})
        self.assertTrue(self.sql("SELECT consent_withdrawn_at FROM visitor")[0]["consent_withdrawn_at"])
        self.assertEqual(self.delete("/api/me", v).status_code, 200)
        self.assertEqual(self.sql("SELECT display_name,mobile_number FROM visitor")[0]["display_name"], "Deleted visitor")

    def test_TC_FR_42_admin_creates_and_deactivates_accounts(self):
        a = self.admin
        r = self.post("/api/admin/accounts", a, {"email": "s2@smms.example", "password": self.PW, "role": "Staff", "full_name": "S2"})
        self.assertEqual(r.status_code, 201); sec = r.get_json()["mfa_secret"]
        self.secrets["s2@smms.example"] = sec
        self.login("s2@smms.example")
        aid = r.get_json()["account_id"]
        self.assertEqual(self.patch(f"/api/admin/accounts/{aid}", a, {"role": "Manager"}).status_code, 200)
        self.patch(f"/api/admin/accounts/{aid}", a, {"is_active": False})
        body = {"email": "s2@smms.example", "password": self.PW, "otp": totp(sec)}
        self.assertEqual(self.c.post("/api/auth/login", json=body).status_code, 403)
        self.assertTrue(self.sql("SELECT 1 FROM audit_log WHERE event_type='roleChange'"))
        self.assertEqual(self.post("/api/admin/accounts", a, {"email": "x@x.com", "password": self.PW, "role": "Visitor"}).status_code, 400)

    # ---- regression tests added in the review
    def test_TC_FR_42_deactivated_account_token_stops_working_immediately(self):
        a, st = self.admin, self.staff
        self.assertEqual(self.get("/api/alerts", st).status_code, 200)
        sid = self.sql("SELECT account_id FROM account WHERE email='staff@smms.example'")[0]["account_id"]
        self.patch(f"/api/admin/accounts/{sid}", a, {"is_active": False})
        self.assertEqual(self.get("/api/alerts", st).status_code, 401)

    def test_TC_FR_42_role_change_of_staff_with_artifacts_and_takes_effect_at_once(self):
        a, st = self.admin, self.staff
        sid = self.sql("SELECT account_id FROM account WHERE email='staff@smms.example'")[0]["account_id"]
        self.assertGreater(len(self.sql("SELECT 1 FROM artifact WHERE created_by=?", (sid,))), 0)     # staff row is referenced
        self.assertEqual(self.patch(f"/api/admin/accounts/{sid}", a, {"role": "Manager"}).status_code, 200)
        self.assertEqual(self.post("/api/categories", st, {"name": "NewCat"}).status_code, 403)        # old Staff token no longer allowed
        self.assertEqual(self.patch(f"/api/admin/accounts/{sid}", a, {"role": "Staff"}).status_code, 200)

    @unittest.skipUnless(hasattr(__import__('time'), 'tzset'), 'time.tzset is not available on Windows')
    def test_TC_NFR_16_session_expiry_is_independent_of_server_time_zone(self):
        import os, time
        old = os.environ.get("TZ")
        try:
            for tz in ("Asia/Dubai", "America/New_York", "UTC"):
                os.environ["TZ"] = tz; time.tzset()
                st = self.staff; self.clock.advance(minutes=16)
                self.assertEqual(self.get("/api/alerts", st).status_code, 401, tz)
                self.clock.advance(minutes=-16)
        finally:
            if old is None: os.environ.pop("TZ", None)
            else: os.environ["TZ"] = old
            time.tzset()
