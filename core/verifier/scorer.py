"""
Deterministic Mathematical Confidence Scoring Engine.
Calculates explainable 100-point score without LLM hallucinations.
Gate Rule: Total >= 95.0% AND Domain Authority >= 25 -> VERIFIED; otherwise REVIEW_REQUIRED.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse
from dateutil import parser as date_parser

from config.settings import settings
from core.discovery.resolver import classify_url, extract_domain
from core.extractor.schema import ScholarshipRecord, ScholarshipStatus


@dataclass
class ScoringBreakdown:
    domain_authority: Dict[str, Any]
    application_authenticity: Dict[str, Any]
    evidence_grounding: Dict[str, Any]
    deadline_verifiability: Dict[str, Any]
    host_health: Dict[str, Any]
    anti_conflict: Dict[str, Any]
    total_score: float
    threshold: float
    status: str
    gate_passed: bool

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def evaluate_deadline_format(date_str: Optional[str]) -> Tuple[int, str]:
    """
    Evaluates closing date string:
    - 15 pts: Unambiguous date format extracted with context
    - 5 pts: Ambiguous / 'Check notification' / tentative
    - 0 pts: Missing / 'Not specified'
    """
    if not date_str or date_str.strip().lower() in ("not specified", "none", "", "null"):
        return 0, "Missing deadline date (0/15)"

    cleaned = date_str.strip()
    ambiguous_keywords = [
        "check notification",
        "tentative",
        "announcement",
        "to be announced",
        "tba",
        "tbd",
        "varies",
        "open throughout",
        "subject to",
        "refer to portal",
    ]
    if any(k in cleaned.lower() for k in ambiguous_keywords):
        return 5, f"Ambiguous deadline specification '{cleaned}' (5/15)"

    # Check for structured date patterns
    iso_or_slash = re.search(r"\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b|\b\d{1,2}[-/]\d{1,2}[-/]\d{4}\b", cleaned)
    named_month = re.search(
        r"\b\d{1,2}(?:st|nd|rd|th)?\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{4}\b",
        cleaned,
        re.IGNORECASE,
    )

    if iso_or_slash or named_month:
        return 15, f"Unambiguous date format detected '{cleaned}' (15/15)"

    # Try standard dateutil parser
    try:
        date_parser.parse(cleaned, fuzzy=True)
        return 15, f"Parseable date format '{cleaned}' (15/15)"
    except Exception:
        pass

    return 5, f"Semi-structured deadline string '{cleaned}' (5/15)"


def evaluate_application_url(
    application_url: Optional[str], official_source_url: str
) -> Tuple[int, str]:
    """
    Evaluates application link authenticity:
    - 20 pts: Official application portal or registered domain gateway
    - 0 pts: Third-party, aggregator, or missing application URL
    """
    if not application_url or application_url.strip().lower() in ("not specified", "none", "", "null"):
        return 0, "Missing direct application URL (0/20)"

    app_clean = application_url.strip()
    app_dom = extract_domain(app_clean)
    source_dom = extract_domain(official_source_url)

    if not app_dom:
        return 0, "Malformed application URL (0/20)"

    # Check if application URL points to a known aggregator
    for agg in settings.aggregator_domains:
        if app_dom == agg or app_dom.endswith("." + agg):
            return 0, f"Application link points to aggregator {agg} (0/20)"

    # If same domain or subdomain
    if app_dom == source_dom or app_dom.endswith("." + source_dom) or source_dom.endswith("." + app_dom):
        return 20, f"Official in-domain application gateway: {app_dom} (20/20)"

    # If application domain is an authoritative government/apex portal
    app_class = classify_url(app_clean)
    if app_class.is_authoritative:
        return 20, f"Official registered gateway domain: {app_dom} (20/20)"

    return 0, f"Third-party or unverified application URL {app_dom} (0/20)"


def calculate_confidence_score(
    record: ScholarshipRecord,
    raw_content: Optional[str] = None,
    http_status_code: int = 200,
    response_time_sec: float = 0.5,
    has_conflicting_guidelines: bool = False,
) -> Tuple[float, str, Dict[str, Any]]:
    """
    Computes exact, explainable 100-point score:
    1. Domain Authority: 30 pts max
    2. Application Link Authenticity: 20 pts max
    3. Eligibility Evidence Grounding: 20 pts max
    4. Deadline Verifiability & Format: 15 pts max
    5. Host Reachability & HTTP Health: 10 pts max
    6. Consistency & Anti-Conflict: 5 pts max

    Gate Rule:
    Total >= 95.0% AND Domain Authority >= 25 -> VERIFIED; otherwise REVIEW_REQUIRED.
    """
    # 1. Domain Authority (30 pts max)
    classification = classify_url(record.official_source_url)
    domain_pts = classification.domain_score
    domain_reason = classification.explanation

    # 2. Application Link Authenticity (20 pts max)
    app_pts, app_reason = evaluate_application_url(
        record.application_url, record.official_source_url
    )

    # 3. Eligibility Evidence Grounding (20 pts max)
    # Check if eligibility criteria is specified and backed by verbatim evidence
    evidence_pts = 0
    evidence_reason = "Missing verbatim evidence quote for eligibility criteria (0/20)"
    if (
        record.eligibility_criteria
        and record.eligibility_criteria != "Not specified"
    ):
        # Look up eligibility_criteria evidence in evidence_map
        ev = record.evidence_map.get("eligibility_criteria")
        if ev and ev.quote:
            # If raw content is provided, verify substring match
            if raw_content:
                if ev.is_grounded_in(raw_content):
                    evidence_pts = 20
                    evidence_reason = "Verbatim text proof verified against source document (20/20)"
                else:
                    evidence_pts = 0
                    evidence_reason = "Evidence quote was not found verbatim in raw page content (0/20)"
            else:
                # If raw_content is not provided, quote is recorded
                evidence_pts = 20
                evidence_reason = f"Verbatim quote recorded: '{ev.quote[:60]}...' (20/20)"
        else:
            evidence_pts = 0
            evidence_reason = "No verbatim evidence quote provided in evidence_map (0/20)"

    # 4. Deadline Verifiability & Format (15 pts max)
    deadline_pts, deadline_reason = evaluate_deadline_format(record.closing_date)

    # 5. Host Reachability & HTTP Health (10 pts max)
    if http_status_code == 200 and response_time_sec <= 5.0:
        health_pts = 10
        health_reason = f"Live HTTP 200 response in {response_time_sec:.2f}s (10/10)"
    elif 200 <= http_status_code < 400:
        health_pts = 5
        health_reason = f"Redirect or slow HTTP {http_status_code} ({response_time_sec:.2f}s) (5/10)"
    else:
        health_pts = 0
        health_reason = f"Host unreachable or returned HTTP {http_status_code} (0/10)"

    # 6. Consistency & Anti-Conflict (5 pts max)
    if not has_conflicting_guidelines:
        conflict_pts = 5
        conflict_reason = "No conflicting eligibility guidelines detected (5/5)"
    else:
        conflict_pts = 0
        conflict_reason = "Conflicting guidelines or dates detected in documentation (0/5)"

    # Total Score
    total_score = float(domain_pts + app_pts + evidence_pts + deadline_pts + health_pts + conflict_pts)
    total_score = round(min(100.0, max(0.0, total_score)), 2)

    # Gate Rule: Total >= 95.0% AND Domain Authority >= 25 -> VERIFIED
    gate_passed = (total_score >= settings.verification_threshold) and (domain_pts >= settings.min_domain_authority_for_verified)
    status = ScholarshipStatus.VERIFIED.value if gate_passed else ScholarshipStatus.REVIEW_REQUIRED.value

    breakdown = {
        "domain_authority": {"points": domain_pts, "max": 30, "reason": domain_reason},
        "application_authenticity": {"points": app_pts, "max": 20, "reason": app_reason},
        "evidence_grounding": {"points": evidence_pts, "max": 20, "reason": evidence_reason},
        "deadline_verifiability": {"points": deadline_pts, "max": 15, "reason": deadline_reason},
        "host_health": {"points": health_pts, "max": 10, "reason": health_reason},
        "anti_conflict": {"points": conflict_pts, "max": 5, "reason": conflict_reason},
        "total_score": total_score,
        "threshold": settings.verification_threshold,
        "status": status,
        "gate_passed": gate_passed,
    }

    return total_score, status, breakdown
