(function () {
  var el = document.getElementById("wm");
  if (!el || !window.maplibregl) return;
  var R = Math.PI / 180, NM = 3440.065, msg = document.getElementById("wm-msg");
  maplibregl.setWorkerUrl(el.dataset.worker);

  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]; }); }
  function fmt(n) { return Math.round(n).toLocaleString("en-US"); }
  function color(t) { return "hsl(" + Math.round(195 - 170 * t) + ",95%,60%)"; }

  // great circle between two [lon, lat] points; longitudes are unwrapped so the line never jumps across the map
  function arc(a, b) {
    var p1 = a[1] * R, l1 = a[0] * R, p2 = b[1] * R, l2 = b[0] * R;
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
      prev = lon; pts.push([lon, lat]);
    }
    return {pts: pts, nm: d * NM};
  }

  var EMPTY = {type: "FeatureCollection", features: []};
  var OFFLINE = {version: 8, sources: {}, layers: [{id: "bg", type: "background", paint: {"background-color": "#0b1d3a"}}]};

  fetch(el.dataset.style).then(function (r) { if (!r.ok) throw new Error("style"); return r.json(); }).catch(function () { return null; }).then(function (style) {
    var online = !!style;
    var font = ["Noto Sans Regular"];
    if (online) (style.layers || []).some(function (l) {
      var f = l.layout && l.layout["text-font"];
      if (Array.isArray(f) && f.length && f.every(function (x) { return typeof x === "string"; })) { font = f; return true; }
      return false;
    });
    var map = new maplibregl.Map({container: el, style: style || OFFLINE, center: [-40, 30], zoom: 1.3, minZoom: 0.8, maxZoom: 12, attributionControl: false});
    map.addControl(new maplibregl.AttributionControl({compact: true}));
    map.addControl(new maplibregl.NavigationControl({visualizePitch: true}), "top-right");
    var popup = new maplibregl.Popup({closeButton: false, closeOnClick: false, className: "wm-tip", offset: 12, maxWidth: "260px"});
    var DATA = null, ready = false, globe = true, firstFit = true;

    function setGlobe(on) {
      globe = on;
      map.setProjection({type: on ? "globe" : "mercator"});
      document.getElementById("wm-proj").textContent = on ? "Flat map" : "Globe";
    }

    function render(year) {
      var routes = {}, visits = {}, legs = 0;
      DATA.legs.forEach(function (g) {
        if (year && g[2] !== year) return;
        var a = g[0], b = g[1], n = g[3];
        legs += n; visits[a] = (visits[a] || 0) + n; visits[b] = (visits[b] || 0) + n;
        if (a === b) return;                                 // local flight (same airport): no line, and it must not set the colour scale
        var key = a < b ? a + "|" + b : b + "|" + a;
        var r = routes[key] || (routes[key] = {a: a < b ? a : b, b: a < b ? b : a, n: 0});
        r.n += n;
      });
      var list = Object.keys(routes).map(function (k) { return routes[k]; }).sort(function (x, y) { return x.n - y.n; });
      var max = list.length ? list[list.length - 1].n : 1, totalNm = 0;
      var rf = list.map(function (r) {
        var A = DATA.airports[r.a], B = DATA.airports[r.b];
        var c = arc([A.lon, A.lat], [B.lon, B.lat]), t = max > 1 ? Math.log(r.n) / Math.log(max) : 0;
        totalNm += c.nm * r.n;
        return {type: "Feature", geometry: {type: "LineString", coordinates: c.pts},
          properties: {a: r.a, b: r.b, n: r.n, nm: Math.round(c.nm), color: color(t), w: 1.1 + 1.7 * t, gw: 6 + 6 * t}};
      });
      var bounds = new maplibregl.LngLatBounds(), codes = Object.keys(visits).sort(function (x, y) { return visits[x] - visits[y]; });
      var af = codes.map(function (code) {
        var ap = DATA.airports[code], v = visits[code];
        bounds.extend([ap.lon, ap.lat]);
        return {type: "Feature", geometry: {type: "Point", coordinates: [ap.lon, ap.lat]},
          properties: {code: code, name: ap.name || "", v: v, r: Math.min(14, 3 + Math.sqrt(v) * 0.9)}};
      });
      map.getSource("routes").setData({type: "FeatureCollection", features: rf});
      map.getSource("airports").setData({type: "FeatureCollection", features: af});
      document.getElementById("wm-n-ap").textContent = codes.length;
      document.getElementById("wm-n-rt").textContent = list.length;
      document.getElementById("wm-n-lg").textContent = fmt(legs);
      document.getElementById("wm-n-nm").textContent = fmt(totalNm) + " NM";
      if (!codes.length) { msg.hidden = false; msg.textContent = "No leg with known airport coordinates."; return; }
      msg.hidden = true;
      map.fitBounds(bounds, {padding: 90, maxZoom: 4.5, duration: firstFit ? 0 : 900});
      firstFit = false;
    }

    function maybeRender() { if (ready && DATA) render(null); }

    map.on("load", function () {
      try { setGlobe(true); } catch (e) { document.getElementById("wm-proj").hidden = true; }
      try { map.setSky({"sky-color": "#0b1d3a", "horizon-color": "#2563eb", "sky-horizon-blend": 0.5, "atmosphere-blend": ["interpolate", ["linear"], ["zoom"], 0, 1, 4, 1, 7, 0]}); } catch (e) {}
      map.addSource("routes", {type: "geojson", data: EMPTY});
      map.addSource("airports", {type: "geojson", data: EMPTY});
      map.addLayer({id: "routes-glow", type: "line", source: "routes", layout: {"line-cap": "round", "line-join": "round"},
        paint: {"line-color": ["get", "color"], "line-width": ["get", "gw"], "line-opacity": 0.13, "line-blur": 4}});
      map.addLayer({id: "routes-core", type: "line", source: "routes", layout: {"line-cap": "round", "line-join": "round"},
        paint: {"line-color": ["get", "color"], "line-width": ["get", "w"], "line-opacity": 0.92}});
      map.addLayer({id: "routes-hit", type: "line", source: "routes", paint: {"line-color": "#ffffff", "line-width": 14, "line-opacity": 0.01}});
      map.addLayer({id: "ap-halo", type: "circle", source: "airports", paint: {"circle-radius": ["+", ["get", "r"], 5], "circle-color": "#fbbf24", "circle-opacity": 0.16}});
      map.addLayer({id: "ap", type: "circle", source: "airports", paint: {"circle-radius": ["get", "r"], "circle-color": "#f59e0b", "circle-opacity": 0.96, "circle-stroke-color": "#fff7ed", "circle-stroke-width": 1.2}});
      if (online && style.glyphs) map.addLayer({id: "ap-label", type: "symbol", source: "airports", minzoom: 3.2,
        layout: {"text-field": ["get", "code"], "text-font": font, "text-size": 11, "text-anchor": "left", "text-offset": [1.1, 0], "text-optional": true},
        paint: {"text-color": "#f1f5f9", "text-halo-color": "#020617", "text-halo-width": 1.6}});

      map.on("mousemove", "ap", function (e) {
        var f = e.features[0], p = f.properties;
        map.getCanvas().style.cursor = "pointer";
        popup.setLngLat(f.geometry.coordinates).setHTML("<b>" + esc(p.code) + "</b>" + (p.name ? "<br>" + esc(p.name) : "") + "<br>" + p.v + " movement" + (p.v > 1 ? "s" : "")).addTo(map);
      });
      map.on("mouseleave", "ap", function () { map.getCanvas().style.cursor = ""; popup.remove(); });
      map.on("mousemove", "routes-hit", function (e) {
        if (map.queryRenderedFeatures(e.point, {layers: ["ap"]}).length) return;
        var p = e.features[0].properties;
        map.getCanvas().style.cursor = "pointer";
        popup.setLngLat(e.lngLat).setHTML("<b>" + esc(p.a) + " ↔ " + esc(p.b) + "</b><br>" + p.n + " flight" + (p.n > 1 ? "s" : "") + " · " + fmt(p.nm) + " NM").addTo(map);
      });
      map.on("mouseleave", "routes-hit", function () { map.getCanvas().style.cursor = ""; popup.remove(); });
      ready = true; maybeRender();
    });

    document.getElementById("wm-proj").addEventListener("click", function () { setGlobe(!globe); });
    fetch(el.dataset.url, {credentials: "same-origin"}).then(function (r) { return r.json(); }).then(function (d) {
      if (d.error) { msg.hidden = false; msg.textContent = d.error; return; }
      DATA = d;
      var years = {}; d.legs.forEach(function (g) { if (g[2]) years[g[2]] = 1; });
      var sel = document.getElementById("wm-year");
      Object.keys(years).sort().reverse().forEach(function (y) { var o = document.createElement("option"); o.value = y; o.textContent = y; sel.appendChild(o); });
      sel.addEventListener("change", function () { render(sel.value ? parseInt(sel.value, 10) : null); });
      maybeRender();
    }).catch(function () { msg.hidden = false; msg.textContent = "Could not load the map data."; });
  });
})();
