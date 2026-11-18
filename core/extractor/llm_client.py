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
        self._gemini_consecutive_failures: int = 0
        self._ollama_unavailable: bool = False
        if settings.gemini_api_key:
            try:
                from google import genai
                from google.genai import types

                self.gemini_client = genai.Client(
                    api_key=settings.gemini_api_key,
                    http_options=types.HttpOptions(
                        timeout=12000,
                        retry_options=types.HttpRetryOptions(attempts=1),
                    ),
                )
            except Exception as e:
                logger.warning("Failed to initialize google-genai client: %s", e)

    def reset_circuit_breakers(self) -> None:
        """Resets provider circuit breakers for a fresh pipeline run."""
        self._gemini_quota_exhausted = False
        self._gemini_consecutive_failures = 0
        self._ollama_unavailable = False

    def generate(self, prompt: str, temperature: float = 0.0) -> str:
        """
        Executes generation using Gemini 3.8 Flash as primary, falling back to Ollama gemma3:4b.
        Uses fast circuit breakers so unreachable cloud/local providers never hang batch runs.
        """
        import time

        # 1. Try Gemini Primary (if quota/circuit breaker is not tripped)
        if self.gemini_client and not self._gemini_quota_exhausted:
            for attempt in range(2):
                try:
                    response = self.gemini_client.models.generate_content(
                        model=settings.gemini_model,
                        contents=prompt,
                    )
                    if response and response.text:
                        self._gemini_consecutive_failures = 0
                        return response.text
                except Exception as e:
                    err_msg = str(e)
                    err_upper = err_msg.upper()
                    if (
                        "RESOURCE_EXHAUSTED" in err_upper
                        or "429" in err_msg
                        or "API_KEY_INVALID" in err_upper
                        or "PERMISSION_DENIED" in err_upper
                        or "401" in err_msg
                        or "403" in err_msg
                        or "404" in err_msg
                        or "NOT_FOUND" in err_upper
                    ):
                        logger.warning(
                            "Gemini unavailable or quota exhausted (%s). Tripping circuit breaker to local Ollama / heuristic fallback.",
                            err_msg[:120],
                        )
                        self._gemini_quota_exhausted = True
                        break
                    elif "503" in err_msg and attempt < 1:
                        time.sleep(1.0)
                        continue
                    else:
                        self._gemini_consecutive_failures += 1
                        logger.warning("Gemini call failed (%s). Attempting Ollama fallback...", err_msg[:120])
                        if self._gemini_consecutive_failures >= 2:
                            logger.warning("Gemini failed %d times consecutively. Tripping circuit breaker.", self._gemini_consecutive_failures)
                            self._gemini_quota_exhausted = True
                        break

        # 2. Try Ollama Fallback (only if not already marked unavailable)
        if not self._ollama_unavailable:
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
                timeout = httpx.Timeout(connect=1.5, read=5.0, write=2.0, pool=1.5)
                with httpx.Client(timeout=timeout) as client:
                    res = client.post(url, json=payload)
                    res.raise_for_status()
                    data = res.json()
                    return data.get("response", "")
            except Exception as e:
                self._ollama_unavailable = True
                logger.warning("Ollama fallback unavailable/timed out (%s). Tripping circuit breaker to heuristic extractor.", e)
                raise RuntimeError(f"All LLM extraction providers failed: {e}")

        raise RuntimeError("All LLM extraction providers currently unavailable (circuit breakers active).")

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
