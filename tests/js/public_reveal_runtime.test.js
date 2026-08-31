const assert = require('node:assert/strict');
const test = require('node:test');
const { initializePublicReveal } = require('../../static/js/public_reveal.js');

class FakeClassList {
  constructor() { this.values = new Set(); }
  add(value) { this.values.add(value); }
  contains(value) { return this.values.has(value); }
}

class FakeNode {
  constructor() {
    this.attributes = new Map();
    this.classList = new FakeClassList();
  }

  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  getAttribute(name) { return this.attributes.get(name) || null; }
}

function fixture({ observer, reducedMotion = false } = {}) {
  const revealNodes = [new FakeNode(), new FakeNode()];
  const listeners = [];
  const pageDocument = {
    body: new FakeNode(),
    querySelectorAll(selector) {
      return selector === '[data-public-reveal]' ? revealNodes : [];
    },
    addEventListener(type) { listeners.push(type); },
  };
  const pageWindow = {
    matchMedia() { return { matches: reducedMotion }; },
  };
  if (observer) pageWindow.IntersectionObserver = observer;
  return { pageDocument, pageWindow, revealNodes, listeners };
}

test('without IntersectionObserver content remains visible and unenhanced', () => {
  const view = fixture();
  const result = initializePublicReveal(view.pageDocument, view.pageWindow);

  assert.equal(result, null);
  assert.equal(view.pageDocument.body.classList.contains('public-reveal-enhanced'), false);
  for (const node of view.revealNodes) assert.equal(node.getAttribute('data-reveal-state'), null);
  assert.deepEqual(view.listeners, []);
});

test('observer enhancement watches reveal hooks and exposes intersecting content', () => {
  class FakeObserver {
    constructor(callback) { this.callback = callback; this.observed = []; this.unobserved = []; }
    observe(node) { this.observed.push(node); }
    unobserve(node) { this.unobserved.push(node); }
  }
  const view = fixture({ observer: FakeObserver });

  const observer = initializePublicReveal(view.pageDocument, view.pageWindow);
  observer.callback([{ isIntersecting: true, target: view.revealNodes[0] }]);

  assert.equal(view.pageDocument.body.classList.contains('public-reveal-enhanced'), true);
  assert.deepEqual(observer.observed, view.revealNodes);
  assert.equal(view.revealNodes[0].getAttribute('data-reveal-state'), 'visible');
  assert.deepEqual(observer.unobserved, [view.revealNodes[0]]);
  assert.deepEqual(view.listeners, []);
});

test('reduced motion exposes all reveal nodes without an observer or scroll interception', () => {
  const view = fixture({ reducedMotion: true });

  const result = initializePublicReveal(view.pageDocument, view.pageWindow);

  assert.equal(result, null);
  assert.equal(view.pageDocument.body.classList.contains('public-reveal-enhanced'), false);
  for (const node of view.revealNodes) assert.equal(node.getAttribute('data-reveal-state'), 'visible');
  assert.deepEqual(view.listeners, []);
});
