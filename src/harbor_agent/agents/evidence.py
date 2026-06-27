from __future__ import annotations

from harbor_agent.models import EvidenceLevel, EvidenceReview, NormalizedProfile


class EvidenceAgent:
    name = "EvidenceAgent"

    def run(self, profile: NormalizedProfile) -> EvidenceReview:
        total_facts = max(1, sum(profile.fact_summary.values()))
        verified = profile.fact_summary.get(EvidenceLevel.evidence_verified.value, 0)
        confirmed = profile.fact_summary.get(EvidenceLevel.user_confirmed.value, 0)
        verified_ratio = round(((verified + confirmed) / total_facts) * 100)

        pending = [
            "education.gpa",
            "language.overall",
            *[f"experience.{index}.outcomes" for index, _ in enumerate(profile.experiences[:3], start=1)],
        ]
        recommended_uploads = []
        if profile.education.evidence_level == EvidenceLevel.self_reported:
            recommended_uploads.append("official transcript")
        if profile.language.evidence_level == EvidenceLevel.self_reported:
            recommended_uploads.append("language score report")
        if profile.experiences:
            recommended_uploads.append("CV or experience proof")

        return EvidenceReview(
            verified_fact_ratio=verified_ratio,
            pending_confirmations=pending[:5],
            conflicts=[item.get("field", "unknown") for item in profile.conflicts],
            recommended_uploads=recommended_uploads,
            human_gate_required=verified_ratio < 60 or bool(profile.conflicts),
        )

