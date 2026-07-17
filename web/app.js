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
    var h = (location.hash || "#/evaluate").replace(/^#\/?/, "");
    var parts = h.split("?");
    var route = parts[0] || "evaluate";
    var params = {};
    (parts[1] || "").split("&").forEach(function (kv) {
      if (!kv) return; var p = kv.split("="); params[decodeURIComponent(p[0])] = decodeURIComponent(p[1] || "");
    });
    return { route: route, params: params };
  }
  function route() {
    var r = parseHash();
    if (r.route === "farms") { renderFarms(); setActive("farms"); }
    else if (r.route === "soon") { renderSoon(r.params.page); setActive("soon"); }
    else { renderEvaluate(); setActive("evaluate"); }
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
      '<div class="field"><label>RE 目標</label><input id="f-retarget" class="num" value="–" readonly><span class="hint">取自資料設定</span></div>' +
      '<div class="field"><label>綠電轉供價</label><input value="依各合約設定" readonly><span class="hint">取自合約(v1 唯讀)</span></div>' +
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
      if (list[0]) reTarget.value = pct(list[0].re_target_percent, 0) + " %";
    }).catch(function (err) {
      sel.innerHTML = '<option value="">無法載入用電戶</option>';
      document.getElementById("result").innerHTML = errbox("載入用電戶", err);
    });
    sel.addEventListener("change", function () {
      var c = custMap[sel.value];
      reTarget.value = c ? pct(c.re_target_percent, 0) + " %" : "–";
    });

    document.getElementById("evalForm").addEventListener("submit", function (e) {
      e.preventDefault();
      var customerId = parseInt(sel.value, 10);
      if (!customerId) { sel.focus(); return; }
      var period = document.getElementById("f-period").value.trim();
      var minPct = parseFloat(document.getElementById("f-minpct").value) || 0;
      var minSites = parseInt(document.getElementById("f-minsites").value, 10) || 0;
      runEvaluation(customerId, custMap[customerId], period, minSites, minPct);
    });
  }

  function farmsReady() {
    if (farmsCache) return Promise.resolve(farmsCache);
    return api.windFarms().then(function (list) {
      farmsCache = {}; list.forEach(function (f) { farmsCache[f.id] = f; }); return farmsCache;
    });
  }

  function runEvaluation(customerId, customer, period, minSites, minPct) {
    showModal("正在求解最佳綠電組合…");
    var result = document.getElementById("result");
    Promise.all([
      api.optimize(period, minSites, minPct),
      api.evaluation(customerId, period, period),
      api.slots(period),
      farmsReady(),
    ]).then(function (r) {
      renderResult(result, {
        optimize: r[0], evaluation: r[1], slots: r[2],
        customerId: customerId, customer: customer, period: period,
      });
    }).catch(function (err) {
      result.innerHTML = errbox("執行評估", err);
    }).then(function () {
      // keep the modal briefly so the animation reads as intentional
      setTimeout(hideModal, reduce ? 0 : 350);
    });
  }

  function errbox(where, err) {
    var msg = (err && err.message) || "未知錯誤";
    return '<div class="errbox"><h3>' + esc(where) + "失敗</h3><p>" + esc(msg) +
      "</p><button class=\"btn ghost\" onclick=\"location.reload()\">重新載入</button></div>";
  }

  function renderResult(root, d) {
    var opt = d.optimize, ev = d.evaluation, sl = d.slots;
    var focus = d.customerId;
    var seller = ev.seller, buyer = ev.buyer;
    var target = (opt.customer_targets || []).filter(function (t) { return t.customer_id === focus; })[0] || {};
    var reTargetPct = d.customer ? d.customer.re_target_percent : 0;
    var allocs = (opt.allocations || []).filter(function (a) { return a.customer_id === focus && a.allocated_mwh > 0; });
    var totalAlloc = allocs.reduce(function (s, a) { return s + a.allocated_mwh; }, 0);
    var sellPrice = buyer.green_mwh > 0 ? seller.sales_revenue / (buyer.green_mwh * 1000) : 0;
    var okPill = opt.solver_status === "Optimal";
    var seasonLabel = sl.season === "summer" ? "夏月" : "非夏月";

    // per-farm aggregate for this customer
    var byFarm = {};
    allocs.forEach(function (a) {
      var k = a.wind_farm_id;
      if (!byFarm[k]) byFarm[k] = { id: k, alloc: 0, contracts: [] };
      byFarm[k].alloc += a.allocated_mwh;
      byFarm[k].contracts.push(a);
    });
    var farmRows = Object.keys(byFarm).map(function (k) { return byFarm[k]; })
      .sort(function (a, b) { return b.alloc - a.alloc; });

    var html = "";
    // page head
    html += '<div class="pagehead" style="margin-top:22px"><div><div class="title"><span class="bar"></span><h1>評估結果</h1>' +
      '<span class="pill ' + (okPill ? "ok" : "warnp") + '"><span class="dot"></span>求解狀態 ' + esc(opt.solver_status) + "</span></div>" +
      '<div class="meta"><span>用電戶 <b>' + esc(ev.company_name) + "</b></span>" +
      "<span>期間 <b>" + esc(d.period) + " · " + seasonLabel + "</b></span>" +
      "<span>約束 <b>最小分配 " + pct(opt.min_site_allocation_percent, 0) + "% · 最少 " + opt.min_sites_per_customer + " 場</b></span></div></div>" +
      '<div class="headactions"><button class="btn primary" id="rerun2"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M20 11a8 8 0 1 0-2.3 5.7M20 5v6h-6"/></svg>再次評估</button></div></div>';

    // integration note — v1 stitches three complementary engines client-side
    html += '<div style="margin:-4px 0 16px;font-size:12px;color:var(--muted);line-height:1.6">本頁整合三種計算:' +
      '<b style="color:var(--seller)">雙面經濟</b> 為 P2 售電評估(優先序引擎);' +
      '<b style="color:var(--brand)">配對明細</b> 為 P3 最佳化(受下方約束);' +
      '<b style="color:var(--buyer)">時段別</b> 為 P4a。三者為互補視角,數值來自不同引擎。</div>';

    // KPI strip
    html += '<div class="kpis">' +
      kpi("RE 達成率", pct(buyer.re_percent) + "<small>%</small>", "目標 " + pct(reTargetPct, 0) + "%", "hl") +
      kpi("售電端毛利", "NT$ " + abbr(seller.gross_profit), "毛利率 " + pct(seller.gross_margin_percent, 2) + "%", "", seller.gross_profit >= 0 ? "up" : "down") +
      kpi("配對案場", (target.sites_used || farmRows.length) + "<small>場</small>", "綠電轉供率 " + pct(buyer.re_percent) + "%") +
      kpi("綠電轉供量", nfmt(buyer.green_mwh, 0) + "<small>MWh</small>", "灰電 " + nfmt(buyer.grey_mwh, 0) + " MWh") +
      kpi("售電均價", price(sellPrice), "NTD / kWh") +
      kpi("用電均價", price(buyer.avg_price_per_kwh), "含綠+灰電") +
      "</div>";

    // body grid
    html += '<div class="grid"><div class="stack">';

    // seller card
    html += '<section class="card side-seller"><div class="hd"><span class="ic">' + iconMoney() + "</span>" +
      "<h3>售電端 · 發電業收益</h3><span class=\"aside\">綠電轉供均價 " + price(sellPrice) + " NTD/kWh</span></div>";
    if (ev.used_default_feed_in_price) html += '<div class="note">部分風場未填收購價,已用預設值估算。</div>';
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
    html += '<section class="card"><div class="hd"><h3>發電端分配概況</h3><span class="aside">P3 最佳化 · 此用電戶</span></div>' +
      '<div class="tablewrap"><table><thead><tr><th>配對案場</th><th>綠電售電量 (MWh)</th><th>綠電轉供率</th><th>預估營收 (NTD)</th></tr></thead><tbody>' +
      "<tr><td>" + farmRows.length + " 場</td><td class=\"num\">" + nfmt(buyer.green_mwh, 0) + "</td><td class=\"num pos\">" + pct(buyer.re_percent) + "%</td><td class=\"num\">" + money(seller.sales_revenue) + "</td></tr>" +
      "</tbody></table></div></section>";

    // 逐案場明細
    html += '<section class="card"><div class="hd"><h3>匹配案場細節</h3><span class="aside">P3 最佳化 · ' + farmRows.length + " 場</span></div><div class=\"tablewrap\"><table>" +
      "<thead><tr><th>案場</th><th>已分配 (MWh)</th><th>分配比例</th><th>分配原因</th></tr></thead><tbody>";
    if (!farmRows.length) {
      html += '<tr><td class="empty" colspan="4">此期間該用電戶無綠電分配</td></tr>';
    } else {
      farmRows.forEach(function (f) {
        var fn = farmName(f.id);
        var share = totalAlloc > 0 ? (f.alloc / totalAlloc * 100) : 0;
        var reason = (f.contracts[0] && f.contracts[0].reason) || "";
        html += "<tr><td><span class=\"code\">" + esc(fn.code) + "</span> " + esc(fn.name) + "</td>" +
          "<td class=\"num\">" + nfmt(f.alloc, 1) + "</td>" +
          "<td><span class=\"barcell num\">" + pct(share, 0) + "%<span class=\"minibar\"><i style=\"width:" + share.toFixed(0) + "%\"></i></span></span></td>" +
          "<td style=\"text-align:left;color:var(--muted);font-size:12px;white-space:normal;max-width:280px\">" + esc(reason) + "</td></tr>";
      });
    }
    html += "</tbody></table></div></section>";

    // 時段別
    var slotLabel = { peak: ["尖峰", "s-peak"], half_peak: ["半尖峰", "s-half"], off_peak: ["離峰", "s-off"] };
    html += '<section class="card"><div class="hd"><h3>時段別達成</h3><span class="aside" style="color:var(--buyer)">P4a · 台電時間電價</span></div><div class="tablewrap"><table>' +
      "<thead><tr><th>時段</th><th>灰電價</th><th>用電量 (MWh)</th><th>綠電分配 (MWh)</th><th>時段 RE</th></tr></thead><tbody>";
    var peakRe = null;
    (sl.slot_breakdown || []).forEach(function (b) {
      var cs = (b.customer_summaries || []).filter(function (c) { return c.customer_id === focus; })[0] || { consumption_mwh: 0, allocated_mwh: 0, achieved_re_percent: 0 };
      var lbl = slotLabel[b.slot] || [b.slot, "s-half"];
      if (b.slot === "peak") peakRe = cs.achieved_re_percent;
      var w = Math.max(0, Math.min(100, cs.achieved_re_percent || 0));
      html += "<tr><td><span class=\"tag-slot " + lbl[1] + "\">" + esc(lbl[0]) + "</span></td>" +
        "<td class=\"num\">" + price(b.grey_price_per_kwh).replace(/0+$/, "").replace(/\.$/, ".0") + "</td>" +
        "<td class=\"num\">" + nfmt(cs.consumption_mwh, 0) + "</td>" +
        "<td class=\"num\">" + nfmt(cs.allocated_mwh, 0) + "</td>" +
        "<td class=\"num\">" + pct(cs.achieved_re_percent) + "%<span class=\"re-bar\"><i style=\"width:" + w.toFixed(0) + "%\"></i></span></td></tr>";
    });
    html += "</tbody></table></div>";
    if (peakRe != null) html += '<div class="slotnote">風電離峰(夜間)發電較高、用電尖峰在日間 → <b>尖峰 RE 僅 ' + pct(peakRe) + "%</b>。月度加總會高估;逐時段媒合才是真實達成。</div>";
    html += "</section>";

    html += "</div></div>"; // grid

    html += '<div class="foot-note">' + iconInfo() + "示範資料為模擬,與台電及任何能源公司無官方關係。單位:能量 MWh、金額 NTD、電價 NTD/kWh。</div>";

    root.innerHTML = html;
    var rr = document.getElementById("rerun2");
    if (rr) rr.addEventListener("click", function () {
      runEvaluation(d.customerId, d.customer, d.period,
        parseInt(document.getElementById("f-minsites").value, 10) || 0,
        parseFloat(document.getElementById("f-minpct").value) || 0);
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
