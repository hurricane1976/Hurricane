// Progressive enhancement: fade/slide cards, stat tiles, and log entries in
// as they scroll into view. With JS off (or IntersectionObserver missing,
// or the visitor asked for reduced motion) everything just stays visible --
// the .reveal class that hides content is only ever added here, never in CSS.
(function () {
  if (!('IntersectionObserver' in window)) return;
  if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

  var els = document.querySelectorAll('section.card, .stat, .log-entry');
  if (!els.length) return;

  var obs = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      if (entry.isIntersecting) {
        entry.target.classList.add('revealed');
        obs.unobserve(entry.target);
      }
    });
  }, { threshold: 0.12, rootMargin: '0px 0px -40px 0px' });

  els.forEach(function (el, i) {
    el.classList.add('reveal');
    el.style.transitionDelay = (Math.min(i, 6) * 60) + 'ms';
    obs.observe(el);
  });
})();
