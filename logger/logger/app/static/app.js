// Shared behaviors (no inline script: the CSP only allows this file and nonce scripts).
document.addEventListener("submit", function (e) {
  const msg = e.target.getAttribute && e.target.getAttribute("data-confirm");
  if (msg && !window.confirm(msg)) e.preventDefault();
  // Destructive forms: the word CLEAR must be typed (the server checks it again).
  const typed = e.target.getAttribute && e.target.getAttribute("data-type-clear");
  if (typed !== null && typed !== undefined) {
    const answer = window.prompt(typed + "\n\nType CLEAR to confirm.");
    if (answer === null || answer.trim() !== "CLEAR") { e.preventDefault(); return; }
    const field = e.target.querySelector("input[name=confirm]");
    if (field) field.value = "CLEAR";
  }
});
document.addEventListener("click", function (e) {
  const toggle = e.target.closest && e.target.closest("[data-toggle]");
  if (toggle) { const panel = document.getElementById(toggle.getAttribute("data-toggle")); if (panel) panel.hidden = !panel.hidden; }
  const el = e.target.closest && e.target.closest("[data-confirm]");
  if (el && el.tagName !== "FORM" && !window.confirm(el.getAttribute("data-confirm"))) e.preventDefault();
});
document.addEventListener("change", function (e) {
  const base = e.target.getAttribute && e.target.getAttribute("data-nav-select");
  if (base) window.location = base + encodeURIComponent(e.target.value);
});

// Import panel: the profile is suggested from the column headers as soon as a file is chosen (and can still be changed).
document.addEventListener("change", function (e) {
  const input = e.target;
  const selectId = input.getAttribute && input.getAttribute("data-detect-profile");
  if (!selectId || !input.files || !input.files.length) return;
  const select = document.getElementById(selectId);
  const note = document.getElementById(selectId + "-note");
  const meta = document.querySelector("meta[name=csrf-token]");
  const body = new FormData();
  body.append("file", input.files[0]);
  if (note) note.textContent = "Detecting the profile…";
  fetch(input.getAttribute("data-detect-url"), {method: "POST", headers: {"X-CSRFToken": meta ? meta.content : ""}, body: body})
    .then(function (r) { return r.json(); })
    .then(function (data) {
      if (data.profile) { select.value = data.profile; if (note) note.textContent = "Profile detected: " + data.name + ". You can change it."; }
      else { select.value = ""; if (note) note.textContent = "Profile not recognized."; }
    })
    .catch(function () { select.value = ""; if (note) note.textContent = "Profile not recognized."; });
});
