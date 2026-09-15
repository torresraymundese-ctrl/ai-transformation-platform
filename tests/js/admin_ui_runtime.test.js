const assert = require('node:assert/strict');
const test = require('node:test');

const adminUi = require('../../static/js/admin_ui.js');

class FakeElement {
  constructor() {
    this.dataset = {};
    this.listeners = new Map();
    this.focusCount = 0;
    this.scrollOptions = [];
    this.section = null;
  }

  addEventListener(type, callback, capture = false) {
    const key = `${type}:${capture}`;
    this.listeners.set(key, [...(this.listeners.get(key) || []), callback]);
  }

  dispatch(type, event, capture = false) {
    for (const callback of this.listeners.get(`${type}:${capture}`) || []) callback(event);
  }

  closest(selector) {
    return selector === '.admin-editor-section' ? this.section : null;
  }

  focus() { this.focusCount += 1; }

  scrollIntoView(options) { this.scrollOptions.push(options); }
}

class FakeDocument {
  constructor(forms = [], summary = null) {
    this.forms = forms;
    this.summary = summary;
  }

  querySelectorAll(selector) {
    assert.equal(selector, 'form[data-admin-editor]');
    return this.forms;
  }

  querySelector(selector) {
    if (selector === '[data-admin-nav]') return null;
    assert.equal(selector, '[data-admin-error-summary]');
    return this.summary;
  }
}

function windowWithMotionPreference(reduced) {
  return {
    matchMedia(query) {
      assert.equal(query, '(prefers-reduced-motion: reduce)');
      return { matches: reduced };
    },
  };
}

test('invalid native field navigates to its editor section without preventing submit', () => {
  const form = new FakeElement();
  const section = new FakeElement();
  const field = new FakeElement();
  field.section = section;
  const event = {
    target: field,
    prevented: false,
    preventDefault() { this.prevented = true; },
  };

  adminUi.bind(new FakeDocument([form]), windowWithMotionPreference(false));
  form.dispatch('invalid', event, true);

  assert.equal(event.prevented, false);
  assert.equal(field.focusCount, 1);
  assert.deepEqual(section.scrollOptions, [{ behavior: 'smooth', block: 'start' }]);
});

test('reduced motion invalid navigation scrolls without animation', () => {
  const form = new FakeElement();
  const section = new FakeElement();
  const field = new FakeElement();
  field.section = section;

  adminUi.bind(new FakeDocument([form]), windowWithMotionPreference(true));
  form.dispatch('invalid', { target: field }, true);

  assert.deepEqual(section.scrollOptions, [{ behavior: 'auto', block: 'start' }]);
});

test('server error summary receives focus once and repeated binding is idempotent', () => {
  const summary = new FakeElement();
  const documentObject = new FakeDocument([], summary);

  adminUi.bind(documentObject, windowWithMotionPreference(false));
  adminUi.bind(documentObject, windowWithMotionPreference(false));

  assert.equal(summary.focusCount, 1);
});

test('absent form and summary are a no-op and never access browser storage', () => {
  let storageAccesses = 0;
  const guardedWindow = {
    matchMedia() { return { matches: false }; },
    get localStorage() { storageAccesses += 1; throw new Error('storage forbidden'); },
    get sessionStorage() { storageAccesses += 1; throw new Error('storage forbidden'); },
  };

  assert.doesNotThrow(() => adminUi.bind(new FakeDocument(), guardedWindow));
  assert.equal(storageAccesses, 0);
});

function navigationFixture(narrow) {
  const toggle = new FakeElement();
  toggle.hidden = true;
  toggle.attributes = {};
  toggle.setAttribute = (key, value) => { toggle.attributes[key] = value; };
  const panel = new FakeElement();
  panel.hidden = false;
  const brand = new FakeElement();
  const link = new FakeElement();
  panel.contains = element => element === link;
  const nav = new FakeElement();
  nav.querySelector = selector => ({
    '[data-admin-nav-toggle]': toggle,
    '[data-admin-nav-panel]': panel,
    '.brand': brand,
  })[selector];
  const documentObject = new FakeDocument();
  let toggleHidden = true;
  Object.defineProperty(toggle, 'hidden', {
    get() { return toggleHidden; },
    set(value) {
      toggleHidden = value;
      // Browsers may blur synchronously when a focused control is hidden.
      if (value && documentObject.activeElement === toggle) documentObject.activeElement = null;
    },
  });
  const originalQuery = documentObject.querySelector.bind(documentObject);
  documentObject.querySelector = selector => selector === '[data-admin-nav]' ? nav : originalQuery(selector);
  const media = { matches: narrow, addEventListener(type, listener) {
    assert.equal(type, 'change'); this.listener = listener;
  } };
  const windowObject = { matchMedia(query) {
    assert.equal(query, '(max-width: 1023px)'); return media;
  } };
  return { toggle, panel, brand, link, nav, documentObject, windowObject, media };
}

test('narrow navigation collapses, toggles once after repeated binding, and Escape restores focus', () => {
  const f = navigationFixture(true);
  adminUi.bind(f.documentObject, f.windowObject);
  adminUi.bind(f.documentObject, f.windowObject);
  assert.equal(f.toggle.hidden, false);
  assert.equal(f.panel.hidden, true);
  assert.equal(f.toggle.attributes['aria-expanded'], 'false');
  f.toggle.dispatch('click', {});
  assert.equal(f.panel.hidden, false);
  assert.equal(f.toggle.attributes['aria-expanded'], 'true');
  f.toggle.dispatch('click', {});
  assert.equal(f.panel.hidden, true);
  f.toggle.dispatch('click', {});
  let prevented = false;
  f.nav.dispatch('keydown', { key: 'Escape', preventDefault() { prevented = true; } });
  assert.equal(f.panel.hidden, true);
  assert.equal(f.toggle.focusCount, 1);
  assert.equal(prevented, true);
});

test('breakpoint transitions show desktop navigation and never hide the focused control', () => {
  const f = navigationFixture(false);
  adminUi.bind(f.documentObject, f.windowObject);
  assert.equal(f.panel.hidden, false);
  assert.equal(f.toggle.hidden, true);
  f.documentObject.activeElement = f.link;
  f.media.matches = true;
  f.media.listener();
  assert.equal(f.panel.hidden, true);
  assert.equal(f.toggle.focusCount, 1);
  f.documentObject.activeElement = f.toggle;
  f.media.matches = false;
  f.media.listener();
  assert.equal(f.panel.hidden, false);
  assert.equal(f.toggle.hidden, true);
  assert.equal(f.brand.focusCount, 1);
});
