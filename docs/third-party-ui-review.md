# Third-party UI Review: animal-island-ui

## Candidate

- Repository: https://github.com/guokaigdg/animal-island-ui
- Intended use: Use its island/card/dock interaction language as the UI foundation for HarborPilot AI.

## Current Implementation Status

- Installed npm package: `animal-island-ui@1.0.1`.
- Global style import: `web/app/layout.tsx`.
- Current direct component usage: `Button`, `Card`, `Tabs`, `Title`, `Tooltip` in `web/app/HarborPilotApp.tsx`.
- HarborPilot also keeps local CSS for admissions-specific density, evidence states, tables, and responsive layout.
- Product assumption confirmed by user on 2026-06-15: this project will not be commercialized, so the upstream README non-commercial note is accepted for this build.

## Review Gate

Before shipping a commercial version:

- Confirm the repository license and any non-commercial usage notice in the upstream README.
- Record the exact commit/version used.
- Confirm attribution requirements.
- Confirm whether component source can be copied, modified, bundled, or only referenced as a dependency.
- Keep a fallback path that does not depend on upstream maintenance.
- If HarborPilot becomes a paid or external commercial service, remove or replace this dependency before launch.

## HarborPilot UX Direction

Use the reference for interaction feel, not for product logic:

- KeyGate and workflow dock for `connect key -> profile -> match -> timeline -> writing`.
- Island-style project pools for core, related, and blocked recommendations.
- Evidence cards for field-level source status.
- Timeline islands for each selected program and shared material tasks.
