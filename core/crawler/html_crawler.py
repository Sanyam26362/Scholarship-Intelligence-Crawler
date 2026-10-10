"""
Resilient HTML Web Crawler for Atlas Scholarship Intelligence.
Employs HTTPX with automatic fallback to Playwright Chromium for dynamic JavaScript-rendered portals.
Strips boilerplate and computes content hashes for deduplication and delta tracking.
"""
from __future__ import annotations

import hashlib
import logging
import random
import re
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse
from bs4 import BeautifulSoup
import httpx

from config.settings import settings

logger = logging.getLogger(__name__)


@dataclass
class CrawlResult:
    url: str
    canonical_url: str
    title: str
    clean_text: str
    raw_hash: str
    status_code: int
    response_time: float
    used_playwright: bool
    error: Optional[str] = None


class HTMLCrawler:
    """Fetches web pages via HTTPX with Playwright fallback for SPA/JS pages."""

    def __init__(self, timeout: Optional[float] = None) -> None:
        self.timeout = timeout if timeout is not None else 6.0
        self.headers = {
            "User-Agent": settings.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "DNT": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
        }

    def _clean_html(self, html_content: str) -> tuple[str, str]:
        """
        Parses HTML, removes navigation, footer, and scripts,
        and returns (clean_text, title).
        """
        if not html_content:
            return "", ""

        soup = BeautifulSoup(html_content, "html.parser")

        # Extract title
        title = soup.title.string.strip() if soup.title and soup.title.string else ""

        # Remove irrelevant noise tags
        for tag in soup(["script", "style", "noscript", "svg", "nav", "footer", "iframe", "header"]):
            tag.decompose()

        # Preserve structured text from headings, paragraphs, lists, and tables
        text_lines = []
        for element in soup.find_all(["h1", "h2", "h3", "h4", "p", "li", "td", "th", "div"]):
            txt = element.get_text(separator=" ", strip=True)
            if txt and len(txt) > 2:
                text_lines.append(txt)

        # Remove duplicates while preserving order
        seen = set()
        deduped = []
        for line in text_lines:
            if line not in seen:
                seen.add(line)
                deduped.append(line)

        raw_combined = "\n".join(deduped)
        cleaned_text = re.sub(r"\n{3,}", "\n\n", raw_combined).strip()
        return cleaned_text, title

    def _fetch_with_playwright(self, url: str) -> tuple[str, str, int, float]:
        """Fetches page using Playwright Chromium headless."""
        from playwright.sync_api import sync_playwright

        start = time.time()
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent=settings.user_agent)
            page.set_default_timeout(4000)

            resp = page.goto(url, wait_until="domcontentloaded")
            # Wait briefly for dynamic elements
            page.wait_for_timeout(400)

            content = page.content()
            status = resp.status if resp else 200
            browser.close()
            duration = time.time() - start
            return content, page.url, status, duration

    def fetch(self, url: str, force_playwright: bool = False) -> CrawlResult:
        """
        Executes resilient fetch with polite delay, HTML stripping,
        and content hashing.
        """
        # Randomized polite delay between 0.8s and 1.5s
        time.sleep(random.uniform(0.8, 1.5))
        start_time = time.time()

        if force_playwright:
            try:
                raw_html, final_url, status, duration = self._fetch_with_playwright(url)
                clean_text, title = self._clean_html(raw_html)
                raw_hash = hashlib.sha256(clean_text.encode("utf-8")).hexdigest()
                return CrawlResult(
                    url=url,
                    canonical_url=final_url,
                    title=title,
                    clean_text=clean_text,
                    raw_hash=raw_hash,
                    status_code=status,
                    response_time=duration,
                    used_playwright=True,
                )
            except Exception as e:
                logger.error("Playwright fetch failed for %s: %s", url, e)
                return CrawlResult(
                    url=url,
                    canonical_url=url,
                    title="",
                    clean_text="",
                    raw_hash="",
                    status_code=0,
                    response_time=time.time() - start_time,
                    used_playwright=True,
                    error=str(e),
                )

        # 1. Attempt fast static HTTPX request
        try:
            with httpx.Client(
                timeout=self.timeout,
                follow_redirects=True,
                headers=self.headers,
                verify=False,
            ) as client:
                res = client.get(url)
                duration = time.time() - start_time

                if res.status_code == 200:
                    clean_text, title = self._clean_html(res.text)
                    if len(clean_text) >= 200:
                        raw_hash = hashlib.sha256(clean_text.encode("utf-8")).hexdigest()
                        return CrawlResult(
                            url=url,
                            canonical_url=str(res.url),
                            title=title,
                            clean_text=clean_text,
                            raw_hash=raw_hash,
                            status_code=res.status_code,
                            response_time=duration,
                            used_playwright=False,
                        )
                elif res.status_code in (404, 500, 502, 503, 403):
                    return CrawlResult(
                        url=url,
                        canonical_url=str(res.url),
                        title="",
                        clean_text="",
                        raw_hash="",
                        status_code=res.status_code,
                        response_time=duration,
                        used_playwright=False,
                        error=f"HTTP {res.status_code}",
                    )

            # If static returned thin content, fallback to Playwright only if requested or likely JS SPA
            raw_html, final_url, status, duration = self._fetch_with_playwright(url)
            clean_text, title = self._clean_html(raw_html)
            raw_hash = hashlib.sha256(clean_text.encode("utf-8")).hexdigest()
            return CrawlResult(
                url=url,
                canonical_url=final_url,
                title=title,
                clean_text=clean_text,
                raw_hash=raw_hash,
                status_code=status,
                response_time=duration,
                used_playwright=True,
            )

        except Exception as exc:
            logger.warning("HTTPX error for %s (%s). Falling back to Playwright...", url, exc)
            try:
                raw_html, final_url, status, duration = self._fetch_with_playwright(url)
                clean_text, title = self._clean_html(raw_html)
                raw_hash = hashlib.sha256(clean_text.encode("utf-8")).hexdigest()
                return CrawlResult(
                    url=url,
                    canonical_url=final_url,
                    title=title,
                    clean_text=clean_text,
                    raw_hash=raw_hash,
                    status_code=status,
                    response_time=duration,
                    used_playwright=True,
                )
            except Exception as pw_exc:
                logger.error("Both HTTPX and Playwright failed for %s: %s", url, pw_exc)
                return CrawlResult(
                    url=url,
                    canonical_url=url,
                    title="",
                    clean_text="",
                    raw_hash="",
                    status_code=0,
                    response_time=time.time() - start_time,
                    used_playwright=True,
                    error=f"HTTPX: {exc} | Playwright: {pw_exc}",
                )


def fetch_html(url: str, force_playwright: bool = False) -> CrawlResult:
    """Convenience helper to crawl an HTML page."""
    crawler = HTMLCrawler()
    return crawler.fetch(url, force_playwright=force_playwright)
