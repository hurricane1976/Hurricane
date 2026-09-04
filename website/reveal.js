// Progressive enhancement: fade/slide cards, stat tiles, and log entries in
// as they scroll into view. With JS off (or IntersectionObserver missing,
// or the visitor asked for reduced motion) everything just stays visible --
// the .reveal class that hides content is only ever added here, never in CSS.
(function () {
  if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  // If the browser can drive this declaratively with a CSS scroll-driven
  // animation, let it -- the @supports (animation-timeline: view()) block in
  // style.css does the reveal with no script. Only fall back to the
  // IntersectionObserver path below when that isn't supported.
  if (window.CSS && CSS.supports && CSS.supports('animation-timeline: view()')) return;
  if (!('IntersectionObserver' in window)) return;

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

// Progressive enhancement: Speculation Rules. Prerender same-origin pages on
// hover intent so internal navigation (this site is very internal-link-heavy)
// feels instant. Browsers without support ignore the injected script; with JS
// off it never runs. Excludes /api/* and anything marked rel="external".
// The prerendered page still gets the cross-document View Transition.
(function () {
  if (!HTMLScriptElement.supports || !HTMLScriptElement.supports('speculationrules')) return;
  var rules = {
    prerender: [{
      where: { and: [
        { href_matches: '/*' },
        { not: { href_matches: '/api/*' } },
        { not: { selector_matches: '[rel~="external"]' } }
      ] },
      eagerness: 'moderate'
    }]
  };
  var s = document.createElement('script');
  s.type = 'speculationrules';
  s.textContent = JSON.stringify(rules);
  document.body.appendChild(s);
})();
