const assert = require('node:assert/strict');
const test = require('node:test');
const app = require('../../static/js/app.js');

class FakeTarget {
  constructor() {
    this.listeners = new Map();
    this.open = false;
    this.focused = false;
  }

  addEventListener(type, listener) {
    const listeners = this.listeners.get(type) || [];
    listeners.push(listener);
    this.listeners.set(type, listeners);
  }

  dispatchEvent(event) {
    if (!event.target) event.target = this;
    for (const listener of this.listeners.get(event.type) || []) listener(event);
  }

  focus() {
    this.focused = true;
  }
}

function mobileNavigationFixture() {
  const document = new FakeTarget();
  const details = new FakeTarget();
  const summary = new FakeTarget();
  const link = new FakeTarget();
  document.querySelector = (selector) => (
    selector === 'details[data-mobile-navigation]' ? details : null
  );
  details.querySelector = (selector) => selector === 'summary' ? summary : null;
  link.closest = (selector) => selector === 'a[href]' ? link : null;
  return { document, details, summary, link };
}

test('Escape closes the mobile menu and restores summary focus', () => {
  const view = mobileNavigationFixture();
  view.details.open = true;
  app.initializeMobileNavigation(view.document);
  view.document.dispatchEvent({ type: 'keydown', key: 'Escape' });
  assert.equal(view.details.open, false);
  assert.equal(view.summary.focused, true);
});

test('activating a mobile navigation link closes the menu', () => {
  const view = mobileNavigationFixture();
  view.details.open = true;
  app.initializeMobileNavigation(view.document);
  view.details.dispatchEvent({ type: 'click', target: view.link });
  assert.equal(view.details.open, false);
});

test('missing mobile-navigation markup returns safely', () => {
  const document = new FakeTarget();
  document.querySelector = () => null;
  assert.equal(app.initializeMobileNavigation(document), null);
});

test('a document without querySelector returns safely', () => {
  assert.equal(app.initializeMobileNavigation({}), null);
});
