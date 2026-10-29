/* Canlı sekme: FotMob'dan anlık veri çeker, canlı gol modelini (src/live_model.py ile aynı formül)
   telefonda hesaplar. Her 60 saniyede yenilenir. */
(function () {
  const FM = "https://www.fotmob.com/api/data/";
  const COUNTRIES = ["TUR", "ENG", "ESP", "ITA", "GER", "FRA", "NED", "POR", "BEL", "GRE", "SCO"];
  const SKIP = /women|kadın|u1[789]|u2[013]|youth|reserve|premier league 2|primavera|regionalliga|national league/i;
  const UEFA = /champions league|europa league|conference league/i;
  const DEF = { T0: 600, beta: 0.8, trail: 1.15, lead: 1, red_self: 0.75, red_opp: 1.25, stoppage1: 3, stoppage2: 8, window: 10, g: 0.3, scale: 1, baski_isareti: 1 };
  let P = { ...DEF }, timer = null, lastRun = null, busy = false, cache = {}, rootEl = null;

  const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const pct = x => Math.round(100 * x);
  const norm = s => String(s || "").normalize("NFKD").replace(/[̀-ͯ]/g, "").replace(/ı/g, "i").toLowerCase()
    .replace(/\b(fc|cf|sc|ac|afc|sk|fk|as|ss|cd|ud|rc|sv|vfb|vfl|tsg)\b/g, " ").replace(/[^a-z0-9]/g, "");

  // ---- Model (live_model.py ile aynı) ----
  function remaining(minute, half) {
    if (half === 1) return Math.max(0.5, 45 - minute) + P.stoppage1 * (minute < 45 ? 1 : 0.5) + 45 + P.stoppage2;
    return Math.max(0.5, 90 - minute) + (minute < 90 ? P.stoppage2 : P.stoppage2 / 2);
  }
  const W = (u, total, g) => u + g * (u * u / (2 * total) - 0.5 * u);
  function rates(lh, la, minute, half, xh, xa, gh, ga, rh_, ra_, mom) {
    const total = 90 + P.stoppage1 + P.stoppage2, g = P.g || 0, sc = P.scale || 1;
    const bh = sc * lh / total, ba = sc * la / total;
    const e = half === 1 ? Math.max(minute, 0.5) : minute + P.stoppage1;
    const R = remaining(minute, half), end = e + R, soFar = W(e, total, g);
    const fh = P.T0 < 1e6 ? (P.T0 * bh + xh) / (P.T0 * bh + bh * soFar) : 1;
    const fa = P.T0 < 1e6 ? (P.T0 * ba + xa) / (P.T0 * ba + ba * soFar) : 1;
    let rh = bh * fh, ra = ba * fa;
    const d = gh - ga;
    if (d < 0) { rh *= P.trail; ra *= P.lead; } else if (d > 0) { rh *= P.lead; ra *= P.trail; }
    rh *= Math.pow(P.red_self, rh_) * Math.pow(P.red_opp, ra_);
    ra *= Math.pow(P.red_self, ra_) * Math.pow(P.red_opp, rh_);
    const w = Math.min(P.window, R);
    const Wn = W(e + w, total, g) - soFar, Wr = W(end, total, g) - W(e + w, total, g);
    const nh = rh * Math.exp(P.beta * mom) * Wn, na = ra * Math.exp(-P.beta * mom) * Wn;
    return { rem_h: nh + rh * Wr, rem_a: na + ra * Wr, next_h: nh, next_a: na, R };
  }
  const fact = n => (n < 2 ? 1 : n * fact(n - 1));
  const pois = (k, l) => Math.exp(-l) * Math.pow(l, k) / fact(k);
  function outputs(r, gh, ga) {
    const lam = r.rem_h + r.rem_a, share = lam > 0 ? r.rem_h / lam : 0.5;
    const res = { "1": 0, X: 0, "2": 0 }, tot = {};
    for (let i = 0; i <= 10; i++) for (let j = 0; j <= 10; j++) {
      const pr = pois(i, r.rem_h) * pois(j, r.rem_a), fh = gh + i, fa = ga + j;
      res[fh > fa ? "1" : fh === fa ? "X" : "2"] += pr;
      tot[fh + fa] = (tot[fh + fa] || 0) + pr;
    }
    const cur = gh + ga, over = l => Object.entries(tot).filter(([k]) => +k > l).reduce((s, [, v]) => s + v, 0);
    return {
      p_goal: 1 - Math.exp(-lam), p_next10: 1 - Math.exp(-(r.next_h + r.next_a)),
      next_home: (1 - Math.exp(-lam)) * share, next_away: (1 - Math.exp(-lam)) * (1 - share),
      rem_h: r.rem_h, rem_a: r.rem_a, sonuc: res, ust: [[cur + 0.5, over(cur + 0.5)], [cur + 1.5, over(cur + 1.5)], [cur + 2.5, over(cur + 2.5)]],
    };
  }

  // ---- Veri ----
  async function getJSON(url) {
    const r = await fetch(url, { cache: "no-store" });
    if (!r.ok) throw new Error(r.status);
    return r.json();
  }
  function ymd(d) { return d.getFullYear() + String(d.getMonth() + 1).padStart(2, "0") + String(d.getDate()).padStart(2, "0"); }
  function wanted(lg) {
    const name = lg.name || "";
    if (SKIP.test(name)) return false;
    if (COUNTRIES.includes(lg.ccode)) return true;
    return lg.ccode === "INT" && UEFA.test(name);
  }
  function parseClock(st, header) {
    const s = (st.liveTime && st.liveTime.short) || "";
    const second = !!(header?.status?.halfs?.secondHalfStarted);
    if (/HT|DA/i.test(s)) return { minute: 45, half: 2, label: "Devre arası" };
    const m = s.match(/(\d+)(?:\s*\+\s*(\d+))?/);
    let minute = m ? +m[1] : 1;
    const half = second || minute > 45 ? 2 : 1;
    return { minute: Math.min(minute, 90), half, label: s.replace(/[‎’']/g, "") + "'" };
  }
  function prior(home, away) {
    const list = (typeof DATA !== "undefined" && DATA && DATA.maclar) || [];
    const H = norm(home), A = norm(away);
    const same = (x, y) => x && y && (x === y || (x.length >= 4 && y.length >= 4 && (x.includes(y) || y.includes(x))));
    const m = list.find(r => (same(norm(r.ev_ad || r.ev), H) || same(norm(r.ev), H)) && (same(norm(r.dep_ad || r.dep), A) || same(norm(r.dep), A)));
    if (m) return { lh: m.beklenen_gol.ev, la: m.beklenen_gol.dep, rapor: m };
    return { lh: 1.4, la: 1.15, rapor: null };
  }
  function statsOf(det) {
    const want = { "Total shots": "sut", "Shots on target": "isabetli", "Expected goals (xG)": "xg", "Big chances": "firsat",
      "Corners": "korner", "Touches in opposition box": "ceza", "Ball possession": "topla" };
    const out = {};
    const per = det?.content?.stats?.Periods?.All?.stats || [];
    per.forEach(g => (g.stats || []).forEach(s => { const k = want[s.title]; if (k && !out[k] && s.stats && s.stats[0] != null) out[k] = s.stats; }));
    return out;
  }
  function analyse(m, det) {
    const header = det.header || {};
    const homeId = det?.general?.homeTeam?.id;
    const clock = parseClock(m.status || {}, header);
    const gh = +(header.teams?.[0]?.score ?? m.home.score ?? 0), ga = +(header.teams?.[1]?.score ?? m.away.score ?? 0);
    let xh = 0, xa = 0;
    (det?.content?.shotmap?.shots || []).forEach(s => { if (s.teamId === homeId) xh += s.expectedGoals || 0; else xa += s.expectedGoals || 0; });
    let rh = 0, ra = 0;
    (det?.content?.matchFacts?.events?.events || []).forEach(e => {
      if (e.type === "Card" && (e.card === "Red" || e.card === "YellowRed")) { if (e.isHome) rh++; else ra++; }
    });
    const mom = (det?.content?.momentum?.main?.data || []);
    const nowMin = clock.half === 2 ? clock.minute : clock.minute;
    const recent = mom.filter(d => d.minute <= nowMin && d.minute > nowMin - 10).map(d => d.value);
    const momAvg = recent.length ? P.baski_isareti * recent.reduce((a, b) => a + b, 0) / recent.length / 100 : 0;
    const pri = prior(m.home.name, m.away.name);
    const r = rates(pri.lh, pri.la, clock.minute, clock.half, xh, xa, gh, ga, rh, ra, momAvg);
    return { clock, gh, ga, xh, xa, rh, ra, momAvg, mom: mom.filter(d => d.minute <= nowMin).slice(-25), pri, out: outputs(r, gh, ga), stats: statsOf(det) };
  }

  // ---- Görünüm ----
  function bar(vals) {
    if (!vals.length) return "";
    const w = 300, h = 46, bw = w / 25;
    return `<svg viewBox="0 0 ${w} ${h}" width="100%" height="${h}" preserveAspectRatio="none" aria-label="Baskı grafiği">
      <line x1="0" y1="${h / 2}" x2="${w}" y2="${h / 2}" stroke="var(--line)"/>
      ${vals.map((d, i) => { const v = P.baski_isareti * d.value / 100, bh = Math.abs(v) * (h / 2 - 2);
        return `<rect x="${i * bw + 1}" y="${v > 0 ? h / 2 - bh : h / 2}" width="${bw - 2}" height="${Math.max(bh, 0.5)}" rx="1.5" fill="${v > 0 ? "var(--home)" : "var(--away)"}"/>`; }).join("")}
    </svg>`;
  }
  function statRow(label, v) {
    if (!v) return "";
    return `<tr><td>${v[0]}</td><td>${label}</td><td>${v[1]}</td></tr>`;
  }
  function card(m, a) {
    const o = a.out, H = esc(m.home.name), A = esc(m.away.name);
    const press = Math.abs(a.momAvg) >= 0.3 ? `<div class="press ${a.momAvg > 0 ? "h" : "a"}">🔥 ${a.momAvg > 0 ? H : A} son 10 dakikadır baskı kuruyor</div>` : "";
    const red = (a.rh || a.ra) ? `<span class="tag derbi">🟥 ${a.rh ? H + " " + a.rh : ""}${a.rh && a.ra ? " · " : ""}${a.ra ? A + " " + a.ra : ""}</span>` : "";
    return `<div class="card live">
      <div class="meta"><span>${esc(m._lig)} ${red}</span><b class="min">${esc(a.clock.label)}</b></div>
      <div class="teams"><div class="t">${H}</div><div class="score">${a.gh} – ${a.ga}</div><div class="t r">${A}</div></div>
      <div class="kpis">
        <div><b>%${pct(o.p_goal)}</b><span>Maçta yeni gol</span></div>
        <div><b>%${pct(o.p_next10)}</b><span>Sonraki 10 dk gol</span></div>
        <div><b>%${pct(Math.max(o.next_home, o.next_away) / Math.max(o.p_goal, 1e-6))}</b><span>Sonraki gol: ${o.next_home >= o.next_away ? H : A}</span></div>
      </div>
      ${press}
      <div class="mom"><div class="lab"><span>${H} baskısı</span><span>son 25 dk</span><span>${A} baskısı</span></div>${bar(a.mom)}</div>
      <details><summary>Detay</summary>
        <table style="margin-top:6px">${statRow("xG", [a.xh.toFixed(2), a.xa.toFixed(2)])}${statRow("Şut", a.stats.sut)}${statRow("İsabetli şut", a.stats.isabetli)}
          ${statRow("Büyük fırsat", a.stats.firsat)}${statRow("Ceza sahasında top", a.stats.ceza)}${statRow("Korner", a.stats.korner)}${statRow("Topla oynama %", a.stats.topla)}</table>
        <table style="margin-top:10px"><tr><th>Şu anki tahmin</th><th></th></tr>
          <tr><td>Maç sonucu 1 / X / 2</td><td>%${pct(o.sonuc["1"])} / %${pct(o.sonuc.X)} / %${pct(o.sonuc["2"])}</td></tr>
          ${o.ust.map(([l, p]) => `<tr><td>Toplam ${l} Üst</td><td>%${pct(p)}</td></tr>`).join("")}
          <tr><td>Kalan süre beklenen gol</td><td>${o.rem_h.toFixed(2)} – ${o.rem_a.toFixed(2)}</td></tr>
        </table>
        <p class="note">${a.pri.rapor ? "Maç öncesi beklenti: bültendeki analiz (" + a.pri.lh + " – " + a.pri.la + ")." : "Bu maç bültende yok; maç öncesi beklenti için lig ortalaması kullanıldı, güven düşük."}</p>
      </details>
    </div>`;
  }

  async function refresh() {
    if (busy || !rootEl) return;
    busy = true;
    const box = rootEl.querySelector("#liveList"), st = rootEl.querySelector("#liveStamp");
    try {
      try { const pj = await getJSON("data/live_params.json?" + Date.now()); P = { ...DEF, ...pj }; } catch (e) {}
      const day = await getJSON(FM + "matches?date=" + ymd(new Date()));
      const live = [], soon = [];
      (day.leagues || []).filter(wanted).forEach(lg => (lg.matches || []).forEach(m => {
        m._lig = lg.name;
        const s = m.status || {};
        if (s.started && !s.finished && !s.cancelled) live.push(m);
        else if (!s.started && !s.cancelled) soon.push(m);
      }));
      if (!live.length) {
        soon.sort((a, b) => (a.status.utcTime || "").localeCompare(b.status.utcTime || ""));
        box.innerHTML = `<div class="empty">Takip edilen liglerde şu an canlı maç yok.</div>` +
          (soon.length ? `<div class="sec"><h3>Bugün başlayacaklar</h3><table>${soon.slice(0, 15).map(m => `<tr><td>${new Date(m.status.utcTime).toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" })}</td><td style="text-align:left">${esc(m.home.name)} – ${esc(m.away.name)}<div style="color:var(--muted);font-size:11px">${esc(m._lig)}</div></td></tr>`).join("")}</table></div>` : "");
      } else {
        const results = [];
        for (let i = 0; i < live.length; i += 4) {
          const part = await Promise.all(live.slice(i, i + 4).map(async m => {
            try { const det = await getJSON(FM + "matchDetails?matchId=" + m.id); cache[m.id] = det; return [m, analyse(m, det)]; }
            catch (e) { return cache[m.id] ? [m, analyse(m, cache[m.id])] : null; }
          }));
          results.push(...part.filter(Boolean));
        }
        results.sort((x, y) => y[1].out.p_next10 - x[1].out.p_next10);
        box.innerHTML = results.map(([m, a]) => card(m, a)).join("");
      }
      lastRun = new Date();
      st.textContent = "Son güncelleme " + lastRun.toLocaleTimeString("tr-TR") + " · 60 sn'de bir yenilenir";
    } catch (e) {
      st.textContent = "Canlı veri alınamadı (" + e.message + "). Birazdan tekrar denenecek.";
    }
    busy = false;
  }

  window.Canli = {
    render(main) {
      rootEl = main;
      main.innerHTML = `<style>
        .card.live .score{font:700 30px "Barlow Condensed",sans-serif;text-align:center;min-width:64px}
        .card.live .min{color:var(--accent)}
        .kpis{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-top:10px}
        .kpis div{background:var(--panel2);border:1px solid var(--line);border-radius:10px;padding:8px;text-align:center}
        .kpis b{display:block;font:700 20px "Barlow Condensed",sans-serif;color:var(--accent)}
        .kpis span{font-size:11px;color:var(--muted)}
        .press{margin-top:8px;font-size:13px;padding:6px 10px;border-radius:8px;background:#2a2410;color:var(--mid)}
        .mom{margin-top:10px}.mom .lab{display:flex;justify-content:space-between;font-size:10px;color:var(--muted);margin-bottom:2px}
        .card.live details{margin-top:8px}.card.live summary{cursor:pointer;color:var(--muted);font-size:13px}
        .card.live td{font-size:13px}.note{color:var(--muted);font-size:12px;margin-top:8px}
      </style>
      <div class="bar"><div style="display:flex;justify-content:space-between;align-items:center;gap:8px">
        <span id="liveStamp" style="color:var(--muted);font-size:12px">Yükleniyor…</span>
        <button class="back" id="liveRefresh">Yenile</button></div></div>
      <div id="liveList"><div class="empty">Canlı maçlar yükleniyor…</div></div>
      <div class="foot">Veri: FotMob. Olasılıklar canlı istatistik modelinden gelir, kesinlik içermez. Model Testi sekmesinde geçmiş başarısı var.</div>`;
      main.querySelector("#liveRefresh").onclick = refresh;
      refresh();
      clearInterval(timer);
      timer = setInterval(() => { if (document.visibilityState === "visible" && rootEl && document.body.contains(rootEl.querySelector("#liveList"))) refresh(); }, 60000);
    },
    stop() { clearInterval(timer); rootEl = null; },
  };
})();
