"""
Extractor and schema package for structured scholarship data.
"""
from core.extractor.schema import (
    FieldEvidence,
    ScholarshipRecord,
    ScholarshipStatus,
    SourceType,
)

from core.extractor.parser import extract_scholarship_data
from core.extractor.llm_client import llm_client, LLMExtractorClient

__all__ = [
    "FieldEvidence",
    "ScholarshipRecord",
    "ScholarshipStatus",
    "SourceType",
    "extract_scholarship_data",
    "llm_client",
    "LLMExtractorClient",
]
