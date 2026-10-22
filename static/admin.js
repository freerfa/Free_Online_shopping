/* ==========================================================================
   Admin panel behaviour — drawer, command palette, theme, toasts.
   Depends on static/admin.css. No dependencies, no build step.
   ========================================================================== */
(function () {
  "use strict";

  var app = document.querySelector(".adm-app");
  if (!app) return;

  /* ---------------- Theme ---------------- */
  var THEME_KEY = "theme";

  function readTheme() {
    try { return localStorage.getItem(THEME_KEY); } catch (e) { return null; }
  }
  function writeTheme(t) {
    try { localStorage.setItem(THEME_KEY, t); } catch (e) {}
  }
  function applyTheme(t) {
    document.documentElement.setAttribute("data-theme", t);
    var btn = document.querySelector("[data-theme-toggle]");
    if (btn) {
      btn.classList.toggle("on", t === "dark");
      btn.setAttribute("aria-label", t === "dark" ? "Switch to light theme" : "Switch to dark theme");
      var moon = btn.querySelector("[data-icon='moon']");
      var sun = btn.querySelector("[data-icon='sun']");
      if (moon && sun) {
        moon.classList.toggle("hidden", t === "dark");
        sun.classList.toggle("hidden", t !== "dark");
      }
    }
  }

  // Apply stored theme before the panel renders.
  var stored = readTheme();
  applyTheme(stored || document.documentElement.getAttribute("data-theme") || "light");

  document.addEventListener("click", function (e) {
    var btn = e.target.closest("[data-theme-toggle]");
    if (!btn) return;
    e.preventDefault();
    var next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
    applyTheme(next);
    writeTheme(next);
  });

  /* ---------------- Command palette ---------------- */
  var palette = document.querySelector(".adm-palette");
  var paletteInput = document.querySelector(".adm-palette-input");
  var paletteList = document.querySelector(".adm-palette-list");
  var paletteOpeners = document.querySelectorAll("[data-palette-open]");

  function paletteItems() {
    if (!paletteList) return [];
    return Array.prototype.slice.call(paletteList.querySelectorAll("[data-palette-item]"));
  }

  function renderPalette(q) {
    if (!paletteList) return;
    var needle = (q || "").trim().toLowerCase();
    var visible = 0;
    paletteItems().forEach(function (item) {
      var text = (item.getAttribute("data-palette-item") || item.textContent || "").toLowerCase();
      var match = !needle || text.indexOf(needle) !== -1;
      item.hidden = !match;
      if (match) visible++;
    });
    var empty = paletteList.querySelector(".adm-palette-empty");
    if (empty) empty.hidden = visible !== 0;
  }

  function openPalette() {
    if (!palette) return;
    palette.classList.add("is-open");
    if (paletteInput) {
      paletteInput.value = "";
      renderPalette("");
      setTimeout(function () { paletteInput.focus(); }, 30);
      // Anchor keyboard navigation on the first visible item so Arrow Up/Down
      // has a visible starting point from the moment the palette opens.
      var first = paletteList.querySelector(".adm-palette-item:not([hidden]):not(.sel)");
      if (first) first.classList.add("sel");
    }
  }
  function closePalette() {
    if (!palette) return;
    palette.classList.remove("is-open");
  }

  paletteOpeners.forEach(function (el) {
    el.addEventListener("click", function (e) {
      e.preventDefault();
      openPalette();
    });
  });
  if (palette) {
    palette.addEventListener("click", function (e) {
      if (e.target === palette) closePalette();
    });
  }
  if (paletteInput) {
    paletteInput.addEventListener("input", function () { renderPalette(paletteInput.value); });
    paletteInput.addEventListener("keydown", function (e) {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        var items = paletteItems().filter(function (i) { return !i.hidden; });
        if (!items.length) return;
        var idx = items.findIndex(function (i) { return i.classList.contains("sel"); });
        items.forEach(function (i) { i.classList.remove("sel"); });
        var next = e.key === "ArrowDown"
          ? Math.min(idx + 1, items.length - 1)
          : Math.max(idx - 1, 0);
        items[idx === -1 ? 0 : next].classList.add("sel");
      } else if (e.key === "Enter") {
        var sel = paletteList.querySelector(".adm-palette-item.sel:not([hidden])")
               || paletteList.querySelector(".adm-palette-item:not([hidden])");
        if (sel) {
          e.preventDefault();
          sel.click();
        }
      }
    });
  }
  document.addEventListener("keydown", function (e) {
    var k = (e.key || "").toLowerCase();
    if ((e.metaKey || e.ctrlKey) && k === "k") {
      e.preventDefault();
      if (palette && palette.classList.contains("is-open")) closePalette();
      else openPalette();
    } else if (e.key === "Escape" && palette && palette.classList.contains("is-open")) {
      closePalette();
    }
  });

  /* ---------------- Flash messages -> toasts ---------------- */
  var toastHost = document.querySelector(".adm-toasts");

  function dismiss(toast) {
    if (!toast || toast.classList.contains("is-hiding")) return;
    toast.classList.add("is-hiding");
    setTimeout(function () {
      if (toast.parentNode) toast.parentNode.removeChild(toast);
    }, 200);
  }

  function pushToast(kind, message) {
    if (!toastHost) return null;
    var t = document.createElement("div");
    t.className = "adm-toast " + kind;
    t.setAttribute("role", "status");
    var p = document.createElement("p");
    p.textContent = message;
    t.appendChild(p);
    toastHost.appendChild(t);
    setTimeout(function () { dismiss(t); }, 5200);
    return t;
  }

  document.querySelectorAll(".adm-flash[data-kind]").forEach(function (el) {
    var toast = pushToast(el.getAttribute("data-kind"), el.getAttribute("data-message") || "");
    el.remove();
    if (toast) {
      toast.addEventListener("click", function () { dismiss(toast); });
    }
  });

  /* ---------------- Table filter (client side) ---------------- */
  document.querySelectorAll("[data-filter-target]").forEach(function (input) {
    var sel = input.getAttribute("data-filter-target");
    var rows = Array.prototype.slice.call(document.querySelectorAll(sel));
    var empty = document.querySelector(input.getAttribute("data-filter-empty") || "#none");
    input.addEventListener("input", function () {
      var needle = input.value.trim().toLowerCase();
      var shown = 0;
      rows.forEach(function (row) {
        var match = !needle || row.textContent.toLowerCase().indexOf(needle) !== -1;
        row.hidden = !match;
        if (match) shown++;
      });
      if (empty) empty.hidden = shown !== 0;
    });
  });

  /* Expose a tiny helper for pages that want to raise a toast from inline JS. */
  window.admToast = pushToast;
})();
