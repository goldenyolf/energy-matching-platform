/* 綠電媒合平台 SPA — hash router + 旗艦「最佳化評估」頁 + 佔位視圖 + 互動。 */
(function () {
  "use strict";
  var view = document.getElementById("view");
  var nav = document.getElementById("nav");
  var crumb = document.getElementById("crumb-page");
  var overlay = document.getElementById("overlay");
  var modalTitle = document.getElementById("modal-title");
  var farmsCache = null; // id -> {code,name}
  var reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ---------- helpers ----------
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }
  function nfmt(n, d) {
    if (n == null || isNaN(n)) return "–";
    return Number(n).toLocaleString("en-US", { minimumFractionDigits: d || 0, maximumFractionDigits: d || 0 });
  }
  function money(n) { return nfmt(Math.round(n), 0); }
  function signed(n) { return (n >= 0 ? "+" : "") + money(n); }
  function abbr(n) {
    if (n == null || isNaN(n)) return "–";
    var a = Math.abs(n), s = n < 0 ? "-" : "";
    if (a >= 1e6) return s + (a / 1e6).toFixed(2) + "M";
    if (a >= 1e3) return s + (a / 1e3).toFixed(1) + "K";
    return s + Math.round(a);
  }
  function pct(n, d) { return n == null || isNaN(n) ? "–" : Number(n).toFixed(d == null ? 1 : d); }
  function price(n) { return n == null || isNaN(n) ? "–" : Number(n).toFixed(3); }
  function farmName(id) {
    var f = farmsCache && farmsCache[id];
    return f ? { code: f.code, name: f.name } : { code: "#" + id, name: "" };
  }
  function showModal(title) { if (title) modalTitle.textContent = title; overlay.classList.add("show"); }
  function hideModal() { overlay.classList.remove("show"); }

  function setActive(route) {
    Array.prototype.forEach.call(nav.querySelectorAll("a"), function (a) {
      a.classList.toggle("on", a.getAttribute("data-route") === route && !a.dataset.page);
    });
  }

  // ---------- router ----------
  function parseHash() {
    var h = (location.hash || "#/overview").replace(/^#\/?/, "");
    var parts = h.split("?");
    var route = parts[0] || "overview";
    var params = {};
    (parts[1] || "").split("&").forEach(function (kv) {
      if (!kv) return; var p = kv.split("="); params[decodeURIComponent(p[0])] = decodeURIComponent(p[1] || "");
    });
    return { route: route, params: params };
  }
  function route() {
    var r = parseHash();
    var views = {
      overview: renderOverview, farms: renderFarms, customers: renderCustomers,
      contracts: renderContracts, evaluate: renderEvaluate, live: renderLive,
    };
    if (r.route === "soon") { renderSoon(r.params.page); setActive("soon"); return; }
    var known = views[r.route];
    (known || renderOverview)();
    setActive(known ? r.route : "overview");
  }
  nav.addEventListener("click", function (e) {
    var a = e.target.closest("a"); if (!a || a.classList.contains("off")) return;
    var rt = a.getAttribute("data-route"); if (!rt) return;
    e.preventDefault();
    location.hash = "#/" + rt + (a.dataset.page ? "?page=" + a.dataset.page : "");
  });
  window.addEventListener("hashchange", route);

  // ---------- placeholder view ----------
  var SOON = {
    farms: ["🏭", "發電案場管理", "案場清單、裝置容量、躉售價與各時段發電量。"],
    optimize: ["🎯", "最佳化媒合", "MILP 全域最佳化(目標毛利、RE 硬約束、最少案場/最小分配%)。"],
    slots: ["⏱️", "時段媒合", "台電三段式時間電價逐時段媒合與時段別經濟。"],
  };
  function renderSoon(page) {
    var s = SOON[page] || ["🧭", "此頁", "此頁面。"];
    crumb.textContent = s[1];
    view.innerHTML =
      '<div class="pagehead"><div class="title"><span class="bar"></span><h1>' + esc(s[1]) + "</h1></div></div>" +
      '<div class="placeholder"><div class="big">' + s[0] + "</div>" +
      "<h2>此頁目前於 Streamlit 儀表板檢視</h2>" +
      "<p>" + esc(s[2]) + " 這一頁尚未移轉到新版介面;請於 Streamlit 儀表板(預設 http://localhost:8501)操作。新版將於後續逐頁移轉。</p></div>";
  }

  // ---------- shared: period-driven pages ----------
  function pageHeadWithPeriod(title, subtitle, id) {
    return '<div class="pagehead"><div><div class="title"><span class="bar"></span><h1>' + esc(title) + "</h1></div>" +
      '<div class="meta"><span>' + esc(subtitle) + "</span></div></div>" +
      '<div class="headactions"><input id="' + id + '-period" class="period-input num" value="2024-01" placeholder="2024-01">' +
      '<button class="btn primary" id="' + id + '-go">查詢</button></div></div>' +
      '<div id="' + id + '-body"><div class="placeholder">載入中…</div></div>';
  }
  function bindPeriod(id, fn) {
    var go = document.getElementById(id + "-go");
    var inp = document.getElementById(id + "-period");
    if (go) go.addEventListener("click", fn);
    if (inp) inp.addEventListener("keydown", function (e) { if (e.key === "Enter") fn(); });
  }
  function periodVal(id) { var el = document.getElementById(id + "-period"); return el ? el.value.trim() : "2024-01"; }
  function reCell(v) {
    var w = Math.max(0, Math.min(100, v || 0));
    return pct(v) + "%<span class=\"re-bar\"><i style=\"width:" + w.toFixed(0) + "%\"></i></span>";
  }
  function metPill(met) {
    return met
      ? '<span class="pill ok"><span class="dot"></span>達標</span>'
      : '<span class="pill warnp"><span class="dot"></span>未達</span>';
  }
  function contractStatusPill(s) {
    var m = { active: ["有效", "ok"], pending: ["待生效", "warnp"], expired: ["已到期", "warnp"], terminated: ["已終止", "warnp"] };
    var x = m[s] || [s, "warnp"];
    return '<span class="pill ' + x[1] + '"><span class="dot"></span>' + esc(x[0]) + "</span>";
  }

  // ---------- 總覽 ----------
  function renderOverview() {
    crumb.textContent = "總覽";
    view.innerHTML = pageHeadWithPeriod("總覽", "平台整體:發電、分配、RE 達成與案場利用率。", "ov");
    bindPeriod("ov", loadOverview);
    loadOverview();
  }
  function loadOverview() {
    var period = periodVal("ov"), body = document.getElementById("ov-body");
    body.innerHTML = '<div class="placeholder">載入中…</div>';
    Promise.all([api.analyticsSummary(period), api.analyticsCustomers(period), api.analyticsWindFarms(period)])
      .then(function (r) {
        var s = r[0], custs = r[1], farms = r[2];
        var html = '<div class="kpis">' +
          kpi("總發電量", nfmt(s.total_generation_mwh, 0) + "<small>MWh</small>", "", "hl") +
          kpi("已分配", nfmt(s.total_allocated_mwh, 0) + "<small>MWh</small>", "未分配 " + nfmt(s.total_unallocated_mwh, 0)) +
          kpi("平均 RE 達成", pct(s.average_re_percent) + "<small>%</small>", "") +
          kpi("總用電量", nfmt(s.total_consumption_mwh, 0) + "<small>MWh</small>", "") +
          kpi("客戶", s.customer_count + "<small>戶</small>", "達標 " + s.customers_meeting_target + " / " + s.customer_count) +
          kpi("風場", s.wind_farm_count + "<small>場</small>", "") +
          "</div><div class=\"grid\">";
        html += '<section class="card"><div class="hd"><h3>各客戶 RE 達成</h3><span class="aside">' + esc(s.period) + "</span></div><div class=\"tablewrap\"><table>" +
          "<thead><tr><th>客戶</th><th>用電 (MWh)</th><th>綠電 (MWh)</th><th>RE 達成</th><th>目標</th><th>達標</th></tr></thead><tbody>";
        custs.forEach(function (c) {
          html += "<tr><td>" + esc(c.company_name) + "</td><td class=\"num\">" + nfmt(c.consumption_mwh, 0) + "</td><td class=\"num\">" + nfmt(c.allocated_mwh, 0) +
            "</td><td class=\"num\">" + reCell(c.achieved_re_percent) + "</td><td class=\"num\">" + pct(c.re_target_percent, 0) + "%</td><td>" + metPill(c.target_met) + "</td></tr>";
        });
        html += "</tbody></table></div></section>";
        html += '<section class="card"><div class="hd"><h3>各風場利用率</h3><span class="aside">' + esc(s.period) + "</span></div><div class=\"tablewrap\"><table>" +
          "<thead><tr><th>風場</th><th>發電 (MWh)</th><th>已分配 (MWh)</th><th>未分配 (MWh)</th><th>利用率</th></tr></thead><tbody>";
        farms.forEach(function (f) {
          html += "<tr><td><span class=\"code\">" + esc(f.code) + "</span> " + esc(f.name) + "</td><td class=\"num\">" + nfmt(f.generated_mwh, 0) +
            "</td><td class=\"num\">" + nfmt(f.allocated_mwh, 0) + "</td><td class=\"num\">" + nfmt(f.unallocated_mwh, 0) + "</td><td class=\"num\">" + reCell(f.utilization_percent) + "</td></tr>";
        });
        html += "</tbody></table></div></section></div>";
        body.innerHTML = html;
      })
      .catch(function (err) { body.innerHTML = errbox("載入總覽", err); });
  }

  // ---------- 企業客戶 ----------
  function renderCustomers() {
    crumb.textContent = "企業客戶";
    view.innerHTML = pageHeadWithPeriod("企業客戶", "客戶基本資料與 RE 目標達成分析。", "cu");
    bindPeriod("cu", loadCustomers);
    loadCustomers();
  }
  function loadCustomers() {
    var period = periodVal("cu"), body = document.getElementById("cu-body");
    body.innerHTML = '<div class="placeholder">載入中…</div>';
    Promise.all([api.customers(), api.analyticsCustomers(period)])
      .then(function (r) {
        var custs = r[0], an = r[1];
        var html = '<section class="card"><div class="hd"><h3>客戶基本資料</h3></div><div class="tablewrap"><table>' +
          "<thead><tr><th>代碼</th><th>公司名稱</th><th>產業</th><th>年用電 (MWh)</th><th>RE 目標</th><th>目標年</th></tr></thead><tbody>";
        custs.forEach(function (c) {
          html += "<tr><td class=\"code\">" + esc(c.code) + "</td><td>" + esc(c.company_name) + "</td><td>" + esc(c.industry || "–") +
            "</td><td class=\"num\">" + nfmt(c.annual_consumption_mwh, 0) + "</td><td class=\"num\">" + pct(c.re_target_percent, 0) + "%</td><td class=\"num\">" + esc(c.target_year || "–") + "</td></tr>";
        });
        html += "</tbody></table></div></section>";
        html += '<section class="card section-gap"><div class="hd"><h3>RE 目標達成分析</h3><span class="aside">' + esc(period) + "</span></div><div class=\"tablewrap\"><table>" +
          "<thead><tr><th>客戶</th><th>用電 (MWh)</th><th>綠電 (MWh)</th><th>RE 達成</th><th>目標</th><th>缺口 (MWh)</th><th>達標</th></tr></thead><tbody>";
        an.forEach(function (c) {
          html += "<tr><td>" + esc(c.company_name) + "</td><td class=\"num\">" + nfmt(c.consumption_mwh, 0) + "</td><td class=\"num\">" + nfmt(c.allocated_mwh, 0) +
            "</td><td class=\"num\">" + reCell(c.achieved_re_percent) + "</td><td class=\"num\">" + pct(c.re_target_percent, 0) + "%</td><td class=\"num\">" + nfmt(c.gap_to_target_mwh, 0) + "</td><td>" + metPill(c.target_met) + "</td></tr>";
        });
        html += "</tbody></table></div></section>";
        body.innerHTML = html;
      })
      .catch(function (err) { body.innerHTML = errbox("載入客戶", err); });
  }

  // ---------- 綠電合約 ----------
  function renderContracts() {
    crumb.textContent = "綠電合約";
    view.innerHTML = '<div class="pagehead"><div class="title"><span class="bar"></span><h1>綠電合約</h1></div>' +
      '<div class="meta"><span>PPA 合約清單:風場、客戶、費率、比例、優先序、狀態。</span></div></div>' +
      '<div id="ct-body"><div class="placeholder">載入中…</div></div>';
    var body = document.getElementById("ct-body");
    Promise.all([api.contracts(), api.windFarms(), api.customers()])
      .then(function (r) {
        var cs = r[0], fm = {}, cm = {};
        r[1].forEach(function (f) { fm[f.id] = f.code; });
        r[2].forEach(function (c) { cm[c.id] = c.code; });
        var html = '<section class="card"><div class="hd"><h3>合約清單</h3><span class="aside">' + cs.length + " 筆</span></div><div class=\"tablewrap\"><table>" +
          "<thead><tr><th>合約編號</th><th>風場</th><th>客戶</th><th>起始</th><th>結束</th><th>合約電量 (MWh)</th><th>合約比例</th><th>售電價</th><th>優先序</th><th>狀態</th></tr></thead><tbody>";
        cs.forEach(function (c) {
          html += "<tr><td class=\"code\">" + esc(c.contract_number) + "</td><td>" + esc(fm[c.wind_farm_id] || c.wind_farm_id) + "</td><td>" + esc(cm[c.customer_id] || c.customer_id) +
            "</td><td class=\"num\">" + esc(c.start_date) + "</td><td class=\"num\">" + esc(c.end_date) +
            "</td><td class=\"num\">" + (c.contracted_energy_mwh != null ? nfmt(c.contracted_energy_mwh, 0) : "–") +
            "</td><td class=\"num\">" + (c.contracted_percentage != null ? pct(c.contracted_percentage, 0) + "%" : "–") +
            "</td><td class=\"num\">" + (c.price_per_kwh != null ? price(c.price_per_kwh) : "–") +
            "</td><td class=\"num\">" + c.priority + "</td><td>" + contractStatusPill(c.status) + "</td></tr>";
        });
        html += "</tbody></table></div></section>";
        body.innerHTML = html;
      })
      .catch(function (err) { body.innerHTML = errbox("載入合約", err); });
  }

  // ---------- 即時再生能源 ----------
  function renderLive() {
    crumb.textContent = "即時再生能源";
    view.innerHTML = '<div class="pagehead"><div><div class="title"><span class="bar"></span><h1>即時再生能源</h1></div>' +
      '<div class="meta"><span>台電各機組即時發電(約 10 分更新);瞬時 MW,不進媒合。</span></div></div>' +
      '<div class="headactions"><button class="btn ghost" id="lv-refresh"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M20 11a8 8 0 1 0-2.3 5.7M20 5v6h-6"/></svg>重新整理</button></div></div>' +
      '<div id="lv-body"><div class="placeholder">載入中…</div></div>';
    document.getElementById("lv-refresh").addEventListener("click", function () { loadLive(true); });
    loadLive(false);
  }
  function loadLive(force) {
    var body = document.getElementById("lv-body");
    body.innerHTML = '<div class="placeholder">載入中…</div>';
    api.liveRenewables(force)
      .then(function (d) {
        var html = '<div class="kpis" style="grid-template-columns:repeat(3,1fr)">' +
          kpi("快照時間", esc(d.snapshot_time || "–"), "") +
          kpi("風力總出力", nfmt(d.wind_total_mw, 1) + "<small>MW</small>", "", "hl") +
          kpi("再生能源總出力", nfmt(d.renewable_total_mw, 1) + "<small>MW</small>", "") +
          "</div><div class=\"grid\">";
        html += '<section class="card"><div class="hd"><h3>各再生能源類型</h3></div><div class="tablewrap"><table>' +
          "<thead><tr><th>類型</th><th>機組數</th><th>淨出力 (MW)</th></tr></thead><tbody>";
        (d.renewable_summary || []).forEach(function (x) {
          html += "<tr><td>" + esc(x.unit_type) + "</td><td class=\"num\">" + x.unit_count + "</td><td class=\"num\">" + nfmt(x.net_mw, 1) + "</td></tr>";
        });
        html += "</tbody></table></div></section>";
        html += '<section class="card"><div class="hd"><h3>風力各機組</h3><span class="aside">' + (d.wind || []).length + " 機組</span></div><div class=\"tablewrap\"><table>" +
          "<thead><tr><th>機組</th><th>裝置容量 (MW)</th><th>淨發電 (MW)</th></tr></thead><tbody>";
        if (!(d.wind || []).length) {
          html += '<tr><td class="empty" colspan="3">目前無風力機組資料</td></tr>';
        } else {
          d.wind.forEach(function (w) {
            html += "<tr><td>" + esc(w.name) + "</td><td class=\"num\">" + (w.capacity_mw != null ? nfmt(w.capacity_mw, 1) : "–") + "</td><td class=\"num\">" + (w.net_mw != null ? nfmt(w.net_mw, 1) : "–") + "</td></tr>";
          });
        }
        html += "</tbody></table></div></section></div>";
        body.innerHTML = html;
      })
      .catch(function (err) { body.innerHTML = errbox("載入即時再生能源", err); });
  }

  // ---------- 發電案場管理 ----------
  function statusPill(s) {
    var m = {
      operational: ["運轉中", "ok"], under_construction: ["建置中", "warnp"],
      planning: ["規劃中", "warnp"], decommissioned: ["除役", "warnp"],
    };
    var x = m[s] || [s || "–", "warnp"];
    return '<span class="pill ' + x[1] + '"><span class="dot"></span>' + esc(x[0]) + "</span>";
  }

  function renderFarms() {
    crumb.textContent = "發電案場管理";
    view.innerHTML =
      '<div class="pagehead"><div class="title"><span class="bar"></span><h1>發電案場管理</h1></div>' +
      '<div class="meta"><span>風場基本資料、裝置容量、躉售價與各時段發電量。</span></div></div>' +
      '<div id="farms-body"><div class="placeholder">載入中…</div></div>';
    var body = document.getElementById("farms-body");
    Promise.all([api.windFarms(), api.generation()]).then(function (r) {
      var farms = r[0], gen = r[1];
      var agg = {};
      gen.forEach(function (g) {
        var a = agg[g.wind_farm_id] || (agg[g.wind_farm_id] = { total: 0, peak: 0, half_peak: 0, off_peak: 0 });
        a.total += g.generated_energy_mwh || 0;
        if (g.time_slot && a[g.time_slot] != null) a[g.time_slot] += g.generated_energy_mwh || 0;
      });
      var totCap = farms.reduce(function (s, f) { return s + (f.installed_capacity_mw || 0); }, 0);
      var totGen = Object.keys(agg).reduce(function (s, k) { return s + agg[k].total; }, 0);
      var prices = farms.map(function (f) { return f.feed_in_price_per_kwh; }).filter(function (v) { return v != null; });
      var avgPrice = prices.length ? prices.reduce(function (s, v) { return s + v; }, 0) / prices.length : null;

      var html = '<div class="kpis" style="grid-template-columns:repeat(4,1fr)">' +
        kpi("案場數", farms.length + "<small>場</small>", "已納入媒合", "hl") +
        kpi("總裝置容量", nfmt(totCap, 1) + "<small>MW</small>", "跨全部案場") +
        kpi("總發電量", nfmt(totGen, 0) + "<small>MWh</small>", "資料區間累積") +
        kpi("平均躉售價", avgPrice != null ? price(avgPrice) : "–", "NTD / kWh") +
        "</div>";
      html += '<section class="card"><div class="hd"><h3>發電數據</h3><span class="aside">' + farms.length + " 場 · 含時段別發電</span></div><div class=\"tablewrap\"><table>" +
        "<thead><tr><th>案場</th><th>營運商</th><th>場址</th><th>裝置容量 (MW)</th><th>商轉日</th><th>躉售價</th><th>狀態</th><th>尖峰 (MWh)</th><th>半尖峰 (MWh)</th><th>離峰 (MWh)</th><th>總發電 (MWh)</th></tr></thead><tbody>";
      farms.slice().sort(function (a, b) { return a.code > b.code ? 1 : -1; }).forEach(function (f) {
        var a = agg[f.id] || { total: 0, peak: 0, half_peak: 0, off_peak: 0 };
        html += "<tr><td><span class=\"code\">" + esc(f.code) + "</span> " + esc(f.name) + "</td>" +
          "<td style=\"text-align:left\">" + esc(f.operator_name || "–") + "</td>" +
          "<td style=\"text-align:left\">" + esc(f.location || "–") + "</td>" +
          "<td class=\"num\">" + nfmt(f.installed_capacity_mw, 1) + "</td>" +
          "<td class=\"num\">" + esc(f.commercial_operation_date || "–") + "</td>" +
          "<td class=\"num\">" + (f.feed_in_price_per_kwh != null ? price(f.feed_in_price_per_kwh) : "–") + "</td>" +
          "<td>" + statusPill(f.status) + "</td>" +
          "<td class=\"num\">" + nfmt(a.peak, 0) + "</td><td class=\"num\">" + nfmt(a.half_peak, 0) + "</td><td class=\"num\">" + nfmt(a.off_peak, 0) + "</td>" +
          "<td class=\"num\" style=\"font-weight:700\">" + nfmt(a.total, 0) + "</td></tr>";
      });
      html += "</tbody></table></div></section>";
      html += '<div class="foot-note">' + iconInfo() + "示範資料為模擬。各時段發電由 generate_slot_profiles 依風電典型占比拆分(離峰較高)。</div>";
      body.innerHTML = html;
    }).catch(function (err) { body.innerHTML = errbox("載入發電案場", err); });
  }

  // ---------- flagship: 最佳化評估 ----------
  function renderEvaluate() {
    crumb.textContent = "售電評估工具";
    view.innerHTML =
      '<div class="pagehead"><div class="title"><span class="bar"></span><h1>最佳化評估</h1></div>' +
      '<div class="meta"><span>對選定用電戶跑最佳化媒合,產出雙面經濟評估與時段別達成。</span></div></div>' +
      '<form class="formcard" id="evalForm"><div class="formgrid">' +
      '<div class="field"><label>用電戶<span class="req">*</span></label><select id="f-customer" required><option value="">載入中…</option></select></div>' +
      '<div class="field"><label>期間 (YYYY-MM)</label><input id="f-period" class="num" value="2024-01" placeholder="2024-01"></div>' +
      '<div class="field"><label>最小分配 %</label><input id="f-minpct" class="num" type="number" min="0" max="100" step="1" value="0"></div>' +
      '<div class="field"><label>最少案場數</label><input id="f-minsites" class="num" type="number" min="0" max="20" step="1" value="0"></div>' +
      '<div class="field"><label>RE 目標 %</label><input id="f-retarget" class="num" type="number" min="0" max="100" step="1" placeholder="依資料設定"><span class="hint">可覆寫</span></div>' +
      '<div class="field"><label>綠電轉供價</label><input id="f-transfer" class="num" type="number" min="0" step="0.1" placeholder="依合約"><span class="hint">NTD/kWh · 可覆寫</span></div>' +
      '</div><div class="formactions"><button class="btn primary" type="submit">' +
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 7h16M7 12h10M10 17h4"/></svg>執行演算評估</button></div></form>' +
      '<div id="result"></div>';

    var sel = document.getElementById("f-customer");
    var reTarget = document.getElementById("f-retarget");
    var custMap = {};
    api.customers().then(function (list) {
      sel.innerHTML = list.map(function (c) {
        custMap[c.id] = c;
        return '<option value="' + c.id + '">' + esc(c.code + " · " + c.company_name) + "</option>";
      }).join("");
      if (list[0]) reTarget.value = pct(list[0].re_target_percent, 0);
    }).catch(function (err) {
      sel.innerHTML = '<option value="">無法載入用電戶</option>';
      document.getElementById("result").innerHTML = errbox("載入用電戶", err);
    });
    sel.addEventListener("change", function () {
      var c = custMap[sel.value];
      reTarget.value = c ? pct(c.re_target_percent, 0) : "";
    });

    document.getElementById("evalForm").addEventListener("submit", function (e) {
      e.preventDefault();
      var customerId = parseInt(sel.value, 10);
      if (!customerId) { sel.focus(); return; }
      var period = document.getElementById("f-period").value.trim();
      var minPct = parseFloat(document.getElementById("f-minpct").value) || 0;
      var minSites = parseInt(document.getElementById("f-minsites").value, 10) || 0;
      var rtv = document.getElementById("f-retarget").value.trim();
      var reTargetV = rtv === "" ? null : parseFloat(rtv);
      var tpv = document.getElementById("f-transfer").value.trim();
      var transferV = tpv === "" ? null : parseFloat(tpv);
      runEvaluation(customerId, custMap[customerId], period, minSites, minPct, reTargetV, transferV);
    });
  }

  function runEvaluation(customerId, customer, period, minSites, minPct, reTarget, transferPrice) {
    showModal("正在求解最佳綠電組合…");
    var result = document.getElementById("result");
    api.customerOptimization(customerId, period, minSites, minPct, reTarget, transferPrice)
      .then(function (r) { renderResult(result, r, customer); })
      .catch(function (err) { result.innerHTML = errbox("執行評估", err); })
      .then(function () { setTimeout(hideModal, reduce ? 0 : 350); });
  }

  function errbox(where, err) {
    var msg = (err && err.message) || "未知錯誤";
    return '<div class="errbox"><h3>' + esc(where) + "失敗</h3><p>" + esc(msg) +
      "</p><button class=\"btn ghost\" onclick=\"location.reload()\">重新載入</button></div>";
  }

  function renderResult(root, r, customer) {
    var seller = r.seller, buyer = r.buyer;
    var reTargetPct = r.re_target_percent;
    var allocs = r.allocations || [];
    var sellPrice = buyer.green_mwh > 0 ? seller.sales_revenue / (buyer.green_mwh * 1000) : 0;
    var okPill = r.solver_status === "Optimal";
    var seasonLabel = r.season === "summer" ? "夏月" : "非夏月";

    var html = "";
    html += '<div class="pagehead" style="margin-top:22px"><div><div class="title"><span class="bar"></span><h1>評估結果</h1>' +
      '<span class="pill ' + (okPill ? "ok" : "warnp") + '"><span class="dot"></span>求解狀態 ' + esc(r.solver_status) + "</span></div>" +
      '<div class="meta"><span>用電戶 <b>' + esc(r.company_name) + "</b></span>" +
      "<span>期間 <b>" + esc(r.period) + " · " + seasonLabel + "</b></span>" +
      "<span>約束 <b>最小分配 " + pct(r.min_site_allocation_percent, 0) + "% · 最少 " + r.min_sites_per_customer + " 場</b></span>" +
      (r.transfer_price_used != null ? "<span>轉供價覆寫 <b>" + price(r.transfer_price_used) + "</b></span>" : "") +
      "</div></div>" +
      '<div class="headactions"><button class="btn primary" id="rerun2"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M20 11a8 8 0 1 0-2.3 5.7M20 5v6h-6"/></svg>再次評估</button></div></div>';

    html += '<div style="margin:-4px 0 16px;font-size:12px;color:var(--muted);line-height:1.6">' +
      '四塊皆由<b style="color:var(--brand)">同一次 MILP 最佳化</b>導出,數值一致;時段別為依案場時段發電占比推估(受各時段用電上限)。</div>';

    // KPI strip
    html += '<div class="kpis">' +
      kpi("RE 達成率", pct(buyer.re_percent) + "<small>%</small>", "目標 " + pct(reTargetPct, 0) + "%", "hl") +
      kpi("售電端毛利", "NT$ " + abbr(seller.gross_profit), "毛利率 " + pct(seller.gross_margin_percent, 2) + "%", "", seller.gross_profit >= 0 ? "up" : "down") +
      kpi("配對案場", allocs.length + "<small>場</small>", "綠電轉供率 " + pct(buyer.re_percent) + "%") +
      kpi("綠電轉供量", nfmt(buyer.green_mwh, 0) + "<small>MWh</small>", "灰電 " + nfmt(buyer.grey_mwh, 0) + " MWh") +
      kpi("售電均價", price(sellPrice), "NTD / kWh") +
      kpi("用電均價", price(buyer.avg_price_per_kwh), "含綠+灰電") +
      "</div>";

    // body grid
    html += '<div class="grid"><div class="stack">';

    // seller card
    html += '<section class="card side-seller"><div class="hd"><span class="ic">' + iconMoney() + "</span>" +
      "<h3>售電端 · 發電業收益</h3><span class=\"aside\">綠電轉供均價 " + price(sellPrice) + " NTD/kWh</span></div>";
    if (r.used_default_feed_in_price) html += '<div class="note">部分風場未填收購價,已用預設值估算。</div>';
    html += '<div class="rows">' +
      erow("收購成本(躉售 / FIT)", money(seller.procurement_cost), "NTD") +
      erow("售電收入(綠電轉供)", money(seller.sales_revenue), "NTD") +
      erowTotal("售電毛利", signed(seller.gross_profit), "NTD", seller.gross_profit >= 0 ? "pos" : "neg") +
      erow("售電毛利率", pct(seller.gross_margin_percent, 2) + "%", "", seller.gross_margin_percent >= 0 ? "pos" : "neg") +
      "</div></section>";

    // buyer card
    var reP = Math.max(0, Math.min(100, buyer.re_percent || 0));
    var gap = Math.max(0, reTargetPct - buyer.re_percent);
    html += '<section class="card side-buyer"><div class="hd"><span class="ic">' + iconBolt() + "</span>" +
      "<h3>用電端 · 企業客戶成本</h3><span class=\"aside\">目標達成度</span></div>" +
      '<div class="gauge"><div class="ring" style="--p:' + reP.toFixed(1) + '"><b class="num">' + pct(buyer.re_percent) + "%</b></div>" +
      '<div class="g-meta"><div class="big">RE 比例 <b>' + pct(buyer.re_percent) + "%</b> / 目標 " + pct(reTargetPct, 0) + "%</div>" +
      '<div class="barwrap"><i style="width:' + reP.toFixed(1) + '%"></i></div>' +
      '<div class="target-flag">' + (gap > 0.05 ? "尚差 " + pct(gap) + "% · " + nfmt(buyer.grey_mwh, 0) + " MWh 留灰電" : "已達目標") + "</div></div></div>" +
      '<div class="rows">' +
      erow("總用電量", nfmt(buyer.total_consumption_mwh, 0), "MWh") +
      erow("— 綠電用電量", nfmt(buyer.green_mwh, 0), "MWh", "", "color:var(--buyer)") +
      erow("— 灰電用電量", nfmt(buyer.grey_mwh, 0), "MWh") +
      erow("用電平均單價", price(buyer.avg_price_per_kwh), "NTD/kWh") +
      erowTotal("增加用電成本(綠電溢價)", signed(buyer.added_cost), "NTD", "prem") +
      "</div></section>";

    html += '</div><div class="stack">';

    // 發電端分配概況
    html += '<section class="card"><div class="hd"><h3>發電端分配概況</h3><span class="aside">此用電戶</span></div>' +
      '<div class="tablewrap"><table><thead><tr><th>配對案場</th><th>綠電售電量 (MWh)</th><th>綠電轉供率</th><th>預估營收 (NTD)</th></tr></thead><tbody>' +
      "<tr><td>" + allocs.length + " 場</td><td class=\"num\">" + nfmt(buyer.green_mwh, 0) + "</td><td class=\"num pos\">" + pct(buyer.re_percent) + "%</td><td class=\"num\">" + money(seller.sales_revenue) + "</td></tr>" +
      "</tbody></table></div></section>";

    // 逐案場明細
    html += '<section class="card"><div class="hd"><h3>匹配案場細節</h3><span class="aside">' + allocs.length + " 場</span></div><div class=\"tablewrap\"><table>" +
      "<thead><tr><th>案場</th><th>已分配 (MWh)</th><th>分配比例</th><th>分配原因</th></tr></thead><tbody>";
    if (!allocs.length) {
      html += '<tr><td class="empty" colspan="4">此期間該用電戶無綠電分配</td></tr>';
    } else {
      allocs.forEach(function (a) {
        var share = Math.max(0, Math.min(100, a.share_percent || 0));
        html += "<tr><td><span class=\"code\">" + esc(a.wind_farm_code) + "</span> " + esc(a.wind_farm_name) + "</td>" +
          "<td class=\"num\">" + nfmt(a.allocated_mwh, 1) + "</td>" +
          "<td><span class=\"barcell num\">" + pct(share, 0) + "%<span class=\"minibar\"><i style=\"width:" + share.toFixed(0) + "%\"></i></span></span></td>" +
          "<td style=\"text-align:left;color:var(--muted);font-size:12px;white-space:normal;max-width:280px\">" + esc(a.reason) + "</td></tr>";
      });
    }
    html += "</tbody></table></div></section>";

    // 時段別(與經濟同源;綠電受各時段用電上限)
    var slotLabel = { peak: ["尖峰", "s-peak"], half_peak: ["半尖峰", "s-half"], off_peak: ["離峰", "s-off"] };
    html += '<section class="card"><div class="hd"><h3>時段別達成</h3><span class="aside" style="color:var(--buyer)">台電時間電價</span></div><div class="tablewrap"><table>' +
      "<thead><tr><th>時段</th><th>灰電價</th><th>用電量 (MWh)</th><th>綠電分配 (MWh)</th><th>時段 RE</th></tr></thead><tbody>";
    var peakRe = null;
    (r.slot_breakdown || []).forEach(function (b) {
      var lbl = slotLabel[b.slot] || [b.slot, "s-half"];
      if (b.slot === "peak") peakRe = b.re_percent;
      var w = Math.max(0, Math.min(100, b.re_percent || 0));
      html += "<tr><td><span class=\"tag-slot " + lbl[1] + "\">" + esc(lbl[0]) + "</span></td>" +
        "<td class=\"num\">" + price(b.grey_price_per_kwh) + "</td>" +
        "<td class=\"num\">" + nfmt(b.consumption_mwh, 0) + "</td>" +
        "<td class=\"num\">" + nfmt(b.allocated_mwh, 0) + "</td>" +
        "<td class=\"num\">" + pct(b.re_percent) + "%<span class=\"re-bar\"><i style=\"width:" + w.toFixed(0) + "%\"></i></span></td></tr>";
    });
    html += "</tbody></table></div>";
    var surplus = r.time_mismatch_surplus_mwh || 0;
    html += '<div class="slotnote">' +
      (peakRe != null ? "風電離峰(夜間)發電多、尖峰用電在日間 → <b>尖峰 RE 僅 " + pct(peakRe) + "%</b>。" : "") +
      (surplus > 0.5 ? "另有 <b>" + nfmt(surplus, 0) + " MWh</b> 離峰過剩綠電無法於該時段媒合(時段錯配)。" : "") +
      "月度加總會高估;逐時段才是真實達成。</div>";
    html += "</section>";

    html += "</div></div>"; // grid

    html += '<div class="foot-note">' + iconInfo() + "示範資料為模擬,與台電及任何能源公司無官方關係。單位:能量 MWh、金額 NTD、電價 NTD/kWh。</div>";

    root.innerHTML = html;
    var rr = document.getElementById("rerun2");
    if (rr) rr.addEventListener("click", function () {
      var form = document.getElementById("evalForm");
      if (form) form.dispatchEvent(new Event("submit", { cancelable: true }));
    });
    root.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
  }

  // small builders
  function kpi(k, v, sub, cls, subcls) {
    return '<div class="kpi"><span class="k">' + esc(k) + '</span><span class="v ' + (cls || "") + ' num">' + v +
      '</span><span class="sub ' + (subcls || "") + '">' + esc(sub) + "</span></div>";
  }
  function erow(lab, val, u, valcls, style) {
    return '<div class="row"><span class="lab">' + esc(lab) + '</span><span class="val num ' + (valcls || "") + '"' + (style ? ' style="' + style + '"' : "") + ">" +
      val + (u ? '<span class="u">' + esc(u) + "</span>" : "") + "</span></div>";
  }
  function erowTotal(lab, val, u, valcls) {
    return '<div class="row total"><span class="lab">' + esc(lab) + '</span><span class="val num ' + (valcls || "") + '">' +
      val + (u ? '<span class="u">' + esc(u) + "</span>" : "") + "</span></div>";
  }
  function iconMoney() { return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 1v22M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>'; }
  function iconBolt() { return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M13 2 4 14h7l-1 8 9-12h-7z"/></svg>'; }
  function iconInfo() { return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="9"/><path d="M12 8h.01M11 12h1v4h1"/></svg>'; }

  // ---------- theme toggle ----------
  document.getElementById("themeBtn").addEventListener("click", function () {
    var root = document.documentElement;
    var cur = root.getAttribute("data-theme");
    if (!cur) cur = matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    root.setAttribute("data-theme", cur === "dark" ? "light" : "dark");
  });
  overlay.addEventListener("click", function (e) { if (e.target === overlay) hideModal(); });

  // ---------- boot ----------
  route();
})();
