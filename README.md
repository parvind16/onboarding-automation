# Employee Onboarding Automation

A Python-based onboarding automation service that coordinates employee onboarding across multiple People and IT systems through a single API.

The project demonstrates workflow orchestration, input validation, retry handling, failure reporting, and SQLite-based workflow persistence.

## Problem Statement

Employee onboarding often involves several separate tasks across HR, identity management, orientation scheduling, and email systems. Manual coordination can cause delays, repeated actions, and limited visibility into failures.

This service automates the onboarding workflow and tracks its progress.

## Features

* **REST API:** Built with FastAPI and Pydantic.
* **Input validation:** Validates employee information, email addresses, and start dates.
* **Workflow orchestration:** Coordinates four onboarding steps in sequence.
* **Retry handling:** Retries failed operations up to three attempts with exponential backoff.
* **Failure handling:** Stops the workflow when a step fails and reports the failed step.
* **Workflow persistence:** Uses SQLite to store workflow status and completed steps.
* **Resume support:** Supports resuming failed workflows through the resume endpoint, when configured.
* **Automated tests:** Uses pytest to validate successful workflows, validation failures, connector failures, duplicate requests, and retry behavior.

## Architecture

```text
Client / API Consumer
        |
        v
   FastAPI API
        |
        v
Input Validation
        |
        v
Onboarding Orchestrator
        |
        +----------------------+
        |                      |
        v                      v
 Retry and Error         SQLite Workflow
 Handling                Store
        |
        v
Onboarding Connectors
        |
        +--> Create Employee Record
        |
        +--> Provision Accounts
        |
        +--> Schedule Orientation
        |
        +--> Send Welcome Email
```

## Technology Stack

* Python 3.12+
* FastAPI
* Pydantic
* SQLite
* uv for dependency and environment management
* pytest and HTTPX for testing

## Project Structure

```text
onboarding-automation/
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── models.py
│   ├── connectors.py
│   ├── validation.py
│   ├── orchestrator.py
│   └── workflow_store.py
├── tests/
│   └── test_orchestrator.py
├── README.md
├── BUILD_NOTE.md
├── pyproject.toml
└── uv.lock
```

## Prerequisites

* Python 3.12 or later
* uv

Install uv using the official installation instructions: https://docs.astral.sh/uv/getting-started/installation/

## Getting Started

Clone the repository and enter the project directory:

```bash
git clone <YOUR_GITHUB_REPOSITORY_URL>
cd onboarding-automation
```

Install dependencies:

```bash
uv sync
```

Run the automated tests:

```bash
uv run pytest -v
```

Start the API:

```bash
uv run uvicorn app.main:app --reload
```

Open the interactive API documentation:

http://127.0.0.1:8000/docs

## API Endpoints

| Method | Endpoint                           | Purpose                                                 |
| ------ | ---------------------------------- | ------------------------------------------------------- |
| GET    | `/health`                          | Check API health                                        |
| POST   | `/onboarding`                      | Start an employee onboarding workflow                   |
| POST   | `/onboarding/{employee_id}/resume` | Resume a failed workflow, if enabled in the application |

### Example Request

```json
{
  "employee_id": "EMP001",
  "first_name": "Rahul",
  "last_name": "Sharma",
  "email": "rahul@example.com",
  "department": "Engineering",
  "manager_email": "manager@example.com",
  "start_date": "2099-01-15",
  "equipment_required": true
}
```

Use a future start date when testing, or replace the example date with a valid future date.

### Example Successful Response

```json
{
  "employee_id": "EMP001",
  "status": "completed",
  "completed_steps": [
    "create_employee_record",
    "provision_accounts",
    "schedule_orientation",
    "send_welcome_email"
  ],
  "failed_step": null,
  "message": "Employee onboarding completed successfully."
}
```

The exact response depends on the application's current response model.

## Reliability and Error Handling

The orchestrator executes onboarding steps sequentially. Each operation can be retried up to three times with exponential backoff. If an operation continues to fail, the workflow records the failure and returns a response identifying the failed step.

SQLite stores workflow status and completed steps so that progress can be inspected and used by resume logic.

The current connectors are **mock implementations** for demonstrating the workflow. Production deployment would require integration with real HR, identity, scheduling, and email systems, along with authentication, authorization, monitoring, and appropriate safeguards against duplicate side effects.

## Testing

Run:

```bash
uv run pytest -v
```

The test suite covers:

* Successful onboarding
* Rejection of past start dates
* Employee and manager email validation
* Connector failure handling
* Duplicate onboarding requests
* Retry behavior after a transient failure

## Future Improvements

* Integrate real HR and identity management APIs.
* Add authentication and role-based authorization.
* Add structured logs, tracing, metrics, and audit history.
* Add workflow timeouts and controlled retry policies.
* Improve recovery for partially completed external operations.
* Add integration tests against simulated external services.
* Add CI automation using GitHub Actions.

## Design Goal

Build a maintainable onboarding automation service that demonstrates practical API development, workflow coordination, reliability, and recovery across multiple enterprise systems.
