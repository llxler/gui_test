"""Durable, process-safe USD reservations. Unknown charges remain reserved."""
from contextlib import contextmanager
from decimal import Decimal, ROUND_CEILING
from pathlib import Path
import json
import sqlite3
import time
import uuid


class BudgetStop(RuntimeError):
    pass


def micros(value):
    value = Decimal(str(value))
    if not value.is_finite() or value < 0:
        raise ValueError("Cost must be finite and nonnegative")
    return int((value * 1_000_000).to_integral_value(rounding=ROUND_CEILING))


class Ledger:
    def __init__(self, path, limit=10, stop=9):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS policy (id INTEGER PRIMARY KEY CHECK(id=1), cap INTEGER, stop INTEGER, halted INTEGER DEFAULT 0)")
            db.execute("INSERT OR IGNORE INTO policy(id,cap,stop) VALUES(1,?,?)", (min(micros(limit), 10_000_000), min(micros(stop), 9_000_000)))
            # A restarted process may tighten, never raise, a persisted limit.
            db.execute("UPDATE policy SET cap=min(cap,?),stop=min(stop,?) WHERE id=1", (micros(limit), micros(stop)))
            db.execute("""CREATE TABLE IF NOT EXISTS calls (
                id TEXT PRIMARY KEY, purpose TEXT, model TEXT, status TEXT,
                reserved INTEGER, actual INTEGER, created REAL, duration REAL,
                generation_id TEXT, usage TEXT, error TEXT)""")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        try:
            with db:
                yield db
        finally:
            db.close()

    def reserve(self, amount, purpose, model):
        reserve = micros(amount)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            cap, stop, halted = db.execute("SELECT cap,stop,halted FROM policy WHERE id=1").fetchone()
            exposure = db.execute("SELECT COALESCE(SUM(COALESCE(actual,reserved)),0) FROM calls").fetchone()[0]
            if halted or exposure + reserve > min(cap, stop):
                raise BudgetStop(f"Budget stopped: exposure=${exposure/1e6:.6f}, requested reserve=${reserve/1e6:.6f}, stop=${stop/1e6:.2f}")
            call_id = uuid.uuid4().hex
            db.execute("INSERT INTO calls(id,purpose,model,status,reserved,created) VALUES(?,?,?,'reserved',?,?)",
                       (call_id, purpose, model, reserve, time.time()))
        return call_id

    def settle(self, call_id, cost, duration=0, generation_id=None, usage=None):
        actual = micros(cost)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT reserved,actual FROM calls WHERE id=?", (call_id,)).fetchone()
            if row is None or row[1] is not None:
                raise ValueError("Unknown or already settled reservation")
            db.execute("UPDATE calls SET actual=?,status='settled',duration=?,generation_id=?,usage=? WHERE id=?",
                       (actual, duration, generation_id, json.dumps(usage or {}), call_id))
            if actual > row[0]:
                db.execute("UPDATE policy SET halted=1 WHERE id=1")
                # Commit the charge before surfacing the breach to the caller.
                breached = True
            else:
                breached = False
        if breached:
            raise BudgetStop("Provider charge exceeded reservation; ledger halted")

    def uncertain(self, call_id, error):
        with self.connect() as db:
            db.execute("UPDATE calls SET status='uncertain',error=? WHERE id=? AND actual IS NULL", (str(error), call_id))

    def summary(self):
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            rows = [dict(r) for r in db.execute("SELECT * FROM calls ORDER BY created")]
            policy = dict(db.execute("SELECT * FROM policy WHERE id=1").fetchone())
        return {"actual_usd": sum(r["actual"] or 0 for r in rows)/1e6,
                "exposure_usd": sum(r["actual"] if r["actual"] is not None else r["reserved"] for r in rows)/1e6,
                "library_usd": sum(r["actual"] or 0 for r in rows if r["purpose"].startswith("library"))/1e6,
                "unsettled_calls": sum(r["actual"] is None for r in rows), "policy": policy, "calls": rows}
