(function (root) {
  "use strict";

  function markVisible(nodes) {
    nodes.forEach(function (node) {
      node.setAttribute("data-reveal-state", "visible");
    });
  }

  function initializePublicReveal(pageDocument, pageWindow) {
    if (!pageDocument || typeof pageDocument.querySelectorAll !== "function") return null;
    const nodes = Array.from(pageDocument.querySelectorAll("[data-public-reveal]"));
    if (!nodes.length) return null;
    const reducedMotion = pageWindow && typeof pageWindow.matchMedia === "function"
      && pageWindow.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reducedMotion) {
      markVisible(nodes);
      return null;
    }
    if (!pageWindow || typeof pageWindow.IntersectionObserver !== "function") return null;
    const body = pageDocument.body;
    if (!body || !body.classList || typeof body.classList.add !== "function") return null;
    const observer = new pageWindow.IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        entry.target.setAttribute("data-reveal-state", "visible");
        observer.unobserve(entry.target);
      });
    }, { threshold: 0.12, rootMargin: "0px 0px -24px 0px" });
    body.classList.add("public-reveal-enhanced");
    nodes.forEach(function (node) { observer.observe(node); });
    return observer;
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = { initializePublicReveal: initializePublicReveal };
  }
  if (root) {
    root.initializePublicReveal = initializePublicReveal;
    if (root.document) initializePublicReveal(root.document, root);
  }
})(typeof window !== "undefined" ? window : null);
