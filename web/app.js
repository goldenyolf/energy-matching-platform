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
  function money(n) {
    if (n == null || isNaN(n)) return "–";
    if (Math.abs(n) >= 1e8) {
      return Number(n / 1e8).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + " 億";
    }
    return nfmt(Math.round(n), 0);
  }
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
  // loading: light non-blocking top bar + optional "求解中" text chip
  var loadbar = document.getElementById("loadbar");
  var loadmsg = document.getElementById("loadmsg");
  var loadmsgTxt = document.getElementById("loadmsg-txt");
  function showModal(msg) {
    loadbar.classList.add("on");
    if (msg) { loadmsgTxt.textContent = msg; loadmsg.classList.add("on"); }
  }
  function hideModal() { loadbar.classList.remove("on"); loadmsg.classList.remove("on"); }

  // 短暫的成功/錯誤提示(toast);kind: "ok" | "bad" | "info"
  var toastBox = document.getElementById("toasts");
  function toast(msg, kind) {
    var t = document.createElement("div");
    t.className = "toast " + (kind || "ok");
    t.innerHTML = '<span class="dot"></span><span></span>';
    t.lastChild.textContent = msg;
    toastBox.appendChild(t);
    requestAnimationFrame(function () { t.classList.add("show"); });
    setTimeout(function () {
      t.classList.remove("show");
      setTimeout(function () { t.remove(); }, reduce ? 0 : 240);
    }, 2200);
  }

  // shared "last used period" so it carries across pages
  var _period = null;
  function getPeriod() {
    if (_period == null) {
      try { _period = localStorage.getItem("emp-period") || "2024-01"; } catch (e) { _period = "2024-01"; }
    }
    return _period;
  }
  function setPeriod(p) {
    if (p && /^\d{4}-\d{2}$/.test(p)) { _period = p; try { localStorage.setItem("emp-period", p); } catch (e) { /* ignore */ } }
  }

  // sub-tab groups: related sub-views share one nav item + a segmented tab bar
  var TABS_PNL = [{ route: "evaluate", name: "售電評估" }, { route: "settlement", name: "轉供結算單" }];
  var TABS_MM = [{ route: "matchmap", name: "多對多情境" }, { route: "recommend", name: "RE 補足建議" }];
  var TAB_GROUPS = {
    evaluate: TABS_PNL, settlement: TABS_PNL,
    matchmap: TABS_MM, recommend: TABS_MM,
  };
  // sub-route → the nav item that should stay highlighted (電號 drills in from 企業客戶)
  var NAV_PARENT = { meters: "customers", settlement: "evaluate", recommend: "matchmap", contract: "contracts" };

  function subtabs(items, active) {
    return '<div class="subtabs">' + items.map(function (t) {
      return '<a class="subtab' + (t.route === active ? " on" : "") + '" href="#/' + t.route + '">' + esc(t.name) + "</a>";
    }).join("") + "</div>";
  }

  function setActive(route) {
    var parent = NAV_PARENT[route] || route;
    Array.prototype.forEach.call(nav.querySelectorAll("a"), function (a) {
      a.classList.toggle("on", a.getAttribute("data-route") === parent && !a.dataset.page);
    });
  }

  var dataBadge = document.getElementById("dataBadge");
  function setDataBadge(route) {
    if (!dataBadge) return;
    var real = route === "live";
    dataBadge.classList.toggle("real", real);
    dataBadge.textContent = real ? "即時 · 台電資料" : "示範資料";
    dataBadge.title = real
      ? "本頁為真實資料:台電公開「各機組即時發電」(約 10 分更新)。僅供監控,不進媒合引擎。"
      : "示範資料:發電、用電、合約、媒合與投資效益皆為模擬 demo。用電端為匿名化的示範對象;風場名稱為真實,但數字為模擬。僅「即時再生能源」頁為台電真實資料。";
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
      meters: renderMeters, contracts: renderContracts, evaluate: renderEvaluate,
      investment: renderInvestment, recommend: renderRecommend,
      matchmap: renderMatchmap, cfe: renderCfe,
      settlement: renderSettlement, trecs: renderTrecs, risks: renderRisks,
      live: renderLive,
      contract: renderContractDetail,
    };
    if (r.route === "soon") { renderSoon(r.params.page); setActive("soon"); setDataBadge("soon"); return; }
    var known = views[r.route];
    (known || renderOverview)();
    var active = known ? r.route : "overview";
    if (TAB_GROUPS[active]) view.insertAdjacentHTML("afterbegin", subtabs(TAB_GROUPS[active], active));
    setActive(active);
    setDataBadge(active);
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
      '<div class="headactions"><input id="' + id + '-period" class="period-input num" value="' + getPeriod() + '" placeholder="2024-01">' +
      '<button class="btn primary" id="' + id + '-go">查詢</button></div></div>' +
      '<div id="' + id + '-body"><div class="placeholder">載入中…</div></div>';
  }
  function bindPeriod(id, fn) {
    var go = document.getElementById(id + "-go");
    var inp = document.getElementById(id + "-period");
    if (go) go.addEventListener("click", fn);
    if (inp) inp.addEventListener("keydown", function (e) { if (e.key === "Enter") fn(); });
  }
  function periodVal(id) { var el = document.getElementById(id + "-period"); var v = el ? el.value.trim() : "2024-01"; setPeriod(v); return v; }
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
    var m = { active: ["有效", "ok"], pending: ["待生效", "neut"], expired: ["已到期", "neut"], terminated: ["已終止", "bad"] };
    var x = m[s] || [s, "neut"];
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
          "</div><div class=\"stack\">";
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
        var html = '<section class="card"><div class="hd"><h3>客戶基本資料</h3><span class="aside">點代碼可查看該客戶的電號/廠區</span>' + entityAddBtn("customer", "新增客戶") + importBtn("customer") + "</div><div class=\"tablewrap\"><table>" +
          "<thead><tr><th>代碼</th><th>公司名稱</th><th>產業</th><th>總用電 (MWh)</th><th>RE 目標</th><th>目標年</th><th>電號/廠區</th>" + (editMode ? '<th class="actcol">操作</th>' : "") + "</tr></thead><tbody>";
        custs.forEach(function (c) {
          crudCache.customer[c.id] = c;
          html += "<tr><td class=\"code\"><a href=\"#/meters?cid=" + c.id + "\">" + esc(c.code) + "</a></td><td>" + esc(c.company_name) + "</td><td>" + esc(c.industry || "–") +
            "</td><td class=\"num\">" + nfmt(c.annual_consumption_mwh, 0) + "</td><td class=\"num\">" + pct(c.re_target_percent, 0) + "%</td><td class=\"num\">" + esc(c.target_year || "–") + "</td>" +
            "<td><a href=\"#/meters?cid=" + c.id + "\">查看電號 →</a></td>" +
            rowActions("customer", c.id) + "</tr>";
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

  // ---------- 多電號/廠區 ----------
  function renderMeters() {
    crumb.textContent = "電號/廠區";
    var presetCid = parseHash().params.cid ? parseInt(parseHash().params.cid, 10) : null;
    view.innerHTML =
      '<div class="pagehead"><div><div class="title"><span class="bar"></span><h1>電號 / 廠區</h1></div>' +
      '<div class="meta"><span><a href="#/customers">← 企業客戶</a></span><span>各電號的用電負載與 RE 目標達成;各電號年度用電加總 = 客戶總用電量。</span></div></div></div>' +
      '<form class="formcard" id="mtForm"><div class="formgrid">' +
      '<div class="field"><label>用電戶<span class="req">*</span></label><select id="m-customer" required><option value="">載入中…</option></select></div>' +
      '<div class="field"><label>期間 (YYYY-MM)</label><input id="m-period" class="num" value="' + getPeriod() + '"></div>' +
      '</div><div class="formactions"><button class="btn primary" type="submit">' +
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="8"/><path d="M12 12l3-3"/></svg>查看各電號</button></div></form>' +
      '<div id="mt-body"><div class="placeholder">載入中…</div></div>';
    var sel = document.getElementById("m-customer");
    api.customers().then(function (list) {
      sel.innerHTML = list.map(function (c) {
        return '<option value="' + c.id + '">' + esc(c.code + " · " + c.company_name) + "</option>";
      }).join("");
      if (presetCid && list.some(function (c) { return c.id === presetCid; })) sel.value = presetCid;
      run();
    }).catch(function (err) {
      sel.innerHTML = '<option value="">無法載入用電戶</option>';
      document.getElementById("mt-body").innerHTML = errbox("載入用電戶", err);
    });
    function run() {
      var cid = parseInt(sel.value, 10); if (!cid) return;
      var period = document.getElementById("m-period").value.trim();
      var body = document.getElementById("mt-body");
      body.innerHTML = '<div class="placeholder">載入中…</div>';
      Promise.all([api.meters(cid), api.meterBreakdown(cid, period)])
        .then(function (res) { body.innerHTML = renderMeterManage(cid, res[0]) + renderMeterBreakdownHtml(res[1]); })
        .catch(function (err) { body.innerHTML = errbox("載入電號", err); });
    }
    document.getElementById("mtForm").addEventListener("submit", function (e) { e.preventDefault(); run(); });
  }

  function kOr(v) { return v != null ? nfmt(v, 0) : "–"; }
  // 用電負載數據(各電號)管理表(含新增/編輯/刪除)
  function renderMeterManage(cid, meters) {
    meters.forEach(function (m) { crudCache.meter[m.id] = m; });
    var sumKwh = meters.reduce(function (s, m) { return s + (m.total_kwh || 0); }, 0);
    var html = '<section class="card"><div class="hd"><h3>用電負載數據(各電號)</h3><span class="aside">年度用電加總 ' + nfmt(sumKwh / 1000, 0) + " MWh(= 客戶總用電)</span>" + entityAddBtn("meter", "新增電號", cid) + importBtn("meter") + "</div><div class=\"tablewrap\"><table>" +
      "<thead><tr><th>電號</th><th>用電名稱</th><th>契約容量 (kW)</th><th>時間電價</th><th>尖峰 (kWh)</th><th>半尖峰 (kWh)</th><th>周六半尖峰 (kWh)</th><th>離峰 (kWh)</th><th>總量 (kWh)</th><th>數據區間</th>" + (editMode ? '<th class="actcol">操作</th>' : "") + "</tr></thead><tbody>";
    if (!meters.length) {
      html += '<tr><td class="empty" colspan="' + (editMode ? 11 : 10) + '">此客戶尚無電號' + (editMode ? ",可按「新增電號」建立。" : "。") + "</td></tr>";
    } else {
      meters.forEach(function (m) {
        html += "<tr><td><span class=\"code\">" + esc(m.code) + "</span></td>" +
          "<td style=\"text-align:left\">" + esc(m.usage_name || m.name || "–") + "</td>" +
          "<td class=\"num\">" + (m.contracted_capacity_kw != null ? nfmt(m.contracted_capacity_kw, 0) : "–") + "</td>" +
          "<td>" + (m.tariff_type ? (TARIFF_LABEL[m.tariff_type] || m.tariff_type) : "–") + "</td>" +
          "<td class=\"num\">" + kOr(m.peak_kwh) + "</td><td class=\"num\">" + kOr(m.half_peak_kwh) + "</td><td class=\"num\">" + kOr(m.saturday_half_peak_kwh) + "</td><td class=\"num\">" + kOr(m.off_peak_kwh) + "</td>" +
          "<td class=\"num\" style=\"font-weight:700\">" + kOr(m.total_kwh) + "</td>" +
          "<td class=\"num\">" + esc(m.data_period || "–") + "</td>" + rowActions("meter", m.id) + "</tr>";
      });
    }
    html += "</tbody></table></div></section>";
    return html;
  }

  // 各電號時段用電結構迷你堆疊條 (尖/半/離);無負載資料時顯示 –
  function touCell(m) {
    if (m.peak_mwh == null) return '<span class="u">–</span>';
    var p = m.peak_mwh, h = m.half_peak_mwh, o = m.off_peak_mwh, t = (p + h + o) || 1;
    var seg = function (v, cls) { return '<i class="' + cls + '" style="width:' + (v / t * 100) + '%"></i>'; };
    return '<div class="toubar" title="尖峰 ' + nfmt(p, 0) + " · 半尖峰 " + nfmt(h, 0) + " · 離峰 " + nfmt(o, 0) + ' MWh">' +
      seg(p, "sp") + seg(h, "hp") + seg(o, "op") + "</div>" +
      '<div class="toutxt">' + nfmt(p, 0) + " / " + nfmt(h, 0) + " / " + nfmt(o, 0) + "</div>";
  }

  function renderMeterBreakdownHtml(r) {
    if (!r.meter_count) return "";
    var html = '<div class="kpis section-gap">' +
      kpi("電號數", r.meter_count + "<small>個</small>", esc(r.company_name), "hl") +
      kpi("客戶總用電", nfmt(r.total_consumption_mwh, 0) + "<small>MWh</small>", "期間 " + esc(r.period)) +
      kpi("客戶總 RE 達成", pct(r.customer_re_percent) + "<small>%</small>", "綠電 " + nfmt(r.total_green_mwh, 0) + " MWh") +
      kpi("達標電號", r.meters_meeting_target + " / " + r.meter_count, "達成各自 RE 目標") +
      "</div>";
    html += '<section class="card"><div class="hd"><h3>各電號/廠區 RE 達成</h3><span class="aside">依 RE 目標排序</span></div><div class="tablewrap"><table>' +
      "<thead><tr><th>電號</th><th>廠區</th><th>用電 (MWh)</th><th>時段用電 尖/半/離 (MWh)</th><th>分配綠電 (MWh)</th><th>RE 達成</th><th>目標</th><th>達標</th></tr></thead><tbody>";
    r.meters.forEach(function (m) {
      html += "<tr><td><span class=\"code\">" + esc(m.code) + "</span></td>" +
        "<td style=\"text-align:left\">" + esc(m.name) + (m.location ? " · " + esc(m.location) : "") + "</td>" +
        "<td class=\"num\">" + nfmt(m.consumption_mwh, 0) + "</td>" +
        "<td class=\"num\">" + touCell(m) + "</td>" +
        "<td class=\"num\">" + nfmt(m.allocated_green_mwh, 0) + "</td>" +
        "<td class=\"num\">" + reCell(m.re_percent) + "</td>" +
        "<td class=\"num\">" + pct(m.re_target_percent, 0) + "%</td>" +
        "<td>" + metPill(m.target_met) + "</td></tr>";
    });
    html += "</tbody></table></div></section>";
    html += '<div class="foot-note">' + iconInfo() + "綠電依各電號 RE 目標優先分配(目標較高者優先填至目標,餘量再補),Σ各電號綠電 = 客戶總綠電。用電佔比依各電號總量;時段結構(尖/半/離)取自各電號負載欄位,周六半尖峰併入半尖峰。示範資料。</div>";
    return html;
  }

  // ---------- 綠電合約 ----------
  // 合約深化條款的徽章：月別配比／take-or-pay 保證量／CPI 年漲幅。
  // 這些欄位引擎真的在用（月上限、結算的保證量差額、逐年價格），
  // 但過去只在編輯表單裡看得到，清單上完全不露臉。
  function contractTerms(c) {
    var t = [];
    if (c.monthly_shares && c.monthly_shares.length === 12) {
      t.push('<span class="term" title="年電量依 12 個月權重分攤，而非平均 1/12">月別配比</span>');
    }
    if (c.min_offtake_percent != null) {
      t.push('<span class="term top" title="take-or-pay：未達月上限的這個比例仍須付費">保證量 ' + pct(c.min_offtake_percent, 0) + "%</span>");
    }
    if (c.price_escalation_percent != null) {
      t.push('<span class="term cpi" title="價格逐年複利調漲' + (c.price_base_year ? "，基準年 " + c.price_base_year : "") + '">CPI ' + pct(c.price_escalation_percent, 1) + "%/年</span>");
    }
    // 掛在合約編號底下（不另闢一欄——表格已經 10 欄,再加就會把優先序/狀態擠出畫面）
    return t.length ? '<div class="terms">' + t.join("") + "</div>" : "";
  }
  // 合約還剩多久（已到期/未生效就不顯示，狀態徽章已經講了）。
  // 不足一年用天數講——「剩 0.0 年」等於沒講,而快到期正是最該看見的時候。
  function contractRemaining(c) {
    if (c.status !== "active" || !c.end_date) return "";
    var days = Math.floor((new Date(c.end_date) - new Date()) / 86400000);
    if (!isFinite(days) || days <= 0) return "";
    var txt = days < 365 ? "剩 " + days + " 天" : "剩 " + (days / 365.25).toFixed(1) + " 年";
    return '<small class="remain' + (days <= 90 ? " soon" : "") + '">' + txt + "</small>";
  }
  // 合約上限：年電量與佔發電比例二擇一(或並用,引擎取較緊的那個)。
  // 過去拆成兩欄,於是每列必有一欄是「–」,看起來像資料沒填完;合併後每列都有值。
  function contractCap(c) {
    var out = [];
    if (c.contracted_energy_mwh != null) {
      out.push(nfmt(c.contracted_energy_mwh, 0) + '<small class="capu">MWh/年</small>');
    }
    if (c.contracted_percentage != null) {
      out.push(pct(c.contracted_percentage, 0) + '%<small class="capu">發電量</small>');
    }
    return out.length ? out.join('<span class="capsep">·</span>') : '<span class="u">未設上限</span>';
  }

  // ---------- 合約詳情（商務視角） ----------
  // 綁定約束 → 顏色與說法。① 分佈條與 ② 月別圖共用同一套,免得兩處各講一套。
  var BIND_META = {
    contract_cap: { cls: "b-cap", name: "合約上限" },
    farm_supply: { cls: "b-sup", name: "案場供給" },
    customer_demand: { cls: "b-dem", name: "客戶用電" },
    none: { cls: "b-non", name: "無分配" },
    not_in_force: { cls: "b-nif", name: "未生效" },
  };
  function bindMeta(k) { return BIND_META[k] || BIND_META.none; }

  // contractRemaining() 只對生效中的合約給得出天數。給不出來時說明為什麼——
  // 「–」在到期倒數這一格會被讀成資料缺漏,而狀態本身就是答案。
  var CONTRACT_END_STATE = {
    expired: "已到期", pending: "未生效", terminated: "已終止",
    active: "已過期(狀態未更新)",
  };

  // 12 格分佈條 + 圖例。一格一個月,顏色就是那個月的主綁定約束。
  // 各類別的月數一律讀 API 的 totals.binding_counts——同一張卡片裡結論句也讀它,
  // 前端不該為同一個統計量再算一套。顯示順序仍照 12 個月裡首次出現的先後。
  function bindStrip(d) {
    var months = d.months, counts = d.totals.binding_counts || {};
    var cells = months.map(function (m) {
      var meta = bindMeta(m.binding_primary);
      return '<span class="bcell ' + meta.cls + '" title="' +
        esc(m.period + " · " + meta.name) + '">' + m.month + "</span>";
    }).join("");
    var order = [];
    months.forEach(function (m) {
      if (order.indexOf(m.binding_primary) < 0) order.push(m.binding_primary);
    });
    var lg = order.map(function (k) {
      return '<span><i class="sw ' + bindMeta(k).cls + '"></i>' + esc(bindMeta(k).name) +
        " " + (counts[k] || 0) + " 個月</span>";
    }).join("");
    return '<div class="bstrip">' + cells + "</div>" + '<div class="blg">' + lg + "</div>";
  }

  // 全年結論句。每個子句都有成立條件——條件不成立就不寫,不靠形容詞硬補。
  function bindVerdict(d) {
    var t = d.totals, counts = t.binding_counts || {};
    var nif = counts.not_in_force || 0;
    // 「未生效」只有在整年一個月都沒生效時才是這一年的結論。過去這裡取的是
    // 全 12 個月的眾數,而 not_in_force 也在裡面數——年中才起始的合約（生效
    // 月數不到 6）於是被判成未生效,印在一個寫著實際分配量的 KPI 旁邊。
    // 眾數只在生效月份裡取,未生效的月數改成句尾的附註。
    if (!t.months_in_force) {
      return "本合約於 " + d.year + " 年度未生效或已到期,無實際分配。";
    }
    var top = null, n = -1;
    Object.keys(counts).forEach(function (k) {
      if (k !== "not_in_force" && counts[k] > n) { n = counts[k]; top = k; }
    });
    var s;
    if (top === "contract_cap") {
      s = n + " 個月被合約上限卡住";
      if (t.headroom_months > 0) {
        s += "——客戶的需求高於合約允許量,其中 " + t.headroom_months +
          " 個月案場仍有餘電,有加購空間";
      }
    } else if (top === "farm_supply") {
      s = n + " 個月被案場供給卡住——此案場已無餘電可分配";
      if (t.utilization_percent != null) {
        s += ",全年只拿到上限的 " + pct(t.utilization_percent, 0) + "%";
      }
      if (d.higher_priority_sibling_count > 0) {
        s += ";同案場另有 " + d.higher_priority_sibling_count + " 紙優先序更高的合約先分";
      }
    } else if (top === "customer_demand") {
      s = n + " 個月被客戶用電卡住——合約允許量高於客戶實際用得掉的量";
    } else {
      s = "生效月份未取得任何分配,引擎未指出單一約束";
    }
    return s + (nif ? ";另 " + nif + " 個月未生效" : "") + "。";
  }

  // 月別配比小條圖。條款本身就是資料——未生效的年度也照畫。
  // 沒設月別配比時要講清楚「那月上限怎麼來的」,而這取決於合約設的是哪一種上限:
  // 只有設了年電量的合約才會走 1/12 平均分攤。比例型合約根本沒有年電量可攤,
  // 上限是「當月發電量 × 比例」,逐月跟著風況跳（004 一到三月 104,741 → 81,466 MWh）。
  function sharesBar(d) {
    var fr = d.monthly_share_fractions;
    if (!fr) {
      if (d.contracted_energy_mwh == null) {
        return d.contracted_percentage == null
          ? '<span class="u">未設;本合約未設上限,無年電量可分攤</span>'
          : '<span class="u">未設;本合約上限依當月發電量的 ' +
            pct(d.contracted_percentage, 0) + "% 計算,不走年電量分攤</span>";
      }
      return '<span class="u">未設,年電量平均 1/12 分攤</span>';
    }
    var mx = Math.max.apply(null, fr) || 1;
    return '<div class="shbar">' + fr.map(function (v, i) {
      return '<span class="shcell" title="' + (i + 1) + " 月 " + (v * 100).toFixed(1) +
        '%"><i style="height:' + (v / mx * 100).toFixed(1) + '%"></i><b>' + (i + 1) + "</b></span>";
    }).join("") + "</div>";
  }

  // CPI 逐年單價。沒設漲幅就不畫——空表格比沒有更糟。
  function priceLadder(d) {
    if (d.price_escalation_percent == null || d.price_base_year == null ||
        d.base_price_per_kwh == null) return "";
    var y0 = parseInt(String(d.start_date).slice(0, 4), 10);
    var y1 = parseInt(String(d.end_date).slice(0, 4), 10);
    var out = [];
    for (var y = y0; y <= y1 && out.length < 12; y++) {
      var n = Math.max(0, y - d.price_base_year);
      out.push('<span class="pl"><b>' + y + "</b>" +
        price(d.base_price_per_kwh * Math.pow(1 + d.price_escalation_percent / 100, n)) + "</span>");
    }
    // 15 年的 PPA 只列 12 年就停,尾巴不能無聲消失——補一格「…」把截斷說出來。
    if (y1 > y0 + 11) {
      out.push('<span class="pl more" title="' + esc("另有 " + (y1 - y0 - 11) + " 年未列出") +
        '">…</span>');
    }
    return '<div class="subhd"><span>逐年單價</span><small>基準年 ' + d.price_base_year +
      " · 每年 +" + pct(d.price_escalation_percent, 1) + "%</small></div>" +
      '<div class="pladder">' + out.join("") + "</div>";
  }

  // 月別履約圖：柱 = 實際分配（依綁定約束上色）,短橫 = 月上限,虛線短橫 = 保證量門檻。
  // 上限用「每月一段短橫」而不是一條連續折線——未設上限的月份沒有值,連起來會憑空
  // 補出一段不存在的線。
  function monthChart(months) {
    var W = 760, Ht = 210, L = 46, R = 12, T = 14, B = 26;
    var pw = W - L - R, ph = Ht - T - B;
    var vals = [];
    months.forEach(function (m) {
      vals.push(m.allocated_mwh);
      if (m.cap_mwh != null) vals.push(m.cap_mwh);
      if (m.min_offtake_mwh) vals.push(m.min_offtake_mwh);
    });
    // 整年沒有分配、沒有上限也沒有門檻時,以前用一個 [1] 的種子撐起座標軸,
    // 於是刻度印出「0 / 1 / 1」——兩個一樣的標籤,配一條沒有意義的軸。
    // 這種情況不畫刻度,改在圖面正中寫明本年度無分配。
    var dataMax = vals.length ? Math.max.apply(null, vals) : 0;
    var blank = !(dataMax > 0);
    var ymax = (blank ? 1 : dataMax) * 1.12;
    var bw = pw / 12 * 0.6;
    var X = function (i) { return L + pw * (i + 0.5) / 12; };
    var Y = function (v) { return T + ph - v / ymax * ph; };
    var grid = "", g;
    for (g = 0; g <= 2; g++) {
      var gy = T + ph - ph * g / 2;
      grid += '<line class="cfe-axis" x1="' + L + '" y1="' + gy.toFixed(1) +
        '" x2="' + (W - R) + '" y2="' + gy.toFixed(1) + '"/>' +
        (blank ? "" : '<text class="mtick" x="' + (L - 6) + '" y="' + (gy + 3.5).toFixed(1) +
          '" text-anchor="end">' + abbr(ymax * g / 2) + "</text>");
    }
    var body = months.map(function (m, i) {
      var meta = bindMeta(m.binding_primary);
      var x0 = X(i) - bw / 2;
      var y = Y(m.allocated_mwh);
      var h = Math.max(0, T + ph - y);
      // 每個月先鋪一塊整欄高的透明命中區,再畫看得見的柱子。
      // 這一塊同時解掉三件事:(1) 0 MWh 的月份不必再靠 2px 的最小高度墊出一個
      // 「點得到的柱子」——那個墊高在 1,400 MWh 的尺度下,把所有低於約 16 MWh 的
      // 月份畫成跟真正的 0 一模一樣的記號;(2) binding_primary 為 none 的柱子是
      // fill:none,預設的 visiblePainted 讓它的內部完全接不到點擊;(3) 順便把每個
      // 月的點擊目標從一根細柱放大成 bw 寬（欄寬的 60%）的命中區。tooltip 也掛在
      // 命中區上,同樣只在這塊寬度內查得到——兩側各 20% 的間距仍是點不到的。
      var s = '<g class="mcol" data-m="' + m.month + '">' +
        '<rect class="mchit" x="' + x0.toFixed(1) + '" y="' + T + '" width="' +
        bw.toFixed(1) + '" height="' + ph + '" fill="transparent"><title>' +
        esc(m.period + " · " + meta.name + " · " +
          (m.in_force ? nfmt(m.allocated_mwh, 0) + " MWh" : "–")) +
        "</title></rect>";
      // 高度 0 就不畫——「沒有分配」與「分配是 0」畫成同一個記號,正是這一頁要避免的事。
      if (h > 0) {
        s += '<rect class="mchbar ' + meta.cls + '" x="' + x0.toFixed(1) + '" y="' +
          y.toFixed(1) + '" width="' + bw.toFixed(1) + '" height="' + h.toFixed(1) +
          '" rx="2"/>';
      }
      if (m.cap_mwh != null) {
        s += '<line class="mcap" x1="' + (X(i) - bw / 2 - 3).toFixed(1) + '" y1="' +
          Y(m.cap_mwh).toFixed(1) + '" x2="' + (X(i) + bw / 2 + 3).toFixed(1) +
          '" y2="' + Y(m.cap_mwh).toFixed(1) + '"/>';
      }
      if (m.min_offtake_mwh) {
        s += '<line class="mfloor" x1="' + (X(i) - bw / 2 - 3).toFixed(1) + '" y1="' +
          Y(m.min_offtake_mwh).toFixed(1) + '" x2="' + (X(i) + bw / 2 + 3).toFixed(1) +
          '" y2="' + Y(m.min_offtake_mwh).toFixed(1) + '"/>';
      }
      s += '<text class="mtick" x="' + X(i).toFixed(1) + '" y="' + (T + ph + 15) +
        '" text-anchor="middle">' + m.month + "</text>";
      return s + "</g>";
    }).join("");
    if (blank) {
      body += '<text class="mchblank" x="' + (L + pw / 2).toFixed(1) + '" y="' +
        (T + ph / 2).toFixed(1) + '" text-anchor="middle">本年度無分配</text>';
    }
    return '<div class="mchart"><svg viewBox="0 0 ' + W + " " + Ht +
      '" role="img" aria-label="月別履約圖">' + grid + body + "</svg></div>" +
      '<div class="blg"><span><i class="ln mcapln"></i>月上限</span>' +
      '<span><i class="ln mfloorln"></i>保證量門檻</span>' +
      '<span class="cfe-hint">點任一月看該月明細</span></div>';
  }

  // 單月明細。金額只在合約有售電價時才出現。
  function monthDetailPanel(m, d) {
    var rows = erow("狀態", m.in_force ? "生效"
      : '<span class="u">' + esc(m.skip_reason || "未生效") + "</span>");
    // 未生效的月份沒有分配量可言,不是拿了 0——0 分配與「不該有分配」是兩件事。
    rows += m.in_force
      ? erow("分配量", nfmt(m.allocated_mwh, 1), "MWh")
      : erow("分配量", '<span class="u">–</span>');
    rows += erow("月上限", m.cap_mwh == null
      ? '<span class="u">未設上限</span>' : nfmt(m.cap_mwh, 1), m.cap_mwh == null ? "" : "MWh");
    rows += erow("使用率", m.utilization_percent == null
      ? '<span class="u">–</span>' : pct(m.utilization_percent, 1) + "%");
    rows += erow("綁定約束", esc(bindMeta(m.binding_primary).name) +
      (m.headroom ? '<span class="u">有加購空間</span>' : ""));
    if (m.min_offtake_mwh) {
      rows += erow("保證量門檻", nfmt(m.min_offtake_mwh, 1), "MWh");
      rows += erow("保證量差額", nfmt(m.shortfall_mwh, 1), "MWh",
        m.shortfall_mwh > 0 ? "neg" : "");
    }
    if (d.has_price) {
      rows += erow("綠電費", money(m.energy_cost), "NTD");
      rows += erow("輪供費", "+" + money(m.wheeling_fee), "NTD");
      if (m.take_or_pay_charge > 0) {
        rows += erow("保證量費", "+" + money(m.take_or_pay_charge), "NTD", "prem");
      }
      rows += erowTotal("買方應付", money(m.buyer_payable), "NTD", "pos");
      rows += erow("案場應收", money(m.seller_receivable), "NTD");
      rows += erow("售電業毛利", money(m.retailer_margin), "NTD",
        m.retailer_margin >= 0 ? "pos" : "neg");
    }
    return '<div class="mdetail"><div class="mdhd"><b>' + esc(m.period) + "</b>" +
      '<span class="aside">' + esc(m.reason || m.skip_reason || "") + "</span></div>" +
      '<div class="rows">' + rows + "</div></div>";
  }

  function wireContractChart(root, d) {
    var panel = root.querySelector("#cd-mdetail");
    if (!panel) return;
    root.addEventListener("click", function (e) {
      // 命中的是整欄的 <g data-m>,不是柱子——0 MWh 的月份根本沒有柱子。
      var col = e.target.closest ? e.target.closest(".mcol") : null;
      if (!col) return;
      var mo = parseInt(col.getAttribute("data-m"), 10);
      Array.prototype.forEach.call(root.querySelectorAll(".mcol"), function (b) {
        b.classList.toggle("on", b === col);
      });
      var m = d.months.filter(function (x) { return x.month === mo; })[0];
      if (m) panel.innerHTML = monthDetailPanel(m, d);
    });
  }

  // 年度選單：改 hash 讓路由自己重畫,不另外抓一次資料。
  function wireYearPicker(root, d) {
    var inp = root.querySelector("#cd-year");
    if (!inp) return;
    var go = function () {
      var y = parseInt(inp.value, 10);
      if (!y || y < 2000 || y > 2100) { inp.value = d.year; return; }
      if (y === d.year) return;
      location.hash = "#/contract?id=" + d.contract_id + "&year=" + y;
    };
    inp.addEventListener("change", go);
    inp.addEventListener("keydown", function (e) { if (e.key === "Enter") go(); });
  }

  function alertsBlock(alerts, year) {
    var rows = "";
    if (!alerts.length) {
      rows = '<tr><td class="empty" colspan="4">目前無風險告警 ✓</td></tr>';
    } else {
      alerts.forEach(function (a) {
        rows += "<tr><td>" + sevPill(a.severity) + "</td><td>" +
          (RISK_CAT[a.category] || esc(a.category)) +
          '</td><td style="text-align:left">' + esc(a.detail) +
          '</td><td style="text-align:left">' + esc(a.suggested_action) + "</td></tr>";
      });
    }
    return '<section class="card"><div class="hd"><h3>風險告警</h3>' +
      '<span class="aside">評估期間 ' + year + "-01 · 到期預警 12 個月</span></div>" +
      '<div class="tablewrap"><table><thead><tr><th>嚴重度</th><th>類型</th>' +
      "<th>說明</th><th>建議動作</th></tr></thead><tbody>" + rows +
      "</tbody></table></div></section>";
  }

  // 雙面帳:買方帳、賣方帳、售電業毛利同框,並標明每一欄是給誰看的。
  function billBlock(d) {
    if (!d.has_price) {
      return '<section class="card"><div class="hd"><h3>雙面帳</h3></div>' +
        '<div style="padding:16px 18px"><p class="u">本合約未設售電價,無法計算金額。' +
        "填入售電價後即可產生買方應付、案場應收與售電業毛利。</p></div></section>";
    }
    var t = d.totals;
    var rows = "";
    // 未生效的月份整列給「–」。金額欄的 0 是真的 0（可加總）,但分配量欄的 0
    // 會被讀成「這個月一度都沒拿到」,而事實是這個月根本不在合約期間內。
    var dash = "";
    for (var dc = 0; dc < 7; dc++) dash += '<td class="num"><span class="u">–</span></td>';
    d.months.forEach(function (m) {
      if (!m.in_force) {
        rows += '<tr class="dim"><td class="num">' + esc(m.period) + "</td>" + dash + "</tr>";
        return;
      }
      rows += '<tr><td class="num">' +
        esc(m.period) + '</td><td class="num">' + nfmt(m.allocated_mwh, 0) +
        '</td><td class="num">' + money(m.energy_cost) +
        '</td><td class="num">' + money(m.wheeling_fee) +
        '</td><td class="num">' + (m.take_or_pay_charge > 0
          ? '<span class="prem">' + money(m.take_or_pay_charge) + "</span>" : "0") +
        '</td><td class="num">' + money(m.buyer_payable) +
        '</td><td class="num">' + money(m.seller_receivable) +
        '</td><td class="num ' + (m.retailer_margin >= 0 ? "pos" : "neg") + '">' +
        money(m.retailer_margin) + "</td></tr>";
    });
    return '<section class="card"><div class="hd"><h3>雙面帳</h3>' +
      '<span class="aside">' + d.year + " 年度合計 · 履約基準</span></div>" +
      '<div class="billcols">' +
      '<div class="billcol"><div class="bctag buyer">買方（用電戶應付）</div><div class="rows">' +
      erow("綠電費", money(t.energy_cost), "NTD") +
      erow("輪供費", "+" + money(t.wheeling_fee), "NTD") +
      (t.take_or_pay_charge > 0
        ? erow("保證量費", "+" + money(t.take_or_pay_charge), "NTD", "prem") : "") +
      erowTotal("應付合計", money(t.buyer_payable), "NTD", "pos") +
      "</div></div>" +
      '<div class="billcol"><div class="bctag seller">賣方（案場應收）</div><div class="rows">' +
      erow("躉售單價", price(d.feed_in_price_per_kwh), "NTD/kWh") +
      erow("綠電量", nfmt(t.allocated_mwh, 0), "MWh") +
      erowTotal("應收合計", money(t.seller_receivable), "NTD") +
      "</div></div>" +
      '<div class="billcol"><div class="bctag">售電業毛利</div><div class="rows">' +
      erow("轉供單價", price(d.months[0].price_per_kwh), "NTD/kWh") +
      erow("毛利率", t.margin_percent == null
        ? '<span class="u">–</span>' : pct(t.margin_percent, 1) + "%") +
      erowTotal("毛利", money(t.retailer_margin), "NTD",
        t.retailer_margin >= 0 ? "pos" : "neg") +
      "</div></div></div>" +
      '<div class="subhd"><span>月別明細</span><small>灰列為未生效月份</small></div>' +
      '<div class="tablewrap"><table><thead><tr><th>期間</th><th>分配 (MWh)</th>' +
      "<th>綠電費</th><th>輪供費</th><th>保證量費</th><th>買方應付</th>" +
      "<th>案場應收</th><th>毛利</th></tr></thead><tbody>" + rows +
      "</tbody></table></div>" +
      '<div class="foot-note">' + iconInfo() +
      "本頁金額以<b>合約優先序引擎</b>的分配為基準(履約基準);轉供結算單頁採 MILP 最佳化配置," +
      "兩者數字會有落差。" +
      (d.used_default_feed_in
        ? "此案場未設躉售價,採預設 " + price(d.feed_in_price_per_kwh) + " 元/度 試算。" : "") +
      "輪供費 " + price(d.wheeling_fee_per_kwh) + " 元/度。減碳量 " +
      nfmt(t.carbon_avoided_tco2e, 0) + " tCO₂e。</div>" +
      "</section>";
  }

  function contractTermsCard(d) {
    var top = d.min_offtake_percent == null
      ? '<span class="u">無此條款</span>'
      : pct(d.min_offtake_percent, 0) + "%" +
        (d.totals.min_offtake_mwh > 0 && d.totals.shortfall_mwh === 0
          ? '<span class="u">全年皆達標,未觸發差額</span>' : "");
    return '<section class="card"><div class="hd"><h3>合約條款</h3>' +
      '<span class="aside">紙上寫的規則</span></div>' +
      '<div class="rows" style="padding:4px 18px 14px">' +
      erow("合約期間", esc(d.start_date) + " ～ " + esc(d.end_date)) +
      erow("優先序", String(d.priority)) +
      erow("合約上限", contractCap(d), "", "", null, "contractCap") +
      erow("售電價", d.base_price_per_kwh == null
        ? '<span class="u">未設</span>' : price(d.base_price_per_kwh), "NTD/kWh") +
      erow("保證量 (take-or-pay)", top) +
      "</div>" +
      '<div class="subhd"><span>月別配比</span><small>年電量如何攤到各月</small></div>' +
      '<div style="padding:0 18px 16px">' + sharesBar(d) + "</div>" +
      priceLadder(d) +
      "</section>";
  }

  function renderContractDetail() {
    var p = parseHash().params;
    var id = parseInt(p.id, 10);
    var year = parseInt(p.year, 10) || parseInt(getPeriod().slice(0, 4), 10);
    crumb.textContent = "合約詳情";
    if (!id) {
      view.innerHTML = errbox("合約詳情", new Error("網址缺少合約 id"));
      return;
    }
    view.innerHTML = '<div id="cd-body"><div class="placeholder">載入中…</div></div>';
    var body = document.getElementById("cd-body");
    Promise.all([
      api.contractDetail(id, year),
      // 告警是既有端點,單獨失敗不該讓整頁掛掉
      api.contractRisks(year + "-01", 12).catch(function () { return null; }),
    ]).then(function (r) {
      renderContractDetailBody(body, r[0], r[1]);
    }).catch(function (err) { body.innerHTML = errbox("合約詳情", err); });
  }

  function renderContractDetailBody(body, d, risks) {
    crumb.textContent = "綠電合約 › " + d.contract_number;
    var t = d.totals;
    // 「有沒有上限」是條款問題:年電量與佔發電比例二擇一或並用,兩個都沒有才是真的沒設。
    var noCap = d.contracted_energy_mwh == null && d.contracted_percentage == null;
    var alerts = risks && risks.alerts
      ? risks.alerts.filter(function (a) { return a.contract_number === d.contract_number; })
      : [];
    var html = '<div class="pagehead"><div><div class="title"><span class="bar"></span>' +
      "<h1>" + esc(d.contract_number) + "</h1>" + contractStatusPill(d.status) + "</div>" +
      '<div class="meta"><span>' + esc(d.wind_farm_name || d.wind_farm_code) + " → " +
      esc(d.company_name) + "</span><span>" + esc(d.start_date) + " ～ " + esc(d.end_date) +
      "</span><span>優先序 " + d.priority + "</span></div>" +
      (contractTerms(d) || "") + "</div>" +
      // 年度選單。?year= 一直都能用,只是沒有 UI 可改;沿用其他頁的 period-input
      // 樣式,但這裡只收年份（合約詳情一次就是整年,YYYY-MM 沒有意義）。
      '<div class="headactions">' +
      '<input id="cd-year" class="period-input num yr-input" value="' + esc(String(d.year)) +
      '" placeholder="2024" inputmode="numeric" maxlength="4" aria-label="年度" title="切換年度">' +
      '<a class="btn" href="#/contracts">← 回合約清單</a></div></div>';

    if (!d.has_period_data) {
      html += '<div class="placeholder"><div class="big">📄</div>' +
        "<h2>" + d.year + " 年度尚無發電與用電資料</h2>" +
        "<p>此年度沒有任何量測資料,無法計算履約與金額。以下僅顯示合約條款。</p></div>" +
        contractTermsCard(d);
      body.innerHTML = html;
      // 「這一年沒資料」正是最需要換一年看的時候,選單在這條路徑上也要接起來
      wireYearPicker(body, d);
      return;
    }

    html += '<section class="card"><div class="hd"><h3>全年被什麼卡住' +
      infoTip("bindingConstraint") + "</h3>" +
      '<span class="aside">' + d.year + " 年 · 依合約優先序引擎</span></div>" +
      '<div style="padding:14px 18px 4px">' + bindStrip(d) +
      '<p class="verdict">' + esc(bindVerdict(d)) + "</p></div>" +
      '<div class="kpis">' +
      kpi("年度分配量", nfmt(t.allocated_mwh, 0) + "<small>MWh</small>",
        "生效 " + t.months_in_force + " 個月", "hl") +
      // 同一個毛病的第四處(清單沒點名,瀏覽器實測時撞見):「這紙合約有沒有設
      // 上限」問的還是條款,而 totals.cap_mwh 只加總生效月份的上限。PPA-2025-008
      // 於是在這裡寫「此合約未設上限」,同一頁的條款卡卻寫「合約上限 20,000
      // MWh/年」——跟保證量差額那格是一模一樣的矛盾。有沒有上限改看條款欄位
      // (與清單頁的 contractCap() 同源),年度上限算不出來的情形另給說明。
      kpi("上限使用率", t.utilization_percent == null
        ? '<span class="u">' + (noCap ? "未設上限" : "–") + "</span>"
        : pct(t.utilization_percent, 1) + "%",
        noCap ? "此合約未設上限"
          : t.cap_mwh == null ? "該年度無生效月份,無年度上限可比"
            : "年度上限 " + nfmt(t.cap_mwh, 0) + " MWh") +
      // 「有沒有這個條款」問的是條款,不是履約數量。以前這裡看 totals.min_offtake_mwh,
      // 而那個量在未生效的月份是 0——於是 PPA-2025-008 一邊寫「未約定 take-or-pay」,
      // 同一頁的合約條款卡一邊寫「保證量 90%」。比例型合約也一樣中招（沒有年電量,
      // 月門檻算不出來）。改看 min_offtake_percent,就是條款卡自己用的那個欄位。
      kpi("保證量差額",
        d.min_offtake_percent == null ? '<span class="u">無此條款</span>'
          : t.months_in_force === 0 ? '<span class="u">–</span>'
            : nfmt(t.shortfall_mwh, 0) + "<small>MWh</small>",
        d.min_offtake_percent == null ? "未約定 take-or-pay"
          : t.months_in_force === 0 ? "該年度無生效月份,無從評估"
            : (t.shortfall_months ? t.shortfall_months + " 個月未達標" : "全年皆達標,未觸發"),
        t.shortfall_mwh > 0 ? "neg" : "") +
      // 到期倒數。清單頁的 contractRemaining() 就是這個數字,兩頁講同一句話。
      kpi("到期倒數", contractRemaining(d) ||
        '<span class="u">' + esc(CONTRACT_END_STATE[d.status] || "–") + "</span>",
        "至 " + d.end_date) +
      // 到期告警是對「今天」算的,供電不足／保證量差額只算一月——KPI 掛在一張
      // 整年的頁面上,不講評估基準就會被讀成「這一年共 N 則」。
      kpi("風險告警", alerts.length + "<small>則</small>",
        "以 " + d.year + "-01 為評估期間", alerts.length ? "prem" : "") +
      "</div></section>";

    html += '<section class="card"><div class="hd"><h3>月別履約</h3>' +
      '<span class="aside">柱＝實際分配 · 短橫＝月上限</span></div>' +
      '<div style="padding:12px 18px 14px">' + monthChart(d.months) + "</div>" +
      '<div id="cd-mdetail"></div></section>';

    html += alertsBlock(alerts, d.year);
    html += billBlock(d);
    html += contractTermsCard(d);
    body.innerHTML = html;
    wireContractChart(body, d);
    wireYearPicker(body, d);
  }

  function renderContracts() {
    crumb.textContent = "綠電合約";
    view.innerHTML = '<div class="pagehead"><div class="title"><span class="bar"></span><h1>綠電合約</h1></div>' +
      '<div class="meta"><span>PPA 合約清單:案場、客戶、費率、比例、優先序、狀態,以及月別配比／保證量／CPI 等合約條款。</span></div></div>' +
      '<div id="ct-body"><div class="placeholder">載入中…</div></div>';
    var body = document.getElementById("ct-body");
    Promise.all([api.contracts(), api.windFarms(), api.customers()])
      .then(function (r) {
        var cs = r[0], fm = {}, cm = {};
        crudCache.contract = {};
        contractFarmOpts.length = 0;
        contractCustOpts.length = 0;
        r[1].forEach(function (f) { fm[f.id] = f.name || f.code; contractFarmOpts.push([f.id, (f.name || f.code)]); });
        r[2].forEach(function (c) { cm[c.id] = c.company_name || c.code; contractCustOpts.push([c.id, (c.company_name || c.code)]); });
        cs.forEach(function (c) { crudCache.contract[c.id] = c; });
        var html = '<section class="card"><div class="hd"><h3>合約清單</h3><span class="aside">' + cs.length + " 筆</span>" + entityAddBtn("contract", "新增合約") + importBtn("contract") + "</div><div class=\"tablewrap\"><table>" +
          "<thead><tr><th>合約編號</th><th>案場</th><th>客戶</th><th>起始</th><th>結束</th><th>合約上限" + infoTip("contractCap") + "</th><th>售電價</th><th>優先序</th><th>狀態</th>" + (editMode ? '<th class="actcol">操作</th>' : "") + "</tr></thead><tbody>";
        if (!cs.length) {
          html += '<tr><td class="empty" colspan="' + (editMode ? 10 : 9) + '">尚無合約' + (editMode ? ",可按「新增合約」建立。" : "。") + "</td></tr>";
        }
        cs.forEach(function (c) {
          var fname = String(fm[c.wind_farm_id] || c.wind_farm_id);
          html += '<tr class="clickrow" data-cid="' + c.id + '"><td class="code">' + esc(c.contract_number) + contractTerms(c) +
            "</td><td class=\"wrapname\">" + esc(fname) + "</td><td style=\"text-align:left\">" + esc(cm[c.customer_id] || c.customer_id) +
            "</td><td class=\"num\">" + esc(c.start_date) + "</td><td class=\"num\">" + esc(c.end_date) + contractRemaining(c) +
            "</td><td class=\"num cap\">" + contractCap(c) +
            "</td><td class=\"num\">" + (c.price_per_kwh != null ? price(c.price_per_kwh) : "–") +
            "</td><td class=\"num\">" + c.priority + "</td><td>" + contractStatusPill(c.status) + "</td>" + rowActions("contract", c.id) + "</tr>";
        });
        html += "</tbody></table></div></section>";
        body.innerHTML = html;
        // 整列可點進詳情頁；編輯模式的操作鈕不算（點刪除不該跳頁）
        body.addEventListener("click", function (e) {
          if (e.target.closest("button") || e.target.closest("a")) return;
          var tr = e.target.closest(".clickrow");
          if (!tr) return;
          location.hash = "#/contract?id=" + tr.getAttribute("data-cid") +
            "&year=" + getPeriod().slice(0, 4);
        });
      })
      .catch(function (err) { body.innerHTML = errbox("載入合約", err); });
  }

  // ---------- 即時再生能源 ----------
  // 台電「各機組發電量即時資訊(含外購電力)」— data.gov.tw dataset 8931,約 10 分更新。
  var LIVE_DATASET_URL = "https://data.gov.tw/dataset/8931";
  var LIVE_TAIPOWER_PAGE_URL = "https://www.taipower.com.tw/d006/loadGraph/loadGraph/genshx_.html";
  var LIVE_JSON_URL = "https://service.taipower.com.tw/data/opendata/apply/file/d006001/001.json";
  function extlink(href, text) {
    return '<a href="' + esc(href) + '" target="_blank" rel="noopener">' + esc(text) + " ↗</a>";
  }
  function renderLive() {
    crumb.textContent = "即時再生能源";
    view.innerHTML = '<div class="pagehead"><div><div class="title"><span class="bar"></span><h1>即時再生能源</h1></div>' +
      '<div class="meta"><span>台電各機組即時發電(約 10 分更新);瞬時 MW,不進媒合。</span>' +
      "<span>資料來源:" + extlink(LIVE_DATASET_URL, "台電各機組發電量即時資訊(dataset 8931)") + "</span></div></div>" +
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
        var html = '<div class="kpis">' +
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
          "<thead><tr><th>機組</th><th>裝置容量 (MW)</th><th>淨發電 (MW)</th><th>即時出力率 (%)</th><th>台電備註</th></tr></thead><tbody>";
        if (!(d.wind || []).length) {
          html += '<tr><td class="empty" colspan="5">目前無風力機組資料</td></tr>';
        } else {
          d.wind.forEach(function (w) {
            html += "<tr><td>" + esc(w.name) + "</td><td class=\"num\">" + (w.capacity_mw != null ? nfmt(w.capacity_mw, 1) : "–") +
              "</td><td class=\"num\">" + (w.net_mw != null ? nfmt(w.net_mw, 1) : "–") +
              "</td><td class=\"num\">" + (w.output_ratio_pct != null ? nfmt(w.output_ratio_pct, 1) + "%" : "–") +
              "</td><td>" + (w.note ? '<span class="pill info">' + esc(w.note) + "</span>" : "–") + "</td></tr>";
          });
        }
        html += "</tbody></table></div></section></div>";
        // 單一 <span> 包住全文:.foot-note 是 flex,否則每個 <a>/<b> 都會變成獨立 flex item。
        html += '<div class="foot-note">' + iconInfo() + "<span>" +
          "資料來源:台電「各機組發電量即時資訊(含外購電力)」" + extlink(LIVE_DATASET_URL, "data.gov.tw dataset 8931") +
          " · " + extlink(d.source_url || LIVE_JSON_URL, "原始 JSON") +
          " · " + extlink(LIVE_TAIPOWER_PAGE_URL, "台電各機組發電量頁面") +
          ",約 10 分更新。表中各欄(裝置容量、淨發電、出力率、備註)皆為台電原始欄位,未加工。" +
          "<b>即時出力率 = 淨發電量 ÷ 裝置容量</b>,是這一刻的瞬時比值,<b>非</b>本站其他頁面的年度容量因數 P50/P90。" +
          "裝置容量顯示「–」代表台電該案場未揭露(多為新增/測試中機組),出力率因此無法計算。" +
          "此為<b>瞬時出力(MW)</b>,非月度累積發電量(kWh,dataset 29961)。read-through 呈現、不儲存、不進媒合引擎。</span></div>";
        body.innerHTML = html;
      })
      .catch(function (err) { body.innerHTML = errbox("載入即時再生能源", err); });
  }

  // ---------- 發電案場管理 ----------
  function statusPill(s) {
    var m = {
      operational: ["運轉中", "ok"], under_construction: ["建置中", "warnp"],
      planning: ["規劃中", "neut"], decommissioned: ["除役", "neut"],
    };
    var x = m[s] || [s || "–", "neut"];
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
      var cfs = farms.map(function (f) { return f.capacity_factor_percent; }).filter(function (v) { return v != null; });
      var avgCf = cfs.length ? cfs.reduce(function (s, v) { return s + v; }, 0) / cfs.length : null;
      var expOf = function (f) { return f.capacity_factor_percent != null ? f.installed_capacity_mw * 8760 * f.capacity_factor_percent / 100 : null; };

      var html = '<div class="kpis">' +
        kpi("案場數", farms.length + "<small>場</small>", "已納入媒合", "hl") +
        kpi("總裝置容量", nfmt(totCap, 1) + "<small>MW</small>", "跨全部案場") +
        kpi("總發電量", nfmt(totGen, 0) + "<small>MWh</small>", "資料區間累積") +
        kpi("平均容量因數", avgCf != null ? pct(avgCf, 1) + "<small>%</small>" : "–", "P50 預期") +
        kpi("平均躉售價", avgPrice != null ? price(avgPrice) : "–", "NTD / kWh") +
        "</div>";
      html += '<section class="card"><div class="hd"><h3>發電數據</h3><span class="aside">' + farms.length + " 場 · 含時段別發電與容量因數" + "</span>" + entityAddBtn("farm", "新增案場") + importBtn("farm") + "</div><div class=\"tablewrap\"><table>" +
        "<thead><tr><th>案場</th><th>場址</th><th>裝置容量 (MW)</th><th>容量因數 P50/P90" + infoTip("cf") + "</th><th>躉售價" + infoTip("feedIn") + "</th><th>狀態</th><th>總發電 (MWh)</th><th>預期 P50 (MWh)" + infoTip("expP50") + "</th><th>達成</th>" + (editMode ? '<th class="actcol">操作</th>' : "") + "</tr></thead><tbody>";
      farms.slice().sort(function (a, b) { return a.code > b.code ? 1 : -1; }).forEach(function (f) {
        crudCache.farm[f.id] = f;
        var a = agg[f.id] || { total: 0, peak: 0, half_peak: 0, off_peak: 0 };
        var exp = expOf(f);
        var cfCell = f.capacity_factor_percent != null
          ? pct(f.capacity_factor_percent, 0) + "% / " + (f.p90_capacity_factor_percent != null ? pct(f.p90_capacity_factor_percent, 0) + "%" : "–")
          : "–";
        var achv = (exp && exp > 0) ? reCell(a.total / exp * 100) : '<span class="u">–</span>';
        html += "<tr><td><span class=\"code\">" + esc(f.code) + "</span> " + esc(f.name) + farmTypeBadge(f.farm_type) + "</td>" +
          "<td style=\"text-align:left\">" + esc(f.location || "–") + "</td>" +
          "<td class=\"num\">" + nfmt(f.installed_capacity_mw, 1) + "</td>" +
          "<td class=\"num\">" + cfCell + "</td>" +
          "<td class=\"num\">" + (f.feed_in_price_per_kwh != null ? price(f.feed_in_price_per_kwh) : "–") + "</td>" +
          "<td>" + statusPill(f.status) + "</td>" +
          "<td class=\"num\" style=\"font-weight:700\">" + nfmt(a.total, 0) + "</td>" +
          "<td class=\"num\">" + (exp != null ? nfmt(exp, 0) : "–") + "</td>" +
          "<td class=\"num\">" + achv + "</td>" + rowActions("farm", f.id) + "</tr>";
      });
      html += "</tbody></table></div></section>";
      html += '<div class="foot-note">' + iconInfo() + "預期年發電 P50 = 裝置容量 × 8760h × 容量因數;達成 = 實際/預期。示範資料為模擬,各時段發電依風電典型占比拆分。</div>";
      body.innerHTML = html;
    }).catch(function (err) { body.innerHTML = errbox("載入發電案場", err); });
  }

  // ---------- 投資效益 (ROI / 回收期) ----------
  function yi(n) {
    if (n == null || isNaN(n)) return "–";
    return (Number(n) / 1e8).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  function paybackCell(y) {
    if (y == null) return '<span class="neg">無法回收</span>';
    return nfmt(y, 1) + " 年";
  }
  function roiCls(r) { return r == null || r < 0 ? "neg" : r >= 8 ? "pos" : "prem"; }

  function renderInvestment() {
    crumb.textContent = "投資效益";
    view.innerHTML =
      '<div class="pagehead"><div class="title"><span class="bar"></span><h1>投資效益</h1></div>' +
      '<div class="meta"><span>逐案場與組合的 CAPEX、年淨利、投報率(ROI)與回收期;每 MW 建置成本與 O&amp;M 費率可覆寫。</span></div></div>' +
      '<form class="formcard" id="invForm"><div class="formgrid">' +
      '<div class="field"><label>每 MW 建置成本</label><input id="i-capex" class="num" type="number" min="1" step="any" placeholder="載入中…"><span class="hint">NTD / MW · 可覆寫</span></div>' +
      '<div class="field"><label>年 O&amp;M 費率</label><input id="i-om" class="num" type="number" min="0" max="100" step="any" placeholder="載入中…"><span class="hint">% of CAPEX · 可覆寫</span></div>' +
      '<div class="field"><label>發電情境</label><select id="i-scenario"><option value="actual">實際 (量測發電)</option><option value="p50">P50 預期 (容量因數)</option><option value="p90">P90 保守 (下行風險)</option></select><span class="hint">P50/P90 以容量因數推估年發電</span></div>' +
      '</div><div class="formactions"><button class="btn primary" type="submit">' +
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 19V5M4 19h16M8 15l3-4 3 3 4-6"/></svg>計算投資效益</button></div></form>' +
      '<div id="inv-body"><div class="placeholder">載入中…</div></div>';

    var capexEl = document.getElementById("i-capex");
    var omEl = document.getElementById("i-om");
    var scenEl = document.getElementById("i-scenario");
    var body = document.getElementById("inv-body");
    var loaded = false;

    function load(capex, om) {
      showModal("正在計算投資效益…");
      api.investment(capex, om, scenEl.value)
        .then(function (r) {
          if (!loaded) { capexEl.value = r.capex_per_mw; omEl.value = r.om_rate_percent; loaded = true; }
          renderInvestmentResult(body, r);
        })
        .catch(function (err) { body.innerHTML = errbox("計算投資效益", err); })
        .then(function () { setTimeout(hideModal, reduce ? 0 : 300); });
    }
    function submit() {
      var cv = capexEl.value.trim(), ov = omEl.value.trim();
      load(cv === "" ? null : parseFloat(cv), ov === "" ? null : parseFloat(ov));
    }
    document.getElementById("invForm").addEventListener("submit", function (e) {
      e.preventDefault(); submit();
    });
    scenEl.addEventListener("change", submit);  // switching scenario re-runs
    load(null, null);
  }

  function renderInvestmentResult(body, r) {
    var farms = (r.farms || []).slice().sort(function (a, b) { return b.roi_percent - a.roi_percent; });
    var t = r.total;
    var netCls = t.annual_net >= 0 ? "pos" : "neg";
    var rCls = roiCls(t.roi_percent);
    var html = '<div class="kpis">' +
      kpi("總 CAPEX", yi(t.capex) + "<small>億</small>", nfmt(t.capacity_mw, 0) + " MW 裝置容量", "hl") +
      kpi("年淨利", '<span class="' + netCls + '">' + yi(t.annual_net) + "</span><small>億</small>", "年收入 − O&M") +
      kpi("組合 ROI", '<span class="' + rCls + '">' + pct(t.roi_percent, 1) + "</span><small>%/年</small>", "年淨利 / CAPEX") +
      kpi("組合回收期", t.payback_years == null ? '<span class="neg">–</span>' : nfmt(t.payback_years, 1) + "<small>年</small>", t.payback_years == null ? "當前假設下無法回收" : "靜態回收(未折現)") +
      "</div>";

    var scenLabel = { actual: "實際 (量測發電)", p50: "P50 預期", p90: "P90 保守" }[r.scenario] || r.scenario;
    var scenCls = r.scenario === "p90" ? "warnp" : (r.scenario === "p50" ? "info" : "neut");
    html += '<section class="card"><div class="hd"><h3>逐案場投資效益</h3><span class="aside"><span class="pill ' + scenCls + '" style="height:20px;font-size:10.5px;padding:0 8px">情境 · ' + esc(scenLabel) + "</span> · " + farms.length +
      " 場 · 依 ROI 排序</span></div><div class=\"tablewrap\"><table>" +
      "<thead><tr><th>案場</th><th>裝置容量 (MW)</th><th>年發電 (MWh)</th><th>躉售價</th>" +
      "<th>年收入 (億)</th><th>CAPEX (億)</th><th>年 O&amp;M (億)</th><th>年淨利 (億)</th><th>ROI (%/年)</th><th>回收期</th></tr></thead><tbody>";
    farms.forEach(function (f) {
      html += "<tr><td><span class=\"code\">" + esc(f.code) + "</span> " + esc(f.name) + farmTypeBadge(f.farm_type) + "</td>" +
        "<td class=\"num\">" + nfmt(f.capacity_mw, 1) + "</td>" +
        "<td class=\"num\">" + nfmt(f.annual_generation_mwh, 0) + "</td>" +
        "<td class=\"num\">" + price(f.selling_price_per_kwh) + "</td>" +
        "<td class=\"num\">" + yi(f.annual_revenue) + "</td>" +
        "<td class=\"num\">" + yi(f.capex) + "</td>" +
        "<td class=\"num\">" + yi(f.annual_om) + "</td>" +
        "<td class=\"num\" style=\"font-weight:700\"><span class=\"" + (f.annual_net >= 0 ? "pos" : "neg") + "\">" + yi(f.annual_net) + "</span></td>" +
        "<td class=\"num\"><span class=\"" + roiCls(f.roi_percent) + "\">" + pct(f.roi_percent, 1) + "</span></td>" +
        "<td class=\"num\">" + paybackCell(f.payback_years) + "</td></tr>";
    });
    html += "<tr class=\"totalrow\"><td style=\"font-weight:700\">組合總計</td>" +
      "<td class=\"num\">" + nfmt(t.capacity_mw, 1) + "</td>" +
      "<td class=\"num\">" + nfmt(t.annual_generation_mwh, 0) + "</td><td class=\"num\">–</td>" +
      "<td class=\"num\">" + yi(t.annual_revenue) + "</td>" +
      "<td class=\"num\">" + yi(t.capex) + "</td>" +
      "<td class=\"num\">" + yi(t.annual_om) + "</td>" +
      "<td class=\"num\" style=\"font-weight:700\"><span class=\"" + netCls + "\">" + yi(t.annual_net) + "</span></td>" +
      "<td class=\"num\"><span class=\"" + rCls + "\">" + pct(t.roi_percent, 1) + "</span></td>" +
      "<td class=\"num\">" + paybackCell(t.payback_years) + "</td></tr>";
    html += "</tbody></table></div></section>";
    var hasSolar = farms.some(function (f) { return f.farm_type === "solar"; });
    html += '<div class="foot-note">' + iconInfo() +
      "CAPEX = 裝置容量 × 每 MW 成本;年收入 = 年發電 × 躉售價;年淨利 = 年收入 − 年 O&amp;M;" +
      "ROI = 年淨利 / CAPEX;回收期 = CAPEX / 年淨利(靜態、未折現)。示範成本參數為預設值,可於上方覆寫。" +
      (hasSolar ? "太陽能案場目前<b>沿用同一組每 MW CAPEX 假設</b>(實務上明顯低於離岸風電),此頁 solar 的 ROI 僅供結構參考。" : "") +
      "</div>";
    body.innerHTML = html;
  }

  // ---------- T-REC 憑證 ----------
  function trecStatusPill(s) {
    return s === "retired"
      ? '<span class="pill ok"><span class="dot"></span>已註銷</span>'
      : '<span class="pill info"><span class="dot"></span>已移轉</span>';
  }

  function renderTrecs() {
    crumb.textContent = "T-REC 憑證";
    view.innerHTML =
      '<div class="pagehead"><div class="title"><span class="bar"></span><h1>T-REC 憑證</h1></div>' +
      '<div class="meta"><span>再生能源憑證(1 憑證 = 1 MWh)。媒合即發行+移轉給客戶;客戶可註銷抵充 RE。</span></div></div>' +
      '<form class="formcard" id="trForm"><div class="formgrid">' +
      '<div class="field"><label>年份別 (YYYY-MM)</label><input id="t-period" class="num" value="' + getPeriod() + '"></div>' +
      '</div><div class="formactions" style="gap:9px">' +
      '<button class="btn ghost" type="submit"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M20 11a8 8 0 1 0-2.3 5.7M20 5v6h-6"/></svg>查詢</button>' +
      '<button class="btn primary" type="button" id="t-issue"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 5v14M5 12h14"/></svg>發行本期憑證</button>' +
      '</div></form><div id="tr-body"><div class="placeholder">載入中…</div></div>';
    var body = document.getElementById("tr-body");
    function period() { return document.getElementById("t-period").value.trim(); }
    function load() {
      body.innerHTML = '<div class="placeholder">載入中…</div>';
      api.trecs(period()).then(function (r) { renderTrecLedger(body, r); })
        .catch(function (err) { body.innerHTML = errbox("載入憑證帳", err); });
    }
    document.getElementById("trForm").addEventListener("submit", function (e) { e.preventDefault(); load(); });
    document.getElementById("t-issue").addEventListener("click", function () {
      showModal("正在由媒合結果發行本期憑證…");
      api.trecsIssue(period()).then(function (r) { renderTrecLedger(body, r); toast("已發行本期憑證"); })
        .catch(function (err) { body.innerHTML = errbox("發行憑證", err); })
        .then(function () { setTimeout(hideModal, reduce ? 0 : 300); });
    });
    body.addEventListener("click", function (e) {
      var btn = e.target.closest("[data-retire]"); if (!btn) return;
      var id = btn.getAttribute("data-retire");
      var row = btn.closest("tr");
      var no = row ? (row.querySelector(".code") || {}).textContent || "" : "";
      showFormModal({
        title: "註銷憑證", fields: [], danger: true, submitLabel: "確定註銷",
        note: "確定要註銷憑證「<b>" + esc(no) + "</b>」嗎?註銷後用於抵充 RE、<b>不可再交易</b>,此動作無法復原。",
        onSubmit: function (_v, done) {
          api.trecRetire(id).then(function () { done(); toast("已註銷憑證"); load(); })
            .catch(function (err) { done(writeErr(err)); });
        },
      });
    });
    load();
  }

  function renderTrecLedger(body, r) {
    var s = r.summary;
    var html = '<div class="kpis">' +
      kpi("總憑證", nfmt(s.total_quantity_mwh, 0) + "<small>MWh</small>", s.total_batches + " 批次", "hl") +
      kpi("已移轉", '<span class="prem">' + nfmt(s.transferred_mwh, 0) + "</span><small>MWh</small>", s.transferred_batches + " 批 · 客戶持有") +
      kpi("已註銷", '<span class="pos">' + nfmt(s.retired_mwh, 0) + "</span><small>MWh</small>", s.retired_batches + " 批 · 已抵充 RE") +
      kpi("批次數", s.total_batches + "<small>批</small>", "1 憑證 = 1 MWh") +
      "</div>";
    html += '<section class="card"><div class="hd"><h3>憑證帳</h3><span class="aside">' + s.total_batches + " 批次</span></div><div class=\"tablewrap\"><table>" +
      "<thead><tr><th>批次號</th><th>風場</th><th>客戶</th><th>年份別</th><th>數量 (MWh)</th><th>狀態</th><th>動作</th></tr></thead><tbody>";
    if (!r.batches.length) {
      html += '<tr><td class="empty" colspan="7">本期尚無憑證,點「發行本期憑證」由媒合結果產生。</td></tr>';
    } else {
      r.batches.forEach(function (b) {
        html += "<tr><td><span class=\"code\">" + esc(b.batch_no) + "</span></td>" +
          "<td style=\"text-align:left\">" + esc(b.wind_farm_code) + "</td>" +
          "<td style=\"text-align:left\">" + esc(b.customer_code) + " · " + esc(b.company_name) + "</td>" +
          "<td class=\"num\">" + esc(b.period) + "</td>" +
          "<td class=\"num\" style=\"font-weight:700\">" + nfmt(b.quantity_mwh, 0) + "</td>" +
          "<td>" + trecStatusPill(b.status) + "</td>" +
          "<td>" + (b.status === "retired" ? "<span class=\"u\">—</span>" : '<button class="btn ghost" data-retire="' + b.id + '" style="height:28px;padding:0 11px;font-size:12px">註銷</button>') + "</td></tr>";
      });
    }
    html += "</tbody></table></div></section>";
    html += '<div class="foot-note">' + iconInfo() + "1 T-REC = 1,000 度 = 1 MWh。媒合即發行+移轉給客戶(已移轉);註銷後用於抵充 RE、不可再交易。示範資料。</div>";
    body.innerHTML = html;
  }

  // ---------- 合約風險告警 ----------
  var SEV = { high: ["高", "bad"], medium: ["中", "warnp"], low: ["低", "ok"] };
  // risk_service 會發 take_or_pay 這一類,但這張對照表漏了它,類型欄就把原始
  // 代碼直接印進中文欄位——而保證量差額正是合約詳情頁最該講清楚的那一則告警。
  var RISK_CAT = { expiry: "即將到期", under_delivery: "供電不足", over_commitment: "超額承諾", status_mismatch: "狀態不一致", take_or_pay: "保證量差額" };
  function sevPill(s) { var x = SEV[s] || [s, "warnp"]; return '<span class="pill ' + x[1] + '"><span class="dot"></span>' + x[0] + "</span>"; }

  function renderRisks() {
    crumb.textContent = "風險告警";
    view.innerHTML =
      '<div class="pagehead"><div class="title"><span class="bar"></span><h1>合約風險告警</h1></div>' +
      '<div class="meta"><span>掃描所有合約:即將到期、供電不足、風場超額承諾、狀態不一致,依嚴重度排序。</span></div></div>' +
      '<form class="formcard" id="rkForm"><div class="formgrid">' +
      '<div class="field"><label>供電不足評估期間 (YYYY-MM)</label><input id="r-period" class="num" value="' + getPeriod() + '"></div>' +
      '<div class="field"><label>到期預警月數</label><input id="r-horizon" class="num" type="number" min="1" max="60" value="6"></div>' +
      '</div><div class="formactions"><button class="btn primary" type="submit">' +
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 3l9 16H3z"/><path d="M12 10v4M12 17h.01"/></svg>掃描風險</button></div></form>' +
      '<div id="rk-body"><div class="placeholder">載入中…</div></div>';
    function run() {
      var period = document.getElementById("r-period").value.trim();
      var hz = parseInt(document.getElementById("r-horizon").value, 10) || 6;
      var body = document.getElementById("rk-body");
      body.innerHTML = '<div class="placeholder">掃描中…</div>';
      api.contractRisks(period, hz).then(function (r) { renderRiskReport(body, r); })
        .catch(function (err) { body.innerHTML = errbox("掃描風險", err); });
    }
    document.getElementById("rkForm").addEventListener("submit", function (e) { e.preventDefault(); run(); });
    run();
  }

  function renderRiskReport(body, r) {
    var k = r.counts;
    var html = '<div class="kpis">' +
      kpi("高風險", '<span class="neg">' + k.high + "</span>", "需立即處理") +
      kpi("中風險", '<span class="prem">' + k.medium + "</span>", "需關注") +
      kpi("低風險", k.low, "提醒") +
      kpi("告警總數", k.total + "<small>則</small>", "期間 " + esc(r.period) + " · 基準日 " + esc(r.reference_date), "hl") +
      "</div>";
    html += '<section class="card"><div class="hd"><h3>告警清單</h3><span class="aside">依嚴重度排序 · 到期預警 ' + r.horizon_months + " 個月</span></div><div class=\"tablewrap\"><table>" +
      "<thead><tr><th>嚴重度</th><th>類型</th><th>影響對象</th><th>說明</th><th>建議動作</th></tr></thead><tbody>";
    if (!r.alerts.length) {
      html += '<tr><td class="empty" colspan="5">目前無風險告警 ✓</td></tr>';
    } else {
      r.alerts.forEach(function (a) {
        var who = [a.contract_number, a.wind_farm_code, a.customer_code].filter(Boolean).map(esc).join(" · ") || "–";
        html += "<tr><td>" + sevPill(a.severity) + "</td><td>" + (RISK_CAT[a.category] || esc(a.category)) +
          "</td><td style=\"text-align:left\">" + who + "</td><td style=\"text-align:left\">" + esc(a.detail) +
          "</td><td style=\"text-align:left\">" + esc(a.suggested_action) + "</td></tr>";
      });
    }
    html += "</tbody></table></div></section>";
    html += '<div class="foot-note">' + iconInfo() + "到期/狀態以今日為基準;供電不足以選定期間的媒合結果比對合約預期上限。示範資料。</div>";
    body.innerHTML = html;
  }

  // ---------- RE 目標建議 ----------
  function renderRecommend() {
    crumb.textContent = "RE 建議";
    view.innerHTML =
      '<div class="pagehead"><div class="title"><span class="bar"></span><h1>RE 目標建議</h1></div>' +
      '<div class="meta"><span>對未達 RE 目標的客戶,以成本最低優先,建議簽哪些有剩餘綠電的風場來補足缺口。</span></div></div>' +
      '<form class="formcard" id="rcForm"><div class="formgrid">' +
      '<div class="field"><label>用電戶<span class="req">*</span></label><select id="c-customer" required><option value="">載入中…</option></select></div>' +
      '<div class="field"><label>期間 (YYYY-MM)</label><input id="c-period" class="num" value="' + getPeriod() + '"></div>' +
      '</div><div class="formactions"><button class="btn primary" type="submit">' +
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 3a6 6 0 0 0-4 10.5c.5.5 1 1.5 1 2.5h6c0-1 .5-2 1-2.5A6 6 0 0 0 12 3zM9 18h6"/></svg>產生建議</button></div></form>' +
      '<div id="rc-body"><div class="placeholder">載入中…</div></div>';
    var sel = document.getElementById("c-customer");
    api.customers().then(function (list) {
      sel.innerHTML = list.map(function (c) {
        return '<option value="' + c.id + '">' + esc(c.code + " · " + c.company_name) + "</option>";
      }).join("");
      run();
    }).catch(function (err) {
      sel.innerHTML = '<option value="">無法載入用電戶</option>';
      document.getElementById("rc-body").innerHTML = errbox("載入用電戶", err);
    });
    function run() {
      var cid = parseInt(sel.value, 10); if (!cid) return;
      var period = document.getElementById("c-period").value.trim();
      var body = document.getElementById("rc-body");
      body.innerHTML = '<div class="placeholder">運算中…</div>';
      api.reRecommendations(cid, period).then(function (r) { renderRecommendResult(body, r); })
        .catch(function (err) { body.innerHTML = errbox("產生建議", err); });
    }
    document.getElementById("rcForm").addEventListener("submit", function (e) { e.preventDefault(); run(); });
  }

  function renderRecommendResult(body, r) {
    var closePill = r.gap_mwh <= 0
      ? '<span class="pill ok"><span class="dot"></span>已達標</span>'
      : (r.fully_closable ? '<span class="pill ok"><span class="dot"></span>可補足</span>'
        : '<span class="pill bad"><span class="dot"></span>尚缺 ' + nfmt(r.residual_gap_mwh, 0) + " MWh</span>");
    var html = '<div class="kpis">' +
      kpi("RE 目標電量", nfmt(r.target_energy_mwh, 0) + "<small>MWh</small>", esc(r.company_name) + " · 目標 " + pct(r.re_target_percent, 0) + "%", "hl") +
      kpi("目前綠電", nfmt(r.current_green_mwh, 0) + "<small>MWh</small>", "期間 " + esc(r.period)) +
      kpi("RE 缺口", '<span class="' + (r.gap_mwh > 0 ? "neg" : "pos") + '">' + nfmt(r.gap_mwh, 0) + "</span><small>MWh</small>", r.gap_mwh > 0 ? "待補足" : "無缺口") +
      kpi("補足狀態", closePill, r.gap_mwh > 0 ? "需簽約 " + nfmt(r.total_recommended_mwh, 0) + " MWh" : "") +
      "</div>";
    if (r.gap_mwh <= 0) {
      html += '<div class="placeholder"><div class="big">✅</div><h2>已達標,無需補足</h2>' +
        "<p>" + esc(r.company_name) + " 於 " + esc(r.period) + " 已達成 RE 目標,無 RE 缺口。</p></div>";
      body.innerHTML = html;
      return;
    }
    html += '<section class="card"><div class="hd"><h3>建議簽約風場</h3><span class="aside">成本最低優先 · 估計總成本 ' + money(r.total_est_cost) + " NTD</span></div><div class=\"tablewrap\"><table>" +
      "<thead><tr><th>風場</th><th>可簽剩餘 (MWh)</th><th>建議補量 (MWh)</th><th>佔缺口</th><th>躉售價</th><th>估計成本</th><th>類型</th></tr></thead><tbody>";
    if (!r.recommendations.length) {
      html += '<tr><td class="empty" colspan="7">目前無可用的剩餘綠電可補足缺口</td></tr>';
    } else {
      r.recommendations.forEach(function (x) {
        html += "<tr><td><span class=\"code\">" + esc(x.code) + "</span> " + esc(x.name) + "</td>" +
          "<td class=\"num\">" + nfmt(x.available_surplus_mwh, 0) + "</td>" +
          "<td class=\"num\" style=\"font-weight:700\">" + nfmt(x.recommended_mwh, 0) + "</td>" +
          "<td class=\"num\">" + pct(x.gap_covered_percent) + "%</td>" +
          "<td class=\"num\">" + price(x.feed_in_price_per_kwh) + "</td>" +
          "<td class=\"num\">" + money(x.est_cost) + "</td>" +
          "<td>" + (x.has_existing_contract ? '<span class="pill ok"><span class="dot"></span>擴約</span>' : '<span class="pill warnp"><span class="dot"></span>新簽</span>') + "</td></tr>";
      });
    }
    html += "</tbody></table></div></section>";
    html += '<div class="foot-note">' + iconInfo() + "以成本最低優先,用有剩餘綠電的風場補足缺口。躉售價為指示性成本(非轉供價)。示範資料。</div>";
    body.innerHTML = html;
  }

  // ---------- 多對多匹配 (情境模擬 · greenfield what-if) ----------
  function renderMatchmap() {
    crumb.textContent = "多對多匹配";
    var fmMap = {}, cmMap = {};
    view.innerHTML =
      '<div class="pagehead"><div><div class="title"><span class="bar"></span><h1>多對多綠電匹配</h1></div>' +
      '<div class="meta"><span>情境模擬:自選要納入的案場/用電端,自訂各家 RE 目標,重算最佳綠電配置組合。</span></div></div>' +
      '<div class="headactions"><input id="mm-period" class="period-input num" value="' + getPeriod() + '" placeholder="2024-01">' +
      '<button class="btn primary" id="mm-go">查詢</button></div></div>' +
      '<div id="mm-panel"><div class="placeholder">載入案場與用電端…</div></div>' +
      '<div id="mm-body"></div>';

    var goBtn = document.getElementById("mm-go");
    var periodInp = document.getElementById("mm-period");
    goBtn.addEventListener("click", run);
    periodInp.addEventListener("keydown", function (e) { if (e.key === "Enter") run(); });

    Promise.all([api.windFarms(), api.customers()]).then(function (res) {
      res[0].forEach(function (f) { fmMap[f.id] = f; });
      res[1].forEach(function (c) { cmMap[c.id] = c; });
      document.getElementById("mm-panel").innerHTML = buildScenarioPanel(res[0], res[1]);
      wirePanel();
      run();
    }).catch(function (err) {
      document.getElementById("mm-panel").innerHTML = errbox("載入案場/用電端", err);
    });

    function wirePanel() {
      document.getElementById("mm-run").addEventListener("click", run);
      Array.prototype.forEach.call(document.querySelectorAll(".mm-all"), function (b) {
        b.addEventListener("click", function () {
          var tgt = b.getAttribute("data-tgt");
          var boxes = document.querySelectorAll('input[data-' + tgt + 'id]');
          var anyOff = Array.prototype.some.call(boxes, function (x) { return !x.checked; });
          Array.prototype.forEach.call(boxes, function (x) { x.checked = anyOff; });
        });
      });
    }

    function run() {
      var period = periodInp.value.trim(); setPeriod(period);
      var body = document.getElementById("mm-body");
      var farmIds = pickedIds("fid"), custIds = pickedIds("cid");
      if (!farmIds.length || !custIds.length) {
        body.innerHTML = '<div class="placeholder"><div class="big">☑️</div><h2>請至少勾選一個發電案場與一個用電端</h2>' +
          "<p>在上方「情境設定」中勾選要納入媒合的案場與用電端,再按「重算最佳配置」。</p></div>";
        return;
      }
      var reParts = [];
      custIds.forEach(function (cid) {
        var el = document.querySelector('input[data-cidre="' + cid + '"]');
        if (el && el.value.trim() !== "") reParts.push(cid + ":" + el.value.trim());
      });
      var fiParts = [];
      farmIds.forEach(function (fid) {
        var el = document.querySelector('input[data-fidfi="' + fid + '"]');
        if (el && el.value.trim() !== "") fiParts.push(fid + ":" + el.value.trim());
      });
      var priceEl = document.getElementById("mm-price");
      var priceV = priceEl && priceEl.value.trim();
      body.innerHTML = '<div class="placeholder">求解最佳配置中…</div>';
      api.scenario(period, {
        farmIds: farmIds.join(","),
        customerIds: custIds.join(","),
        reTargets: reParts.join(","),
        feedIns: fiParts.join(","),
        transferPrice: priceV ? parseFloat(priceV) : undefined,
      }).then(function (r) { renderMatchmapResult(body, r, fmMap, cmMap); })
        .catch(function (err) { body.innerHTML = errbox("求解最佳配置", err); });
    }

    function pickedIds(attr) {
      return Array.prototype.filter.call(
        document.querySelectorAll('input[data-' + attr + ']'), function (x) { return x.checked; }
      ).map(function (x) { return parseInt(x.getAttribute("data-" + attr), 10); });
    }
  }

  function buildScenarioPanel(farms, custs) {
    var fRows = farms.map(function (f) {
      var fi = f.feed_in_price_per_kwh == null ? 4.0 : f.feed_in_price_per_kwh;
      return '<div class="mm-pick farm"><label><input type="checkbox" data-fid="' + f.id + '" checked>' +
        '<span class="code">' + esc(f.code) + '</span> <span class="nm">' + esc((f.name || "").split(" (")[0]) + "</span></label>" +
        '<span class="mm-fi"><input class="num" type="number" min="0" step="0.1" data-fidfi="' + f.id + '" value="' + fi + '"><i>躉售</i></span></div>';
    }).join("");
    var cRows = custs.map(function (c) {
      var t = c.re_target_percent == null ? 0 : c.re_target_percent;
      return '<div class="mm-pick cust"><label><input type="checkbox" data-cid="' + c.id + '" checked>' +
        '<span class="code">' + esc(c.code) + '</span> <span class="nm">' + esc(c.company_name || "") + "</span></label>" +
        '<span class="mm-re"><input class="num" type="number" min="0" max="100" step="1" data-cidre="' + c.id + '" value="' + t + '"><i>% RE</i></span></div>';
    }).join("");
    return '<section class="card mm-panel"><div class="hd"><h3>情境設定</h3>' +
      '<span class="aside">選要納入的案場/用電端,並可自訂各家 RE 目標</span></div>' +
      '<div class="mm-panelbody">' +
      '<div class="mm-pricerow"><label>假設轉供價 <input id="mm-price" class="num" type="number" min="0" step="0.1" value="5.0"> NTD/kWh</label>' +
      '<span class="hint">無合約的「假設配對」用此售價估毛利(毛利 = 售價 − 案場躉售成本)</span></div>' +
      '<div class="mm-picks"><div class="mm-col"><div class="mm-colhd"><span>發電案場</span>' +
      '<button class="mm-all" data-tgt="f" type="button">全選 / 清空</button></div><div class="mm-list">' + fRows + "</div></div>" +
      '<div class="mm-col"><div class="mm-colhd"><span>用電端 · RE 目標</span>' +
      '<button class="mm-all" data-tgt="c" type="button">全選 / 清空</button></div><div class="mm-list">' + cRows + "</div></div></div>" +
      '<div class="mm-panelactions"><button class="btn primary" id="mm-run" type="button">' +
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M20 11a8 8 0 1 0-2.3 5.7M20 5v6h-6"/></svg>重算最佳配置</button></div></div></section>';
  }

  function mmShort(s, n) {
    s = String(s == null ? "" : s);
    return s.length > n ? s.slice(0, n) + "…" : s;
  }

  function renderMatchmapResult(body, opt, fm, cm) {
    var farmSum = {}, custSum = {}, custTgt = {};
    (opt.farm_summaries || []).forEach(function (s) { farmSum[s.wind_farm_id] = s; });
    (opt.customer_summaries || []).forEach(function (s) { custSum[s.customer_id] = s; });
    (opt.customer_targets || []).forEach(function (t) { custTgt[t.customer_id] = t; });

    // 把 allocation 依 (案場,客戶) 聚合成一條流,並記錄是否為真實合約
    var pair = {}, hc = {};
    (opt.allocations || []).forEach(function (a) {
      if (!(a.allocated_mwh > 0.0001)) return;
      var k = a.wind_farm_id + "|" + a.customer_id;
      pair[k] = (pair[k] || 0) + a.allocated_mwh;
      hc[k] = !!a.has_contract;
    });
    var pairKeys = Object.keys(pair);

    var totalGreen = 0; pairKeys.forEach(function (k) { totalGreen += pair[k]; });
    var hypoGreen = 0; pairKeys.forEach(function (k) { if (!hc[k]) hypoGreen += pair[k]; });
    var totalSurplus = 0; (opt.farm_summaries || []).forEach(function (s) { totalSurplus += (s.unallocated_mwh || 0); });
    // 顯示「所有選定」的案場/用電端(含未配到綠電者),對齊情境選擇
    var shownFarmIds = (opt.farm_ids || []).slice().sort(function (a, b) { return a - b; });
    var shownCustIds = (opt.customer_ids || []).slice().sort(function (a, b) { return a - b; });
    var metCount = 0, reSum = 0, reN = 0;
    shownCustIds.forEach(function (id) {
      var t = custTgt[id], s = custSum[id];
      if (t && t.re_target_met) metCount++;
      if (s) { reSum += s.achieved_re_percent; reN++; }
    });
    var avgRe = reN ? reSum / reN : 0;
    var hypoPct = totalGreen > 0 ? hypoGreen / totalGreen * 100 : 0;

    var html = '<div class="kpis">' +
      kpi("售電業毛利", money(opt.objective_gross_margin_ntd) + "<small>NTD</small>", "最佳解 · 假設轉供價 " + price(opt.assumed_transfer_price_per_kwh), "hl", opt.objective_gross_margin_ntd >= 0 ? "up" : "down") +
      kpi("總配置綠電", nfmt(totalGreen, 0) + "<small>MWh</small>", hypoGreen > 0.5 ? "其中假設新配對 " + pct(hypoPct, 0) + "%" : "全數為既有合約") +
      kpi("平均 RE 達成", pct(avgRe) + "<small>%</small>", "達標 " + metCount + " / " + shownCustIds.length + " 家") +
      kpi("案場餘電", nfmt(Math.max(0, totalSurplus), 0) + "<small>MWh</small>", totalSurplus > 0.5 ? "尚可再售" : "已幾近全數消化") +
      "</div>";

    if (!pairKeys.length) {
      html += '<div class="placeholder"><div class="big">🔌</div><h2>此情境下無綠電配置</h2>' +
        "<p>期間 " + esc(opt.period) + " 選定的案場沒有可配置的綠電(可能無發電,或售價低於躉售成本且各家 RE 目標為 0)。可調整假設轉供價、RE 目標或期間再試。</p></div>";
      body.innerHTML = html;
      return;
    }

    var farms = shownFarmIds.map(function (id) {
      var f = fm[id] || {}, s = farmSum[id] || {};
      var thru = 0; pairKeys.forEach(function (k) { if (+k.split("|")[0] === id) thru += pair[k]; });
      return { id: id, label: mmShort((f.name || f.code || ("#" + id)).split(" (")[0], 10), code: f.code || ("#" + id),
        gen: s.generated_mwh || 0, surplus: s.unallocated_mwh || 0, thru: thru };
    });
    var custs = shownCustIds.map(function (id) {
      var c = cm[id] || {}, s = custSum[id] || {}, t = custTgt[id] || {};
      var thru = 0; pairKeys.forEach(function (k) { if (+k.split("|")[1] === id) thru += pair[k]; });
      // effective (possibly overridden) target %, derived from the solved target energy
      var tgtPct = (s.consumption_mwh > 0 && t.re_target_mwh != null)
        ? (t.re_target_mwh / s.consumption_mwh * 100) : c.re_target_percent;
      var re = s.achieved_re_percent != null ? s.achieved_re_percent : 0;
      return { id: id, label: mmShort(c.company_name || c.code || ("#" + id), 8), code: c.code || ("#" + id),
        re: re, target: tgtPct, met: !!t.re_target_met, thru: thru,
        gap: Math.max(0, (tgtPct || 0) - re),  // percentage points short of target
        targetMwh: t.re_target_mwh || 0, allocMwh: t.allocated_mwh || 0 };
    });

    // 供電不足偵測:target-cap 後,任何「未達」都是因為可用綠電不夠(非設定問題)
    var unmet = custs.filter(function (c) { return !c.met && c.gap > 0.05; });
    var needTotal = 0, allocTotal = 0;
    custs.forEach(function (c) { needTotal += c.targetMwh; allocTotal += c.allocMwh; });
    if (unmet.length) {
      html += '<div class="mm-supply-note">' + iconWarn() +
        "<div><b>發電量不足以完整滿足用電端 RE 目標。</b> 此情境綠電總配置 " + nfmt(allocTotal, 0) +
        " MWh、用電端目標合計 " + nfmt(needTotal, 0) + " MWh(缺口 " + nfmt(Math.max(0, needTotal - allocTotal), 0) +
        " MWh)。已把可用綠電<b>盡量分配</b>給各用電端;下方標「發電不足」者受限於可用綠電,並非目標設定問題。" +
        "</div></div>";
    }

    html += '<section class="card mm-card"><div class="hd"><h3>綠電配置最佳解</h3>' +
      '<span class="aside">帶寬 ∝ 配置電量 · 實線=既有合約 · 虛線=假設新配對</span></div>' +
      '<div class="mm-legend"><span class="mm-lg farm">發電案場</span>' +
      '<span class="mm-arrow">綠電配置 →</span>' +
      '<span class="mm-lg cust">用電端 · RE 目標</span></div>' +
      buildFlowSVG(farms, custs, pair, hc) +
      '<div class="mm-caps"><span>提升售電業總營收利潤,消化案場餘電</span>' +
      '<span>實現企業 RE 綠電目標</span></div></section>';

    // 用電端 RE 達成(目標 vs 實際),未達者標「發電不足」——最不足者排前
    var attain = custs.slice().sort(function (a, b) {
      var ra = a.target > 0 ? a.re / a.target : 1, rb = b.target > 0 ? b.re / b.target : 1;
      return ra - rb;
    });
    html += '<section class="card"><div class="hd"><h3>用電端 RE 達成</h3>' +
      '<span class="aside">目標 vs 實際配置 · 未達=發電不足</span></div><div class="tablewrap"><table>' +
      "<thead><tr><th>用電端</th><th>RE 目標</th><th>配置綠電 (MWh)</th><th>達成率</th><th>距目標</th><th>狀態</th></tr></thead><tbody>";
    attain.forEach(function (c) {
      var cust = cm[c.id] || {};
      html += "<tr><td style=\"text-align:left\"><span class=\"code\">" + esc(c.code) + "</span> " + esc(cust.company_name || "") + "</td>" +
        "<td class=\"num\">" + (c.target == null ? "–" : pct(c.target, 0) + "%") + "</td>" +
        "<td class=\"num\">" + nfmt(c.allocMwh, 0) + "</td>" +
        "<td class=\"num\">" + reCell(c.re) + "</td>" +
        "<td class=\"num\">" + (c.met ? "—" : '<span class="neg">缺 ' + pct(c.gap, 0) + "%</span>") + "</td>" +
        "<td>" + (c.met
          ? '<span class="pill ok"><span class="dot"></span>達標</span>'
          : '<span class="pill bad"><span class="dot"></span>發電不足</span>') + "</td></tr>";
    });
    html += "</tbody></table></div></section>";

    var rows = pairKeys.map(function (k) {
      var p = k.split("|"); return { fid: +p[0], cid: +p[1], mwh: pair[k] };
    }).sort(function (a, b) { return b.mwh - a.mwh; });
    var custThru = {}; custs.forEach(function (c) { custThru[c.id] = c.thru; });
    html += '<section class="card"><div class="hd"><h3>配置明細</h3><span class="aside">' + rows.length + " 條配置 · 依電量排序</span></div><div class=\"tablewrap\"><table>" +
      "<thead><tr><th>發電案場</th><th>用電端</th><th>配對</th><th>配置電量 (MWh)</th><th>占客戶綠電</th><th>占案場發電</th></tr></thead><tbody>";
    rows.forEach(function (r) {
      var f = fm[r.fid] || {}, c = cm[r.cid] || {}, s = farmSum[r.fid] || {};
      var shareCust = custThru[r.cid] ? r.mwh / custThru[r.cid] * 100 : 0;
      var shareFarm = s.generated_mwh ? r.mwh / s.generated_mwh * 100 : 0;
      var real = hc[r.fid + "|" + r.cid];
      html += "<tr><td style=\"text-align:left\"><span class=\"code\">" + esc(f.code || ("#" + r.fid)) + "</span> " + esc((f.name || "").split(" (")[0]) + "</td>" +
        "<td style=\"text-align:left\"><span class=\"code\">" + esc(c.code || ("#" + r.cid)) + "</span> " + esc(c.company_name || "") + "</td>" +
        "<td>" + (real ? '<span class="pill ok"><span class="dot"></span>合約</span>' : '<span class="pill warnp"><span class="dot"></span>假設</span>') + "</td>" +
        "<td class=\"num\" style=\"font-weight:700\">" + nfmt(r.mwh, 0) + "</td>" +
        "<td class=\"num\">" + pct(shareCust, 0) + "%</td>" +
        "<td class=\"num\">" + pct(shareFarm, 0) + "%</td></tr>";
    });
    html += "</tbody></table></div></section>";
    html += mmExplainBlock();
    html += '<div class="foot-note">' + iconInfo() + "情境模擬:任一選定案場皆可(假設性)供電給任一選定客戶,以最便宜綠電優先滿足各家 RE 目標、再放大售電毛利。實線/「合約」= 既有 PPA;虛線/「假設」= 尚無合約的 what-if。轉供結算與售電評估頁仍以既有合約為準。示範資料。</div>";

    body.innerHTML = html;
  }

  function buildFlowSVG(farms, custs, pair, hc) {
    hc = hc || {};
    var W = 980, padY = 30, boxW = 198, boxH = 62, rowPitch = 92;
    var leftX = 12, rightX = W - 12 - boxW;      // 左欄 12..210 ; 右欄 770..968
    var innerL = leftX + boxW, innerR = rightX;  // 流帶起訖 x
    var F = farms.length, C = custs.length;
    var H = padY * 2 + Math.max(F, C) * rowPitch;
    function colY(i, n) { return (H - n * rowPitch) / 2 + i * rowPitch + rowPitch / 2; }
    var farmById = {}, custById = {};
    farms.forEach(function (f, i) { f.cy = colY(i, F); farmById["f" + f.id] = f; });
    custs.forEach(function (c, j) { c.cy = colY(j, C); custById["c" + c.id] = c; });

    var maxFarm = Math.max.apply(null, farms.map(function (f) { return f.thru; }).concat([1]));
    var maxCust = Math.max.apply(null, custs.map(function (c) { return c.thru; }).concat([1]));
    var cap = boxH * 0.84;
    var ppm = Math.min(cap / maxFarm, cap / maxCust);  // 每 MWh 的像素寬,兩側都不溢出

    // 產生流帶並在左右兩側各自堆疊錨點(排序以減少交叉)
    var flows = [];
    farms.forEach(function (f) {
      var outs = [];
      custs.forEach(function (c) {
        var m = pair[f.id + "|" + c.id]; if (!m) return;
        outs.push({ fid: f.id, cid: c.id, mwh: m, w: Math.max(1.5, m * ppm), ccy: c.cy });
      });
      outs.sort(function (a, b) { return a.ccy - b.ccy; });
      outs.forEach(function (o) { o.real = !!hc[o.fid + "|" + o.cid]; });
      var tot = outs.reduce(function (s, o) { return s + o.w; }, 0);
      var cur = f.cy - tot / 2;
      outs.forEach(function (o) { o.lY = cur; cur += o.w; flows.push(o); });
    });
    custs.forEach(function (c) {
      var ins = flows.filter(function (o) { return o.cid === c.id; });
      ins.sort(function (a, b) { return farmById["f" + a.fid].cy - farmById["f" + b.fid].cy; });
      var tot = ins.reduce(function (s, o) { return s + o.w; }, 0);
      var cur = c.cy - tot / 2;
      ins.forEach(function (o) { o.rY = cur; cur += o.w; });
    });

    var xm = (innerL + innerR) / 2;
    var svg = '<div class="mm-wrap"><svg class="mm-svg" viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="xMidYMid meet" role="img" aria-label="綠電多對多配置圖">';
    flows.forEach(function (o) {
      var f = farmById["f" + o.fid], c = custById["c" + o.cid];
      var t0 = o.lY, t1 = o.rY, w = o.w;
      var d = "M" + innerL + "," + t0.toFixed(1) +
        " C" + xm + "," + t0.toFixed(1) + " " + xm + "," + t1.toFixed(1) + " " + innerR + "," + t1.toFixed(1) +
        " L" + innerR + "," + (t1 + w).toFixed(1) +
        " C" + xm + "," + (t1 + w).toFixed(1) + " " + xm + "," + (t0 + w).toFixed(1) + " " + innerL + "," + (t0 + w).toFixed(1) + " Z";
      svg += '<path class="mm-flow ' + (o.real ? "real" : "hypo") + '" d="' + d + '"><title>' +
        esc(f.code) + " → " + esc(c.code) + " · " + nfmt(o.mwh, 0) + " MWh(占客戶 " + pct(c.thru ? o.mwh / c.thru * 100 : 0, 0) + "%)" +
        (o.real ? " · 既有合約" : " · 假設新配對") + "</title></path>";
    });
    farms.forEach(function (f) {
      var y = f.cy - boxH / 2;
      svg += '<g class="mm-node mm-farm">' +
        '<rect x="' + leftX + '" y="' + y.toFixed(1) + '" width="' + boxW + '" height="' + boxH + '" rx="10"/>' +
        '<text class="mm-t1" x="' + (leftX + 14) + '" y="' + (y + 25).toFixed(1) + '">' + esc(f.label) + "</text>" +
        '<text class="mm-t2" x="' + (leftX + 14) + '" y="' + (y + 45).toFixed(1) + '">發 ' + nfmt(f.gen, 0) + " · 餘 " + nfmt(f.surplus, 0) + " MWh</text>" +
        "<title>" + esc(f.code) + " " + esc(f.label) + "</title></g>";
    });
    custs.forEach(function (c) {
      var y = c.cy - boxH / 2;
      var dotC = c.met ? "var(--good)" : "var(--warn)";
      svg += '<g class="mm-node mm-cust">' +
        '<rect x="' + rightX + '" y="' + y.toFixed(1) + '" width="' + boxW + '" height="' + boxH + '" rx="10"/>' +
        '<circle cx="' + (rightX + boxW - 16) + '" cy="' + (y + 16) + '" r="5" fill="' + dotC + '"/>' +
        '<text class="mm-t1" x="' + (rightX + 14) + '" y="' + (y + 25).toFixed(1) + '">' + esc(c.label) + "</text>" +
        '<text class="' + (c.met ? "mm-t2" : "mm-t2 warn") + '" x="' + (rightX + 14) + '" y="' + (y + 45).toFixed(1) + '">RE ' +
        pct(c.re, 0) + "% / 目標 " + (c.target == null ? "–" : pct(c.target, 0) + "%") +
        (!c.met && c.gap > 0.5 ? " · 缺 " + pct(c.gap, 0) + "%" : "") + "</text>" +
        "<title>" + esc(c.code) + " " + esc(c.label) + " · " + (c.met ? "達標" : "發電不足,缺 " + pct(c.gap, 0) + "%") + "</title></g>";
    });
    svg += "</svg></div>";
    return svg;
  }

  // 三階段視覺化小卡(每根柱=一個用電端的配置,演化到公平均攤)
  function mmPhaseCard(n, title, tag, desc, heights, cls) {
    var bars = heights.map(function (h) {
      return '<i class="' + cls + '" style="height:' + h + 'px"></i>';
    }).join("");
    return '<div class="mm-exph"><div class="mm-exph-h"><span class="pn">' + n + "</span><b>" + title + "</b>" +
      '<span class="tg">' + tag + "</span></div>" +
      '<div class="mm-exbars">' + bars + "</div><p>" + desc + "</p></div>";
  }

  // 可展開的「計算方式與演算流程」說明(預設收合)
  function mmExplainBlock() {
    return '<details class="mm-explain"><summary>計算方式與演算流程 · 點此展開</summary>' +
      '<div class="mm-explain-body">' +
      '<p class="lead">這頁<b>不是</b>逐筆「先搶先贏」的貪婪分配,而是一次<b>全域最佳化</b>:把所有可能的「案場 × 客戶」配對同時放進一個<b>混合整數線性規劃(MILP)</b>,用 PuLP + CBC 求解器<b>解到數學最佳解</b>。</p>' +
      "<h4>決策變數</h4><ul>" +
      "<li>每一組(發電案場 → 用電端)的<b>配置電量</b>(連續變數,MWh)。</li>" +
      "<li>每一組配對的<b>是否啟用</b>(0/1 二元變數,用於「最少案場數」等結構限制)。</li></ul>" +
      "<h4>限制條件</h4><ul>" +
      "<li><b>案場供給</b>:一座案場配出去的總量 ≤ 它當月發電量(綠電不會被分兩次)。</li>" +
      "<li><b>客戶綠電上限</b>:一個用電端收到的綠電 ≤ 它的 <b>RE 目標電量</b> → 達成率<b>不會超過</b>你設定的目標;多出來的綠電留為案場餘電,不會硬塞。</li>" +
      "<li><b>RE 目標(填到滿)</b>:綠電足夠時填到目標;不夠時差額記為缺口。</li>" +
      "<li>(選用)最少案場數、單場最小分配比例。</li></ul>" +
      "<h4>目標:三階段「字典序」最佳化</h4>" +
      "<p>三個目標有優先順序,依序求解;每個階段先<b>鎖住</b>上一階段的成果,再往下最佳化。" +
      "下圖每根小柱代表一個用電端的配置,看它如何一步步演化到<b>公平均攤</b>:</p>" +
      '<div class="mm-expipe">' +
      mmPhaseCard("1", "先顧達標", "最小化 RE 缺口", "讓所有客戶「未達 RE 目標的總缺口」最小。", [22, 27, 13, 31, 17, 10], "g") +
      '<span class="mm-exarr">▶</span>' +
      mmPhaseCard("2", "再顧毛利", "最大化毛利", "不犧牲上一關,讓售電毛利最大——便宜綠電優先賣。", [31, 12, 24, 34, 15, 20], "d") +
      '<span class="mm-exarr">▶</span>' +
      mmPhaseCard("3", "求公平", "maximin 公平", "不犧牲前兩關,把「最低達成率」拉最高;不夠分時按比例均攤。", [24, 24, 24, 24, 24, 24], "g") +
      "</div>" +
      "<h4>有沒有迭代?</h4><p>有,兩個層次:</p><ul>" +
      "<li><b>三次依序求解</b>:上面三個階段就是跑三輪 CBC,一輪鎖住結果、下一輪接著最佳化(字典序法)。</li>" +
      "<li><b>求解器內部迭代</b>:每一輪 CBC 以<b>分支定界 + 單純形</b>反覆迭代,直到證明是最佳解(最佳化間隙設為 0,不提早停)。</li></ul>" +
      '<p class="muted">它<b>不是</b>那種「跑很多輪隨機試誤 / 逐步貪婪逼近」的啟發式;每一輪都求到精確最佳。</p>' +
      "<h4>決定性</h4>" +
      '<p class="muted">輸入相同 → 結果永遠相同(案場、客戶先排序,消除退化解的隨機性)。實線=既有合約、虛線=假設新配對,僅影響顯示,不影響計算。</p>' +
      '<p class="mm-ex-link"><a href="https://claude.ai/code/artifact/efbab99c-5166-4fa4-bcb8-e31aa1d6795b" target="_blank" rel="noopener">看完整視覺化圖解 →</a></p>' +
      "</div></details>";
  }

  // ---------- 轉供結算單 (P5) ----------
  var SLOT_LABEL = { peak: "尖峰", half_peak: "半尖峰", off_peak: "離峰" };
  function slotName(s) { return SLOT_LABEL[s] || s; }

  function renderSettlement() {
    crumb.textContent = "轉供結算";
    view.innerHTML =
      '<div class="pagehead"><div class="title"><span class="bar"></span><h1>轉供結算單</h1></div>' +
      '<div class="meta"><span>選用電戶與期間,產出雙方逐時段轉供結算單(綠電轉供費、台電輸配費、售電毛利、減碳量)。</span></div></div>' +
      '<form class="formcard" id="stForm"><div class="formgrid">' +
      '<div class="field"><label>用電戶<span class="req">*</span></label><select id="s-customer" required><option value="">載入中…</option></select></div>' +
      '<div class="field"><label>期間 (YYYY-MM)</label><input id="s-period" class="num" value="' + getPeriod() + '"></div>' +
      '<div class="field"><label>轉供價</label><input id="s-transfer" class="num" type="number" min="0" step="0.1" placeholder="依合約"><span class="hint">NTD/kWh · 可覆寫</span></div>' +
      '<div class="field"><label>台電輸配費</label><input id="s-wheel" class="num" type="number" min="0" step="0.01" placeholder="0.1"><span class="hint">NTD/kWh · 可覆寫</span></div>' +
      '</div><div class="formactions"><button class="btn primary" type="submit">' +
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 7h16M7 12h10M10 17h4"/></svg>產生結算單</button></div></form>' +
      '<div id="st-result"></div>';
    var sel = document.getElementById("s-customer");
    function run() {
      var cid = parseInt(sel.value, 10); if (!cid) { sel.focus(); return; }
      var period = document.getElementById("s-period").value.trim();
      var tv = document.getElementById("s-transfer").value.trim();
      var wv = document.getElementById("s-wheel").value.trim();
      showModal("正在產生轉供結算單…");
      var root = document.getElementById("st-result");
      api.settlement(cid, period, tv === "" ? null : parseFloat(tv), wv === "" ? null : parseFloat(wv))
        .then(function (r) { renderSettlementBill(root, r); })
        .catch(function (err) { root.innerHTML = errbox("產生結算單", err); })
        .then(function () { setTimeout(hideModal, reduce ? 0 : 300); });
    }
    api.customers().then(function (list) {
      sel.innerHTML = list.map(function (c) {
        return '<option value="' + c.id + '">' + esc(c.code + " · " + c.company_name) + "</option>";
      }).join("");
      if (list[0]) run();  // auto-run for the first customer so the page isn't empty
    }).catch(function (err) {
      sel.innerHTML = '<option value="">無法載入用電戶</option>';
      document.getElementById("st-result").innerHTML = errbox("載入用電戶", err);
    });
    document.getElementById("stForm").addEventListener("submit", function (e) { e.preventDefault(); run(); });
  }

  function renderSettlementBill(root, r) {
    var t = r.totals;
    var farms = (r.farms || []).map(function (f) { return esc(f.wind_farm_name || f.wind_farm_code); }).join(" · ") || "–";
    var seasonLabel = r.season === "summer" ? "夏月" : "非夏月";
    var html = '<section class="card">' +
      '<div class="hd"><h3>轉供結算單 · ' + esc(r.period) + "</h3><span class=\"aside\">" + seasonLabel + " · " + esc(r.solver_status) + "</span></div>" +
      '<div class="rows"><div class="row"><span class="lab">用電戶</span><span class="val">' + esc(r.company_name) + " (" + esc(r.customer_code) + ")</span></div>" +
      '<div class="row"><span class="lab">供電風場</span><span class="val">' + farms + "</span></div>" +
      '<div class="row"><span class="lab">轉供價 / 輸配費</span><span class="val num">' + price(r.transfer_price_per_kwh) + " / " + price(r.wheeling_fee_per_kwh) + '<span class="u">NTD/kWh</span></span></div></div>';
    // 時段別供需匹配圖(結算的綠/灰電量 → 用電=綠+灰、已分配=綠)
    html += '<div class="subhd"><span>時段別供需匹配</span><small>風電進來怎麼對上用電</small></div>' +
      slotMatchViz((r.slots || []).map(function (s) {
        var cons = (s.green_mwh || 0) + (s.grey_mwh || 0);
        return { slot: s.slot, consumption_mwh: cons, allocated_mwh: s.green_mwh || 0, re_percent: cons > 0 ? (s.green_mwh || 0) / cons * 100 : 0 };
      }));
    html += '<div class="tablewrap"><table><thead><tr><th>時段</th><th>綠電量 (MWh)</th><th>轉供價</th><th>綠電金額</th><th>灰電量 (MWh)</th><th>灰電TOU價</th><th>灰電金額</th></tr></thead><tbody>';
    (r.slots || []).forEach(function (s) {
      html += "<tr><td>" + slotName(s.slot) + "</td><td class=\"num\">" + nfmt(s.green_mwh, 0) + "</td><td class=\"num\">" + price(s.transfer_price_per_kwh) +
        "</td><td class=\"num\">" + money(s.green_cost) + "</td><td class=\"num\">" + nfmt(s.grey_mwh, 0) + "</td><td class=\"num\">" + price(s.grey_price_per_kwh) + "</td><td class=\"num\">" + money(s.grey_cost) + "</td></tr>";
    });
    html += "</tbody></table></div>";
    html += '<div class="rows">' +
      erow("綠電轉供費", money(t.green_transfer_cost), "NTD") +
      erow("台電輸配費", "+" + money(t.wheeling_fee), "NTD") +
      (t.take_or_pay_charge > 0
        ? erow("保證量差額 (take-or-pay)", "+" + money(t.take_or_pay_charge) + "（未達 " + nfmt(t.take_or_pay_shortfall_mwh, 0) + " MWh）", "NTD", "prem")
        : "") +
      erowTotal("客戶應付合計", money(t.customer_payable), "NTD", "pos") +
      erow("風場應收", money(t.farm_receivable), "NTD") +
      erow("售電業毛利", money(t.retailer_margin) + " (" + pct(t.retailer_margin_percent) + "%)", "NTD", t.retailer_margin >= 0 ? "pos" : "neg", null, "retailerMargin") +
      erow("灰電補足（參考）", money(t.grey_cost), "NTD", "prem", null, "greyTopup") +
      '</div>';
    html += '<div class="slotnote">' + iconInfo() + "減碳量 <b>" + nfmt(t.carbon_avoided_tco2e, 0) + " tCO₂e</b>(綠電 " + nfmt(t.green_mwh, 0) + " MWh × " + price(r.grid_emission_factor_kg_per_kwh) + " kgCO₂e/kWh)。灰電補足為客戶剩餘用電成本,僅供參考、不計入應付。</div>";
    html += "</section>";
    root.innerHTML = html;
  }

  // ---------- 逐時匹配 (24/7 CFE) ----------
  function renderCfe() {
    crumb.textContent = "逐時匹配";
    view.innerHTML = pageHeadWithPeriod(
      "逐時匹配 (24/7 CFE)",
      "只有同一小時內發電與用電重疊才算真綠電;逐時 CFE% 對照帳面 RE%,差距即時間錯配。",
      "cfe"
    );
    function load() {
      var period = periodVal("cfe");
      var body = document.getElementById("cfe-body");
      body.innerHTML = '<div class="placeholder">計算中…</div>';
      api.hourlyMatching(period).then(function (r) {
        body.innerHTML = cfeBody(r);
        wireCfe(r);
      }).catch(function (err) { body.innerHTML = errbox("逐時匹配", err); });
    }
    bindPeriod("cfe", load);
    load();
  }

  function cfeBody(r) {
    var gap = Math.max(0, r.paper_re_percent - r.cfe_percent);
    // 有電池時,發電分成三個互斥的桶：直供 + 充進電池 + 外溢（見 app/matching/storage.py）。
    // 充進去卻沒出來的（往返損耗 + 期末殘留）誰也沒用到 → 單獨報,不藏進外溢。
    var hasBattery = r.total_charged_mwh != null;
    var stuck = hasBattery ? Math.max(0, r.total_charged_mwh - r.total_discharged_mwh) : 0;
    var kpis = '<div class="kpis">' +
      kpi("逐時 CFE%", pct(r.cfe_percent) + "<small>%</small>", "真時間匹配率", "hl") +
      kpi("帳面 RE%", pct(r.paper_re_percent) + "<small>%</small>", "月總量淨額") +
      kpi("時間錯配", '<span class="' + (gap > 0.05 ? "neg" : "pos") + '">' + pct(gap) + "</span><small>pt</small>", "帳面 − 逐時") +
      kpi("外溢", nfmt(r.total_surplus_mwh, 0) + "<small>MWh</small>", hasBattery ? "沒人用,也沒存進電池" : "發電時沒人用") +
      kpi("缺口", nfmt(r.total_shortfall_mwh, 0) + "<small>MWh</small>", "用電時沒風→灰電") +
      (hasBattery
        ? kpi("儲能送出", nfmt(r.total_discharged_mwh, 0) + "<small>MWh</small>",
          "充入 " + nfmt(r.total_charged_mwh, 0) + " · 損耗與期末殘留 " + nfmt(stuck, 0))
        : "") +
      "</div>";
    // 風光互補（B4）：有光電時才有對照組，直接把增益放在最上面。
    var uplift = (r.uplift_pt != null || r.storage_uplift_pt != null)
      ? '<div id="cfe-uplift">' + upliftBar("全系統", r) + "</div>"
      : "";
    var opts = '<option value="__all">全系統</option>' + r.customers.map(function (c) {
      return '<option value="' + c.customer_id + '">' + esc(c.name) + "</option>";
    }).join("");
    var srcBadge = r.source === "interval"
      ? '<span class="src-pill ok">真實 interval · 逐日 15 分鐘（示範模擬）</span>'
      : '<span class="src-pill">典型日型建模</span>';
    var chart = '<section class="card"><div class="hd"><h3>24 小時供需匹配</h3>' + srcBadge +
      '<span class="aside" style="display:inline-flex;align-items:center;gap:4px">帳面 vs 逐時' + infoTip("paperVsCfe") + "</span>" +
      '<label class="cfe-selwrap">檢視 <select id="cfe-cust" class="cfe-select">' + opts + "</select></label></div>" +
      '<div id="cfe-chart-wrap"></div><div id="cfe-legend"></div>' +
      cfeConcept() + "</section>";
    // 風光增益欄只在投組有太陽能時出現(系統級增益會被沒簽光電的大客戶稀釋,
    // 逐客戶才看得出誰真的受惠)。
    var showUplift = r.uplift_pt != null;
    var rows = r.customers.slice().sort(function (a, b) {
      return (b.paper_re_percent - b.cfe_percent) - (a.paper_re_percent - a.cfe_percent);
    }).map(function (c) {
      var g = Math.max(0, c.paper_re_percent - c.cfe_percent);
      var upCell = c.uplift_pt > 0.005
        ? '<span class="pos" title="只風電 ' + pct(c.wind_only_cfe_percent) + '%">+' + pct(c.uplift_pt) + " pt</span>"
        : '<span class="u">–</span>';
      return '<tr data-cust="' + c.customer_id + '"><td><span class="code">' + esc(c.name) + "</span></td>" +
        "<td>" + esc(c.industry || "–") + "</td>" +
        '<td class="num">' + pct(c.paper_re_percent) + "%</td>" +
        '<td class="num" style="font-weight:700">' + pct(c.cfe_percent) + "%</td>" +
        '<td class="num">' + (g > 0.05 ? '<span class="neg">−' + pct(g) + "</span>" : '<span class="u">–</span>') + "</td>" +
        (showUplift ? '<td class="num">' + upCell + "</td>" : "") +
        "<td>" + cfeGapBar(c.cfe_percent, c.paper_re_percent) + "</td></tr>";
    }).join("");
    var table = '<section class="card"><div class="hd"><h3>各客戶 · 帳面 vs 逐時</h3><span class="aside">按時間錯配排序 · 點列查看該客戶</span></div>' +
      '<div class="tablewrap"><table><thead><tr><th>客戶</th><th>產業</th><th>帳面 RE%</th><th>逐時 CFE%</th><th>時間錯配</th>' +
      (showUplift ? "<th>風光增益</th>" : "") + "<th>對比</th></tr></thead><tbody>" +
      rows + "</tbody></table></div></section>";
    var heat = r.heatmap ? cfeHeatmap(r.heatmap) : "";
    var note = '<div class="foot-note">' + iconInfo() + esc(r.note) +
      " CFE% ≤ 帳面 RE%,差距即時間錯配。示範資料。</div>";
    return kpis + uplift + chart + heat + table + note;
  }

  // 「只風電 X% → 風光 Y% → 風光＋儲 Z%」讀數；scope 為「全系統」或某一客戶。
  // 每一段各加一件事：太陽能、然後儲能。沒有的那一段自動略過。
  function upliftBar(scope, x) {
    // 兩段各自的存在與否互不隱含（太陽能看案場、儲能看電池），標籤與說明文案
    // 必須照這兩個布林值決定，不能用「陣列長度」猜——猜會在只有其中一段時講錯話。
    var hasSolar = x.wind_only_cfe_percent != null;
    var hasStorage = x.storage_uplift_pt != null;
    var segs = [];
    if (hasSolar) segs.push({ lab: "只風電", v: x.wind_only_cfe_percent });
    if (hasStorage) {
      // no_storage_cfe_percent 是「加儲能之前」那一刻的 CFE：投組有光電時它就是
      // 風光合計、沒有光電時它其實就等於只風電——標籤不能寫死「風光」。
      segs.push({ lab: hasSolar ? "風光" : "只風電", v: x.no_storage_cfe_percent });
    }
    var finalLab = hasStorage
      ? (hasSolar ? "風光＋儲" : "加上儲能")
      : (hasSolar ? "風光" : "逐時 CFE");
    segs.push({ lab: finalLab, v: x.cfe_percent });
    if (segs.length < 2) {
      return '<div class="uplift flat">' + iconInfo() +
        '<span class="up-txt">' + esc(scope) + " 未簽太陽能合約、也沒有儲能，逐時 CFE 不受這兩者影響</span>" +
        infoTip("windSolar") + "</div>";
    }
    var txt = segs.map(function (s, i) {
      return (i ? " → " : "") + esc(s.lab) + " <b>" + pct(s.v) + "%</b>";
    }).join("");
    var pills = "";
    [
      { pt: x.uplift_pt, why: "太陽能" },
      { pt: x.storage_uplift_pt, why: "儲能" },
    ].forEach(function (u) {
      if (u.pt == null) return;
      pills += '<span class="up-pt ' + (u.pt > 0 ? "pos" : "") + '" title="' + u.why + '帶來的增益">' +
        (u.pt > 0 ? "+" : "") + pct(u.pt) + " pt</span>";
    });
    var why = hasStorage
      ? (hasSolar ? "正午 bell 補白天缺口，電池再把多餘的挪到早晚" : "電池把外溢挪到缺口時段，逐時 CFE 因此上升")
      : "太陽能正午 bell 補上風電白天的缺口";
    return '<div class="uplift">' + iconInfo() +
      '<span class="up-scope">' + esc(scope) + "</span>" +
      '<span class="up-txt">' + txt + "</span>" + pills +
      '<span class="up-why">' + why + "</span>" +
      (hasStorage ? infoTip("storage") : infoTip("windSolar")) + "</div>";
  }

  function cfeHeatmap(hm) {
    var days = hm.days || [], vals = hm.values || [];
    // green alpha ∝ CFE%; theme-aware (low = faint over card, high = solid green)
    function cell(v) {
      var t = Math.max(0, Math.min(1, (v || 0) / 100));
      var a = (0.06 + 0.9 * t).toFixed(3);
      return '<i style="background:rgba(47,162,77,' + a + ')" title="CFE ' + pct(v, 0) + '%"></i>';
    }
    function dlab(iso) { var p = (iso || "").split("-"); return p.length === 3 ? (+p[1]) + "/" + (+p[2]) : iso; }
    var hours = "";
    for (var h = 0; h < 24; h++) hours += "<span>" + (h % 6 === 0 ? (h < 10 ? "0" + h : h) : "") + "</span>";
    var rows = "";
    for (var d = 0; d < vals.length; d++) {
      var cells = vals[d].map(cell).join("");
      rows += '<div class="heat-row"><span class="heat-daylab">' + dlab(days[d]) + '</span><div class="heat-cells">' + cells + "</div></div>";
    }
    return '<section class="card"><div class="hd"><h3>時×日 CFE 熱力圖</h3>' +
      '<span class="aside">每格＝該日該小時的逐時 CFE%(綠色越深越高)</span></div>' +
      '<div class="heatwrap"><div class="heat">' +
      '<div class="heat-row heat-hdr"><span class="heat-daylab"></span><div class="heat-hours">' + hours + "</div></div>" +
      rows + "</div></div>" +
      '<div class="heat-lg"><span>低</span><i class="heat-grad"></i><span>高 CFE%</span>' +
      '<span class="cfe-hint">哪些日子／時段長期匹配不足,一眼看出(夜間偏綠、白天偏淡)</span></div></section>';
  }

  function cfeChart(gen, con, matched, mode, solar, discharge) {
    var H = (matched || con).length, W = 760, Ht = 232, L = 16, R = 12, T = 16, B = 24;
    var pw = W - L - R, ph = Ht - T - B;
    var ymax = 1, all = [con, matched].concat(gen ? [gen] : []);
    all.forEach(function (a) { a.forEach(function (v) { if (v > ymax) ymax = v; }); });
    ymax *= 1.08;
    var X = function (i) { return L + (H <= 1 ? 0 : i / (H - 1) * pw); };
    var Y = function (v) { return T + ph - v / ymax * ph; };
    function area(a) {
      var d = "M" + X(0).toFixed(1) + " " + Y(0).toFixed(1);
      for (var i = 0; i < H; i++) d += " L" + X(i).toFixed(1) + " " + Y(a[i]).toFixed(1);
      return d + " L" + X(H - 1).toFixed(1) + " " + Y(0).toFixed(1) + " Z";
    }
    function line(a) {
      var d = "M" + X(0).toFixed(1) + " " + Y(a[0]).toFixed(1);
      for (var i = 1; i < H; i++) d += " L" + X(i).toFixed(1) + " " + Y(a[i]).toFixed(1);
      return d;
    }
    // 兩條曲線之間的帶狀區域(上緣往前、下緣往回)——風光堆疊用。
    function band(lower, upper) {
      var d = "M" + X(0).toFixed(1) + " " + Y(lower[0]).toFixed(1);
      for (var i = 0; i < H; i++) d += " L" + X(i).toFixed(1) + " " + Y(upper[i]).toFixed(1);
      for (var j = H - 1; j >= 0; j--) d += " L" + X(j).toFixed(1) + " " + Y(lower[j]).toFixed(1);
      return d + " Z";
    }
    var grid = "";
    [0, 6, 12, 18, 23].forEach(function (h) {
      grid += '<line x1="' + X(h).toFixed(1) + '" y1="' + T + '" x2="' + X(h).toFixed(1) + '" y2="' + (T + ph) + '" class="cfe-grid"/>' +
        '<text x="' + X(h).toFixed(1) + '" y="' + (Ht - 6) + '" class="cfe-xtick">' + (h < 10 ? "0" + h : h) + ":00</text>";
    });
    grid += '<line x1="' + L + '" y1="' + (T + ph) + '" x2="' + (W - R) + '" y2="' + (T + ph) + '" class="cfe-axis"/>';
    // 有光電時,把太陽能那層疊在最上面:虛線=只風電、實線=風光合計,
    // 中間那條琥珀色帶就是太陽能補進來的量(壓在綠色匹配區之上才看得見)。
    var stack = "";
    if (gen && solar) {
      var wind = gen.map(function (v, i) { return Math.max(0, v - (solar[i] || 0)); });
      stack = '<path d="' + band(wind, gen) + '" class="cfe-solar"/>' +
        '<path d="' + line(wind) + '" class="cfe-wind"/>';
    }
    // 儲能放電的那一段本來就算在 matched 裡；用斜線帶標出「這一層來自電池」。
    var batt = "";
    if (discharge && discharge.some(function (v) { return v > 0; })) {
      var floor = matched.map(function (m, i) { return Math.max(0, m - (discharge[i] || 0)); });
      batt = '<path d="' + band(floor, matched) + '" class="cfe-batt"/>';
    }
    var paths = '<path d="' + area(con) + '" class="cfe-demand"/>' +
      '<path d="' + area(matched) + '" class="cfe-match"/>' + batt + stack +
      (gen ? '<path d="' + line(gen) + '" class="cfe-gen"/>' : "");
    return '<div class="cfe-chart-box"><svg viewBox="0 0 ' + W + " " + Ht + '" role="img" aria-label="24 小時供需匹配圖">' +
      '<defs><pattern id="cfeBattHatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">' +
      '<line x1="0" y1="0" x2="0" y2="6" class="cfe-batt-line"/></pattern></defs>' +
      grid + paths + "</svg></div>";
  }

  // SOC 走勢條：獨立一條、自己的尺度（與發電/用電量級差很多，不併軸以免誤讀）。
  function socStrip(soc) {
    if (!soc || !soc.some(function (v) { return v > 0; })) return "";
    var H = soc.length, W = 760, Ht = 64, L = 16, R = 12, T = 8, B = 14;
    var pw = W - L - R, ph = Ht - T - B;
    var ymax = Math.max.apply(null, soc) * 1.1 || 1;
    var X = function (i) { return L + (H <= 1 ? 0 : i / (H - 1) * pw); };
    var Y = function (v) { return T + ph - v / ymax * ph; };
    var d = "M" + X(0).toFixed(1) + " " + Y(0).toFixed(1);
    for (var i = 0; i < H; i++) d += " L" + X(i).toFixed(1) + " " + Y(soc[i]).toFixed(1);
    d += " L" + X(H - 1).toFixed(1) + " " + Y(0).toFixed(1) + " Z";
    return '<div class="soc-box"><div class="soc-lab">電池 SOC<small>MWh · 日均</small></div>' +
      '<svg viewBox="0 0 ' + W + " " + Ht + '" role="img" aria-label="電池 SOC 走勢">' +
      '<path d="' + d + '" class="soc-area"/>' +
      '<line x1="' + L + '" y1="' + (T + ph) + '" x2="' + (W - R) + '" y2="' + (T + ph) + '" class="cfe-axis"/>' +
      "</svg></div>";
  }

  function cfeLegend(withGen, withSolar, withBatt) {
    return '<div class="cfe-lg">' +
      '<span><i class="sw" style="background:var(--good)"></i>已匹配（重疊才算）</span>' +
      '<span><i class="sw" style="background:var(--faint);opacity:.35"></i>缺口（需灰電補足）</span>' +
      (withGen ? '<span><i class="ln"></i>' + (withSolar ? "風光合計發電" : "風電發電") + "（超出用電即外溢）</span>" : "") +
      (withSolar ? '<span><i class="ln ln-wind"></i>只風電</span><span><i class="sw sw-solar"></i>太陽能補上的部分</span>' : "") +
      (withBatt ? '<span><i class="sw sw-batt"></i>儲能放電</span>' : "") +
      '<span class="cfe-hint">' + (withGen
        ? (withBatt ? "斜線那層是電池放出來的電——原本會外溢，被挪到缺口時段" : (withSolar ? "午間那條琥珀色帶就是太陽能填進風電的白天缺口（風光互補）" : "綠色越貼齊用電輪廓，時間匹配越好"))
        : "此客戶：綠色＝已匹配、上方灰色＝該時段仍需灰電") + "</span></div>";
  }

  function cfeConcept() {
    return '<details class="concept"><summary>什麼是逐時（24/7 CFE）匹配？<span>點開說明</span></summary>' +
      '<div class="concept-body">' +
      "<b>帳面 RE%</b> 用月／年總量淨額：只要期間買的綠電總量 ≥ 用電就算 100%，不管時間對不對得上。<br>" +
      "<b>逐時 CFE%</b> 只算「同一小時內發電與用電<b>重疊</b>」的部分——發電時沒人用（外溢）不算、用電時沒風（缺口）也不算。CFE% = Σ 每小時 min(發電, 用電) ÷ Σ 用電。<br>" +
      "兩者差距就是<b>時間錯配</b>，也正是 24/7 無碳能源（如 Google）追求的真實對時。" +
      '<span class="concept-note">逐時曲線為典型日型建模（半模擬）：風電夜強日弱、用電依產業別日型，Σ逐時＝原月量。接真實 15 分鐘資料後原地替換。</span>' +
      "</div></details>";
  }

  function cfeGapBar(cfe, paper) {
    var c = Math.max(0, Math.min(100, cfe || 0));
    var p = Math.max(c, Math.min(100, paper || 0));
    return '<span class="gapbar" title="逐時 ' + pct(cfe) + "% / 帳面 " + pct(paper) + '%">' +
      '<i class="p" style="width:' + p.toFixed(0) + '%"></i><i class="c" style="width:' + c.toFixed(0) + '%"></i></span>';
  }

  function wireCfe(r) {
    var sel = document.getElementById("cfe-cust");
    var wrap = document.getElementById("cfe-chart-wrap");
    var lg = document.getElementById("cfe-legend");
    var upBox = document.getElementById("cfe-uplift");
    function draw() {
      var v = sel.value;
      if (v === "__all") {
        wrap.innerHTML = cfeChart(r.generation_by_hour, r.consumption_by_hour, r.matched_by_hour, "all", r.solar_generation_by_hour, r.discharged_by_hour) + socStrip(r.soc_by_hour);
        lg.innerHTML = cfeLegend(true, !!r.solar_generation_by_hour, !!r.discharged_by_hour);
        if (upBox) upBox.innerHTML = upliftBar("全系統", r);
      } else {
        var c = null;
        r.customers.forEach(function (x) { if (String(x.customer_id) === v) c = x; });
        if (!c) return;
        var loadArr = c.matched_by_hour.map(function (m, i) { return m + c.shortfall_by_hour[i]; });
        wrap.innerHTML = cfeChart(null, loadArr, c.matched_by_hour, "cust", null, c.discharged_by_hour) + socStrip(c.soc_by_hour);
        lg.innerHTML = cfeLegend(false, false, !!c.discharged_by_hour);
        if (upBox) upBox.innerHTML = upliftBar(c.name, c);
      }
    }
    if (sel) sel.addEventListener("change", draw);
    view.querySelectorAll("tr[data-cust]").forEach(function (tr) {
      tr.style.cursor = "pointer";
      tr.addEventListener("click", function () {
        if (!sel) return;
        sel.value = tr.getAttribute("data-cust");
        draw();
        wrap.scrollIntoView({ block: "center", behavior: "smooth" });
      });
    });
    draw();
  }

  // ---------- flagship: 最佳化評估 ----------
  function renderEvaluate() {
    crumb.textContent = "售電評估";
    view.innerHTML =
      '<div class="pagehead"><div class="title"><span class="bar"></span><h1>售電評估</h1></div>' +
      '<div class="meta"><span>對選定用電戶跑最佳化媒合,產出雙面經濟評估與時段別達成。</span></div></div>' +
      '<form class="formcard" id="evalForm"><div class="formgrid">' +
      '<div class="field"><label>用電戶<span class="req">*</span></label><select id="f-customer" required><option value="">載入中…</option></select></div>' +
      '<div class="field"><label>期間 (YYYY-MM)</label><input id="f-period" class="num" value="' + getPeriod() + '" placeholder="2024-01"></div>' +
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
      if (list[0]) {
        reTarget.value = pct(list[0].re_target_percent, 0);
        // auto-run for the first customer so the flagship page isn't empty on arrival
        runEvaluation(list[0].id, list[0], document.getElementById("f-period").value.trim(), 0, 0, null, null);
      }
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

  // 三時段供需匹配圖:每段一根長條,高度=用電,綠色=已分配綠電、灰色=缺口(需灰電)
  function slotMatchViz(rows) {
    if (!rows || !rows.length) return "";
    var ord = { peak: 0, half_peak: 1, off_peak: 2 };
    var slots = rows.slice().sort(function (a, b) { return (ord[a.slot] || 0) - (ord[b.slot] || 0); });
    var maxC = Math.max.apply(null, slots.map(function (s) { return s.consumption_mwh || 0; }).concat([1]));
    var W = 560, H = 210, padT = 22, padB = 46, bw = 104, gapW = 56;
    var left = (W - (bw * slots.length + gapW * (slots.length - 1))) / 2;
    var base = H - padB, top = padT;
    var yv = function (v) { return base - (base - top) * (v / maxC); };
    var defs = "", body = "";
    slots.forEach(function (s, i) {
      var x = left + i * (bw + gapW);
      var cy = yv(s.consumption_mwh || 0), ay = yv(s.allocated_mwh || 0);
      var re = Math.max(0, s.re_percent || 0);
      defs += '<clipPath id="scv' + i + '"><rect x="' + x + '" y="' + cy + '" width="' + bw + '" height="' + (base - cy) + '" rx="8"/></clipPath>';
      body += '<g clip-path="url(#scv' + i + ')">' +
        '<rect x="' + x + '" y="' + cy + '" width="' + bw + '" height="' + (base - cy) + '" fill="var(--faint)" fill-opacity=".22"/>' +
        '<rect x="' + x + '" y="' + ay + '" width="' + bw + '" height="' + (base - ay) + '" fill="var(--good)"/></g>';
      // 缺口分隔線
      if (s.allocated_mwh < s.consumption_mwh - 0.5)
        body += '<line x1="' + x + '" y1="' + ay + '" x2="' + (x + bw) + '" y2="' + ay + '" stroke="var(--good)" stroke-width="1.5" opacity=".5"/>';
      body += '<text x="' + (x + bw / 2) + '" y="' + (cy - 8) + '" text-anchor="middle" style="font-size:15px;font-weight:800;fill:' + (re >= 60 ? "var(--good)" : re >= 40 ? "var(--warn)" : "var(--bad)") + '">' + pct(re, 0) + '%</text>' +
        '<text x="' + (x + bw / 2) + '" y="' + (base + 20) + '" text-anchor="middle" style="font-size:13px;font-weight:700;fill:var(--ink)">' + esc(slotName(s.slot)) + '</text>' +
        '<text x="' + (x + bw / 2) + '" y="' + (base + 37) + '" text-anchor="middle" style="font-size:11px;fill:var(--muted)">綠 ' + nfmt(s.allocated_mwh, 0) + ' / 用 ' + nfmt(s.consumption_mwh, 0) + '</text>';
    });
    return '<div class="slotviz"><svg viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="三時段供需匹配圖">' +
      '<defs>' + defs + '</defs>' + body + '</svg>' +
      '<div class="slotviz-lg"><span><i style="background:var(--good)"></i>已分配綠電</span>' +
      '<span><i style="background:var(--faint);opacity:.4"></i>缺口(需灰電補足)</span>' +
      '<span class="slotviz-hint">長條高=該時段用電;綠色越滿代表綠電越對得上該時段</span></div></div>';
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
      '四塊皆由<b style="color:var(--brand)">同一次逐時段 MILP</b>導出,數值一致;時段別為最優精確值(逐時段轉供 + 台電二次匹配)。</div>';

    // KPI strip
    html += '<div class="kpis">' +
      kpi("RE 達成率", pct(buyer.re_percent) + "<small>%</small>", "目標 " + pct(reTargetPct, 0) + "%", "hl") +
      kpi("售電端毛利", money(seller.gross_profit) + "<small>NTD</small>", "毛利率 " + pct(seller.gross_margin_percent, 2) + "%", "", seller.gross_profit >= 0 ? "up" : "down") +
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
      erowTotal("增加用電成本(綠電溢價)", signed(buyer.added_cost), "NTD", "prem", "addedCost") +
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
    html += '<section class="card"><div class="hd"><h3>時段別供需匹配</h3><span class="aside" style="color:var(--buyer)">台電時間電價 · 風電進來怎麼對上用電</span></div>' +
      slotMatchViz(r.slot_breakdown) +
      '<div class="tablewrap"><table>' +
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
      (surplus > 0.5 ? "尚差 <b>" + nfmt(surplus, 0) + " MWh</b> 因時段錯配無法媒合(離峰過剩發電對不上日間用電),RE 目標未達。" : "") +
      "月度加總會高估;逐時段最佳化才是真實達成。</div>";
    html += '<details class="concept"><summary>為什麼「逐時匹配」這麼重要?<span>概念示意 · 點開</span></summary>' +
      '<div class="concept-body">上面這張是<b>這家客戶的真實三時段資料</b>。若把一天攤成 24 小時看更直覺:' +
      '風電夜裡強、白天弱,跟用電對不上時,帳面上的綠電就有一部分「對不上時間」——這正是逐時最佳化要解決的。' +
      '<a href="https://goldenyolf.github.io/energy-matching-platform/" target="_blank" rel="noopener">看 24 小時互動示意 →</a>' +
      '<span class="concept-note">⚠ 互動示意為模型曲線、非本客戶實測;實際評估請以上方真實三時段為準。</span></div></details>';
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
  function erow(lab, val, u, valcls, style, tip) {
    return '<div class="row"><span class="lab">' + esc(lab) + (tip ? infoTip(tip) : "") + '</span><span class="val num ' + (valcls || "") + '"' + (style ? ' style="' + style + '"' : "") + ">" +
      val + (u ? '<span class="u">' + esc(u) + "</span>" : "") + "</span></div>";
  }
  function erowTotal(lab, val, u, valcls, tip) {
    return '<div class="row total"><span class="lab">' + esc(lab) + (tip ? infoTip(tip) : "") + '</span><span class="val num ' + (valcls || "") + '">' +
      val + (u ? '<span class="u">' + esc(u) + "</span>" : "") + "</span></div>";
  }
  function iconMoney() { return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 1v22M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>'; }
  function iconBolt() { return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M13 2 4 14h7l-1 8 9-12h-7z"/></svg>'; }
  function iconInfo() { return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="9"/><path d="M12 8h.01M11 12h1v4h1"/></svg>'; }
  function iconWarn() { return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 3l9 16H3z"/><path d="M12 10v4M12 17h.01"/></svg>'; }

  // ---------- 名詞說明 popover(點擊 ⓘ 跳出) ----------
  var INFO = {
    cf: {
      title: "容量因數 P50 / P90",
      html:
        "<p><b>容量因數（Capacity Factor）</b>＝實際發電量 ÷ 理論滿載發電量（裝置容量 × 8760h）。代表風場「相當於幾成時間在滿載發電」。台灣陸域風電約 28–35%、離岸約 40–50%。</p>" +
        "<p><b>P50</b>：期望值／中位數預估——長期而言約有 <b>50%</b> 機率達到或超過（半數年份更好、半數更差）。用作基準財務預估。</p>" +
        "<p><b>P90</b>：保守預估——約有 <b>90%</b> 機率達到或超過（只有一成的壞年份會低於它），數字比 P50 低，代表下行風險；銀行融資常要求以 P90 評估債務覆蓋。</p>" +
        '<p class="tip-eg">直覺：P50 是「一般年」，P90 是「差一點的年也至少有這麼多」。</p>',
    },
    expP50: {
      title: "預期 P50 發電（MWh）",
      html:
        "<p><b>預期年發電（P50）</b>＝ 裝置容量(MW) × 8760 小時 × 容量因數 P50(%)。</p>" +
        "<p>代表「一般風況年」的預估年發電量；表格右側的「<b>達成</b>」＝ 實際發電 ÷ 這個預期。</p>" +
        '<p class="tip-eg">若改用 P90 容量因數，得到的是保守年發電（數字較低）。</p>',
    },
    feedIn: {
      title: "躉售價（FIT）",
      html:
        "<p><b>躉售價（Feed-in Tariff）</b>＝再生能源躉購費率，台電依 20 年費率向案場「保證收購」每度電的價格。</p>" +
        "<p>在本平台，躉售價當作<b>案場的售電成本基準</b>（把電賣給企業客戶時，案場少賺的機會成本）；售電業毛利＝綠電售價 − 躉售成本。</p>" +
        '<p class="tip-eg">注意：這不是「轉供價」（轉供價是企業客戶付的價）。</p>',
    },
    addedCost: {
      title: "增加用電成本（綠電溢價）",
      html:
        "<p>＝客戶改用綠電後，比原本全部向台電買灰電<b>多付</b>的錢。</p>" +
        "<p>綠電（PPA）每度通常比灰電略貴，這個差額 × 綠電度數就是溢價；反映「為了達成 RE 目標付出的代價」。</p>" +
        '<p class="tip-eg">正值＝多付；若綠電比灰電便宜也可能為負（省錢）。</p>',
    },
    greyTopup: {
      title: "灰電補足（參考）",
      html:
        "<p>綠電不足以覆蓋全部用電時，剩餘用電仍向台電買「<b>灰電</b>」補足。</p>" +
        "<p>這欄是那部分灰電的用電成本（依尖/半/離峰 TOU 電價估算）。</p>" +
        '<p class="tip-eg">僅供參考、<b>不計入本結算單應付</b>——結算單只計綠電轉供。</p>',
    },
    retailerMargin: {
      title: "售電業毛利",
      html:
        "<p>售電業（本平台使用者）從轉供賺的<b>毛利</b>＝綠電轉供收入 − 向案場採購的躉售成本。</p>" +
        "<p>百分比＝毛利 ÷ 轉供收入。</p>" +
        '<p class="tip-eg">為毛利、非淨利——尚未計營運、台電輸配等其他費用。</p>',
    },
    paperVsCfe: {
      title: "帳面 RE% vs 逐時 CFE%",
      html:
        "<p><b>帳面 RE%</b>：以「月／年總量淨額」計——只要期間買的綠電總量 ≥ 用電就算 100%，不論時間對不對得上。</p>" +
        "<p><b>逐時 CFE%</b>：只有「同一小時內發電與用電<b>重疊</b>」的部分才算（24/7 CFE）；發電時沒人用、用電時沒風都不算。</p>" +
        '<p class="tip-eg">逐時 CFE% 通常低於帳面，差距＝時間錯配。更嚴的國際標準（如 Google 24/7）看的是逐時。</p>',
    },
    windSolar: {
      title: "風光互補",
      html:
        "<p>風電<b>夜強日弱</b>，但多數工業客戶白天用電最兇——中午因此出現缺口（熱力圖午間偏淡）。</p>" +
        "<p>太陽能剛好相反：<b>正午 bell 型</b>、夜間歸零。兩者疊在一起，發電輪廓更貼近用電輪廓 → <b>逐時 CFE% 上升、外溢下降</b>。</p>" +
        '<p class="tip-eg">上方「只風電 X% → 風光 Y%」就是同一批用電、把光電案場與其合約拿掉重算一次的對照；差額（pt）即互補帶來的增益。</p>',
    },
    contractCap: {
      title: "合約上限（年電量 vs 佔發電比例）",
      html:
        "<p>一紙 PPA 可以用兩種方式限制它最多能拿多少電：</p>" +
        "<p><b>年電量</b>（MWh/年）——談定的年度總量，再依<b>月別配比</b>攤到各月（沒設就平均 1/12）。<br>" +
        "<b>佔發電比例</b>（%）——拿該案場當期發電的固定比例，發多少就按比例分多少。</p>" +
        '<p class="tip-eg">兩者可以只設一種，也可以同時設；同時設時引擎取<b>較緊</b>的那個當上限。所以這一欄顯示的是這紙合約實際用的那一種，不是缺漏。</p>',
    },
    storage: {
      title: "儲能時間位移",
      html:
        "<p>逐時匹配的鐵律是<b>嚴格不跨小時</b>：發電時沒人用就是外溢、用電時沒電就是缺口，兩邊不能互抵。</p>" +
        "<p><b>儲能</b>是唯一能合法打破這條鐵律的東西——把外溢的綠電充進電池，等缺口出現再放出來。放電會有往返效率損耗（示範為 88%）。</p>" +
        '<p class="tip-eg">示範中電池可收任一案場的外溢（自家合約優先），屬<b>情境模擬</b>——實務上跨案場取電需另簽轉供合約。結算與 T-REC 尚未反映充放。</p>',
    },
    bindingConstraint: {
      title: "綁定約束（這個月被什麼卡住）",
      html:
        "<p>每個月的分配量都是三個上限取最小：<b>案場當月還剩多少電</b>、<b>客戶還有多少沒被綠電覆蓋的用電</b>、<b>合約自己的上限</b>。實際卡住的那一個,就是這個月的綁定約束。</p>" +
        "<p><b>合約上限</b>——客戶要得比合約允許的多。若案場同時還有餘電,就代表<b>有加購空間</b>。<br>" +
        "<b>案場供給</b>——案場的電被分光了。這時調高合約上限也拿不到更多,要看的是案場是否超賣、或本合約優先序是否排在後面。<br>" +
        "<b>客戶用電</b>——合約允許量高於客戶用得掉的量,多簽的部分是浪費;若合約帶 take-or-pay,還會產生保證量費。</p>" +
        '<p class="tip-eg">同時卡在兩個約束時,顯示較硬的那一個（案場供給 &gt; 客戶用電 &gt; 合約上限）。</p>',
    },
  };
  function infoTip(key) {
    return '<button type="button" class="infotip" data-tip="' + key + '" aria-label="說明">' + iconInfo() + "</button>";
  }
  var tipPop = null, tipKey = null;
  function closeTip() { if (tipPop) { tipPop.remove(); tipPop = null; tipKey = null; } }
  function openTip(btn) {
    var key = btn.getAttribute("data-tip"), info = INFO[key];
    if (!info) return;
    closeTip();
    var pop = document.createElement("div");
    pop.className = "tip-pop";
    pop.innerHTML = '<div class="tip-hd">' + esc(info.title) + '<button type="button" class="tip-x" aria-label="關閉">&times;</button></div><div class="tip-bd">' + info.html + "</div>";
    document.body.appendChild(pop);
    var r = btn.getBoundingClientRect();
    var pw = pop.offsetWidth, ph = pop.offsetHeight;
    var left = Math.min(Math.max(8, r.left + r.width / 2 - pw / 2), window.innerWidth - pw - 8);
    var top = r.bottom + 8;
    if (top + ph > window.innerHeight - 8) top = Math.max(8, r.top - ph - 8);
    pop.style.left = left + "px";
    pop.style.top = top + "px";
    pop.querySelector(".tip-x").onclick = closeTip;
    tipPop = pop; tipKey = key;
  }
  document.addEventListener("click", function (e) {
    var btn = e.target.closest ? e.target.closest(".infotip") : null;
    if (btn) {
      e.preventDefault(); e.stopPropagation();
      if (tipKey === btn.getAttribute("data-tip")) closeTip(); else openTip(btn);
      return;
    }
    if (tipPop && !(e.target.closest && e.target.closest(".tip-pop"))) closeTip();
  });
  window.addEventListener("resize", closeTip);
  window.addEventListener("scroll", closeTip, true);

  // ---------- theme toggle ----------
  document.getElementById("themeBtn").addEventListener("click", function () {
    var root = document.documentElement;
    var cur = root.getAttribute("data-theme");
    if (!cur) cur = matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    var next = cur === "dark" ? "light" : "dark";
    root.setAttribute("data-theme", next);
    try { localStorage.setItem("emp-theme", next); } catch (e) { /* ignore */ }
  });
  overlay.addEventListener("click", function (e) { if (e.target === overlay) hideModal(); });

  // ---------- help panel ----------
  var helpOverlay = document.getElementById("helpOverlay");
  function showHelp() { helpOverlay.classList.add("show"); }
  function hideHelp() { helpOverlay.classList.remove("show"); }
  // remember the period whenever any "*-period" input changes, so pages share it
  view.addEventListener("input", function (e) {
    if (e.target && /(^|-)period$/.test(e.target.id || "")) setPeriod(e.target.value.trim());
  });
  document.getElementById("helpBtn").addEventListener("click", showHelp);
  document.getElementById("helpClose").addEventListener("click", hideHelp);
  document.getElementById("helpOk").addEventListener("click", hideHelp);
  helpOverlay.addEventListener("click", function (e) { if (e.target === helpOverlay) hideHelp(); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") { hideHelp(); hideModal(); closeTip(); } });

  // ---------- 實體 CRUD(發電案場 / 企業客戶) ----------
  // 這兩個是「管理頁」,一律顯示新增/編輯/刪除。密碼保護暫時隱藏(之後再設計呈現);
  // 後端仍有 ADMIN_WRITE_TOKEN 寫入閘,設定後即需帶密碼(屆時再補密碼輸入 UI)。
  var editMode = true;
  var crudCache = { farm: {}, customer: {}, contract: {} };

  var FARM_FIELDS = [
    { key: "code", label: "案場代碼", createOnly: true, required: true, placeholder: "WF-XXX" },
    { key: "name", label: "名稱", required: true },
    { key: "operator_name", label: "營運商" },
    { key: "location", label: "場址" },
    { key: "installed_capacity_mw", label: "裝置容量 (MW)", type: "number", required: true },
    { key: "farm_type", label: "類型", type: "select", options: [["", "—"], ["offshore", "離岸"], ["onshore", "陸域"], ["solar", "太陽能"]] },
    { key: "capacity_factor_percent", label: "容量因數 P50 (%)", type: "number", min: 0, max: 100 },
    { key: "p90_capacity_factor_percent", label: "容量因數 P90 (%)", type: "number", min: 0, max: 100 },
    { key: "turbine_count", label: "風機數", type: "number", step: "1" },
    { key: "grid_connection_voltage", label: "並網電壓", placeholder: "161kV" },
    { key: "feed_in_price_per_kwh", label: "躉售價 (NTD/kWh)", type: "number" },
    { key: "commercial_operation_date", label: "商轉日", placeholder: "2024-01-01" },
    { key: "status", label: "狀態", type: "select", options: [["operational", "營運中"], ["under_construction", "建置中"], ["planning", "規劃中"], ["decommissioned", "除役"]] },
  ];
  var FARM_TYPE_LABEL = { offshore: "離岸", onshore: "陸域", solar: "太陽能" };
  var FARM_TYPE_PILL = { offshore: "info", solar: "warnp" };
  function farmTypeBadge(t) {
    if (!t) return "";
    return ' <span class="pill ' + (FARM_TYPE_PILL[t] || "neut") + '" style="height:19px;font-size:10.5px;padding:0 7px">' + esc(FARM_TYPE_LABEL[t] || t) + "</span>";
  }
  var CUST_FIELDS = [
    { key: "code", label: "客戶代碼", createOnly: true, required: true, placeholder: "CUST-XXX" },
    { key: "company_name", label: "公司名稱", required: true },
    { key: "industry", label: "產業" },
    { key: "annual_consumption_mwh", label: "總用電量 (MWh)", type: "number" },
    { key: "re_target_percent", label: "RE 目標 (%)", type: "number", min: 0, max: 100 },
    { key: "target_year", label: "目標年", type: "number", step: "1" },
  ];
  // 綠電合約:發電案場 / 用電端下拉選項於 renderContracts 時就地填入(保留參照)
  var contractFarmOpts = [];
  var contractCustOpts = [];
  var CONTRACT_STATUS = [["active", "生效中"], ["pending", "待生效"], ["expired", "已到期"], ["terminated", "已終止"]];
  // 風電季節曲線權重(冬高夏低);後端會正規化。前端只送平均分攤(null)或此曲線。
  var WIND_WEIGHTS = [1.35, 1.25, 1.05, 0.85, 0.70, 0.55, 0.55, 0.60, 0.85, 1.15, 1.30, 1.40];
  var SHARE_OPTS = [["flat", "平均分攤 (每月相同)"], ["wind", "風電季節曲線 (冬高夏低)"]];
  var CONTRACT_FIELDS = [
    { key: "contract_number", label: "合約編號", createOnly: true, required: true, placeholder: "PPA-2024-001" },
    { key: "wind_farm_id", label: "發電案場", type: "select", options: contractFarmOpts, required: true, createOnly: true },
    { key: "customer_id", label: "用電端 / 客戶", type: "select", options: contractCustOpts, required: true, createOnly: true },
    { key: "start_date", label: "起始日", type: "date", required: true, placeholder: "2024-01-01" },
    { key: "end_date", label: "結束日", type: "date", required: true, placeholder: "2033-12-31" },
    { key: "contracted_energy_mwh", label: "合約年電量 (MWh)", type: "number" },
    { key: "monthly_shares", label: "月別配比", type: "select", options: SHARE_OPTS },
    { key: "contracted_percentage", label: "合約比例 (%)", type: "number", min: 0, max: 100 },
    { key: "min_offtake_percent", label: "保證量 take-or-pay (% 月上限)", type: "number", min: 0, max: 100 },
    { key: "price_per_kwh", label: "轉供價格 (NTD/kWh)", type: "number" },
    { key: "price_escalation_percent", label: "價格年漲幅 CPI (%/年)", type: "number", min: 0, max: 100 },
    { key: "price_base_year", label: "漲幅基準年", type: "number", step: "1", placeholder: "2024" },
    { key: "priority", label: "優先序 (小=優先)", type: "number", step: "1" },
    { key: "status", label: "狀態", type: "select", options: CONTRACT_STATUS },
  ];
  // 台電時間電價方案(下拉)
  var TARIFF_PLANS = [["", "—"], ["lv_two_stage", "低壓-二段式時間電價"], ["lv_three_stage", "低壓-三段式時間電價"], ["hv_two_stage", "高壓-二段式時間電價"], ["hv_three_stage", "高壓-三段式時間電價"], ["ehv_two_stage", "特高壓-二段式時間電價"], ["ehv_three_stage", "特高壓-三段式時間電價"], ["batch_production", "批次生產時間電價"]];
  var TARIFF_LABEL = { lv_two_stage: "低壓-二段式", lv_three_stage: "低壓-三段式", hv_two_stage: "高壓-二段式", hv_three_stage: "高壓-三段式", ehv_two_stage: "特高壓-二段式", ehv_three_stage: "特高壓-三段式", batch_production: "批次生產" };
  var METER_FIELDS = [
    { key: "code", label: "電號", createOnly: true, required: true, placeholder: "04-95-4331-15-3" },
    { key: "name", label: "廠區 / 名稱", required: true },
    { key: "usage_name", label: "用電名稱" },
    { key: "contracted_capacity_kw", label: "契約容量 (kW)", type: "number" },
    { key: "tariff_type", label: "時間電價", type: "select", options: TARIFF_PLANS },
    { key: "re_target_percent", label: "RE 目標 (%)", type: "number", min: 0, max: 100 },
    { key: "load_data_type", label: "負載數據種類", placeholder: "年度用電量(15分鐘一筆)" },
    { key: "data_period", label: "數據區間", placeholder: "2023-01~2023-12" },
    { key: "peak_kwh", label: "尖峰 (kWh)", type: "number" },
    { key: "half_peak_kwh", label: "半尖峰 (kWh)", type: "number" },
    { key: "saturday_half_peak_kwh", label: "周六半尖峰 (kWh)", type: "number" },
    { key: "off_peak_kwh", label: "離峰 (kWh)", type: "number" },
    { key: "total_kwh", label: "總量 (kWh)", type: "number" },
  ];
  crudCache.meter = {};

  // 模擬一組合理的電號負載值(含周六半尖峰),供表單「模擬填入」用
  function simulateMeterValues() {
    var total = Math.round((0.5 + Math.random() * 4.5) * 1e6);
    var jit = function (base) { return Math.round(base * (0.9 + Math.random() * 0.2)); };
    var peak = jit(total * 0.14), half = jit(total * 0.40), sat = jit(total * 0.11);
    return {
      contracted_capacity_kw: Math.round(total / 8760 / 0.6),
      tariff_type: "hv_three_stage",
      load_data_type: "年度用電量(15分鐘一筆)",
      data_period: "2023-01~2023-12",
      peak_kwh: peak, half_peak_kwh: half, saturday_half_peak_kwh: sat,
      off_peak_kwh: Math.max(0, total - peak - half - sat), total_kwh: total,
    };
  }

  function entityAddBtn(kind, label, custId) {
    if (!editMode) return "";
    return '<button class="btn primary sm entity-add" data-kind="' + kind + '"' +
      (custId != null ? ' data-cust="' + custId + '"' : "") + ">+ " + esc(label) + "</button>";
  }
  // CSV 匯入:各類實體的欄位提示(第一欄為關鍵欄)
  var IMPORT_COLS = {
    farm: "code, name, installed_capacity_mw, operator_name, location, feed_in_price_per_kwh, commercial_operation_date, status",
    customer: "code, company_name, industry, annual_consumption_mwh, re_target_percent, target_year",
    contract: "contract_number, wind_farm_code, customer_code, start_date, end_date, contracted_energy_mwh, contracted_percentage, price_per_kwh, priority, status",
    meter: "customer_code, code, name, location, re_target_percent, annual_consumption_mwh",
  };
  var IMPORT_FN = {
    farm: function (f) { return api.importFarms(f); },
    customer: function (f) { return api.importCustomers(f); },
    contract: function (f) { return api.importContracts(f); },
    meter: function (f) { return api.importMeters(f); },
  };
  function importBtn(kind) {
    if (!editMode) return "";
    return '<button class="btn ghost sm entity-import" data-kind="' + kind + '">⇪ 匯入 CSV</button>';
  }
  function openImportModal(kind) {
    var ov = document.createElement("div");
    ov.className = "overlay show formov";
    ov.innerHTML = '<div class="formmodal"><div class="fm-hd"><h3>匯入' + esc(ENTITY_NAME[kind]) + ' CSV</h3><button class="fm-x" aria-label="關閉">&times;</button></div>' +
      '<form class="fm-body"><p class="fm-note">CSV 欄位(首行為標題,關鍵欄:<b>' + esc(IMPORT_COLS[kind].split(",")[0]) + '</b>):<br><code style="font-size:11px">' + esc(IMPORT_COLS[kind]) + '</code><br>已存在(代碼重複)者自動略過。</p>' +
      '<label class="fm-f"><span>選擇 CSV 檔 <i class="req">*</i></span><input type="file" name="file" accept=".csv,text/csv" required></label>' +
      '<div class="fm-err"></div><div class="fm-result"></div><div class="fm-act"><button type="button" class="btn ghost fm-cancel">取消</button><button type="submit" class="btn primary">匯入</button></div></form></div>';
    document.body.appendChild(ov);
    function close() { ov.remove(); }
    ov.querySelector(".fm-x").onclick = close;
    ov.querySelector(".fm-cancel").onclick = close;
    ov.addEventListener("click", function (e) { if (e.target === ov) close(); });
    ov.querySelector("form").addEventListener("submit", function (e) {
      e.preventDefault();
      var input = ov.querySelector('input[name="file"]');
      var file = input.files && input.files[0];
      var errEl = ov.querySelector(".fm-err"), resEl = ov.querySelector(".fm-result");
      errEl.textContent = ""; resEl.innerHTML = "";
      if (!file) { errEl.textContent = "請選擇檔案。"; return; }
      var btn = ov.querySelector('button[type="submit"]'); btn.disabled = true;
      IMPORT_FN[kind](file).then(function (r) {
        toast("已匯入 " + r.imported + " 筆" + ENTITY_NAME[kind]);
        var msg = "匯入 <b>" + r.imported + "</b> 筆,略過 " + (r.skipped || 0) + " 筆" + ((r.errors && r.errors.length) ? "," + r.errors.length + " 筆錯誤" : "") + "。";
        if (r.errors && r.errors.length) msg += '<div style="margin-top:6px;color:var(--bad);font-size:11.5px">' + r.errors.slice(0, 5).map(esc).join("<br>") + "</div>";
        resEl.innerHTML = msg;
        route();
        setTimeout(close, r.errors && r.errors.length ? 4000 : 1200);
      }).catch(function (err) { btn.disabled = false; errEl.textContent = writeErr(err); });
    });
    ov.querySelector('input[name="file"]').focus();
  }
  function rowActions(kind, id) {
    if (!editMode) return "";
    return '<td class="rowact"><button class="mini entity-edit" data-kind="' + kind + '" data-id="' + id + '">編輯</button>' +
      '<button class="mini danger entity-del" data-kind="' + kind + '" data-id="' + id + '">刪除</button></td>';
  }
  function writeErr(err) {
    if (err && err.status === 403) return "沒有編輯權限:此環境已啟用寫入密碼保護(ADMIN_WRITE_TOKEN)。";
    return String((err && err.message) || "").replace(/^\d+:\s*/, "") || "操作失敗";
  }
  function fmField(f, val) {
    var v = val == null ? "" : val;
    var lab = "<span>" + esc(f.label) + (f.required ? ' <i class="req">*</i>' : "") + "</span>";
    if (f.type === "select") {
      var opts = f.options.map(function (o) {
        return '<option value="' + o[0] + '"' + (String(o[0]) === String(v) ? " selected" : "") + ">" + esc(o[1]) + "</option>";
      }).join("");
      return '<label class="fm-f">' + lab + '<select name="' + f.key + '">' + opts + "</select></label>";
    }
    var attrs = 'name="' + f.key + '" type="' + (f.type || "text") + '"';
    if (f.type === "number") attrs += ' step="' + (f.step || "any") + '"' + (f.min != null ? ' min="' + f.min + '"' : "") + (f.max != null ? ' max="' + f.max + '"' : "");
    if (f.required) attrs += " required";
    if (f.placeholder) attrs += ' placeholder="' + esc(f.placeholder) + '"';
    return '<label class="fm-f">' + lab + "<input " + attrs + ' value="' + esc(v) + '"></label>';
  }
  function showFormModal(opts) {
    var ov = document.createElement("div");
    ov.className = "overlay show formov";
    var fieldsHtml = (opts.fields || []).map(function (f) { return fmField(f, (opts.values || {})[f.key]); }).join("");
    var tools = opts.simulate ? '<div class="fm-tools"><button type="button" class="btn ghost sm fm-sim">🎲 模擬填入</button></div>' : "";
    ov.innerHTML = '<div class="formmodal"><div class="fm-hd"><h3>' + esc(opts.title) + '</h3><button class="fm-x" aria-label="關閉">&times;</button></div>' +
      '<form class="fm-body">' + (opts.note ? '<p class="fm-note">' + opts.note + "</p>" : "") + tools + fieldsHtml +
      '<div class="fm-err"></div><div class="fm-act"><button type="button" class="btn ghost fm-cancel">取消</button>' +
      '<button type="submit" class="btn ' + (opts.danger ? "danger" : "primary") + '">' + esc(opts.submitLabel || "儲存") + "</button></div></form></div>";
    document.body.appendChild(ov);
    function close() { ov.remove(); }
    ov.querySelector(".fm-x").onclick = close;
    ov.querySelector(".fm-cancel").onclick = close;
    var simBtn = ov.querySelector(".fm-sim");
    if (simBtn) simBtn.onclick = function () {
      var vals = opts.simulate();
      Object.keys(vals).forEach(function (k) {
        var el = ov.querySelector('[name="' + k + '"]'); if (el) el.value = vals[k];
      });
    };
    ov.addEventListener("click", function (e) { if (e.target === ov) close(); });
    ov.querySelector("form").addEventListener("submit", function (e) {
      e.preventDefault();
      var vals = {};
      (opts.fields || []).forEach(function (f) {
        var el = ov.querySelector('[name="' + f.key + '"]'); if (!el) return;
        var v = el.value;
        if (f.type === "number") { v = v.trim() === "" ? null : parseFloat(v); }
        else { v = v.trim(); if (v === "") v = null; }
        // 空白欄位不送出:新增時套用後端預設(如優先序 100),編輯時保持原值不變。
        if (v !== null) vals[f.key] = v;
      });
      var errEl = ov.querySelector(".fm-err");
      var btn = ov.querySelector('button[type="submit"]'); btn.disabled = true;
      opts.onSubmit(vals, function (err) { btn.disabled = false; if (err) { errEl.textContent = err; } else { close(); } });
    });
    var first = ov.querySelector("input,select"); if (first) first.focus();
  }
  var ENTITY_NAME = { farm: "發電案場", customer: "企業客戶", meter: "電號", contract: "綠電合約" };
  var ENTITY_NOTE = { contract: "「合約年電量」與「合約比例」至少填一項;分配以兩者較嚴格者為準。" };
  var ENTITY_FIELDS = { farm: FARM_FIELDS, meter: METER_FIELDS, contract: CONTRACT_FIELDS, customer: CUST_FIELDS };
  function openEntityForm(kind, item, preset) {
    var cfg = ENTITY_FIELDS[kind] || CUST_FIELDS;
    var create = { farm: api.createFarm, customer: api.createCustomer, meter: api.createMeter, contract: api.createContract }[kind];
    var upd = { farm: api.updateFarm, customer: api.updateCustomer, meter: api.updateMeter, contract: api.updateContract }[kind];
    var fields = cfg.filter(function (f) { return !(item && f.createOnly); });
    // 月別配比:陣列 ↔ 下拉值("wind"/"flat")互轉,供表單顯示。
    var values = item ? Object.assign({}, item) : {};
    if (kind === "contract") values.monthly_shares = item && item.monthly_shares ? "wind" : "flat";
    showFormModal({
      title: (item ? "編輯" : "新增") + ENTITY_NAME[kind],
      fields: fields, values: values, submitLabel: item ? "儲存" : "新增",
      note: ENTITY_NOTE[kind],
      simulate: kind === "meter" ? simulateMeterValues : undefined,
      onSubmit: function (vals, done) {
        if (kind === "contract") vals.monthly_shares = vals.monthly_shares === "wind" ? WIND_WEIGHTS : null;
        if (preset) Object.keys(preset).forEach(function (k) { vals[k] = preset[k]; });
        var p = item ? upd(item.id, vals) : create(vals);
        p.then(function () { done(); toast((item ? "已儲存" : "已新增") + ENTITY_NAME[kind]); route(); })
          .catch(function (err) { done(writeErr(err)); });
      },
    });
  }
  function confirmDelete(kind, item) {
    var del = { farm: api.deleteFarm, customer: api.deleteCustomer, meter: api.deleteMeter, contract: api.deleteContract }[kind];
    var nm = esc(item.code || item.contract_number) + " " + esc(item.name || item.company_name || "");
    showFormModal({
      title: "刪除" + ENTITY_NAME[kind], fields: [], danger: true, submitLabel: "確定刪除",
      note: "確定要刪除「<b>" + nm + "</b>」嗎?此動作無法復原;若仍有關聯資料(合約/發電/用電)會被擋下。",
      onSubmit: function (_vals, done) {
        del(item.id).then(function () { done(); toast("已刪除" + ENTITY_NAME[kind]); route(); })
          .catch(function (err) { done(writeErr(err)); });
      },
    });
  }
  // delegated CRUD actions
  view.addEventListener("click", function (e) {
    var el = e.target.closest(".entity-add,.entity-edit,.entity-del,.entity-import"); if (!el) return;
    var kind = el.getAttribute("data-kind");
    if (el.classList.contains("entity-import")) { openImportModal(kind); return; }
    if (el.classList.contains("entity-add")) {
      var preset = kind === "meter" ? { customer_id: parseInt(el.getAttribute("data-cust"), 10) } : null;
      openEntityForm(kind, null, preset); return;
    }
    var item = crudCache[kind][el.getAttribute("data-id")];
    if (!item) return;
    if (el.classList.contains("entity-edit")) openEntityForm(kind, item);
    else confirmDelete(kind, item);
  });
  // ---------- boot ----------
  route();
})();
