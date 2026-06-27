from __future__ import annotations

import os

from harbor_agent.config import Settings
from harbor_agent.core.llm import build_llm_provider


def main() -> None:
    if not os.getenv("OPENAI_API_KEY") and not os.getenv("HARBOR_AGENT_OPENAI_API_KEY"):
        raise SystemExit("Set OPENAI_API_KEY or HARBOR_AGENT_OPENAI_API_KEY before running this smoke test.")
    settings = Settings(
        llm_mode="openai",
        llm_provider=os.getenv("HARBOR_AGENT_LLM_PROVIDER", "deepseek"),
        openai_api_key=os.getenv("OPENAI_API_KEY") or os.getenv("HARBOR_AGENT_OPENAI_API_KEY"),
        openai_model=os.getenv("HARBOR_AGENT_OPENAI_MODEL", "deepseek-v4-flash"),
        openai_base_url=os.getenv("HARBOR_AGENT_OPENAI_BASE_URL"),
    )
    provider = build_llm_provider(settings)
    print(
        provider.complete_json(
            system="Return JSON only.",
            user="用中文确认 HarborPilot 真实模型适配器已经连通。",
            schema_hint={"summary": "string"},
        )
    )


if __name__ == "__main__":
    main()
