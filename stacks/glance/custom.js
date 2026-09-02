// Countdown timer for the native LANmine 42 widget on the dashboard.
// Loaded via document.head (<script src="/assets/custom.js">). Runs client-side.
(function () {
  // LANmine 42 doors open — Thu 1 October 2026, 14:00 (CEST = UTC+2).
  var TARGET = new Date("2026-10-01T14:00:00+02:00").getTime();
  var pad = function (n) { return String(n).padStart(2, "0"); };
  var el = function (id) { return document.getElementById(id); };

  function tick() {
    if (!el("lm-d")) return; // countdown widget not on this page
    var diff = TARGET - Date.now();
    if (diff <= 0) {
      var timer = el("lm-timer"); if (timer) timer.style.display = "none";
      var live = el("lm-live"); if (live) live.style.display = "block";
      return;
    }
    var s = Math.floor(diff / 1000);
    el("lm-d").textContent = Math.floor(s / 86400);
    el("lm-h").textContent = pad(Math.floor((s % 86400) / 3600));
    el("lm-m").textContent = pad(Math.floor((s % 3600) / 60));
    el("lm-s").textContent = pad(s % 60);
  }

  function boot() { tick(); setInterval(tick, 1000); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
