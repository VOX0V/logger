// Raw / work db structure page: filter, "all" toggles and a confirmation before columns are removed.
(function () {
  const form = document.getElementById("structure-form");
  if (!form) return;
  const rows = Array.prototype.slice.call(form.querySelectorAll("tbody tr"));
  const filter = document.getElementById("s-filter");
  if (filter) filter.addEventListener("input", function () {
    const q = filter.value.trim().toLowerCase();
    rows.forEach(function (tr) { tr.hidden = q !== "" && tr.textContent.toLowerCase().indexOf(q) === -1; });
  });
  form.querySelectorAll("input[data-all]").forEach(function (box) {
    box.addEventListener("change", function () {
      rows.forEach(function (tr) {
        if (tr.hidden) return;
        const c = tr.querySelector('input[name="' + box.dataset.all + '"]');
        if (c) c.checked = box.checked;
      });
    });
  });
  form.addEventListener("submit", function (e) {
    let n = 0;
    rows.forEach(function (tr) {
      const c = tr.querySelector('input[name="present"]');
      if (tr.dataset.was === "1" && c && !c.checked) n++;
    });
    if (n && !window.confirm(n + " column(s) will be removed from the database together with their data. Continue?")) e.preventDefault();
  });
})();
