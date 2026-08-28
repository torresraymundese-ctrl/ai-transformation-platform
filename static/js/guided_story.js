// Native-scroll chapter guidance for the public homepage.
(function () {
  "use strict";

  function getStoryParts(story) {
    if (!story || typeof story.querySelectorAll !== "function") return null;
    return {
      chapters: Array.from(story.querySelectorAll("[data-story-chapter]")),
      steps: Array.from(story.querySelectorAll("[data-story-step]")),
    };
  }

  function findStoryPair(parts, chapterId) {
    if (!parts) return null;
    const chapter = parts.chapters.find(function (candidate) {
      return candidate.id === chapterId;
    });
    const step = parts.steps.find(function (candidate) {
      return candidate.getAttribute("data-story-step") === chapterId;
    });
    return chapter && step ? { chapter: chapter, step: step } : null;
  }

  function activateStoryChapter(story, chapterId) {
    const parts = getStoryParts(story);
    const activePair = findStoryPair(parts, chapterId);
    if (!activePair) return false;

    story.dataset.activeChapter = chapterId;
    parts.chapters.forEach(function (chapter) {
      if (chapter === activePair.chapter) {
        chapter.dataset.storyActive = "true";
      } else {
        delete chapter.dataset.storyActive;
      }
    });
    parts.steps.forEach(function (step) {
      if (step === activePair.step) {
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

    const parts = getStoryParts(story);
    const configuredPair = findStoryPair(parts, story.dataset.activeChapter);
    const initialPair = configuredPair || parts.chapters.map(function (chapter) {
      return findStoryPair(parts, chapter.id);
    }).find(Boolean);
    if (!initialPair) {
      story.dataset.storyMode = "static";
      return { story: story, observer: null };
    }
    activateStoryChapter(story, initialPair.chapter.id);

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
        if (!parts.chapters.includes(entry.target)) return;
        if (!entry.isIntersecting) return;
        if (!findStoryPair(parts, entry.target.id)) return;
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
    parts.chapters.forEach(function (chapter) {
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
