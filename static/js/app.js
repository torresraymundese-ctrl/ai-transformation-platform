// Shared page behaviors: sticky conversion CTA, reveal animations, and counters.
(function () {
  "use strict";

  const CLICK_EVENTS = new Set([
    "service_inquiry_clicked",
    "wechat_clicked",
    "phone_clicked",
  ]);

  function sendAnalyticsEvent(fetchImpl, endpoint, csrfToken, eventName, metadata) {
    if (
      typeof fetchImpl !== "function" ||
      typeof endpoint !== "string" ||
      !endpoint ||
      typeof csrfToken !== "string" ||
      !csrfToken
    ) return Promise.resolve(false);
    try {
      return Promise.resolve(fetchImpl(endpoint, {
        method: "POST",
        credentials: "same-origin",
        keepalive: true,
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrfToken,
        },
        body: JSON.stringify({
          event_name: eventName,
          metadata: metadata || {},
        }),
      })).then(
        function (response) { return Boolean(response && response.ok); },
        function () { return false; }
      );
    } catch (_error) {
      return Promise.resolve(false);
    }
  }

  function initializeConversionAnalytics(pageDocument, fetchImpl) {
    const body = pageDocument && pageDocument.body;
    if (!body || !body.dataset) return null;
    const endpoint = body.dataset.analyticsEndpoint || "";
    const csrfToken = body.dataset.analyticsCsrfToken || "";
    const page = body.dataset.analyticsPage || "";
    const track = function (eventName, metadata) {
      return sendAnalyticsEvent(
        fetchImpl,
        endpoint,
        csrfToken,
        eventName,
        metadata
      );
    };

    if (typeof window !== "undefined") {
      window.aiConversionAnalytics = { track: track };
    }
    if (page === "home") {
      void track("home_viewed", { page: "home" });
    }
    pageDocument.addEventListener("click", function (event) {
      const marker = event.target && typeof event.target.closest === "function"
        ? event.target.closest("[data-analytics-event]")
        : null;
      if (!marker || !CLICK_EVENTS.has(marker.dataset.analyticsEvent)) return;
      const metadata = {};
      if (page) metadata.page = page;
      if (marker.dataset.analyticsSource) {
        metadata.source = marker.dataset.analyticsSource;
      }
      void track(marker.dataset.analyticsEvent, metadata);
    });
    return { track: track };
  }

  function initializeMobileNavigation(pageDocument) {
    const details = pageDocument && typeof pageDocument.querySelector === "function"
      ? pageDocument.querySelector("details[data-mobile-navigation]")
      : null;
    if (!details) return null;
    const summary = details.querySelector("summary");
    pageDocument.addEventListener("keydown", function (event) {
      if (event.key !== "Escape" || !details.open) return;
      details.open = false;
      if (summary && typeof summary.focus === "function") summary.focus();
    });
    details.addEventListener("click", function (event) {
      const link = event.target && typeof event.target.closest === "function"
        ? event.target.closest("a[href]")
        : null;
      if (link) details.open = false;
    });
    return details;
  }

  function toggleFaq(toggle) {
    const answer = toggle && toggle.nextElementSibling;
    const arrow = toggle && toggle.querySelector(".faq-arrow");
    if (!answer || !arrow) return false;
    const isOpen = answer.classList.toggle("open");
    arrow.classList.toggle("open", isOpen);
    toggle.setAttribute("aria-expanded", String(isOpen));
    return isOpen;
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = {
      initializeConversionAnalytics: initializeConversionAnalytics,
      initializeMobileNavigation: initializeMobileNavigation,
      sendAnalyticsEvent: sendAnalyticsEvent,
      toggleFaq: toggleFaq,
    };
  }

  if (typeof document === "undefined" || typeof window === "undefined") return;
  initializeConversionAnalytics(
    document,
    typeof window.fetch === "function" ? window.fetch.bind(window) : null
  );
  initializeMobileNavigation(document);

  document.addEventListener("click", function (event) {
    const toggle = event.target && typeof event.target.closest === "function"
      ? event.target.closest("[data-faq-toggle]")
      : null;
    if (!toggle) return;
    toggleFaq(toggle);
  });

  const cta = document.getElementById("stickyCta");
  let shown = false;

  function showStickyCta() {
    if (!cta || shown) return;
    cta.classList.add("show");
    document.body.classList.add("has-sticky-cta");
    shown = true;
  }

  function checkStickyCta() {
    if (window.scrollY > 600) showStickyCta();
  }

  window.addEventListener("scroll", checkStickyCta, { passive: true });
  window.setTimeout(showStickyCta, 8000);

  const revealElements = document.querySelectorAll(".reveal");
  if (revealElements.length && window.IntersectionObserver) {
    const observer = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (!entry.isIntersecting) return;
          entry.target.classList.add("visible");
          observer.unobserve(entry.target);
        });
      },
      { threshold: 0.15, rootMargin: "0px 0px -30px 0px" }
    );
    revealElements.forEach(function (element) {
      observer.observe(element);
    });
  } else {
    revealElements.forEach(function (element) {
      element.classList.add("visible");
    });
  }

  const countElements = document.querySelectorAll("[data-count]");
  if (countElements.length && window.IntersectionObserver) {
    const countObserver = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (!entry.isIntersecting || entry.target.dataset.done) return;
          entry.target.dataset.done = "1";
          const target = Number.parseInt(entry.target.dataset.count, 10);
          const suffix = entry.target.dataset.suffix || "";
          const prefix = entry.target.dataset.prefix || "";
          const duration = Number.parseInt(entry.target.dataset.duration, 10) || 1200;
          const start = performance.now();

          function tick(now) {
            const progress = Math.min((now - start) / duration, 1);
            const eased = 1 - Math.pow(1 - progress, 3);
            entry.target.textContent = prefix + Math.round(target * eased) + suffix;
            if (progress < 1) {
              window.requestAnimationFrame(tick);
            } else {
              entry.target.textContent = prefix + target + suffix;
            }
          }

          window.requestAnimationFrame(tick);
          entry.target.classList.add("done");
        });
      },
      { threshold: 0.3 }
    );
    countElements.forEach(function (element) {
      countObserver.observe(element);
    });
  }
})();
