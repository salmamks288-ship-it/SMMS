import os
os.environ["GROQ_API_KEY"] = ""
os.environ["ANTHROPIC_API_KEY"] = ""
import os, tempfile, unittest
from datetime import datetime, date, time, timedelta
from smms.app import create_app
from smms.seed import seed
from smms.security import totp

class Clock:
    # Fixed start (08:00 today) so results never depend on the time of day or the machine's time zone.
    def __init__(self): self.t = datetime.combine(date.today(), time(8, 0))
    def __call__(self): return self.t
    def advance(self, **kw): self.t += timedelta(**kw)

class Base(unittest.TestCase):
    PW = "Passw0rd1"
    def setUp(self):
        self.fd, self.path = tempfile.mkstemp(suffix=".db"); os.close(self.fd); os.remove(self.path)
        self.clock = Clock()
        self.app = create_app({"DATABASE": self.path, "NOW": self.clock, "TESTING": True, "MUSEUM_UTC_OFFSET_HOURS": 0})
        self.secrets = seed(self.app)
        self.c = self.app.test_client()
        from smms.services import integration
        integration.STATE.update(payment_up=True, notify_up=True, llm_up=True, outbox=[])
        self.integration = integration
    def tearDown(self):
        if os.path.exists(self.path): os.remove(self.path)
    # ---- helpers
    def post(self, url, tok=None, json=None, client=None):
        return (client or self.c).post(url, json=json or {}, headers=self.h(tok))
    def get(self, url, tok=None, client=None): return (client or self.c).get(url, headers=self.h(tok))
    def patch(self, url, tok=None, json=None): return self.c.patch(url, json=json or {}, headers=self.h(tok))
    def delete(self, url, tok=None): return self.c.delete(url, headers=self.h(tok))
    @staticmethod
    def h(tok): return {"Authorization": f"Bearer {tok}"} if tok else {}
    def login(self, email, otp=True):
        body = {"email": email, "password": self.PW}
        sec = self.secrets.get(email)
        if sec and otp: body["otp"] = totp(sec)
        r = self.c.post("/api/auth/login", json=body)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        return r.get_json()["token"]
    @property
    def visitor(self): return self.login("visitor@smms.example")
    @property
    def staff(self): return self.login("staff@smms.example")
    @property
    def manager(self): return self.login("manager@smms.example")
    @property
    def admin(self): return self.login("admin@smms.example")
    def new_visitor(self, email="v2@example.com", consent=True):
        r = self.c.post("/api/auth/register", json={"email": email, "password": self.PW, "display_name": "Test", "consent_personalisation": consent})
        self.assertEqual(r.status_code, 201)
        self.c.post("/api/auth/verify", json={"token": r.get_json()["verification_token"]})
        r = self.c.post("/api/auth/login", json={"email": email, "password": self.PW}); return r.get_json()["token"]
    def slot(self, i=0, exhibition=1):
        with self.app.app_context():
            from smms.db import q
            return q("SELECT * FROM time_slot WHERE exhibition_id=? ORDER BY slot_date,start_time", (exhibition,))[i]
    def book(self, tok, slot_id, qty=1, tt=1):
        return self.post("/api/bookings", tok, {"slot_id": slot_id, "ticket_type_id": tt, "quantity": qty})
    def book_and_pay(self, tok, slot_id, qty=1):
        b = self.book(tok, slot_id, qty); self.assertEqual(b.status_code, 201, b.get_data(as_text=True))
        p = self.post(f"/api/bookings/{b.get_json()['booking_id']}/pay", tok, {"gateway_token": "tok_success"})
        self.assertEqual(p.status_code, 200, p.get_data(as_text=True)); return b.get_json(), p.get_json()
    def sql(self, query, args=()):
        with self.app.app_context():
            from smms.db import q
            return q(query, args)
