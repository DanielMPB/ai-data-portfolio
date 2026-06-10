"use strict";

/* ===================== navegação ===================== */
document.querySelectorAll(".nav-item").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".nav-item").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".tabpanel").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById(btn.dataset.tab).classList.add("active");
    if (btn.dataset.tab === "b3") loadMarketOverview();  // lazy: cotações reais
  });
});

/* ===================== helpers ===================== */
function setStatus(id, msg, kind = "") {
  const el = document.getElementById(id);
  el.textContent = msg || "";
  el.className = "status" + (kind ? " " + kind : "");
}
async function apiGet(url) {
  const r = await fetch(url);
  const b = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(b.detail || `HTTP ${r.status}`);
  return b;
}
async function apiPost(url, payload) {
  const r = await fetch(url, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
  });
  const b = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(b.detail || `HTTP ${r.status}`);
  return b;
}
const fmtNum = (n) => (n == null ? "—" : Number(n).toLocaleString("pt-BR"));

/* cor por score: verde / âmbar / vermelho */
function scoreColor(score) {
  if (score >= 70) return getComputedStyle(document.documentElement).getPropertyValue("--emerald").trim();
  if (score >= 40) return getComputedStyle(document.documentElement).getPropertyValue("--amber").trim();
  return getComputedStyle(document.documentElement).getPropertyValue("--rose").trim();
}
function situacaoClass(s) {
  if (!s) return "";
  if (s === "Ativa") return "ok";
  if (["Baixada", "Inapta", "Suspensa"].includes(s)) return "bad";
  return "warn";
}

/* ===================== DUE DILIGENCE ===================== */
let network = null;
let sampleNetwork = null;
const GRUPOS = {
  Alvo: { color: { background: "#6366f1", border: "#a855f7" }, font: { color: "#fff" }, shape: "dot", size: 30, borderWidth: 3,
          shadow: { enabled: true, color: "rgba(99,102,241,0.7)", size: 24 } },
  SocioPF: { color: { background: "#fbbf24", border: "#f59e0b" }, font: { color: "#1c1917" }, shape: "dot", size: 15 },
  SocioPJ: { color: { background: "#a855f7", border: "#7e22ce" }, font: { color: "#fff" }, shape: "diamond", size: 16 },
  EmpresaRelacionada: { color: { background: "#3f3f46", border: "#52525b" }, font: { color: "#e4e4e7" }, shape: "dot", size: 13 },
};

// Cria uma rede Vis.js (Barnes-Hut) em `container` e corrige o tamanho do canvas.
function criarRede(container, grafo) {
  const nodes = new vis.DataSet(grafo.nodes.map((n) => ({
    id: n.id, label: n.label, group: n.group, title: `${n.label}\n${n.id}`,
  })));
  const edges = new vis.DataSet(grafo.edges.map((e) => ({
    from: e.from, to: e.to, label: e.label, arrows: "to",
  })));
  const options = {
    groups: GRUPOS,
    nodes: { font: { size: 12, face: "Inter" } },
    edges: {
      color: { color: "#3f3f46", highlight: "#6366f1", hover: "#818cf8" },
      font: { color: "#71717a", size: 9, strokeWidth: 0, face: "JetBrains Mono" },
      width: 1, smooth: { type: "continuous" },
    },
    physics: {
      // Barnes-Hut: repele as empresas de 2º grau para as extremidades,
      // mantendo os sócios-conectores centralizados.
      solver: "barnesHut",
      barnesHut: { gravitationalConstant: -9000, centralGravity: 0.3, springLength: 130, springConstant: 0.04, damping: 0.09 },
      stabilization: { iterations: 200 },
    },
    interaction: { hover: true, tooltipDelay: 120 },
    autoResize: true,
  };
  const net = new vis.Network(container, { nodes, edges }, options);
  // O canvas pode nascer com altura errada se o painel acabou de ficar visível.
  const ajustar = () => { try { net.setSize("100%", "100%"); net.redraw(); } catch (e) {} };
  requestAnimationFrame(ajustar);
  net.once("stabilizationIterationsDone", () => { ajustar(); net.fit({ animation: false }); });
  return net;
}

function renderGrafo(grafo) {
  if (network) network.destroy();
  network = criarRede(document.getElementById("grafo"), grafo);
}

// ----- Grafo de amostra: redes REAIS de 10 empresas com muitas ligações -----
async function renderSample() {
  const c = document.getElementById("grafoSample");
  if (!c || sampleNetwork) return;
  const cap = document.getElementById("sampleCaption");
  try {
    const d = await apiGet("/api/v1/amostra/rede");
    if (!d.grafo.nodes.length) throw new Error("vazio");
    sampleNetwork = criarRede(c, d.grafo);
    if (cap) cap.textContent = d.empresas.length === 1
      ? `exemplo real: ${d.empresas[0]} · busque um CNPJ para investigar outra`
      : `${d.empresas.length} empresas reais com redes densas · busque um CNPJ para investigar`;
  } catch (e) {
    if (cap) cap.textContent = "busque um CNPJ para ver a rede societária";
  }
}

// ----- Histórico de buscas (localStorage, persiste entre sessões) -----
const HIST_KEY = "nexus_buscas_recentes";
function getHist() { try { return JSON.parse(localStorage.getItem(HIST_KEY) || "[]"); } catch { return []; } }
function addHist(entry) {
  let h = getHist().filter((x) => x.cnpj !== entry.cnpj);
  h.unshift(entry);
  localStorage.setItem(HIST_KEY, JSON.stringify(h.slice(0, 12)));
  renderHistorico();
}
function _classeScore(s) { return s >= 70 ? "ok" : s >= 40 ? "warn" : "bad"; }
function renderHistorico() {
  const el = document.getElementById("ddHist");
  if (!el) return;
  const h = getHist();
  if (!h.length) {
    el.innerHTML = '<div class="hist-empty">Suas buscas aparecerão aqui em cards — e ficam salvas mesmo ao recarregar a página.</div>';
    return;
  }
  el.innerHTML = h.map((x) => {
    const cls = _classeScore(x.score);
    const cor = x.score >= 70 ? "var(--emerald)" : x.score >= 40 ? "var(--amber)" : "var(--rose)";
    const sit = x.situacao ? `<span class="badge ${situacaoClass(x.situacao)}">${escHtml(x.situacao)}</span>` : "";
    return `<button class="hist-card" data-cnpj="${x.cnpj}">
      <div class="hc-top">
        <span class="hc-nome">${escHtml(x.nome || x.cnpj)}</span>
        <span class="hc-score" style="color:${cor}">${x.score ?? "—"}</span>
      </div>
      <div class="hc-meta"><span class="mono hc-cnpj">${x.cnpj}</span>${sit}</div>
      <div class="hc-foot"><span class="dot-sm ${cls}"></span>${escHtml(x.classe || "")} · ${x.satelites ?? 0} satélites · grupo ${x.grupo ?? "—"}</div>
    </button>`;
  }).join("");
  el.querySelectorAll(".hist-card").forEach((b) =>
    b.addEventListener("click", () => { document.getElementById("cnpjInput").value = b.dataset.cnpj; buscarEmpresa(); }));
}

function renderRisco(risco) {
  const gauge = document.getElementById("ddGauge");
  const cor = scoreColor(risco.nexus_score);
  gauge.style.setProperty("--val", risco.nexus_score);
  gauge.style.setProperty("--gauge-color", cor);
  document.getElementById("ddScore").textContent = risco.nexus_score;
  document.getElementById("ddClass").textContent = risco.classificacao;
  document.getElementById("ddClass").style.color = cor;
  document.getElementById("ddSat").textContent = `${risco.satelites_analisadas} empresa(s)-satélite na teia`;
  const penal = document.getElementById("ddPenal");
  penal.innerHTML = risco.penalidades.length
    ? risco.penalidades.map((p) =>
        `<div class="penal"><span class="pen-pts">${p.pontos}</span><span>Layer ${p.camada} · ${p.motivo}</span></div>`).join("")
    : `<div class="penal-ok">✓ Nenhum gatilho de risco acionado.</div>`;
}

function renderMining(gm) {
  const g = gm.grupo_economico;
  document.getElementById("gmGrupo").textContent = fmtNum(g.tamanho);
  document.getElementById("gmEmp").textContent = fmtNum(g.empresas);
  document.getElementById("gmSoc").textContent = fmtNum(g.socios);
  document.getElementById("gmArt").textContent = fmtNum(gm.pontos_articulacao);
  const hub = document.getElementById("gmHub");
  if (gm.socio_conector_central) {
    const h = gm.socio_conector_central;
    hub.innerHTML = `<div class="hub-name">${h.nome || h.id}</div>
      <div class="hub-meta">${h.id} · ${h.vinculos} vínculos · centralidade ${h.centralidade_grau}</div>`;
  } else {
    hub.innerHTML = `<span class="muted small">Sem sócios conectores na teia.</span>`;
  }
}

async function buscarEmpresa() {
  const cnpj = document.getElementById("cnpjInput").value.trim();
  if (!cnpj) return;
  setStatus("ddStatus", "Compilando registros e mapeando vínculos", "loading");
  try {
    const d = await apiGet(`/api/v1/empresa/${encodeURIComponent(cnpj)}`);
    document.getElementById("ddEmpty").classList.add("hidden");
    document.getElementById("ddBody").classList.remove("hidden");
    addHist({
      cnpj: d.empresa_principal.cnpj,
      nome: d.empresa_principal.razao_social,
      situacao: d.empresa_principal.situacao,
      score: d.risco.nexus_score,
      classe: d.risco.classificacao,
      satelites: d.risco.satelites_analisadas,
      grupo: d.graph_mining.grupo_economico.tamanho,
      ts: Date.now(),
    });
    document.getElementById("ddNome").textContent = d.empresa_principal.razao_social || "(razão social indisponível)";
    document.getElementById("ddCnpj").textContent = d.empresa_principal.cnpj;
    const sit = document.getElementById("ddSituacao");
    sit.textContent = d.empresa_principal.situacao || "—";
    sit.className = "badge " + situacaoClass(d.empresa_principal.situacao);
    renderRisco(d.risco);
    renderMining(d.graph_mining);
    document.getElementById("ddGraphMeta").textContent = `${d.grafo.nodes.length} nós · ${d.grafo.edges.length} vínculos`;
    renderGrafo(d.grafo);
    setStatus("ddStatus", "");
  } catch (e) {
    setStatus("ddStatus", e.message, "error");
  }
}
document.getElementById("btnBuscar").addEventListener("click", buscarEmpresa);
document.getElementById("cnpjInput").addEventListener("keydown", (e) => { if (e.key === "Enter") buscarEmpresa(); });

/* ===================== CALCULADORA RI ===================== */
function escHtml(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
function renderInline(s) {
  return escHtml(s)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>")
    .replace(/`(.+?)`/g, "<code>$1</code>");
}
function accentOf(title) {
  const t = title.toUpperCase();
  if (t.includes("EVITAR") || t.includes("CAUTELA") || t.includes("VULNERAB") || t.includes("ATEN")) return "rose";
  if (t.includes("OPORTUNID") || t.includes("MELHORES") || t.includes("COMPRA")) return "emerald";
  if (t.includes("ESTRATÉG") || t.includes("ESTRATEG")) return "cyan";
  if (t.includes("PLANO") || t.includes("RECOMEND")) return "emerald";
  if (t.includes("RESERVA") || t.includes("BLINDAGEM") || t.includes("CONTING")) return "cyan";
  if (t.includes("RATING") || t.includes("MATURIDADE")) return "amber";
  return "indigo";
}
function renderMarkdown(md) {
  const linhas = (md || "").split("\n");
  let html = "", listType = null, inSec = false;
  const closeList = () => { if (listType) { html += `</${listType}>`; listType = null; } };
  const openList = (t) => { if (listType !== t) { closeList(); html += `<${t}>`; listType = t; } };
  const closeSec = () => { closeList(); if (inSec) { html += "</div></section>"; inSec = false; } };
  for (const raw of linhas) {
    const ln = raw.trim();
    if (raw.startsWith("# ")) {
      closeSec();
      const title = raw.slice(2).trim();
      html += `<section class="md-sec md-${accentOf(title)}"><h1>${renderInline(title)}</h1><div class="md-body">`;
      inSec = true;
    } else if (/^[-*]\s+/.test(ln)) {
      openList("ul");
      html += `<li>${renderInline(ln.replace(/^[-*]\s+/, ""))}</li>`;
    } else if (/^\d+\.\s+/.test(ln)) {
      openList("ol");
      html += `<li>${renderInline(ln.replace(/^\d+\.\s+/, ""))}</li>`;
    } else if (ln) {
      closeList();
      html += `<p>${renderInline(ln)}</p>`;
    }
  }
  closeSec();
  return html;
}
document.getElementById("riForm").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const fd = new FormData(ev.target);
  const payload = {
    setor: fd.get("setor"),
    liquidez_imediata: parseFloat(fd.get("liquidez_imediata")),
    reserva_contingencia: parseFloat(fd.get("reserva_contingencia")),
    disponibilidade_liquida_protecao: parseFloat(fd.get("disponibilidade_liquida_protecao")),
    grau_cobertura_crise: parseFloat(fd.get("grau_cobertura_crise")),
    prazo_medio_recebimento: parseInt(fd.get("prazo_medio_recebimento"), 10),
    prazo_medio_pagamento: parseInt(fd.get("prazo_medio_pagamento"), 10),
  };
  setStatus("riStatus", "Sintetizando relatório via IA — pode levar até ~1 min", "loading");
  try {
    const d = await apiPost("/api/v1/calculator/ir", payload);
    document.getElementById("riSectorStats").classList.add("hidden");
    document.getElementById("riResult").classList.remove("hidden");
    const RATING_INFO = {
      A: { cor: "#34d399", txt: "Excelente blindagem" },
      B: { cor: "#818cf8", txt: "Sólido" },
      C: { cor: "#fbbf24", txt: "Atenção" },
      D: { cor: "#fb7185", txt: "Risco de insolvência" },
    };
    const info = RATING_INFO[d.rating] || RATING_INFO.C;
    const ratingEl = document.getElementById("riRating");
    ratingEl.textContent = d.rating;
    ratingEl.style.color = info.cor;
    ratingEl.style.borderColor = info.cor;
    ratingEl.style.background = info.cor + "1f"; // ~12% alpha
    document.getElementById("riRatingLabel").textContent = info.txt;
    document.getElementById("riRatingLabel").style.color = info.cor;
    document.getElementById("riReport").innerHTML = renderMarkdown(d.relatorio_markdown);
    setStatus("riStatus", `Modelo: ${d.modelo}`);
  } catch (e) {
    setStatus("riStatus", e.message, "error");
  }
});

/* ----- Estatísticas (sintéticas) por setor: radar + ciclo de caixa ----- */
// Dados médios plausíveis por segmento. liquidez (índice), cobertura (meses),
// margem (%), pmr/pmp (dias).
const SETOR_STATS = {
  "Varejo":               { liquidez: 0.45, cobertura: 2.0, margem: 10, pmr: 25, pmp: 40 },
  "Indústria":            { liquidez: 0.70, cobertura: 4.0, margem: 16, pmr: 50, pmp: 45 },
  "Serviços":             { liquidez: 0.80, cobertura: 3.0, margem: 20, pmr: 35, pmp: 25 },
  "Tecnologia":           { liquidez: 1.20, cobertura: 6.0, margem: 28, pmr: 40, pmp: 30 },
  "Agronegócio":          { liquidez: 0.60, cobertura: 5.0, margem: 18, pmr: 60, pmp: 55 },
  "Construção Civil":     { liquidez: 0.40, cobertura: 3.0, margem: 14, pmr: 70, pmp: 60 },
  "Saúde":                { liquidez: 0.90, cobertura: 4.0, margem: 22, pmr: 45, pmp: 35 },
  "Educação":             { liquidez: 0.70, cobertura: 4.0, margem: 19, pmr: 20, pmp: 30 },
  "Energia":              { liquidez: 1.00, cobertura: 7.0, margem: 25, pmr: 50, pmp: 45 },
  "Financeiro":           { liquidez: 1.40, cobertura: 9.0, margem: 32, pmr: 30, pmp: 40 },
  "Logística e Transporte": { liquidez: 0.55, cobertura: 2.5, margem: 12, pmr: 45, pmp: 35 },
  "Alimentos e Bebidas":  { liquidez: 0.60, cobertura: 3.0, margem: 15, pmr: 28, pmp: 38 },
};
const RADAR_MAX = { liquidez: 1.5, cobertura: 10, margem: 35 };

function _pt(cx, cy, ang, r) {
  const a = (ang * Math.PI) / 180;
  return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
}
function buildRadar(s) {
  const W = 280, H = 220, cx = 140, cy = 108, R = 78;
  const eixos = [
    { ang: -90, lbl: "Liquidez", val: s.liquidez.toFixed(2), n: Math.min(1, s.liquidez / RADAR_MAX.liquidez) },
    { ang: 30, lbl: "Cobertura", val: s.cobertura + "m", n: Math.min(1, s.cobertura / RADAR_MAX.cobertura) },
    { ang: 150, lbl: "Margem", val: s.margem + "%", n: Math.min(1, s.margem / RADAR_MAX.margem) },
  ];
  let svg = `<svg viewBox="0 0 ${W} ${H}" class="radar-svg">`;
  // anéis da teia
  [0.25, 0.5, 0.75, 1].forEach((f) => {
    const pts = eixos.map((e) => _pt(cx, cy, e.ang, R * f).map((v) => v.toFixed(1)).join(",")).join(" ");
    svg += `<polygon points="${pts}" fill="none" stroke="#333" stroke-width="1"/>`;
  });
  // eixos
  eixos.forEach((e) => {
    const [x, y] = _pt(cx, cy, e.ang, R);
    svg += `<line x1="${cx}" y1="${cy}" x2="${x.toFixed(1)}" y2="${y.toFixed(1)}" stroke="#333" stroke-width="1"/>`;
  });
  // área de dados
  const dpts = eixos.map((e) => _pt(cx, cy, e.ang, R * e.n).map((v) => v.toFixed(1)).join(",")).join(" ");
  svg += `<polygon points="${dpts}" fill="rgba(139,92,246,0.30)" stroke="#a78bfa" stroke-width="2" filter="url(#glow)"/>`;
  eixos.forEach((e) => {
    const [x, y] = _pt(cx, cy, e.ang, R * e.n);
    svg += `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="3" fill="#c4b5fd"/>`;
  });
  // rótulos
  eixos.forEach((e) => {
    const [lx, ly] = _pt(cx, cy, e.ang, R + 18);
    const anchor = e.ang === -90 ? "middle" : e.ang === 30 ? "start" : "end";
    svg += `<text x="${lx.toFixed(1)}" y="${ly.toFixed(1)}" text-anchor="${anchor}" class="radar-lbl">${e.lbl}</text>`;
    svg += `<text x="${lx.toFixed(1)}" y="${(ly + 13).toFixed(1)}" text-anchor="${anchor}" class="radar-val">${e.val}</text>`;
  });
  svg += `<defs><filter id="glow"><feGaussianBlur stdDeviation="2.5" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>`;
  svg += `</svg>`;
  return svg;
}
// Métricas e estatísticas de mercado (descritivas, sem juízo de valor).
const METRICAS = [
  { k: "liquidez", lbl: "Liquidez", fmt: (v) => v.toFixed(2), max: 1.5 },
  { k: "cobertura", lbl: "Cobertura", fmt: (v) => v + "m", max: 10 },
  { k: "margem", lbl: "Margem", fmt: (v) => v + "%", max: 35 },
  { k: "pmr", lbl: "PMR", fmt: (v) => v + "d", max: 90 },
  { k: "pmp", lbl: "PMP", fmt: (v) => v + "d", max: 90 },
];
function mercado(k) {
  const vals = Object.values(SETOR_STATS).map((s) => s[k]);
  return { avg: vals.reduce((a, b) => a + b, 0) / vals.length, min: Math.min(...vals), max: Math.max(...vals) };
}

let setorAtual = "Varejo";
let rankMetric = "liquidez";

// 1) Ranking dos setores por uma métrica (setor atual destacado).
function renderRanking() {
  const el = document.getElementById("riRanking");
  const tg = document.getElementById("riRankToggle");
  if (!el) return;
  const m = METRICAS.find((x) => x.k === rankMetric);
  const ent = Object.entries(SETOR_STATS).map(([nome, s]) => ({ nome, v: s[rankMetric] })).sort((a, b) => b.v - a.v);
  const maxV = Math.max(...ent.map((e) => e.v));
  el.innerHTML = ent.map((e) => `
    <div class="rank-row ${e.nome === setorAtual ? "sel" : ""}">
      <span class="rank-name">${escHtml(e.nome)}</span>
      <div class="rank-track"><div class="rank-bar" style="width:${(e.v / maxV * 100).toFixed(1)}%"></div></div>
      <span class="rank-val">${m.fmt(e.v)}</span>
    </div>`).join("");
  if (tg) {
    tg.innerHTML = METRICAS.slice(0, 3).map((x) =>
      `<button class="mini-btn ${x.k === rankMetric ? "on" : ""}" data-k="${x.k}">${x.lbl}</button>`).join("");
    tg.querySelectorAll(".mini-btn").forEach((b) =>
      b.addEventListener("click", () => { rankMetric = b.dataset.k; renderRanking(); }));
  }
}

// 2) Setor vs. média do mercado (barra do setor + tick na média).
function renderVsMedia() {
  const el = document.getElementById("riVsMedia");
  if (!el) return;
  const s = SETOR_STATS[setorAtual];
  el.innerHTML = METRICAS.map((m) => {
    const mk = mercado(m.k);
    const w = Math.min(100, s[m.k] / m.max * 100);
    const avgPos = Math.min(100, mk.avg / m.max * 100);
    const avgFmt = m.k === "liquidez" ? mk.avg.toFixed(2) : mk.avg.toFixed(0) + (m.k === "cobertura" ? "m" : m.k === "margem" ? "%" : "d");
    return `<div class="mb-row">
      <div class="mb-head"><span>${m.lbl}</span><span class="mono">${m.fmt(s[m.k])} <span class="mb-avg">· média ${avgFmt}</span></span></div>
      <div class="mb-track"><div class="mb-bar" style="width:${w.toFixed(1)}%"></div><div class="mb-tick" style="left:${avgPos.toFixed(1)}%"></div></div>
    </div>`;
  }).join("");
}

// 3) Faixa de mercado (mín–máx) com marcador na posição do setor.
function renderFaixa() {
  const el = document.getElementById("riFaixa");
  if (!el) return;
  const s = SETOR_STATS[setorAtual];
  el.innerHTML = METRICAS.map((m) => {
    const mk = mercado(m.k);
    const pos = mk.max > mk.min ? (s[m.k] - mk.min) / (mk.max - mk.min) * 100 : 50;
    return `<div class="fx-row">
      <div class="fx-head"><span>${m.lbl}</span><span class="mono">${m.fmt(s[m.k])}</span></div>
      <div class="fx-track"><div class="fx-marker" style="left:${pos.toFixed(1)}%"></div></div>
      <div class="fx-ends"><span>mín ${m.fmt(mk.min)}</span><span>máx ${m.fmt(mk.max)}</span></div>
    </div>`;
  }).join("");
}

// 4) Prazos médios PMR e PMP (sem veredito).
function renderPmrPmp() {
  const el = document.getElementById("riPmrPmp");
  if (!el) return;
  const s = SETOR_STATS[setorAtual];
  const max = Math.max(90, s.pmr, s.pmp);
  el.innerHTML = `
    <div class="ciclo-row"><div class="ciclo-head"><span>Recebimento · PMR</span><span class="mono">${s.pmr} dias</span></div>
      <div class="ciclo-track"><div class="ciclo-bar bar-pmr" style="width:${(s.pmr / max * 100).toFixed(1)}%"></div></div></div>
    <div class="ciclo-row"><div class="ciclo-head"><span>Pagamento · PMP</span><span class="mono">${s.pmp} dias</span></div>
      <div class="ciclo-track"><div class="ciclo-bar bar-pmp" style="width:${(s.pmp / max * 100).toFixed(1)}%"></div></div></div>
    <div class="pmr-note">Prazos médios praticados no setor (dias).</div>`;
}

function renderSetorStats(setor) {
  setorAtual = setor;
  const t = document.getElementById("riSectorTitle");
  if (t) t.innerHTML = `Estatísticas do setor: <b>${escHtml(setor)}</b>`;
  const r = document.getElementById("riRadar");
  if (r) r.innerHTML = buildRadar(SETOR_STATS[setor] || SETOR_STATS["Serviços"]);
  renderRanking();
  renderVsMedia();
  renderFaixa();
  renderPmrPmp();
}
(function initSetorStats() {
  const sel = document.querySelector('#riForm select[name="setor"]');
  if (!sel) return;
  renderSetorStats(sel.value);
  sel.addEventListener("change", () => renderSetorStats(sel.value));
})();

/* ===================== RADAR DE MERCADO ===================== */
let b3ChartObj = null, b3VolObj = null, b3MonObj = null;
function renderVolume(historico) {
  const cv = document.getElementById("b3Volume");
  if (!cv || !historico || historico.length < 2 || !window.Chart) return;
  const cores = historico.map((h, i) =>
    i > 0 && h.fechamento >= historico[i - 1].fechamento ? "rgba(52,211,153,0.55)" : "rgba(251,113,133,0.55)");
  if (b3VolObj) b3VolObj.destroy();
  b3VolObj = new Chart(cv.getContext("2d"), {
    type: "bar",
    data: { labels: historico.map((h) => h.data), datasets: [{ data: historico.map((h) => h.volume || 0), backgroundColor: cores, borderWidth: 0, barPercentage: 1, categoryPercentage: 1 }] },
    options: { responsive: true, maintainAspectRatio: false, animation: false,
      plugins: { legend: { display: false }, tooltip: { enabled: true, displayColors: false, callbacks: { title: (it) => it[0].label, label: (c) => "Vol: " + Number(c.parsed.y).toLocaleString("pt-BR") } } },
      scales: { x: { display: false }, y: { display: false } } },
  });
}
function renderMonthly(historico) {
  const cv = document.getElementById("b3Monthly");
  if (!cv || !historico || historico.length < 2 || !window.Chart) return;
  const byMonth = {};
  historico.forEach((h) => { byMonth[h.data.slice(0, 7)] = h.fechamento; });
  const meses = Object.keys(byMonth).sort();
  const MES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
  const rows = [];
  for (let i = 1; i < meses.length; i++) {
    rows.push({ lbl: MES[+meses[i].slice(5, 7) - 1], ret: +((byMonth[meses[i]] / byMonth[meses[i - 1]] - 1) * 100).toFixed(2) });
  }
  if (b3MonObj) b3MonObj.destroy();
  b3MonObj = new Chart(cv.getContext("2d"), {
    type: "bar",
    data: { labels: rows.map((r) => r.lbl), datasets: [{ data: rows.map((r) => r.ret), backgroundColor: rows.map((r) => r.ret >= 0 ? "rgba(52,211,153,0.7)" : "rgba(251,113,133,0.7)"), borderWidth: 0, borderRadius: 3 }] },
    options: { responsive: true, maintainAspectRatio: false, animation: false,
      plugins: { legend: { display: false }, tooltip: { enabled: true, displayColors: false, callbacks: { label: (c) => (c.parsed.y >= 0 ? "+" : "") + c.parsed.y + "%" } } },
      scales: { x: { grid: { display: false }, ticks: { color: "#71717a", font: { size: 9 } } },
        y: { display: true, position: "right", grid: { color: "rgba(255,255,255,0.04)" }, ticks: { color: "#71717a", font: { size: 9 }, maxTicksLimit: 4, callback: (v) => v + "%" } } } },
  });
}
function fmtCap(v) {
  if (v == null) return "—";
  if (v >= 1e12) return "R$ " + (v / 1e12).toFixed(2) + " tri";
  if (v >= 1e9) return "R$ " + (v / 1e9).toFixed(2) + " bi";
  if (v >= 1e6) return "R$ " + (v / 1e6).toFixed(1) + " mi";
  return "R$ " + Number(v).toLocaleString("pt-BR");
}
function renderPriceChart(historico, up) {
  const cv = document.getElementById("b3Chart");
  if (!cv || !historico || historico.length < 2 || !window.Chart) return;
  const cor = up ? "#34d399" : "#fb7185";
  const ctx = cv.getContext("2d");
  const grad = ctx.createLinearGradient(0, 0, 0, 300);
  grad.addColorStop(0, up ? "rgba(52,211,153,0.22)" : "rgba(251,113,133,0.20)");
  grad.addColorStop(1, "rgba(0,0,0,0)");
  if (b3ChartObj) b3ChartObj.destroy();
  b3ChartObj = new Chart(ctx, {
    type: "line",
    data: { labels: historico.map((h) => h.data), datasets: [{ data: historico.map((h) => h.fechamento), borderColor: cor, borderWidth: 2, pointRadius: 0, fill: true, backgroundColor: grad, tension: 0.2 }] },
    options: { responsive: true, maintainAspectRatio: false, animation: false,
      interaction: { mode: "index", intersect: false },
      plugins: { legend: { display: false }, tooltip: { enabled: true, displayColors: false,
        callbacks: { title: (it) => it[0].label, label: (c) => "R$ " + c.parsed.y } } },
      scales: { x: { display: false },
        y: { display: true, position: "right", grid: { color: "rgba(255,255,255,0.04)" }, ticks: { color: "#71717a", font: { size: 9 }, maxTicksLimit: 5 } } } },
  });
}
function renderAcao(d) {
  document.getElementById("b3Empty").classList.add("hidden");
  document.getElementById("b3DayReport").classList.add("hidden");
  document.getElementById("b3Result").classList.remove("hidden");
  document.getElementById("b3Nome").textContent = d.nome;
  document.getElementById("b3Ticker").textContent = d.ticker;
  document.getElementById("b3Preco").textContent = d.preco_atual != null ? `R$ ${d.preco_atual}` : "—";
  const vEl = document.getElementById("b3Var");
  if (d.variacao_dia != null) {
    vEl.textContent = `${d.variacao_dia >= 0 ? "▲ +" : "▼ "}${d.variacao_dia}% no dia`;
    vEl.className = "b3-var mono " + (d.variacao_dia >= 0 ? "up" : "down");
  } else vEl.textContent = "";
  const set = (id, val) => { document.getElementById(id).textContent = val; };
  const v6 = document.getElementById("b3Var6m");
  v6.textContent = d.variacao_periodo != null ? `${d.variacao_periodo >= 0 ? "+" : ""}${d.variacao_periodo}%` : "—";
  v6.className = "mono " + (d.variacao_periodo >= 0 ? "up" : "down");
  set("b3Max", d.maxima_periodo != null ? "R$ " + d.maxima_periodo : "—");
  set("b3Min", d.minima_periodo != null ? "R$ " + d.minima_periodo : "—");
  set("b3PL", d.multiplos.pl ?? "—");
  set("b3DY", d.multiplos.dy != null ? d.multiplos.dy + "%" : "—");
  set("b3ROE", d.multiplos.roe != null ? d.multiplos.roe + "%" : "—");
  set("b3Cap", fmtCap(d.valor_mercado));
  renderPriceChart(d.historico, (d.variacao_periodo ?? 0) >= 0);
  renderVolume(d.historico);
  renderMonthly(d.historico);
}
async function carregarAcao(ticker) {
  const d = await apiGet(`/api/v1/market/stock/${encodeURIComponent(ticker)}`);
  renderAcao(d);
  return d;
}
document.getElementById("btnAcao").addEventListener("click", async () => {
  const t = document.getElementById("tickerInput").value.trim();
  if (!t) return;
  setStatus("b3Status", "Buscando cotação", "loading");
  document.getElementById("b3Advisor").classList.add("hidden");
  try {
    const d = await carregarAcao(t);
    setStatus("b3Status", `${d.historico.length} pregões (6 meses)`);
  } catch (e) { setStatus("b3Status", e.message, "error"); }
});
async function carregarRecomendacaoDia() {
  document.getElementById("b3Empty").classList.add("hidden");
  document.getElementById("b3Result").classList.add("hidden");
  const card = document.getElementById("b3DayReport");
  card.classList.remove("hidden");
  document.getElementById("b3RecReport").innerHTML = '<div class="muted small">Analisando dezenas de ações da B3 e gerando as recomendações do dia…</div>';
  setStatus("b3Status", "Gerando recomendações do dia via IA — pode levar alguns segundos", "loading");
  try {
    const d = await apiGet("/api/v1/market/recomendacao-dia");
    document.getElementById("b3RecReport").innerHTML = renderMarkdown(d.relatorio_markdown);
    document.getElementById("b3RecModelo").textContent = `${d.universo} ações analisadas · ${d.modelo}`;
    setStatus("b3Status", "");
  } catch (e) {
    document.getElementById("b3RecReport").innerHTML = `<div class="ciclo-note bad">${e.message}</div>`;
    setStatus("b3Status", e.message, "error");
  }
}
document.getElementById("btnAdvisor").addEventListener("click", async () => {
  const t = document.getElementById("tickerInput").value.trim();
  if (!t) { carregarRecomendacaoDia(); return; }  // sem ticker → recomendação do dia
  setStatus("b3Status", "Carregando cotação e consultando IA — pode levar alguns segundos", "loading");
  document.getElementById("b3Advisor").classList.add("hidden");
  try {
    await carregarAcao(t);
    const d = await apiPost("/api/v1/market/analyze", { ticker: t });
    const adv = document.getElementById("b3Advisor"); adv.classList.remove("hidden");
    const ver = document.getElementById("b3Veredito");
    ver.textContent = d.veredito === "STRONG BUY" ? "COMPRA FORTE" : d.veredito === "SELL" ? "VENDA" : "MANTER";
    ver.className = "veredito " + (d.veredito === "SELL" ? "sell" : d.veredito === "HOLD" ? "hold" : "buy");
    document.getElementById("b3Tese").textContent = d.tese;
    setStatus("b3Status", `Modelo: ${d.modelo}`);
  } catch (e) { setStatus("b3Status", e.message, "error"); }
});

/* ----- Panorama de mercado (estado inicial do Radar) ----- */
// 1) Painel macro (dados reais via /market/overview)
function fmtVar(v) {
  if (v == null) return "";
  const cls = v >= 0 ? "up" : "down";
  return `<span class="mc-var ${cls}">${v >= 0 ? "+" : ""}${v}%</span>`;
}
function renderMacro(macro) {
  const el = document.getElementById("b3Macro");
  if (!el) return;
  el.innerHTML = macro.map((m) => `
    <div class="macro-card">
      <div class="mc-nome">${m.nome}</div>
      <div class="mc-valor mono">${m.valor != null ? Number(m.valor).toLocaleString("pt-BR") : "—"}<span class="mc-uni">${m.unidade || ""}</span></div>
      ${fmtVar(m.variacao)}
    </div>`).join("");
}
// 2) Heatmap setorial (sintético/mock — MVP)
const HEATMAP_SETORES = [
  { nome: "Petróleo & Gás", base: 1.4, vol: 5 }, { nome: "Bancos", base: 0.6, vol: 5 },
  { nome: "Mineração", base: -0.8, vol: 4 }, { nome: "Energia", base: 0.4, vol: 3 },
  { nome: "Varejo", base: -1.3, vol: 3 }, { nome: "Siderurgia", base: -0.4, vol: 2 },
  { nome: "Saúde", base: 0.7, vol: 2 }, { nome: "Consumo", base: 0.3, vol: 2 },
  { nome: "Tecnologia", base: 1.0, vol: 2 }, { nome: "Agro", base: 0.5, vol: 3 },
  { nome: "Imobiliário", base: -0.6, vol: 1 }, { nome: "Telecom", base: -0.2, vol: 1 },
];
function renderHeatmap() {
  const el = document.getElementById("b3Heatmap");
  if (!el) return;
  el.innerHTML = HEATMAP_SETORES.map((s) => {
    const chg = +(s.base + (Math.random() - 0.5) * 0.8).toFixed(2); // jitter "do dia"
    const up = chg >= 0;
    const inten = Math.min(0.85, 0.18 + Math.abs(chg) / 3.5);
    const bg = up ? `rgba(16,185,129,${inten})` : `rgba(244,63,94,${inten})`;
    return `<div class="hm-block" style="background:${bg}">
      <span class="hm-nome">${s.nome}</span>
      <span class="hm-var">${up ? "+" : ""}${chg}%</span>
    </div>`;
  }).join("");
}
// 3) Watchlist com sparkline (Chart.js)
function renderWatchlist(watch) {
  const el = document.getElementById("b3Watchlist");
  if (!el) return;
  el.innerHTML = watch.map((w, i) => {
    const cls = (w.variacao ?? 0) >= 0 ? "up" : "down";
    return `<button class="wl-card" data-ticker="${w.ticker}">
      <div class="wl-top">
        <div><div class="wl-ticker">${w.ticker}</div><div class="wl-nome">${w.nome}</div></div>
        <div class="wl-right"><div class="wl-preco mono">${w.preco != null ? "R$ " + w.preco : "—"}</div>${fmtVar(w.variacao)}</div>
      </div>
      <canvas class="wl-spark" id="spark${i}" height="36"></canvas>
    </button>`;
  }).join("");
  // sparklines
  watch.forEach((w, i) => {
    const cv = document.getElementById("spark" + i);
    if (!cv || !w.sparkline || w.sparkline.length < 2 || !window.Chart) return;
    const cor = (w.variacao ?? 0) >= 0 ? "#34d399" : "#fb7185";
    new Chart(cv.getContext("2d"), {
      type: "line",
      data: { labels: w.sparkline.map((_, j) => j), datasets: [{ data: w.sparkline, borderColor: cor, borderWidth: 1.6, pointRadius: 0, fill: false, tension: 0.35 }] },
      options: { responsive: true, maintainAspectRatio: false, animation: false,
        plugins: { legend: { display: false }, tooltip: { enabled: false } },
        scales: { x: { display: false }, y: { display: false } } },
    });
  });
  el.querySelectorAll(".wl-card").forEach((b) => b.addEventListener("click", () => {
    document.getElementById("tickerInput").value = b.dataset.ticker;
    document.getElementById("btnAcao").click();
  }));
}
// 4) Ibovespa — linha de 3 meses (Chart.js, com gradiente)
let ibovChartObj = null;
function renderIbov(serie) {
  const cv = document.getElementById("ibovChart");
  if (!cv || !serie || serie.length < 2 || !window.Chart) return;
  const last = serie[serie.length - 1], first = serie[0];
  const pv = ((last / first - 1) * 100).toFixed(2);
  const up = last >= first;
  const lbl = document.getElementById("ibovVar");
  if (lbl) { lbl.textContent = `${up ? "+" : ""}${pv}% no período`; lbl.className = "mono small " + (up ? "mc-var up" : "mc-var down"); }
  const ctx = cv.getContext("2d");
  const grad = ctx.createLinearGradient(0, 0, 0, 170);
  grad.addColorStop(0, "rgba(99,102,241,0.35)");
  grad.addColorStop(1, "rgba(99,102,241,0)");
  if (ibovChartObj) ibovChartObj.destroy();
  ibovChartObj = new Chart(ctx, {
    type: "line",
    data: { labels: serie.map((_, i) => i), datasets: [{ data: serie, borderColor: "#818cf8", borderWidth: 2, pointRadius: 0, fill: true, backgroundColor: grad, tension: 0.25 }] },
    options: { responsive: true, maintainAspectRatio: false, animation: false,
      plugins: { legend: { display: false }, tooltip: { enabled: false } },
      scales: { x: { display: false }, y: { display: true, position: "right", grid: { color: "rgba(255,255,255,0.04)" }, ticks: { color: "#71717a", font: { size: 9 }, maxTicksLimit: 4 } } } },
  });
}
// 5) Maiores altas e baixas do dia (barras)
function renderMovers(m) {
  const el = document.getElementById("b3Movers");
  if (!el || !m) return;
  const todos = [...(m.altas || []), ...(m.baixas || [])];
  const maxAbs = Math.max(1, ...todos.map((x) => Math.abs(x.variacao)));
  const row = (x) => {
    const cls = x.variacao >= 0 ? "up" : "down";
    return `<div class="mv-row"><span class="mv-tk">${x.ticker}</span>
      <div class="mv-track"><div class="mv-bar ${cls}" style="width:${(Math.abs(x.variacao) / maxAbs * 100).toFixed(0)}%"></div></div>
      <span class="mv-var ${cls}">${x.variacao >= 0 ? "+" : ""}${x.variacao}%</span></div>`;
  };
  el.innerHTML = `
    <div class="mv-col"><div class="mv-title up">▲ Maiores Altas</div>${(m.altas || []).map(row).join("")}</div>
    <div class="mv-col"><div class="mv-title down">▼ Maiores Baixas</div>${(m.baixas || []).map(row).join("")}</div>`;
}
let marketLoaded = false;
async function loadMarketOverview() {
  if (marketLoaded) return;
  marketLoaded = true;
  const el = document.getElementById("b3Macro");
  if (el) el.innerHTML = '<div class="muted small">Carregando cotações…</div>';
  try {
    const d = await apiGet("/api/v1/market/overview");
    renderMacro(d.macro);
    renderIbov(d.ibov_serie);
    renderMovers(d.movers);
    renderWatchlist(d.watchlist);
  } catch (e) {
    marketLoaded = false;
    if (el) el.innerHTML = '<div class="muted small">Cotações indisponíveis no momento.</div>';
  }
}

/* ===================== INICIALIZAÇÃO ===================== */
// Estado inicial da página de Vínculos: histórico (cards) + grafo de amostra.
renderHistorico();
renderSample();
// Estado inicial do Radar de Mercado: heatmap setorial (cotações carregam ao abrir a aba).
renderHeatmap();
