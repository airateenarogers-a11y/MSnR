from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from .clock import iso, utcnow
from .domain import Signal


def encode(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str, allow_nan=False)


TRANSITIONS = {
    "Detected": {"Validated", "Invalidated"},
    "Validated": {"Published", "Expired", "Invalidated"},
    "Published": {"Triggered", "Expired", "Invalidated"},
    "Triggered": {"Active", "Closed", "Invalidated"},
    "Active": {"Closed"},
    "Closed": set(),
    "Expired": set(),
    "Invalidated": set(),
}


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript((Path(__file__).parent / "migrations/001_initial.sql").read_text())
            db.execute("INSERT OR IGNORE INTO schema_versions VALUES(1,?)", (iso(utcnow()),))

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA busy_timeout=10000")
        return db

    @contextmanager
    def transaction(self):
        db = self.connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def event(self, kind: str, entity: str, payload: dict, at: datetime | None = None, db=None):
        if db is None:
            with self.transaction() as connection:
                return self.event(kind, entity, payload, at, connection)
        row = db.execute("SELECT hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
        previous = row[0] if row else "0" * 64
        event_id, timestamp, data = str(uuid4()), iso(at or utcnow()), encode(payload)
        digest = hashlib.sha256(
            encode([previous, event_id, kind, entity, timestamp, data]).encode()
        ).hexdigest()
        db.execute(
            "INSERT INTO events(id,kind,entity_id,at,payload,previous_hash,hash) VALUES(?,?,?,?,?,?,?)",
            (event_id, kind, entity, timestamp, data, previous, digest),
        )
        return event_id

    def verify_chain(self) -> bool:
        previous = "0" * 64
        for e in self.rows("SELECT * FROM events ORDER BY seq"):
            digest = hashlib.sha256(
                encode([previous, e["id"], e["kind"], e["entity_id"], e["at"], e["payload"]]).encode()
            ).hexdigest()
            if e["previous_hash"] != previous or e["hash"] != digest:
                return False
            previous = digest
        return True

    def rows(self, sql: str, args=()) -> list[dict]:
        db = self.connect()
        try:
            return [dict(r) for r in db.execute(sql, args).fetchall()]
        finally:
            db.close()

    def state(self, key, default=None, db=None):
        if db is not None:
            row = db.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
        else:
            rows = self.rows("SELECT value FROM state WHERE key=?", (key,))
            row = rows[0] if rows else None
        return json.loads(row["value"]) if row else default

    def set_state(self, key, value, db=None):
        if db is None:
            with self.transaction() as connection:
                self.set_state(key, value, connection)
            return
        db.execute(
            "INSERT INTO state VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, encode(value)),
        )

    def add_signal(self, signal: Signal) -> bool:
        with self.transaction() as db:
            inserted = db.execute(
                "INSERT OR IGNORE INTO signals VALUES(?,?,?,?,?,?,NULL)",
                (
                    signal.id,
                    signal.fingerprint,
                    signal.symbol,
                    "Detected",
                    iso(signal.created_at),
                    signal.model_dump_json(),
                ),
            ).rowcount
            if not inserted:
                return False
            self.event("signal.detected", signal.id, signal.model_dump(mode="json"), signal.created_at, db)
            self.transition(
                signal.id, "Validated", {"reason": "All mandatory rules passed"}, signal.created_at, db
            )
            return True

    def transition(self, signal_id, target, detail, at=None, db=None):
        if db is None:
            with self.transaction() as connection:
                return self.transition(signal_id, target, detail, at, connection)
        row = db.execute("SELECT status FROM signals WHERE id=?", (signal_id,)).fetchone()
        if row is None:
            raise KeyError(signal_id)
        if row["status"] == target:
            return False
        if target not in TRANSITIONS[row["status"]]:
            raise ValueError(f"Invalid lifecycle transition {row['status']} → {target}")
        db.execute("UPDATE signals SET status=? WHERE id=?", (target, signal_id))
        self.event(
            "signal." + target.lower(), signal_id, {"from": row["status"], "to": target, **detail}, at, db
        )
        if (
            target in ("Expired", "Invalidated", "Closed")
            or target == "Triggered"
            and detail.get("executed") is False
        ):
            self.enqueue(
                "lifecycle:" + signal_id + ":" + target,
                {"type": "signal status", "signal_id": signal_id, "status": target, **detail},
                at,
                db,
            )
        return True

    def enqueue(self, key, payload, at=None, db=None):
        if db is None:
            with self.transaction() as connection:
                return self.enqueue(key, payload, at, connection)
        return bool(
            db.execute(
                "INSERT OR IGNORE INTO outbox(id,event_key,status,available_at,payload) VALUES(?,?,'pending',?,?)",
                (str(uuid4()), key, iso(at or utcnow()), encode(payload)),
            ).rowcount
        )

    def backup(self, path: Path):
        if path.resolve() == Path(self.path).resolve():
            raise ValueError("Backup must have a distinct path")
        path.parent.mkdir(parents=True, exist_ok=True)
        source = self.connect()
        target = sqlite3.connect(path)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
