// GH₵ Portfolio frontend.
//
// Security note: every place that puts user-supplied text (symbols, etc.)
// into the DOM uses textContent / createElement, never innerHTML with
// interpolated strings, so a symbol like "<script>" can't execute.

const $ = (id) => document.getElementById(id);

let chart = null;
let chartMode = "combined"; // "combined" | "separate"
let cachedHoldings = null;
let cachedStocks = null;

const CACHE_KEYS = {
  stocks: "cache_stocks",
  holdings: "cache_holdings",
  chart: "cache_chart",
  chartMode: "cache_chart_mode",
};

function clearAppCache() {
  Object.values(CACHE_KEYS).forEach(k => localStorage.removeItem(k));
}

function renderFromCache() {
  let hasAny = false;

  const stocksRaw = localStorage.getItem(CACHE_KEYS.stocks);
  if (stocksRaw) {
    try {
      cachedStocks = JSON.parse(stocksRaw);
      for (const s of cachedStocks) {
        if (s.logo) LOGO_EXTS[s.symbol] = s.logo;
      }
      hasAny = true;
    } catch (_) {}
  }

  const holdingsRaw = localStorage.getItem(CACHE_KEYS.holdings);
  if (holdingsRaw) {
    try {
      cachedHoldings = JSON.parse(holdingsRaw);
      renderTotals(cachedHoldings.totals);
      renderHoldingsTable(cachedHoldings.holdings);
      $("stale-badge").classList.toggle("hidden", !cachedHoldings.any_price_stale);
      $("stale-badge").textContent = cachedHoldings.any_price_missing
        ? "prices unavailable"
        : "prices delayed";
      hasAny = true;
    } catch (_) {}
  }

  const modeRaw = localStorage.getItem(CACHE_KEYS.chartMode);
  if (modeRaw) {
    chartMode = modeRaw;
    $("view-combined").classList.toggle("active", chartMode === "combined");
    $("view-separate").classList.toggle("active", chartMode === "separate");
  }

  const chartRaw = localStorage.getItem(CACHE_KEYS.chart);
  if (chartRaw && chartMode === "combined") {
    try {
      const chartData = JSON.parse(chartRaw);
      if (chartData && chartData.series && chartData.series.length > 0) {
        renderCombinedChart(chartData);
        hasAny = true;
      }
    } catch (_) {}
  }

  return hasAny;
}

// ---------- bootstrap ----------

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.addEventListener("controllerchange", () => {
    window.location.reload();
  });
}

async function init() {
  const config = await api("/api/config", { auth: false }).catch(() => ({ bot_username: "" }));
  mountTelegramWidget(config.bot_username);
  setupAuthTabs();
  setupWebAuthForm();
  setupStockPicker();

  const me = await api("/api/me", { auth: false, silent404: true });
  if (me) {
    showDashboard();
    await loadEverything();
  } else {
    showLogin();
  }
}

function setupAuthTabs() {
  const tabLogin = $("tab-login");
  const tabRegister = $("tab-register");
  const submitBtn = $("auth-submit");

  tabLogin.addEventListener("click", () => {
    tabLogin.classList.add("active");
    tabRegister.classList.remove("active");
    submitBtn.textContent = "Log in";
    submitBtn.dataset.mode = "login";
    $("auth-error").classList.add("hidden");
  });

  tabRegister.addEventListener("click", () => {
    tabRegister.classList.add("active");
    tabLogin.classList.remove("active");
    submitBtn.textContent = "Create account";
    submitBtn.dataset.mode = "register";
    $("auth-error").classList.add("hidden");
  });

  submitBtn.dataset.mode = "login";
}

function setupWebAuthForm() {
  $("web-auth-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const errEl = $("auth-error");
    errEl.classList.add("hidden");

    const username = $("auth-username").value.trim();
    const password = $("auth-password").value;
    const mode = $("auth-submit").dataset.mode;

    if (!username || !password) return;

    try {
      await api(`/api/auth/${mode}`, { method: "POST", body: { username, password }, auth: false });
      clearAppCache();
      showDashboard();
      await loadEverything();
    } catch (e) {
      errEl.textContent = e.message;
      errEl.classList.remove("hidden");
    }
  });
}

function setupStockPicker() {
  const input = $("tx-symbol");
  const dropdown = $("tx-symbol-dropdown");
  let activeIdx = -1;

  function renderDropdown(stocks) {
    dropdown.innerHTML = "";
    activeIdx = -1;
    if (!stocks || !stocks.length) {
      dropdown.classList.add("hidden");
      return;
    }
    for (const s of stocks) {
      const li = document.createElement("li");
      const logo = stockLogo(s.symbol, 28, "stock-logo", "stock-letter");
      li.appendChild(logo);
      const sym = document.createElement("span");
      sym.className = "stock-sym";
      sym.textContent = s.symbol;
      const name = document.createElement("span");
      name.className = "stock-name";
      name.textContent = s.name;
      const price = document.createElement("span");
      price.className = "stock-price";
      price.textContent = s.price != null ? `GH₵${s.price.toFixed(2)}` : "";
      li.appendChild(sym);
      li.appendChild(name);
      li.appendChild(price);
      li.addEventListener("mousedown", (e) => {
        e.preventDefault();
        pickStock(s);
      });
      dropdown.appendChild(li);
    }
    dropdown.classList.remove("hidden");
  }

  function pickStock(s) {
    input.value = s.symbol;
    dropdown.classList.add("hidden");
    if (s.price != null) {
      const priceInput = $("tx-price");
      if (!priceInput.value) priceInput.value = s.price.toFixed(2);
    }
    $("tx-shares").focus();
  }

  function filterStocks(query) {
    if (!cachedStocks) return [];
    const q = (query || "").trim().toUpperCase();
    if (!q) return cachedStocks;
    return cachedStocks.filter(
      (s) => s.symbol.includes(q) || (s.name && s.name.toUpperCase().includes(q))
    );
  }

  async function updatePicker() {
    if (!cachedStocks || !cachedStocks.length) {
      await loadStocks();
    }
    renderDropdown(filterStocks(input.value));
  }

  input.addEventListener("focus", updatePicker);
  input.addEventListener("input", updatePicker);

  input.addEventListener("blur", () => {
    setTimeout(() => dropdown.classList.add("hidden"), 150);
  });

  input.addEventListener("keydown", (e) => {
    const items = dropdown.querySelectorAll("li");
    if (!items.length) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      activeIdx = Math.min(activeIdx + 1, items.length - 1);
      items.forEach((li, i) => li.classList.toggle("active", i === activeIdx));
      items[activeIdx].scrollIntoView({ block: "nearest" });
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      activeIdx = Math.max(activeIdx - 1, 0);
      items.forEach((li, i) => li.classList.toggle("active", i === activeIdx));
      items[activeIdx].scrollIntoView({ block: "nearest" });
    } else if (e.key === "Enter" && activeIdx >= 0) {
      e.preventDefault();
      const filtered = filterStocks(input.value);
      if (filtered[activeIdx]) pickStock(filtered[activeIdx]);
    }
  });

  window.openPickerDropdown = updatePicker;
}

function mountTelegramWidget(botUsername) {
  const container = $("telegram-login-container");
  if (!botUsername) {
    const p = document.createElement("p");
    p.className = "login-note";
    p.textContent = "Login widget unavailable: server has no bot configured.";
    container.appendChild(p);
    return;
  }
  window.onTelegramAuth = handleTelegramAuth;
  const script = document.createElement("script");
  script.src = "https://telegram.org/js/telegram-widget.js?22";
  script.setAttribute("data-telegram-login", botUsername);
  script.setAttribute("data-size", "large");
  script.setAttribute("data-onauth", "onTelegramAuth(user)");
  script.setAttribute("data-request-access", "write");
  container.appendChild(script);
}

async function handleTelegramAuth(user) {
  try {
    await api("/api/auth/telegram", { method: "POST", body: user, auth: false });
    clearAppCache();
    showDashboard();
    await loadEverything();
  } catch (e) {
    alert("Login failed: " + e.message);
  }
}

// ---------- api helper ----------

async function api(path, { method = "GET", body, auth = true, silent404 = false } = {}) {
  let resp;
  try {
    resp = await fetch(path, {
      method,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
      credentials: "same-origin",
    });
  } catch (_) {
    throw new Error("Couldn't reach the server — check your connection.");
  }
  if (resp.status === 401 && silent404) return null;
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const j = await resp.json();
      detail = j.detail || detail;
    } catch (_) {}
    const err = new Error(detail);
    err.status = resp.status;
    throw err;
  }
  if (resp.status === 204) return null;
  return resp.json();
}

// ---------- view toggling ----------

function showLogin() {
  clearAppCache();
  $("login-screen").classList.remove("hidden");
  $("dashboard-screen").classList.add("hidden");
}

function showDashboard() {
  $("login-screen").classList.add("hidden");
  $("dashboard-screen").classList.remove("hidden");
}

// ---------- data loading ----------

async function loadEverything() {
  const overlay = $("loading-overlay");
  const textEl = overlay.querySelector(".loading-text");

  const hasCache = renderFromCache();

  if (hasCache) {
    overlay.classList.add("hidden");
    try {
      await Promise.all([loadHoldings()]);
    } catch (e) {
      if (e.status === 401) {
        clearAppCache();
        showLogin();
        return;
      }
      console.error("Background data refresh failed:", e);
    }

    try {
      await loadChart();
    } catch (e) {
      if (e.status === 401) {
        clearAppCache();
        showLogin();
        return;
      }
      console.error("Chart load failed:", e);
      $("progress-chart").style.display = "none";
      $("chart-empty").textContent = "Error loading chart.";
      $("chart-empty").classList.remove("hidden");
    }
  } else {
    overlay.classList.remove("hidden");
    textEl.textContent = "Loading…";
    try {
      await Promise.all([loadStocks(), loadHoldings()]);
      overlay.classList.add("hidden");
    } catch (e) {
      textEl.textContent = "Couldn't load data — check your connection and try refreshing.";
      return;
    }

    try {
      await loadChart();
    } catch (e) {
      console.error("Chart load failed:", e);
      $("progress-chart").style.display = "none";
      $("chart-empty").textContent = "Error loading chart.";
      $("chart-empty").classList.remove("hidden");
    }
  }
}

async function loadStocks(force = false) {
  if (!force && cachedStocks && cachedStocks.length > 0) return;
  try {
    const data = await api("/api/stocks", { auth: false });
    if (data && data.stocks && data.stocks.length > 0) {
      cachedStocks = data.stocks;
      for (const s of cachedStocks) {
        if (s.logo) LOGO_EXTS[s.symbol] = s.logo;
      }
      localStorage.setItem(CACHE_KEYS.stocks, JSON.stringify(cachedStocks));
    }
  } catch (_) {}
}

async function loadTransactions() {
  const body = $("history-body");
  const emptyEl = $("history-empty");
  const tableEl = $("history-table");
  body.innerHTML = "";
  try {
    const txs = await api("/api/transactions");
    if (!txs || txs.length === 0) {
      emptyEl.classList.remove("hidden");
      tableEl.classList.add("hidden");
      return;
    }
    emptyEl.classList.add("hidden");
    tableEl.classList.remove("hidden");

    for (const t of txs) {
      const tr = document.createElement("tr");

      const dateTd = document.createElement("td");
      dateTd.textContent = t.trade_date;
      tr.appendChild(dateTd);

      const typeTd = document.createElement("td");
      typeTd.textContent = t.side.toUpperCase();
      typeTd.className = t.side === "buy" ? "pl-positive" : "pl-negative";
      tr.appendChild(typeTd);

      const symTd = document.createElement("td");
      const logo = stockLogo(t.symbol, 20, "holding-logo", "holding-letter");
      symTd.appendChild(logo);
      const symSpan = document.createElement("span");
      symSpan.textContent = t.symbol;
      symSpan.style.fontWeight = "600";
      symTd.appendChild(symSpan);
      tr.appendChild(symTd);

      const sharesTd = document.createElement("td");
      sharesTd.textContent = t.shares;
      tr.appendChild(sharesTd);

      const priceTd = document.createElement("td");
      priceTd.textContent = fmtMoney(t.price);
      tr.appendChild(priceTd);

      const totalTd = document.createElement("td");
      totalTd.textContent = fmtMoney(t.shares * t.price);
      tr.appendChild(totalTd);

      const actionTd = document.createElement("td");
      const delBtn = document.createElement("button");
      delBtn.className = "btn-delete";
      delBtn.textContent = "Delete";
      delBtn.title = "Delete transaction";
      delBtn.addEventListener("click", async () => {
        if (confirm(`Delete ${t.side} transaction of ${t.shares} ${t.symbol}?`)) {
          try {
            await api(`/api/transactions/${t.id}`, { method: "DELETE" });
            await loadTransactions();
            await loadEverything();
          } catch (err) {
            alert("Could not delete transaction: " + err.message);
          }
        }
      });
      actionTd.appendChild(delBtn);
      tr.appendChild(actionTd);

      body.appendChild(tr);
    }
  } catch (err) {
    emptyEl.textContent = "Error loading transactions.";
    emptyEl.classList.remove("hidden");
    tableEl.classList.add("hidden");
  }
}

async function loadHoldings() {
  const data = await api("/api/holdings");
  cachedHoldings = data;
  renderTotals(data.totals);
  renderHoldingsTable(data.holdings);
  $("stale-badge").classList.toggle("hidden", !data.any_price_stale);
  $("stale-badge").textContent = data.any_price_missing
    ? "prices unavailable"
    : "prices delayed";
  localStorage.setItem(CACHE_KEYS.holdings, JSON.stringify(data));
}

function fmtMoney(v) {
  if (v === null || v === undefined) return "—";
  const sign = v < 0 ? "-" : "";
  return `${sign}GH₵${Math.abs(v).toFixed(2)}`;
}

function fmtPct(v) {
  if (v === null || v === undefined) return "";
  const sign = v >= 0 ? "+" : "";
  return ` (${sign}${v.toFixed(2)}%)`;
}

function plClass(v) {
  if (v === null || v === undefined) return "";
  return v > 0 ? "pl-positive" : v < 0 ? "pl-negative" : "";
}

function renderTotals(totals) {
  $("stat-cost").textContent = fmtMoney(totals.cost_basis);
  $("stat-value").textContent = fmtMoney(totals.market_value);

  const unrealizedEl = $("stat-unrealized");
  unrealizedEl.textContent = fmtMoney(totals.unrealized_pl) + fmtPct(totals.unrealized_pl_pct);
  unrealizedEl.className = "stat-value " + plClass(totals.unrealized_pl);

  const realizedEl = $("stat-realized");
  realizedEl.textContent = fmtMoney(totals.realized_pl);
  realizedEl.className = "stat-value " + plClass(totals.realized_pl);
}

function renderHoldingsTable(holdings) {
  const body = $("holdings-body");
  body.innerHTML = "";

  $("holdings-empty").classList.toggle("hidden", holdings.length > 0);
  $("holdings-table").classList.toggle("hidden", holdings.length === 0);

  for (const h of holdings) {
    const tr = document.createElement("tr");

    const symTd = document.createElement("td");
    const logo = stockLogo(h.symbol, 22, "holding-logo", "holding-letter");
    symTd.appendChild(logo);
    const symText = document.createElement("span");
    symText.textContent = h.symbol;
    symText.className = "clickable-symbol";
    symText.addEventListener("click", () => showStockDetail(h.symbol));
    symTd.appendChild(symText);
    tr.appendChild(symTd);

    const cells = [
      h.shares_held.toString(),
      fmtMoney(h.avg_cost),
      h.current_price !== null ? fmtMoney(h.current_price) : "unavailable",
    ];
    for (const text of cells) {
      const td = document.createElement("td");
      td.textContent = text;
      tr.appendChild(td);
    }

    const changeTd = document.createElement("td");
    const changeVal = h.change || 0;
    changeTd.textContent = changeVal >= 0 ? `+${changeVal.toFixed(2)}` : changeVal.toFixed(2);
    changeTd.className = changeVal > 0 ? "pl-positive" : changeVal < 0 ? "pl-negative" : "";
    tr.appendChild(changeTd);

    const volTd = document.createElement("td");
    volTd.textContent = (h.volume || 0).toLocaleString();
    tr.appendChild(volTd);

    const mvTd = document.createElement("td");
    mvTd.textContent = fmtMoney(h.market_value);
    tr.appendChild(mvTd);

    const plTd = document.createElement("td");
    plTd.textContent = fmtMoney(h.unrealized_pl) + fmtPct(h.unrealized_pl_pct);
    plTd.className = plClass(h.unrealized_pl);
    tr.appendChild(plTd);

    body.appendChild(tr);
  }
}

// ---------- stock logo helper ----------

const LOGO_EXTS = {};  // populated from /api/stocks response

function stockLogo(symbol, size, imgClass, fallbackClass) {
  const ext = LOGO_EXTS[symbol];
  if (ext) {
    const img = document.createElement("img");
    img.src = `/static/logos/${symbol}.${ext}`;
    img.alt = symbol;
    img.width = size;
    img.height = size;
    img.className = imgClass;
    img.onerror = function () {
      this.replaceWith(letterAvatar(symbol, size, fallbackClass));
    };
    return img;
  }
  return letterAvatar(symbol, size, fallbackClass);
}

function letterAvatar(symbol, size, className) {
  const span = document.createElement("span");
  span.className = className;
  span.textContent = symbol.charAt(0);
  span.style.width = size + "px";
  span.style.height = size + "px";
  return span;
}

// ---------- chart ----------

function fmtDate(iso) {
  if (!iso || typeof iso !== "string" || !iso.includes("-")) return iso || "";
  const parts = iso.split("-");
  if (parts.length < 3) return iso;
  const [, m, d] = parts;
  const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  const monthIdx = parseInt(m, 10) - 1;
  if (monthIdx < 0 || monthIdx > 11) return iso;
  return `${months[monthIdx]} ${parseInt(d, 10)}`;
}

function chartGainBadge(series) {
  const badge = $("chart-gain");
  if (!badge || !series || series.length < 2) {
    if (badge) badge.classList.add("hidden");
    return;
  }
  const first = series[0];
  const last = series[series.length - 1];
  const gain = last.value - first.cost_basis;
  const pct = first.cost_basis > 0 ? (gain / first.cost_basis) * 100 : 0;
  const sign = gain >= 0 ? "+" : "";
  badge.textContent = `${sign}${fmtMoney(gain)} (${sign}${pct.toFixed(1)}%)`;
  badge.className = "chart-gain-badge " + (gain >= 0 ? "pl-positive" : "pl-negative");
}

async function loadChart() {
  if (chartMode === "combined") {
    const data = await api("/api/history");
    renderCombinedChart(data);
    localStorage.setItem(CACHE_KEYS.chart, JSON.stringify(data));
    localStorage.setItem(CACHE_KEYS.chartMode, "combined");
  } else {
    const symbols = cachedHoldings ? cachedHoldings.holdings.map((h) => h.symbol) : [];
    const perSymbol = {};
    for (const sym of symbols) {
      perSymbol[sym] = (await api(`/api/history?symbol=${encodeURIComponent(sym)}`)).series;
    }
    renderSeparateChart(perSymbol);
    localStorage.setItem(CACHE_KEYS.chartMode, "separate");
  }
}

function destroyChart() {
  if (chart) {
    chart.destroy();
    chart = null;
  }
}

function renderCombinedChart(data) {
  destroyChart();
  if (!data.series || data.series.length === 0) {
    chartGainBadge(null);
    $("progress-chart").style.display = "none";
    $("chart-empty").classList.remove("hidden");
    return;
  }
  $("progress-chart").style.display = "";
  $("chart-empty").classList.add("hidden");
  chartGainBadge(data.series);
  const ctx = $("progress-chart").getContext("2d");
  const labels = data.series.map((p) => p.date);
  const values = data.series.map((p) => p.value);
  const costs = data.series.map((p) => p.cost_basis);

  chart = new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: "Market value",
          data: values,
          borderColor: "#4ade80",
          backgroundColor: "rgba(74, 222, 128, 0.08)",
          fill: true,
          tension: 0.15,
          pointRadius: values.length > 60 ? 0 : 3,
          pointHoverRadius: 5,
        },
        {
          label: "Cost basis",
          data: costs,
          borderColor: "rgba(154, 160, 172, 0.5)",
          borderDash: [6, 3],
          fill: false,
          tension: 0,
          pointRadius: 0,
          pointHoverRadius: 4,
        },
      ],
    },
    options: chartOptions(data.series),
  });
}

function renderSeparateChart(perSymbol) {
  destroyChart();
  if (!Object.keys(perSymbol).length) {
    chartGainBadge(null);
    $("progress-chart").style.display = "none";
    $("chart-empty").classList.remove("hidden");
    return;
  }
  $("progress-chart").style.display = "";
  $("chart-empty").classList.add("hidden");
  chartGainBadge(null);
  const ctx = $("progress-chart").getContext("2d");
  const palette = ["#4ade80", "#60a5fa", "#f472b6", "#facc15", "#a78bfa", "#fb923c", "#2dd4bf"];

  const allDates = new Set();
  Object.values(perSymbol).forEach((series) => {
    if (series && Array.isArray(series)) {
      series.forEach((p) => {
        if (p && p.date) allDates.add(p.date);
      });
    }
  });
  const labels = Array.from(allDates).sort();

  const datasets = Object.entries(perSymbol).map(([symbol, series], i) => {
    const byDate = Object.fromEntries(series.map((p) => [p.date, p.value]));
    return {
      label: symbol,
      data: labels.map((d) => (d in byDate ? byDate[d] : null)),
      borderColor: palette[i % palette.length],
      spanGaps: true,
      tension: 0.15,
      pointRadius: labels.length > 60 ? 0 : 3,
      pointHoverRadius: 5,
    };
  });

  chart = new Chart(ctx, {
    type: "line",
    data: { labels, datasets },
    options: chartOptions(null),
  });
}

function chartOptions(seriesWithCost) {
  return {
    responsive: true,
    interaction: { mode: "index", intersect: false },
    scales: {
      y: {
        ticks: { callback: (v) => `GH₵${v.toLocaleString()}` },
        grid: { color: "rgba(255,255,255,0.06)" },
      },
      x: {
        ticks: { callback: function(val) { return fmtDate(this.getLabelForValue(val)); } },
        grid: { display: false },
      },
    },
    plugins: {
      legend: { display: true },
      tooltip: {
        callbacks: {
          title: (items) => items.length ? fmtDate(items[0].label) : "",
          label: function(ctx) {
            const val = ctx.parsed.y;
            if (val === null || val === undefined || isNaN(val)) {
              return `${ctx.dataset.label}: —`;
            }
            const prefix = `${ctx.dataset.label}: GH₵${val.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
            if (!seriesWithCost || ctx.datasetIndex !== 0) return prefix;
            const pt = seriesWithCost[ctx.dataIndex];
            if (!pt || !pt.cost_basis) return prefix;
            const gain = pt.value - pt.cost_basis;
            const pct = pt.cost_basis > 0 ? (gain / pt.cost_basis) * 100 : 0;
            const sign = gain >= 0 ? "+" : "";
            return `${prefix}  ${sign}GH₵${Math.abs(gain).toFixed(2)} (${sign}${pct.toFixed(1)}%)`;
          },
        },
      },
    },
  };
}

// ---------- stock detail modal ----------

async function showStockDetail(symbol) {
  const modal = $("detail-modal");
  const errEl = $("detail-error");
  errEl.classList.add("hidden");

  $("detail-symbol").textContent = symbol;
  $("detail-company").textContent = "Loading…";
  $("detail-sector").textContent = "—";
  $("detail-industry").textContent = "—";
  $("detail-mcap").textContent = "—";
  $("detail-shares").textContent = "—";
  $("detail-eps").textContent = "—";
  $("detail-dps").textContent = "—";
  modal.classList.remove("hidden");

  try {
    const d = await api(`/api/stock/${encodeURIComponent(symbol)}`);
    $("detail-company").textContent = d.company_name || symbol;
    $("detail-sector").textContent = d.sector || "—";
    $("detail-industry").textContent = d.industry || "—";
    $("detail-mcap").textContent = d.market_cap ? `GH₵${Number(d.market_cap).toLocaleString()}` : "—";
    $("detail-shares").textContent = d.shares_outstanding ? Number(d.shares_outstanding).toLocaleString() : "—";
    $("detail-eps").textContent = d.eps != null ? `GH₵${d.eps}` : "—";
    $("detail-dps").textContent = d.dps != null ? `GH₵${d.dps}` : "—";
  } catch (e) {
    errEl.textContent = e.message;
    errEl.classList.remove("hidden");
  }
}

$("detail-close").addEventListener("click", () => $("detail-modal").classList.add("hidden"));

// ---------- events ----------

$("logout-btn").addEventListener("click", async () => {
  clearAppCache();
  await api("/api/logout", { method: "POST" });
  location.reload();
});

$("view-combined").addEventListener("click", () => switchChartMode("combined"));
$("view-separate").addEventListener("click", () => switchChartMode("separate"));

function switchChartMode(mode) {
  chartMode = mode;
  localStorage.setItem(CACHE_KEYS.chartMode, mode);
  $("view-combined").classList.toggle("active", mode === "combined");
  $("view-separate").classList.toggle("active", mode === "separate");
  loadChart();
}

$("add-tx-btn").addEventListener("click", async () => {
  $("tx-error").classList.add("hidden");
  $("tx-form").reset();
  $("tx-date").valueAsDate = new Date();
  $("tx-modal").classList.remove("hidden");
  $("tx-symbol").focus();
  if (window.openPickerDropdown) {
    await window.openPickerDropdown();
  }
});

$("view-tx-btn").addEventListener("click", () => {
  $("history-modal").classList.remove("hidden");
  loadTransactions();
});

$("history-close").addEventListener("click", () => {
  $("history-modal").classList.add("hidden");
});

$("view-market-btn").addEventListener("click", loadMarket);
$("market-close").addEventListener("click", () => $("market-modal").classList.add("hidden"));
$("market-search").addEventListener("input", renderMarketTable);

let marketSort = { column: "symbol", dir: "asc" };

function renderMarketTable(stocks) {
  const body = $("market-body");
  body.innerHTML = "";
  const searchVal = ($("market-search").value || "").trim().toUpperCase();
  let list = stocks || cachedStocks || [];
  if (searchVal) {
    list = list.filter(
      (s) => s.symbol.includes(searchVal) || (s.name && s.name.toUpperCase().includes(searchVal))
    );
  }
  list = list.slice().sort((a, b) => {
    let av = a[marketSort.column];
    let bv = b[marketSort.column];
    if (typeof av === "string") av = av.toUpperCase();
    if (typeof bv === "string") bv = bv.toUpperCase();
    if (av == null) av = "";
    if (bv == null) bv = "";
    if (av < bv) return marketSort.dir === "asc" ? -1 : 1;
    if (av > bv) return marketSort.dir === "asc" ? 1 : -1;
    return 0;
  });

  $("market-empty").classList.toggle("hidden", list.length > 0);
  $("market-table").classList.toggle("hidden", list.length === 0);

  for (const s of list) {
    const tr = document.createElement("tr");

    const symTd = document.createElement("td");
    const logo = stockLogo(s.symbol, 22, "market-logo", "market-letter");
    symTd.appendChild(logo);
    const symSpan = document.createElement("span");
    symSpan.textContent = s.symbol;
    symSpan.className = "clickable-symbol";
    symSpan.addEventListener("click", () => {
      $("market-modal").classList.add("hidden");
      showStockDetail(s.symbol);
    });
    symTd.appendChild(symSpan);
    tr.appendChild(symTd);

    const nameTd = document.createElement("td");
    nameTd.textContent = s.name || "";
    tr.appendChild(nameTd);

    const priceTd = document.createElement("td");
    priceTd.textContent = s.price != null ? fmtMoney(s.price) : "—";
    tr.appendChild(priceTd);

    const changeTd = document.createElement("td");
    const changeVal = s.change || 0;
    changeTd.textContent = changeVal >= 0 ? `+${changeVal.toFixed(2)}` : changeVal.toFixed(2);
    changeTd.className = changeVal > 0 ? "pl-positive" : changeVal < 0 ? "pl-negative" : "";
    tr.appendChild(changeTd);

    body.appendChild(tr);
  }
}

function sortMarket(column) {
  if (marketSort.column === column) {
    marketSort.dir = marketSort.dir === "asc" ? "desc" : "asc";
  } else {
    marketSort.column = column;
    marketSort.dir = "asc";
  }
  document.querySelectorAll("#market-table th").forEach((th) => {
    th.classList.toggle("sort-asc", th.dataset.sort === marketSort.column && marketSort.dir === "asc");
    th.classList.toggle("sort-desc", th.dataset.sort === marketSort.column && marketSort.dir === "desc");
  });
  renderMarketTable();
}

async function loadMarket() {
  const modal = $("market-modal");
  modal.classList.remove("hidden");
  $("market-search").value = "";
  if (!cachedStocks || !cachedStocks.length) {
    await loadStocks();
  }
  document.querySelectorAll("#market-table th").forEach((th) => {
    th.classList.remove("sort-asc", "sort-desc");
    if (th.dataset.sort === marketSort.column) {
      th.classList.add(marketSort.dir === "asc" ? "sort-asc" : "sort-desc");
    }
  });
  renderMarketTable();
}

document.querySelectorAll("#market-table th[data-sort]").forEach((th) => {
  th.addEventListener("click", () => sortMarket(th.dataset.sort));
});

$("tx-cancel").addEventListener("click", () => $("tx-modal").classList.add("hidden"));

$("tx-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const errEl = $("tx-error");
  errEl.classList.add("hidden");

  const symbol = $("tx-symbol").value.trim().toUpperCase();
  const shares = parseFloat($("tx-shares").value);
  const price = parseFloat($("tx-price").value);

  if (!symbol || !/^[A-Z0-9]{1,12}$/.test(symbol)) {
    errEl.textContent = "Symbol must be 1-12 letters/numbers.";
    errEl.classList.remove("hidden");
    return;
  }
  if (cachedStocks && cachedStocks.length > 0 &&
      !cachedStocks.some((s) => s.symbol === symbol)) {
    errEl.textContent = `"${symbol}" isn't a recognized GSE ticker — pick it from the search list.`;
    errEl.classList.remove("hidden");
    return;
  }
  if (isNaN(shares) || shares <= 0) {
    errEl.textContent = "Shares must be greater than 0.";
    errEl.classList.remove("hidden");
    return;
  }
  if (isNaN(price) || price < 0) {
    errEl.textContent = "Price must be 0 or greater.";
    errEl.classList.remove("hidden");
    return;
  }

  const payload = {
    symbol,
    side: $("tx-side").value,
    shares,
    price,
    trade_date: $("tx-date").value || null,
  };

  try {
    await api("/api/transactions", { method: "POST", body: payload });
    $("tx-modal").classList.add("hidden");
    await loadEverything();
  } catch (err) {
    errEl.textContent = err.message;
    errEl.classList.remove("hidden");
  }
});

init();
