import os, sqlite3
from contextlib import contextmanager
from flask import g, current_app

SCHEMA = os.path.join(os.path.dirname(__file__), "schema.sql")

def connect(path):
    con = sqlite3.connect(path, isolation_level=None, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con

def get_db():
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE"])
    return g.db

def close_db(exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()

def init_db(path):
    con = connect(path)
    with open(SCHEMA, encoding="utf-8") as f:
        con.executescript(f.read())
    con.close()

def q(sql, args=(), one=False):
    cur = get_db().execute(sql, args)
    rows = [dict(r) for r in cur.fetchall()]
    return (rows[0] if rows else None) if one else rows

def x(sql, args=()):
    cur = get_db().execute(sql, args)
    return cur.lastrowid

@contextmanager
def tx():
    """Write transaction. BEGIN IMMEDIATE takes the write lock up front, which plays the
    role of SELECT ... FOR UPDATE on PostgreSQL (capacity control, FR-19 / NFR-12)."""
    db = get_db()
    db.execute("BEGIN IMMEDIATE")
    try:
        yield db
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise

def local_now():
    """Museum wall-clock time (naive). Business rules that compare with slot dates/times use this, never raw UTC."""
    from datetime import timedelta
    return current_app.config["NOW"]() + timedelta(hours=current_app.config["MUSEUM_UTC_OFFSET_HOURS"])

def iso(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")
