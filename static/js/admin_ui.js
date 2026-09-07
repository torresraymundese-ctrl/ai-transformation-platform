(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root && root.document) api.bind(root.document, root);
}(typeof window === 'undefined' ? null : window, function () {
  'use strict';

  function scrollBehavior(windowObject) {
    if (!windowObject || typeof windowObject.matchMedia !== 'function') return 'auto';
    return windowObject.matchMedia('(prefers-reduced-motion: reduce)').matches
      ? 'auto'
      : 'smooth';
  }

  function focusServerSummary(documentObject) {
    const summary = documentObject.querySelector('[data-admin-error-summary]');
    if (!summary || summary.dataset.adminUiFocused === 'true') return;
    summary.dataset.adminUiFocused = 'true';
    summary.focus();
  }

  function bindEditor(form, windowObject) {
    if (form.dataset.adminUiBound === 'true') return;
    form.dataset.adminUiBound = 'true';
    form.addEventListener('invalid', function (event) {
      const field = event.target;
      if (!field || typeof field.closest !== 'function') return;
      const section = field.closest('.admin-editor-section');
      if (section && typeof section.scrollIntoView === 'function') {
        section.scrollIntoView({
          behavior: scrollBehavior(windowObject),
          block: 'start',
        });
      }
      if (typeof field.focus === 'function') field.focus();
    }, true);
  }

  function bind(documentObject, windowObject) {
    if (!documentObject) return;
    focusServerSummary(documentObject);
    documentObject.querySelectorAll('form[data-admin-editor]').forEach(function (form) {
      bindEditor(form, windowObject);
    });
  }

  return Object.freeze({ bind: bind });
}));
