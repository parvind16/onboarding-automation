import httpx

from app.classifier import (
    ClaudeExceptionClassifier,
    RuleBasedClassifier,
    apply_guardrails,
    get_default_classifier,
    redact,
)
from app.models import Conflict, ConflictClassification
from tests.conftest import EMP, make_change, make_service


class FakeResponse:
    def __init__(self, body, status=200):
        self._body, self.status = body, status

    def raise_for_status(self):
        if self.status >= 400:
            raise httpx.HTTPStatusError(
                "boom", request=httpx.Request("POST", "http://x"), response=self
            )

    def json(self):
        return self._body


def tool_use(**fields):
    return FakeResponse(
        {"content": [{"type": "tool_use", "name": "classify_conflict", "input": fields}]}
    )


GOOD = dict(
    category="stale_target",
    recommended_action="refresh_expected_old_value",
    confidence=0.9,
    rationale="Workday drifted from the expected value.",
)

CONFLICTS = [Conflict(system="workday", expected="Engineering", found="Finance")]


def claude_with(response, calls=None):
    def post(url, headers, json, timeout):
        if calls is not None:
            calls.append((url, headers, json))
        if isinstance(response, Exception):
            raise response
        return response

    return ClaudeExceptionClassifier("sk-test", post=post)


# ---- the Claude call -------------------------------------------------------


def test_claude_result_is_parsed_and_marked_as_claude():
    result = claude_with(tool_use(**GOOD)).classify(make_change(), CONFLICTS)

    assert result.category == "stale_target"
    assert result.classified_by == "claude"


def test_request_forces_the_tool_and_keeps_the_key_in_headers_only():
    calls = []
    claude_with(tool_use(**GOOD), calls).classify(make_change(), CONFLICTS)

    url, headers, body = calls[0]
    assert url == "https://api.anthropic.com/v1/messages"
    assert headers["x-api-key"] == "sk-test"
    assert body["tool_choice"] == {"type": "tool", "name": "classify_conflict"}
    assert "sk-test" not in str(body)


def test_emails_are_redacted_before_leaving_the_service():
    calls = []
    change = make_change("manager_email")
    conflicts = [
        Conflict(system="workday", expected=change.old_value, found="someone.else@example.com")
    ]
    claude_with(tool_use(**GOOD), calls).classify(change, conflicts)

    sent = calls[0][2]["messages"][0]["content"]
    assert "someone.else@example.com" not in sent
    assert "s***@example.com" in sent
    assert redact("a@b.com") == "a***@b.com"


def test_http_error_falls_back_to_rules():
    result = claude_with(FakeResponse({}, status=529)).classify(make_change(), CONFLICTS)

    assert result.classified_by == "rules"
    assert result.guardrail_applied == "claude_unavailable_used_rules"


def test_network_timeout_falls_back_to_rules():
    result = claude_with(httpx.ReadTimeout("slow")).classify(make_change(), CONFLICTS)

    assert result.classified_by == "rules"


def test_schema_violation_from_model_falls_back_to_rules():
    bad = tool_use(**{**GOOD, "recommended_action": "overwrite_all_systems"})

    result = claude_with(bad).classify(make_change(), CONFLICTS)

    assert result.classified_by == "rules"
    assert result.recommended_action != "overwrite_all_systems"


def test_missing_tool_block_falls_back_to_rules():
    result = claude_with(FakeResponse({"content": [{"type": "text", "text": "hi"}]})).classify(
        make_change(), CONFLICTS
    )

    assert result.classified_by == "rules"


# ---- deterministic guardrails ------------------------------------------------


def test_low_confidence_is_escalated():
    low = ConflictClassification(**{**GOOD, "confidence": 0.4})

    out = apply_guardrails(low, make_change(), CONFLICTS)

    assert out.recommended_action == "escalate_to_human"
    assert out.guardrail_applied.startswith("confidence_below")


def test_identity_fields_cannot_be_auto_refreshed():
    change = make_change("manager_email")
    out = apply_guardrails(ConflictClassification(**GOOD), change, CONFLICTS)

    assert out.recommended_action == "escalate_to_human"
    assert out.guardrail_applied == "identity_field_requires_human"


def test_source_conflict_cannot_refresh_old_value():
    conflicts = [Conflict(system="ashby", expected="Product", found="Sales")]
    out = apply_guardrails(ConflictClassification(**GOOD), make_change(), conflicts)

    assert out.recommended_action == "escalate_to_human"


def test_safe_classification_passes_through_untouched():
    original = ConflictClassification(**GOOD)

    assert apply_guardrails(original, make_change(), CONFLICTS) == original


# ---- wired into the service -----------------------------------------------------


def test_service_uses_claude_classification_but_guardrails_still_apply():
    # Claude (wrongly) says "refresh" for an identity field -> guardrail wins.
    claude = claude_with(tool_use(**GOOD))
    service = make_service(classifier=claude)
    service.systems["workday"].seed(EMP, {"manager_email": "someone.else@example.com"})

    result = service.process_change(make_change("manager_email"))

    assert result.status == "conflict"
    assert result.classification.classified_by == "claude"
    assert result.classification.recommended_action == "escalate_to_human"
    assert result.escalated is True
    # Claude's output changed nothing in any system.
    assert service.systems["okta_lumos"].read(EMP, "manager_email") == "old.manager@example.com"


def test_service_survives_a_classifier_that_raises():
    class Exploding:
        def classify(self, change, conflicts):
            raise RuntimeError("model client crashed")

    service = make_service(classifier=Exploding())
    service.systems["workday"].seed(EMP, {"department": "Finance"})

    result = service.process_change(make_change())

    assert result.status == "conflict"
    assert result.classification.classified_by == "rules"


def test_default_classifier_depends_on_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert isinstance(get_default_classifier(), RuleBasedClassifier)

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert isinstance(get_default_classifier(), ClaudeExceptionClassifier)


def test_model_written_rationale_never_reaches_slack():
    leaky = tool_use(**{**GOOD, "rationale": "Engineering vs Finance mismatch"})
    service = make_service(classifier=claude_with(leaky))
    service.systems["workday"].seed(EMP, {"manager_email": "x.y@example.com"})

    service.process_change(make_change("manager_email"))

    _, text = service.notifier.messages[0]
    assert "Engineering" not in text and "Finance" not in text
