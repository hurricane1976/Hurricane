/* fleet-live.js — page-scoped progressive enhancement for /fleet-status.html.
 *
 * The page ships fully rendered from build_fleet_status.py; every value is
 * already correct at deploy time. This script only keeps it fresh between
 * deploys:
 *   1. re-ticks the relative "last waking" times ("1.8 h ago") from the ISO
 *      timestamps the server left in data-ts attributes, every 30 s;
 *   2. re-fetches /fleet.json every 90 s and reconciles each agent card's
 *      state dot / badge / signal / timestamp plus the "reporting healthy"
 *      stat, so a sibling that woke since the last deploy shows up live;
 *   3. shows a small "re-checked N ago" line under the stat grid.
 *
 * No dependencies, no build step. With JS off, none of this runs and the
 * static page stands on its own. Motion (the pulsing dot) is CSS-gated behind
 * prefers-reduced-motion; the data refresh itself always runs.
 */
(function () {
  'use strict';

  var JSON_URL = '/fleet.json';
  var TICK_MS = 30000;   // recompute relative times
  var POLL_MS = 90000;   // re-fetch fleet.json

  var synced = document.getElementById('fleet-synced');
  var syncedText = document.getElementById('fleet-synced-text');
  var healthyStat = document.getElementById('fleet-healthy-stat');

  var cards = {};
  var list = document.querySelectorAll('.agent-card[data-agent]');
  for (var i = 0; i < list.length; i++) {
    cards[list[i].getAttribute('data-agent')] = list[i];
  }
  if (!list.length) return;

  var lastSync = Date.now();   // page was just served; refined on first poll
  var lastOk = true;

  var STATE_LABEL = {
    ok: 'healthy', waking: 'waking now', stale: 'stale',
    error: 'check logs', unreachable: 'unreachable', unknown: 'unknown'
  };

  // Mirror build_fleet_status.py:ago() so the ticked text matches what a fresh
  // deploy would render.
  function rel(fromMs) {
    var s = (Date.now() - fromMs) / 1000;
    if (s < 90) return 'just now';
    if (s < 3600) return Math.floor(s / 60) + ' min ago';
    if (s < 36 * 3600) return (s / 3600).toFixed(1) + ' h ago';
    return Math.floor(s / 86400) + ' d ago';
  }

  function coarse(ageMs) {
    if (ageMs < 60000) return 'just now';
    if (ageMs < 3600000) return Math.floor(ageMs / 60000) + ' min ago';
    return (ageMs / 3600000).toFixed(1) + ' h ago';
  }

  function tickTimes() {
    var spans = document.querySelectorAll('.agent-ago[data-ts]');
    for (var j = 0; j < spans.length; j++) {
      var ms = Date.parse(spans[j].getAttribute('data-ts'));
      if (isNaN(ms)) continue;
      var txt = rel(ms);
      if (spans[j].textContent !== txt) spans[j].textContent = txt;
    }
    updateSynced();
  }

  function updateSynced() {
    if (!synced || !syncedText) return;
    synced.hidden = false;
    synced.classList.remove('is-stale', 'is-error');
    if (!lastOk) {
      syncedText.textContent = 'live re-check failed — showing last known state';
      synced.classList.add('is-error');
      return;
    }
    var age = Date.now() - lastSync;
    syncedText.textContent = 'live — re-checked from /fleet.json ' + coarse(age);
    if (age > POLL_MS * 3) synced.classList.add('is-stale');
  }

  function applyState(el, state) {
    if (!state || el.getAttribute('data-state') === state) return;
    el.setAttribute('data-state', state);
    var dot = el.querySelector('.agent-dot');
    var badge = el.querySelector('.agent-badge');
    if (dot) dot.setAttribute('data-state', state);
    if (badge) {
      badge.setAttribute('data-state', state);
      badge.textContent = STATE_LABEL[state] || state;
    }
  }

  function applyAgent(a) {
    if (!a || !a.name) return;
    var el = cards[a.name];
    if (!el) return;
    applyState(el, a.state);
    if (a.signal) {
      var sig = el.querySelector('.agent-signal');
      if (sig && sig.textContent !== a.signal) sig.textContent = a.signal;
    }
    if (a.last_wake) {
      var ago = el.querySelector('.agent-ago');
      if (ago && ago.getAttribute('data-ts') !== a.last_wake) {
        ago.setAttribute('data-ts', a.last_wake);
      }
    }
  }

  function poll() {
    if (document.hidden || !window.fetch) return;
    fetch(JSON_URL, { cache: 'no-store' })
      .then(function (r) {
        if (!r.ok) throw new Error('http ' + r.status);
        return r.json();
      })
      .then(function (d) {
        if (!d || !Array.isArray(d.agents)) throw new Error('shape');
        for (var k = 0; k < d.agents.length; k++) applyAgent(d.agents[k]);
        if (healthyStat && typeof d.healthy === 'number' && typeof d.total === 'number') {
          healthyStat.textContent = d.healthy + '/' + d.total;
          healthyStat.classList.toggle('good', d.healthy === d.total);
          healthyStat.classList.toggle('warn', d.healthy !== d.total);
        }
        lastSync = Date.now();
        lastOk = true;
        tickTimes();
      })
      .catch(function () {
        lastOk = false;
        updateSynced();
      });
  }

  tickTimes();
  setInterval(tickTimes, TICK_MS);
  setInterval(poll, POLL_MS);
  document.addEventListener('visibilitychange', function () {
    if (!document.hidden) poll();
  });
  setTimeout(poll, 4000);   // first live re-check shortly after load
})();
