(function () {
  "use strict";

  const form = document.getElementById("appointment-intent-form");
  if (typeof module !== "undefined" && module.exports) {
    module.exports = {
      setAppointmentBusy: setAppointmentBusy,
      submitAppointmentIntent: submitAppointmentIntent,
    };
  }
  if (!form) return;

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    if (!form.reportValidity()) return;
    submitAppointmentIntent(form, window.fetch.bind(window));
  });

  async function submitAppointmentIntent(target, fetchImpl, formDataFactory) {
    if (
      target.getAttribute("aria-busy") === "true" ||
      target.getAttribute("data-submitted") === "true"
    ) return null;
    const createFormData = formDataFactory || function (element) {
      return new FormData(element);
    };
    const values = createFormData(target);
    const feedback = target.querySelector("[data-appointment-feedback]");
    const error = target.querySelector("[data-appointment-error]");
    const payload = {
      assessment_id: Number(values.get("assessment_id")),
      submission_key: values.get("submission_key"),
      preferred_date: values.get("preferred_date"),
      time_slot: values.get("time_slot"),
      note: String(values.get("note") || "").trim(),
    };

    feedback.textContent = "正在提交预约意向…";
    error.textContent = "";
    error.hidden = true;
    setAppointmentBusy(target, true);
    try {
      const response = await fetchImpl(target.action, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": values.get("csrf_token"),
        },
        body: JSON.stringify(payload),
      });
      let result = {};
      try {
        result = await response.json();
      } catch (_error) {
        result = {};
      }
      if (!response.ok || result.success !== true) {
        throw new Error("appointment request failed");
      }
      setAppointmentSubmitted(target);
      feedback.textContent = "预约意向已提交，顾问将在后续联系中确认具体时间。";
      return result;
    } catch (_error) {
      feedback.textContent = "";
      error.textContent = "提交未完成，请稍后重试。";
      error.hidden = false;
      setAppointmentBusy(target, false);
      return null;
    }
  }

  function setAppointmentBusy(target, isBusy) {
    target.setAttribute("aria-busy", String(isBusy));
    target.querySelectorAll("button, input, textarea").forEach(function (control) {
      control.disabled = isBusy;
    });
  }

  function setAppointmentSubmitted(target) {
    target.setAttribute("aria-busy", "false");
    target.setAttribute("data-submitted", "true");
    target.querySelectorAll("button, input, textarea").forEach(function (control) {
      control.disabled = true;
    });
  }
})();
