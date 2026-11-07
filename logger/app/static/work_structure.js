// Work db structure: reorder the columns by drag and drop, choose the type of each one, add entities, remove columns.
(function () {
  window.initWorkStructure = function (cfg) {
    const available = cfg.available.slice();
    const entityNames = {};
    cfg.available.forEach(function (a) { entityNames[a.entity] = a; });
    const initial = cfg.rows.map(function (r) { return r.column; });
    const select = document.getElementById("add-entity");
    const addButton = document.getElementById("add-btn");
    function fill() {
      select.innerHTML = "";
      available.forEach(function (a) {
        const option = document.createElement("option");
        option.value = a.entity;
        option.textContent = a.title + "  (" + a.entity + ")";
        select.appendChild(option);
      });
      addButton.disabled = !available.length;
    }
    function flag(field) {
      return {title: field, field: field, headerSort: false, hozAlign: "center", width: 90, formatter: "tickCross",
              cellClick: function (e, cell) { cell.setValue(!cell.getValue()); }};
    }
    const table = new Tabulator("#grid", {
      data: cfg.rows, index: "column", layout: "fitDataStretch", movableRows: true, placeholder: "No columns.",
      columns: [
        {rowHandle: true, formatter: "handle", headerSort: false, width: 30, minWidth: 30, resizable: false},
        {title: "#", formatter: "rownum", headerSort: false, width: 50, hozAlign: "right"},
        {title: "column", field: "column", headerSort: false},
        {title: "display name", field: "display_name", editor: "input", headerSort: false},
        {title: "type", field: "data_type", editor: "list", editorParams: {values: cfg.types}, headerSort: false, width: 120},
        flag("visible"), flag("editable"), flag("nullable"),
        {title: "", headerSort: false, hozAlign: "center", width: 90, formatter: function () { return "<a href=\"#\">remove</a>"; },
         cellClick: function (e, cell) {
           e.preventDefault();
           const data = cell.getRow().getData();
           if (entityNames[data.column]) available.push(entityNames[data.column]);
           cell.getRow().delete();
           table.redraw(true);
           fill();
         }}
      ]
    });
    table.on("rowMoved", function () { table.redraw(true); });
    addButton.addEventListener("click", function () {
      const index = available.findIndex(function (a) { return a.entity === select.value; });
      if (index < 0) return;
      const item = available.splice(index, 1)[0];
      table.addRow({column: item.entity, display_name: item.title, data_type: item.data_type, visible: true, editable: true, nullable: true})
        .then(function () { table.redraw(true); fill(); });
    });
    document.getElementById("structure-form").addEventListener("submit", function (e) {
      const rows = table.getData();
      const names = rows.map(function (r) { return r.column; });
      const removed = initial.filter(function (x) { return names.indexOf(x) === -1; });
      if (removed.length && !window.confirm(removed.length + " column(s) will be removed together with their data. Continue?")) {
        e.preventDefault();
        return;
      }
      document.getElementById("columns").value = JSON.stringify(rows);
    });
    fill();
  };
})();
