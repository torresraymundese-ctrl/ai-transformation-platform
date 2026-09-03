"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");

global.window = {
  matchMedia: function () { return { matches: false }; },
};
global.document = {
  getElementById: function () { return null; },
};

const wizard = require("../../static/js/assessment.js");


test("successful completion redirects when storage cleanup throws", function () {
  const assigned = [];
  const browser = {
    sessionStorage: {
      removeItem: function () { throw new Error("storage blocked"); },
    },
    location: {
      assign: function (url) { assigned.push(url); },
    },
  };

  wizard.clearStoredStateAndRedirect(
    browser,
    "assessment-v2-state",
    "/assessment/report/41"
  );

  assert.deepEqual(assigned, ["/assessment/report/41"]);
});


test("successful completion redirects when sessionStorage acquisition throws", function () {
  const assigned = [];
  const browser = {
    location: {
      assign: function (url) { assigned.push(url); },
    },
  };
  Object.defineProperty(browser, "sessionStorage", {
    get: function () { throw new Error("storage getter blocked"); },
  });

  assert.doesNotThrow(function () {
    wizard.clearStoredStateAndRedirect(
      browser,
      "assessment-v2-state",
      "/assessment/report/42"
    );
  });

  assert.deepEqual(assigned, ["/assessment/report/42"]);
});


test("busy state freezes and restores every mutable form control", function () {
  const controls = Array.from({ length: 4 }, function () {
    return { disabled: false };
  });
  const attributes = {};
  const root = {
    setAttribute: function (name, value) { attributes[name] = value; },
    querySelectorAll: function (selector) {
      assert.equal(selector, "button, input, select, textarea");
      return controls;
    },
  };

  wizard.setMutableControlsBusy(root, true);
  assert.equal(attributes["aria-busy"], "true");
  assert.ok(controls.every(function (control) { return control.disabled; }));

  wizard.setMutableControlsBusy(root, false);
  assert.equal(attributes["aria-busy"], "false");
  assert.ok(controls.every(function (control) { return !control.disabled; }));
});


test("configuration retry is recoverable and stale responses are rejected", async function () {
  assert.equal(
    wizard.configurationResponseIsCurrent(3, 3, "retail", "retail"),
    true
  );
  assert.equal(
    wizard.configurationResponseIsCurrent(2, 3, "retail", "retail"),
    false
  );
  assert.equal(
    wizard.configurationResponseIsCurrent(3, 3, "manufacturing", "retail"),
    false
  );

  let attempts = 0;
  const failed = await wizard.ensureConfigurationAvailable(
    "retail",
    null,
    async function () { attempts += 1; return false; }
  );
  const recovered = await wizard.ensureConfigurationAvailable(
    "retail",
    null,
    async function (branch) { attempts += 1; return branch === "retail"; }
  );

  assert.equal(failed, false);
  assert.equal(recovered, true);
  assert.equal(attempts, 2);
});


test("flow credentials never enter browser recovery storage", function () {
  const snapshot = wizard.storageSafeAssessmentState({
    step: 2,
    branchCode: "manufacturing",
    subbranchCode: "discrete_manufacturing",
    departmentCode: "production",
    companySizeCode: "50_200",
    painCodes: ["production_reporting"],
    answers: { process_documentation: "level_3" },
    roiChoices: { headcount: "6_20" },
    submissionKey: "00000000-0000-4000-8000-000000000021",
    attribution: { utm_source: "organic" },
    flow_id: "secret-flow-id",
    flowId: "secret-flow-id",
    rule_version: "secret-rule-version",
    legal_ids: { privacy: 41 },
  });

  assert.deepEqual(Object.keys(snapshot).sort(), [
    "answers",
    "attribution",
    "branchCode",
    "companySizeCode",
    "departmentCode",
    "painCodes",
    "roiChoices",
    "step",
    "subbranchCode",
    "submissionKey",
  ]);
  assert.equal(JSON.stringify(snapshot).includes("secret-flow-id"), false);
  assert.equal(JSON.stringify(snapshot).includes("secret-rule-version"), false);
});


test("initial attribution drops normalized contact-like values", function () {
  assert.equal(wizard.privacySafeAttribution("organic-search"), "organic-search");
  assert.equal(wizard.privacySafeAttribution("ｌｅａｄ＠ｅｘａｍｐｌｅ．ｃｏｍ"), "");
  assert.equal(wizard.privacySafeAttribution("ref +86 (138) 0013-8000"), "");
  assert.equal(wizard.privacySafeAttribution("١٣٨٠٠١٣٨٠٠٠"), "");
  assert.equal(wizard.privacySafeAttribution("campaign-2026-08-19-123"), "");
  assert.equal(wizard.privacySafeAttribution("x".repeat(120)).length, 100);
});


test("contact validation trims required values and enforces dotted email", function () {
  const blank = wizard.validateContactValues({
    company_name: "   ",
    contact_name: " 张先生 ",
    phone: " 13800138000 ",
    email: "",
    wechat: "",
  });
  assert.equal(blank.valid, false);
  assert.equal(blank.fieldId, "company-name");

  const undotted = wizard.validateContactValues({
    company_name: " 示例企业 ",
    contact_name: " 张先生 ",
    phone: " 13800138000 ",
    email: "lead@localhost",
    wechat: " wx-id ",
  });
  assert.equal(undotted.valid, false);
  assert.equal(undotted.fieldId, "email");

  const valid = wizard.validateContactValues({
    company_name: " 示例企业 ",
    contact_name: " 张先生 ",
    phone: " +86 138-0013-8000 ",
    email: " lead@example.invalid ",
    wechat: " wx-id ",
  });
  assert.equal(valid.valid, true);
  assert.deepEqual(valid.values, {
    company_name: "示例企业",
    contact_name: "张先生",
    phone: "+86 138-0013-8000",
    email: "lead@example.invalid",
    wechat: "wx-id",
  });
});


test("assessment analytics starts once and never retries a failed user action", async function () {
  const state = { started: false };
  const attempts = [];
  const tracker = function (eventName, metadata) {
    attempts.push([eventName, metadata]);
    return Promise.reject(new Error("offline"));
  };

  const first = await wizard.trackAssessmentStartOnce(
    state,
    tracker,
    { branch_code: "manufacturing" }
  );
  const duplicate = await wizard.trackAssessmentStartOnce(
    state,
    tracker,
    { branch_code: "retail" }
  );
  const step = await wizard.emitAssessmentEvent(
    tracker,
    "assessment_step_completed",
    { step: "profile", branch_code: "manufacturing" }
  );

  assert.equal(first, false);
  assert.equal(duplicate, false);
  assert.equal(step, false);
  assert.deepEqual(attempts, [
    ["assessment_started", { branch_code: "manufacturing" }],
    [
      "assessment_step_completed",
      { step: "profile", branch_code: "manufacturing" },
    ],
  ]);
});
