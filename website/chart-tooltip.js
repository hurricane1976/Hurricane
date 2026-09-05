// Progressive enhancement for /metrics.html charts: an instant, styled
// hover + focus tooltip. Without this script every bar or point still carries
// a native SVG <title> (the no-JS path -- correct, but with the browser's ~1s
// delay and no styling). When JS runs we strip those <title>s to avoid a
// double tooltip and show one shared element that tracks the pointer, reading
// each element's pre-formatted `data-tip` string (bar <rect>s or, on the
// fleet overview area chart, per-day <circle> points). Keyboard/AT users are
// already served by the full <details> data table under every chart (the
// area chart's own table is the union of the per-agent bar charts below it),
// so points are not added to the tab order. Nothing here is motion; it is
// not gated on prefers-reduced-motion.
(function () {
  var charts = document.querySelectorAll("svg.chart");
  if (!charts.length || !("closest" in Element.prototype)) return;

  var tip = document.createElement("div");
  tip.className = "chart-tip";
  tip.setAttribute("role", "status");
  tip.hidden = true;
  document.body.appendChild(tip);

  function place(clientX, clientY) {
    tip.hidden = false;
    var pad = 14;
    var r = tip.getBoundingClientRect();
    var x = clientX + pad;
    var y = clientY + pad;
    if (x + r.width > window.innerWidth - 6) x = clientX - r.width - pad;
    if (y + r.height > window.innerHeight - 6) y = clientY - r.height - pad;
    tip.style.left = Math.max(4, x + window.scrollX) + "px";
    tip.style.top = Math.max(4, y + window.scrollY) + "px";
  }

  function showFor(bar, clientX, clientY) {
    var txt = bar.getAttribute("data-tip");
    if (!txt) return;
    if (tip.textContent !== txt) tip.textContent = txt;
    place(clientX, clientY);
  }

  function hide() {
    tip.hidden = true;
  }

  charts.forEach(function (svg) {
    svg.querySelectorAll("rect > title, circle > title").forEach(function (t) {
      t.parentNode.removeChild(t);
    });

    svg.addEventListener("pointermove", function (e) {
      var bar = e.target.closest("rect[data-tip], circle[data-tip]");
      if (bar) showFor(bar, e.clientX, e.clientY);
      else hide();
    });
    svg.addEventListener("pointerleave", hide);
    svg.addEventListener("pointercancel", hide);
  });

  window.addEventListener(
    "scroll",
    function () {
      if (!tip.hidden) hide();
    },
    { passive: true }
  );
})();
