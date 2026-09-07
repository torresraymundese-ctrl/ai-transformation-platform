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
    this.listeners.set(`${type}:${capture}`, callback);
  }

  dispatch(type, event, capture = false) {
    const callback = this.listeners.get(`${type}:${capture}`);
    if (callback) callback(event);
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
