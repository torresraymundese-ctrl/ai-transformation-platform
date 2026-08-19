// Shared page behaviors: sticky conversion CTA, reveal animations, and counters.
(function () {
  "use strict";

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
