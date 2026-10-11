# BetterUp Employee Onboarding Automation

## 1. Problem and approach

Employee onboarding depends on multiple systems, including Ashby, Workday, Okta/Lumos, equipment provisioning, and the cohort tracker. When employee information changes after an offer, inconsistent updates can create access, equipment, and scheduling issues.

This prototype focuses on **cross-system validation and safe change propagation**. It checks that the source system contains the approved new value and that downstream systems still contain the expected previous value before updating them.

The implementation uses mock systems and sample data. It does not connect to BetterUp's live systems.

## 2. Architecture

The prototype has two workflows:

* **Onboarding workflow:** validates an onboarding request and executes onboarding steps through a mock connector.
* **Change propagation workflow:** validates an employee change against mock system records and propagates it to relevant downstream systems only when validation succeeds.

Change propagation flow:

1. Receive a change request with a unique change ID.
2. Confirm that Ashby contains the expected new value.
3. Check each target system against the expected old value.
4. If any check fails, return a conflict without updating any target.
5. If all checks pass, update the target systems and return the result.
6. Return the stored result when the same change request is submitted again.

## 3. Technology choices

* Python for the workflow and business logic.
* FastAPI for HTTP endpoints and interactive API documentation.
* Pydantic for request and response validation.
* SQLite for the existing onboarding workflow store.
* Pytest for automated tests.
* In-memory mock connectors for change propagation.

The implementation uses deterministic business rules for reconciliation. An LLM is not needed to decide whether employee records match because those checks must be predictable and testable.

## 4. Data model

The change request includes:

* `change_id`: unique identifier for a change event.
* `employee_id`: employee affected by the change.
* `source_system`: source of the approved change, currently Ashby.
* `field_name`: supported field being changed.
* `old_value`: expected existing value in downstream systems.
* `new_value`: approved new value.
* `requested_by`: requester email address.

The response reports the change status, updated systems, conflicts, and a message.

## 5. Error handling and idempotency

The service rejects changes when the source value is incorrect or any target system differs from the expected old value. It validates all targets before updating any of them, preventing partial updates in the in-memory prototype.

Repeated requests with the same change ID and identical payload return the stored result. Reusing a change ID with a different payload is rejected.

The existing onboarding workflow also supports retries, recorded completed steps, and explicit resumption after failure.

## 6. Testing

The automated tests cover onboarding success, business-rule validation, connector failure, retries, duplicate onboarding, successful change propagation, conflicting target data, duplicate change requests, and change-ID reuse.

Run the suite with:

`uv run pytest -v`

## 7. Production considerations

Before production use, I would:

1. Replace mock connectors with authenticated API integrations for Ashby, Workday, Okta/Lumos, equipment, and the cohort tracker.
2. Persist change events, idempotency keys, system responses, and audit history in a durable database.
3. Add access controls, secret management, input authorization, and PII-safe logging.
4. Implement bounded retries with timeouts, backoff, rate-limit handling, and dead-letter handling for persistent failures.
5. Use a durable workflow or reconciliation process to detect and recover from partial failures across external systems.
6. Add monitoring and alerts for conflicts, overdue onboarding gates, and repeated integration failures.
7. Require human approval for sensitive changes, such as access or identity changes, where appropriate.
8. Add integration tests, contract tests, and observability before enabling real writes.

The current implementation is a prototype: in-memory change state does not survive restarts, and updates across real external systems cannot be made atomic by a local Python loop.

## 8. AI-assisted development

AI assistance was used to help draft and review implementation code. One issue occurred when validation logic referenced `work_location` before that field had been added to the Pydantic request model. The automated tests exposed the `AttributeError`; the model was updated and the tests were rerun successfully.

No live Claude API or MCP integration is implemented in this prototype. The core reconciliation logic is deterministic. A future AI component could classify unstructured exception details and recommend remediation, while keeping authorization and actual system updates under deterministic rules and, where needed, human approval.
