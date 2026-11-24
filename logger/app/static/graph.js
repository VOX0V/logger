(function () {
  var script = document.currentScript, url = script.dataset.url;
  var select = document.getElementById("gr-select"), canvas = document.getElementById("gr-canvas");
  var msg = document.getElementById("gr-msg"), chart = null;
  if (!select || !window.Chart) return;
  var PALETTE = ["#2563eb", "#f59e0b", "#10b981", "#ef4444", "#8b5cf6", "#06b6d4", "#ec4899", "#84cc16", "#f97316", "#64748b"];
  function fmt(n) { return Number(n).toLocaleString("en-US", {maximumFractionDigits: 1}); }

  function draw(d) {
    if (chart) { chart.destroy(); chart = null; }
    if (d.error || !d.labels.length) {
      canvas.parentNode.hidden = true; msg.hidden = false; msg.textContent = d.error || "No data for this chart.";
      document.getElementById("gr-total").textContent = "–"; return;
    }
    canvas.parentNode.hidden = false; msg.hidden = true;
    var line = d.type === "line" || d.type === "area", many = d.labels.length > 40;
    document.getElementById("gr-total-label").textContent = d.cumulative ? "Final total" : "Total";
    var last = d.datasets.reduce(function (s, x) { return s + (d.cumulative ? x.data[x.data.length - 1] : x.data.reduce(function (a, b) { return a + b; }, 0)); }, 0);
    document.getElementById("gr-total").textContent = fmt(last);
    chart = new Chart(canvas, {
      type: line ? "line" : "bar",
      data: {labels: d.labels, datasets: d.datasets.map(function (s, i) {
        var c = PALETTE[i % PALETTE.length];
        return line ? {label: s.label, data: s.data, borderColor: c, backgroundColor: c + (d.type === "area" ? "40" : "20"), fill: d.type === "area" || d.stacked,
                       tension: 0.25, borderWidth: 2.2, pointRadius: many ? 0 : 3, pointHoverRadius: 5}
                    : {label: s.label, data: s.data, backgroundColor: c, borderRadius: 3, maxBarThickness: 46};
      })},
      options: {
        responsive: true, maintainAspectRatio: false, indexAxis: d.horizontal ? "y" : "x",
        interaction: {mode: d.horizontal ? "nearest" : "index", intersect: false},
        plugins: {
          legend: {display: d.datasets.length > 1, position: "bottom"},
          tooltip: {callbacks: {label: function (c) { return (d.datasets.length > 1 ? c.dataset.label + ": " : "") + fmt(c.parsed[d.horizontal ? "x" : "y"]) + " h"; }}}
        },
        scales: {
          x: {stacked: !!d.stacked, beginAtZero: true, grid: {display: !!d.horizontal, color: "rgba(100,116,139,.18)"},
              ticks: {autoSkip: true, maxTicksLimit: d.horizontal ? 12 : 24, maxRotation: 55}, title: {display: !!d.horizontal, text: "hours"}},
          y: {stacked: !!d.stacked, beginAtZero: true, grid: {color: "rgba(100,116,139,.18)"}, title: {display: !d.horizontal, text: "hours"}}
        }
      }
    });
  }

  function load() {
    fetch(url + "?chart=" + encodeURIComponent(select.value), {credentials: "same-origin"}).then(function (r) { return r.json(); }).then(draw)
      .catch(function () { draw({error: "Could not load the chart."}); });
  }
  select.addEventListener("change", load);
  if (select.options.length) load(); else draw({error: "No chart defined: see the graph/ folder."});
})();
