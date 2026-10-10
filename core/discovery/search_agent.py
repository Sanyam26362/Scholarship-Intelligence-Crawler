"""
Dynamic Discovery Search Agent using ddgs.
Queries web sources for Indian scholarship intelligence with rate-limiting,
canonical domain filtering, and robust error recovery.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

try:
    from ddgs import DDGS
except ImportError:
    from duckduckgo_search import DDGS  # Fallback compatibility

from config.settings import settings
from core.discovery.resolver import classify_url

logger = logging.getLogger(__name__)


class SearchAgent:
    """
    Search agent wrapper over ddgs with polite pacing, canonical classification,
    and automatic retry backoff.
    """

    def __init__(self, rate_limit_delay: Optional[float] = None) -> None:
        self.rate_limit_delay = rate_limit_delay if rate_limit_delay is not None else settings.ddgs_rate_limit_delay
        self._last_call_timestamp: float = 0.0

    def _wait_for_rate_limit(self) -> None:
        """Enforces minimum delay between search engine queries."""
        elapsed = time.time() - self._last_call_timestamp
        if elapsed < self.rate_limit_delay:
            sleep_duration = self.rate_limit_delay - elapsed
            time.sleep(sleep_duration)
        self._last_call_timestamp = time.time()

    def search(
        self,
        query: str,
        max_results: int = 10,
        filter_aggregators: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Executes a dynamic search with polite rate limiting and enriches results
        with source authority classifications.
        """
        results: List[Dict[str, Any]] = []
        retries = 0
        backoff = 2.0

        while retries <= settings.max_retries:
            try:
                self._wait_for_rate_limit()
                with DDGS() as ddgs:
                    raw_results = list(
                        ddgs.text(
                            keywords=query,
                            region="in-en",
                            safesearch="moderate",
                            max_results=max_results,
                        )
                    )

                for item in raw_results:
                    href = item.get("href") or item.get("link") or ""
                    title = item.get("title") or ""
                    snippet = item.get("body") or item.get("snippet") or ""

                    classification = classify_url(href)

                    if filter_aggregators and classification.is_aggregator:
                        continue

                    results.append({
                        "title": title,
                        "href": href,
                        "body": snippet,
                        "classification": classification.to_dict(),
                        "is_authoritative": classification.is_authoritative,
                        "domain_score": classification.domain_score,
                    })

                return results

            except Exception as e:
                retries += 1
                logger.warning(
                    "Search error on query '%s' (attempt %d/%d): %s",
                    query,
                    retries,
                    settings.max_retries,
                    str(e),
                )
                if retries > settings.max_retries:
                    logger.error("Max retries exceeded for query '%s'", query)
                    break
                time.sleep(backoff)
                backoff *= 2.0

        return results

    def discover_from_seeds(self, max_per_pattern: int = 5) -> List[Dict[str, Any]]:
        """
        Executes discovery patterns from configured seed sources to find authentic opportunities.
        """
        seeds = settings.get_seed_list()
        discovered: List[Dict[str, Any]] = []
        seen_urls = set()

        for seed in seeds:
            patterns = seed.get("discovery_patterns", [])
            for pattern in patterns:
                res_list = self.search(pattern, max_results=max_per_pattern, filter_aggregators=True)
                for item in res_list:
                    url = item.get("href")
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        discovered.append({
                            **item,
                            "seed_source": seed.get("name"),
                            "seed_category": seed.get("category_name"),
                        })

        return discovered

    def find_canonical_for_scholarship(
        self, scheme_name: str, provider: str = ""
    ) -> Optional[str]:
        """
        Queries specifically for the canonical government or official portal for an identified scheme.
        """
        clean_scheme = scheme_name.replace('"', "").strip()
        clean_provider = provider.replace('"', "").strip()
        query = f'"{clean_scheme}" {clean_provider} (site:gov.in OR site:nic.in OR site:ac.in OR "official website")'
        
        results = self.search(query, max_results=5, filter_aggregators=True)
        for r in results:
            url = r.get("href", "")
            classification = classify_url(url)
            if classification.is_authoritative:
                return classification.normalized_url

        return None


def search_scholarships(query: str, max_results: int = 10) -> List[Dict[str, Any]]:
    """Convenience helper to run a scholarship search with default SearchAgent."""
    agent = SearchAgent()
    return agent.search(query=query, max_results=max_results)
