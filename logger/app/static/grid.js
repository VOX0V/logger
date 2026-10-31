// Shared Tabulator page: remote paging/sort/filter, cell editing, "Add row" form and "Delete selected".
(function () {
  function csrf() { const m = document.querySelector("meta[name=csrf-token]"); return m ? m.content : ""; }
  function post(url, params) {
    return fetch(url, {method: "POST", headers: {"X-CSRFToken": csrf()}, body: new URLSearchParams(params)}).then(function (r) {
      if (!r.ok) return r.text().then(function (t) { throw new Error(t || "Request failed"); });
      return r;
    });
  }
  function remoteRequest(url, config, params) {
    const qs = new URLSearchParams();
    qs.set("page", params.page || 1);
    qs.set("size", params.size || 200);
    (params.sorters || []).forEach(function (s, i) { qs.set("sort[" + i + "][field]", s.field); qs.set("sort[" + i + "][dir]", s.dir); });
    (params.filters || []).forEach(function (f, i) { qs.set("filter[" + i + "][field]", f.field); qs.set("filter[" + i + "][type]", f.type); qs.set("filter[" + i + "][value]", f.value); });
    return fetch(url + "?" + qs.toString()).then(function (r) { return r.json(); });
  }
  window.initGrid = function (cfg) {
    const select = {formatter: "rowSelection", titleFormatter: "rowSelection", hozAlign: "center", headerSort: false, width: 40, frozen: true,
                    cellClick: function (e, cell) { cell.getRow().toggleSelect(); }};
    const columns = [select].concat(cfg.columns.map(function (c) {
      return Object.assign({editor: "input", headerFilter: "input", headerFilterPlaceholder: "filter…",
        cellEdited: function (cell) {
          const value = cell.getValue();
          post(cfg.cellUrl, {row_id: cell.getRow().getData().id, column: c.field, value: value === null || value === undefined ? "" : value})
            .catch(function (err) { alert("Change rejected: " + err.message); cell.restoreOldValue(); });
        }}, c);
    }));
    const table = new Tabulator(cfg.el || "#grid", {
      ajaxURL: cfg.rowsUrl, ajaxRequestFunc: remoteRequest,
      pagination: true, paginationMode: "remote", paginationSize: 200, paginationSizeSelector: [50, 200, 500, 1000],
      sortMode: "remote", filterMode: "remote", layout: "fitDataFill", height: "70vh",
      placeholder: cfg.placeholder || "No data.", columns: columns
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
    return table;
  };
})();
