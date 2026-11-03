(function () {
  var el = document.getElementById("wm");
  if (!el || !window.L) return;
  var R = Math.PI / 180, NM = 3440.065;
  var map = L.map(el, {worldCopyJump: true, minZoom: 2, maxZoom: 12, zoomSnap: 0.25, preferCanvas: false}).setView([35, -40], 3);
  L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
    subdomains: "abcd", maxZoom: 12,
    attribution: "&copy; OpenStreetMap contributors &copy; CARTO"
  }).addTo(map);
  var layer = L.layerGroup().addTo(map), DATA = null, firstFit = true;
  var msg = document.getElementById("wm-msg");

  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]; }); }
  function fmt(n) { return Math.round(n).toLocaleString("en-US"); }

  // great circle between two [lat, lon] points, longitudes unwrapped so that the line never jumps across the map
  function arc(a, b) {
    var p1 = a[0] * R, l1 = a[1] * R, p2 = b[0] * R, l2 = b[1] * R;
    var d = 2 * Math.asin(Math.min(1, Math.sqrt(Math.pow(Math.sin((p2 - p1) / 2), 2) + Math.cos(p1) * Math.cos(p2) * Math.pow(Math.sin((l2 - l1) / 2), 2))));
    if (d < 1e-9) return {pts: [a, b], nm: 0};
    var n = Math.max(8, Math.min(160, Math.ceil(d / R / 1.5))), pts = [], prev = null;
    for (var i = 0; i <= n; i++) {
      var f = i / n, A = Math.sin((1 - f) * d) / Math.sin(d), B = Math.sin(f * d) / Math.sin(d);
      var x = A * Math.cos(p1) * Math.cos(l1) + B * Math.cos(p2) * Math.cos(l2);
      var y = A * Math.cos(p1) * Math.sin(l1) + B * Math.cos(p2) * Math.sin(l2);
      var z = A * Math.sin(p1) + B * Math.sin(p2);
      var lat = Math.atan2(z, Math.hypot(x, y)) / R, lon = Math.atan2(y, x) / R;
      if (prev !== null) { while (lon - prev > 180) lon -= 360; while (lon - prev < -180) lon += 360; }
      prev = lon; pts.push([lat, lon]);
    }
    return {pts: pts, nm: d * NM};
  }
  function shift(pts, k) { return pts.map(function (p) { return [p[0], p[1] + k]; }); }
  function color(t) { return "hsl(" + Math.round(195 - 170 * t) + ",95%,60%)"; }

  function render(year) {
    layer.clearLayers();
    var routes = {}, visits = {}, legs = 0;
    DATA.legs.forEach(function (g) {
      if (year && g[2] !== year) return;
      var a = g[0], b = g[1], n = g[3], key = a < b ? a + "|" + b : b + "|" + a;
      var r = routes[key] || (routes[key] = {a: a < b ? a : b, b: a < b ? b : a, n: 0});
      r.n += n; legs += n; visits[a] = (visits[a] || 0) + n; visits[b] = (visits[b] || 0) + n;
    });
    var list = Object.keys(routes).map(function (k) { return routes[k]; }).sort(function (x, y) { return x.n - y.n; });
    var max = list.length ? list[list.length - 1].n : 1, totalNm = 0, bounds = [];
    list.forEach(function (r) {
      var A = DATA.airports[r.a], B = DATA.airports[r.b];
      var c = arc([A.lat, A.lon], [B.lat, B.lon]), t = max > 1 ? (r.n - 1) / (max - 1) : 0, col = color(t);
      totalNm += c.nm * r.n;
      var tip = "<b>" + esc(r.a) + " ↔ " + esc(r.b) + "</b><br>" + r.n + " flight" + (r.n > 1 ? "s" : "") + " · " + fmt(c.nm) + " NM";
      [-360, 0, 360].forEach(function (k) {
        var pts = shift(c.pts, k);
        L.polyline(pts, {color: col, weight: 5 + 5 * t, opacity: 0.10, interactive: false, lineCap: "round"}).addTo(layer);
        L.polyline(pts, {color: col, weight: 1.1 + 1.7 * t, opacity: 0.88, interactive: false, lineCap: "round"}).addTo(layer);
        L.polyline(pts, {color: col, weight: 12, opacity: 0, className: "wm-hit"}).bindTooltip(tip, {sticky: true, className: "wm-tip"}).addTo(layer);
      });
    });
    var codes = Object.keys(visits).sort(function (x, y) { return visits[x] - visits[y]; });
    codes.forEach(function (code) {
      var ap = DATA.airports[code], v = visits[code], rad = Math.min(14, 3 + Math.sqrt(v) * 0.9);
      bounds.push([ap.lat, ap.lon]);
      var tip = "<b>" + esc(code) + "</b>" + (ap.name ? "<br>" + esc(ap.name) : "") + "<br>" + v + " movement" + (v > 1 ? "s" : "");
      [-360, 0, 360].forEach(function (k) {
        var ll = [ap.lat, ap.lon + k];
        L.circleMarker(ll, {radius: rad + 5, stroke: false, fillColor: "#fbbf24", fillOpacity: 0.16, interactive: false}).addTo(layer);
        var m = L.circleMarker(ll, {radius: rad, color: "#fff7ed", weight: 1.2, fillColor: "#f59e0b", fillOpacity: 0.95});
        m.bindTooltip(tip, {className: "wm-tip", direction: "top", offset: [0, -rad]});
        m.bindTooltip(esc(code), {permanent: true, direction: "right", offset: [rad + 2, 0], className: "wm-label"});
        m.addTo(layer);
      });
    });
    document.getElementById("wm-n-ap").textContent = codes.length;
    document.getElementById("wm-n-rt").textContent = list.length;
    document.getElementById("wm-n-lg").textContent = fmt(legs);
    document.getElementById("wm-n-nm").textContent = fmt(totalNm) + " NM";
    if (!codes.length) { msg.hidden = false; msg.textContent = "No leg with known airport coordinates."; return; }
    msg.hidden = true;
    if (firstFit || year !== undefined) { map.fitBounds(bounds, {padding: [60, 60], maxZoom: 6}); firstFit = false; }
  }

  function zoomClass() { el.classList.toggle("wm-z5", map.getZoom() >= 5); }
  map.on("zoomend", zoomClass); zoomClass();

  fetch(el.dataset.url, {credentials: "same-origin"}).then(function (r) { return r.json(); }).then(function (d) {
    if (d.error) { msg.hidden = false; msg.textContent = d.error; return; }
    DATA = d;
    var years = {}; d.legs.forEach(function (g) { if (g[2]) years[g[2]] = 1; });
    var sel = document.getElementById("wm-year");
    Object.keys(years).sort().reverse().forEach(function (y) { var o = document.createElement("option"); o.value = y; o.textContent = y; sel.appendChild(o); });
    sel.addEventListener("change", function () { render(sel.value ? parseInt(sel.value, 10) : null); });
    render(null);
  }).catch(function () { msg.hidden = false; msg.textContent = "Could not load the map data."; });
})();
