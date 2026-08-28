const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');
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
  const ids = settings.chapterIds || [
    'story-purpose',
    'story-assessment',
    'story-matching',
    'story-roadmap',
    'story-evidence',
  ];
  const document = new FakeTarget();
  const environment = new FakeTarget();
  const chapters = ids.map((id) => new FakeElement(id));
  const stepIds = settings.stepIds === undefined ? ids : settings.stepIds;
  const steps = stepIds.map((id) => new FakeElement('', { storyStep: id }));
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
  const result = guided.initializeGuidedStory(view.document, view.environment);
  view.observer.callback([
    { target: view.chapters[1], isIntersecting: true, intersectionRatio: 0.25 },
    { target: view.chapters[2], isIntersecting: true, intersectionRatio: 0.75 },
  ]);

  assert.equal(view.story.dataset.activeChapter, 'story-matching');
  assert.equal(view.steps[2].getAttribute('aria-current'), 'step');
  assert.equal(view.chapters[2].dataset.storyActive, 'true');
  assert.equal(activeCount(view.chapters, 'storyActive'), 1);
  assert.equal(view.steps.filter((step) => step.getAttribute('aria-current') === 'step').length, 1);
  assert.deepEqual(view.observer.options.threshold, [0.25, 0.5, 0.75]);
  assert.equal(view.observer.options.rootMargin, '-35% 0px -35% 0px');
  assert.deepEqual(view.observer.observed, view.chapters);
  assert.equal(result.observer, view.observer);
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

test('a missing environment leaves the complete story static', () => {
  const view = guidedStoryFixture();
  const result = guided.initializeGuidedStory(view.document);

  assert.equal(view.story.dataset.storyMode, 'static');
  assert.equal(result.observer, null);
});

test('entries outside this story cannot override a valid visible chapter', () => {
  const view = guidedStoryFixture();
  const outsideChapter = new FakeElement('story-matching');
  guided.initializeGuidedStory(view.document, view.environment);

  view.observer.callback([
    { target: outsideChapter, isIntersecting: true, intersectionRatio: 0.95 },
    { target: view.chapters[1], isIntersecting: true, intersectionRatio: 0.75 },
  ]);

  assert.equal(view.story.dataset.activeChapter, 'story-assessment');
  assert.equal(activeCount(view.chapters, 'storyActive'), 1);
});

test('repeated observer targets use the highest ratio across a real entry batch', () => {
  const view = guidedStoryFixture();
  guided.initializeGuidedStory(view.document, view.environment);

  view.observer.callback([
    { target: view.chapters[3], isIntersecting: true, intersectionRatio: 0.25 },
    { target: view.chapters[2], isIntersecting: true, intersectionRatio: 0.5 },
    { target: view.chapters[3], isIntersecting: true, intersectionRatio: 0.65 },
  ]);

  assert.equal(view.story.dataset.activeChapter, 'story-roadmap');
  assert.equal(activeCount(view.chapters, 'storyActive'), 1);
  assert.equal(view.steps.filter((step) => step.getAttribute('aria-current') === 'step').length, 1);
});

test('duplicate progress links still leave only the first matching step current', () => {
  const view = guidedStoryFixture({
    stepIds: [
      'story-purpose',
      'story-assessment',
      'story-assessment',
      'story-roadmap',
      'story-evidence',
    ],
  });

  assert.equal(guided.activateStoryChapter(view.story, 'story-assessment'), true);
  assert.equal(view.steps[1].getAttribute('aria-current'), 'step');
  assert.equal(view.steps[2].getAttribute('aria-current'), null);
  assert.equal(view.steps.filter((step) => step.getAttribute('aria-current') === 'step').length, 1);
});

test('an unknown chapter or missing step mapping leaves prior state intact', () => {
  const view = guidedStoryFixture({
    stepIds: ['story-purpose', 'story-matching', 'story-roadmap', 'story-evidence'],
  });
  guided.activateStoryChapter(view.story, 'story-purpose');
  const activeChapter = view.story.dataset.activeChapter;
  const activeSteps = view.steps.map((step) => step.getAttribute('aria-current'));

  assert.equal(guided.activateStoryChapter(view.story, 'story-assessment'), false);
  assert.equal(guided.activateStoryChapter(view.story, 'story-unknown'), false);
  assert.equal(view.story.dataset.activeChapter, activeChapter);
  assert.deepEqual(view.steps.map((step) => step.getAttribute('aria-current')), activeSteps);
  assert.equal(view.chapters[0].dataset.storyActive, 'true');
});

test('an unknown initial chapter falls back to the first chapter with a legal step', () => {
  const view = guidedStoryFixture({
    stepIds: ['story-matching', 'story-roadmap', 'story-evidence'],
  });
  view.story.dataset.activeChapter = 'story-unknown';
  const result = guided.initializeGuidedStory(view.document, view.environment);

  assert.equal(view.story.dataset.activeChapter, 'story-matching');
  assert.equal(view.chapters[2].dataset.storyActive, 'true');
  assert.equal(result.observer, view.observer);
});

test('an empty or unmapped story stays static without an observer', () => {
  const empty = guidedStoryFixture({ chapterIds: [], stepIds: [] });
  const unmapped = guidedStoryFixture({ stepIds: [] });

  assert.equal(guided.initializeGuidedStory(empty.document, empty.environment).observer, null);
  assert.equal(empty.story.dataset.storyMode, 'static');
  assert.equal(guided.initializeGuidedStory(unmapped.document, unmapped.environment).observer, null);
  assert.equal(unmapped.story.dataset.storyMode, 'static');
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

test('the browser branch exports and bootstraps without CommonJS', () => {
  const view = guidedStoryFixture();
  const source = fs.readFileSync(require.resolve('../../static/js/guided_story.js'), 'utf8');

  vm.runInNewContext(source, { document: view.document, window: view.environment });

  assert.equal(typeof view.environment.guidedStory.activateStoryChapter, 'function');
  assert.equal(typeof view.environment.guidedStory.initializeGuidedStory, 'function');
  assert.equal(view.story.dataset.storyMode, 'enhanced');
  assert.equal(view.observer.observed.length, view.chapters.length);
});
