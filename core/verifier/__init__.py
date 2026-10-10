"""
Verifier and scoring engine package.
"""
from core.verifier.scorer import (
    ScoringBreakdown,
    calculate_confidence_score,
    evaluate_deadline_format,
    evaluate_application_url,
)
from core.verifier.verifier import ScholarshipVerifier, verify_scholarship_candidate

__all__ = [
    "ScoringBreakdown",
    "calculate_confidence_score",
    "evaluate_deadline_format",
    "evaluate_application_url",
    "ScholarshipVerifier",
    "verify_scholarship_candidate",
]
