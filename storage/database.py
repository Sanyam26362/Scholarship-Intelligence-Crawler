"""
Relational Database and Audit Storage for Atlas Scholarship Intelligence Engine.
Implements SQLite schema, foreign key enforcement, delta tracking, and evidence trace persistence.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from config.settings import settings


def _resolve_db_path(db_path: Optional[Union[str, Path]] = None) -> Path:
    """Resolves and ensures the parent directory for the SQLite database path exists."""
    if db_path is None:
        target = settings.db_path
    else:
        target = Path(db_path) if Path(db_path).is_absolute() else settings.base_dir / db_path
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def get_connection(db_path: Optional[Union[str, Path]] = None) -> sqlite3.Connection:
    """
    Creates and returns a SQLite connection with foreign keys enabled and row_factory configured.
    """
    path = _resolve_db_path(db_path)
    conn = sqlite3.connect(str(path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    # Enforce SQLite foreign key integrity constraints
    conn.execute("PRAGMA foreign_keys = ON;")
    # Use write-ahead logging for high concurrency
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn


def init_db(db_path: Optional[Union[str, Path]] = None) -> None:
    """
    Initializes the database schema including scholarships, evidence_traces, and audit_logs tables.
    """
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS scholarships (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    official_source_url TEXT UNIQUE NOT NULL,
                    application_url TEXT NOT NULL DEFAULT 'Not specified',
                    amount_benefit TEXT NOT NULL DEFAULT 'Not specified',
                    eligibility_criteria TEXT NOT NULL DEFAULT 'Not specified',
                    academic_requirements TEXT NOT NULL DEFAULT 'Not specified',
                    course_level TEXT NOT NULL DEFAULT 'Not specified',
                    income_criteria TEXT NOT NULL DEFAULT 'Not specified',
                    age_criteria TEXT NOT NULL DEFAULT 'Not specified',
                    gender_criteria TEXT NOT NULL DEFAULT 'Not specified',
                    category_criteria TEXT NOT NULL DEFAULT 'Not specified',
                    domicile_requirements TEXT NOT NULL DEFAULT 'Not specified',
                    institution_requirements TEXT NOT NULL DEFAULT 'Not specified',
                    opening_date TEXT NOT NULL DEFAULT 'Not specified',
                    closing_date TEXT NOT NULL DEFAULT 'Not specified',
                    documents_required TEXT NOT NULL DEFAULT 'Not specified',
                    selection_process TEXT NOT NULL DEFAULT 'Not specified',
                    renewal_requirements TEXT NOT NULL DEFAULT 'Not specified',
                    status TEXT NOT NULL DEFAULT 'REVIEW_REQUIRED',
                    confidence_score REAL NOT NULL DEFAULT 0.0,
                    score_breakdown TEXT NOT NULL DEFAULT '{}',
                    last_verified TIMESTAMP NOT NULL,
                    raw_hash TEXT,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS evidence_traces (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scholarship_id TEXT NOT NULL,
                    field_name TEXT NOT NULL,
                    extracted_value TEXT NOT NULL,
                    evidence_quote TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    captured_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (scholarship_id) REFERENCES scholarships (id) ON DELETE CASCADE
                );
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scholarship_id TEXT NOT NULL,
                    field_name TEXT NOT NULL,
                    old_value TEXT,
                    new_value TEXT,
                    source_url TEXT,
                    evidence_quote TEXT,
                    detected_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (scholarship_id) REFERENCES scholarships (id) ON DELETE CASCADE
                );
            """)

            # Helpful indexing for rapid querying and audit traversal
            conn.execute("CREATE INDEX IF NOT EXISTS idx_scholarships_url ON scholarships (official_source_url);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_scholarships_status ON scholarships (status);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_evidence_scholarship ON evidence_traces (scholarship_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_evidence_field ON evidence_traces (scholarship_id, field_name);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_scholarship ON audit_logs (scholarship_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_detected ON audit_logs (detected_at);")
    finally:
        conn.close()


def log_change(
    scholarship_id: str,
    field_name: str,
    old_value: Optional[str],
    new_value: Optional[str],
    source_url: Optional[str] = None,
    evidence_quote: Optional[str] = None,
    detected_at: Optional[str] = None,
    db_path: Optional[Union[str, Path]] = None,
) -> int:
    """
    Records an entry in the audit_logs table for delta tracking and compliance verification.
    """
    if detected_at is None:
        detected_at = datetime.now(timezone.utc).isoformat()

    conn = get_connection(db_path)
    try:
        with conn:
            cursor = conn.execute(
                """
                INSERT INTO audit_logs (scholarship_id, field_name, old_value, new_value, source_url, evidence_quote, detected_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (scholarship_id, field_name, old_value, new_value, source_url, evidence_quote, detected_at),
            )
            return cursor.lastrowid
    finally:
        conn.close()


def save_scholarship(
    scholarship_data: Dict[str, Any],
    evidence_list: Optional[List[Dict[str, Any]]] = None,
    db_path: Optional[Union[str, Path]] = None,
) -> str:
    """
    Persists a scholarship record with automatic delta tracking against previous snapshots,
    and inserts corresponding evidence traces.
    """
    conn = get_connection(db_path)
    try:
        now_iso = datetime.now(timezone.utc).isoformat()
        official_url = scholarship_data.get("official_source_url", "").strip()
        if not official_url:
            raise ValueError("official_source_url is required to save scholarship")

        with conn:
            # Check for existing record by official_source_url or id
            cursor = conn.execute(
                "SELECT * FROM scholarships WHERE official_source_url = ? OR id = ?",
                (official_url, scholarship_data.get("id", "")),
            )
            existing = cursor.fetchone()

            # Ensure ID
            scholarship_id = existing["id"] if existing else (scholarship_data.get("id") or str(uuid.uuid4()))

            # Prepare columns
            tracked_fields = [
                "name",
                "provider",
                "source_type",
                "application_url",
                "amount_benefit",
                "eligibility_criteria",
                "academic_requirements",
                "course_level",
                "income_criteria",
                "age_criteria",
                "gender_criteria",
                "category_criteria",
                "domicile_requirements",
                "institution_requirements",
                "opening_date",
                "closing_date",
                "documents_required",
                "selection_process",
                "renewal_requirements",
                "status",
                "confidence_score",
            ]

            # Delta tracking when existing record is updated
            if existing:
                for field in tracked_fields:
                    if field in scholarship_data:
                        old_val = str(existing[field]) if existing[field] is not None else ""
                        new_val = str(scholarship_data[field]) if scholarship_data[field] is not None else ""
                        if old_val != new_val:
                            # Find matching evidence quote if present
                            evidence_quote = None
                            if evidence_list:
                                for ev in evidence_list:
                                    if ev.get("field_name") == field:
                                        evidence_quote = ev.get("evidence_quote")
                                        break
                            conn.execute(
                                """
                                INSERT INTO audit_logs (scholarship_id, field_name, old_value, new_value, source_url, evidence_quote, detected_at)
                                VALUES (?, ?, ?, ?, ?, ?, ?)
                                """,
                                (
                                    scholarship_id,
                                    field,
                                    old_val,
                                    new_val,
                                    scholarship_data.get("official_source_url", existing["official_source_url"]),
                                    evidence_quote,
                                    now_iso,
                                ),
                            )

            # Format score_breakdown as JSON string
            score_breakdown = scholarship_data.get("score_breakdown", {})
            if isinstance(score_breakdown, dict):
                score_breakdown_str = json.dumps(score_breakdown)
            else:
                score_breakdown_str = str(score_breakdown)

            last_verified = scholarship_data.get("last_verified") or now_iso
            created_at = existing["created_at"] if existing else (scholarship_data.get("created_at") or now_iso)
            raw_hash = scholarship_data.get("raw_hash", existing["raw_hash"] if existing else None)

            # Insert or replace scholarship master row
            conn.execute(
                """
                INSERT INTO scholarships (
                    id, name, provider, source_type, official_source_url, application_url,
                    amount_benefit, eligibility_criteria, academic_requirements, course_level,
                    income_criteria, age_criteria, gender_criteria, category_criteria,
                    domicile_requirements, institution_requirements, opening_date, closing_date,
                    documents_required, selection_process, renewal_requirements, status,
                    confidence_score, score_breakdown, last_verified, raw_hash, created_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?, ?
                )
                ON CONFLICT(official_source_url) DO UPDATE SET
                    name = excluded.name,
                    provider = excluded.provider,
                    source_type = excluded.source_type,
                    application_url = excluded.application_url,
                    amount_benefit = excluded.amount_benefit,
                    eligibility_criteria = excluded.eligibility_criteria,
                    academic_requirements = excluded.academic_requirements,
                    course_level = excluded.course_level,
                    income_criteria = excluded.income_criteria,
                    age_criteria = excluded.age_criteria,
                    gender_criteria = excluded.gender_criteria,
                    category_criteria = excluded.category_criteria,
                    domicile_requirements = excluded.domicile_requirements,
                    institution_requirements = excluded.institution_requirements,
                    opening_date = excluded.opening_date,
                    closing_date = excluded.closing_date,
                    documents_required = excluded.documents_required,
                    selection_process = excluded.selection_process,
                    renewal_requirements = excluded.renewal_requirements,
                    status = excluded.status,
                    confidence_score = excluded.confidence_score,
                    score_breakdown = excluded.score_breakdown,
                    last_verified = excluded.last_verified,
                    raw_hash = excluded.raw_hash
                """,
                (
                    scholarship_id,
                    scholarship_data.get("name", "Not specified"),
                    scholarship_data.get("provider", "Not specified"),
                    scholarship_data.get("source_type", "GOVERNMENT"),
                    official_url,
                    scholarship_data.get("application_url", "Not specified"),
                    scholarship_data.get("amount_benefit", "Not specified"),
                    scholarship_data.get("eligibility_criteria", "Not specified"),
                    scholarship_data.get("academic_requirements", "Not specified"),
                    scholarship_data.get("course_level", "Not specified"),
                    scholarship_data.get("income_criteria", "Not specified"),
                    scholarship_data.get("age_criteria", "Not specified"),
                    scholarship_data.get("gender_criteria", "Not specified"),
                    scholarship_data.get("category_criteria", "Not specified"),
                    scholarship_data.get("domicile_requirements", "Not specified"),
                    scholarship_data.get("institution_requirements", "Not specified"),
                    scholarship_data.get("opening_date", "Not specified"),
                    scholarship_data.get("closing_date", "Not specified"),
                    scholarship_data.get("documents_required", "Not specified"),
                    scholarship_data.get("selection_process", "Not specified"),
                    scholarship_data.get("renewal_requirements", "Not specified"),
                    scholarship_data.get("status", "REVIEW_REQUIRED"),
                    float(scholarship_data.get("confidence_score", 0.0)),
                    score_breakdown_str,
                    last_verified,
                    raw_hash,
                    created_at,
                ),
            )

            # Persist Evidence Traces if provided
            if evidence_list:
                for ev in evidence_list:
                    conn.execute(
                        """
                        INSERT INTO evidence_traces (scholarship_id, field_name, extracted_value, evidence_quote, source_url, captured_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            scholarship_id,
                            ev.get("field_name", ""),
                            str(ev.get("extracted_value", "")),
                            str(ev.get("evidence_quote", "")),
                            ev.get("source_url") or official_url,
                            ev.get("captured_at") or now_iso,
                        ),
                    )

            return scholarship_id
    finally:
        conn.close()


def get_scholarship_by_url(
    url: str, db_path: Optional[Union[str, Path]] = None
) -> Optional[Dict[str, Any]]:
    """Retrieves a scholarship record by its official source URL."""
    conn = get_connection(db_path)
    try:
        cursor = conn.execute("SELECT * FROM scholarships WHERE official_source_url = ?", (url.strip(),))
        row = cursor.fetchone()
        if not row:
            return None
        res = dict(row)
        if isinstance(res.get("score_breakdown"), str):
            try:
                res["score_breakdown"] = json.loads(res["score_breakdown"])
            except Exception:
                pass
        return res
    finally:
        conn.close()


def get_scholarship_by_id(
    scholarship_id: str, db_path: Optional[Union[str, Path]] = None
) -> Optional[Dict[str, Any]]:
    """Retrieves a scholarship record by its primary key ID."""
    conn = get_connection(db_path)
    try:
        cursor = conn.execute("SELECT * FROM scholarships WHERE id = ?", (scholarship_id.strip(),))
        row = cursor.fetchone()
        if not row:
            return None
        res = dict(row)
        if isinstance(res.get("score_breakdown"), str):
            try:
                res["score_breakdown"] = json.loads(res["score_breakdown"])
            except Exception:
                pass
        return res
    finally:
        conn.close()


def get_all_scholarships(
    limit: int = 100,
    offset: int = 0,
    status: Optional[str] = None,
    db_path: Optional[Union[str, Path]] = None,
) -> List[Dict[str, Any]]:
    """Fetches all scholarships with optional status filtering and pagination."""
    conn = get_connection(db_path)
    try:
        if status:
            cursor = conn.execute(
                "SELECT * FROM scholarships WHERE status = ? ORDER BY confidence_score DESC, last_verified DESC LIMIT ? OFFSET ?",
                (status, limit, offset),
            )
        else:
            cursor = conn.execute(
                "SELECT * FROM scholarships ORDER BY confidence_score DESC, last_verified DESC LIMIT ? OFFSET ?",
                (limit, offset),
            )
        records = []
        for row in cursor.fetchall():
            rec = dict(row)
            if isinstance(rec.get("score_breakdown"), str):
                try:
                    rec["score_breakdown"] = json.loads(rec["score_breakdown"])
                except Exception:
                    pass
            records.append(rec)
        return records
    finally:
        conn.close()


def get_audit_logs(
    scholarship_id: Optional[str] = None,
    limit: int = 100,
    db_path: Optional[Union[str, Path]] = None,
) -> List[Dict[str, Any]]:
    """Fetches audit delta logs, optionally filtered by scholarship ID."""
    conn = get_connection(db_path)
    try:
        if scholarship_id:
            cursor = conn.execute(
                "SELECT * FROM audit_logs WHERE scholarship_id = ? ORDER BY detected_at DESC, id DESC LIMIT ?",
                (scholarship_id, limit),
            )
        else:
            cursor = conn.execute(
                "SELECT * FROM audit_logs ORDER BY detected_at DESC, id DESC LIMIT ?",
                (limit,),
            )
        return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()


def get_scholarship_evidence(
    scholarship_id: str,
    field_name: Optional[str] = None,
    db_path: Optional[Union[str, Path]] = None,
) -> List[Dict[str, Any]]:
    """Retrieves all ground-truth evidence traces recorded for a given scholarship."""
    conn = get_connection(db_path)
    try:
        if field_name:
            cursor = conn.execute(
                "SELECT * FROM evidence_traces WHERE scholarship_id = ? AND field_name = ? ORDER BY id ASC",
                (scholarship_id, field_name),
            )
        else:
            cursor = conn.execute(
                "SELECT * FROM evidence_traces WHERE scholarship_id = ? ORDER BY id ASC",
                (scholarship_id,),
            )
        return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()
