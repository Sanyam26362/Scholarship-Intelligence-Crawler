"""
Comprehensive Test Suite for Phase 1 & 2 Foundation & Verification Engine.
Verifies:
1. SQLite schema integrity, foreign key constraints, and cascade operations.
2. Pydantic v2 strict models, zero-hallucination defaults ('Not specified'), and evidence grounding.
3. Canonical domain resolver classifications, aggregator blacklisting, and CSR whitelisting.
4. Deterministic 100-point scoring algorithm and strict 95.0% gating rule.
5. Automated delta tracking in audit_logs on simulated scholarship record updates.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import settings
from core.discovery.resolver import (
    AuthorityTier,
    classify_url,
    is_canonical_domain,
    clean_url,
)
from core.extractor.schema import (
    FieldEvidence,
    ScholarshipRecord,
    ScholarshipStatus,
    SourceType,
)
from core.verifier.scorer import (
    calculate_confidence_score,
    evaluate_deadline_format,
    evaluate_application_url,
)
from storage.database import (
    init_db,
    get_connection,
    save_scholarship,
    log_change,
    get_scholarship_by_url,
    get_scholarship_by_id,
    get_all_scholarships,
    get_audit_logs,
    get_scholarship_evidence,
)


class TestFoundationEngine(unittest.TestCase):
    """Automated verification suite for the Atlas Scholarship Foundation."""

    def setUp(self) -> None:
        """Create a dedicated temporary database file for each test execution."""
        self.temp_db_fd, self.temp_db_path = tempfile.mkstemp(suffix=".db")
        os.close(self.temp_db_fd)
        init_db(self.temp_db_path)

    def tearDown(self) -> None:
        """Clean up the temporary database file after test completion."""
        try:
            if os.path.exists(self.temp_db_path):
                os.remove(self.temp_db_path)
        except Exception:
            pass

    # --------------------------------------------------------------------------
    # TEST 1: Database Schema Integrity & Foreign Key Constraints
    # --------------------------------------------------------------------------
    def test_database_schema_integrity(self) -> None:
        """Validates table schemas, required columns, and foreign key cascades."""
        conn = get_connection(self.temp_db_path)
        cursor = conn.cursor()

        # 1. Verify existence of all three core tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = {row["name"] for row in cursor.fetchall()}
        self.assertIn("scholarships", tables, "scholarships master table missing")
        self.assertIn("evidence_traces", tables, "evidence_traces table missing")
        self.assertIn("audit_logs", tables, "audit_logs table missing")

        # 2. Verify scholarships table columns
        cursor.execute("PRAGMA table_info(scholarships);")
        columns = {row["name"] for row in cursor.fetchall()}
        expected_columns = {
            "id", "name", "provider", "source_type", "official_source_url",
            "application_url", "amount_benefit", "eligibility_criteria",
            "academic_requirements", "course_level", "income_criteria",
            "age_criteria", "gender_criteria", "category_criteria",
            "domicile_requirements", "institution_requirements",
            "opening_date", "closing_date", "documents_required",
            "selection_process", "renewal_requirements", "status",
            "confidence_score", "score_breakdown", "last_verified",
            "raw_hash", "created_at"
        }
        for col in expected_columns:
            self.assertIn(col, columns, f"Column '{col}' missing in scholarships table")

        # 3. Verify Foreign Key enforcement
        cursor.execute("PRAGMA foreign_keys;")
        fk_status = cursor.fetchone()[0]
        self.assertEqual(fk_status, 1, "Foreign keys must be actively enabled (PRAGMA foreign_keys = ON)")

        # 4. Verify Foreign Key Cascade on deletion
        # Insert parent scholarship
        parent_id = "test-scheme-001"
        cursor.execute(
            """
            INSERT INTO scholarships (id, name, provider, source_type, official_source_url, eligibility_criteria, last_verified)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (parent_id, "National Merit", "Gov of India", "GOVERNMENT", "https://scholarships.gov.in/scheme1", "All students", "2026-10-10T12:00:00Z"),
        )
        # Insert child evidence trace
        cursor.execute(
            """
            INSERT INTO evidence_traces (scholarship_id, field_name, extracted_value, evidence_quote, source_url)
            VALUES (?, ?, ?, ?, ?)
            """,
            (parent_id, "amount_benefit", "Rs 50000", "Scholarship of Rs 50000", "https://scholarships.gov.in/scheme1"),
        )
        # Insert child audit log
        cursor.execute(
            """
            INSERT INTO audit_logs (scholarship_id, field_name, old_value, new_value)
            VALUES (?, ?, ?, ?)
            """,
            (parent_id, "status", "REVIEW_REQUIRED", "VERIFIED"),
        )
        conn.commit()

        # Delete parent scholarship and assert children are cascaded
        cursor.execute("DELETE FROM scholarships WHERE id = ?", (parent_id,))
        conn.commit()

        cursor.execute("SELECT COUNT(*) FROM evidence_traces WHERE scholarship_id = ?", (parent_id,))
        self.assertEqual(cursor.fetchone()[0], 0, "Evidence traces must cascade delete with parent scholarship")

        cursor.execute("SELECT COUNT(*) FROM audit_logs WHERE scholarship_id = ?", (parent_id,))
        self.assertEqual(cursor.fetchone()[0], 0, "Audit logs must cascade delete with parent scholarship")

        conn.close()

    # --------------------------------------------------------------------------
    # TEST 2: Pydantic Validation & Zero-Hallucination Policy
    # --------------------------------------------------------------------------
    def test_pydantic_validation_and_zero_hallucination(self) -> None:
        """Validates that omitted optional fields strictly default to 'Not specified' and required fields fail on empty."""
        # 1. Valid record with minimal fields: all optional fields MUST be 'Not specified'
        rec = ScholarshipRecord(
            name="AICTE Pragati Scholarship for Girls",
            provider="AICTE",
            official_source_url="https://www.aicte-india.org/schemes/students-development-schemes/Pragati",
            eligibility_criteria="Girls admitted to 1st year of degree programme",
        )
        self.assertEqual(rec.amount_benefit, "Not specified")
        self.assertEqual(rec.application_url, "Not specified")
        self.assertEqual(rec.academic_requirements, "Not specified")
        self.assertEqual(rec.income_criteria, "Not specified")
        self.assertEqual(rec.closing_date, "Not specified")
        self.assertEqual(rec.selection_process, "Not specified")

        # 2. Coercion of empty strings or generic placeholders to 'Not specified'
        rec2 = ScholarshipRecord(
            name="AICTE Saksham Scholarship",
            provider="AICTE",
            official_source_url="https://www.aicte-india.org/schemes/students-development-schemes/Saksham",
            eligibility_criteria="Specially-abled students with disability not less than 40%",
            amount_benefit="",
            income_criteria="None",
            closing_date="N/A",
        )
        self.assertEqual(rec2.amount_benefit, "Not specified")
        self.assertEqual(rec2.income_criteria, "Not specified")
        self.assertEqual(rec2.closing_date, "Not specified")

        # 3. Missing required fields must raise validation errors
        with self.assertRaises(Exception):
            ScholarshipRecord(
                name="Incomplete Scheme",
                # missing provider
                official_source_url="https://gov.in",
                eligibility_criteria="Eligibility info",
            )

        with self.assertRaises(Exception):
            ScholarshipRecord(
                name="Invalid URL Scheme",
                provider="Department",
                official_source_url="not-a-valid-url",
                eligibility_criteria="Eligibility info",
            )

        # 4. FieldEvidence verbatim grounding check
        raw_webpage = """
        AICTE Pragati Scholarship provides Rs 50,000 per annum for every year of study.
        Eligible candidates must have family income not exceeding Rs 8 Lakh per annum.
        Applications close strictly on 31st October 2026.
        """
        valid_ev = FieldEvidence(
            value="Rs 50,000 per annum",
            quote="provides Rs 50,000 per annum for every year of study",
        )
        self.assertTrue(valid_ev.is_grounded_in(raw_webpage), "Verbatim quote must match substring")

        hallucinated_ev = FieldEvidence(
            value="Rs 1,00,000 per annum",
            quote="provides Rs 1,00,000 bonus cash reward",  # Not in source
        )
        self.assertFalse(hallucinated_ev.is_grounded_in(raw_webpage), "Hallucinated quote must fail grounding check")

    # --------------------------------------------------------------------------
    # TEST 3: Canonical Domain Resolver & Aggregator Flagging
    # --------------------------------------------------------------------------
    def test_canonical_domain_resolver(self) -> None:
        """Validates high domain authority for .gov.in, .ac.in, CSR and rejection of aggregators."""
        # 1. Government domains (.gov.in, .nic.in)
        c_gov = classify_url("https://scholarships.gov.in/public/schemeGuidelines/101.pdf")
        self.assertEqual(c_gov.source_type, SourceType.GOVERNMENT)
        self.assertEqual(c_gov.domain_score, 30)
        self.assertTrue(c_gov.is_authoritative)
        self.assertFalse(c_gov.is_aggregator)

        c_nic = classify_url("https://serviceonline.gov.in/service/scholarship")
        self.assertEqual(c_nic.source_type, SourceType.GOVERNMENT)
        self.assertEqual(c_nic.domain_score, 30)
        self.assertTrue(c_nic.is_authoritative)

        # 2. Academic / Apex bodies (.ac.in, aicte-india.org)
        c_ac = classify_url("https://www.ugc.ac.in/page/Scholarships-and-Fellowships.aspx")
        self.assertEqual(c_ac.domain_score, 28)
        self.assertTrue(c_ac.is_authoritative)

        c_aicte = classify_url("https://www.aicte-india.org/schemes/students-development-schemes")
        self.assertEqual(c_aicte.domain_score, 28)
        self.assertTrue(c_aicte.is_authoritative)

        # 3. Verified CSR & Philanthropic Trusts
        c_tata = classify_url("https://www.tatatrusts.org/our-work/individual-grants-programme/education")
        self.assertEqual(c_tata.source_type, SourceType.NGO_TRUST)
        self.assertEqual(c_tata.domain_score, 25)
        self.assertTrue(c_tata.is_authoritative)

        c_rf = classify_url("https://www.reliancefoundation.org/initiatives/education/scholarships")
        self.assertEqual(c_rf.source_type, SourceType.CORPORATE_CSR)
        self.assertEqual(c_rf.domain_score, 25)
        self.assertTrue(c_rf.is_authoritative)

        # 4. Blacklisted Aggregators (Buddy4Study, SarkariResult, Shiksha)
        c_b4s = classify_url("https://www.buddy4study.com/scholarship/reliance-foundation-scholarships")
        self.assertEqual(c_b4s.source_type, SourceType.AGGREGATOR)
        self.assertEqual(c_b4s.domain_score, 0)
        self.assertFalse(c_b4s.is_authoritative)
        self.assertTrue(c_b4s.is_aggregator)

        c_sarkari = classify_url("https://www.sarkariresult.com/scholarship/up-scholarship-online-form/")
        self.assertEqual(c_sarkari.source_type, SourceType.AGGREGATOR)
        self.assertEqual(c_sarkari.domain_score, 0)
        self.assertFalse(c_sarkari.is_authoritative)
        self.assertTrue(c_sarkari.is_aggregator)

        # 5. Clean URL stripping of tracking parameters
        dirty_url = "https://scholarships.gov.in/scheme?utm_source=telegram&utm_medium=cpc&ref=affiliate_123"
        cleaned = clean_url(dirty_url)
        self.assertEqual(cleaned, "https://scholarships.gov.in/scheme")

    # --------------------------------------------------------------------------
    # TEST 4: Deterministic Scorer & Strict 95% Gating
    # --------------------------------------------------------------------------
    def test_deterministic_scoring_and_gating(self) -> None:
        """Verifies exact 100-point calculation and strictly gated VERIFIED vs REVIEW_REQUIRED."""
        raw_page_text = (
            "National Means Cum Merit Scholarship scheme: eligible for students in class 9 with income < 3.5 Lakh. "
            "Applications must be submitted on scholarships.gov.in by 31st October 2026."
        )

        # 1. Scheme A: High-confidence scheme reaching 100% -> VERIFIED
        scheme_a = ScholarshipRecord(
            name="National Means Cum Merit Scholarship",
            provider="Ministry of Education, GoI",
            official_source_url="https://scholarships.gov.in/nmmss",
            application_url="https://scholarships.gov.in/application-form",
            eligibility_criteria="Class 9 students with family income less than 3.5 Lakh",
            closing_date="31st October 2026",
            evidence_map={
                "eligibility_criteria": FieldEvidence(
                    value="Class 9 students with family income < 3.5 Lakh",
                    quote="eligible for students in class 9 with income < 3.5 Lakh",
                )
            },
        )
        score_a, status_a, breakdown_a = calculate_confidence_score(
            scheme_a,
            raw_content=raw_page_text,
            http_status_code=200,
            response_time_sec=0.45,
            has_conflicting_guidelines=False,
        )

        # Check exact points:
        # Domain Authority (gov.in) = 30
        # Application Authenticity (in-domain gov.in) = 20
        # Evidence Grounding (verbatim quote matched) = 20
        # Deadline Verifiability (31st October 2026) = 15
        # Host Health (200 in 0.45s) = 10
        # Anti-conflict (no conflicts) = 5
        # Total = 100.0%
        self.assertEqual(breakdown_a["domain_authority"]["points"], 30)
        self.assertEqual(breakdown_a["application_authenticity"]["points"], 20)
        self.assertEqual(breakdown_a["evidence_grounding"]["points"], 20)
        self.assertEqual(breakdown_a["deadline_verifiability"]["points"], 15)
        self.assertEqual(breakdown_a["host_health"]["points"], 10)
        self.assertEqual(breakdown_a["anti_conflict"]["points"], 5)
        self.assertEqual(score_a, 100.0)
        self.assertEqual(status_a, ScholarshipStatus.VERIFIED.value)
        self.assertTrue(breakdown_a["gate_passed"])

        # 2. Scheme B: Verified CSR Scheme reaching 95.0% -> VERIFIED
        scheme_b = ScholarshipRecord(
            name="Reliance Foundation Undergraduate Scholarship",
            provider="Reliance Foundation",
            official_source_url="https://www.reliancefoundation.org/scholarships",
            application_url="https://www.reliancefoundation.org/apply",
            eligibility_criteria="First-year regular undergraduate students",
            closing_date="15-11-2026",
            evidence_map={
                "eligibility_criteria": FieldEvidence(
                    value="Undergraduate students",
                    quote="First-year regular undergraduate students",
                )
            },
        )
        # CSR domain (25) + App url (20) + Evidence (20) + Deadline (15) + Health (10) + Conflict (5) = 95.0%
        score_b, status_b, breakdown_b = calculate_confidence_score(
            scheme_b,
            raw_content="First-year regular undergraduate students eligible for Reliance Foundation grants.",
            http_status_code=200,
            response_time_sec=0.8,
            has_conflicting_guidelines=False,
        )
        self.assertEqual(score_b, 95.0)
        self.assertEqual(status_b, ScholarshipStatus.VERIFIED.value)
        self.assertTrue(breakdown_b["gate_passed"])

        # 3. Scheme C: Incomplete or ambiguous scheme scoring 80.0% -> REVIEW_REQUIRED
        # Gov domain (30) + Missing application url (0) + Evidence (20) + Ambiguous date (5) + Health (10) + Conflict (5)
        # Total = 30 + 0 + 20 + 5 + 10 + 5 = 70.0%
        scheme_c = ScholarshipRecord(
            name="State Pre-Matric Scheme",
            provider="State Welfare Dept",
            official_source_url="https://welfare.wb.gov.in/pre-matric",
            application_url="Not specified",  # Missing (0 pts)
            eligibility_criteria="Pre-matric students",
            closing_date="Check notification for extended schedule",  # Ambiguous (5 pts)
            evidence_map={
                "eligibility_criteria": FieldEvidence(
                    value="Pre-matric students",
                    quote="Pre-matric students enrolled in recognized schools",
                )
            },
        )
        score_c, status_c, breakdown_c = calculate_confidence_score(
            scheme_c,
            raw_content="Pre-matric students enrolled in recognized schools may apply.",
            http_status_code=200,
            response_time_sec=0.5,
        )
        self.assertEqual(score_c, 70.0)
        self.assertEqual(status_c, ScholarshipStatus.REVIEW_REQUIRED.value)
        self.assertFalse(breakdown_c["gate_passed"])

        # 4. Scheme D: Aggregator portal -> must NEVER pass gate even if 70 points
        scheme_d = ScholarshipRecord(
            name="Aggregator Mirror Listing",
            provider="Unknown Aggregator",
            official_source_url="https://www.buddy4study.com/scholarship/sample-scheme",
            application_url="https://www.buddy4study.com/apply",
            eligibility_criteria="Any student",
            closing_date="2026-12-31",
            evidence_map={
                "eligibility_criteria": FieldEvidence(
                    value="Any student",
                    quote="Any student studying in India",
                )
            },
        )
        score_d, status_d, breakdown_d = calculate_confidence_score(
            scheme_d,
            raw_content="Any student studying in India is eligible to register.",
            http_status_code=200,
        )
        # Aggregator domain authority = 0, application url to buddy4study = 0
        # Total = 0 + 0 + 20 + 15 + 10 + 5 = 50.0%
        self.assertEqual(breakdown_d["domain_authority"]["points"], 0)
        self.assertEqual(score_d, 50.0)
        self.assertEqual(status_d, ScholarshipStatus.REVIEW_REQUIRED.value)

    # --------------------------------------------------------------------------
    # TEST 5: Automated Audit Delta Tracking on Change
    # --------------------------------------------------------------------------
    def test_audit_delta_tracking(self) -> None:
        """Verifies that modifications to an existing scholarship automatically log audit deltas."""
        # Initial Scholarship Snapshot
        initial_data = {
            "name": "Tata Trusts Healthcare Grant",
            "provider": "Tata Trusts",
            "source_type": "NGO_TRUST",
            "official_source_url": "https://www.tatatrusts.org/our-work/medical-education",
            "application_url": "https://www.tatatrusts.org/apply-healthcare",
            "amount_benefit": "Rs 50,000 per year",
            "eligibility_criteria": "Students pursuing MBBS or BDS with family income < 4.5 Lakh",
            "closing_date": "30-09-2026",
            "status": "REVIEW_REQUIRED",
            "confidence_score": 85.0,
        }
        evidence_initial = [
            {
                "field_name": "amount_benefit",
                "extracted_value": "Rs 50,000 per year",
                "evidence_quote": "Grant amount covers Rs 50,000 per year towards tuition",
                "source_url": "https://www.tatatrusts.org/our-work/medical-education",
            }
        ]

        # 1. Save Initial Version
        scholarship_id = save_scholarship(
            scholarship_data=initial_data,
            evidence_list=evidence_initial,
            db_path=self.temp_db_path,
        )
        self.assertIsNotNone(scholarship_id)

        # Verify no audit deltas on first creation
        logs_initial = get_audit_logs(scholarship_id=scholarship_id, db_path=self.temp_db_path)
        self.assertEqual(len(logs_initial), 0, "No audit logs should exist prior to any modification")

        # 2. Update Scholarship Snapshot (simulating crawler re-verification with changed amount and deadline)
        updated_data = dict(initial_data)
        updated_data["amount_benefit"] = "Rs 75,000 per year"  # Modified Benefit
        updated_data["closing_date"] = "31-10-2026"  # Extended Deadline
        updated_data["confidence_score"] = 96.0
        updated_data["status"] = "VERIFIED"

        evidence_update = [
            {
                "field_name": "amount_benefit",
                "extracted_value": "Rs 75,000 per year",
                "evidence_quote": "Grant amount increased to Rs 75,000 per year for 2026",
                "source_url": "https://www.tatatrusts.org/our-work/medical-education",
            }
        ]

        save_scholarship(
            scholarship_data=updated_data,
            evidence_list=evidence_update,
            db_path=self.temp_db_path,
        )

        # 3. Retrieve Audit Logs & Verify Deltas
        audit_logs = get_audit_logs(scholarship_id=scholarship_id, db_path=self.temp_db_path)
        self.assertGreaterEqual(len(audit_logs), 2, "Expected audit deltas for amount_benefit and closing_date")

        # Map logs by field_name
        logs_by_field = {log["field_name"]: log for log in audit_logs}

        # Check amount_benefit delta
        self.assertIn("amount_benefit", logs_by_field)
        amount_log = logs_by_field["amount_benefit"]
        self.assertEqual(amount_log["old_value"], "Rs 50,000 per year")
        self.assertEqual(amount_log["new_value"], "Rs 75,000 per year")
        self.assertIn("increased to Rs 75,000", amount_log["evidence_quote"])
        self.assertIsNotNone(amount_log["detected_at"])

        # Check closing_date delta
        self.assertIn("closing_date", logs_by_field)
        date_log = logs_by_field["closing_date"]
        self.assertEqual(date_log["old_value"], "30-09-2026")
        self.assertEqual(date_log["new_value"], "31-10-2026")

        # Check updated scholarship record reflects latest values
        fetched = get_scholarship_by_id(scholarship_id, db_path=self.temp_db_path)
        self.assertEqual(fetched["amount_benefit"], "Rs 75,000 per year")
        self.assertEqual(fetched["closing_date"], "31-10-2026")
        self.assertEqual(fetched["status"], "VERIFIED")
        self.assertEqual(fetched["confidence_score"], 96.0)

    # --------------------------------------------------------------------------
    # TEST 6: Search Agent Rate Limiting & Canonical Resolution
    # --------------------------------------------------------------------------
    def test_search_agent_rate_limiting_and_resolution(self) -> None:
        """Verifies rate-limiter spacing and canonical resolution routing."""
        import time
        from core.discovery.search_agent import SearchAgent
        from core.discovery.resolver import resolve_canonical_source

        agent = SearchAgent(rate_limit_delay=0.1)
        t0 = time.time()
        agent._wait_for_rate_limit()
        agent._wait_for_rate_limit()
        elapsed = time.time() - t0
        self.assertGreaterEqual(elapsed, 0.09, "Search agent must enforce minimum delay between calls")

        # Authoritative URL resolves immediately without search
        res_gov = resolve_canonical_source("https://scholarships.gov.in/fresh-application")
        self.assertEqual(res_gov, "https://scholarships.gov.in/fresh-application")

        # Aggregator URL without search agent returns None (rejecting aggregator as primary source)
        res_agg = resolve_canonical_source("https://www.buddy4study.com/scholarship/test-scheme")
        self.assertIsNone(res_agg, "Aggregator URL must not be accepted as primary canonical source")

    # --------------------------------------------------------------------------
    # TEST 7: Database Query Helpers & Evidence Tracing
    # --------------------------------------------------------------------------
    def test_database_evidence_and_query_helpers(self) -> None:
        """Verifies get_all_scholarships, get_scholarship_evidence, and pagination."""
        rec_data = {
            "name": "UGC Ishan Uday Scholarship",
            "provider": "UGC",
            "source_type": "APEX_BODY",
            "official_source_url": "https://www.ugc.ac.in/ishan-uday",
            "application_url": "https://scholarships.gov.in",
            "amount_benefit": "Rs 7,800 per month",
            "eligibility_criteria": "NER students with family income < 4.5 Lakh",
            "closing_date": "31-12-2026",
            "status": "VERIFIED",
            "confidence_score": 98.0,
            "score_breakdown": {"domain_authority": 28, "total_score": 98.0},
        }
        ev_items = [
            {
                "field_name": "amount_benefit",
                "extracted_value": "Rs 7,800 per month",
                "evidence_quote": "For technical courses Rs 7,800 per month",
                "source_url": "https://www.ugc.ac.in/ishan-uday",
            },
            {
                "field_name": "eligibility_criteria",
                "extracted_value": "NER domicile",
                "evidence_quote": "Students having domicile of NER state",
                "source_url": "https://www.ugc.ac.in/ishan-uday",
            },
        ]
        sid = save_scholarship(rec_data, evidence_list=ev_items, db_path=self.temp_db_path)
        
        # Test get_all_scholarships
        all_schemes = get_all_scholarships(db_path=self.temp_db_path)
        self.assertEqual(len(all_schemes), 1)
        self.assertEqual(all_schemes[0]["name"], "UGC Ishan Uday Scholarship")
        self.assertIsInstance(all_schemes[0]["score_breakdown"], dict)

        # Test get_scholarship_evidence
        ev_list = get_scholarship_evidence(sid, db_path=self.temp_db_path)
        self.assertEqual(len(ev_list), 2)
        
        # Test field filtering on evidence
        amt_ev = get_scholarship_evidence(sid, field_name="amount_benefit", db_path=self.temp_db_path)
        self.assertEqual(len(amt_ev), 1)
        self.assertEqual(amt_ev[0]["extracted_value"], "Rs 7,800 per month")


if __name__ == "__main__":
    unittest.main(verbosity=2)
