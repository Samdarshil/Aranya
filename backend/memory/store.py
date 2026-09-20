"""
Farm Memory — persistent store, spec section 9.

IMPLEMENTATION STATUS: this is a real, working sqlite3-backed store — not a
stub — chosen deliberately as the first implementation because it runs with
zero extra dependencies. The full entity list from the spec (SoilTest,
IrrigationEvent, MarketPrice, Harvest, ...) is NOT all modelled here yet;
see docs/STATUS.md. What IS modelled (Farmer, Farm, Field, Animal,
VisionScan, Recommendation, FarmEvent) is enough to support the full
vertical slice: photo -> evidence -> recommendation -> memory -> "what
happened last time in this field?".

Migration path: backend/memory/models_sqlalchemy.py defines the same
entities (plus the rest of the spec's list) as SQLAlchemy/Postgres models
for production use. FarmMemory here and the SQLAlchemy-backed version
should implement the same public methods so agents don't need to change
when the swap happens — see FarmMemoryProtocol below.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Protocol

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "aranya.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS farmers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    phone TEXT UNIQUE,
    email TEXT,
    preferred_language TEXT DEFAULT 'hi',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS farms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    farmer_id INTEGER NOT NULL REFERENCES farmers(id),
    name TEXT NOT NULL,
    location TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fields (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    farm_id INTEGER NOT NULL REFERENCES farms(id),
    field_ref TEXT NOT NULL,          -- farmer-facing identifier, e.g. "FIELD-01"
    crop_name TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(farm_id, field_ref)
);

CREATE TABLE IF NOT EXISTS animals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    farm_id INTEGER NOT NULL REFERENCES farms(id),
    animal_ref TEXT NOT NULL,         -- e.g. "COW-001"
    species TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(farm_id, animal_ref)
);

CREATE TABLE IF NOT EXISTS vision_scans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_type TEXT NOT NULL,       -- 'field' | 'animal'
    subject_id INTEGER NOT NULL,      -- fields.id or animals.id
    kind TEXT NOT NULL,               -- 'crop' | 'livestock'
    timestamp TEXT NOT NULL,
    status TEXT NOT NULL,             -- status/risk_level string
    score REAL NOT NULL,              -- affected_area_pct or risk_score
    confidence REAL NOT NULL,
    is_demo INTEGER NOT NULL DEFAULT 0,
    raw_metrics TEXT
);

CREATE TABLE IF NOT EXISTS recommendations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id INTEGER REFERENCES vision_scans(id),
    farm_id INTEGER NOT NULL REFERENCES farms(id),
    problem TEXT NOT NULL,
    severity TEXT NOT NULL,
    urgency TEXT NOT NULL,
    confidence REAL NOT NULL,
    recommended_action TEXT NOT NULL,
    reasoning TEXT NOT NULL,
    evidence TEXT NOT NULL,           -- JSON list
    escalate_to_expert INTEGER NOT NULL DEFAULT 0,
    escalation_reason TEXT,
    source_agent TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS farm_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    farm_id INTEGER NOT NULL REFERENCES farms(id),
    event_type TEXT NOT NULL,
    description TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS guardian_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    farm_id INTEGER NOT NULL REFERENCES farms(id),
    subject_type TEXT NOT NULL,       -- 'field' | 'animal' | 'farm'
    subject_id INTEGER NOT NULL,
    subject_ref TEXT NOT NULL,
    alert_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    urgency TEXT NOT NULL,
    priority INTEGER NOT NULL,
    recommendation_id INTEGER REFERENCES recommendations(id),
    problem TEXT NOT NULL,
    acknowledged_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor TEXT NOT NULL,              -- farmer id, agent name, or 'system'
    action TEXT NOT NULL,
    target_type TEXT,
    target_id TEXT,
    details TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS soil_tests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    field_id INTEGER NOT NULL REFERENCES fields(id),
    ph REAL,
    nitrogen_ppm REAL,
    phosphorus_ppm REAL,
    potassium_ppm REAL,
    source TEXT NOT NULL,              -- 'lab_report' | 'farmer_reported' | 'provider_api'
    tested_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS market_watches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    farm_id INTEGER NOT NULL REFERENCES farms(id),
    crop_name TEXT NOT NULL,
    market_name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(farm_id, crop_name, market_name)
);

CREATE TABLE IF NOT EXISTS market_prices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    crop_name TEXT NOT NULL,
    market_name TEXT NOT NULL,
    price_per_quintal REAL NOT NULL,
    provider TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS expert_consultations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    farm_id INTEGER NOT NULL REFERENCES farms(id),
    recommendation_id INTEGER REFERENCES recommendations(id),
    source_agent TEXT NOT NULL,
    problem TEXT NOT NULL,
    escalation_reason TEXT NOT NULL,
    severity TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',   -- 'pending' | 'resolved'
    expert_name TEXT,
    resolution_notes TEXT,
    requested_at TEXT NOT NULL,
    resolved_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    field_id INTEGER NOT NULL REFERENCES fields(id),
    crop_cycle_id INTEGER REFERENCES crop_cycles(id),
    category TEXT NOT NULL,           -- e.g. 'seed', 'fertilizer', 'labor', 'irrigation', 'pesticide', 'other'
    amount REAL NOT NULL,
    incurred_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    field_id INTEGER NOT NULL REFERENCES fields(id),
    crop_cycle_id INTEGER REFERENCES crop_cycles(id),
    quantity_kg REAL NOT NULL,
    price_per_kg REAL NOT NULL,
    sold_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS treatment_outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    farm_id INTEGER NOT NULL REFERENCES farms(id),
    recommendation_id INTEGER REFERENCES recommendations(id),
    source_agent TEXT NOT NULL,
    followed_advice INTEGER NOT NULL,   -- 0/1
    outcome TEXT NOT NULL,              -- 'improved' | 'no_change' | 'worsened'
    notes TEXT,
    recorded_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS crop_cycles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    field_id INTEGER NOT NULL REFERENCES fields(id),
    crop_name TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class FarmMemoryProtocol(Protocol):
    """Public contract agents depend on. Both the sqlite implementation
    (below) and the future Postgres/SQLAlchemy implementation must satisfy
    this, so swapping the backing store doesn't ripple into agent code."""

    def get_or_create_field(self, farm_id: int, field_ref: str, crop_name: str) -> int: ...
    def get_or_create_animal(self, farm_id: int, animal_ref: str, species: str) -> int: ...
    def save_vision_scan(self, **kwargs: Any) -> int: ...
    def get_field_history(self, field_id: int) -> list[dict[str, Any]]: ...
    def get_animal_history(self, animal_id: int) -> list[dict[str, Any]]: ...
    def get_animal_baseline(self, animal_id: int) -> dict[str, Any] | None: ...
    def save_recommendation(self, **kwargs: Any) -> int: ...
    def log_event(self, farm_id: int, event_type: str, description: str) -> int: ...
    def get_scan(self, scan_id: int) -> dict[str, Any] | None: ...
    def save_guardian_alert(self, **kwargs: Any) -> int: ...
    def get_latest_alert_for_subject(self, farm_id: int, subject_type: str, subject_id: int) -> dict[str, Any] | None: ...
    def get_active_alerts(self, farm_id: int) -> list[dict[str, Any]]: ...
    def get_alert(self, alert_id: int) -> dict[str, Any] | None: ...
    def acknowledge_alert(self, alert_id: int) -> None: ...
    def get_farm(self, farm_id: int) -> dict[str, Any] | None: ...
    def farmer_owns_farm(self, farmer_id: int, farm_id: int) -> bool: ...
    def log_audit(self, actor: str, action: str, **kwargs: Any) -> int: ...
    def save_soil_test(self, **kwargs: Any) -> int: ...
    def get_latest_soil_test(self, field_id: int) -> dict[str, Any] | None: ...
    def get_soil_test_history(self, field_id: int) -> list[dict[str, Any]]: ...
    def get_or_create_market_watch(self, farm_id: int, crop_name: str, market_name: str) -> int: ...
    def save_market_price(self, **kwargs: Any) -> int: ...
    def get_market_price_history(self, crop_name: str, market_name: str, limit: int = 30) -> list[dict[str, Any]]: ...
    def create_consultation_request(self, **kwargs: Any) -> int: ...
    def get_pending_consultations(self, farm_id: int) -> list[dict[str, Any]]: ...
    def get_consultation(self, consultation_id: int) -> dict[str, Any] | None: ...
    def resolve_consultation(self, consultation_id: int, expert_name: str, notes: str) -> None: ...
    def log_expense(self, field_id: int, category: str, amount: float, incurred_at: str | None = None) -> int: ...
    def get_field_expenses(self, field_id: int) -> list[dict[str, Any]]: ...
    def log_sale(self, field_id: int, quantity_kg: float, price_per_kg: float, sold_at: str | None = None) -> int: ...
    def get_field_sales(self, field_id: int) -> list[dict[str, Any]]: ...
    def get_field(self, field_id: int) -> dict[str, Any] | None: ...
    def get_active_crop_cycle(self, field_id: int) -> dict[str, Any] | None: ...
    def start_new_crop_cycle(self, field_id: int, crop_name: str) -> int: ...
    def get_active_cycle_expenses(self, field_id: int) -> list[dict[str, Any]]: ...
    def get_active_cycle_sales(self, field_id: int) -> list[dict[str, Any]]: ...
    def record_outcome(self, **kwargs: Any) -> int: ...
    def get_outcomes_for_agent(self, source_agent: str) -> list[dict[str, Any]]: ...
    def get_farm_outcomes(self, farm_id: int) -> list[dict[str, Any]]: ...


@dataclass
class FarmMemory:
    db_path: Path = DEFAULT_DB_PATH

    def __post_init__(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # -- Farmer / Farm ----------------------------------------------------
    def get_or_create_farmer(self, name: str, phone: str | None = None,
                              email: str | None = None, preferred_language: str = "hi") -> int:
        with self._connect() as conn:
            if phone:
                row = conn.execute("SELECT id, email FROM farmers WHERE phone = ?", (phone,)).fetchone()
                if row:
                    # Backfill email if the farmer now provides one and didn't before —
                    # never overwrite an existing email with a different one silently.
                    if email and not row["email"]:
                        conn.execute("UPDATE farmers SET email = ? WHERE id = ?", (email, row["id"]))
                    return row["id"]
            cur = conn.execute(
                "INSERT INTO farmers (name, phone, email, preferred_language, created_at) VALUES (?,?,?,?,?)",
                (name, phone, email, preferred_language, _now()),
            )
            return cur.lastrowid

    def get_farmer(self, farmer_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM farmers WHERE id = ?", (farmer_id,)).fetchone()
            return dict(row) if row else None

    def get_or_create_farm(self, farmer_id: int, name: str, location: str | None = None) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM farms WHERE farmer_id = ? AND name = ?", (farmer_id, name)
            ).fetchone()
            if row:
                return row["id"]
            cur = conn.execute(
                "INSERT INTO farms (farmer_id, name, location, created_at) VALUES (?,?,?,?)",
                (farmer_id, name, location, _now()),
            )
            return cur.lastrowid

    # -- Field / Animal -----------------------------------------------------
    def get_or_create_field(self, farm_id: int, field_ref: str, crop_name: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM fields WHERE farm_id = ? AND field_ref = ?", (farm_id, field_ref)
            ).fetchone()
            if row:
                return row["id"]
            cur = conn.execute(
                "INSERT INTO fields (farm_id, field_ref, crop_name, created_at) VALUES (?,?,?,?)",
                (farm_id, field_ref, crop_name, _now()),
            )
            return cur.lastrowid

    def get_or_create_animal(self, farm_id: int, animal_ref: str, species: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM animals WHERE farm_id = ? AND animal_ref = ?", (farm_id, animal_ref)
            ).fetchone()
            if row:
                return row["id"]
            cur = conn.execute(
                "INSERT INTO animals (farm_id, animal_ref, species, created_at) VALUES (?,?,?,?)",
                (farm_id, animal_ref, species, _now()),
            )
            return cur.lastrowid

    # -- Vision scans ---------------------------------------------------------
    def save_vision_scan(self, subject_type: str, subject_id: int, kind: str,
                          status: str, score: float, confidence: float,
                          raw_metrics: dict[str, Any], is_demo: bool = False) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO vision_scans
                   (subject_type, subject_id, kind, timestamp, status, score,
                    confidence, is_demo, raw_metrics)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (subject_type, subject_id, kind, _now(), status, score,
                 confidence, int(is_demo), json.dumps(raw_metrics)),
            )
            return cur.lastrowid

    def get_field_history(self, field_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM vision_scans WHERE subject_type='field' AND subject_id=?
                   ORDER BY timestamp ASC""",
                (field_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_animal_history(self, animal_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM vision_scans WHERE subject_type='animal' AND subject_id=?
                   ORDER BY timestamp ASC""",
                (animal_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_animal_baseline(self, animal_id: int) -> dict[str, Any] | None:
        """Mean of past biomarkers for this animal — ported logic from
        the pipeline's earlier baseline logic, adapted to the new schema."""
        history = self.get_animal_history(animal_id)
        if not history:
            return None
        parsed = [json.loads(h["raw_metrics"]) for h in history if h.get("raw_metrics")]
        if not parsed:
            return None
        hsv_vals = [p["coat_mean_hsv"] for p in parsed if p.get("coat_mean_hsv")]
        rough_vals = [p["coat_texture_roughness"] for p in parsed if p.get("coat_texture_roughness") is not None]
        area_vals = [p["body_region_area_pct"] for p in parsed if p.get("body_region_area_pct") is not None]
        baseline: dict[str, Any] = {}
        if hsv_vals:
            n = len(hsv_vals)
            baseline["coat_mean_hsv"] = [sum(v[i] for v in hsv_vals) / n for i in range(3)]
        if rough_vals:
            baseline["coat_texture_roughness"] = sum(rough_vals) / len(rough_vals)
        if area_vals:
            baseline["body_region_area_pct"] = sum(area_vals) / len(area_vals)
        return baseline or None

    # -- Recommendations ------------------------------------------------------
    def save_recommendation(self, scan_id: int | None, farm_id: int, problem: str,
                             severity: str, urgency: str, confidence: float,
                             recommended_action: str, reasoning: str,
                             evidence: list[dict[str, Any]], source_agent: str,
                             escalate_to_expert: bool = False,
                             escalation_reason: str | None = None) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO recommendations
                   (scan_id, farm_id, problem, severity, urgency, confidence,
                    recommended_action, reasoning, evidence, escalate_to_expert,
                    escalation_reason, source_agent, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (scan_id, farm_id, problem, severity, urgency, confidence,
                 recommended_action, reasoning, json.dumps(evidence),
                 int(escalate_to_expert), escalation_reason, source_agent, _now()),
            )
            return cur.lastrowid

    def get_farm_recommendations(self, farm_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM recommendations WHERE farm_id = ? ORDER BY created_at DESC",
                (farm_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    # -- Timeline ---------------------------------------------------------
    def log_event(self, farm_id: int, event_type: str, description: str) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO farm_events (farm_id, event_type, description, created_at) VALUES (?,?,?,?)",
                (farm_id, event_type, description, _now()),
            )
            return cur.lastrowid

    def get_farm_timeline(self, farm_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM farm_events WHERE farm_id = ? ORDER BY created_at DESC",
                (farm_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    # -- Scan lookup (used by Guardian to resolve a recommendation's subject) --
    def get_scan(self, scan_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM vision_scans WHERE id = ?", (scan_id,)).fetchone()
            return dict(row) if row else None

    # -- Guardian alerts ----------------------------------------------------
    def save_guardian_alert(self, farm_id: int, subject_type: str, subject_id: int,
                             subject_ref: str, alert_type: str, severity: str, urgency: str,
                             priority: int, problem: str, recommendation_id: int | None = None) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO guardian_alerts
                   (farm_id, subject_type, subject_id, subject_ref, alert_type, severity,
                    urgency, priority, recommendation_id, problem, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (farm_id, subject_type, subject_id, subject_ref, alert_type, severity,
                 urgency, priority, recommendation_id, problem, _now()),
            )
            return cur.lastrowid

    def get_latest_alert_for_subject(self, farm_id: int, subject_type: str,
                                      subject_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """SELECT * FROM guardian_alerts
                   WHERE farm_id = ? AND subject_type = ? AND subject_id = ?
                   ORDER BY created_at DESC LIMIT 1""",
                (farm_id, subject_type, subject_id),
            ).fetchone()
            return dict(row) if row else None

    def get_active_alerts(self, farm_id: int) -> list[dict[str, Any]]:
        """Unacknowledged alerts, most urgent first (spec section 12:
        alerts must be prioritized)."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM guardian_alerts
                   WHERE farm_id = ? AND acknowledged_at IS NULL
                   ORDER BY priority DESC, created_at DESC""",
                (farm_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_alert(self, alert_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM guardian_alerts WHERE id = ?", (alert_id,)).fetchone()
            return dict(row) if row else None

    def acknowledge_alert(self, alert_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE guardian_alerts SET acknowledged_at = ? WHERE id = ?",
                (_now(), alert_id),
            )

    # -- Authorization support ----------------------------------------------
    def get_farm(self, farm_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM farms WHERE id = ?", (farm_id,)).fetchone()
            return dict(row) if row else None

    def farmer_owns_farm(self, farmer_id: int, farm_id: int) -> bool:
        farm = self.get_farm(farm_id)
        return farm is not None and farm["farmer_id"] == farmer_id

    # -- Audit log ------------------------------------------------------------
    def log_audit(self, actor: str, action: str, target_type: str | None = None,
                   target_id: str | None = None, details: dict[str, Any] | None = None) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO audit_log (actor, action, target_type, target_id, details, created_at)
                   VALUES (?,?,?,?,?,?)""",
                (actor, action, target_type, target_id,
                 json.dumps(details) if details is not None else None, _now()),
            )
            return cur.lastrowid

    def get_audit_log(self, actor: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if actor:
                rows = conn.execute(
                    "SELECT * FROM audit_log WHERE actor = ? ORDER BY created_at DESC LIMIT ?",
                    (actor, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM audit_log ORDER BY created_at DESC LIMIT ?", (limit,)
                ).fetchall()
            return [dict(r) for r in rows]

    # -- Soil tests -----------------------------------------------------------
    def save_soil_test(self, field_id: int, ph: float | None, nitrogen_ppm: float | None,
                        phosphorus_ppm: float | None, potassium_ppm: float | None,
                        source: str) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO soil_tests
                   (field_id, ph, nitrogen_ppm, phosphorus_ppm, potassium_ppm, source,
                    tested_at, created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (field_id, ph, nitrogen_ppm, phosphorus_ppm, potassium_ppm, source, _now(), _now()),
            )
            return cur.lastrowid

    def get_latest_soil_test(self, field_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM soil_tests WHERE field_id = ? ORDER BY tested_at DESC LIMIT 1",
                (field_id,),
            ).fetchone()
            return dict(row) if row else None

    def get_soil_test_history(self, field_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM soil_tests WHERE field_id = ? ORDER BY tested_at ASC",
                (field_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    # -- Market prices ----------------------------------------------------
    def get_or_create_market_watch(self, farm_id: int, crop_name: str, market_name: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM market_watches WHERE farm_id = ? AND crop_name = ? AND market_name = ?",
                (farm_id, crop_name, market_name),
            ).fetchone()
            if row:
                return row["id"]
            cur = conn.execute(
                "INSERT INTO market_watches (farm_id, crop_name, market_name, created_at) VALUES (?,?,?,?)",
                (farm_id, crop_name, market_name, _now()),
            )
            return cur.lastrowid

    def save_market_price(self, crop_name: str, market_name: str, price_per_quintal: float,
                           provider: str, recorded_at: str | None = None) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO market_prices
                   (crop_name, market_name, price_per_quintal, provider, recorded_at, created_at)
                   VALUES (?,?,?,?,?,?)""",
                (crop_name, market_name, price_per_quintal, provider, recorded_at or _now(), _now()),
            )
            return cur.lastrowid

    def get_market_price_history(self, crop_name: str, market_name: str,
                                  limit: int = 30) -> list[dict[str, Any]]:
        """Most recent first, capped at `limit` — this is shared reference
        data across farms watching the same crop/market, not per-farm."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM market_prices WHERE crop_name = ? AND market_name = ?
                   ORDER BY recorded_at DESC LIMIT ?""",
                (crop_name, market_name, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    # -- Expert consultations --------------------------------------------------
    def create_consultation_request(self, farm_id: int, recommendation_id: int | None,
                                      source_agent: str, problem: str, escalation_reason: str,
                                      severity: str) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO expert_consultations
                   (farm_id, recommendation_id, source_agent, problem, escalation_reason,
                    severity, status, requested_at, created_at)
                   VALUES (?,?,?,?,?,?,'pending',?,?)""",
                (farm_id, recommendation_id, source_agent, problem, escalation_reason,
                 severity, _now(), _now()),
            )
            return cur.lastrowid

    def get_pending_consultations(self, farm_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM expert_consultations WHERE farm_id = ? AND status = 'pending'
                   ORDER BY created_at DESC""",
                (farm_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_consultation(self, consultation_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM expert_consultations WHERE id = ?", (consultation_id,)
            ).fetchone()
            return dict(row) if row else None

    def resolve_consultation(self, consultation_id: int, expert_name: str, notes: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """UPDATE expert_consultations
                   SET status = 'resolved', expert_name = ?, resolution_notes = ?, resolved_at = ?
                   WHERE id = ?""",
                (expert_name, notes, _now(), consultation_id),
            )

    # -- Crop cycles (fixes Economics blending seasons together) --------------
    def get_field(self, field_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM fields WHERE id = ?", (field_id,)).fetchone()
            return dict(row) if row else None

    def get_active_crop_cycle(self, field_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM crop_cycles WHERE field_id = ? AND ended_at IS NULL "
                "ORDER BY started_at DESC LIMIT 1",
                (field_id,),
            ).fetchone()
            return dict(row) if row else None

    def _ensure_active_cycle_id(self, conn: sqlite3.Connection, field_id: int) -> int:
        """Internal helper used within an already-open connection (so
        expense/sale inserts and cycle creation stay in one transaction).
        Lazily creates a cycle using the field's current crop_name if none
        is active yet — callers that never explicitly call
        start_new_crop_cycle() still get correctly-scoped data from day one."""
        row = conn.execute(
            "SELECT id FROM crop_cycles WHERE field_id = ? AND ended_at IS NULL "
            "ORDER BY started_at DESC LIMIT 1",
            (field_id,),
        ).fetchone()
        if row:
            return row["id"]
        field_row = conn.execute("SELECT crop_name FROM fields WHERE id = ?", (field_id,)).fetchone()
        crop_name = field_row["crop_name"] if field_row else "unknown"
        cur = conn.execute(
            "INSERT INTO crop_cycles (field_id, crop_name, started_at) VALUES (?,?,?)",
            (field_id, crop_name, _now()),
        )
        return cur.lastrowid

    def start_new_crop_cycle(self, field_id: int, crop_name: str) -> int:
        """Ends whatever cycle is currently active for this field (if any)
        and starts a new one with `crop_name` — the explicit action a
        farmer takes when replanting, so old and new season's
        expenses/sales don't blend together in Economics."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE crop_cycles SET ended_at = ? WHERE field_id = ? AND ended_at IS NULL",
                (_now(), field_id),
            )
            conn.execute("UPDATE fields SET crop_name = ? WHERE id = ?", (crop_name, field_id))
            cur = conn.execute(
                "INSERT INTO crop_cycles (field_id, crop_name, started_at) VALUES (?,?,?)",
                (field_id, crop_name, _now()),
            )
            return cur.lastrowid

    # -- Expenses / Sales (Economics Agent) ------------------------------------
    def log_expense(self, field_id: int, category: str, amount: float,
                     incurred_at: str | None = None) -> int:
        with self._connect() as conn:
            cycle_id = self._ensure_active_cycle_id(conn, field_id)
            cur = conn.execute(
                """INSERT INTO expenses (field_id, crop_cycle_id, category, amount, incurred_at, created_at)
                   VALUES (?,?,?,?,?,?)""",
                (field_id, cycle_id, category, amount, incurred_at or _now(), _now()),
            )
            return cur.lastrowid

    def get_field_expenses(self, field_id: int) -> list[dict[str, Any]]:
        """All-time, across every crop cycle this field has ever had —
        use get_active_cycle_expenses() for the current-season-only view
        Economics actually needs."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM expenses WHERE field_id = ? ORDER BY incurred_at ASC", (field_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_active_cycle_expenses(self, field_id: int) -> list[dict[str, Any]]:
        cycle = self.get_active_crop_cycle(field_id)
        if cycle is None:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM expenses WHERE crop_cycle_id = ? ORDER BY incurred_at ASC",
                (cycle["id"],),
            ).fetchall()
            return [dict(r) for r in rows]

    def log_sale(self, field_id: int, quantity_kg: float, price_per_kg: float,
                 sold_at: str | None = None) -> int:
        with self._connect() as conn:
            cycle_id = self._ensure_active_cycle_id(conn, field_id)
            cur = conn.execute(
                """INSERT INTO sales (field_id, crop_cycle_id, quantity_kg, price_per_kg, sold_at, created_at)
                   VALUES (?,?,?,?,?,?)""",
                (field_id, cycle_id, quantity_kg, price_per_kg, sold_at or _now(), _now()),
            )
            return cur.lastrowid

    def get_field_sales(self, field_id: int) -> list[dict[str, Any]]:
        """All-time, across every crop cycle — see get_field_expenses's docstring."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM sales WHERE field_id = ? ORDER BY sold_at ASC", (field_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_active_cycle_sales(self, field_id: int) -> list[dict[str, Any]]:
        cycle = self.get_active_crop_cycle(field_id)
        if cycle is None:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM sales WHERE crop_cycle_id = ? ORDER BY sold_at ASC",
                (cycle["id"],),
            ).fetchall()
            return [dict(r) for r in rows]

    # -- Treatment outcomes (Learning Agent) -----------------------------------
    def record_outcome(self, farm_id: int, recommendation_id: int | None, source_agent: str,
                        followed_advice: bool, outcome: str, notes: str | None = None) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO treatment_outcomes
                   (farm_id, recommendation_id, source_agent, followed_advice, outcome,
                    notes, recorded_at, created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (farm_id, recommendation_id, source_agent, int(followed_advice), outcome,
                 notes, _now(), _now()),
            )
            return cur.lastrowid

    def get_outcomes_for_agent(self, source_agent: str) -> list[dict[str, Any]]:
        """Across ALL farms — a track record is only meaningful in
        aggregate; one farm's handful of outcomes isn't a sample size."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM treatment_outcomes WHERE source_agent = ? ORDER BY recorded_at ASC",
                (source_agent,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_farm_outcomes(self, farm_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM treatment_outcomes WHERE farm_id = ? ORDER BY recorded_at DESC",
                (farm_id,),
            ).fetchall()
            return [dict(r) for r in rows]
