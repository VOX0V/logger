// Structure page of the location / aircraft databases: reorder the columns by drag and drop, add or remove entities.
(function () {
  window.initRefStructure = function (cfg) {
    const available = cfg.available.slice();
    const initialExtras = cfg.rows.filter(function (r) { return !r.core; }).map(function (r) { return r.entity; });
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
    const table = new Tabulator("#grid", {
      data: cfg.rows, index: "entity", layout: "fitDataStretch", movableRows: true, placeholder: "No columns.",
      columns: [
        {rowHandle: true, formatter: "handle", headerSort: false, width: 30, minWidth: 30, resizable: false},
        {title: "#", formatter: "rownum", headerSort: false, width: 50, hozAlign: "right"},
        {title: "entity", field: "entity", headerSort: false},
        {title: "name", field: "title", headerSort: false},
        {title: "", field: "core", headerSort: false, hozAlign: "center",
         formatter: function (cell) { return cell.getValue() ? "key column" : "<a href=\"#\">remove</a>"; },
         cellClick: function (e, cell) {
           if (cell.getValue()) return;
           e.preventDefault();
           const data = cell.getRow().getData();
           available.push({entity: data.entity, title: data.title});
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
      table.addRow({entity: item.entity, title: item.title, core: false}).then(function () { table.redraw(true); fill(); });
    });
    document.getElementById("structure-form").addEventListener("submit", function (e) {
      const order = table.getData().map(function (r) { return r.entity; });
      const removed = initialExtras.filter(function (x) { return order.indexOf(x) === -1; });
      if (removed.length && !window.confirm(removed.length + " column(s) will be removed together with their data. Continue?")) {
        e.preventDefault();
        return;
      }
      document.getElementById("order").value = JSON.stringify(order);
    });
    fill();
  };
})();
