// Comportements communs (aucun script inline : la CSP n'autorise que ce fichier et les scripts à nonce).
document.addEventListener("submit", function (e) {
  const msg = e.target.getAttribute && e.target.getAttribute("data-confirm");
  if (msg && !window.confirm(msg)) e.preventDefault();
});
document.addEventListener("click", function (e) {
  const el = e.target.closest && e.target.closest("[data-confirm]");
  if (el && el.tagName !== "FORM" && !window.confirm(el.getAttribute("data-confirm"))) e.preventDefault();
});
document.addEventListener("change", function (e) {
  const base = e.target.getAttribute && e.target.getAttribute("data-nav-select");
  if (base) window.location = base + encodeURIComponent(e.target.value);
});
