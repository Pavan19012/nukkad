/* Nukkad web app — vanilla JS, no build step.
 * Open ?shop=1 in one tab and ?shop=2 in another to see live shop-to-shop requests. */
const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const rupee = (n) => "₹" + Number(n || 0).toLocaleString("en-IN", { maximumFractionDigits: n % 1 ? 2 : 0 });
const dist = (m) => (m >= 1000 ? (m / 1000).toFixed(1) + " km" : Math.round(m) + " m");
const ago = (iso) => {
  const s = (Date.now() - new Date(iso.replace(" ", "T") + "+05:30").getTime()) / 1000; // server stores IST
  if (s < 60) return "just now";
  if (s < 3600) return Math.floor(s / 60) + " min ago";
  if (s < 86400) return Math.floor(s / 3600) + " h ago";
  return Math.floor(s / 86400) + " d ago";
};

async function api(path, body) {
  const r = await fetch("/api" + path, body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.detail || r.statusText);
  return j;
}

const LANGS = [
  { code: "en-IN", label: "EN" },
  { code: "hi-IN", label: "हिंदी" },
  { code: "kn-IN", label: "ಕನ್ನಡ" },
];
const DEMO = ["oats wala doodh ek litre", "ಗ್ರೀಕ್ ಮೊಸರು ಇಲ್ಲ", "मैगी मसाला दो", "brown bread 2 packet", "protein bar nahi hai"];

const state = {
  shopId: Number(new URLSearchParams(location.search).get("shop")) || null,
  shop: null, shops: [], tab: "capture", lang: localStorageGet("lang") || "en-IN",
  summary: {}, asks: [], incoming: [], holding: [], radar: null, radius: 1000, wallet: null, restock: [],
  lastResult: null, live: false, recording: false, interim: "",
};

function localStorageGet(k) { try { return localStorage.getItem(k); } catch { return null; } }
function localStorageSet(k, v) { try { localStorage.setItem(k, v); } catch {} }

function toast(msg) {
  const t = $("#toast");
  t.innerHTML = msg;
  t.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.remove("show"), 3800);
}
function beep() {
  try {
    const ctx = beep.ctx || (beep.ctx = new AudioContext());
    const o = ctx.createOscillator(), g = ctx.createGain();
    o.frequency.value = 880; g.gain.value = 0.08;
    o.connect(g); g.connect(ctx.destination); o.start(); o.stop(ctx.currentTime + 0.15);
  } catch {}
}

/* ---------------- data loading ---------------- */
async function loadAll() {
  const [shop, asks, incoming] = await Promise.all([
    api(`/shops/${state.shopId}`), api(`/shops/${state.shopId}/asks`), api(`/shops/${state.shopId}/incoming`),
  ]);
  state.shop = shop; state.summary = shop.summary; state.asks = asks; state.incoming = incoming;
  await loadHolding();
}
async function loadHolding() {
  // items this shop is holding for customers sent by neighbours
  [state.holding, state.wallet] = await Promise.all([api(`/shops/${state.shopId}/holding`), api(`/shops/${state.shopId}/wallet`)]);
}
async function refresh(part) {
  try {
    if (part === "radar") state.radar = await api(`/shops/${state.shopId}/radar?radius_m=${state.radius}`);
    else if (part === "wallet") { state.wallet = await api(`/shops/${state.shopId}/wallet`); state.restock = await api(`/shops/${state.shopId}/restock`); }
    else await loadAll();
  } catch (e) { toast("⚠️ " + esc(e.message)); }
  render();
}

/* ---------------- websocket ---------------- */
function connectWS() {
  const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/${state.shopId}`);
  ws.onopen = () => { state.live = true; render(); ws._ping = setInterval(() => ws.readyState === 1 && ws.send("ping"), 20000); };
  ws.onclose = () => { state.live = false; clearInterval(ws._ping); render(); setTimeout(connectWS, 2000); };
  ws.onmessage = async (m) => {
    const { event, data } = JSON.parse(m.data);
    if (event === "incoming_request") {
      beep();
      toast(`📣 <b>${esc(data.from_shop.name)}</b> needs <b>${esc(data.product_name)} × ${data.qty}</b> · ${dist(data.distance_m)}`);
      state.incoming = [data, ...state.incoming.filter((i) => i.id !== data.id)];
      state.summary = await api(`/shops/${state.shopId}/summary`);
    } else if (event === "request_closed") {
      state.incoming = state.incoming.filter((i) => i.id !== data.id);
    } else if (event === "ask_update") {
      state.asks = state.asks.some((a) => a.id === data.id) ? state.asks.map((a) => (a.id === data.id ? data : a)) : [data, ...state.asks];
      if (data.status === "held") { beep(); toast(`✅ <b>${esc(data.held_by_shop.name)}</b> has <b>${esc(data.product_name)}</b> — send the customer (${dist(data.held_distance_m)})`); }
      if (state.lastResult && state.lastResult.ask.id === data.id) state.lastResult.ask = data;
      state.summary = await api(`/shops/${state.shopId}/summary`);
    } else if (event === "ledger") {
      toast(`💸 Referral earned: <b>${rupee(data.referral)}</b> on a ${rupee(data.sale_amount)} sale`);
      state.summary = await api(`/shops/${state.shopId}/summary`);
    }
    render();
  };
}

/* ---------------- voice capture ---------------- */
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
let rec = null, finalText = "";

function extractVoiceQty(text) {
  const t = text.toLowerCase().trim();

  const numbers = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "ek": 1,
    "do": 2,
    "teen": 3,
    "char": 4,
    "chaar": 4,
    "paanch": 5,
    "panch": 5,
    "एक": 1,
    "दो": 2,
    "तीन": 3,
    "चार": 4,
    "पांच": 5,
    "पाँच": 5,
    "ondu": 1,
    "eradu": 2,
    "mooru": 3,
    "naalku": 4,
    "aidu": 5,
    "too":2,
    "to":2,
    "TO":2
  };

  // Prefer quantities that appear directly before a quantity unit.
  const unitPattern =
    "(?:packet|packets|pack|piece|pieces|bottle|bottles|box|boxes|kg|kilo|gram|grams|g|ml|litre|liter|litres|liters|ltr|l)";

  const words = Object.keys(numbers)
    .sort((a, b) => b.length - a.length)
    .join("|");

  const wordMatch = t.match(
    new RegExp(`\\b(${words})\\b\\s*${unitPattern}\\b`, "i")
  );

  if (wordMatch) {
    return numbers[wordMatch[1].toLowerCase()];
  }

  const digitMatch = t.match(
    new RegExp(`\\b(\\d{1,2})\\s*${unitPattern}\\b`, "i")
  );

  if (digitMatch) {
    return Number(digitMatch[1]);
  }

  return null;
}

function startRec() {
  if (!SR) { toast("Voice needs Chrome/Edge — type the item below instead."); $("#typein")?.focus(); return; }
  finalText = ""; state.interim = "";
  rec = new SR();
  rec.lang = state.lang; rec.interimResults = true; rec.continuous = true;
  rec.onresult = (e) => {
    let interim = "";
    for (let i = e.resultIndex; i < e.results.length; i++) {
      if (e.results[i].isFinal) finalText += e.results[i][0].transcript + " ";
      else interim += e.results[i][0].transcript;
    }
    state.interim = (finalText + interim).trim();
    const l = $("#micl small"); if (l) l.textContent = "“" + state.interim + "”";
  };
  rec.onerror = (e) => { if (e.error !== "aborted") toast("Mic: " + esc(e.error)); };
  rec.onend = () => {
    const text = (finalText || state.interim).trim();
    state.recording = false; render();
    if (text) submitAsk(text);
  };
  try { rec.start(); state.recording = true; render(); } catch {}
}
function stopRec() { if (rec && state.recording) rec.stop(); }

async function submitAsk(text, productId, qty = null) {
  try {
    const detectedQty = qty ?? extractVoiceQty(text);

    const r = await api("/asks", {
      shop_id: state.shopId,
      text,
      product_id: productId || null,
      qty: detectedQty
    });

    state.lastResult = r;
    state.asks = [r.ask, ...state.asks.filter((a) => a.id !== r.ask.id)];
    state.summary = await api(`/shops/${state.shopId}/summary`);
    render();
  } catch (e) {
    toast("⚠️ " + esc(e.message));
  }
}

/* ---------------- map ---------------- */
function mapSVG(center, points, { w = 360, h = 170, span = 1300, ring = 500 } = {}) {
  const mLat = 111320, mLng = 111320 * Math.cos((center.lat * Math.PI) / 180);
  const sc = w / span;
  const P = (p) => [w / 2 + (p.lng - center.lng) * mLng * sc, h / 2 - (p.lat - center.lat) * mLat * sc];
  const [cx, cy] = P(center);
  let s = `<svg viewBox="0 0 ${w} ${h}" xmlns="http://www.w3.org/2000/svg">
    <defs><pattern id="g" width="22" height="22" patternUnits="userSpaceOnUse"><path d="M22 0H0V22" fill="none" stroke="#11303855"/></pattern></defs>
    <rect width="${w}" height="${h}" fill="url(#g)"/>
    <rect x="0" y="${h * 0.47}" width="${w}" height="10" fill="#15343c"/><rect x="${w * 0.52}" y="0" width="10" height="${h}" fill="#15343c"/>
    <circle cx="${cx}" cy="${cy}" r="${ring * sc}" fill="#5de0e60a" stroke="#5de0e6aa" stroke-dasharray="4 4"/>`;
  for (const p of points) {
    const [x, y] = P(p);
    if (p.line) s += `<line x1="${cx}" y1="${cy}" x2="${x}" y2="${y}" stroke="${p.color}" stroke-width="2" stroke-dasharray="5 4"/>`;
  }
  for (const p of points) {
    const [x, y] = P(p);
    s += `<circle cx="${x}" cy="${y}" r="${p.r || 6}" fill="${p.color}" stroke="#071418" stroke-width="3" ${p.glow ? 'style="filter:drop-shadow(0 0 6px ' + p.color + ')"' : ""}/>`;
    if (p.label) s += `<text x="${x}" y="${y < 18 ? y + 20 : y - 11}" fill="${p.color}" font-size="10" text-anchor="middle" font-family="Poppins">${esc(p.label)}</text>`;
  }
  return s + "</svg>";
}
const short = (n) => n.split(" ")[0] === "Sri" ? n.split(" ").slice(0, 2).join(" ") : n.split(" ")[0];

/* ---------------- views ---------------- */
const ICONS = {
  capture: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></svg>',
  network: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="5" cy="12" r="2.5"/><circle cx="19" cy="5" r="2.5"/><circle cx="19" cy="19" r="2.5"/><path d="M7.3 11 16.7 6M7.3 13l9.4 5"/></svg>',
  radar: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><path d="M12 12l6-6"/></svg>',
  wallet: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="3" y="6" width="18" height="13" rx="3"/><path d="M16 12.5h2M3 9h18"/></svg>',
};
const statusTag = (a) => `<span class="tag t-${a.status}">${{ sold: "sold nearby", held: "held nearby", searching: "searching", unmet: "unmet", expired: "expired" }[a.status] || a.status}</span>`;

function header(title) {
  const lang = LANGS.map((l) => `<option value="${l.code}" ${l.code === state.lang ? "selected" : ""}>${l.label}</option>`).join("");
  return `<div class="hdr"><div class="logo">${title}<span>.</span></div>
    <div style="display:flex;gap:6px;align-items:center"><span class="chip" title="live connection"><span class="live-dot ${state.live ? "on" : ""}"></span>${state.live ? "Live" : "Offline"}</span>
    <select class="chip" id="lang" aria-label="Voice language">${lang}</select></div></div>
    <div class="sub"><span>${esc(state.shop.name)} · ${esc(state.shop.owner)}</span><a href="/">switch shop</a></div>`;
}

function viewCapture() {
  const s = state.summary;
  const r = state.lastResult;
  let result = "";
  if (r) {
    const a = r.ask;
    const likely = r.routed_to.filter((t) => t.likely_has).length;
    result = `<div class="card">
      <div class="k">Heard: “${esc(a.raw_text)}”</div>
      ${a.product_id ? `<div class="big">${esc(a.product_name)} × ${a.qty}</div>
        <div class="d">${Math.round((a.confidence || 0) * 100)}% match · est. ${rupee(a.est_value)} · ${
          a.status === "held" ? `<span class="ok">${esc(a.held_by_shop.name)} is holding it (${dist(a.held_distance_m)})</span>`
          : a.status === "sold" ? `<span class="ok">Sold at ${esc(a.held_by_shop.name)} — referral earned</span>`
          : r.routed_to.length ? `sent to ${r.routed_to.length} shops within 500 m${likely ? ` (${likely} likely have it)` : ""}` : "no shops nearby — logged for Radar"}</div>`
        : `<div class="big">Not recognised</div><div class="d">Still logged as demand. Pick the right item:</div>`}
      <div class="cands">${(r.normalized.candidates || []).filter((c) => c.product_id !== a.product_id).map((c) =>
        `<button data-correct="${c.product_id}">${a.product_id ? "Not this? " : ""}${esc(c.name)}</button>`).join("")}</div>
      ${a.status === "held" ? shareBtns(a) : ""}
    </div>`;
  }
  const recent = state.asks.slice(0, 8).map((a) => `<div class="row"><div class="grow">${esc(a.product_name || "“" + a.raw_text + "”")}${a.qty > 1 ? " × " + a.qty : ""}
      <small>${a.status === "held" || a.status === "sold" ? "At " + esc(a.held_by_shop.name) + " · " + dist(a.held_distance_m) : a.status === "searching" ? "Asking nearby shops…" : a.product_id ? "No shop nearby had it" : "Not in catalogue"} · ${ago(a.created_at)}</small></div>${statusTag(a)}</div>`).join("");
  return `${header("Nukkad")}
    <div class="stats">
      <div class="stat"><b>${s.asks_today ?? 0}</b><small>“Nahi hai” asks today</small></div>
      <div class="stat g"><b>${s.recovered_today ?? 0}</b><small>Recovered via network</small></div>
      <div class="stat g"><b>${rupee(s.referral_earned_today)}</b><small>Referral earned today</small></div>
    </div>
    <div class="mic-wrap"><button class="mic ${state.recording ? "rec" : ""}" id="mic" aria-label="Hold to speak">
      <svg viewBox="0 0 24 24" fill="none" stroke="#052126" stroke-width="2" stroke-linecap="round"><rect x="9" y="3" width="6" height="11" rx="3" fill="#052126"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></svg></button>
      <div class="mic-l" id="micl">${state.recording ? "Listening… release to send" : "Hold & say what they asked for"}<small>${state.recording ? "“" + esc(state.interim) + "”" : "e.g. “oats wala doodh ek litre, nahi hai”"}</small></div>
    </div>
    <form class="typebar" id="typeform"><input id="typein" placeholder="…or type it (any language)" autocomplete="off"><button class="btn p sm" type="submit">Log</button></form>
    <div class="chips">${DEMO.map((d) => `<button data-demo="${esc(d)}">${esc(d)}</button>`).join("")}</div>
    ${result}
    <div class="sec">Recent asks</div>
    ${recent || '<div class="empty">No asks yet. Hold the mic when a customer asks for something you don’t have.</div>'}`;
}

function shareBtns(a) {
  const h = a.held_by_shop;
  const msg = `${a.product_name} is available at ${h.name}, ${dist(a.held_distance_m)} away — they're holding it for you. Directions: https://maps.google.com/?q=${h.lat},${h.lng}`;
  return `<div class="btns"><a class="btn p" target="_blank" rel="noopener" href="https://wa.me/?text=${encodeURIComponent(msg)}">Send customer on WhatsApp</a>
    <a class="btn s" target="_blank" rel="noopener" href="https://maps.google.com/?q=${h.lat},${h.lng}">Map</a></div>`;
}

function viewNetwork() {
  const me = state.shop;
  const inc = state.incoming.map((i) => {
    const from = i.from_shop;
    return `<div class="card">
      <div class="k">${esc(from.name)} · ${dist(i.distance_m)} away · ${ago(i.created_at)}</div>
      <div class="big">${esc(i.product_name)} × ${i.qty}</div>
      <div class="d">Customer is at their counter now · est. value ${rupee(i.est_value)}${i.likely_has ? ' · <span class="ok">you usually stock this</span>' : ""}</div>
      <div class="map">${mapSVG(me, [{ ...from, color: "#f3c457", label: short(from.name), line: true }, { ...me, color: "#5de0e6", label: "You", glow: true }])}</div>
      <div class="btns"><button class="btn p" data-yes="${i.id}">Yes · hold it</button><button class="btn s" data-no="${i.id}">Don’t have</button></div>
    </div>`;
  }).join("");
  const hold = state.holding.map((a) => `<div class="row"><div class="grow">${esc(a.product_name)} × ${a.qty}
      <small>Customer coming from ${esc(a.from_shop.name)} · ${dist(a.distance_m)}</small></div>
      <button class="btn p sm" data-sold="${a.id}" data-amt="${a.est_value}">Mark sold</button></div>`).join("");
  const neighbours = me.neighbours.filter((n) => n.id !== me.id);
  const pts = neighbours.map((n) => ({ ...n, color: n.distance_m <= 500 ? "#8fb3b8" : "#3b6b73", label: short(n.name) }));
  pts.push({ ...me, color: "#5de0e6", label: "You", glow: true });
  const w = state.wallet;
  return `${header("Network")}
    <div class="sec">Incoming requests ${state.incoming.length ? `<span class="count">${state.incoming.length}</span>` : ""}</div>
    ${inc || '<div class="empty">No open requests. When a shop within 500 m logs a “nahi hai”, it shows up here instantly.</div>'}
    <div class="sec">Holding for customers</div>
    ${hold || '<div class="empty">Nothing on hold.</div>'}
    <div class="sec">Your street network</div>
    <div class="row col"><div class="map" style="margin:0">${mapSVG(me, pts, { h: 190, span: 1500 })}</div>
      <small style="margin-top:8px">${neighbours.filter((n) => n.distance_m <= 500).length} shops within 500 m · ${neighbours.length} within 1 km</small></div>
    ${w ? `<div class="row"><div class="grow">This network so far<small>You sent ${w.customers_sent} customers · received ${w.customers_received}</small></div><span class="tag t-sold">${rupee(w.sales_from_network)} sales</span></div>` : ""}`;
}

function spark(series) {
  if (!series?.length) return "";
  const max = Math.max(1, ...series.map((s) => s.asks)), w = 300, h = 46;
  const pts = series.map((s, i) => [(i / (series.length - 1)) * w, h - 4 - (s.asks / max) * (h - 10)]);
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><polyline points="${pts.map((p) => p.join(",")).join(" ")}" fill="none" stroke="#5de0e6" stroke-width="2.5" vector-effect="non-scaling-stroke"/>
    ${pts.map((p) => `<circle cx="${p[0]}" cy="${p[1]}" r="2.5" fill="#5de0e6"/>`).join("")}</svg>`;
}

function viewRadar() {
  const r = state.radar;
  if (!r) return `${header("Radar")}<div class="empty">Loading demand…</div>`;
  const max = Math.max(1, ...r.items.map((i) => i.asks));
  const seg = [500, 1000, 2000].map((m) => `<button data-radius="${m}" class="${state.radius === m ? "on" : ""}">${dist(m)}</button>`).join("");
  const items = r.items.map((i) => `<div class="row col">
      <div class="split"><span>${esc(i.name)}</span><span class="hl">${i.asks} asks${i.shops_stocking === 0 ? ' · <span class="warn">0 shops stock</span>' : ""}</span></div>
      <div class="bar"><i style="width:${(i.asks / max) * 100}%"></i></div>
      <small>${i.recovered} recovered · ${i.unmet} lost (${rupee(i.unmet_value)}) · ${i.shops_stocking} shop(s) stock it${i.trend_pct != null ? ` · <span class="${i.trend_pct >= 0 ? "ok" : "warn"}">${i.trend_pct >= 0 ? "▲" : "▼"} ${Math.abs(i.trend_pct)}% vs last week</span>` : ""}</small></div>`).join("");
  const sug = r.suggestions.map((s) => `<div class="card" style="padding:14px">
      <div style="font-size:14px;font-weight:600">💡 Stock ${s.suggested_qty} × ${esc(s.name)}</div>
      <div class="d" style="margin-top:4px">Est. +${rupee(s.est_weekly_revenue)}/week · ${esc(s.reason)}</div>
      <div class="btns" style="margin-top:10px"><button class="btn p" data-restock="${s.product_id}" data-qty="${s.suggested_qty}">Add to restock list</button></div></div>`).join("");
  const top = r.items[0];
  return `${header("Radar")}
    <div class="sub" style="padding-top:6px"><span>${r.shops_in_area} shops · last ${r.days} days</span><div class="seg">${seg}</div></div>
    <div class="card"><div class="k">Demand that walked out of your shop</div>
      <div class="big">${rupee(r.missed.value)} · ${r.missed.asks} missed asks</div>
      <div class="d">${r.missed.recovered} recovered by the network · ${r.missed.lost} lost (${rupee(r.missed.lost_value)})</div></div>
    ${sug ? `<div class="sec">Suggested for you</div>${sug}` : ""}
    <div class="sec">Top unmet demand within ${dist(r.radius_m)}</div>
    ${items || '<div class="empty">No demand logged in this area yet.</div>'}
    ${top ? `<div class="row col"><div class="split"><span>${esc(top.name)} · daily asks</span><span class="hl">area forecast next week ≈ ${top.forecast_next_week}</span></div>${spark(r.top_series)}</div>` : ""}
    ${r.uncatalogued.length ? `<div class="sec">Not in catalogue yet</div><div class="row col"><small>${r.uncatalogued.map(esc).join(" · ")}</small></div>` : ""}`;
}

function viewWallet() {
  const w = state.wallet;
  if (!w) return `${header("Wallet")}<div class="empty">Loading…</div>`;
  const pays = w.payouts.map((p) => {
    const upi = `upi://pay?pa=${encodeURIComponent(p.upi)}&pn=${encodeURIComponent(p.name)}&am=${p.amount.toFixed(2)}&cu=INR&tn=${encodeURIComponent("Nukkad referral")}`;
    return `<div class="row"><div class="grow">${esc(p.name)}<small>${esc(p.upi)} · referral fees</small></div>
      <span class="warn" style="font-weight:600">${rupee(p.amount)}</span>
      <a class="btn p sm" href="${upi}">Pay UPI</a><button class="btn s sm" data-settle="${p.shop_id}">Mark paid</button></div>`;
  }).join("");
  const ent = w.entries.slice(0, 15).map((e) => `<div class="row"><div class="grow">${esc(e.product || "Item")}
      <small>${e.direction === "earned" ? "You sent a customer to " : "Customer sent by "}${esc(e.other_shop)} · ${ago(e.created_at)}${e.settled ? " · settled" : ""}</small></div>
      <span class="${e.direction === "earned" ? "ok" : "warn"}" style="font-weight:600">${e.direction === "earned" ? "+" : "−"}${rupee(e.referral)}</span></div>`).join("");
  const rs = state.restock.map((r) => `<div class="row"><div class="grow">${esc(r.name)}<small>${ago(r.created_at)}</small></div><span class="hl">× ${r.qty}</span></div>`).join("");
  return `${header("Wallet")}
    <div class="stats">
      <div class="stat g"><b>${rupee(w.unsettled_earned)}</b><small>To receive</small></div>
      <div class="stat"><b>${rupee(w.unsettled_owed)}</b><small>To pay</small></div>
      <div class="stat ${w.net >= 0 ? "g" : ""}"><b>${w.net >= 0 ? "+" : "−"}${rupee(Math.abs(w.net))}</b><small>Net this cycle</small></div>
    </div>
    <div class="card"><div class="k">How referrals work</div><div class="d" style="margin-top:4px">The shop that makes the sale pays <b>3%</b> to the shop that sent the customer. Settled weekly over UPI — everyone on the street wins more than they pay.</div></div>
    <div class="sec">Pay your neighbours</div>${pays || '<div class="empty">Nothing to pay right now.</div>'}
    <div class="sec">Restock list</div>${rs || '<div class="empty">Add items from Radar suggestions.</div>'}
    <div class="sec">Ledger</div>${ent || '<div class="empty">No referrals yet.</div>'}`;
}

function viewPicker() {
  return `<div class="picker"><h1>Nukkad<span>.</span></h1>
    <p>Every “nahi hai” becomes a sale. Pick a shop to sign in as — then open another shop in a <b>second tab</b> to see requests flow between them live.</p>
    ${state.shops.map((s) => `<div class="row" data-shop="${s.id}"><div class="grow">${esc(s.name)}<small>${esc(s.owner)} · Koramangala 5th Block</small></div><span class="hl">Open →</span></div>`).join("")}
    <div class="sec" style="padding-top:22px">Demo tips</div>
    <div class="row col"><small>1. Open <b>Sri Lakshmi Stores</b> here and <b>Sharma General Store</b> in another tab.<br>2. In Sri Lakshmi, say or type “brown bread 2 packet”.<br>3. Sharma gets the request instantly → tap “Yes · hold it”.<br>4. Sri Lakshmi sees where to send the customer. Sharma taps “Mark sold” → 3% referral lands in the Wallet.</small></div>
    <div class="foot">HackSprint prototype · Team Cache Me Outside · <button class="link-btn" id="reset">reset demo data</button></div></div>`;
}

function render() {
  const app = $("#app");
  if (!state.shopId) { app.innerHTML = viewPicker(); return; }
  if (!state.shop) { app.innerHTML = '<div class="empty" style="padding-top:120px">Loading…</div>'; return; }
  const view = { capture: viewCapture, network: viewNetwork, radar: viewRadar, wallet: viewWallet }[state.tab];
  const focusId = document.activeElement?.id, val = $("#typein")?.value;
  app.innerHTML = view() + `<nav class="nav">${["capture", "network", "radar", "wallet"].map((t) =>
    `<button data-tab="${t}" class="${state.tab === t ? "on" : ""}">${ICONS[t]}${t[0].toUpperCase() + t.slice(1)}${t === "network" && state.incoming.length ? `<span class="badge">${state.incoming.length}</span>` : ""}</button>`).join("")}</nav>`;
  if (val && $("#typein")) $("#typein").value = val;
  if (focusId === "typein") $("#typein")?.focus();
  const mic = $("#mic");
  if (mic) {
    mic.onpointerdown = (e) => { e.preventDefault(); startRec(); };
    mic.onpointerup = mic.onpointerleave = () => stopRec();
  }
}

function modal(html) {
  const bg = document.createElement("div");
  bg.className = "modal-bg";
  bg.innerHTML = `<div class="modal">${html}</div>`;
  bg.onclick = (e) => { if (e.target === bg) bg.remove(); };
  document.body.appendChild(bg);
  return bg;
}

/* ---------------- events ---------------- */
document.addEventListener("click", async (e) => {
  const t = e.target.closest("button, .row[data-shop]");
  if (!t) return;
  const d = t.dataset;
  if (d.shop) location.search = "?shop=" + d.shop;
  else if (t.id === "reset") { await api("/demo/reset", {}); toast("Demo data reset"); }
  else if (d.tab) { state.tab = d.tab; render(); if (d.tab === "radar") refresh("radar"); else if (d.tab === "wallet") refresh("wallet"); else refresh(); }
  else if (d.demo) submitAsk(d.demo);
  else if (d.correct) {
    const r = await api(`/asks/${state.lastResult.ask.id}/correct`, { product_id: Number(d.correct) });
    state.lastResult = { ...state.lastResult, ...r };
    state.asks = state.asks.map((a) => (a.id === r.ask.id ? r.ask : a)); render();
  } else if (d.yes || d.no) {
    const id = Number(d.yes || d.no);
    const r = await api(`/asks/${id}/respond`, { shop_id: state.shopId, has_it: !!d.yes }).catch((err) => ({ ok: false, error: err.message }));
    state.incoming = state.incoming.filter((i) => i.id !== id);
    if (d.yes && r.ok) toast("👍 Holding it — the customer is on the way");
    else if (d.yes) toast("Another shop already took this one");
    await loadHolding(); render();
  } else if (d.sold) {
    const m = modal(`<h3>Mark as sold</h3><div class="d" style="color:var(--muted);font-size:13px">3% referral goes to the shop that sent the customer.</div>
      <label>Sale amount (₹)</label><input id="amt" type="number" min="0" step="1" value="${Math.round(Number(d.amt) || 0)}">
      <label>UPI transaction ref (optional)</label><input id="ref" placeholder="e.g. 4271 8812 0093">
      <div class="btns"><button class="btn s" id="cx">Cancel</button><button class="btn p" id="ok">Confirm sale</button></div>`);
    $("#cx", m).onclick = () => m.remove();
    $("#ok", m).onclick = async () => {
      try {
        const r = await api(`/asks/${d.sold}/sold`, { shop_id: state.shopId, sale_amount: Number($("#amt", m).value), upi_ref: $("#ref", m).value });
        m.remove(); toast(`Sale recorded · referral ${rupee(r.ledger.referral)} owed to ${esc(r.ask.from_shop.name)}`);
        await loadHolding(); render();
      } catch (err) { toast("⚠️ " + esc(err.message)); }
    };
  } else if (d.radius) { state.radius = Number(d.radius); refresh("radar"); }
  else if (d.restock) {
    state.restock = await api(`/shops/${state.shopId}/restock`, { product_id: Number(d.restock), qty: Number(d.qty) });
    toast("Added to restock list (see Wallet)");
  } else if (d.settle) {
    state.wallet = await api(`/shops/${state.shopId}/settle`, { payee_id: Number(d.settle), upi_ref: "" });
    toast("Marked as paid"); render();
  }
});
document.addEventListener("submit", (e) => {
  if (e.target.id === "typeform") {
    e.preventDefault();
    const v = $("#typein").value.trim();
    if (v) { $("#typein").value = ""; submitAsk(v); }
  }
});
document.addEventListener("change", (e) => {
  if (e.target.id === "lang") { state.lang = e.target.value; localStorageSet("lang", state.lang); toast("Voice language: " + LANGS.find((l) => l.code === state.lang).label); }
});
// keyboard: hold space to talk (desktop demo)
document.addEventListener("keydown", (e) => { if (e.code === "Space" && !e.repeat && state.tab === "capture" && document.activeElement?.tagName !== "INPUT" && state.shopId) { e.preventDefault(); startRec(); } });
document.addEventListener("keyup", (e) => { if (e.code === "Space" && state.recording) stopRec(); });

/* ---------------- boot ---------------- */
(async function boot() {
  if (!state.shopId) { state.shops = await api("/shops"); render(); return; }
  render();
  await refresh();
  connectWS();
  setInterval(() => { if (state.tab === "capture" || state.tab === "network") refresh(); }, 15000);
})();
