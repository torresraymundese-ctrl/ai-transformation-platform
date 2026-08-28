// Native-scroll chapter guidance for the public homepage.
(function () {
  "use strict";

  function activateStoryChapter(story, chapterId) {
    if (!story || typeof story.querySelectorAll !== "function") return false;
    const chapters = Array.from(story.querySelectorAll("[data-story-chapter]"));
    const steps = Array.from(story.querySelectorAll("[data-story-step]"));
    const activeChapter = chapters.find(function (chapter) {
      return chapter.id === chapterId;
    });
    if (!activeChapter) return false;

    story.dataset.activeChapter = chapterId;
    chapters.forEach(function (chapter) {
      if (chapter === activeChapter) {
        chapter.dataset.storyActive = "true";
      } else {
        delete chapter.dataset.storyActive;
      }
    });
    steps.forEach(function (step) {
      if (step.getAttribute("data-story-step") === chapterId) {
        step.setAttribute("aria-current", "step");
      } else {
        step.removeAttribute("aria-current");
      }
    });
    return true;
  }

  function initializeGuidedStory(pageDocument, environment) {
    const story = pageDocument && typeof pageDocument.querySelector === "function"
      ? pageDocument.querySelector("[data-guided-story]")
      : null;
    if (!story) return null;

    const chapters = Array.from(story.querySelectorAll("[data-story-chapter]"));
    const initialChapterId = story.dataset.activeChapter || (chapters[0] && chapters[0].id);
    if (initialChapterId) activateStoryChapter(story, initialChapterId);

    const reduceMotion = environment && typeof environment.matchMedia === "function"
      && environment.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduceMotion || !environment || typeof environment.IntersectionObserver !== "function") {
      story.dataset.storyMode = "static";
      return { story: story, observer: null };
    }

    story.dataset.storyMode = "enhanced";
    const handleEntries = function (entries) {
      let candidate = null;
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        if (!candidate || entry.intersectionRatio > candidate.intersectionRatio) {
          candidate = entry;
        }
      });
      if (candidate) activateStoryChapter(story, candidate.target.id);
    };
    const observer = new environment.IntersectionObserver(handleEntries, {
      threshold: [0.25, 0.5, 0.75],
      rootMargin: "-35% 0px -35% 0px",
    });
    chapters.forEach(function (chapter) {
      observer.observe(chapter);
    });
    return { story: story, observer: observer };
  }

  const api = {
    activateStoryChapter: activateStoryChapter,
    initializeGuidedStory: initializeGuidedStory,
  };

  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (typeof window !== "undefined") window.guidedStory = api;
  if (typeof document !== "undefined" && typeof window !== "undefined") {
    initializeGuidedStory(document, window);
  }
})();
