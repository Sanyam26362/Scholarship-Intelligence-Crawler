"""
Canonical Domain Resolver & Source Authority Classifier.
Enforces strict authenticity rules: Aggregators (Buddy4Study, SarkariResult, blogs) are strictly
flagged as non-authoritative pointers, while verified .gov.in, .nic.in, .ac.in, and CSR portals
are granted canonical status.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional, TYPE_CHECKING
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from config.settings import settings
from core.extractor.schema import SourceType

if TYPE_CHECKING:
    from core.discovery.search_agent import SearchAgent


class AuthorityTier(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    REJECTED = "REJECTED"


@dataclass
class SourceClassification:
    url: str
    normalized_url: str
    domain: str
    source_type: SourceType
    authority_tier: AuthorityTier
    domain_score: int
    is_authoritative: bool
    is_aggregator: bool
    explanation: str

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "normalized_url": self.normalized_url,
            "domain": self.domain,
            "source_type": self.source_type.value,
            "authority_tier": self.authority_tier.value,
            "domain_score": self.domain_score,
            "is_authoritative": self.is_authoritative,
            "is_aggregator": self.is_aggregator,
            "explanation": self.explanation,
        }


def clean_url(url: str) -> str:
    """
    Normalizes a URL by stripping marketing tracking query params (utm_*, ref, etc.)
    and standardizing schemes and paths.
    """
    if not url:
        return ""
    try:
        parsed = urlparse(url.strip())
        # Filter tracking query parameters
        filtered_queries = [
            (k, v)
            for k, v in parse_qsl(parsed.query, keep_blank_values=False)
            if not k.lower().startswith("utm_")
            and k.lower() not in ("ref", "fbclid", "gclid", "source", "affiliate")
        ]
        new_query = urlencode(filtered_queries)
        clean_path = parsed.path.rstrip("/") if parsed.path != "/" else "/"
        return urlunparse((
            parsed.scheme.lower() or "https",
            parsed.netloc.lower(),
            clean_path,
            parsed.params,
            new_query,
            "",  # strip fragment
        ))
    except Exception:
        return url.strip()


def extract_domain(url: str) -> str:
    """Extracts lowercase bare domain without port or 'www.' prefix."""
    try:
        netloc = urlparse(url.strip()).netloc.lower()
        if ":" in netloc:
            netloc = netloc.split(":")[0]
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc
    except Exception:
        return ""


def classify_url(url: str) -> SourceClassification:
    """
    Determines whether a URL originates from a canonical authoritative authority
    or an aggregator/unverified domain.
    """
    norm_url = clean_url(url)
    domain = extract_domain(norm_url)

    if not domain:
        return SourceClassification(
            url=url,
            normalized_url=norm_url,
            domain=domain,
            source_type=SourceType.UNVERIFIED,
            authority_tier=AuthorityTier.LOW,
            domain_score=0,
            is_authoritative=False,
            is_aggregator=False,
            explanation="Invalid or unparseable URL domain",
        )

    # 1. Check for Blacklisted Aggregators & Commercial Blogs first
    for agg in settings.aggregator_domains:
        if domain == agg or domain.endswith("." + agg):
            return SourceClassification(
                url=url,
                normalized_url=norm_url,
                domain=domain,
                source_type=SourceType.AGGREGATOR,
                authority_tier=AuthorityTier.REJECTED,
                domain_score=0,
                is_authoritative=False,
                is_aggregator=True,
                explanation=f"Matches known commercial aggregator/blog: {agg}",
            )

    # 2. Check for Central/State Government Domains (.gov.in, .nic.in)
    for gov_suffix in settings.gov_domain_suffixes:
        if domain.endswith(gov_suffix):
            return SourceClassification(
                url=url,
                normalized_url=norm_url,
                domain=domain,
                source_type=SourceType.GOVERNMENT,
                authority_tier=AuthorityTier.HIGH,
                domain_score=30,
                is_authoritative=True,
                is_aggregator=False,
                explanation=f"Canonical Government portal with {gov_suffix} suffix (Domain Score: 30/30)",
            )

    # 3. Check for Apex Bodies and Academic Institutions (.ac.in, .edu.in, .res.in)
    for edu_suffix in settings.edu_domain_suffixes:
        if domain.endswith(edu_suffix):
            source_type = SourceType.APEX_BODY if "aicte" in domain or "ugc" in domain else SourceType.UNIVERSITY
            return SourceClassification(
                url=url,
                normalized_url=norm_url,
                domain=domain,
                source_type=source_type,
                authority_tier=AuthorityTier.HIGH,
                domain_score=28,
                is_authoritative=True,
                is_aggregator=False,
                explanation=f"Accredited Higher Education / Research portal with {edu_suffix} (Domain Score: 28/30)",
            )

    # Special Apex Body handling (e.g., aicte-india.org)
    if domain in ("aicte-india.org", "ugc.ac.in", "ncte.gov.in", "dbtindia.gov.in"):
        return SourceClassification(
            url=url,
            normalized_url=norm_url,
            domain=domain,
            source_type=SourceType.APEX_BODY,
            authority_tier=AuthorityTier.HIGH,
            domain_score=28,
            is_authoritative=True,
            is_aggregator=False,
            explanation=f"Recognized Apex Body portal: {domain} (Domain Score: 28/30)",
        )

    # 4. Check for Verified Corporate CSR & Philanthropic Trusts
    known_csr_types = {
        "tatatrusts.org": SourceType.NGO_TRUST,
        "azimpremjifoundation.org": SourceType.NGO_TRUST,
        "reliancefoundation.org": SourceType.CORPORATE_CSR,
        "adityabirlacapital.com": SourceType.CORPORATE_CSR,
        "adityabirlasolar.com": SourceType.CORPORATE_CSR,
        "infosys.org": SourceType.CORPORATE_CSR,
        "infosysfoundation.org": SourceType.CORPORATE_CSR,
        "wipro.org": SourceType.CORPORATE_CSR,
        "hdfcbank.com": SourceType.CORPORATE_CSR,
        "sbi.co.in": SourceType.CORPORATE_CSR,
        "foundation.licindia.in": SourceType.CORPORATE_CSR,
        "ongcindia.com": SourceType.CORPORATE_CSR,
        "indianoil.in": SourceType.CORPORATE_CSR,
    }
    for csr_dom in settings.verified_csr_domains:
        if domain == csr_dom or domain.endswith("." + csr_dom):
            source_type = known_csr_types.get(csr_dom)
            if not source_type:
                source_type = SourceType.NGO_TRUST if "trust" in csr_dom else SourceType.CORPORATE_CSR
            return SourceClassification(
                url=url,
                normalized_url=norm_url,
                domain=domain,
                source_type=source_type,
                authority_tier=AuthorityTier.HIGH,
                domain_score=25,
                is_authoritative=True,
                is_aggregator=False,
                explanation=f"Verified Corporate CSR / Philanthropic Trust portal: {csr_dom} (Domain Score: 25/30)",
            )

    # 5. Default: Unverified Domain
    return SourceClassification(
        url=url,
        normalized_url=norm_url,
        domain=domain,
        source_type=SourceType.UNVERIFIED,
        authority_tier=AuthorityTier.LOW,
        domain_score=0,
        is_authoritative=False,
        is_aggregator=False,
        explanation=f"Domain {domain} is not in registered canonical whitelists (Domain Score: 0/30)",
    )


def is_canonical_domain(url: str) -> bool:
    """Returns True if the URL originates from an authoritative canonical source."""
    classification = classify_url(url)
    return classification.is_authoritative


def resolve_canonical_source(
    discovered_url: str,
    title: str = "",
    search_agent: Optional[SearchAgent] = None,
) -> Optional[str]:
    """
    Takes any discovered URL and classifies its authority.
    If already canonical, returns the clean canonical URL.
    If an aggregator, triggers a canonical resolution query using SearchAgent
    to locate the authentic governmental or institutional source.
    """
    classification = classify_url(discovered_url)
    if classification.is_authoritative:
        return classification.normalized_url

    if not classification.is_aggregator and classification.domain_score > 0:
        return classification.normalized_url

    # If it is an aggregator or unverified domain and we have search capability
    if search_agent is not None:
        # Formulate query to search for the official source
        # Clean title to extract key scheme name
        clean_title = re.sub(r"(?i)\b(buddy4study|sarkari|result|apply online|eligibility|registration)\b", "", title).strip()
        query = f'"{clean_title}" official website site:gov.in OR site:nic.in OR site:ac.in'
        candidates = search_agent.search(query=query, max_results=5, filter_aggregators=True)
        for cand in candidates:
            cand_url = cand.get("href", "")
            cand_class = classify_url(cand_url)
            if cand_class.is_authoritative:
                return cand_class.normalized_url

    return None
