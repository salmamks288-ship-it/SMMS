"""Adds extra published knowledge-base entries to smms.db so the chatbot can answer more visitor questions.
Run from the project folder:  python tools/add_kb.py     (safe to run twice: existing questions are skipped)
Edit the FACILITY section below so it matches your real museum before running."""
import os, sqlite3, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from smms.config import Config

# ---- EDIT THESE to match your museum / report -------------------------------------------------
ADDRESS = "Smart Museum, Abu Dhabi, United Arab Emirates"
HELPDESK = Config.HELPDESK
# -----------------------------------------------------------------------------------------------

con = sqlite3.connect(Config.DATABASE); con.row_factory = sqlite3.Row
staff = con.execute("SELECT account_id FROM account WHERE email='staff@smms.example'").fetchone()
staff_id = staff["account_id"] if staff else None
ex = con.execute("SELECT title, gallery, start_date, end_date FROM exhibition ORDER BY exhibition_id LIMIT 1").fetchone()
arts = con.execute("SELECT title, location FROM artifact WHERE status='onDisplay' ORDER BY location, title").fetchall()
galleries = {}
for a in arts: galleries.setdefault(a["location"], []).append(a["title"])

E = []   # (question, answer, source)
if ex:
    E += [("When does the exhibition start?", f"The {ex['title']} exhibition ({ex['gallery']}) runs from {ex['start_date']} to {ex['end_date']}.", "Exhibitions"),
          ("When does the exhibit end?", f"The {ex['title']} exhibition ends on {ex['end_date']}.", "Exhibitions"),
          ("What exhibitions are on now?", f"Currently on: {ex['title']} in {ex['gallery']}, until {ex['end_date']}. You can book a time slot in the Exhibitions tab.", "Exhibitions")]
if galleries:
    E.append(("Where is each exhibit? Which gallery has which objects?", " ".join(f"{g}: {', '.join(t)}." for g, t in galleries.items()), "Galleries"))
E += [
 ("Where is the museum? What is the address? How do I get there?", f"{ADDRESS}. For directions, contact the help desk: {HELPDESK}", "Visitor info > Location"),
 ("How do I book a ticket?", "Log in, open Exhibitions, choose an exhibition, date, time slot and ticket type, then pay. Your seats are held for 10 minutes while you pay, and you receive a digital QR ticket.", "Tickets > Booking"),
 ("What time slots are available?", "Time slots are 10:00-11:00, 11:00-12:00 and 13:00-14:00. Each slot shows how many seats remain.", "Tickets > Time slots"),
 ("Can I cancel or change my booking?", "Yes. You can cancel or reschedule from My bookings up to 24 hours before your slot. Cancelled seats are released for other visitors.", "Tickets > Cancellation"),
 ("What payment methods are accepted?", "Online card payment through our payment gateway. The museum never sees or stores your card details.", "Tickets > Payment"),
 ("What if I am late for my time slot?", "There is a grace period of 15 minutes after your slot starts. After that, please contact the help desk or reschedule.", "Tickets > Entry"),
 ("How do I enter with my ticket?", "Show the QR code of your digital ticket at the entrance. Staff scan it to validate your entry. Each ticket works once.", "Tickets > Entry"),
 ("Is there a 3D or AR experience?", "Yes. Open Exhibit / AR to view an interactive 3D model of an exhibit. On a phone or tablet you can tap View in AR to place it in your space.", "Exhibits > AR"),
 ("Which languages does the museum support?", "The website and chatbot work in English and Arabic.", "Visitor info > Languages"),
 ("How can I contact the museum or help desk?", f"{HELPDESK}", "Visitor info > Contact"),
 ("Do you recommend exhibits for me?", "Yes. Open Recommendations. Based on your interests you get suggested exhibits with reasons. You can turn personalisation off in your profile.", "Exhibits > Recommendations"),
 # --- Demo facility information: EDIT to match your museum --------------------------------------
 ("Is there parking?", "Yes, visitor parking is available at the museum, including accessible parking bays near the entrance.", "Visitor info > Parking"),
 ("Is there a cafe or restaurant?", "Yes, a cafe on the ground floor serves drinks, snacks and light meals during opening hours.", "Visitor info > Facilities"),
 ("Is there a gift shop?", "Yes, the museum shop near the exit sells books, replicas and souvenirs during opening hours.", "Visitor info > Facilities"),
 ("Where are the restrooms?", "Restrooms are on every floor, next to the lifts. Accessible restrooms are available on all floors.", "Visitor info > Facilities"),
 ("Is there a prayer room?", "Yes, a prayer room is available on the ground floor. Ask at the information desk for directions.", "Visitor info > Facilities"),
 ("Are there lockers or a cloakroom?", "Free lockers are available near the entrance for bags and coats.", "Visitor info > Facilities"),
 ("Is the museum suitable for children and families?", "Yes. Children are welcome and child tickets cost 15 AED. Strollers are allowed in all galleries.", "Visitor info > Families"),
 ("Do you offer guided tours or group visits?", f"Guided tours and group visits can be arranged in advance. Please contact the help desk: {HELPDESK}", "Visitor info > Groups"),
 ("Can I bring food or drinks into the galleries?", "Food and drinks are not allowed in the galleries. Please use the cafe.", "Visitor info > Rules"),
 ("Is there a lost and found?", f"Yes. Please ask at the information desk or contact the help desk: {HELPDESK}", "Visitor info > Lost property"),
]
added = 0
for qn, an, src in E:
    if con.execute("SELECT 1 FROM knowledge_entry WHERE question=?", (qn,)).fetchone(): continue
    con.execute("INSERT INTO knowledge_entry(question,answer,language,status,source_page,updated_by,updated_at) VALUES (?,?,?,'published',?,?,datetime('now'))", (qn, an, "EN", src, staff_id))
    added += 1
con.commit(); print(f"Added {added} knowledge entries ({len(E) - added} already existed).")
