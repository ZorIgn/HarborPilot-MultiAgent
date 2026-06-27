# ADR 0001: Modular Monolith for the MVP

## Status

Accepted

## Context

The original outline includes separate workers, PostgreSQL, Redis, object storage, source governance, OCR, observability, and a multi-role UI. That is the right long-term direction, but overbuilding all infrastructure before the core workflow is proven would make the portfolio project harder to review.

## Decision

Use a modular monolith:

- FastAPI backend with separated agent modules.
- Next.js frontend.
- JSON demo data for the current repository.
- Docker Compose for local deployment.
- Mock LLM by default, OpenAI adapter behind environment variables.

## Consequences

Good:

- The project runs without external accounts.
- The multi-agent architecture is inspectable in code and tests.
- Future production components can replace JSON loaders and mock providers.

Tradeoff:

- No persistent database in the MVP.
- OCR and crawler workers are represented as extension points rather than full services.

