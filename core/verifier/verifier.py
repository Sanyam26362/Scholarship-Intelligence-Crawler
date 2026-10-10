"""
Scholarship Verification Coordinator.
Integrates network reachability checks, verbatim evidence quote verification,
and deterministic confidence scoring.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional, Tuple
import httpx

from config.settings import settings
from core.extractor.schema import ScholarshipRecord
from core.verifier.scorer import calculate_confidence_score

logger = logging.getLogger(__name__)


class ScholarshipVerifier:
    """Coordinates reachability checks and score calculation for scholarship records."""

    def __init__(self, timeout: Optional[float] = None) -> None:
        self.timeout = timeout if timeout is not None else settings.http_timeout

    def check_http_health(self, url: str) -> Tuple[int, float]:
        """
        Executes a polite HEAD/GET request to evaluate host reachability and latency.
        """
        start = time.time()
        try:
            with httpx.Client(
                timeout=self.timeout,
                follow_redirects=True,
                headers={"User-Agent": settings.user_agent},
                verify=False,  # Allow self-signed or legacy gov certs if needed
            ) as client:
                resp = client.get(url)
                duration = time.time() - start
                return resp.status_code, duration
        except httpx.HTTPStatusError as e:
            return e.response.status_code, time.time() - start
        except Exception as e:
            logger.warning("HTTP health check failed for %s: %s", url, str(e))
            return 0, time.time() - start

    def verify(
        self,
        record: ScholarshipRecord,
        raw_content: Optional[str] = None,
        perform_live_http_check: bool = False,
    ) -> ScholarshipRecord:
        """
        Evaluates a scholarship candidate record, runs deterministic scoring,
        and annotates the record with score, breakdown, and lifecycle status.
        """
        http_status = 200
        latency = 0.4

        if perform_live_http_check:
            http_status, latency = self.check_http_health(record.official_source_url)

        score, status, breakdown = calculate_confidence_score(
            record=record,
            raw_content=raw_content,
            http_status_code=http_status,
            response_time_sec=latency,
            has_conflicting_guidelines=False,
        )

        record.confidence_score = score
        record.status = status
        record.score_breakdown = breakdown
        return record


def verify_scholarship_candidate(
    record: ScholarshipRecord,
    raw_content: Optional[str] = None,
    perform_live_http_check: bool = False,
) -> ScholarshipRecord:
    """Convenience functional interface to verify and score a scholarship candidate."""
    verifier = ScholarshipVerifier()
    return verifier.verify(
        record,
        raw_content=raw_content,
        perform_live_http_check=perform_live_http_check,
    )
