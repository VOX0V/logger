// Raw DB settings: same grid as the Work DB settings page (tick / cross cells, filter, confirmation before columns are removed).
(function () {
  window.initRawStructure = function (cfg) {
    const form = document.getElementById("structure-form");
    const filter = document.getElementById("s-filter");
    const was = {};
    cfg.rows.forEach(function (r) { was[r.column] = r.present; });
    function flag(field) {
      return {title: field, field: field, headerSort: false, hozAlign: "center", width: 90, formatter: "tickCross",
              headerClick: function () {
                const rows = table.getRows("active");
                const on = !rows.every(function (r) { return r.getData()[field]; });
                rows.forEach(function (r) { const change = {}; change[field] = on; r.update(change); });
              },
              cellClick: function (e, cell) { cell.setValue(!cell.getValue()); }};
    }
    const table = new Tabulator("#grid", {
      data: cfg.rows, index: "column", layout: "fitDataStretch", height: "70vh", placeholder: "No columns.",
      columns: [
        {title: "#", formatter: "rownum", headerSort: false, width: 50, hozAlign: "right"},
        flag("present"),
        {title: "group", field: "group", headerSort: false},
        {title: "entity", field: "column", headerSort: false},
        {title: "display name", field: "display_name", headerSort: false},
        flag("visible"), flag("editable"), flag("nullable")
      ]
    });
    if (filter) filter.addEventListener("input", function () {
      const q = filter.value.trim().toLowerCase();
      table.setFilter(function (d) { return q === "" || (d.group + " " + d.column + " " + d.display_name).toLowerCase().indexOf(q) !== -1; });
    });
    form.addEventListener("submit", function (e) {
      const rows = table.getData();
      const removed = rows.filter(function (r) { return was[r.column] && !r.present; }).length;
      if (removed && !window.confirm(removed + " column(s) will be removed from the database together with their data. Continue?")) {
        e.preventDefault();
        return;
      }
      form.querySelectorAll("input[data-generated]").forEach(function (n) { n.remove(); });
      rows.forEach(function (r) {
        ["present", "visible", "editable", "nullable"].forEach(function (field) {
          if (!r[field]) return;
          const input = document.createElement("input");
          input.type = "hidden"; input.name = field; input.value = r.column; input.setAttribute("data-generated", "1");
          form.appendChild(input);
        });
      });
    });
  };
})();
