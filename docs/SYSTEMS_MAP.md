# Systems map

## Where the data lives

| System | Role | Fields it owns (native name) | Direction |
|---|---|---|---|
| **Ashby** | Source of truth for the offer | department, manager_email, start_date, work_location | read-only for us |
| **Workday** | HRIS | `supervisory_org`, `manager_email`, `hire_date`, `location` | written |
| **Okta / Lumos** | Identity + access | `manager` (lower-cased), `location_group` | written |
| **Equipment (ExpoIT)** | Hardware shipping | `ship_by_date` (= start − 7 days), `ship_to_region` | written |
| **Cohort tracker** | Onboarding cohort | `cohort_dept`, `cohort_start` | written |
| **Slack** | Human escalation | – | notified |

Each connector in `app/systems.py` declares a `FIELD_MAP` plus `encode`/`decode`, so the
service reasons in Ashby's canonical fields and the targets for a change are *derived*
from which systems own that field, not hard-coded.

| Field changed | Targets written |
|---|---|
| department | Workday, cohort tracker |
| manager_email | Workday, Okta/Lumos |
| start_date | Workday, equipment, cohort tracker |
| work_location | Workday, Okta/Lumos, equipment |

## How a change moves

```
Ashby (approved value) ──webhook/POST──▶ /changes/propagate
                                              │
                    1. idempotency  ◀── ChangeStore (SQLite: changes + audit_log)
                    2. validate (READ ONLY)
                         Ashby == new_value ?
                         every target ∈ {old_value, new_value} ?
                              │
              ┌───────────────┴───────────────┐
        disagreement                       all agree
              │                                 │
   Claude triage (API, tool-use)        3. write each target (bounded retry)
   → schema check → guardrails                  │
   → Slack if human needed              write fails after retries?
   → NO writes                                  │
                                       compensate: restore earlier writes
                                       → Slack (flags INCONSISTENT if restore fails)
```

## Where it breaks today (and what this slice does about it)

| Break | Today | In the prototype |
|---|---|---|
| Start date moves after offer | Someone re-keys Workday, equipment, tracker by hand; equipment ship-by is missed | One validated fan-out; equipment ship-by recomputed by the connector |
| Ashby edited, downstream already changed by someone else | Silent overwrite | Conflict, zero writes, triage, human paged |
| Change request built on stale data | Wrong value propagated | Old-value check per target |
| Partial failure (Workday ok, equipment down) | Systems left disagreeing, nobody knows | Compensating rollback; if that fails, Slack says **INCONSISTENT** |
| Same event delivered twice (webhook retry) | Double-apply | Durable idempotency key; replay returns stored result |
| Process dies mid-change | Unknown state | `in_progress` row is resumed; already-applied targets are skipped |

## Not in this slice (deliberately)

* **Exception monitoring for the 7-day gates** (hardware form, background check, Okta
  provisioning). It needs deadline data from systems this prototype doesn't model.
  The audit trail and Slack notifier are the pieces it would reuse.
* **Onboarding-time validation** (bad name/location at creation). Partly covered by
  Pydantic validation at the edge, but no cross-system rules yet.
