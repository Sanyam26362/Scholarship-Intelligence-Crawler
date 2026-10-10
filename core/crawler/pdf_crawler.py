"""
PDF Guidelines and Circulars Crawler for Atlas Scholarship Intelligence.
Downloads and extracts clean text from official PDF circulars using pypdf.
"""
from __future__ import annotations

import hashlib
import io
import logging
import re
import time
from dataclasses import dataclass
from typing import Optional
import httpx
from pypdf import PdfReader

from config.settings import settings

logger = logging.getLogger(__name__)


@dataclass
class PDFCrawlResult:
    url: str
    clean_text: str
    page_count: int
    raw_hash: str
    status_code: int
    response_time: float
    error: Optional[str] = None


class PDFCrawler:
    """Downloads and parses PDF guideline circulars from Indian educational/government portals."""

    def __init__(self, timeout: Optional[float] = None, max_size_mb: float = 20.0) -> None:
        self.timeout = timeout if timeout is not None else settings.http_timeout
        self.max_bytes = int(max_size_mb * 1024 * 1024)
        self.headers = {
            "User-Agent": settings.user_agent,
            "Accept": "application/pdf,*/*",
        }

    def fetch_and_extract(self, url: str) -> PDFCrawlResult:
        """Downloads PDF and extracts clean text from all pages."""
        start = time.time()
        try:
            with httpx.Client(
                timeout=self.timeout,
                follow_redirects=True,
                headers=self.headers,
                verify=False,
            ) as client:
                res = client.get(url)
                duration = time.time() - start

                if res.status_code != 200:
                    return PDFCrawlResult(
                        url=url,
                        clean_text="",
                        page_count=0,
                        raw_hash="",
                        status_code=res.status_code,
                        response_time=duration,
                        error=f"HTTP {res.status_code}",
                    )

                pdf_bytes = res.content
                if len(pdf_bytes) > self.max_bytes:
                    return PDFCrawlResult(
                        url=url,
                        clean_text="",
                        page_count=0,
                        raw_hash="",
                        status_code=res.status_code,
                        response_time=duration,
                        error=f"PDF size {len(pdf_bytes)} exceeds limit of {self.max_bytes} bytes",
                    )

                reader = PdfReader(io.BytesIO(pdf_bytes))
                page_count = len(reader.pages)
                extracted_pages = []

                for i, page in enumerate(reader.pages):
                    page_text = page.extract_text() or ""
                    if page_text.strip():
                        extracted_pages.append(page_text.strip())

                raw_combined = "\n\n".join(extracted_pages)
                clean_text = re.sub(r"\n{3,}", "\n\n", raw_combined).strip()
                raw_hash = hashlib.sha256(clean_text.encode("utf-8")).hexdigest()

                return PDFCrawlResult(
                    url=url,
                    clean_text=clean_text,
                    page_count=page_count,
                    raw_hash=raw_hash,
                    status_code=res.status_code,
                    response_time=duration,
                )

        except Exception as e:
            logger.error("Failed to parse PDF from %s: %s", url, e)
            return PDFCrawlResult(
                url=url,
                clean_text="",
                page_count=0,
                raw_hash="",
                status_code=0,
                response_time=time.time() - start,
                error=str(e),
            )


def fetch_pdf(url: str) -> PDFCrawlResult:
    """Convenience helper to crawl a PDF."""
    crawler = PDFCrawler()
    return crawler.fetch_and_extract(url)
