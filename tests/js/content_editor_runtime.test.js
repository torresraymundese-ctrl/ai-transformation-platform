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
    this.value = '';
  }
  append(...nodes) { this.children.push(...nodes); }
  setAttribute(name, value) { this.attributes[name] = String(value); }
}

const fakeDocument = { createElement: (tagName) => new FakeElement(tagName) };

function descendants(node) {
  return node.children.flatMap((child) => [child, ...descendants(child)]);
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
