/* ══════════════════════════════════════════════════════════════
   Panoptes FX — animated AI network background + pipeline flow
   Pure canvas, no deps. Respects prefers-reduced-motion.
   ══════════════════════════════════════════════════════════════ */
(function () {
  "use strict";

  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ── Network background ─────────────────────────────────── */
  const canvas = document.getElementById("fx-canvas");
  if (canvas && !reduce) {
    const ctx = canvas.getContext("2d");
    let W = 0, H = 0, dpr = Math.min(window.devicePixelRatio || 1, 2);
    let nodes = [];
    let pulses = [];
    const CYAN = "53, 230, 255";
    const VIOLET = "150, 123, 255";
    const AMBER = "255, 179, 71";

    function resize() {
      W = window.innerWidth;
      H = window.innerHeight;
      canvas.width = Math.floor(W * dpr);
      canvas.height = Math.floor(H * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      buildNodes();
    }

    function buildNodes() {
      const count = Math.min(72, Math.max(28, Math.round((W * H) / 26000)));
      nodes = [];
      for (let i = 0; i < count; i++) {
        nodes.push({
          x: Math.random() * W,
          y: Math.random() * H,
          vx: (Math.random() - 0.5) * 0.28,
          vy: (Math.random() - 0.5) * 0.28,
          r: 1 + Math.random() * 2,
          hot: Math.random() < 0.12, // a few "author/source" nodes glow brighter
        });
      }
    }

    const LINK_DIST = 150;

    function spawnPulse() {
      if (pulses.length > 22 || nodes.length < 2) return;
      const a = (Math.random() * nodes.length) | 0;
      let b = (Math.random() * nodes.length) | 0;
      if (a === b) b = (b + 1) % nodes.length;
      const dx = nodes[a].x - nodes[b].x, dy = nodes[a].y - nodes[b].y;
      if (Math.hypot(dx, dy) > LINK_DIST * 1.6) return;
      pulses.push({
        a, b, t: 0,
        speed: 0.006 + Math.random() * 0.012,
        color: Math.random() < 0.28 ? AMBER : CYAN,
      });
    }

    let frame = 0;
    function draw() {
      ctx.clearRect(0, 0, W, H);

      // edges
      for (let i = 0; i < nodes.length; i++) {
        const n = nodes[i];
        n.x += n.vx; n.y += n.vy;
        if (n.x < -20) n.x = W + 20; else if (n.x > W + 20) n.x = -20;
        if (n.y < -20) n.y = H + 20; else if (n.y > H + 20) n.y = -20;

        for (let j = i + 1; j < nodes.length; j++) {
          const m = nodes[j];
          const dx = n.x - m.x, dy = n.y - m.y;
          const d = Math.hypot(dx, dy);
          if (d < LINK_DIST) {
            const alpha = (1 - d / LINK_DIST) * 0.22;
            ctx.strokeStyle = `rgba(${CYAN}, ${alpha})`;
            ctx.lineWidth = 0.6;
            ctx.beginPath();
            ctx.moveTo(n.x, n.y);
            ctx.lineTo(m.x, m.y);
            ctx.stroke();
          }
        }
      }

      // nodes
      for (const n of nodes) {
        const col = n.hot ? VIOLET : CYAN;
        const glow = n.hot ? 14 : 7;
        ctx.beginPath();
        ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(${col}, 0.9)`;
        ctx.shadowBlur = glow;
        ctx.shadowColor = `rgba(${col}, 0.8)`;
        ctx.fill();
        ctx.shadowBlur = 0;
      }

      // data pulses travelling along edges
      for (let k = pulses.length - 1; k >= 0; k--) {
        const p = pulses[k];
        p.t += p.speed;
        if (p.t >= 1) { pulses.splice(k, 1); continue; }
        const na = nodes[p.a], nb = nodes[p.b];
        if (!na || !nb) { pulses.splice(k, 1); continue; }
        const x = na.x + (nb.x - na.x) * p.t;
        const y = na.y + (nb.y - na.y) * p.t;
        ctx.beginPath();
        ctx.arc(x, y, 2.1, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(${p.color}, 0.95)`;
        ctx.shadowBlur = 10;
        ctx.shadowColor = `rgba(${p.color}, 0.9)`;
        ctx.fill();
        ctx.shadowBlur = 0;
      }

      frame++;
      if (frame % 8 === 0) spawnPulse();
      requestAnimationFrame(draw);
    }

    window.addEventListener("resize", () => {
      clearTimeout(window.__fxrz);
      window.__fxrz = setTimeout(resize, 150);
    });
    resize();
    requestAnimationFrame(draw);
  }

  /* ── Neural pipeline hero ───────────────────────────────
     Dense input wall -> wavy stream bundle that disperses in the
     middle ("lost in the middle") -> re-condensed output wall.
     ───────────────────────────────────────────────────────── */
  const neural = document.getElementById("neural-canvas");
  if (neural && !reduce) {
    const nx = neural.getContext("2d");
    let W = 0, H = 0, cy = 0, inX = 0, outX = 0, wallH = 0;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);

    const STREAMS = 28;
    let streams = [];
    let travellers = [];
    let wallDots = [];
    let ribbonGrad = null;
    let t0 = performance.now();

    function layout() {
      W = neural.clientWidth;
      H = neural.clientHeight;
      neural.width = Math.floor(W * dpr);
      neural.height = Math.floor(H * dpr);
      nx.setTransform(dpr, 0, 0, dpr, 0, 0);
      cy = H * 0.5;
      inX = Math.max(70, W * 0.1);
      outX = Math.min(W - 70, W * 0.9);
      wallH = H * 0.62;
      buildStreams();
      buildWalls();
      // ribbons are bright at the walls and nearly vanish mid-pipeline
      ribbonGrad = nx.createLinearGradient(inX, 0, outX, 0);
      ribbonGrad.addColorStop(0.00, "rgba(53, 230, 255, 0.26)");
      ribbonGrad.addColorStop(0.30, "rgba(53, 230, 255, 0.07)");
      ribbonGrad.addColorStop(0.50, "rgba(53, 230, 255, 0.015)");
      ribbonGrad.addColorStop(0.70, "rgba(53, 230, 255, 0.07)");
      ribbonGrad.addColorStop(1.00, "rgba(53, 230, 255, 0.26)");
    }

    function buildStreams() {
      streams = [];
      for (let s = 0; s < STREAMS; s++) {
        const f = s / (STREAMS - 1) - 0.5;          // -0.5 .. 0.5
        streams.push({
          y0: cy + f * wallH,
          y1: cy + (f * 0.85 + (Math.random() - 0.5) * 0.12) * wallH,
          amp: 14 + Math.random() * 46,
          freq: 1.1 + Math.random() * 1.9,
          phase: Math.random() * Math.PI * 2,
          drift: 0.25 + Math.random() * 0.5,
        });
      }
      travellers = [];
      for (let i = 0; i < 520; i++) {
        travellers.push({
          s: (Math.random() * STREAMS) | 0,
          t: Math.random(),
          sp: 0.0013 + Math.random() * 0.0034,
          r: 0.7 + Math.random() * 1.5,
          warm: Math.random() < 0.09,
        });
      }
    }

    function buildWalls() {
      wallDots = [];
      // particle clouds fanning outward from each wall
      for (const side of [-1, 1]) {
        const baseX = side < 0 ? inX : outX;
        for (let i = 0; i < 460; i++) {
          // cubic bias => dots crowd tightly against the wall, thinning outward
          const k = Math.pow(Math.random(), 3);
          const spread = k * (W * 0.07);
          wallDots.push({
            x: baseX + side * -spread,
            y: cy + (Math.random() - 0.5) * wallH * (1.02 - k * 0.45),
            r: 0.6 + Math.random() * 1.7,
            a: 0.35 + (1 - k) * 0.6,
            ph: Math.random() * Math.PI * 2,
          });
        }
      }
    }

    // y position along a stream at progress t
    function streamY(st, t, time) {
      const env = Math.sin(Math.PI * Math.min(1, Math.max(0, t)));
      const base = st.y0 + (st.y1 - st.y0) * t;
      return base + st.amp * env * Math.sin(t * st.freq * Math.PI * 2 + st.phase + time * st.drift);
    }

    // dispersion factor — peaks mid-pipeline for the scattered look
    function mid(t) {
      return Math.exp(-Math.pow((t - 0.5) / 0.17, 2));
    }

    function render(now) {
      const time = (now - t0) / 1000;
      nx.clearRect(0, 0, W, H);

      // ── stream ribbons (one gradient stroke each: bright at walls, gone mid)
      nx.strokeStyle = ribbonGrad;
      nx.lineWidth = 0.75;
      for (const st of streams) {
        nx.beginPath();
        for (let i = 0; i <= 56; i++) {
          const t = i / 56;
          const x = inX + (outX - inX) * t;
          const y = streamY(st, t, time);
          i === 0 ? nx.moveTo(x, y) : nx.lineTo(x, y);
        }
        nx.stroke();
      }

      // ── travelling data particles
      for (const p of travellers) {
        const m0 = mid(p.t);
        // accelerate through the middle => genuinely sparser there
        p.t += p.sp * (1 + m0 * 3.4);
        if (p.t > 1) { p.t = 0; p.s = (Math.random() * STREAMS) | 0; }
        const st = streams[p.s];
        if (!st) continue;
        const m = mid(p.t);
        const x = inX + (outX - inX) * p.t;
        // scatter + fade through the middle
        const y = streamY(st, p.t, time) + (Math.random() - 0.5) * m * 40;
        const alpha = 0.95 - m * 0.72;
        const col = p.warm ? "255, 179, 71" : "53, 230, 255";
        nx.beginPath();
        nx.arc(x, y, p.r, 0, Math.PI * 2);
        nx.fillStyle = `rgba(${col}, ${alpha})`;
        nx.shadowBlur = 7;
        nx.shadowColor = `rgba(${col}, ${alpha})`;
        nx.fill();
      }
      nx.shadowBlur = 0;

      // ── wall particle clouds
      for (const d of wallDots) {
        const tw = 0.75 + 0.25 * Math.sin(time * 2 + d.ph);
        nx.beginPath();
        nx.arc(d.x, d.y, d.r, 0, Math.PI * 2);
        nx.fillStyle = `rgba(53, 230, 255, ${d.a * tw})`;
        nx.fill();
      }

      // ── bright input / output walls
      for (const x of [inX, outX]) {
        const g = nx.createLinearGradient(0, cy - wallH / 2, 0, cy + wallH / 2);
        g.addColorStop(0, "rgba(53, 230, 255, 0.05)");
        g.addColorStop(0.15, "rgba(90, 240, 255, 0.75)");
        g.addColorStop(0.5, "rgba(215, 253, 255, 1)");
        g.addColorStop(0.85, "rgba(90, 240, 255, 0.75)");
        g.addColorStop(1, "rgba(53, 230, 255, 0.05)");
        nx.fillStyle = g;
        nx.shadowBlur = 46;
        nx.shadowColor = "rgba(53, 230, 255, 1)";
        nx.fillRect(x - 5, cy - wallH / 2, 10, wallH);
        nx.fillRect(x - 5, cy - wallH / 2, 10, wallH); // second pass = hotter core
        nx.shadowBlur = 0;
      }

      requestAnimationFrame(render);
    }

    window.addEventListener("resize", () => {
      clearTimeout(window.__nrz);
      window.__nrz = setTimeout(layout, 150);
    });
    layout();
    requestAnimationFrame(render);
  }

  /* ── Pipeline flow controller ───────────────────────────── */
  const pipeline = document.getElementById("pipeline");
  if (pipeline) {
    const stages = Array.from(pipeline.querySelectorAll(".pipe-stage"));
    let active = 0;
    let cycle = null;

    function setActive(i) {
      stages.forEach((s, idx) => s.classList.toggle("active", idx === i));
    }

    function isBusy() {
      const rb = document.getElementById("radar-timer-box");
      const db = document.getElementById("discover-timer-box");
      return (rb && rb.classList.contains("running")) ||
             (db && db.classList.contains("running"));
    }

    function startFlow() {
      if (cycle) return;
      pipeline.classList.add("flowing");
      cycle = setInterval(() => {
        active = (active + 1) % stages.length;
        setActive(active);
      }, 700);
    }
    function stopFlow() {
      if (cycle) { clearInterval(cycle); cycle = null; }
      pipeline.classList.remove("flowing");
      // idle ambient: gently sweep the first + last as "ready"
      setActive(-1);
      idleSweep();
    }

    let idleTimer = null, idleIdx = 0;
    function idleSweep() {
      if (reduce) { setActive(0); return; }
      if (idleTimer) clearInterval(idleTimer);
      idleTimer = setInterval(() => {
        idleIdx = (idleIdx + 1) % stages.length;
        setActive(idleIdx);
      }, 1400);
    }

    // watch busy state
    setInterval(() => {
      if (isBusy()) {
        if (idleTimer) { clearInterval(idleTimer); idleTimer = null; }
        startFlow();
      } else if (cycle) {
        stopFlow();
      }
    }, 400);

    idleSweep();
  }

  /* ── Panel spotlight follows cursor ─────────────────────── */
  if (!reduce) {
    document.addEventListener("mousemove", (e) => {
      const panel = e.target.closest && e.target.closest(".panel");
      if (!panel) return;
      const rect = panel.getBoundingClientRect();
      panel.style.setProperty("--mx", `${e.clientX - rect.left}px`);
      panel.style.setProperty("--my", `${e.clientY - rect.top}px`);
    });
  }
})();
