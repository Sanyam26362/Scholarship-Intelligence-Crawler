"""
Dual-Provider LLM Client for Zero-Cost Extraction & Evidence Parsing.
Primary: Google Gemini (gemini-3.8-flash) via official google-genai SDK.
Fallback: Local Ollama (gemma3:4b) via HTTP endpoint.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional
import httpx

from config.settings import settings

logger = logging.getLogger(__name__)


class LLMExtractorClient:
    """Manages LLM queries with primary Gemini and automatic Ollama fallback."""

    def __init__(self) -> None:
        self.gemini_client = None
        self._gemini_quota_exhausted: bool = False
        if settings.gemini_api_key:
            try:
                from google import genai
                self.gemini_client = genai.Client(api_key=settings.gemini_api_key)
            except Exception as e:
                logger.warning("Failed to initialize google-genai client: %s", e)

    def generate(self, prompt: str, temperature: float = 0.0) -> str:
        """
        Executes generation using Gemini 3.8 Flash as primary, falling back to Ollama gemma3:4b.
        """
        import time

        # 1. Try Gemini Primary (if quota is not exhausted)
        if self.gemini_client and not self._gemini_quota_exhausted:
            for attempt in range(2):
                try:
                    response = self.gemini_client.models.generate_content(
                        model=settings.gemini_model,
                        contents=prompt,
                    )
                    if response and response.text:
                        return response.text
                except Exception as e:
                    err_msg = str(e)
                    if "RESOURCE_EXHAUSTED" in err_msg or "429" in err_msg:
                        logger.warning("Gemini free tier quota exhausted. Switching permanently to local Ollama / heuristic fallback.")
                        self._gemini_quota_exhausted = True
                        break
                    elif "503" in err_msg and attempt < 1:
                        time.sleep(1.5)
                        continue
                    else:
                        logger.warning("Gemini call failed (%s). Attempting Ollama fallback...", e)
                        break

        # 2. Try Ollama Fallback
        try:
            url = f"{settings.ollama_base_url.rstrip('/')}/api/generate"
            # Keep prompt focused for fast inference
            truncated_prompt = prompt[:800] if len(prompt) > 800 else prompt
            payload = {
                "model": settings.ollama_model,
                "prompt": truncated_prompt,
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "num_predict": 150,
                },
            }
            with httpx.Client(timeout=8.0) as client:
                res = client.post(url, json=payload)
                res.raise_for_status()
                data = res.json()
                return data.get("response", "")
        except Exception as e:
            logger.warning("Ollama fallback failed or timed out: %s. Using heuristic extractor.", e)
            raise RuntimeError(f"All LLM extraction providers failed: {e}")

    def test_connection(self) -> Dict[str, Any]:
        """Tests availability of both primary and fallback providers."""
        status = {"gemini": False, "ollama": False, "primary_working": False}
        
        # Test Gemini
        if self.gemini_client:
            try:
                res = self.gemini_client.models.generate_content(
                    model=settings.gemini_model, contents="Say READY"
                )
                if "READY" in res.text:
                    status["gemini"] = True
                    status["primary_working"] = True
            except Exception as e:
                status["gemini_error"] = str(e)

        # Test Ollama
        try:
            url = f"{settings.ollama_base_url.rstrip('/')}/api/generate"
            with httpx.Client(timeout=5.0) as client:
                res = client.post(
                    url,
                    json={"model": settings.ollama_model, "prompt": "Say READY", "stream": False},
                )
                if res.status_code == 200 and "READY" in res.json().get("response", ""):
                    status["ollama"] = True
        except Exception as e:
            status["ollama_error"] = str(e)

        return status


# Global LLM Client Singleton
llm_client: LLMExtractorClient = LLMExtractorClient()
