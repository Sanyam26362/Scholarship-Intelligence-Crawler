"""
Discovery and domain resolution package.
"""
from core.discovery.resolver import (
    AuthorityTier,
    SourceClassification,
    classify_url,
    is_canonical_domain,
    clean_url,
    resolve_canonical_source,
)
from core.discovery.search_agent import SearchAgent, search_scholarships

__all__ = [
    "AuthorityTier",
    "SourceClassification",
    "classify_url",
    "is_canonical_domain",
    "clean_url",
    "resolve_canonical_source",
    "SearchAgent",
    "search_scholarships",
]
