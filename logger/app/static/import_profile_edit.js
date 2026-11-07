// Import profile editor: one row per header of the file, with the entity it goes to.
(function () {
  window.initImportProfile = function (cfg) {
    const table = new Tabulator("#grid", {
      data: cfg.rows, layout: "fitDataStretch", height: "60vh", placeholder: "No header yet: add a row.",
      columns: [
        {formatter: "rowSelection", titleFormatter: "rowSelection", hozAlign: "center", headerSort: false, width: 40, resizable: false,
         cellClick: function (e, cell) { cell.getRow().toggleSelect(); }},
        {title: "header of the file", field: "header", editor: "input", headerSort: false, widthGrow: 2},
        {title: "entity", field: "entity", editor: "list", headerSort: false, widthGrow: 3,
         editorParams: {values: cfg.entities, autocomplete: true, listOnEmpty: true}}
      ]
    });
    document.getElementById("row-add").addEventListener("click", function () { table.addRow({header: "", entity: ""}, true); });
    document.getElementById("row-delete").addEventListener("click", function () {
      table.getSelectedRows().forEach(function (row) { row.delete(); });
    });
    document.getElementById("profile-form").addEventListener("submit", function () {
      document.getElementById("columns").value = JSON.stringify(table.getData().map(function (r) { return {header: r.header, entity: r.entity}; }));
    });
  };
})();
