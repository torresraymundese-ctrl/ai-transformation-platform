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

  function bindNavigation(documentObject, windowObject) {
    const nav = documentObject.querySelector('[data-admin-nav]');
    if (!nav || nav.dataset.adminNavBound === 'true' || !windowObject ||
        typeof windowObject.matchMedia !== 'function') return;
    const toggle = nav.querySelector('[data-admin-nav-toggle]');
    const panel = nav.querySelector('[data-admin-nav-panel]');
    const brand = nav.querySelector('.brand');
    if (!toggle || !panel || !brand) return;
    nav.dataset.adminNavBound = 'true';
    const media = windowObject.matchMedia('(max-width: 1023px)');

    function setExpanded(expanded) {
      panel.hidden = !expanded;
      toggle.setAttribute('aria-expanded', String(expanded));
      toggle.textContent = expanded ? '收起菜单' : '展开菜单';
    }
    function syncWidth() {
      if (!media.matches && documentObject.activeElement === toggle) brand.focus();
      toggle.hidden = !media.matches;
      if (media.matches && panel.contains(documentObject.activeElement)) toggle.focus();
      setExpanded(!media.matches);
    }
    toggle.addEventListener('click', function () {
      if (media.matches) setExpanded(panel.hidden);
    });
    nav.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && media.matches && !panel.hidden) {
        event.preventDefault();
        toggle.focus();
        setExpanded(false);
      }
    });
    media.addEventListener('change', syncWidth);
    syncWidth();
  }

  function bind(documentObject, windowObject) {
    if (!documentObject) return;
    bindNavigation(documentObject, windowObject);
    focusServerSummary(documentObject);
    documentObject.querySelectorAll('form[data-admin-editor]').forEach(function (form) {
      bindEditor(form, windowObject);
    });
  }

  return Object.freeze({ bind: bind });
}));
