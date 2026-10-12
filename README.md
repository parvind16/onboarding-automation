# BetterUp Employee Onboarding Automation

A Python/FastAPI prototype demonstrating employee onboarding automation, cross-system data validation, and safe propagation of employee changes.

## Problem

Employee onboarding involves multiple systems, including Ashby, Workday, Okta/Lumos, equipment provisioning, and a cohort tracker. When employee information changes, inconsistent records can lead to access, equipment, and scheduling issues.

This prototype demonstrates how to validate a change before propagating it to downstream systems.

## Features

* Per-system connectors (Ashby, Workday, Okta/Lumos, equipment, cohort tracker) with field mapping and transforms.
* Validate-all-then-write-all change propagation with compensating rollback.
* Durable idempotency keys and audit trail in SQLite; crash-resume of unfinished changes.
* Bounded retries with exponential backoff on connector calls.
* **Claude as a scoped component**: conflict triage via the Anthropic API (forced tool-use), schema-validated, wrapped in deterministic guardrails, with a rule-based fallback.
* Slack escalation (mocked) when a human is needed.
* Request validation using Pydantic; onboarding workflow with resumable steps.
* Automated tests (43) using pytest.

## Technology stack

* Python 3.12+, FastAPI, Pydantic, httpx
* SQLite for workflow state, idempotency keys and audit trail
* Pytest, uv

How this maps onto BetterUp's existing stack (and why a small service is added at all) is in
[BUILD_NOTE.md](BUILD_NOTE.md); the systems map is in [docs/SYSTEMS_MAP.md](docs/SYSTEMS_MAP.md).

## Prerequisites

* Python 3.12 or newer.
* `uv` installed.

## Setup

Clone the repository:

```bash
git clone https://github.com/parvind16/onboarding-automation.git
cd onboarding-automation
```

Install dependencies:

```bash
uv sync
```

## Run the application

```bash
uv run uvicorn app.main:app --reload
```

Open the interactive API documentation:

http://127.0.0.1:8000/docs

Health check:

http://127.0.0.1:8000/health

## Try change propagation

The demo employee `EMP-DEMO-01` is seeded in memory at startup (Ashby holds the approved
values; Workday, Okta/Lumos, equipment and the tracker hold the old ones). The mock systems
reset on every start, so delete `changes.db` between runs: `rm -f changes.db`.

Use `POST /changes/propagate` in Swagger UI:

```json
{
  "change_id": "CHG-001",
  "employee_id": "EMP-DEMO-01",
  "source_system": "ashby",
  "field_name": "department",
  "old_value": "Engineering",
  "new_value": "Product",
  "requested_by": "hr@example.com"
}
```

Other things to try:

* Send it again: the stored result is replayed and nothing is rewritten.
* Same `change_id` with a different `new_value`: rejected.
* `field_name: work_location`, `old_value: Seattle`, `new_value: Austin`: conflict, no writes,
  classified, and escalated to Slack (the guardrail forces a human for identity fields).
* `field_name: start_date`, `2026-11-09` to `2026-11-16`: fans out to Workday, equipment
  (stored as ship-by = start - 7 days) and the tracker.
* `GET /changes/CHG-001/audit`: full event trail.

A recorded run is in [docs/DEMO_TRANSCRIPT.md](docs/DEMO_TRANSCRIPT.md).

### Enable the Claude classifier

```bash
export ANTHROPIC_API_KEY=...        # optional; CLAUDE_MODEL overrides the default model
uv run uvicorn app.main:app --reload
```

Without a key the service uses the deterministic rule-based classifier, so everything runs offline.

## Run tests

```bash
uv run pytest -v
```

The suite covers onboarding, field mapping and transforms, conflicts, idempotency across a restart, crash-resume, retries, rollback (including failed rollback), the Claude request/parse/fallback paths, and guardrails. The Claude calls are tested against a fake HTTP transport; run once with a real key to verify the live path.

## Architecture and design decisions

Onboarding orchestration and change propagation are separate. Propagation validates every target before writing any, writes with bounded retries, and compensates if a later write fails. Deterministic code decides validity; Claude only triages conflicts, and its output is advisory, schema-checked and guard-railed. Full rationale, failure handling, AI-usage notes and production considerations: [BUILD_NOTE.md](BUILD_NOTE.md).

## Scope and limitations

All People-system integrations are mocked and in-memory (reseeded on start). Cross-system writes are not atomic; rollback is best-effort and failures are escalated. The live Claude call has not been run against the real API in this repo's tests.
