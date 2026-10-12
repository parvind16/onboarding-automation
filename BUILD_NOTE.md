# Build note: cross-system change propagation

## 1. Why this slice

The brief names three slices: **change propagation, cross-system validation, exception
monitoring.** I built propagation because the other two are partly *inside* it:

* **Validation-only** tells you a value is wrong but leaves the fix manual, and the manual fix is
  where the breakage happens today. Propagation makes validation a precondition for every
  write (validate all targets, then write), so I get validation for free.
* **Exception monitoring** detects late gates but not wrong data. Propagation's conflict path
  *is* an exception handler: it detects drift, triages it (Claude), and pages a human.
* **Blast radius:** a changed start date silently breaks equipment (7-day ship lead), Okta
  provisioning timing and the tracker at once. It is also the only slice where a bad write is
  hard to undo, so it is where engineering care pays off most.

I did not have real frequency data. The leverage case rests on the brief's own statements
(hiring fast, changes after offer, manual and undocumented today). With BetterUp numbers I'd
replace that with changes per hire × systems touched × minutes per manual fix.

Excluded on purpose: the 7-day gate monitoring (needs deadline data from systems not modelled
here). See `docs/SYSTEMS_MAP.md` for the map, break points and flow.

## 2. Stack discipline

| Need | Existing stack used | Added |
|---|---|---|
| Trigger on Ashby changes | Ashby webhook → **n8n** (or Zapier) calling `POST /changes/propagate` | none |
| Source of truth / targets | Ashby, Workday, Okta/Lumos, equipment, cohort tracker (mocked connectors, one per system) | none |
| Human escalation | **Slack** | none |
| Triage of conflicts | **Claude** via API | none |

**The one thing I added is this small service (FastAPI + SQLite), and I'd defend it narrowly.**
n8n/Zapier are strong at linear trigger → action flows. What this problem needs, and what I
would not want to build out of nodes, is: (1) check *all* targets before writing *any*,
(2) compensating rollback when the third write fails, (3) durable idempotency keys with
crash-resume, and (4) per-system field mapping/transforms (e.g. equipment ship-by = start − 7).
So n8n stays as the trigger/router layer and calls this service for the stateful part. If BetterUp's
n8n can already express (1)–(3) reliably, I would drop the service and port the connectors, which is
the first thing I'd verify.

SQLite stands in for whatever durable store the platform team prefers; nothing depends on it.

## 3. Claude as a component

`app/classifier.py`. When validation finds a conflict, Claude receives a **redacted** structured
report (emails masked) and must call one tool, `classify_conflict`, returning
`{category, recommended_action, confidence, rationale}`.

Guardrails that make it safe to use:

* **Claude never decides validity and never writes.** Deterministic code decided there was a
  conflict before Claude was called; the output is advisory.
* **Forced tool-use + Pydantic validation.** A value outside the enum is rejected.
* **Deterministic guardrails after the call:** confidence < 0.7 → escalate; a conflict in Ashby
  itself can't recommend "refresh old value"; identity fields (manager, location) can't be
  auto-refreshed. The applied guardrail is recorded in the response.
* **Failure isolation:** timeout, HTTP error, malformed output, or an exception falls back to a
  rule-based classifier. Propagation results never depend on the model being up.
* **Untrusted data:** system values are treated as data in the prompt; because output is
  schema-bound and guard-railed, an injected instruction in a field value can at worst yield a
  wrong *advisory* label, never a write.

Without `ANTHROPIC_API_KEY` the service uses the rule-based classifier, so demo and tests run
offline. **Status: the Claude path is unit-tested against a fake transport (request shape,
parsing, redaction, every fallback). I have not yet run it against the live API.** Run it once
with a real key before the walkthrough.

## 4. Key design decisions

* **Data model.** `changes(change_id PK, payload, status in_progress|done, result)` and an
  append-only `audit_log(change_id, ts, event, detail)`. The audit trail is exposed at
  `GET /changes/{id}/audit`.
* **Idempotency.** Same `change_id` + same payload → stored result, nothing rewritten.
  Same id + different payload → rejected. Keys survive restarts (tested with a file DB). A
  retention method (`purge_older_than`) drops finished keys after N days; unfinished rows are
  never purged.
* **Crash-resume.** A repeat of an `in_progress` change re-runs; a target already holding the
  new value counts as OK and is not rewritten.
* **Failure handling.** Reads and writes retry on `ConnectorError` only, 3 attempts with
  exponential backoff (0.25s, 0.5s). If a write still fails, targets already written this run are
  restored. If a restore fails too, the response lists the stuck systems, says manual
  reconciliation is required, and Slack is paged.
* **PII.** Slack messages carry the change/employee id, field name and conflict category, never
  values or model-written text (the rationale stays in the API response and audit trail). Emails
  are masked before they go to Claude; other field values (department, location) are sent as-is.

## 5. What I'd productionize

1. Real authenticated connectors (OAuth/SSO or service accounts, secrets in a vault).
2. Per-employee locking or queue partitioning; today a process-wide lock serialises changes.
3. A reconciliation job that periodically re-reads systems and detects drift that no change
   event announced (the real fix for non-atomic cross-system writes).
4. Dead-letter queue and alerting on repeated integration failures; rate-limit handling.
5. Human-approval step for identity-affecting fields before write, not just after conflict.
6. Contract tests per connector; run the Claude path against recorded fixtures in CI.
7. Zero-retention / data-processing review before sending any employee data to a model.
8. Move the 7-day gate monitoring onto the same audit/notifier foundation.

Known limits: mocked systems are in-memory and reseeded on start; cross-system writes are not
atomic (compensation is best-effort); a replayed result reflects the original run, not
current system state.

## 6. AI tools and where they were wrong

Tools: Claude (drafting, review and this revision after the feedback round).

* **Wrote vs delegated:** _[Parvind: fill in your own split here. e.g. which modules you wrote by
  hand, which Claude drafted and you rewrote. The feedback asked for this granularity and only
  you can state it truthfully.]_
* **Wrong #1 (earlier round):** validation referenced `work_location` before it existed on the
  Pydantic model. Tests raised `AttributeError`; I fixed the model.
* **Wrong #2 (this round):** my first demo script claimed a repeat change with a new ID would
  conflict. Running it against the live server showed it propagated as a no-op, which is the
  intended "already at new value is OK" rule that makes crash-resume safe. The script was wrong,
  not the service, so I replaced the scenario with a genuinely stale request and kept the rule.
