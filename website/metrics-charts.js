// Progressive enhancement for /metrics.html: when a chart (or KPI sparkline)
// scrolls into view, add `.chart-in` so the CSS can draw its bars/lines in.
// With JS off, no IntersectionObserver, or prefers-reduced-motion, the class
// is never added and every chart renders full and static -- the animated
// "from" state lives only in @keyframes (animation-fill-mode: backwards),
// never as a plain rule, so nothing is hidden without this script.
(function () {
  if (!('IntersectionObserver' in window)) return;
  if (window.matchMedia &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

  var els = document.querySelectorAll('.chart, .spark');
  if (!els.length) return;

  var obs = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      if (entry.isIntersecting) {
        entry.target.classList.add('chart-in');
        obs.unobserve(entry.target);
      }
    });
  }, { threshold: 0.2, rootMargin: '0px 0px -32px 0px' });

  els.forEach(function (el) { obs.observe(el); });
})();
