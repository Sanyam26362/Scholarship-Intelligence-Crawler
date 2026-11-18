"""
Core configuration and environment management for Atlas Scholarship Intelligence Engine.
Loads environment variables safely via python-dotenv and centralizes system parameters.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml
from dotenv import load_dotenv

# Base Project Directory
BASE_DIR: Path = Path(__file__).resolve().parent.parent

# Safely load .env file from project root
ENV_FILE: Path = BASE_DIR / ".env"
if ENV_FILE.exists():
    load_dotenv(dotenv_path=ENV_FILE, override=True)
else:
    load_dotenv(override=False)


def _get_env_or_secret(key: str, default: Optional[str] = None) -> Optional[str]:
    """Reads config from environment variables, falling back to Streamlit Cloud st.secrets if available."""
    val = os.getenv(key)
    if val is not None and str(val).strip() != "":
        return str(val).strip()
    try:
        import streamlit as st
        if key in st.secrets:
            secret_val = st.secrets[key]
            if secret_val is not None and str(secret_val).strip() != "":
                return str(secret_val).strip()
    except Exception:
        pass
    return default


class Settings:
    """Central settings object loaded from environment variables and static configuration."""

    def __init__(self) -> None:
        # Paths
        self.base_dir: Path = BASE_DIR
        raw_db_path = _get_env_or_secret("DB_PATH", "data/scholarships.db") or "data/scholarships.db"
        self.db_path: Path = (
            Path(raw_db_path) if Path(raw_db_path).is_absolute() else BASE_DIR / raw_db_path
        )
        self.seed_sources_path: Path = BASE_DIR / "config" / "seed_sources.yaml"
        self.data_dir: Path = self.db_path.parent

        # Ensure essential directories exist
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Primary LLM Provider: Google Gemini
        self.gemini_api_key: Optional[str] = _get_env_or_secret("GEMINI_API_KEY")
        self.gemini_model: str = _get_env_or_secret("GEMINI_MODEL", "gemini-3.8-flash") or "gemini-3.8-flash"

        # Fallback LLM Provider: Local Ollama
        self.ollama_model: str = _get_env_or_secret("OLLAMA_MODEL", "gemma3:4b") or "gemma3:4b"
        self.ollama_base_url: str = _get_env_or_secret("OLLAMA_BASE_URL", "http://localhost:11434") or "http://localhost:11434"

        # Network & Scraping Limits
        self.ddgs_rate_limit_delay: float = float(os.getenv("DDGS_RATE_LIMIT_DELAY", "1.5"))
        self.http_timeout: float = float(os.getenv("HTTP_TIMEOUT", "15.0"))
        self.max_retries: int = int(os.getenv("MAX_RETRIES", "3"))
        self.user_agent: str = (
            os.getenv("USER_AGENT")
            or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36 (AtlasScholarshipVerifier/1.0)"
        )

        # Verification & Scoring Engine Thresholds
        self.verification_threshold: float = float(os.getenv("VERIFICATION_THRESHOLD", "95.0"))
        self.min_domain_authority_for_verified: int = int(
            os.getenv("MIN_DOMAIN_AUTHORITY_FOR_VERIFIED", "25")
        )

        # Canonical Domain Authority Classifications
        self.gov_domain_suffixes: List[str] = [".gov.in", ".nic.in"]
        self.edu_domain_suffixes: List[str] = [".ac.in", ".edu.in", ".res.in"]
        
        # Verified CSR & Philanthropic Trust Domains
        self.verified_csr_domains: List[str] = [
            "tatatrusts.org",
            "reliancefoundation.org",
            "adityabirlacapital.com",
            "adityabirlasolar.com",
            "infosys.org",
            "infosysfoundation.org",
            "azimpremjifoundation.org",
            "wipro.org",
            "hdfcbank.com",
            "sbi.co.in",
            "foundation.licindia.in",
            "ongcindia.com",
            "indianoil.in",
            "drdo.gov.in",
            "isro.gov.in",
            "csir.res.in",
            "dbtindia.gov.in",
            "dst.gov.in",
        ]

        # Blacklisted Aggregators & Commercial Blogs (discovery pointers only; not authoritative)
        self.aggregator_domains: List[str] = [
            "buddy4study.com",
            "sarkariresult.com",
            "shiksha.com",
            "collegedunia.com",
            "careers360.com",
            "jagranjosh.com",
            "freshersworld.com",
            "indgovtjobs.in",
            "freejobalert.com",
            "studycafe.in",
            "testbook.com",
            "adda247.com",
            "byjus.com",
            "unstop.com",
            "scholarshipsinindia.com",
            "blogspot.com",
            "wordpress.com",
            "medium.com",
            "quora.com",
        ]

    def load_seeds(self) -> Dict[str, Any]:
        """Loads registered seed sources from YAML."""
        if not self.seed_sources_path.exists():
            return {}
        with open(self.seed_sources_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def get_seed_list(self) -> List[Dict[str, Any]]:
        """Flattens seed categories into a single list of source records."""
        data = self.load_seeds()
        categories = data.get("categories", {})
        seed_list: List[Dict[str, Any]] = []
        for cat_key, cat_data in categories.items():
            cat_name = cat_data.get("name", cat_key)
            for src in cat_data.get("sources", []):
                src_copy = dict(src)
                src_copy["category_name"] = cat_name
                src_copy["category_key"] = cat_key
                seed_list.append(src_copy)
        return seed_list


# Global Settings Singleton
settings: Settings = Settings()
