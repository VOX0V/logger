// Review pages (import / conversion): "select all" buttons for the per-line choices.
document.addEventListener("click", function (e) {
  const button = e.target.closest && e.target.closest("[data-review-all]");
  if (!button) return;
  const form = button.closest("form");
  if (!form) return;
  const value = button.getAttribute("data-review-all");
  const group = button.getAttribute("data-review-group");
  form.querySelectorAll('input[type=radio][data-review-group="' + group + '"][value="' + value + '"]').forEach(function (radio) { radio.checked = true; });
});
