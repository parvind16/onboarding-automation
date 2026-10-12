$ curl localhost:8765/health
{"status":"healthy"}

### 1. Propagate a department change (Ashby=Product, Workday/tracker=Engineering)
{
    "change_id": "CHG-001",
    "employee_id": "EMP-DEMO-01",
    "status": "propagated",
    "updated_systems": [
        "workday",
        "cohort_tracker"
    ],
    "conflicts": [],
    "classification": null,
    "escalated": false,
    "message": "Change validated and propagated successfully."
}

### 2. Same change_id + same payload -> stored result replayed, nothing rewritten
{
    "change_id": "CHG-001",
    "employee_id": "EMP-DEMO-01",
    "status": "propagated",
    "updated_systems": [
        "workday",
        "cohort_tracker"
    ],
    "conflicts": [],
    "classification": null,
    "escalated": false,
    "message": "Change validated and propagated successfully."
}

### 3. Same change_id, different payload -> rejected
{
    "change_id": "CHG-001",
    "employee_id": "EMP-DEMO-01",
    "status": "conflict",
    "updated_systems": [],
    "conflicts": [
        "This change ID has already been used for a different request."
    ],
    "classification": null,
    "escalated": false,
    "message": "Change rejected because the change ID was reused."
}

### 4. Conflict: stale request (expects Seattle, systems hold Denver) -> no writes, classified, guardrail -> Slack
{
    "change_id": "CHG-002",
    "employee_id": "EMP-DEMO-01",
    "status": "conflict",
    "updated_systems": [],
    "conflicts": [
        "workday: expected 'Seattle', found 'Denver'.",
        "okta_lumos: expected 'Seattle', found 'Denver'.",
        "equipment: expected 'Seattle', found 'Denver'."
    ],
    "classification": {
        "category": "stale_target",
        "recommended_action": "escalate_to_human",
        "confidence": 0.8,
        "rationale": "Downstream systems hold a value different from the expected old value, so the change request was built on stale data.",
        "classified_by": "rules",
        "guardrail_applied": "identity_field_requires_human"
    },
    "escalated": true,
    "message": "No downstream systems were updated because validation failed."
}

### 5. start_date fans out to 3 systems (equipment stores ship-by = start - 7 days)
{
    "change_id": "CHG-003",
    "employee_id": "EMP-DEMO-01",
    "status": "propagated",
    "updated_systems": [
        "workday",
        "equipment",
        "cohort_tracker"
    ],
    "conflicts": [],
    "classification": null,
    "escalated": false,
    "message": "Change validated and propagated successfully."
}

### 6. Malformed value rejected at the edge
HTTP 422

### 7. Audit trail for CHG-001
2026-10-12T06:47:26 received {}
2026-10-12T06:47:26 validated {'targets': ['workday', 'cohort_tracker']}
2026-10-12T06:47:26 write_applied {'system': 'workday'}
2026-10-12T06:47:26 write_applied {'system': 'cohort_tracker'}
2026-10-12T06:47:26 propagated {'updated_systems': ['workday', 'cohort_tracker']}
2026-10-12T06:47:26 replayed_stored_result {}
2026-10-12T06:47:26 id_reuse_rejected {}
