const assert = require('node:assert/strict');
const test = require('node:test');

const editor = require('../../static/js/content_editor.js');

class FakeElement {
  constructor(tagName) {
    this.tagName = tagName;
    this.children = [];
    this.dataset = {};
    this.attributes = {};
    this.textContent = '';
    this._value = '';
    this.disabled = false;
    this.hidden = false;
    this.parentElement = null;
    this.listeners = new Map();
  }
  append(...nodes) {
    for (const node of nodes) {
      if (node.parentElement) node.remove();
      node.parentElement = this;
      this.children.push(node);
      if (this.tagName === 'select' && node.attributes.selected !== undefined) {
        this._value = node.value;
      }
    }
  }
  setAttribute(name, value) {
    this.attributes[name] = String(value);
    if (name === 'value' && this.tagName !== 'select') this._value = String(value);
  }
  get value() {
    if (this.tagName !== 'select') return this._value;
    if (this.children.some((option) => option.value === this._value)) {
      return this._value;
    }
    const selected = this.children.find(
      (option) => option.attributes.selected !== undefined && !option.disabled,
    );
    const fallback = selected || this.children.find((option) => !option.disabled);
    return fallback ? fallback.value : '';
  }
  set value(value) { this._value = String(value); }
  get options() { return this.children; }
  get previousElementSibling() {
    if (!this.parentElement) return null;
    const index = this.parentElement.children.indexOf(this);
    return index > 0 ? this.parentElement.children[index - 1] : null;
  }
  get nextElementSibling() {
    if (!this.parentElement) return null;
    const index = this.parentElement.children.indexOf(this);
    return index >= 0 && index + 1 < this.parentElement.children.length
      ? this.parentElement.children[index + 1] : null;
  }
  addEventListener(type, callback) {
    const listeners = this.listeners.get(type) || [];
    listeners.push(callback);
    this.listeners.set(type, listeners);
  }
  dispatchEvent(event) {
    const dispatched = event || {};
    if (!dispatched.type) throw new TypeError('event type required');
    if (!dispatched.target) dispatched.target = this;
    for (const callback of this.listeners.get(dispatched.type) || []) callback(dispatched);
    if (dispatched.bubbles && this.parentElement) this.parentElement.dispatchEvent(dispatched);
    return true;
  }
  click() { this.dispatchEvent({ type: 'click', target: this }); }
  matches(selector) {
    const data = selector.match(/^\[data-([a-z0-9-]+)\]$/);
    if (data) {
      const key = data[1].replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
      return Object.hasOwn(this.dataset, key);
    }
    const name = selector.match(/^\[name="([^"]+)"\]$/);
    return name ? this.attributes.name === name[1] : false;
  }
  querySelectorAll(selector) {
    return descendants(this).filter((node) => node.matches(selector));
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  closest(selector) {
    let candidate = this;
    while (candidate) {
      if (candidate.matches(selector)) return candidate;
      candidate = candidate.parentElement;
    }
    return null;
  }
  insertBefore(node, reference) {
    if (node.parentElement) node.remove();
    const index = this.children.indexOf(reference);
    if (index < 0) throw new TypeError('reference is not a child');
    node.parentElement = this;
    this.children.splice(index, 0, node);
  }
  remove() {
    if (!this.parentElement) return;
    const index = this.parentElement.children.indexOf(this);
    if (index >= 0) this.parentElement.children.splice(index, 1);
    this.parentElement = null;
  }
}

class FakeDocument {
  constructor(root = null) { this.root = root; }
  createElement(tagName) { return new FakeElement(tagName); }
  querySelector(selector) {
    if (!this.root) return null;
    return this.root.matches(selector) ? this.root : this.root.querySelector(selector);
  }
}

const fakeDocument = new FakeDocument();

function descendants(node) {
  return node.children.flatMap((child) => [child, ...descendants(child)]);
}

function option(value, label, entryType) {
  const element = new FakeElement('option');
  element.setAttribute('value', String(value));
  element.textContent = label;
  element.dataset.entryType = entryType;
  return element;
}

function boundRelationEditor(targets) {
  const root = new FakeElement('main');
  const blockContainer = new FakeElement('div');
  blockContainer.dataset.contentBlocks = '1';
  const addBlock = new FakeElement('button');
  addBlock.dataset.addBlock = '1';
  const blockType = new FakeElement('select');
  blockType.dataset.newBlockType = '1';
  blockType.value = 'heading';
  const relationContainer = new FakeElement('div');
  relationContainer.dataset.contentRelations = '1';
  const addRelation = new FakeElement('button');
  addRelation.dataset.addRelation = '1';
  const relationType = new FakeElement('select');
  relationType.dataset.newRelationType = '1';
  relationType.append(
    option('scenario_case', 'scenario_case', 'case'),
    option('scenario_resource', 'scenario_resource', 'resource'),
  );
  relationType.value = 'scenario_case';
  const relationTarget = new FakeElement('select');
  relationTarget.dataset.newRelationTarget = '1';
  relationTarget.append(...targets.map((target) => option(
    target.value, target.label, target.entryType,
  )));
  root.append(
    blockContainer, addBlock, blockType,
    relationContainer, relationType, relationTarget, addRelation,
  );
  const documentObject = new FakeDocument(root);
  editor.bind(documentObject);
  return {
    addRelation,
    relationContainer,
    relationTarget,
    relationType,
  };
}

test('choice-first editor builds safe DOM without interpreting labels as HTML', () => {
  const row = editor.createChoiceRow(fakeDocument, {
    name: 'maturity_codes',
    value: 'pilot',
    label: '<img src=x onerror=steal()>试点',
  });

  assert.equal(row.children[1].textContent, '<img src=x onerror=steal()>试点');
  assert.equal(Object.hasOwn(row.children[1], 'innerHTML'), false);
  assert.equal(row.children[0].attributes.type, 'checkbox');
  assert.equal(row.children[0].attributes.name, 'maturity_codes');
});

test('reorder is deterministic, bounded, and renumbers server field names', () => {
  const blocks = [
    { type: 'heading', title: '一' },
    { type: 'rich_text', title: '二' },
    { type: 'cta', title: '三' },
  ];
  assert.deepEqual(editor.reorder(blocks, 0, -1), blocks);
  assert.deepEqual(editor.reorder(blocks, 1, -1).map((item) => item.type), [
    'rich_text', 'heading', 'cta',
  ]);
  assert.deepEqual(editor.indexedFieldNames(2), {
    type: 'blocks-2-type',
    title: 'blocks-2-title',
    body: 'blocks-2-body',
    mediaId: 'blocks-2-media_id',
  });
});

test('runtime exposes only frozen schema choices and rejects arbitrary types', () => {
  assert.deepEqual(editor.BLOCK_TYPES, [
    'heading', 'rich_text', 'image_text', 'metric', 'steps', 'download', 'cta',
  ]);
  assert.throws(() => editor.assertBlockType('script'), /unsupported block type/);
  assert.equal(editor.assertBlockType('steps'), 'steps');
});

test('new block DOM contains the exact type-specific server controls', () => {
  const heading = editor.createBlockElement(fakeDocument, 'heading');
  const image = editor.createBlockElement(fakeDocument, 'image_text');

  assert.equal(
    descendants(heading).some((node) => node.dataset.fieldSuffix === 'heading_level'),
    true,
  );
  assert.deepEqual(
    descendants(image)
      .filter((node) => node.dataset.fieldSuffix)
      .map((node) => node.dataset.fieldSuffix)
      .filter((name) => name.startsWith('image_')),
    ['image_alignment', 'image_alt_text'],
  );
});

test('new media block uses server choices instead of a free-form media id', () => {
  const block = editor.createBlockElement(fakeDocument, 'image_text', [
    { value: 9, label: '<img onerror=steal()>受控图片' },
  ]);
  const media = descendants(block).find(
    (node) => node.dataset.fieldSuffix === 'media_id',
  );

  assert.equal(media.tagName, 'select');
  assert.equal(media.children[1].textContent, '<img onerror=steal()>受控图片');
});

test('relation DOM uses fixed choices and safe target label text', () => {
  const relation = editor.createRelationElement(fakeDocument, {
    relationType: 'scenario_case',
    targetGroupId: 17,
    targets: [
      { value: 17, label: '<svg onload=steal()>案例' },
      { value: 18, label: '第二个案例' },
    ],
  });
  const nodes = descendants(relation);

  assert.equal(nodes.some((node) => node.textContent === '<svg onload=steal()>案例'), true);
  const targetChoice = nodes.find(
    (node) => node.dataset.relationField === 'target_group_id',
  );
  assert.equal(targetChoice.children.length, 2);
  assert.deepEqual(editor.indexedRelationFieldNames(3), {
    type: 'relations-3-type',
    targetGroupId: 'relations-3-target_group_id',
  });
});

test('bound add relation uses the selected second target and freezes the row type', () => {
  const view = boundRelationEditor([
    { value: 17, label: '第一个案例', entryType: 'case' },
    { value: 18, label: '第二个案例', entryType: 'case' },
    { value: 25, label: '第一份资源', entryType: 'resource' },
  ]);
  view.relationTarget.value = '18';

  view.addRelation.click();

  assert.equal(view.relationContainer.children.length, 1);
  const row = view.relationContainer.children[0];
  const targetField = row.querySelectorAll('[data-relation-field]')[1];
  assert.equal(targetField.value, '18');
  assert.equal(
    targetField.options.find((target) => target.value === '18').attributes.selected,
    'selected',
  );
  const typeField = row.querySelector('[data-relation-field]');
  assert.equal(typeField.tagName, 'input');
  assert.equal(typeField.attributes.type, 'hidden');
  assert.equal(typeField.value, 'scenario_case');

  view.relationTarget.value = '25';
  view.addRelation.click();
  assert.equal(view.relationContainer.children.length, 1);
});

test('bound relation type changes synchronize legal targets and block empty choices', () => {
  const view = boundRelationEditor([
    { value: 17, label: '案例', entryType: 'case' },
    { value: 25, label: '资源', entryType: 'resource' },
  ]);
  const caseTarget = view.relationTarget.options[0];
  const resourceTarget = view.relationTarget.options[1];

  assert.equal(caseTarget.disabled, false);
  assert.equal(resourceTarget.disabled, true);
  assert.equal(view.relationTarget.value, '17');

  view.relationType.value = 'scenario_resource';
  view.relationType.dispatchEvent({ type: 'change', target: view.relationType });

  assert.equal(caseTarget.disabled, true);
  assert.equal(caseTarget.hidden, true);
  assert.equal(resourceTarget.disabled, false);
  assert.equal(resourceTarget.hidden, false);
  assert.equal(view.relationTarget.value, '25');
  view.addRelation.click();
  const resourceRow = view.relationContainer.children[0];
  assert.equal(resourceRow.querySelector('[data-relation-field]').value, 'scenario_resource');

  const noResource = boundRelationEditor([
    { value: 17, label: '仅有案例', entryType: 'case' },
  ]);
  noResource.relationType.value = 'scenario_resource';
  noResource.relationType.dispatchEvent({ type: 'change', target: noResource.relationType });
  assert.equal(noResource.addRelation.disabled, true);
  assert.equal(noResource.relationTarget.disabled, true);
  assert.equal(noResource.relationTarget.value, '');
  noResource.addRelation.click();
  assert.equal(noResource.relationContainer.children.length, 0);
});
