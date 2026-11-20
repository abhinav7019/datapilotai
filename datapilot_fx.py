"""
datapilot_fx.py - the 3D background and interactive effects for DataPilot AI
============================================================================
No Streamlit import. fx_html() returns a tiny HTML snippet; the app shows it in a zero-height
component. The snippet installs ONE script in the page itself (so it survives Streamlit reruns):

  * 3D background drawn on a canvas behind the app (perspective projection, mouse parallax):
        "Neural network"   linked nodes drifting in 3D
        "Galaxy"           a rotating spiral of ~1,000 stars
        "Floating shapes"  wireframe cubes / pyramids / gems slowly turning
        "Off"
  * Interactive effects (can be switched off): cards tilt towards the mouse, a soft light follows the
    cursor, KPI numbers count up, a thin progress bar shows how far you scrolled.

Safe by design: no network access, pauses when the tab is hidden, honours "reduce motion",
uses fewer particles on phones, and never touches the app's data.
"""

import json

BACKGROUNDS = ["Neural network", "Galaxy", "Floating shapes", "Off"]
DEFAULT_BG = "Neural network"

_JS = r"""
(function () {
  if (window.__dpfx) return;
  var D = document, W = window;
  var reduce = !!(W.matchMedia && W.matchMedia('(prefers-reduced-motion: reduce)').matches);
  var cfg = { bg: 'Off', accent: '#00b4d8', effects: true, dark: true };
  var canvas = null, ctx = null, cw = W.innerWidth, ch = W.innerHeight, dpr = 1;
  var glow = null, bar = null, scene = null, sceneKey = '';
  var mouse = { x: 0, y: 0, tx: 0, ty: 0, gx: -999, gy: -999, sx: -999, sy: -999 };
  var running = false, lastT = 0, tiltEl = null, mobile = Math.min(W.innerWidth, W.innerHeight) < 700;
  var TILT = '.kpi, [data-testid="stMetric"], .feat, .tilt';
  var COUNT = '.kpi .val, [data-testid="stMetricValue"]';

  function rnd(a, b) { return a + Math.random() * (b - a); }
  function rgb(h) {
    h = String(h || '').replace('#', '');
    if (h.length === 3) h = h.split('').map(function (c) { return c + c; }).join('');
    var n = parseInt(h.slice(0, 6), 16);
    if (isNaN(n)) n = 0x00b4d8;
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }
  function mixc(a, b, t) { return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t]; }
  function css(c, a) { return 'rgba(' + (c[0] | 0) + ',' + (c[1] | 0) + ',' + (c[2] | 0) + ',' + a + ')'; }

  // ---------- canvas / helpers ----------
  function ensure() {
    var app = D.querySelector('.stApp');
    if (!app) return false;
    if (!canvas || !D.body.contains(canvas)) {
      canvas = D.getElementById('dp-bg') || D.createElement('canvas');
      canvas.id = 'dp-bg';
      canvas.setAttribute('aria-hidden', 'true');
      canvas.style.cssText = 'position:fixed;left:0;top:0;width:100vw;height:100vh;z-index:0;pointer-events:none;';
      app.insertBefore(canvas, app.firstChild);
      ctx = canvas.getContext('2d');
      resize();
    }
    if (!glow || !D.body.contains(glow)) {
      glow = D.getElementById('dp-glow') || D.createElement('div');
      glow.id = 'dp-glow';
      glow.setAttribute('aria-hidden', 'true');
      glow.style.cssText = 'position:fixed;left:0;top:0;width:560px;height:560px;margin:-280px 0 0 -280px;' +
        'border-radius:50%;pointer-events:none;z-index:0;opacity:0;transition:opacity .4s;will-change:transform;';
      app.insertBefore(glow, canvas.nextSibling);
    }
    if (!bar || !D.body.contains(bar)) {
      bar = D.getElementById('dp-progress') || D.createElement('div');
      bar.id = 'dp-progress';
      bar.setAttribute('aria-hidden', 'true');
      bar.style.cssText = 'position:fixed;left:0;top:0;height:3px;width:0;z-index:1000001;pointer-events:none;' +
        'transition:width .12s linear;';
      D.body.appendChild(bar);
    }
    return true;
  }
  function resize() {
    if (!canvas) return;
    dpr = Math.min(W.devicePixelRatio || 1, 2);
    cw = W.innerWidth; ch = W.innerHeight;
    canvas.width = Math.round(cw * dpr); canvas.height = Math.round(ch * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    sceneKey = '';
    if (reduce) renderOnce();
  }
  function colors() {
    var ac = rgb(cfg.accent);
    return cfg.dark
      ? { ac: ac, node: mixc(ac, [255, 255, 255], .55), line: mixc(ac, [255, 255, 255], .25), add: true }
      : { ac: ac, node: mixc(ac, [0, 0, 0], .15), line: ac, add: false };
  }

  // ---------- 3D maths ----------
  function view(x, y, z, ry, rx) {
    var cy = Math.cos(ry), sy = Math.sin(ry), cx = Math.cos(rx), sx = Math.sin(rx);
    var x1 = x * cy + z * sy, z1 = -x * sy + z * cy;
    var y2 = y * cx - z1 * sx, z2 = y * sx + z1 * cx;
    var k = 3 / (3 + z2);
    return { x: x1, y: y2, z: z2, k: k };
  }

  // ---------- scenes ----------
  var SHAPES = null;
  function polyhedra() {
    if (SHAPES) return SHAPES;
    var p = (1 + Math.sqrt(5)) / 2, defs = {
      cube: [[1, 1, 1], [1, 1, -1], [1, -1, 1], [1, -1, -1], [-1, 1, 1], [-1, 1, -1], [-1, -1, 1], [-1, -1, -1]],
      octa: [[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1]],
      tetra: [[1, 1, 1], [1, -1, -1], [-1, 1, -1], [-1, -1, 1]],
      icosa: [[0, 1, p], [0, -1, p], [0, 1, -p], [0, -1, -p], [1, p, 0], [-1, p, 0], [1, -p, 0], [-1, -p, 0],
              [p, 0, 1], [-p, 0, 1], [p, 0, -1], [-p, 0, -1]]
    };
    SHAPES = [];
    Object.keys(defs).forEach(function (k) {
      var v = defs[k].map(function (a) { var l = Math.hypot(a[0], a[1], a[2]); return [a[0] / l, a[1] / l, a[2] / l]; });
      var min = 9, i, j;
      for (i = 0; i < v.length; i++) for (j = i + 1; j < v.length; j++) {
        min = Math.min(min, Math.hypot(v[i][0] - v[j][0], v[i][1] - v[j][1], v[i][2] - v[j][2]));
      }
      var e = [];
      for (i = 0; i < v.length; i++) for (j = i + 1; j < v.length; j++) {
        if (Math.hypot(v[i][0] - v[j][0], v[i][1] - v[j][1], v[i][2] - v[j][2]) < min * 1.05) e.push([i, j]);
      }
      SHAPES.push({ v: v, e: e });
    });
    return SHAPES;
  }
  function build() {
    var key = cfg.bg + '|' + cw + 'x' + ch;
    if (key === sceneKey) return;
    sceneKey = key; scene = { type: cfg.bg }; var i;
    if (cfg.bg === 'Neural network') {
      var n = Math.max(34, Math.min(mobile ? 46 : 92, Math.round(cw * ch / 19000)));
      scene.p = [];
      for (i = 0; i < n; i++) scene.p.push({ x: rnd(-1, 1), y: rnd(-1, 1), z: rnd(-1, 1),
        vx: rnd(-.00022, .00022), vy: rnd(-.00022, .00022), vz: rnd(-.00022, .00022) });
    } else if (cfg.bg === 'Galaxy') {
      var m = mobile ? 520 : 1150; scene.s = [];
      for (i = 0; i < m; i++) {
        var r = Math.pow(Math.random(), .62) * 1.2, arm = i % 3, ang = r * 5.4 + arm * 2.0944 + rnd(-.4, .4) * (.25 + r);
        scene.s.push({ x: r * Math.cos(ang), z: r * Math.sin(ang), y: rnd(-.07, .07) * (1.3 - r), r: r,
          size: rnd(.7, 2.3), tw: rnd(0, 6.28) });
      }
    } else if (cfg.bg === 'Floating shapes') {
      var sh = polyhedra(), c = mobile ? 6 : 10; scene.o = []; scene.d = [];
      for (i = 0; i < c; i++) scene.o.push({ g: sh[i % sh.length], x: rnd(-1, 1), y: rnd(-1.1, 1.1), z: rnd(-.8, .8),
        size: rnd(.11, .26), ax: rnd(0, 6), ay: rnd(0, 6), az: rnd(0, 6),
        wx: rnd(-.0005, .0005), wy: rnd(-.0007, .0007), wz: rnd(-.0004, .0004), vy: rnd(.00004, .00012) });
      for (i = 0; i < (mobile ? 30 : 70); i++) scene.d.push({ x: rnd(-1, 1), y: rnd(-1, 1), z: rnd(-1, 1) });
    }
  }
  function drawNetwork(t, dt, C) {
    var P = scene.p, ry = t * .00007 + mouse.x * .55, rx = mouse.y * .35 + Math.sin(t * .00004) * .12;
    var sx = cw * .55, sy = ch * .55, i, j, pr = [];
    for (i = 0; i < P.length; i++) {
      var p = P[i]; p.x += p.vx * dt; p.y += p.vy * dt; p.z += p.vz * dt;
      if (p.x < -1 || p.x > 1) p.vx *= -1; if (p.y < -1 || p.y > 1) p.vy *= -1; if (p.z < -1 || p.z > 1) p.vz *= -1;
      var v = view(p.x, p.y, p.z, ry, rx);
      pr.push({ X: cw / 2 + v.x * sx * v.k, Y: ch / 2 + v.y * sy * v.k, k: v.k, z: v.z });
    }
    ctx.lineWidth = 1;
    var LIM = .6;
    for (i = 0; i < P.length; i++) for (j = i + 1; j < P.length; j++) {
      var d = Math.hypot(P[i].x - P[j].x, P[i].y - P[j].y, P[i].z - P[j].z);
      if (d < LIM) {
        var fade = Math.max(.25, Math.min(1, (pr[i].k + pr[j].k) / 2 - .35));
        ctx.strokeStyle = css(C.line, ((1 - d / LIM) * .42 * fade).toFixed(3));
        ctx.beginPath(); ctx.moveTo(pr[i].X, pr[i].Y); ctx.lineTo(pr[j].X, pr[j].Y); ctx.stroke();
      }
    }
    for (i = 0; i < pr.length; i++) {
      var q = pr[i], a = Math.max(.25, Math.min(1, q.k - .3));
      ctx.fillStyle = css(C.node, (a * .9).toFixed(3));
      ctx.beginPath(); ctx.arc(q.X, q.Y, Math.max(.8, 2.1 * q.k), 0, 6.2832); ctx.fill();
    }
  }
  function drawGalaxy(t, dt, C) {
    var S = scene.s, ry = t * .00005 + mouse.x * .9, rx = 1.0 + mouse.y * .5, i;
    var sc = Math.min(cw, ch) * (mobile ? .62 : .72), cx = cw * .5, cy = ch * .52;
    var g = ctx.createRadialGradient(cx, cy, 0, cx, cy, sc * .75);
    g.addColorStop(0, css(C.ac, C.add ? .22 : .12)); g.addColorStop(1, css(C.ac, 0));
    ctx.fillStyle = g; ctx.fillRect(0, 0, cw, ch);
    if (C.add) ctx.globalCompositeOperation = 'lighter';
    for (i = 0; i < S.length; i++) {
      var s = S[i], v = view(s.x, s.y, s.z, ry, rx);
      var X = cx + v.x * sc * v.k * 1.35, Y = cy + v.y * sc * v.k * 1.35;
      if (X < -4 || X > cw + 4 || Y < -4 || Y > ch + 4) continue;
      var tw = .75 + .25 * Math.sin(t * .002 + s.tw), a = Math.max(.12, Math.min(1, v.k - .1)) * tw;
      var col = mixc([255, 244, 220], C.ac, Math.min(1, s.r / 1.05));
      if (!C.add) col = mixc(C.ac, [0, 0, 0], .25);
      ctx.fillStyle = css(col, 1); ctx.globalAlpha = a * (C.add ? .95 : .55);
      var z = s.size * v.k; ctx.fillRect(X, Y, z, z);
    }
    ctx.globalAlpha = 1; ctx.globalCompositeOperation = 'source-over';
  }
  function drawShapes(t, dt, C) {
    var ry = mouse.x * .5, rx = mouse.y * .3, i, j, sc = Math.min(cw, ch) * .62;
    var D2 = scene.d;
    for (i = 0; i < D2.length; i++) {
      var d = D2[i], vd = view(d.x, d.y, d.z, ry, rx);
      ctx.fillStyle = css(C.node, (Math.max(.1, vd.k - .5) * .5).toFixed(3));
      ctx.fillRect(cw / 2 + vd.x * cw * .55 * vd.k, ch / 2 + vd.y * ch * .55 * vd.k, 1.6 * vd.k, 1.6 * vd.k);
    }
    ctx.lineWidth = 1.2;
    for (i = 0; i < scene.o.length; i++) {
      var o = scene.o[i], g = o.g; o.ax += o.wx * dt; o.ay += o.wy * dt; o.az += o.wz * dt; o.y -= o.vy * dt;
      if (o.y < -1.25) o.y = 1.25;
      var ca = Math.cos(o.ax), sa = Math.sin(o.ax), cb = Math.cos(o.ay), sb = Math.sin(o.ay), cc = Math.cos(o.az), sc2 = Math.sin(o.az);
      var P = g.v.map(function (v) {
        var x = v[0], y = v[1] * ca - v[2] * sa, z = v[1] * sa + v[2] * ca;
        var x2 = x * cb + z * sb, z2 = -x * sb + z * cb;
        var x3 = x2 * cc - y * sc2, y3 = x2 * sc2 + y * cc;
        var w = view(o.x + x3 * o.size, o.y + y3 * o.size, o.z + z2 * o.size, ry, rx);
        return { X: cw / 2 + w.x * cw * .55 * w.k, Y: ch / 2 + w.y * ch * .55 * w.k, k: w.k };
      });
      for (j = 0; j < g.e.length; j++) {
        var A = P[g.e[j][0]], B = P[g.e[j][1]], f = Math.max(.15, Math.min(1, (A.k + B.k) / 2 - .35));
        ctx.strokeStyle = css(C.line, (f * .6).toFixed(3));
        ctx.beginPath(); ctx.moveTo(A.X, A.Y); ctx.lineTo(B.X, B.Y); ctx.stroke();
      }
      for (j = 0; j < P.length; j++) {
        ctx.fillStyle = css(C.node, .85); ctx.beginPath(); ctx.arc(P[j].X, P[j].Y, 1.8 * P[j].k, 0, 6.2832); ctx.fill();
      }
    }
  }
  function render(t, dt) {
    if (!ctx || cfg.bg === 'Off') return;
    ctx.clearRect(0, 0, cw, ch); build();
    var C = colors();
    if (scene.type === 'Neural network') drawNetwork(t, dt, C);
    else if (scene.type === 'Galaxy') drawGalaxy(t, dt, C);
    else if (scene.type === 'Floating shapes') drawShapes(t, dt, C);
  }
  function renderOnce() { if (ctx) render(1500, 16); }

  // ---------- loop ----------
  function frame(now) {
    running = false;
    if (D.hidden) return;
    if (now - lastT < 26) { loop(); return; }
    var dt = Math.min(now - lastT, 60); lastT = now;
    mouse.x += (mouse.tx - mouse.x) * .06; mouse.y += (mouse.ty - mouse.y) * .06;
    render(now, dt);
    if (glow) {
      mouse.sx += (mouse.gx - mouse.sx) * .14; mouse.sy += (mouse.gy - mouse.sy) * .14;
      glow.style.transform = 'translate3d(' + mouse.sx.toFixed(1) + 'px,' + mouse.sy.toFixed(1) + 'px,0)';
    }
    loop();
  }
  function loop() {
    if (running || reduce) return;
    if (cfg.bg === 'Off' && !cfg.effects) return;
    running = true; W.requestAnimationFrame(frame);
  }

  // ---------- interactive effects ----------
  function resetTilt(el) { el.style.transition = 'transform .45s cubic-bezier(.2,.7,.2,1)'; el.style.transform = ''; }
  function onMove(e) {
    mouse.tx = e.clientX / Math.max(1, cw) - .5; mouse.ty = e.clientY / Math.max(1, ch) - .5;
    mouse.gx = e.clientX; mouse.gy = e.clientY;
    if (mouse.sx < -900) { mouse.sx = e.clientX; mouse.sy = e.clientY; }
    if (!cfg.effects || reduce) return;
    var el = e.target && e.target.closest ? e.target.closest(TILT) : null;
    if (tiltEl && tiltEl !== el) { resetTilt(tiltEl); tiltEl = null; }
    if (el) {
      var r = el.getBoundingClientRect(), px = (e.clientX - r.left) / Math.max(1, r.width), py = (e.clientY - r.top) / Math.max(1, r.height);
      el.style.transition = 'transform .08s ease-out';
      el.style.transform = 'perspective(700px) rotateX(' + ((.5 - py) * 9).toFixed(2) + 'deg) rotateY(' + ((px - .5) * 11).toFixed(2) + 'deg) translateZ(6px)';
      el.style.setProperty('--mx', (px * 100).toFixed(0) + '%'); el.style.setProperty('--my', (py * 100).toFixed(0) + '%');
      tiltEl = el;
    }
  }
  function onLeave() { if (tiltEl) { resetTilt(tiltEl); tiltEl = null; } }
  function onScroll(e) {
    if (!bar || !cfg.effects) return;
    var t = e.target; if (!t || t === D) t = D.scrollingElement || D.documentElement;
    var max = (t.scrollHeight || 0) - (t.clientHeight || 0);
    if (max > 40 && t.clientHeight > 200) bar.style.width = Math.max(0, Math.min(100, (t.scrollTop / max) * 100)) + '%';
  }
  function leaf(el) {
    var n = el; while (n && n.firstElementChild) n = n.firstElementChild;
    if (!n) return null;
    for (var c = n.firstChild; c; c = c.nextSibling) if (c.nodeType === 3 && /\d/.test(c.nodeValue)) return c;
    return null;
  }
  function countUp(el) {
    var node = leaf(el); if (!node) return;
    var txt = node.nodeValue;
    if (el.getAttribute('data-cu') === txt) return;
    el.setAttribute('data-cu', txt);
    var m = txt.match(/-?\d[\d,]*\.?\d*/); if (!m) return;
    var ns = m[0], hasC = ns.indexOf(',') > -1, dec = (ns.split('.')[1] || '').length, target = parseFloat(ns.replace(/,/g, ''));
    if (!isFinite(target) || Math.abs(target) < 1) return;
    var pre = txt.slice(0, m.index), post = txt.slice(m.index + ns.length), t0 = performance.now(), last = txt;
    (function step(now) {
      if (node.nodeValue !== last) return;               // the app changed it: stop, do not fight it
      var p = Math.min(1, (now - t0) / 850), v = target * (1 - Math.pow(1 - p, 3)), s = v.toFixed(dec);
      if (p >= 1) { node.nodeValue = txt; return; }
      if (hasC) { var q = s.split('.'); q[0] = q[0].replace(/\B(?=(\d{3})+(?!\d))/g, ','); s = q.join('.'); }
      last = pre + s + post; node.nodeValue = last; W.requestAnimationFrame(step);
    })(t0);
  }
  var scanT = 0;
  function scan() {
    clearTimeout(scanT);
    scanT = setTimeout(function () {
      if (typeof tick === 'function') tick();
      if (!cfg.effects || reduce) return;
      var els = D.querySelectorAll(COUNT); for (var i = 0; i < els.length; i++) countUp(els[i]);
      if (typeof tick === 'function') tick();
    }, 160);
  }

  // ---------- public ----------
  function theme() {
    var ac = rgb(cfg.accent);
    if (glow) {
      glow.style.background = 'radial-gradient(circle, ' + css(ac, cfg.dark ? .17 : .12) + ', ' + css(ac, 0) + ' 62%)';
      glow.style.mixBlendMode = cfg.dark ? 'screen' : 'multiply';
      glow.style.opacity = cfg.effects && !reduce ? 1 : 0;
    }
    if (bar) {
      bar.style.background = 'linear-gradient(90deg,' + css(ac, 1) + ',' + css(mixc(ac, [255, 255, 255], .6), 1) + ')';
      bar.style.opacity = cfg.effects ? 1 : 0;
    }
  }
  function update(c) {
    for (var k in c) cfg[k] = c[k];
    if (!ensure()) return;
    canvas.style.display = cfg.bg === 'Off' ? 'none' : 'block';
    canvas.style.opacity = String(cfg.opacity != null ? cfg.opacity : (cfg.dark ? 0.9 : 0.6));
    if (cfg.bg === 'Off') ctx.clearRect(0, 0, cw, ch);
    sceneKey = ''; theme();
    if (reduce) renderOnce(); else loop();
    scan();
  }


  // ---------- Flex look: navigation, doors, pull-cord, clock ----------
  var TABS = { 'go-insights': 'Insights', 'go-toolkit': 'Analyst Toolkit', 'go-dash': 'Power BI', 'go-ai': 'Ask AI', 'go-projects': 'Projects' };
  var GOS = ['go-home', 'go-insights', 'go-toolkit', 'go-dash', 'go-ai', 'go-projects', 'go-doors', 'go-start'];
  var MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
  function findTab(key) {
    var all = D.querySelectorAll('[role="tab"], [data-baseweb="tab"]');
    for (var i = 0; i < all.length; i++) if ((all[i].innerText || '').indexOf(key) > -1) return all[i];
    return null;
  }
  function scrollToEl(el) { if (el && el.scrollIntoView) el.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' }); }
  function goTo(cls) {
    if (cls === 'go-home') { var top = D.querySelector('.fx-nav') || D.querySelector('.stApp'); scrollToEl(top); return; }
    if (cls === 'go-doors') { scrollToEl(D.querySelector('.fx-doors') || D.querySelector('.anchor-add-data')); return; }
    if (cls === 'go-start') { scrollToEl(D.querySelector('.anchor-add-data')); return; }
    var key = TABS[cls], tab = key ? findTab(key) : null;
    if (tab) { tab.click(); setTimeout(function () { scrollToEl(tab.closest('[role="tablist"], [data-baseweb="tab-list"]') || tab); }, 80); }
    else scrollToEl(D.querySelector('.anchor-add-data'));        // no data yet: take them to the "add data" step
  }
  function pullCord(c) {
    c.classList.add('pulled');
    setTimeout(function () { c.classList.remove('pulled'); c.classList.add('swing'); setTimeout(function () { c.classList.remove('swing'); }, 1000); }, 220);
    var boxes = D.querySelectorAll('[data-testid="stCheckbox"], [data-testid="stToggle"]');
    for (var i = 0; i < boxes.length; i++) {
      if (/dark mode/i.test(boxes[i].innerText || '')) { var inp = boxes[i].querySelector('input[type="checkbox"]'); (inp || boxes[i].querySelector('label') || boxes[i]).click(); return; }
    }
  }
  function onClick(e) {
    var t = e.target; if (!t || !t.closest) return;
    var cord = t.closest('.cord'); if (cord) { pullCord(cord); return; }
    var hit = t.closest('.nl, .pill, .door-wrap'); if (!hit) return;
    var cls = '';
    for (var i = 0; i < GOS.length; i++) if (hit.classList.contains(GOS[i])) cls = GOS[i];
    if (!cls) return;
    if (hit.classList.contains('door-wrap')) {
      hit.classList.add('open');
      setTimeout(function () { goTo(cls); setTimeout(function () { hit.classList.remove('open'); }, 1000); }, 480);
    } else goTo(cls);
  }
  function placeCord() {                       // hang the cord right beside the Dark mode switch, whatever the layout
    var c = D.querySelector('.cord'); if (!c) return;
    var boxes = D.querySelectorAll('[data-testid="stCheckbox"], [data-testid="stToggle"]');
    for (var i = 0; i < boxes.length; i++) {
      if (/dark mode/i.test(boxes[i].innerText || '')) {
        var r = boxes[i].getBoundingClientRect();
        if (r.width > 0) { c.style.right = 'auto'; c.style.left = Math.round(r.right + 6) + 'px'; }
        return;
      }
    }
  }
  function tick() {
    placeCord();
    var d = new Date(), h = d.getHours(), m = d.getMinutes();
    var t = ((h % 12) || 12) + ':' + (m < 10 ? '0' : '') + m + (h >= 12 ? 'pm' : 'am');
    var ds = d.getDate() + ' ' + MONTHS[d.getMonth()] + ', ' + d.getFullYear(), a, i;
    a = D.querySelectorAll('.dp-clock'); for (i = 0; i < a.length; i++) if (a[i].textContent !== t) a[i].textContent = t;
    a = D.querySelectorAll('.dp-date'); for (i = 0; i < a.length; i++) if (a[i].textContent !== ds) a[i].textContent = ds;
  }
  D.addEventListener('click', onClick);
  setInterval(tick, 15000);

  W.addEventListener('mousemove', onMove, { passive: true });
  D.addEventListener('mouseleave', onLeave);
  W.addEventListener('blur', onLeave);
  W.addEventListener('resize', function () { mobile = Math.min(W.innerWidth, W.innerHeight) < 700; resize(); placeCord(); });
  D.addEventListener('scroll', onScroll, true);
  D.addEventListener('visibilitychange', function () { if (!D.hidden) { lastT = 0; loop(); } });
  try { new MutationObserver(scan).observe(D.body, { childList: true, subtree: true }); } catch (e) { }
  setInterval(function () { if (ensure() && canvas.style.display !== 'none') { /* keep elements attached */ } }, 2500);
  W.__dpfx = { update: update, version: 1 };
})();
"""


def fx_script():
    """The JavaScript that runs inside the app page (exposed for tests)."""
    return _JS


def fx_html(bg=DEFAULT_BG, accent="#00b4d8", effects=True, dark=True, opacity=None):
    """HTML for a zero-height component that installs / updates the effects."""
    if bg not in BACKGROUNDS:
        bg = DEFAULT_BG
    cfg = {"bg": bg, "accent": str(accent), "effects": bool(effects), "dark": bool(dark)}
    if opacity is not None:
        cfg["opacity"] = float(opacity)
    code = json.dumps(_JS).replace("</", "<\\/")
    return ("<script>(function(){try{var P=window.parent,D=P.document,c=" + json.dumps(cfg) + ";"
            "if(P.__dpfx){P.__dpfx.update(c);return;}"
            "var s=D.createElement('script');s.id='dpfx-script';s.text=" + code + ";D.head.appendChild(s);"
            "if(P.__dpfx){P.__dpfx.update(c);}}catch(e){}})();</script>")
