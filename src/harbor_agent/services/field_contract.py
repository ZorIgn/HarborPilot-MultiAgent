"""Shared field contracts for acquisition, review, and formal decisions.

The project previously repeated slightly different lists of programme fields in
the resolver, the crawler, and legacy refresh reports.  That creates a subtle
but dangerous failure mode: an operator screen can say a programme is complete
while the formal gate still blocks an omitted hard admissions field.  This
module deliberately contains data only, so every layer can import the same
contract without introducing service-level dependency cycles.
"""

from __future__ import annotations


# These fields must have a current, reviewed DecisionFact before a programme
# can be represented as a formal recommendation.  ``portfolio_required`` is a
# hard admissions predicate; it is not merely a writing preference.
FORMAL_RECOMMENDATION_FIELDS: tuple[str, ...] = (
    "official_program_url",
    "application_url",
    "deadline",
    "tuition_hkd",
    "min_gpa",
    "language_requirement",
    "required_backgrounds",
    "portfolio_required",
    "materials",
)


# The controlled acquisition pipeline also collects essay prompts.  They do
# not make a programme formally recommendable by themselves, but a current
# fact is required before a prompt-specific writing claim can be formal.
ACQUISITION_FIELD_ORDER: tuple[str, ...] = (
    "official_program_url",
    "deadline",
    "tuition_hkd",
    "min_gpa",
    "language_requirement",
    "required_backgrounds",
    "portfolio_required",
    "materials",
    "application_url",
    "essay_prompts",
)


HARD_ADMISSIONS_FIELDS: tuple[str, ...] = (
    "min_gpa",
    "language_requirement",
    "required_backgrounds",
    "portfolio_required",
)


CRITICAL_TIMELINE_FIELDS: tuple[str, ...] = (
    "official_program_url",
    "deadline",
    "application_url",
    "language_requirement",
    "materials",
    "tuition_hkd",
)
