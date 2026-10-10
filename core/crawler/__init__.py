"""
Crawler package for HTML and PDF guidelines extraction.
"""
from core.crawler.html_crawler import HTMLCrawler, CrawlResult, fetch_html
from core.crawler.pdf_crawler import PDFCrawler, PDFCrawlResult, fetch_pdf

__all__ = [
    "HTMLCrawler",
    "CrawlResult",
    "fetch_html",
    "PDFCrawler",
    "PDFCrawlResult",
    "fetch_pdf",
]
