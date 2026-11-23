"""Generates smms/schema.sql from the Phase 4 table definitions (tools/phase4_db.py)."""
import re, sys
sys.path.insert(0,"tools")
from phase4_db import T
OVR={("time_slot","confirmed_seats"):"CHECK (confirmed_seats >= 0 AND confirmed_seats <= capacity)"}
EXTRA={"time_slot":["UNIQUE (exhibition_id, slot_date, start_time)"],"ticket_type":["UNIQUE (exhibition_id, name)"],"feedback":["UNIQUE (visitor_id, artifact_id)"]}
def col_sql(tb,c,ty,fl,single_pk_int):
    parts=[c]
    pk=("PK" in (fl.split("FK")[0] if "FK" in fl else fl))
    fk=re.search(r"FK→(\w+)",fl)
    composite=sum(1 for _,_,f in tb["cols"] if "PK" in (f.split("FK")[0] if "FK" in f else f))>1
    if pk and not composite and not fk and ty=="INT": return f"{c} INTEGER PRIMARY KEY AUTOINCREMENT"
    parts.append(ty)
    if pk and not composite: parts.append("PRIMARY KEY")
    if "NN" in fl and not pk: parts.append("NOT NULL")
    if "UQ" in fl: parts.append("UNIQUE")
    m=re.search(r"DEFAULT ('[^']*'|\w+)",fl)
    if m: parts.append("DEFAULT "+m.group(1))
    if (tb["name"],c) in OVR: parts.append(OVR[(tb["name"],c)])
    else:
        m=re.search(r"CHECK IN \(([^)]*)\)",fl)
        if m: parts.append("CHECK (%s IN (%s))"%(c,", ".join("'%s'"%v.strip() for v in m.group(1).split(","))))
        else:
            m=re.search(r"CHECK (.+)$",fl)
            if m:
                e=m.group(1).replace("≥",">=").replace("≤","<=").strip()
                e=re.sub(r"DEFAULT .*","",e)
                parts.append(f"CHECK ({e})")
    if fk and not (pk and composite): parts.append(f"REFERENCES {fk.group(1)}")
    return " ".join(parts)
out=["-- SMMS relational schema (generated from Phase 4 data design; portable SQL, runs on SQLite and PostgreSQL)","PRAGMA foreign_keys = ON;",""]
for tb in T:
    lines=[]
    for c,ty,fl in tb["cols"]: lines.append("  "+col_sql(tb,c,ty,fl,True))
    pks=[c for c,_,f in tb["cols"] if "PK" in (f.split("FK")[0] if "FK" in f else f)]
    if len(pks)>1:
        lines.append(f"  PRIMARY KEY ({', '.join(pks)})")
        for c,_,f in tb["cols"]:
            m=re.search(r"FK→(\w+)",f)
            if m and c in pks: lines.append(f"  FOREIGN KEY ({c}) REFERENCES {m.group(1)}")
    for e in EXTRA.get(tb["name"],[]): lines.append("  "+e)
    out.append(f"CREATE TABLE IF NOT EXISTS {tb['name']} (\n"+",\n".join(lines)+"\n);\n")
out.append("""-- extra indexes (Phase 4, Section 4.3)
CREATE UNIQUE INDEX IF NOT EXISTS ux_entry_valid_once ON entry_validation(ticket_id) WHERE result = 'valid';
CREATE INDEX IF NOT EXISTS ix_artifact_search ON artifact(category_id, status, location);
CREATE INDEX IF NOT EXISTS ix_artifact_title ON artifact(title);
CREATE INDEX IF NOT EXISTS ix_slot_exh_date ON time_slot(exhibition_id, slot_date);
CREATE INDEX IF NOT EXISTS ix_booking_visitor ON booking(visitor_id, created_at);
CREATE INDEX IF NOT EXISTS ix_ticket_token ON digital_ticket(token);
CREATE INDEX IF NOT EXISTS ix_reco_visitor ON recommendation(visitor_id, shown_at);
CREATE INDEX IF NOT EXISTS ix_kb_status ON knowledge_entry(status, language);
CREATE INDEX IF NOT EXISTS ix_audit_time ON audit_log(event_time, event_type);
CREATE INDEX IF NOT EXISTS ix_hold_slot ON seat_hold(slot_id, status);
""")
open("smms/schema.sql","w").write("\n".join(out))
print("ok")
