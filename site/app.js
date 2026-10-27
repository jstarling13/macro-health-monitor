/* Macro Health Monitor — front end. Reads data.json (built by `python -m mhd.export`). */
"use strict";

const S = { d: null, charts: [], route: "" };
const FKEYS = ["gdp", "fed", "inflation", "earnings", "usd", "credit"];
const FCOL = { gdp: "--s1", fed: "--s2", inflation: "--s3", earnings: "--s4", usd: "--s5", credit: "--s6" };
const v = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const $ = (sel, el = document) => el.querySelector(sel);
const h = (tag, attrs = {}, ...kids) => {
  const e = document.createElement(tag);
  for (const [k, val] of Object.entries(attrs || {})) {
    if (k === "class") e.className = val;
    else if (k === "html") e.innerHTML = val;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), val);
    else if (val !== undefined && val !== null && val !== false) e.setAttribute(k, val);
  }
  for (const k of kids.flat()) if (k !== null && k !== undefined && k !== false) e.append(k.nodeType ? k : document.createTextNode(k));
  return e;
};

/* ---------------------------------------------------------------- format */
const isNum = (x) => typeof x === "number" && isFinite(x);
const f0 = (x) => (isNum(x) ? x.toFixed(0) : "–");
const f1 = (x) => (isNum(x) ? x.toFixed(1) : "–");
const f2 = (x) => (isNum(x) ? x.toFixed(2) : "–");
const pct = (x, d = 1) => (isNum(x) ? (x * 100).toFixed(d) + "%" : "–");
const sgn = (x, d = 1, suf = "") => (isNum(x) ? (x > 0 ? "+" : x < 0 ? "−" : "") + Math.abs(x).toFixed(d) + suf : "–");
const cls = (x) => (isNum(x) ? (x > 0 ? "pos" : x < 0 ? "neg" : "") : "");
const big = (x) => (isNum(x) ? x.toLocaleString("en-US", { maximumFractionDigits: 2 }) : "–");
const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const dlong = (s) => { if (!s) return "–"; const [y, m, d] = s.split("-").map(Number); return d ? `${MON[m - 1]} ${d}, ${y}` : `${MON[m - 1]} ${y}`; };
const ym = (s) => { const [y, m] = s.split("-").map(Number); return `${MON[m - 1]} ${y}`; };
const qtr = (s) => { const [y, m] = s.split("-").map(Number); return `Q${Math.floor((m - 1) / 3) + 1} ${y}`; };
const asOfLabel = (p) => (["GDP", "CP", "DRT"].some((k) => p.series.startsWith(k)) || p.series === "A191RL1Q225SBEA" ? qtr(p.as_of) : (p.series.startsWith("D") || p.series === "TOTBKCR") ? dlong(p.as_of) : ym(p.as_of));
const unitFmt = (val, unit) => (unit === "pp" ? sgn(val, 2, " pp") : unit === "%" ? f2(val) + "%" : f2(val));

function gradeInfo(g) {
  return { A: ["--good", "Strong"], B: ["--good", "Healthy"], C: ["--neutral", "Neutral"], D: ["--warning", "Weak"], F: ["--critical", "Stressed"] }[g] || ["--neutral", "No data"];
}
function gradePill(g, word) {
  const [c, w] = gradeInfo(g);
  return h("span", { class: "grade" }, h("i", { style: `background:var(${c})` }), `${g} · ${word || w}`);
}
const gradeOf = (s) => (!isNum(s) ? "–" : s >= 70 ? "A" : s >= 60 ? "B" : s >= 45 ? "C" : s >= 35 ? "D" : "F");

/* ------------------------------------------------------------------ csv */
function downloadCSV(name, cols, rows) {
  const esc = (x) => { const s = x === null || x === undefined ? "" : String(x); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
  const lines = [cols.map((c) => esc(c.label)).join(",")].concat(rows.map((r) => cols.map((c) => esc(r[c.k])).join(",")));
  const a = h("a", { href: URL.createObjectURL(new Blob([lines.join("\n")], { type: "text/csv" })), download: name });
  document.body.append(a); a.click(); a.remove();
}
function table(cols, rows, { onRow, rowClass } = {}) {
  const t = h("table", { class: "t" });
  t.append(h("thead", {}, h("tr", {}, cols.map((c) => h("th", { class: c.r ? "r" : "" }, c.label)))));
  const tb = h("tbody");
  for (const r of rows) {
    const tr = h("tr", { class: (onRow ? "click " : "") + (rowClass ? rowClass(r) : "") });
    if (onRow) tr.addEventListener("click", () => onRow(r));
    for (const c of cols) {
      const val = c.fmt ? c.fmt(r[c.k], r) : r[c.k];
      const td = h("td", { class: (c.r ? "r " : "") + (c.cls ? c.cls(r[c.k], r) : "") });
      if (val && val.nodeType) td.append(val); else td.textContent = val ?? "–";
      tr.append(td);
    }
    tb.append(tr);
  }
  t.append(tb);
  return t;
}

/* ------------------------------------------------------------------ card */
function srcFoot(ids, note) {
  const src = S.d.sources.filter((s) => ids.includes(s.id));
  const parts = src.map((s) => [h("a", { href: `#sources/${s.id}` }, s.id), ` (${s.source || "FRED"})`]);
  const left = h("span", {}, "Source: ", ...parts.flatMap((p, i) => (i ? ["; ", ...p] : p)));
  return h("div", { class: "card-foot" }, left, note ? h("span", {}, note) : null);
}
/** A chart card with a "Data" table toggle and CSV export. */
function card({ title, sub, tools = [], chart, size = "", table: tbl, csv, sources = [], note, body }) {
  const c = h("section", { class: "card" });
  const toolsEl = h("div", { class: "card-tools" }, ...tools);
  let wrap;
  if (tbl) {
    wrap = h("div", { class: "data-wrap" });
    const btn = h("button", { class: "btn", "aria-pressed": "false", title: "Show the numbers behind this chart" }, "Data");
    btn.onclick = () => {
      const open = !wrap.classList.contains("open");
      if (open && !wrap.firstChild) wrap.append(table(tbl.cols, tbl.rows()));
      wrap.classList.toggle("open", open); btn.setAttribute("aria-pressed", String(open));
    };
    toolsEl.append(btn, h("button", { class: "btn", title: "Download CSV", onclick: () => downloadCSV(csv || "data.csv", tbl.cols, tbl.rows()) }, "CSV"));
  }
  c.append(h("div", { class: "card-head" }, h("div", {}, h("h3", { class: "card-title" }, title), sub ? h("div", { class: "card-sub" }, sub) : null), toolsEl));
  const b = h("div", { class: "card-body" });
  if (body) b.append(body);
  let el = null;
  if (chart) { el = h("div", { class: "chart " + size }); b.append(el); }
  if (wrap) b.append(wrap);
  c.append(b);
  if (sources.length || note) c.append(srcFoot(sources, note));
  if (chart) queueMicrotask(() => mount(el, chart));
  c.chartEl = el;
  return c;
}
function mount(el, build) {
  const ch = echarts.init(el, null, { renderer: "canvas" });
  ch.setOption(build());
  el._chart = ch;
  S.charts.push(ch);
  return ch;
}

/* --------------------------------------------------------- chart basics */
function base(extra = {}) {
  const ax = { axisLine: { lineStyle: { color: v("--border") } }, axisTick: { show: false }, axisLabel: { color: v("--text-3"), fontSize: 11 }, splitLine: { lineStyle: { color: v("--grid") } } };
  return {
    animation: false,
    textStyle: { fontFamily: "Inter, system-ui, sans-serif", color: v("--text-2") },
    grid: { left: 46, right: 18, top: 16, bottom: 28, containLabel: false },
    tooltip: {
      trigger: "axis", backgroundColor: v("--surface"), borderColor: v("--border"), textStyle: { color: v("--text"), fontSize: 12 },
      axisPointer: { type: "line", lineStyle: { color: v("--text-3"), type: "dashed" } }, confine: true,
    },
    xAxis: { type: "time", ...ax, splitLine: { show: false } },
    yAxis: { type: "value", ...ax, splitNumber: 4, axisLine: { show: false } },
    ...extra,
  };
}
const line = (name, data, color, extra = {}) => ({ name, type: "line", data, showSymbol: false, symbolSize: 8, lineStyle: { width: 2, color }, itemStyle: { color }, emphasis: { focus: "series" }, ...extra });
const ymd = (s) => (s.length === 7 ? s + "-15" : s);
const pairs = (dates, vals) => dates.map((d, i) => [ymd(d), vals[i]]);
function recessionAreas(dates, flags) {
  const out = []; let start = null;
  flags.forEach((f, i) => {
    if (f && start === null) start = dates[i];
    if ((!f || i === flags.length - 1) && start !== null) { out.push([{ xAxis: ymd(start) }, { xAxis: ymd(f ? dates[i] : dates[i - 1]) }]); start = null; }
  });
  return { silent: true, itemStyle: { color: v("--rec") }, data: out };
}
const tipDate = (p) => { const d = new Date(p[0].value[0]); return `${MON[d.getUTCMonth()]} ${d.getUTCFullYear()}`; };
function tipRows(params, fmt = f1) {
  return `<div style="font-weight:600;margin-bottom:4px">${tipDate(params)}</div>` + params.filter((p) => p.value[1] !== null && p.value[1] !== undefined)
    .map((p) => `<div style="display:flex;justify-content:space-between;gap:18px"><span>${p.marker}${p.seriesName}</span><b style="font-family:JetBrains Mono,monospace;font-weight:500">${fmt(p.value[1], p)}</b></div>`).join("");
}
function rangeSeg(opts, initial, onPick) {
  const seg = h("div", { class: "seg", role: "group" });
  for (const [label, val] of opts) {
    const b = h("button", { "aria-pressed": String(val === initial) }, label);
    b.onclick = () => { seg.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", "false")); b.setAttribute("aria-pressed", "true"); onPick(val); };
    seg.append(b);
  }
  return seg;
}
function yearsBack(lastDate, years) {
  if (!years) return null;
  const d = new Date(ymd(lastDate)); d.setUTCFullYear(d.getUTCFullYear() - years); return d.toISOString().slice(0, 10);
}
function sparkSVG(vals, w = 110, ht = 28, color = "var(--text-2)") {
  const xs = vals.filter(isNum); if (xs.length < 2) return h("span");
  const lo = Math.min(...xs), hi = Math.max(...xs), n = vals.length;
  const pts = vals.map((y, i) => (isNum(y) ? `${(i / (n - 1)) * w},${ht - 2 - ((y - lo) / (hi - lo || 1)) * (ht - 4)}` : null)).filter(Boolean);
  const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  s.setAttribute("viewBox", `0 0 ${w} ${ht}`); s.setAttribute("width", w); s.setAttribute("height", ht); s.setAttribute("aria-hidden", "true");
  s.innerHTML = `<polyline points="${pts.join(" ")}" fill="none" stroke="${color}" stroke-width="1.5" stroke-linejoin="round"/>`;
  return s;
}

/* ============================================================ OVERVIEW */
function pageOverview() {
  const d = S.d, H = d.history, hd = d.headline;
  const fs = d.factors.slice().sort((a, b) => b.score - a.score);
  const page = h("div");
  page.append(h("div", { class: "page-head" }, h("div", {},
    h("div", { class: "eyebrow" }, `Daily brief · ${dlong(d.meta.generated_at.slice(0, 10))}`),
    h("h1", {}, "Macro Health"),
    h("p", {}, `The Health Gauge reads ${f0(hd.score)} (${hd.grade}, ${hd.word}), ${hd.change_3m >= 0 ? "up" : "down"} ${f1(Math.abs(hd.change_3m))} points over three months. `
      + `${fs[0].label} (${f0(fs[0].score)}) is the strongest factor; ${fs[5].label} (${f0(fs[5].score)}) is the weakest.`))));

  // hero + tiles
  const hero = h("section", { class: "card hero" },
    h("div", { class: "eyebrow" }, "Health Gauge"),
    h("div", { class: "hero-score" }, h("span", { class: "hero-num" }, f0(hd.score)), h("span", { class: "hero-of" }, "/ 100"), gradePill(hd.grade, hd.word)),
    h("div", {}, h("div", { class: "meter", role: "img", "aria-label": `Gauge at ${f0(hd.score)} of 100` }, h("div", { class: "meter-mark", style: `left:${Math.max(0, Math.min(100, hd.score))}%` })),
      h("div", { class: "meter-scale" }, ...["0", "35", "45", "60", "70", "100"].map((x) => h("span", {}, x)))),
    h("div", { class: "chips" }, ...[["1M", hd.change_1m], ["3M", hd.change_3m], ["12M", hd.change_12m]].map(([k, x]) => h("span", { class: "chip" }, `${k} `, h("b", { class: cls(x) }, sgn(x))))),
    h("div", { class: "card-sub" }, "Equal-weighted average of six factor scores. Each score is a percentile against all history known at the time: 50 is a historically typical reading."));
  const tiles = h("div", { class: "grid g-tiles" });
  for (const f of d.factors) {
    const head = f.parts[0];
    const tile = h("section", { class: "card tile", role: "link", tabindex: "0", onclick: () => (location.hash = `#factor/${f.key}`), onkeydown: (e) => e.key === "Enter" && (location.hash = `#factor/${f.key}`) },
      h("div", { class: "tile-top" }, h("span", { class: "tile-name" }, h("i", { class: "swatch", style: `background:var(${FCOL[f.key]})` }), f.label), gradePill(f.grade, f.word)),
      h("div", { style: "display:flex;align-items:baseline;gap:10px" }, h("span", { class: "tile-score" }, f0(f.score)), h("span", { class: "delta " + cls(f.change_3m) }, `${sgn(f.change_3m)} 3M`)),
      h("div", { class: "tile-read" }, `${head.label}: `, h("b", { class: "mono" }, unitFmt(head.value, head.unit)), ` (${asOfLabel(head)})`));
    const sp = h("div", { class: "tile-spark" }); tile.append(sp);
    queueMicrotask(() => mount(sp, () => ({ animation: false, grid: { left: 0, right: 0, top: 4, bottom: 2 }, xAxis: { type: "category", show: false, data: H.dates.slice(-60) },
      yAxis: { type: "value", min: 0, max: 100, show: false }, series: [{ type: "line", data: H.factors[f.key].slice(-60), showSymbol: false, lineStyle: { width: 1.5, color: v(FCOL[f.key]) },
        markLine: { silent: true, symbol: "none", lineStyle: { color: v("--border"), type: "dashed" }, label: { show: false }, data: [{ yAxis: 50 }] } }] })));
    tiles.append(tile);
  }
  page.append(h("div", { class: "grid g-hero" }, hero, tiles));

  // gauge history + S&P (separate panels, shared range — never a dual axis)
  const last = H.dates[H.dates.length - 1];
  let zoomFrom = yearsBack(last, 20);
  const histRows = () => H.dates.map((dt, i) => ({ date: dt, health: H.health[i], ...Object.fromEntries(FKEYS.map((k) => [k, H.factors[k][i]])), spx: H.spx[i], recession: H.recession[i] }));
  const histCols = [{ k: "date", label: "Month" }, { k: "health", label: "Gauge", r: 1, fmt: f1 }, ...d.factors.map((f) => ({ k: f.key, label: f.label, r: 1, fmt: f1 })), { k: "spx", label: "S&P 500 (monthly avg)", r: 1, fmt: big }, { k: "recession", label: "NBER recession", r: 1 }];
  const gaugeCard = card({
    title: "Health Gauge, point-in-time", sub: "Each month uses only data published by that month-end. Shaded: NBER recessions. Bands: grade F (<35) and A (≥70).",
    size: "lg", sources: ["USREC", ...new Set(d.factors.flatMap((f) => f.parts.map((p) => p.series)))].slice(0, 12),
    table: { cols: histCols, rows: () => histRows().slice().reverse() }, csv: "health_gauge_history.csv",
    chart: () => base({
      tooltip: { ...base().tooltip, formatter: (p) => tipRows(p) },
      yAxis: { ...base().yAxis, min: 0, max: 100, interval: 25 },
      dataZoom: [{ type: "inside", startValue: zoomFrom }],
      series: [line("Health Gauge", pairs(H.dates, H.health), v("--text"), {
        markArea: { silent: true, data: [[{ yAxis: 0, itemStyle: { color: v("--critical"), opacity: 0.07 } }, { yAxis: 35 }], [{ yAxis: 70, itemStyle: { color: v("--good"), opacity: 0.07 } }, { yAxis: 100 }]] },
        markLine: { silent: true, symbol: "none", label: { show: false }, lineStyle: { color: v("--text-3"), type: "dashed" }, data: [{ yAxis: 50 }] },
      }), { type: "line", data: [], markArea: recessionAreas(H.dates, H.recession) }],
    }),
  });
  const spxCard = card({
    title: "S&P 500, monthly average (log scale)", sub: "Shown on its own axis below the gauge; same date range.",
    size: "sm", sources: ["SHILLER", "SP500"], table: { cols: [{ k: "date", label: "Month" }, { k: "spx", label: "S&P 500", r: 1, fmt: big }], rows: () => histRows().slice().reverse() }, csv: "sp500_monthly.csv",
    chart: () => base({
      tooltip: { ...base().tooltip, formatter: (p) => tipRows(p, big) },
      yAxis: { ...base().yAxis, type: "log", min: (e) => Math.pow(10, Math.floor(Math.log10(e.min))), axisLabel: { ...base().yAxis.axisLabel, formatter: (x) => (x >= 1000 ? (x / 1000).toFixed(0) + "k" : x) } },
      dataZoom: [{ type: "inside", startValue: zoomFrom }],
      series: [line("S&P 500", pairs(H.dates, H.spx), v("--spx")), { type: "line", data: [], markArea: recessionAreas(H.dates, H.recession) }],
    }),
  });
  const seg = rangeSeg([["5Y", 5], ["10Y", 10], ["20Y", 20], ["All", 0]], 20, (yrs) => {
    zoomFrom = yearsBack(last, yrs);
    for (const c of [gaugeCard, spxCard]) c.chartEl._chart.dispatchAction({ type: "dataZoom", startValue: zoomFrom || ymd(H.dates[0]), endValue: ymd(last) });
  });
  $(".card-tools", gaugeCard).prepend(seg);
  page.append(h("div", { class: "stack mt" }, gaugeCard, spxCard));
  queueMicrotask(() => { if (gaugeCard.chartEl._chart && spxCard.chartEl._chart) echarts.connect([gaugeCard.chartEl._chart, spxCard.chartEl._chart]); });

  // heatmap
  const N = 36, hx = H.dates.slice(-N);
  const heat = [];
  d.factors.forEach((f, yi) => hx.forEach((dt, xi) => heat.push([xi, yi, H.factors[f.key][H.dates.length - N + xi]])));
  hx.forEach((dt, xi) => heat.push([xi, 6, H.health[H.dates.length - N + xi]]));
  page.append(h("div", { class: "mt" }, card({
    title: "Factor scores, last 36 months", sub: "Blue = supportive (above 50), red = a drag (below 50). Hover for values.",
    size: "", sources: [...new Set(d.factors.flatMap((f) => f.parts.map((p) => p.series)))], note: "Scores are percentiles of these series; see each factor page.",
    table: { cols: histCols.slice(0, 8), rows: () => histRows().slice(-N).reverse() }, csv: "factor_scores_36m.csv",
    chart: () => ({
      animation: false, textStyle: { fontFamily: "Inter" },
      tooltip: { backgroundColor: v("--surface"), borderColor: v("--border"), textStyle: { color: v("--text"), fontSize: 12 },
        formatter: (p) => `${ym(hx[p.value[0]])}<br><b>${p.value[1] === 6 ? "Health Gauge" : d.factors[p.value[1]].label}</b>: ${f1(p.value[2])} (${gradeOf(p.value[2])})` },
      grid: { left: 130, right: 70, top: 6, bottom: 28 },
      xAxis: { type: "category", data: hx.map(ym), axisLabel: { color: v("--text-3"), fontSize: 10, interval: 5 }, axisTick: { show: false }, axisLine: { show: false } },
      yAxis: { type: "category", data: [...d.factors.map((f) => f.label), "Health Gauge"], inverse: true, axisLabel: { color: v("--text-2"), fontSize: 11.5, fontWeight: 500 }, axisTick: { show: false }, axisLine: { show: false } },
      visualMap: { min: 0, max: 100, calculable: false, orient: "vertical", right: 4, top: "middle", itemHeight: 140, itemWidth: 10, text: ["100", "0"], textStyle: { color: v("--text-3"), fontSize: 10 },
        inRange: { color: ["#b42b2b", "#e34948", "#f2a19c", v("--surface-2"), "#86b6ef", "#2a78d6", "#184f95"] } },
      series: [{ type: "heatmap", data: heat, itemStyle: { borderColor: v("--surface"), borderWidth: 2, borderRadius: 3 }, emphasis: { itemStyle: { borderColor: v("--text"), borderWidth: 1 } } }],
    }),
  })));

  // markets strip + gauge log
  const pick = ["SP500", "VIXCLS", "DGS10", "DTWEXBGS", "BAMLH0A0HYM2", "DCOILWTICO"].map((id) => d.markets.find((m) => m.id === id));
  const strip = h("div", { class: "strip" }, ...pick.map((m) => h("div", {},
    h("div", { class: "lbl" }, m.label), h("div", { class: "val" }, m.kind === "rate" ? f2(m.last) + "%" : big(m.last)),
    h("div", { class: "delta " + cls(m.chg_1d) }, `${sgn(m.chg_1d, m.kind === "rate" ? 0 : 2, m.kind === "rate" ? " bp" : "%")} 1D`))));
  const mk = card({ title: "Markets today", sub: `Latest daily closes from FRED. Full monitor on the Daily Markets page.`, body: strip, sources: pick.map((m) => m.id),
    tools: [h("a", { class: "btn", href: "#markets" }, "Open")] });
  $(".card-body", mk).style.padding = "0";
  const log = d.gauge_log || [];
  const logCols = [{ k: "date", label: "Run date" }, { k: "health", label: "Gauge", r: 1, fmt: f1 }, ...d.factors.map((f) => ({ k: f.key, label: f.label, r: 1, fmt: f0 }))];
  const logCard = card({
    title: "Daily gauge log", sub: log.length > 1 ? `${log.length} daily readings recorded.` : "Starts today. A new row is added each time the daily refresh runs.",
    body: h("div", { style: "overflow-x:auto" }, table(logCols, log.slice().reverse().slice(0, 10))), table: { cols: logCols, rows: () => log.slice().reverse() }, csv: "gauge_daily_log.csv",
  });
  page.append(h("div", { class: "grid g-2 mt" }, mk, logCard));
  return page;
}

/* ============================================================= FACTORS */
function pageFactor(key) {
  const d = S.d, H = d.history;
  const f = d.factors.find((x) => x.key === key) || d.factors[0];
  const page = h("div");
  page.append(h("div", { class: "subnav" }, ...d.factors.map((x) => h("a", { href: `#factor/${x.key}`, class: x.key === f.key ? "active" : "" }, h("i", { class: "swatch", style: `background:var(${FCOL[x.key]})` }), x.label))));
  page.append(h("div", { class: "page-head" }, h("div", {},
    h("div", { class: "eyebrow" }, "Factor"),
    h("h1", { style: "display:flex;gap:12px;align-items:center" }, `${f.label} · ${f0(f.score)}`, gradePill(f.grade, f.word)),
    h("p", {}, f.why + " The factor score averages its measures' scores below."))));

  const sc = H.factors[f.key];
  page.append(card({
    title: `${f.label} factor score`, sub: "Point-in-time percentile, 0–100. Dashed line: 50 (historical norm). Shaded: recessions.", size: "sm",
    sources: [...new Set(f.parts.flatMap((p) => (p.series === "DTWEXBGS" ? ["TWEXBMTH", "DTWEXBGS"] : [p.series])))].concat(["USREC"]),
    table: { cols: [{ k: "date", label: "Month" }, { k: "s", label: "Score", r: 1, fmt: f1 }], rows: () => H.dates.map((dt, i) => ({ date: dt, s: sc[i] })).reverse() }, csv: `${f.key}_factor_score.csv`,
    chart: () => base({ tooltip: { ...base().tooltip, formatter: (p) => tipRows(p) }, yAxis: { ...base().yAxis, min: 0, max: 100, interval: 25 }, dataZoom: [{ type: "inside" }],
      series: [line(`${f.label} score`, pairs(H.dates, sc), v(FCOL[f.key]), { markLine: { silent: true, symbol: "none", label: { show: false }, lineStyle: { color: v("--text-3"), type: "dashed" }, data: [{ yAxis: 50 }] } }),
        { type: "line", data: [], markArea: recessionAreas(H.dates, H.recession) }] }),
  }));

  for (const p of f.parts) {
    const ch = H.components[p.key];
    const src = d.sources.find((s) => s.id === p.series) || {};
    const rows = () => H.dates.map((dt, i) => ({ date: dt, value: ch.value[i], score: ch.score[i] })).reverse();
    const cols = [{ k: "date", label: "Month (as known)" }, { k: "value", label: `${p.label} (${p.unit})`, r: 1, fmt: f2 }, { k: "score", label: "Score", r: 1, fmt: f1 }];
    const kv = h("dl", { class: "kv" },
      h("dt", {}, "Latest"), h("dd", { class: "mono" }, `${unitFmt(p.value, p.unit)} (${asOfLabel(p)})`),
      h("dt", {}, "Score"), h("dd", {}, `${f0(p.score)} · ${p.direction}`),
      h("dt", {}, "Series"), h("dd", {}, h("a", { href: src.url, target: "_blank", rel: "noopener" }, `${p.series}: ${src.title || ""}`)),
      h("dt", {}, "Publisher"), h("dd", {}, src.source || "–"),
      h("dt", {}, "Frequency"), h("dd", {}, src.frequency || "–"));
    page.append(h("div", { class: "grid g-2 mt" },
      card({ title: p.label, sub: `Value as it was known at each month-end, ${p.unit === "pp" ? "percentage points" : "percent"}.`, size: "sm", sources: p.series === "DTWEXBGS" ? ["TWEXBMTH", "DTWEXBGS"] : [p.series],
        table: { cols, rows }, csv: `${p.key}.csv`,
        chart: () => base({ tooltip: { ...base().tooltip, formatter: (q) => tipRows(q, f2) }, dataZoom: [{ type: "inside" }], yAxis: { ...base().yAxis, scale: true },
          series: [line(p.label, pairs(H.dates, ch.value), v(FCOL[f.key])), { type: "line", data: [], markArea: recessionAreas(H.dates, H.recession) }] }) }),
      card({ title: "Measure score", sub: p.direction + ". Percentile vs. all prior history.", sources: [p.series], body: kv, size: "xs",
        table: { cols, rows }, csv: `${p.key}_score.csv`,
        chart: () => base({ grid: { left: 40, right: 12, top: 10, bottom: 24 }, tooltip: { ...base().tooltip, formatter: (q) => tipRows(q) }, yAxis: { ...base().yAxis, min: 0, max: 100, splitNumber: 2 },
          series: [line("Score", pairs(H.dates, ch.score), v(FCOL[f.key]), { lineStyle: { width: 1.5, color: v(FCOL[f.key]) } })] }) })));
  }
  return page;
}

/* ============================================================= MARKETS */
function pageMarkets(sel) {
  const d = S.d, ms = d.markets;
  const cur = ms.find((m) => m.id === sel) || ms[0];
  const page = h("div");
  const latest = ms.map((m) => m.as_of).sort().pop();
  page.append(h("div", { class: "page-head" }, h("div", {}, h("div", { class: "eyebrow" }, `Latest close ${dlong(latest)}`), h("h1", {}, "Daily Markets"),
    h("p", {}, "Rates, credit, the dollar, equities and oil from FRED's daily series. Rate changes are in basis points; prices in percent. Click a row to chart it."))));
  const chg = (k) => ({ k, r: 1, label: { chg_1d: "1D", chg_1w: "1W", chg_1m: "1M", chg_ytd: "YTD", chg_1y: "1Y" }[k], fmt: (x, r) => sgn(x, r.kind === "rate" ? 0 : 2, r.kind === "rate" ? " bp" : "%"), cls: (x) => cls(x) });
  const cols = [{ k: "label", label: "Series" }, { k: "last", label: "Last", r: 1, fmt: (x, r) => (r.kind === "rate" ? f2(x) + "%" : big(x)) }, chg("chg_1d"), chg("chg_1w"), chg("chg_1m"), chg("chg_ytd"), chg("chg_1y"),
    { k: "pct_rank_5y", label: "5Y pctile", r: 1, fmt: f0 }, { k: "as_of", label: "As of", fmt: dlong }, { k: "spark", label: "1Y trend", fmt: (_, r) => sparkSVG(r.values.slice(-260)) }];
  const csvCols = cols.filter((c) => c.k !== "spark").concat([{ k: "id", label: "FRED ID" }]);
  page.append(card({ title: "Market monitor", sub: "5Y pctile: where today's level sits in its last five years (100 = highest).", sources: ms.map((m) => m.id),
    body: h("div", { style: "overflow-x:auto" }, table(cols, ms, { onRow: (r) => (location.hash = `#markets/${r.id}`), rowClass: (r) => (r.id === cur.id ? "sel" : "") })),
    table: { cols: csvCols, rows: () => ms }, csv: "daily_markets.csv" }));

  let from = yearsBack(cur.as_of, 1);
  const c = card({
    title: `${cur.label} (${cur.id})`, sub: `${cur.kind === "rate" ? f2(cur.last) + "%" : big(cur.last)} on ${dlong(cur.as_of)}. Five years of daily data.`, size: "lg", sources: [cur.id],
    table: { cols: [{ k: "date", label: "Date" }, { k: "value", label: cur.label, r: 1, fmt: f2 }], rows: () => cur.dates.map((dt, i) => ({ date: dt, value: cur.values[i] })).reverse() }, csv: `${cur.id}_daily.csv`,
    chart: () => base({ tooltip: { ...base().tooltip, formatter: (p) => { const dt = p[0].value[0]; return `<b>${dlong(typeof dt === "string" ? dt : new Date(dt).toISOString().slice(0, 10))}</b><br>${cur.label}: <b>${f2(p[0].value[1])}</b>`; } },
      yAxis: { ...base().yAxis, scale: true }, dataZoom: [{ type: "inside", startValue: from }],
      series: [line(cur.label, pairs(cur.dates, cur.values), v("--s1"), { lineStyle: { width: 1.6, color: v("--s1") } })] }),
  });
  $(".card-tools", c).prepend(rangeSeg([["1M", 1 / 12], ["3M", 0.25], ["6M", 0.5], ["1Y", 1], ["5Y", 0]], 1, (y) => {
    const dd = new Date(cur.as_of); if (y) dd.setUTCDate(dd.getUTCDate() - Math.round(365 * y));
    c.chartEl._chart.dispatchAction({ type: "dataZoom", startValue: y ? dd.toISOString().slice(0, 10) : cur.dates[0], endValue: cur.as_of });
  }));
  page.append(h("div", { class: "mt" }, c));
  return page;
}

/* ============================================================ BACKTEST */
function pageBacktest() {
  const d = S.d, B = d.backtest, st = Object.fromEntries(B.stats.map((r) => [r.horizon, r]));
  const perf = Object.fromEntries(B.perf.map((r) => [r.name, r]));
  const G = perf["Gauge timing"], BH = perf["Buy & hold S&P 500"];
  const sig = B.stats.some((r) => r.significant_5pct);
  const page = h("div");
  page.append(h("div", { class: "page-head" }, h("div", {}, h("div", { class: "eyebrow" }, `${B.months} months · ${ym(d.meta.backtest_start.slice(0, 7))} to present`),
    h("h1", {}, "Does the gauge predict the market?"),
    h("p", {}, "Every month-end reading uses only data published by then. The trade happens the following month at that month's average price. Nothing was fitted to returns: weights are equal and grade cut-offs were fixed in advance."))));
  page.append(h("div", { class: "callout" + (sig ? "" : " warn") }, h("b", {}, sig ? "Some horizons show a statistically significant link. " : "Short answer: no reliable edge. "),
    `The 12-month rank correlation between the gauge and the S&P 500's next-12-month total return is ${sgn(st["12m"].rank_corr, 2)} (Newey-West t = ${f2(st["12m"].nw_t_stat)}; |t| above 1.96 is needed for 95% confidence). `
    + `Moving to T-bills when the gauge is below ${d.meta.threshold} cut the worst drawdown from ${pct(BH.max_drawdown, 0)} to ${pct(G.max_drawdown, 0)}, but returned ${pct(G.CAGR)} a year versus ${pct(BH.CAGR)} for buy-and-hold.`));

  const kpi = (label, val, sub) => h("section", { class: "card hero", style: "gap:4px" }, h("div", { class: "eyebrow" }, label), h("div", { class: "tile-score" }, val), h("div", { class: "card-sub" }, sub));
  page.append(h("div", { class: "grid g-tiles mt", style: "grid-template-columns:repeat(4,1fr)" },
    kpi("12M rank correlation", sgn(st["12m"].rank_corr, 2), `t = ${f2(st["12m"].nw_t_stat)} (not significant)`),
    kpi("CAGR: timing vs. hold", `${pct(G.CAGR)} / ${pct(BH.CAGR)}`, "Before costs and taxes"),
    kpi("Max drawdown", `${pct(G.max_drawdown, 0)} / ${pct(BH.max_drawdown, 0)}`, "Timing vs. buy-and-hold"),
    kpi("Sharpe (vs. T-bills)", `${f2(G.sharpe)} / ${f2(BH.sharpe)}`, `${f1(B.switches_per_year)} switches a year`)));

  const bk = B.buckets_12m;
  const bCols = [{ k: "bucket", label: "Gauge grade" }, { k: "months", label: "Months", r: 1 }, { k: "avg_return", label: "Avg 12M return", r: 1, fmt: pct }, { k: "median_return", label: "Median", r: 1, fmt: pct }, { k: "pct_positive", label: "% positive", r: 1, fmt: (x) => pct(x, 0) }, { k: "worst", label: "Worst", r: 1, fmt: pct }];
  const E = B.equity;
  const eqCols = [{ k: "date", label: "Month" }, { k: "s", label: "Gauge timing ($1 grows to)", r: 1, fmt: f2 }, { k: "b", label: "Buy & hold", r: 1, fmt: f2 }, { k: "ds", label: "Timing drawdown", r: 1, fmt: pct }, { k: "db", label: "Hold drawdown", r: 1, fmt: pct }, { k: "in", label: "In stocks", r: 1 }];
  const eqRows = () => E.dates.map((dt, i) => ({ date: dt, s: E.strategy[i], b: E.buy_hold[i], ds: E.dd_strategy[i], db: E.dd_buy_hold[i], in: E.in_market[i] })).reverse();
  const legend2 = h("div", { class: "legend" }, h("span", {}, h("i", { style: `background:var(--s1)` }), "Gauge timing"), h("span", {}, h("i", { style: `background:var(--spx)` }), "Buy & hold S&P 500"));
  const eq = card({ title: "Growth of $1 (log scale)", sub: `Timing rule: stocks when gauge ≥ ${d.meta.threshold}, else 3-month T-bills.`, size: "", sources: ["SHILLER", "SP500", "TB3MS"], body: legend2,
    table: { cols: eqCols, rows: eqRows }, csv: "backtest_equity.csv",
    chart: () => base({ tooltip: { ...base().tooltip, formatter: (p) => tipRows(p, (x) => "$" + f2(x)) }, yAxis: { ...base().yAxis, type: "log", axisLabel: { ...base().yAxis.axisLabel, formatter: (x) => "$" + x } },
      series: [line("Gauge timing", pairs(E.dates, E.strategy), v("--s1")), line("Buy & hold", pairs(E.dates, E.buy_hold), v("--spx"))] }) });
  const dd = card({ title: "Drawdown from prior peak", sub: "How far each approach was below its own high.", size: "sm", sources: ["SHILLER", "SP500", "TB3MS"],
    table: { cols: eqCols, rows: eqRows }, csv: "backtest_drawdowns.csv",
    chart: () => base({ tooltip: { ...base().tooltip, formatter: (p) => tipRows(p, (x) => pct(x)) }, yAxis: { ...base().yAxis, max: 0, axisLabel: { ...base().yAxis.axisLabel, formatter: (x) => (x * 100).toFixed(0) + "%" } },
      series: [line("Gauge timing", pairs(E.dates, E.dd_strategy), v("--s1")), line("Buy & hold", pairs(E.dates, E.dd_buy_hold), v("--spx"))] }) });
  const bars = card({ title: "Next-12-month S&P 500 return by gauge grade", sub: "Average total return over the 12 months after each reading.", sources: ["SHILLER", "SP500"],
    table: { cols: bCols, rows: () => bk }, csv: "returns_by_grade.csv",
    chart: () => base({ tooltip: { trigger: "item", backgroundColor: v("--surface"), borderColor: v("--border"), textStyle: { color: v("--text") }, formatter: (p) => `${p.name}<br>Avg: <b>${pct(p.value)}</b><br>${bk[p.dataIndex].months} months` },
      xAxis: { type: "category", data: bk.map((r) => r.bucket), axisLabel: { color: v("--text-2"), fontSize: 11 }, axisTick: { show: false }, axisLine: { lineStyle: { color: v("--border") } } },
      yAxis: { ...base().yAxis, axisLabel: { ...base().yAxis.axisLabel, formatter: (x) => (x * 100).toFixed(0) + "%" } },
      series: [{ type: "bar", data: bk.map((r) => r.avg_return), barMaxWidth: 46, itemStyle: { color: v("--s1"), borderRadius: [4, 4, 0, 0] },
        label: { show: true, position: "top", color: v("--text-2"), fontSize: 11, formatter: (p) => `${pct(p.value)} · n=${bk[p.dataIndex].months}` } }] }) });
  page.append(h("div", { class: "grid g-2 mt" }, eq, bars), h("div", { class: "mt" }, dd));

  // threshold sensitivity: two charts, one measure each
  const sw = B.sweep;
  const swCols = [{ k: "threshold", label: "Threshold", r: 1 }, { k: "cagr", label: "CAGR", r: 1, fmt: pct }, { k: "max_drawdown", label: "Max drawdown", r: 1, fmt: pct }, { k: "sharpe", label: "Sharpe", r: 1, fmt: f2 }, { k: "pct_invested", label: "% in stocks", r: 1, fmt: (x) => pct(x, 0) }];
  const swChart = (key, label, ref, fmt) => () => base({ grid: { left: 52, right: 18, top: 16, bottom: 34 },
    tooltip: { ...base().tooltip, axisPointer: { type: "shadow" }, formatter: (p) => `Threshold ${p[0].name}<br>${label}: <b>${fmt(p[0].value)}</b><br>Buy & hold: ${fmt(ref)}` },
    xAxis: { type: "category", data: sw.map((r) => r.threshold), name: "Hold stocks when gauge ≥", nameLocation: "middle", nameGap: 24, nameTextStyle: { color: v("--text-3"), fontSize: 11 }, axisLabel: { color: v("--text-3") }, axisTick: { show: false }, axisLine: { lineStyle: { color: v("--border") } } },
    yAxis: { ...base().yAxis, scale: true, axisLabel: { ...base().yAxis.axisLabel, formatter: (x) => (x * 100).toFixed(0) + "%" } },
    series: [{ type: "bar", data: sw.map((r) => r[key]), barMaxWidth: 26, itemStyle: { color: v("--s1"), borderRadius: 3 },
      markLine: { silent: true, symbol: "none", lineStyle: { color: v("--spx"), type: "dashed" }, label: { formatter: "Buy & hold", color: v("--text-3"), fontSize: 10, position: "insideEndTop" }, data: [{ yAxis: ref }] } }] });
  page.append(h("div", { class: "grid g-2 mt" },
    card({ title: "Sensitivity: annual return by threshold", sub: "No threshold beats buy-and-hold on return.", size: "sm", sources: ["SHILLER", "SP500", "TB3MS"], table: { cols: swCols, rows: () => sw }, csv: "threshold_sweep.csv", chart: swChart("cagr", "CAGR", BH.CAGR, pct) }),
    card({ title: "Sensitivity: worst drawdown by threshold", sub: "Higher thresholds sit in cash more and lose less at the bottom.", size: "sm", sources: ["SHILLER", "SP500", "TB3MS"], table: { cols: swCols, rows: () => sw }, csv: "threshold_sweep.csv", chart: swChart("max_drawdown", "Max drawdown", BH.max_drawdown, pct) })));

  // factor diagnostics
  const fd = B.factor_diag;
  const label = (k) => (d.factors.find((f) => f.key === k) || {}).label || { health: "Health Gauge", health_6m_change: "Gauge, 6-mo change" }[k] || k;
  const fdCols = [{ k: "signal", label: "Signal", fmt: label }, { k: "months", label: "Months", r: 1 }, { k: "rank_corr_12m", label: "12M rank corr", r: 1, fmt: (x) => sgn(x, 2) }, { k: "nw_t_stat", label: "Newey-West t", r: 1, fmt: (x) => sgn(x, 2) }];
  page.append(h("div", { class: "grid g-2 mt" },
    card({ title: "Which inputs carry signal? (12-month horizon)", sub: "Newey-West t-statistic; bars past the dashed lines (±1.96) would be significant at 95%.", sources: [], note: "Exploratory: 8 tests at once.",
      table: { cols: fdCols, rows: () => fd }, csv: "factor_diagnostics.csv",
      chart: () => base({ grid: { left: 130, right: 24, top: 10, bottom: 28 }, tooltip: { trigger: "item", backgroundColor: v("--surface"), borderColor: v("--border"), textStyle: { color: v("--text") }, formatter: (p) => `${p.name}<br>t = <b>${f2(p.value)}</b><br>rank corr ${sgn(fd[p.dataIndex].rank_corr_12m, 2)}` },
        xAxis: { type: "value", min: -3, max: 3, axisLabel: { color: v("--text-3") }, splitLine: { lineStyle: { color: v("--grid") } } },
        yAxis: { type: "category", data: fd.map((r) => label(r.signal)), inverse: true, axisLabel: { color: v("--text-2") }, axisTick: { show: false }, axisLine: { lineStyle: { color: v("--border") } } },
        series: [{ type: "bar", data: fd.map((r) => ({ value: r.nw_t_stat, itemStyle: { color: FCOL[r.signal] ? v(FCOL[r.signal]) : v("--text-2"), borderRadius: 3 } })), barMaxWidth: 16,
          markLine: { silent: true, symbol: "none", lineStyle: { color: v("--text-3"), type: "dashed" }, label: { show: false }, data: [{ xAxis: -1.96 }, { xAxis: 1.96 }] } }] }) }),
    card({ title: "All horizons and decades", sub: "Rank correlation with forward returns, and the timing rule by decade.", sources: ["SHILLER", "SP500", "TB3MS"],
      body: h("div", {}, table([{ k: "horizon", label: "Horizon" }, { k: "months", label: "Months", r: 1 }, { k: "rank_corr", label: "Rank corr", r: 1, fmt: (x) => sgn(x, 3) }, { k: "ret_per_10pts", label: "Return per +10 pts", r: 1, fmt: (x) => sgn(x * 100, 2, "%") }, { k: "nw_t_stat", label: "NW t", r: 1, fmt: (x) => sgn(x, 2) }], B.stats),
        h("div", { style: "height:12px" }), table([{ k: "decade", label: "Decade" }, { k: "strategy_cagr", label: "Timing CAGR", r: 1, fmt: pct }, { k: "buy_hold_cagr", label: "Hold CAGR", r: 1, fmt: pct }, { k: "pct_time_invested", label: "% in stocks", r: 1, fmt: (x) => pct(x, 0) }], B.by_decade)),
      table: { cols: [{ k: "horizon", label: "Horizon" }, { k: "months", label: "Months" }, { k: "rank_corr", label: "Rank corr" }, { k: "ret_per_10pts", label: "Return per +10 pts" }, { k: "nw_t_stat", label: "NW t" }], rows: () => B.stats }, csv: "horizon_stats.csv" })));

  page.append(h("div", { class: "callout mt" }, h("b", {}, "Caveats. "), "FRED serves today's revised GDP and profit figures, not first prints, which flatters the backtest slightly. Monthly-average prices smooth returns. No trading costs or taxes. Factor choices reflect hindsight about what usually matters, even though no parameter was fitted. Overlapping 12-month windows are handled with Newey-West standard errors."));
  return page;
}

/* ============================================================= SOURCES */
function pageSources(sel) {
  const d = S.d;
  const page = h("div");
  page.append(h("div", { class: "page-head" }, h("div", {}, h("div", { class: "eyebrow" }, `${d.sources.length} series`), h("h1", {}, "Sources"),
    h("p", {}, "Every number on this site comes from one of the series below. Titles, publishers, releases, units and update times are read from each series' FRED page at refresh time, not typed by hand."))));
  const cols = [
    { k: "id", label: "ID", fmt: (x, r) => h("a", { href: r.url, target: "_blank", rel: "noopener", class: "mono" }, x) },
    { k: "title", label: "Title" },
    { k: "source", label: "Publisher", fmt: (x, r) => (r.source_url ? h("a", { href: r.source_url, target: "_blank", rel: "noopener" }, x) : x) },
    { k: "release", label: "Release", fmt: (x, r) => (r.release_url ? h("a", { href: r.release_url, target: "_blank", rel: "noopener" }, x) : x || "–") },
    { k: "units", label: "Units" }, { k: "frequency", label: "Frequency" },
    { k: "last_obs", label: "Latest obs.", fmt: (x) => (x ? x.slice(0, 10) : "–") },
    { k: "fred_updated", label: "Publisher update" },
    { k: "fetch_status", label: "This refresh", fmt: (x) => h("span", { class: "badge " + (x === "live" ? "live" : String(x).startsWith("STALE") ? "stale" : "") }, x || "–") },
    { k: "used_for", label: "Used for", fmt: (x) => h("div", {}, ...(x || []).map((u) => h("div", {}, u))) },
  ];
  const csvCols = cols.map((c) => ({ ...c, fmt: undefined })).concat([{ k: "url", label: "URL" }]);
  const rows = d.sources.map((s) => ({ ...s, used_for_csv: (s.used_for || []).join("; ") }));
  const t = table(cols, rows, { rowClass: (r) => (r.id === sel ? "sel" : "") });
  page.append(card({ title: "Series used", sub: "Click an ID for the series page on FRED, or a publisher for the original agency.", body: h("div", { style: "overflow-x:auto" }, t),
    table: { cols: csvCols.map((c) => (c.k === "used_for" ? { k: "used_for_csv", label: "Used for" } : c)), rows: () => rows }, csv: "sources.csv" }));
  const M = d.meta;
  page.append(h("div", { class: "grid g-2 mt" },
    card({ title: "How the data is collected", body: h("div", { class: "prose" },
      h("p", {}, "FRED series are downloaded from FRED's public CSV endpoint (fredgraph.csv), one request per series for the full history. No API key is required. Each download is checked before it replaces the saved copy; if FRED is unreachable, the last good copy is used and the series is marked STALE above."),
      h("p", {}, `S&P 500 monthly prices and dividends before ${M.price_splice ? ym(M.price_splice.slice(0, 7)) : "–"} come from Robert Shiller's dataset; later months use FRED's SP500 series averaged by month. Dividends after ${M.dividends_estimated_after ? ym(M.dividends_estimated_after.slice(0, 7)) : "–"} are estimated at the last known dividend yield.`),
      h("p", {}, "The broad dollar index before 2006 is FRED's discontinued goods-only broad index (TWEXBMTH), rescaled to match the current index (DTWEXBGS) over their first overlapping year.")) }),
    card({ title: "Download the data", body: h("div", { class: "prose" },
      h("p", {}, "Everything this page displays is in one file: ", h("a", { href: "data.json", download: "macro_health_data.json" }, "data.json"), ". Every chart also has a Data button and a CSV export."),
      h("p", {}, `Built ${M.generated_at.replace("T", " ")}. Latest market data ${dlong(M.latest_data)}.`)) })));
  if (sel) queueMicrotask(() => { const r = $("tr.sel"); if (r) { r.scrollIntoView({ block: "center" }); r.querySelectorAll("td").forEach((td) => (td.style.background = "var(--surface-2)")); } });
  return page;
}

/* ========================================================== METHODOLOGY */
function pageMethod() {
  const d = S.d;
  const rows = d.factors.flatMap((f) => f.parts.map((p) => ({ factor: f.label, measure: p.label, dir: p.direction, series: p.series })));
  const page = h("div");
  page.append(h("div", { class: "page-head" }, h("div", {}, h("div", { class: "eyebrow" }, "How it works"), h("h1", {}, "Methodology"))));
  page.append(h("div", { class: "grid g-2" },
    card({ title: "Scoring", body: h("div", { class: "prose" },
      h("h2", {}, "Measures"), h("p", {}, "Each factor is built from one to three published measures. Every measure is signed so that a higher value is better for stocks: rate cuts, a weaker dollar, inflation closer to 2% and looser bank lending all score higher."),
      h("h2", {}, "Scores"), h("p", {}, "A measure's score is its percentile against every earlier month (at least five years of history). A score of 80 means the reading is better than about 80% of the history known at that time. A factor score is the average of its measures. The Health Gauge is the equal-weighted average of the six factor scores."),
      h("h2", {}, "Grades"), h("p", {}, "A ≥ 70 (Strong), B ≥ 60 (Healthy), C ≥ 45 (Neutral), D ≥ 35 (Weak), F below 35 (Stressed). Cut-offs were set before running the backtest."),
      h("h2", {}, "No look-ahead"), h("p", {}, "A reading enters the history only after its usual publication delay: GDP 4 months after the quarter starts, corporate profits 6 months, the loan officer survey 2 months, CPI, M2, bank credit and the dollar 1 month. The top-line gauge today uses the newest published value of everything.")) }),
    card({ title: "Measures", body: table([{ k: "factor", label: "Factor" }, { k: "measure", label: "Measure" }, { k: "dir", label: "Direction" }, { k: "series", label: "Series", fmt: (x) => h("a", { href: `#sources/${x}` }, x) }], rows) })));
  page.append(h("div", { class: "grid g-2 mt" },
    card({ title: "Why these factors", body: h("div", { class: "prose" },
      ...d.factors.map((f) => h("p", {}, h("b", {}, f.label + ". "), f.why)),
      h("p", {}, h("b", {}, "On Fed lending and capital rules. "), "Changes to capital and reserve requirements are discrete rule changes with no daily series. Their effect shows up in how freely banks lend, so the Credit & Liquidity factor tracks it through the Fed's loan officer survey, total bank credit and M2.")) }),
    card({ title: "Known limitations", body: h("div", { class: "prose" }, h("ul", {},
      h("li", {}, "GDP and corporate profits are revised after release; history uses today's revised values."),
      h("li", {}, "Corporate profits cover all U.S. companies, not just the S&P 500. An S&P 500 EPS file from FactSet or LSEG can replace them (data/sp500_eps.csv)."),
      h("li", {}, "The broad dollar index is used in place of the ICE DXY, which is not freely available."),
      h("li", {}, "The backtest found no statistically reliable link between the gauge and future returns. Treat the gauge as a description of conditions, not a timing signal."),
      h("li", {}, "Research only. Not investment advice.")))})));
  return page;
}

/* =============================================================== ROUTER */
function render() {
  if (!S.d) return;
  S.charts.forEach((c) => c.dispose()); S.charts = [];
  const [route, arg] = (location.hash.slice(1) || "overview").split("/");
  const top = route === "factor" ? "factors" : route;
  document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.route === top));
  const app = $("#app"); app.innerHTML = "";
  const pages = { overview: pageOverview, factors: () => pageFactor(arg), factor: () => pageFactor(arg), markets: () => pageMarkets(arg), backtest: pageBacktest, sources: () => pageSources(arg), method: pageMethod };
  app.append((pages[route] || pageOverview)());
  if (S.route !== location.hash) window.scrollTo(0, 0);
  S.route = location.hash;
}
window.addEventListener("hashchange", render);
let rt; window.addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(() => S.charts.forEach((c) => c.resize()), 120); });

function initTheme() {
  let saved = null; try { saved = localStorage.getItem("mhm-theme"); } catch (e) {}
  if (saved) document.documentElement.dataset.theme = saved;
  $("#theme").onclick = () => {
    const dark = document.documentElement.dataset.theme ? document.documentElement.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    const next = dark ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("mhm-theme", next); } catch (e) {}
    render();
  };
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", render);
}

(async function main() {
  initTheme();
  $("#app").append(h("div", { class: "skeleton" }, "Loading data…"));
  try {
    const r = await fetch("data.json", { cache: "no-cache" });
    if (!r.ok) throw new Error(r.status);
    S.d = await r.json();
  } catch (e) {
    $("#app").innerHTML = ""; $("#app").append(h("div", { class: "callout warn" }, "Couldn't load data.json. Run `python -m mhd.export` to build it."));
    return;
  }
  const M = S.d.meta;
  $("#asof").textContent = `Data through ${dlong(M.latest_data)} · built ${M.generated_at.slice(0, 10)}`;
  $("#generated").textContent = `Built ${M.generated_at.replace("T", " ")} UTC`;
  render();
})();
