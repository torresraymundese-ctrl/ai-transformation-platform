(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.ContentEditor = api;
  }
})(typeof globalThis === 'object' ? globalThis : this, function () {
  'use strict';

  const BLOCK_TYPES = Object.freeze([
    'heading', 'rich_text', 'image_text', 'metric', 'steps', 'download', 'cta',
  ]);
  const BLOCK_LABELS = Object.freeze({
    heading: '标题',
    rich_text: '富文本',
    image_text: '图文',
    metric: '指标',
    steps: '步骤',
    download: '下载',
    cta: '行动按钮',
  });

  function assertBlockType(value) {
    if (!BLOCK_TYPES.includes(value)) {
      throw new TypeError('unsupported block type');
    }
    return value;
  }

  function reorder(items, index, delta) {
    if (!Array.isArray(items) || !Number.isInteger(index) || !Number.isInteger(delta)) {
      throw new TypeError('invalid reorder request');
    }
    const destination = index + delta;
    if (index < 0 || index >= items.length || destination < 0 || destination >= items.length) {
      return items.slice();
    }
    const reordered = items.slice();
    const moved = reordered.splice(index, 1)[0];
    reordered.splice(destination, 0, moved);
    return reordered;
  }

  function indexedFieldNames(index) {
    if (!Number.isInteger(index) || index < 0) {
      throw new TypeError('invalid block index');
    }
    return Object.freeze({
      type: `blocks-${index}-type`,
      title: `blocks-${index}-title`,
      body: `blocks-${index}-body`,
      mediaId: `blocks-${index}-media_id`,
    });
  }

  function createChoiceRow(documentObject, choice) {
    const row = documentObject.createElement('label');
    const input = documentObject.createElement('input');
    input.setAttribute('type', 'checkbox');
    input.setAttribute('name', String(choice.name));
    input.setAttribute('value', String(choice.value));
    const label = documentObject.createElement('span');
    label.textContent = String(choice.label);
    row.append(input, label);
    return row;
  }

  function field(documentObject, tagName, suffix, labelText) {
    const wrapper = documentObject.createElement('label');
    const label = documentObject.createElement('span');
    label.textContent = labelText;
    const control = documentObject.createElement(tagName);
    control.dataset.fieldSuffix = suffix;
    wrapper.append(label, control);
    return wrapper;
  }

  function choiceField(documentObject, suffix, labelText, choices) {
    const wrapper = field(documentObject, 'select', suffix, labelText);
    const select = wrapper.children[1];
    for (const choice of choices) {
      const option = documentObject.createElement('option');
      option.setAttribute('value', choice);
      option.textContent = choice;
      select.append(option);
    }
    return wrapper;
  }

  function serverChoiceField(documentObject, suffix, labelText, choices, includeEmpty) {
    const wrapper = field(documentObject, 'select', suffix, labelText);
    const select = wrapper.children[1];
    if (includeEmpty) {
      const empty = documentObject.createElement('option');
      empty.setAttribute('value', '');
      empty.textContent = '不使用';
      select.append(empty);
    }
    for (const choice of choices) {
      const option = documentObject.createElement('option');
      option.setAttribute('value', String(choice.value));
      option.textContent = String(choice.label);
      select.append(option);
    }
    return wrapper;
  }

  function createBlockElement(documentObject, blockType, mediaChoices) {
    const type = assertBlockType(blockType);
    const safeMediaChoices = Array.isArray(mediaChoices) ? mediaChoices : [];
    const block = documentObject.createElement('fieldset');
    block.dataset.contentBlock = '1';
    const legend = documentObject.createElement('legend');
    legend.textContent = BLOCK_LABELS[type];
    const hiddenType = documentObject.createElement('input');
    hiddenType.setAttribute('type', 'hidden');
    hiddenType.setAttribute('value', type);
    hiddenType.dataset.fieldSuffix = 'type';
    block.append(
      legend,
      hiddenType,
      field(documentObject, 'input', 'title', '区块标题'),
      field(documentObject, 'textarea', 'body', '正文'),
      serverChoiceField(
        documentObject, 'media_id', '媒体', safeMediaChoices, true,
      ),
    );
    if (type === 'heading') {
      block.append(choiceField(documentObject, 'heading_level', '标题级别', ['2', '3', '4']));
    }
    if (type === 'image_text') {
      block.append(
        choiceField(documentObject, 'image_alignment', '图片位置', ['left', 'right']),
        field(documentObject, 'input', 'image_alt_text', '替代文字'),
      );
    }
    if (type === 'metric') {
      block.append(
        field(documentObject, 'input', 'metric_value', '数值'),
        field(documentObject, 'input', 'metric_unit', '单位'),
      );
    }
    if (type === 'steps') {
      block.append(field(documentObject, 'textarea', 'steps_items', '步骤（每行一项）'));
    }
    if (type === 'download') {
      block.append(field(documentObject, 'input', 'download_label', '下载标签'));
    }
    if (type === 'cta') {
      block.append(
        field(documentObject, 'input', 'cta_label', '按钮标签'),
        field(documentObject, 'input', 'cta_url', '按钮地址'),
        choiceField(documentObject, 'cta_style', '按钮样式', ['primary', 'secondary', 'text']),
      );
    }
    const controls = documentObject.createElement('div');
    for (const action of ['up', 'down', 'remove']) {
      const button = documentObject.createElement('button');
      button.setAttribute('type', 'button');
      button.dataset.blockAction = action;
      button.textContent = { up: '上移', down: '下移', remove: '移除' }[action];
      controls.append(button);
    }
    block.append(controls);
    return block;
  }

  function indexedRelationFieldNames(index) {
    if (!Number.isInteger(index) || index < 0) {
      throw new TypeError('invalid relation index');
    }
    return Object.freeze({
      type: `relations-${index}-type`,
      targetGroupId: `relations-${index}-target_group_id`,
    });
  }

  function createRelationElement(documentObject, relation) {
    if (!/^(industry|scenario|service)_(case|resource)$/.test(relation.relationType)) {
      throw new TypeError('unsupported relation type');
    }
    if (
      !Number.isInteger(relation.targetGroupId)
      || relation.targetGroupId < 1
      || !Array.isArray(relation.targets)
      || !relation.targets.some((target) => target.value === relation.targetGroupId)
    ) {
      throw new TypeError('invalid relation target');
    }
    const row = documentObject.createElement('div');
    row.dataset.contentRelation = '1';
    const typeChoice = documentObject.createElement('select');
    typeChoice.dataset.relationField = 'type';
    const owner = relation.relationType.split('_')[0];
    for (const suffix of ['case', 'resource']) {
      const value = `${owner}_${suffix}`;
      const option = documentObject.createElement('option');
      option.setAttribute('value', value);
      option.textContent = value;
      if (value === relation.relationType) option.setAttribute('selected', 'selected');
      typeChoice.append(option);
    }
    const targetChoice = documentObject.createElement('select');
    targetChoice.dataset.relationField = 'target_group_id';
    for (const target of relation.targets) {
      if (!Number.isInteger(target.value) || target.value < 1) {
        throw new TypeError('invalid relation target');
      }
      const option = documentObject.createElement('option');
      option.setAttribute('value', String(target.value));
      option.textContent = String(target.label);
      if (target.value === relation.targetGroupId) option.setAttribute('selected', 'selected');
      targetChoice.append(option);
    }
    row.append(typeChoice, targetChoice);
    for (const action of ['up', 'down', 'remove']) {
      const button = documentObject.createElement('button');
      button.setAttribute('type', 'button');
      button.dataset.relationAction = action;
      button.textContent = { up: '上移', down: '下移', remove: '移除' }[action];
      row.append(button);
    }
    return row;
  }

  function renumberBlocks(container) {
    const blocks = Array.from(container.querySelectorAll('[data-content-block]'));
    blocks.forEach(function (block, index) {
      block.dataset.blockIndex = String(index);
      for (const control of block.querySelectorAll('[data-field-suffix]')) {
        control.setAttribute('name', `blocks-${index}-${control.dataset.fieldSuffix}`);
      }
    });
    return blocks.length;
  }

  function renumberRelations(container) {
    const relations = Array.from(container.querySelectorAll('[data-content-relation]'));
    relations.forEach(function (relation, index) {
      relation.dataset.relationIndex = String(index);
      for (const control of relation.querySelectorAll('[data-relation-field]')) {
        const suffix = control.dataset.relationField;
        control.setAttribute('name', `relations-${index}-${suffix}`);
      }
    });
    return relations.length;
  }

  function bind(documentObject) {
    if (!documentObject || typeof documentObject.querySelector !== 'function') {
      return;
    }
    const container = documentObject.querySelector('[data-content-blocks]');
    const addButton = documentObject.querySelector('[data-add-block]');
    const typeChoice = documentObject.querySelector('[data-new-block-type]');
    if (!container || !addButton || !typeChoice) {
      return;
    }
    const mediaSource = documentObject.querySelector('[name="share_image_media_id"]');
    const mediaChoices = mediaSource
      ? Array.from(mediaSource.options)
        .filter((option) => option.value)
        .map((option) => ({ value: Number(option.value), label: option.textContent }))
      : [];
    addButton.addEventListener('click', function () {
      if (container.querySelectorAll('[data-content-block]').length >= 40) return;
      container.append(createBlockElement(documentObject, typeChoice.value, mediaChoices));
      renumberBlocks(container);
    });
    container.addEventListener('click', function (event) {
      const button = event.target.closest('[data-block-action]');
      if (!button) return;
      const block = button.closest('[data-content-block]');
      if (!block) return;
      const action = button.dataset.blockAction;
      if (action === 'remove') block.remove();
      if (action === 'up' && block.previousElementSibling) {
        container.insertBefore(block, block.previousElementSibling);
      }
      if (action === 'down' && block.nextElementSibling) {
        container.insertBefore(block.nextElementSibling, block);
      }
      renumberBlocks(container);
    });
    renumberBlocks(container);

    const relationContainer = documentObject.querySelector('[data-content-relations]');
    const addRelation = documentObject.querySelector('[data-add-relation]');
    const relationType = documentObject.querySelector('[data-new-relation-type]');
    const relationTarget = documentObject.querySelector('[data-new-relation-target]');
    if (relationContainer && addRelation && relationType && relationTarget) {
      addRelation.addEventListener('click', function () {
        if (relationContainer.querySelectorAll('[data-content-relation]').length >= 50) return;
        const suffix = relationType.value.endsWith('_case') ? 'case' : 'resource';
        const targets = Array.from(relationTarget.options).filter(function (candidate) {
          return candidate.dataset.entryType === suffix;
        }).map(function (candidate) {
          return { value: Number(candidate.value), label: candidate.textContent };
        });
        if (!targets.length) return;
        relationContainer.append(createRelationElement(documentObject, {
          relationType: relationType.value,
          targetGroupId: targets[0].value,
          targets,
        }));
        renumberRelations(relationContainer);
      });
      relationContainer.addEventListener('click', function (event) {
        const button = event.target.closest('[data-relation-action]');
        if (!button) return;
        const relation = button.closest('[data-content-relation]');
        if (!relation) return;
        const action = button.dataset.relationAction;
        if (action === 'remove') relation.remove();
        if (action === 'up' && relation.previousElementSibling) {
          relationContainer.insertBefore(relation, relation.previousElementSibling);
        }
        if (action === 'down' && relation.nextElementSibling) {
          relationContainer.insertBefore(relation.nextElementSibling, relation);
        }
        renumberRelations(relationContainer);
      });
      renumberRelations(relationContainer);
    }
  }

  if (typeof document === 'object' && document.addEventListener) {
    document.addEventListener('DOMContentLoaded', function () { bind(document); });
  }

  return Object.freeze({
    BLOCK_TYPES,
    assertBlockType,
    bind,
    createBlockElement,
    createChoiceRow,
    createRelationElement,
    indexedFieldNames,
    indexedRelationFieldNames,
    renumberBlocks,
    renumberRelations,
    reorder,
  });
});
