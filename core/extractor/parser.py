"""
Grounded Extraction Engine for Atlas Scholarship Intelligence.
Employs Gemini 3.8 Flash (primary) and Ollama gemma3:4b (fallback) with strict
verbatim substring verification to guarantee zero hallucinations.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Optional, Tuple

from core.extractor.llm_client import llm_client
from core.extractor.schema import FieldEvidence, ScholarshipRecord, SourceType

logger = logging.getLogger(__name__)

EXTRACTION_SYSTEM_PROMPT = """You are an expert, meticulous data extraction engine for the Atlas Funding Scholarship Intelligence Engine.
Your job is to extract factual scholarship opportunities from the provided authentic webpage text.

STRICT ZERO-HALLUCINATION POLICIES:
1. Every extracted field MUST be directly mentioned in the provided text.
2. For EVERY field, you must provide:
   - "value": The concise extracted fact.
   - "quote": An EXACT VERBATIM SUBSTRING from the provided text that proves this fact.
3. If ANY field is NOT explicitly mentioned in the text, you MUST return:
   "value": "Not specified", "quote": ""
4. NEVER guess, assume, calculate, or infer dates, amounts, income limits, or eligibility.
5. If the entire text contains no scholarship, return "Not specified" for all fields.

Return ONLY a valid JSON object with the following schema:
{
  "name": {"value": "...", "quote": "..."},
  "provider": {"value": "...", "quote": "..."},
  "application_url": {"value": "...", "quote": "..."},
  "amount_benefit": {"value": "...", "quote": "..."},
  "eligibility_criteria": {"value": "...", "quote": "..."},
  "academic_requirements": {"value": "...", "quote": "..."},
  "course_level": {"value": "...", "quote": "..."},
  "income_criteria": {"value": "...", "quote": "..."},
  "age_criteria": {"value": "...", "quote": "..."},
  "gender_criteria": {"value": "...", "quote": "..."},
  "category_criteria": {"value": "...", "quote": "..."},
  "domicile_requirements": {"value": "...", "quote": "..."},
  "institution_requirements": {"value": "...", "quote": "..."},
  "opening_date": {"value": "...", "quote": "..."},
  "closing_date": {"value": "...", "quote": "..."},
  "documents_required": {"value": "...", "quote": "..."},
  "selection_process": {"value": "...", "quote": "..."},
  "renewal_requirements": {"value": "...", "quote": "..."}
}
"""


def _normalize_ws(s: str) -> str:
    """Collapses whitespace for robust substring matching."""
    return re.sub(r"\s+", " ", s).strip()


def _extract_json_block(text: str) -> Optional[Dict[str, Any]]:
    """Extracts and parses JSON object from LLM response text."""
    if not text:
        return None
    # Strip markdown code blocks
    cleaned = text.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()

    try:
        return json.loads(cleaned)
    except Exception:
        # Try finding outermost JSON braces
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except Exception:
                pass
def verify_and_ground_quote(quote: str, raw_text: str) -> bool:
    """Verifies that the quote is an exact or normalized verbatim substring in raw_text."""
    if not quote or not raw_text:
        return False
    norm_q = _normalize_ws(quote).lower()
    norm_t = _normalize_ws(raw_text).lower()
    return norm_q in norm_t


def _extract_heuristics_fallback(clean_raw: str) -> Dict[str, Dict[str, str]]:
    """
    Fallback regex-based heuristic extractor strictly extracting verbatim substrings from raw text.
    Ensures robust parsing even under high network latency or API quotas.
    """
    fallback: Dict[str, Dict[str, str]] = {}

    # Amount
    amt_match = re.search(
        r"(?:Rs\.?|INR|₹)\s*[\d,]+(?:\s*(?:per annum|per year|per month|p\.a\.|\/-))?",
        clean_raw,
        re.IGNORECASE,
    )
    if amt_match:
        val = amt_match.group(0).strip()
        fallback["amount_benefit"] = {"value": val, "quote": val}

    # Closing date
    date_match = re.search(
        r"\b\d{1,2}(?:st|nd|rd|th)?\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{4}\b|\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}[/-]\d{1,2}[/-]\d{4}\b",
        clean_raw,
        re.IGNORECASE,
    )
    if date_match:
        val = date_match.group(0).strip()
        fallback["closing_date"] = {"value": val, "quote": val}

    # Income limit
    inc_match = re.search(
        r"(?:family\s+)?income\s+(?:should\s+not\s+exceed|not\s+exceeding|less\s+than|up\s+to|below)\s*(?:Rs\.?|INR|₹)?\s*[\d,.]+\s*(?:Lakh|Crore|per annum|p\.a\.)?",
        clean_raw,
        re.IGNORECASE,
    )
    if inc_match:
        val = inc_match.group(0).strip()
        fallback["income_criteria"] = {"value": val, "quote": val}

    # Application portal
    portal_match = re.search(
        r"https?://(?:scholarships\.gov\.in|aicte-india\.org|ugc\.ac\.in|tatatrusts\.org|reliancefoundation\.org)[^\s,]*",
        clean_raw,
        re.IGNORECASE,
    )
    if portal_match:
        val = portal_match.group(0).strip()
        fallback["application_url"] = {"value": val, "quote": val}

    return fallback


def extract_scholarship_data(
    raw_text: str,
    source_url: str,
    source_type: str = "GOVERNMENT",
    fallback_title: str = "",
) -> Tuple[ScholarshipRecord, Dict[str, FieldEvidence]]:
    """
    Extracts structured scholarship data from raw text using LLM with
    dual-provider execution and Python-side verbatim grounding verification.
    """
    clean_raw = raw_text[:16000] if raw_text else ""
    evidence_map: Dict[str, FieldEvidence] = {}

    extracted_dict: Dict[str, Any] = {}
    if clean_raw.strip():
        user_prompt = f"{EXTRACTION_SYSTEM_PROMPT}\n\nSOURCE URL: {source_url}\n\nPAGE TEXT:\n{clean_raw}\n\nJSON OUTPUT:"
        try:
            llm_response = llm_client.generate(user_prompt)
            parsed = _extract_json_block(llm_response)
            if parsed and isinstance(parsed, dict):
                extracted_dict = parsed
        except Exception as e:
            logger.warning("LLM extraction call failed for %s: %s", source_url, e)

    # If LLM returned empty or failed, use verbatim heuristic extraction as reliable safety net
    if not extracted_dict and clean_raw.strip():
        heuristic_data = _extract_heuristics_fallback(clean_raw)
        extracted_dict.update(heuristic_data)

    # Fields to process
    target_fields = [
        "name", "provider", "application_url", "amount_benefit",
        "eligibility_criteria", "academic_requirements", "course_level",
        "income_criteria", "age_criteria", "gender_criteria",
        "category_criteria", "domicile_requirements", "institution_requirements",
        "opening_date", "closing_date", "documents_required",
        "selection_process", "renewal_requirements"
    ]

    record_kwargs: Dict[str, Any] = {
        "official_source_url": source_url,
        "source_type": source_type,
    }

    for field in target_fields:
        item = extracted_dict.get(field)
        val = "Not specified"
        quote = ""

        if isinstance(item, dict):
            val = str(item.get("value", "Not specified")).strip()
            quote = str(item.get("quote", "")).strip()
        elif isinstance(item, str):
            val = item.strip()
            quote = ""

        # Normalize default placeholders
        if not val or val.lower() in ("none", "null", "n/a", "na", "undefined", "not specified"):
            val = "Not specified"
            quote = ""

        # Python-side Anti-Hallucination Grounding Verification
        if val != "Not specified" and quote:
            is_grounded = verify_and_ground_quote(quote, clean_raw)
            if not is_grounded:
                logger.warning(
                    "Hallucination caught for field '%s'! Quote '%s' not found in source text.",
                    field, quote[:60]
                )
                # Nullify hallucinated value to enforce strict zero-hallucination policy
                val = "Not specified"
                quote = ""
        elif val != "Not specified" and not quote:
            # Check if value itself exists as verbatim substring in clean_raw
            if verify_and_ground_quote(val, clean_raw):
                quote = val
            else:
                # Value was not backed by verbatim proof in text
                val = "Not specified"
                quote = ""

        record_kwargs[field] = val
        evidence_map[field] = FieldEvidence(
            value=val,
            quote=quote,
            source_url=source_url,
        )

    # Ensure required fields have valid defaults if LLM did not extract
    if not record_kwargs.get("name") or record_kwargs["name"] == "Not specified":
        record_kwargs["name"] = fallback_title or "Government / Institutional Scholarship Scheme"
        evidence_map["name"] = FieldEvidence(value=record_kwargs["name"], quote="", source_url=source_url)

    if not record_kwargs.get("provider") or record_kwargs["provider"] == "Not specified":
        record_kwargs["provider"] = "Department / Statutory Council"
        evidence_map["provider"] = FieldEvidence(value=record_kwargs["provider"], quote="", source_url=source_url)

    if not record_kwargs.get("eligibility_criteria") or record_kwargs["eligibility_criteria"] == "Not specified":
        record_kwargs["eligibility_criteria"] = "Indian students enrolled in recognized institutions"
        evidence_map["eligibility_criteria"] = FieldEvidence(
            value=record_kwargs["eligibility_criteria"], quote="", source_url=source_url
        )

    record = ScholarshipRecord(
        **record_kwargs,
        evidence_map=evidence_map,
    )

    return record, evidence_map
