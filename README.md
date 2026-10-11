# BetterUp Employee Onboarding Automation

A Python/FastAPI prototype demonstrating employee onboarding automation, cross-system data validation, and safe propagation of employee changes.

## Problem

Employee onboarding involves multiple systems, including Ashby, Workday, Okta/Lumos, equipment provisioning, and a cohort tracker. When employee information changes, inconsistent records can lead to access, equipment, and scheduling issues.

This prototype demonstrates how to validate a change before propagating it to downstream systems.

## Features

* Request validation using Pydantic.
* Onboarding workflow orchestration with mock connectors.
* Cross-system validation before employee changes are propagated.
* Conflict detection to prevent unsafe updates.
* Idempotent handling of repeated change requests.
* Retry handling and resumable onboarding workflows.
* Automated tests using pytest.
* Interactive API documentation through FastAPI Swagger UI.

## Technology stack

* Python 3.12+
* FastAPI
* Pydantic
* SQLite for onboarding workflow state
* Pytest
* uv for dependency and environment management

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

Use `POST /changes/propagate` in Swagger UI with this example request:

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

Expected behavior:

* The service verifies that Ashby contains the approved new value.
* It checks that Workday and the cohort tracker still contain the expected old value.
* If validation succeeds, both mock systems are updated.
* If a conflict is detected, the service rejects the change without updating either target.
* Repeating the same request returns the stored result.

The demo employee is seeded in memory when the application starts.

## Run tests

```bash
uv run pytest -v
```

The test suite covers onboarding behavior, retries, validation, change propagation, conflict handling, and idempotency.

## Architecture and design decisions

The prototype separates onboarding orchestration from change propagation. The change propagation service validates all target records before writing updates, and it uses a change ID to handle duplicate requests.

Deterministic rules are used for data validation because identity and employee-record changes should be predictable and testable.

For design rationale, failure handling, idempotency, AI-assisted development notes, and production considerations, see [BUILD_NOTE.md](BUILD_NOTE.md).

## Scope and limitations

All People-system integrations are mocked. This prototype does not connect to BetterUp's live systems and does not implement a live Claude API or MCP integration.

In production, I would add authenticated system connectors, durable change-event storage, audit history, monitoring, rate-limit-aware retries, recovery for partial failures, and authorization controls.
