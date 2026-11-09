// Entities page: Tabulator grid with cell editing, add / delete and drag-and-drop reordering of the rows.
(function () {
  function csrf() { const m = document.querySelector("meta[name=csrf-token]"); return m ? m.content : ""; }
  function post(url, params) {
    return fetch(url, {method: "POST", headers: {"X-CSRFToken": csrf()}, body: new URLSearchParams(params)}).then(function (r) {
      if (!r.ok) return r.text().then(function (t) { throw new Error(t || "Request failed"); });
      return r;
    });
  }
  window.initEntities = function (cfg) {
    const edit = function (field, title) {
      return {title: title, field: field, editor: "input", headerSort: false,
        cellEdited: function (cell) {
          post(cfg.cellUrl, {row_id: cell.getRow().getData().id, column: field, value: cell.getValue() == null ? "" : cell.getValue()})
            .catch(function (err) { alert("Change rejected: " + err.message); cell.restoreOldValue(); });
        }};
    };
    const type = edit("data_type", "data type");
    type.editor = "list"; type.editorParams = {values: cfg.types};
    const table = new Tabulator("#grid", {
      ajaxURL: cfg.rowsUrl, index: "id", layout: "fitData", height: "70vh", movableRows: true,
      placeholder: "No entities.",
      columns: [
        {rowHandle: true, formatter: "handle", headerSort: false, width: 30, minWidth: 30, resizable: false},
        {formatter: "rowSelection", titleFormatter: "rowSelection", hozAlign: "center", headerSort: false, width: 40, resizable: false,
         cellClick: function (e, cell) { cell.getRow().toggleSelect(); }},
        {title: "position", field: "position", headerSort: false, width: 90},
        edit("group", "group"), edit("name", "name"), edit("entity", "field"), type, edit("display_name", "label")
      ]
    });
    table.on("rowMoved", function (row) {
      post(cfg.moveUrl, {id: row.getData().id, position: row.getPosition()})
        .then(function () { table.replaceData(); })
        .catch(function (err) { alert("Move failed: " + err.message); table.replaceData(); });
    });
    const del = document.getElementById("grid-delete");
    if (del) del.addEventListener("click", function () {
      const ids = table.getSelectedData().map(function (r) { return r.id; });
      if (!ids.length) { alert("Select at least one row first."); return; }
      if (!window.confirm("Delete " + ids.length + " selected row(s)?")) return;
      post(cfg.deleteUrl, {ids: ids.join(",")}).then(function () { table.replaceData(); }).catch(function (err) { alert(err.message); });
    });
    const form = document.getElementById("grid-add");
    if (form) form.addEventListener("submit", function (e) {
      e.preventDefault();
      const params = {};
      new FormData(form).forEach(function (v, k) { if (String(v).trim() !== "") params[k] = String(v).trim(); });
      post(cfg.addUrl, params).then(function () {
        form.reset(); document.getElementById("add-panel").hidden = true; table.replaceData();
      }).catch(function (err) { alert("Row not added: " + err.message); });
    });
  };
})();
