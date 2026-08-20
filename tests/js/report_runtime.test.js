"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");

global.window = {};
Object.defineProperty(global.window, "sessionStorage", {
  get: function () { throw new Error("appointment form must not use sessionStorage"); },
});
global.document = {
  getElementById: function () { return null; },
};

const appointmentForm = require("../../static/js/report.js");


function fakeForm() {
  const controls = Array.from({ length: 6 }, function () {
    return { disabled: false };
  });
  const attributes = {};
  const feedback = { textContent: "" };
  const error = { hidden: true, textContent: "" };
  return {
    action: "/api/v2/appointments",
    attributes: attributes,
    controls: controls,
    feedback: feedback,
    error: error,
    getAttribute: function (name) { return attributes[name]; },
    setAttribute: function (name, value) { attributes[name] = value; },
    querySelectorAll: function (selector) {
      assert.equal(selector, "button, input, textarea");
      return controls;
    },
    querySelector: function (selector) {
      if (selector === "[data-appointment-feedback]") return feedback;
      if (selector === "[data-appointment-error]") return error;
      throw new Error("unexpected selector " + selector);
    },
  };
}


function fakeData() {
  const values = new Map([
    ["assessment_id", "42"],
    ["submission_key", "550e8400-e29b-41d4-a716-446655440000"],
    ["preferred_date", "2026-08-25"],
    ["time_slot", "afternoon"],
    ["note", " 希望先讨论客服场景 "],
    ["csrf_token", "csrf-secret"],
  ]);
  return { get: function (name) { return values.get(name); } };
}


test("pending submission locks once and success remains locked with live feedback", async function () {
  const form = fakeForm();
  const calls = [];
  let resolveFetch;
  const fetchImpl = function (url, options) {
    calls.push([url, options]);
    return new Promise(function (resolve) { resolveFetch = resolve; });
  };

  const pending = appointmentForm.submitAppointmentIntent(
    form,
    fetchImpl,
    function () { return fakeData(); }
  );
  const duplicate = await appointmentForm.submitAppointmentIntent(
    form,
    fetchImpl,
    function () { return fakeData(); }
  );

  assert.equal(form.attributes["aria-busy"], "true");
  assert.ok(form.controls.every(function (control) { return control.disabled; }));
  assert.equal(calls.length, 1);
  assert.equal(duplicate, null);
  const request = JSON.parse(calls[0][1].body);
  assert.deepEqual(request, {
    assessment_id: 42,
    submission_key: "550e8400-e29b-41d4-a716-446655440000",
    preferred_date: "2026-08-25",
    time_slot: "afternoon",
    note: "希望先讨论客服场景",
  });
  assert.deepEqual(calls[0].slice(0, 1), ["/api/v2/appointments"]);
  assert.equal(calls[0][1].method, "POST");
  assert.equal(calls[0][1].credentials, "same-origin");
  assert.equal(calls[0][1].headers["Content-Type"], "application/json");
  assert.equal(calls[0][1].headers["X-CSRF-Token"], "csrf-secret");

  resolveFetch({
    ok: true,
    status: 200,
    json: async function () {
      return { success: true, appointment_id: 7, status: "pending" };
    },
  });
  const result = await pending;

  assert.equal(result.appointment_id, 7);
  assert.match(form.feedback.textContent, /已提交/);
  assert.equal(form.error.hidden, true);
  assert.equal(form.attributes["aria-busy"], "true");
  assert.ok(form.controls.every(function (control) { return control.disabled; }));
});


test("failed submission unlocks controls and exposes safe alert feedback", async function () {
  const form = fakeForm();
  const result = await appointmentForm.submitAppointmentIntent(
    form,
    async function () {
      return {
        ok: false,
        status: 503,
        json: async function () { return { error: "private server detail" }; },
      };
    },
    function () { return fakeData(); }
  );

  assert.equal(result, null);
  assert.equal(form.attributes["aria-busy"], "false");
  assert.ok(form.controls.every(function (control) { return !control.disabled; }));
  assert.equal(form.error.hidden, false);
  assert.match(form.error.textContent, /稍后重试/);
  assert.doesNotMatch(form.error.textContent, /private server detail/);
});
