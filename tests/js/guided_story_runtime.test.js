const assert = require('node:assert/strict');
const test = require('node:test');
const guided = require('../../static/js/guided_story.js');

class FakeTarget {
  constructor() {
    this.listeners = new Map();
  }

  addEventListener(type, listener) {
    const listeners = this.listeners.get(type) || [];
    listeners.push(listener);
    this.listeners.set(type, listeners);
  }
}

class FakeElement {
  constructor(id, dataAttributes) {
    this.id = id;
    this.dataset = Object.assign({}, dataAttributes);
    this.attributes = new Map();
  }

  getAttribute(name) {
    if (name === 'data-story-step') return this.dataset.storyStep || null;
    return this.attributes.has(name) ? this.attributes.get(name) : null;
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
  }

  removeAttribute(name) {
    this.attributes.delete(name);
  }
}

function guidedStoryFixture(options) {
  const settings = options || {};
  const ids = [
    'story-purpose',
    'story-assessment',
    'story-matching',
    'story-roadmap',
    'story-evidence',
  ];
  const document = new FakeTarget();
  const environment = new FakeTarget();
  const chapters = ids.map((id) => new FakeElement(id));
  const steps = ids.map((id) => new FakeElement('', { storyStep: id }));
  const story = new FakeElement('');
  let observer = null;

  story.querySelectorAll = (selector) => {
    if (selector === '[data-story-chapter]') return chapters;
    if (selector === '[data-story-step]') return steps;
    return [];
  };
  document.querySelector = (selector) => (
    selector === '[data-guided-story]' && !settings.missingStory ? story : null
  );
  environment.matchMedia = () => ({ matches: Boolean(settings.reducedMotion) });
  if (!settings.missingObserver) {
    environment.IntersectionObserver = class FakeIntersectionObserver {
      constructor(callback, observerOptions) {
        this.callback = callback;
        this.options = observerOptions;
        this.observed = [];
        observer = this;
      }

      observe(chapter) {
        this.observed.push(chapter);
      }
    };
  }

  return {
    chapters,
    document,
    environment,
    get observer() { return observer; },
    steps,
    story,
  };
}

function activeCount(items, property) {
  return items.filter((item) => item.dataset[property] === 'true').length;
}

test('the most visible chapter activates its matching progress step', () => {
  const view = guidedStoryFixture();
  guided.initializeGuidedStory(view.document, view.environment);
  view.observer.callback([
    { target: view.chapters[1], isIntersecting: true, intersectionRatio: 0.25 },
    { target: view.chapters[2], isIntersecting: true, intersectionRatio: 0.75 },
  ]);

  assert.equal(view.story.dataset.activeChapter, 'story-matching');
  assert.equal(view.steps[2].getAttribute('aria-current'), 'step');
  assert.equal(view.chapters[2].dataset.storyActive, 'true');
  assert.equal(activeCount(view.chapters, 'storyActive'), 1);
  assert.equal(view.steps.filter((step) => step.getAttribute('aria-current') === 'step').length, 1);
});

test('reduced motion keeps the complete story static and does not create an observer', () => {
  const view = guidedStoryFixture({ reducedMotion: true });
  const result = guided.initializeGuidedStory(view.document, view.environment);

  assert.equal(view.story.dataset.storyMode, 'static');
  assert.equal(view.observer, null);
  assert.equal(result.observer, null);
});

test('the guided story never registers a wheel handler', () => {
  const view = guidedStoryFixture();
  guided.initializeGuidedStory(view.document, view.environment);

  assert.equal(view.document.listeners.has('wheel'), false);
  assert.equal(view.environment.listeners.has('wheel'), false);
});

test('a missing story root returns safely', () => {
  const view = guidedStoryFixture({ missingStory: true });

  assert.equal(guided.initializeGuidedStory(view.document, view.environment), null);
});

test('a missing observer API leaves the complete story static', () => {
  const view = guidedStoryFixture({ missingObserver: true });
  const result = guided.initializeGuidedStory(view.document, view.environment);

  assert.equal(view.story.dataset.storyMode, 'static');
  assert.equal(result.observer, null);
});

test('repeated observer entries retain exactly one active chapter and step', () => {
  const view = guidedStoryFixture();
  guided.initializeGuidedStory(view.document, view.environment);
  const entry = { target: view.chapters[3], isIntersecting: true, intersectionRatio: 0.5 };

  view.observer.callback([entry, entry]);

  assert.equal(view.story.dataset.activeChapter, 'story-roadmap');
  assert.equal(activeCount(view.chapters, 'storyActive'), 1);
  assert.equal(view.steps.filter((step) => step.getAttribute('aria-current') === 'step').length, 1);
});

test('an earlier chapter becomes active again when the reader scrolls upward', () => {
  const view = guidedStoryFixture();
  guided.initializeGuidedStory(view.document, view.environment);
  view.observer.callback([
    { target: view.chapters[4], isIntersecting: true, intersectionRatio: 0.75 },
  ]);
  view.observer.callback([
    { target: view.chapters[0], isIntersecting: true, intersectionRatio: 0.5 },
  ]);

  assert.equal(view.story.dataset.activeChapter, 'story-purpose');
  assert.equal(view.chapters[0].dataset.storyActive, 'true');
  assert.equal(view.steps[0].getAttribute('aria-current'), 'step');
});
