"""
Universal Pydantic v2 Data Models & Strict Grounding Schemas.
Implements zero-hallucination policies: missing values default strictly to 'Not specified'
and extracted fields must map to verbatim evidence quotes.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ScholarshipStatus(str, Enum):
    VERIFIED = "VERIFIED"
    ACTIVE = "ACTIVE"
    EXPIRING_SOON = "EXPIRING_SOON"
    EXPIRED = "EXPIRED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    NO_LONGER_VERIFIABLE = "NO_LONGER_VERIFIABLE"


class SourceType(str, Enum):
    GOVERNMENT = "GOVERNMENT"
    APEX_BODY = "APEX_BODY"
    UNIVERSITY = "UNIVERSITY"
    CORPORATE_CSR = "CORPORATE_CSR"
    NGO_TRUST = "NGO_TRUST"
    AGGREGATOR = "AGGREGATOR"
    UNVERIFIED = "UNVERIFIED"


class FieldEvidence(BaseModel):
    """
    Encapsulates an extracted field value paired with its verbatim evidence quote from the source text.
    """
    model_config = ConfigDict(extra="ignore")

    value: str = Field(default="Not specified", description="Extracted factual value")
    quote: str = Field(default="", description="Verbatim substring quote from source page")
    source_url: Optional[str] = Field(default=None, description="URL where quote was captured")

    @field_validator("value", mode="before")
    @classmethod
    def normalize_value(cls, v: Any) -> str:
        if v is None:
            return "Not specified"
        s = str(v).strip()
        return s if s else "Not specified"

    @field_validator("quote", mode="before")
    @classmethod
    def normalize_quote(cls, v: Any) -> str:
        if v is None:
            return ""
        return str(v).strip()

    def is_grounded_in(self, raw_text: str, case_sensitive: bool = False) -> bool:
        """
        Validates if quote exists verbatim in the source content.
        If value is 'Not specified', no evidence quote is required.
        """
        if self.value == "Not specified" or not self.quote:
            return True
        if not raw_text:
            return False
        
        # Clean both quote and raw_text of normalized whitespace for robust substring matching
        def _clean_ws(t: str) -> str:
            return re.sub(r"\s+", " ", t).strip()

        clean_q = _clean_ws(self.quote)
        clean_text = _clean_ws(raw_text)

        if case_sensitive:
            return clean_q in clean_text
        return clean_q.lower() in clean_text.lower()


class ScholarshipRecord(BaseModel):
    """
    Universal canonical schema for a validated scholarship opportunity.
    Strictly enforces zero-hallucination defaults and evidence tracking.
    """
    model_config = ConfigDict(extra="ignore")

    # Identifiers & Primary Metadata
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = Field(..., min_length=2, description="Official title of the scholarship scheme")
    provider: str = Field(..., min_length=2, description="Disbursing department, apex body, or trust")
    source_type: str = Field(default="GOVERNMENT", description="Category of authority")
    official_source_url: str = Field(..., description="Canonical source URL")
    application_url: str = Field(default="Not specified", description="Direct application gateway")

    # Benefits & Core Eligibility
    amount_benefit: str = Field(default="Not specified", description="Financial stipend or fee waiver details")
    eligibility_criteria: str = Field(..., min_length=2, description="Core eligibility requirements")
    academic_requirements: str = Field(default="Not specified", description="Minimum marks, GPA, or degrees required")
    course_level: str = Field(default="Not specified", description="Pre-Matric, Post-Matric, UG, PG, PhD")
    income_criteria: str = Field(default="Not specified", description="Annual family income limit")
    age_criteria: str = Field(default="Not specified", description="Age cutoffs")
    gender_criteria: str = Field(default="Not specified", description="Specific gender targeting e.g. Female only")
    category_criteria: str = Field(default="Not specified", description="General, SC, ST, OBC, EWS, Minority, PwD")
    domicile_requirements: str = Field(default="Not specified", description="State or regional domicile requirements")
    institution_requirements: str = Field(default="Not specified", description="Recognized/AIECTE/UGC institutions")

    # Timeline & Procedure
    opening_date: str = Field(default="Not specified", description="Application opening date")
    closing_date: str = Field(default="Not specified", description="Application closing/deadline date")
    documents_required: str = Field(default="Not specified", description="Mandatory certificates and documents")
    selection_process: str = Field(default="Not specified", description="Merit list, exam, or interview process")
    renewal_requirements: str = Field(default="Not specified", description="Conditions for subsequent year disbursement")

    # Verification & Audit State
    status: str = Field(default="REVIEW_REQUIRED", description="Verification lifecycle status")
    confidence_score: float = Field(default=0.0, ge=0.0, le=100.0, description="Deterministic confidence score")
    score_breakdown: Dict[str, Any] = Field(default_factory=dict, description="Point attribution breakdown")
    last_verified: Optional[str] = Field(default=None, description="ISO timestamp of last verification")
    raw_hash: Optional[str] = Field(default=None, description="Hash of crawled raw source text")
    created_at: Optional[str] = Field(default=None, description="Creation timestamp")

    # Evidence Grounding Map
    evidence_map: Dict[str, FieldEvidence] = Field(
        default_factory=dict,
        description="Map of field_name to verbatim FieldEvidence quote"
    )

    # ------------------ Validators ------------------

    @field_validator(
        "application_url",
        "amount_benefit",
        "academic_requirements",
        "course_level",
        "income_criteria",
        "age_criteria",
        "gender_criteria",
        "category_criteria",
        "domicile_requirements",
        "institution_requirements",
        "opening_date",
        "closing_date",
        "documents_required",
        "selection_process",
        "renewal_requirements",
        mode="before",
    )
    @classmethod
    def enforce_not_specified_default(cls, v: Any) -> str:
        """Coerces any None, empty, whitespace, or generic placeholder string to 'Not specified'."""
        if v is None:
            return "Not specified"
        s = str(v).strip()
        if not s or s.lower() in ("none", "null", "n/a", "na", "undefined", "not available"):
            return "Not specified"
        return s

    @field_validator("official_source_url")
    @classmethod
    def validate_official_url(cls, v: str) -> str:
        s = str(v).strip()
        if not (s.startswith("http://") or s.startswith("https://")):
            raise ValueError(f"official_source_url must start with http:// or https://: '{v}'")
        return s

    @model_validator(mode="after")
    def populate_defaults_and_timestamps(self) -> ScholarshipRecord:
        now_iso = datetime.now(timezone.utc).isoformat()
        if not self.last_verified:
            self.last_verified = now_iso
        if not self.created_at:
            self.created_at = now_iso
        return self

    # ------------------ Helper Methods ------------------

    def verify_evidence_quotes(self, raw_content: str) -> Dict[str, bool]:
        """
        Validates all evidence quotes in evidence_map against the raw webpage content.
        Returns a dictionary of field_name -> bool (is_verbatim_match).
        """
        results: Dict[str, bool] = {}
        for field_name, evidence in self.evidence_map.items():
            results[field_name] = evidence.is_grounded_in(raw_content)
        return results

    def to_db_dict(self) -> Dict[str, Any]:
        """Converts model into a dictionary mapped directly to the SQLite scholarships schema."""
        return {
            "id": self.id,
            "name": self.name,
            "provider": self.provider,
            "source_type": str(self.source_type),
            "official_source_url": self.official_source_url,
            "application_url": self.application_url,
            "amount_benefit": self.amount_benefit,
            "eligibility_criteria": self.eligibility_criteria,
            "academic_requirements": self.academic_requirements,
            "course_level": self.course_level,
            "income_criteria": self.income_criteria,
            "age_criteria": self.age_criteria,
            "gender_criteria": self.gender_criteria,
            "category_criteria": self.category_criteria,
            "domicile_requirements": self.domicile_requirements,
            "institution_requirements": self.institution_requirements,
            "opening_date": self.opening_date,
            "closing_date": self.closing_date,
            "documents_required": self.documents_required,
            "selection_process": self.selection_process,
            "renewal_requirements": self.renewal_requirements,
            "status": str(self.status),
            "confidence_score": float(self.confidence_score),
            "score_breakdown": self.score_breakdown,
            "last_verified": self.last_verified,
            "raw_hash": self.raw_hash,
            "created_at": self.created_at,
        }

    def to_evidence_list(self) -> List[Dict[str, Any]]:
        """Converts evidence_map entries into a list of dicts suitable for evidence_traces DB storage."""
        ev_list: List[Dict[str, Any]] = []
        for field_name, ev in self.evidence_map.items():
            ev_list.append({
                "scholarship_id": self.id,
                "field_name": field_name,
                "extracted_value": ev.value,
                "evidence_quote": ev.quote,
                "source_url": ev.source_url or self.official_source_url,
                "captured_at": self.last_verified,
            })
        return ev_list
