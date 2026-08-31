const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
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
  const documentListeners = [];
  const windowListeners = [];
  const pageDocument = {
    body: new FakeNode(),
    querySelectorAll(selector) {
      return selector === '[data-public-reveal]' ? revealNodes : [];
    },
    addEventListener(type, listener) { documentListeners.push({ type, listener }); },
  };
  const pageWindow = {
    matchMedia() { return { matches: reducedMotion }; },
    addEventListener(type, listener) { windowListeners.push({ type, listener }); },
  };
  if (observer) pageWindow.IntersectionObserver = observer;
  return { pageDocument, pageWindow, revealNodes, documentListeners, windowListeners };
}

function assertNoScrollInterception(view) {
  const listeners = [...view.documentListeners, ...view.windowListeners];
  assert.equal(listeners.some(({ type }) => ['wheel', 'touchmove', 'scroll'].includes(type)), false);
  for (const { listener } of listeners) {
    let preventDefaultCalls = 0;
    listener({
      type: 'wheel',
      preventDefault() { preventDefaultCalls += 1; },
    });
    assert.equal(preventDefaultCalls, 0);
  }
}

test('without IntersectionObserver content remains visible and unenhanced', () => {
  const view = fixture();
  const result = initializePublicReveal(view.pageDocument, view.pageWindow);

  assert.equal(result, null);
  assert.equal(view.pageDocument.body.classList.contains('public-reveal-enhanced'), false);
  for (const node of view.revealNodes) assert.equal(node.getAttribute('data-reveal-state'), null);
  assertNoScrollInterception(view);
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
  assertNoScrollInterception(view);
});

test('reduced motion exposes all reveal nodes without an observer or scroll interception', () => {
  const view = fixture({ reducedMotion: true });

  const result = initializePublicReveal(view.pageDocument, view.pageWindow);

  assert.equal(result, null);
  assert.equal(view.pageDocument.body.classList.contains('public-reveal-enhanced'), false);
  for (const node of view.revealNodes) assert.equal(node.getAttribute('data-reveal-state'), 'visible');
  assertNoScrollInterception(view);
});

test('browser branch exposes a callable initializer on window', () => {
  const view = fixture();
  view.pageWindow.document = view.pageDocument;
  const source = fs.readFileSync(
    path.join(__dirname, '../../static/js/public_reveal.js'),
    'utf8'
  );

  vm.runInNewContext(source, { window: view.pageWindow });

  assert.equal(typeof view.pageWindow.initializePublicReveal, 'function');
  assert.equal(view.pageWindow.initializePublicReveal(view.pageDocument, view.pageWindow), null);
  assertNoScrollInterception(view);
});

test('mobile menu summary source keeps a 44 by 44 pixel aligned target', () => {
  const css = fs.readFileSync(
    path.join(__dirname, '../../static/css/silver-evidence-public.css'),
    'utf8'
  );
  const rule = css.match(/\.public-shell \.mobile-navigation summary\s*\{([^}]*)\}/);

  assert.ok(rule);
  assert.match(rule[1], /min-height:\s*2\.75rem;/);
  assert.match(rule[1], /min-inline-size:\s*2\.75rem;/);
  assert.match(rule[1], /display:\s*inline-flex;/);
  assert.match(rule[1], /align-items:\s*center;/);
});
