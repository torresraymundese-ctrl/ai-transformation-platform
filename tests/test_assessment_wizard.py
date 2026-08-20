import re
from pathlib import Path

from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "templates" / "assessment.html"
SCRIPT = ROOT / "static" / "js" / "assessment.js"
STYLES = ROOT / "static" / "css" / "assessment.css"


def test_assessment_page_loads_external_v2_wizard_assets(client):
    """Removing the V2 asset boundary must break the public assessment page."""
    response = client.get("/assessment")
    page = BeautifulSoup(response.data, "html.parser")

    assert response.status_code == 200
    assert page.select_one('link[href="/static/css/assessment.css"]')
    script = page.select_one('script[src="/static/js/assessment.js"]')
    assert script is not None and script.has_attr("defer")
    assert page.select_one("#assessment-wizard[data-config-base]")
    assert page.select_one("#assessment-step")
    assert page.select_one('#assessment-progress[aria-labelledby="assessment-progress-text"]')
    assert page.select_one("#assessment-progress-text")
    assert page.select_one('#assessment-live-status[aria-live="polite"]')
    assert page.select_one('#assessment-error[role="alert"]')
    assert page.select_one('#assessment-back[type="button"]')
    assert page.select_one('#assessment-continue[type="button"]')

    template_source = TEMPLATE.read_text(encoding="utf-8")
    assert "const INDUSTRIES" not in template_source
    assert "INDUSTRY_QUESTIONS" not in template_source
    assert "<style" not in template_source
    assert not re.search(r"<script(?![^>]+src=)", template_source)


def test_contact_gate_is_native_labelled_and_private_by_default(client):
    """Removing labels, required fields, or opt-in consent must fail loudly."""
    page = BeautifulSoup(client.get("/assessment").data, "html.parser")
    gate = page.select_one("#assessment-contact-gate[hidden]")

    assert gate is not None
    for field_id in ("company-name", "contact-name", "phone", "email", "wechat"):
        field = gate.select_one(f"#{field_id}")
        label = gate.select_one(f'label[for="{field_id}"]')
        assert field is not None and label is not None
    for field_id in ("company-name", "contact-name", "phone"):
        assert gate.select_one(f"#{field_id}").has_attr("required")
    assert not gate.select_one("#email").has_attr("required")
    assert not gate.select_one("#wechat").has_attr("required")

    consent = gate.select_one('#privacy-consent[type="checkbox"][required]')
    assert consent is not None
    assert not consent.has_attr("checked")
    assert gate.select_one('label[for="privacy-consent"]')
    assert gate.select_one("#privacy-summary")
    assert gate.select_one("#privacy-policy-link")
    assert gate.select_one("#preview-maturity")
    assert gate.select_one("#preview-strongest")
    assert gate.select_one("#preview-weakest")


def test_wizard_source_enforces_safe_dom_and_six_step_contract():
    """Unsafe HTML rendering or a missing step must be caught before browser QA."""
    source = SCRIPT.read_text(encoding="utf-8")

    assert 'const STEPS = ["profile", "pain", "value_process", "data_systems", "org_delivery", "roi"]' in source
    assert "document.createElement" in source
    assert ".textContent" in source
    assert "innerHTML" not in source
    assert "insertAdjacentHTML" not in source
    assert "eval(" not in source
    assert "input.type = multi ? \"checkbox\" : \"radio\"" in source
    assert "label.htmlFor = input.id" in source
    assert "errorTarget.focus()" in source
    assert "prefers-reduced-motion" in source


def test_storage_snapshot_is_non_contact_and_restores_one_submission_key():
    """A storage regression must never persist lead contact fields or rotate keys."""
    source = SCRIPT.read_text(encoding="utf-8")
    snapshot = re.search(
        r"function storedStateSnapshot\(\) \{(?P<body>.*?)\n  \}",
        source,
        re.DOTALL,
    )

    assert snapshot is not None
    stored_body = snapshot.group("body")
    for key in (
        "step",
        "branchCode",
        "subbranchCode",
        "departmentCode",
        "companySizeCode",
        "painCodes",
        "answers",
        "roiChoices",
        "submissionKey",
        "attribution",
    ):
        assert re.search(rf"\b{key}\b", stored_body)
    for contact_key in (
        "companyName",
        "contactName",
        "phone",
        "email",
        "wechat",
        "consent",
    ):
        assert contact_key not in stored_body

    assert source.count("crypto.randomUUID()") == 1
    assert "const restoredState = readStoredState();" in source
    assert "restoredState.submissionKey" in source
    assert 'sessionStorage.setItem(STORAGE_KEY, JSON.stringify(storedStateSnapshot()))' in source
    assert "sessionStorage.removeItem(STORAGE_KEY)" in source
    assert "params.get(key).slice(0, ATTRIBUTION_LIMIT)" in source
    assert 'const ATTRIBUTION_KEYS = ["utm_source", "utm_medium", "utm_campaign"]' in source


def test_requests_disable_actions_and_failure_paths_preserve_entered_state():
    """Network failures must leave the assessment and contact form retryable."""
    source = SCRIPT.read_text(encoding="utf-8")

    assert "function setBusy(isBusy)" in source
    assert "button.disabled = isBusy" in source
    assert source.count("setBusy(true)") >= 3
    assert source.count("setBusy(false)") >= 3
    assert 'await requestJson("/api/v2/assessment/preview"' in source
    assert 'await requestJson("/api/v2/assessment/complete"' in source
    assert "window.location.assign(result.report_url)" in source
    assert 'form.addEventListener("submit"' in source
    assert "event.preventDefault()" in source

    preview = re.search(
        r"async function requestPreview\(\) \{(?P<body>.*?)\n  \}",
        source,
        re.DOTALL,
    )
    complete = re.search(
        r"async function requestCompletion\(\) \{(?P<body>.*?)\n  \}",
        source,
        re.DOTALL,
    )
    assert preview is not None and complete is not None
    for body in (preview.group("body"), complete.group("body")):
        assert "catch (error)" in body
        assert "showError(" in body
        assert "finally" in body
        assert "state.answers = {}" not in body
        assert "state.roiChoices = {}" not in body
        assert "sessionStorage.removeItem" not in body.split("catch (error)", 1)[1]


def test_assessment_styles_are_mobile_first_and_respect_reduced_motion():
    """Dropping focus, mobile, or motion safeguards must fail source QA."""
    source = STYLES.read_text(encoding="utf-8")

    assert ":focus-visible" in source
    assert "@media (min-width: 48rem)" in source
    assert "@media (prefers-reduced-motion: reduce)" in source
    assert ".assessment-route .sticky-cta" in source
    assert "overflow-wrap: anywhere" in source
