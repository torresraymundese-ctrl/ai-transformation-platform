"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");

global.window = {
  addEventListener: function () {},
  setTimeout: function () {},
};
global.document = {
  body: null,
  getElementById: function () { return null; },
  querySelectorAll: function () { return []; },
  addEventListener: function () {},
};

const analytics = require("../../static/js/app.js");


test("analytics transport sends exactly once and swallows async or sync failure", async function () {
  const asyncCalls = [];
  const asyncResult = await analytics.sendAnalyticsEvent(
    function (url, options) {
      asyncCalls.push([url, options]);
      return Promise.reject(new Error("offline"));
    },
    "/api/v2/events",
    "csrf-token",
    "home_viewed",
    { page: "home" }
  );

  assert.equal(asyncResult, false);
  assert.equal(asyncCalls.length, 1);
  assert.equal(asyncCalls[0][0], "/api/v2/events");
  assert.equal(asyncCalls[0][1].method, "POST");
  assert.equal(asyncCalls[0][1].credentials, "same-origin");
  assert.equal(asyncCalls[0][1].headers["X-CSRF-Token"], "csrf-token");
  assert.deepEqual(JSON.parse(asyncCalls[0][1].body), {
    event_name: "home_viewed",
    metadata: { page: "home" },
  });

  let syncAttempts = 0;
  const syncResult = await analytics.sendAnalyticsEvent(
    function () {
      syncAttempts += 1;
      throw new Error("blocked");
    },
    "/api/v2/events",
    "csrf-token",
    "phone_clicked",
    { page: "home" }
  );
  assert.equal(syncResult, false);
  assert.equal(syncAttempts, 1);
});


test("page initialization fires one home event and one event per click", async function () {
  const calls = [];
  let clickHandler;
  const page = {
    body: {
      dataset: {
        analyticsEndpoint: "/api/v2/events",
        analyticsCsrfToken: "csrf-token",
        analyticsPage: "home",
      },
    },
    addEventListener: function (name, handler) {
      if (name === "click") clickHandler = handler;
    },
  };
  const fetchImpl = async function (url, options) {
    calls.push([url, JSON.parse(options.body)]);
    return { ok: false, status: 503 };
  };

  analytics.initializeConversionAnalytics(page, fetchImpl);
  await Promise.resolve();
  clickHandler({
    target: {
      closest: function (selector) {
        assert.equal(selector, "[data-analytics-event]");
        return {
          dataset: {
            analyticsEvent: "service_inquiry_clicked",
            analyticsSource: "services",
          },
        };
      },
    },
  });
  await Promise.resolve();

  assert.deepEqual(calls, [
    [
      "/api/v2/events",
      { event_name: "home_viewed", metadata: { page: "home" } },
    ],
    [
      "/api/v2/events",
      {
        event_name: "service_inquiry_clicked",
        metadata: { page: "home", source: "services" },
      },
    ],
  ]);
});


test("external FAQ behavior toggles answer, arrow, and expanded state together", function () {
  const calls = [];
  const answer = {
    classList: {
      toggle: function (name) {
        calls.push(["answer", name]);
        return true;
      },
    },
  };
  const arrow = {
    classList: {
      toggle: function (name, force) {
        calls.push(["arrow", name, force]);
      },
    },
  };
  const attributes = {};
  const toggle = {
    nextElementSibling: answer,
    querySelector: function (selector) {
      assert.equal(selector, ".faq-arrow");
      return arrow;
    },
    setAttribute: function (name, value) {
      attributes[name] = value;
    },
  };

  assert.equal(analytics.toggleFaq(toggle), true);
  assert.deepEqual(calls, [
    ["answer", "open"],
    ["arrow", "open", true],
  ]);
  assert.equal(attributes["aria-expanded"], "true");
});
