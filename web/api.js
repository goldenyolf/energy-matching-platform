/* 同源 API 封裝。SPA 由 FastAPI 服務於 /app,故用相對路徑打 /api/v1。 */
(function (global) {
  "use strict";
  var V1 = "/api/v1";

  function ApiError(message, status) {
    this.name = "ApiError";
    this.message = message;
    this.status = status || 0;
  }
  ApiError.prototype = Object.create(Error.prototype);

  function qs(params) {
    var parts = [];
    Object.keys(params || {}).forEach(function (k) {
      var v = params[k];
      if (v === undefined || v === null || v === "") return;
      parts.push(encodeURIComponent(k) + "=" + encodeURIComponent(v));
    });
    return parts.length ? "?" + parts.join("&") : "";
  }

  var adminToken = null; // set via api.setToken() when 編輯模式 is on
  function request(method, path, params, jsonBody) {
    var headers = { Accept: "application/json" };
    var opts = { method: method, headers: headers };
    if (jsonBody !== undefined) {
      headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(jsonBody);
    }
    if (adminToken) headers["X-Admin-Token"] = adminToken;
    return fetch(V1 + path + qs(params), opts)
      .then(function (resp) {
        return resp.text().then(function (body) {
          if (!resp.ok) {
            var detail = body;
            try { detail = JSON.parse(body).detail || body; } catch (e) { /* keep text */ }
            throw new ApiError(resp.status + ": " + detail, resp.status);
          }
          return body ? JSON.parse(body) : null;
        });
      })
      .catch(function (err) {
        if (err instanceof ApiError) throw err;
        throw new ApiError("無法連線到後端 API：" + err.message, 0);
      });
  }
  function upload(path, file, params) {
    var fd = new FormData();
    fd.append("file", file);
    // dry_run:false relies on the endpoint's own default (a real write) —
    // there is no "?dry_run=false", the query string is simply omitted.
    var qs = params && params.dry_run ? "?dry_run=true" : "";
    var headers = { Accept: "application/json" };
    if (adminToken) headers["X-Admin-Token"] = adminToken;
    return fetch(V1 + path + qs, { method: "POST", headers: headers, body: fd })
      .then(function (resp) {
        return resp.text().then(function (body) {
          if (!resp.ok) {
            var detail = body;
            try { detail = JSON.parse(body).detail || body; } catch (e) { /* keep */ }
            throw new ApiError(resp.status + ": " + detail, resp.status);
          }
          return body ? JSON.parse(body) : null;
        });
      })
      .catch(function (err) {
        if (err instanceof ApiError) throw err;
        throw new ApiError("無法連線到後端 API：" + err.message, 0);
      });
  }
  function get(path, params) { return request("GET", path, params); }
  function post(path, params) { return request("POST", path, params); }
  function postJson(path, jsonBody) { return request("POST", path, null, jsonBody); }
  function putJson(path, jsonBody) { return request("PUT", path, null, jsonBody); }
  function del(path) { return request("DELETE", path, null); }

  global.api = {
    ApiError: ApiError,
    setToken: function (t) { adminToken = t || null; },
    customers: function () { return get("/customers", { limit: 1000 }); },
    windFarms: function () { return get("/wind-farms", { limit: 1000 }); },
    importFarms: function (file, o) { return upload("/wind-farms/import", file, o); },
    importCustomers: function (file, o) { return upload("/customers/import", file, o); },
    importContracts: function (file, o) { return upload("/contracts/import", file, o); },
    importMeters: function (file, o) { return upload("/meters/import", file, o); },
    importGeneration: function (file, o) { return upload("/generation/import", file, o); },
    importConsumption: function (file, o) { return upload("/consumption/import", file, o); },
    importBatteries: function (file, o) { return upload("/batteries/import", file, o); },
    importSchema: function () { return get("/import/schema"); },
    importTemplateUrl: function (entity) { return V1 + "/import/template/" + entity; },
    createFarm: function (data) { return postJson("/wind-farms", data); },
    updateFarm: function (id, data) { return putJson("/wind-farms/" + id, data); },
    deleteFarm: function (id) { return del("/wind-farms/" + id); },
    createCustomer: function (data) { return postJson("/customers", data); },
    updateCustomer: function (id, data) { return putJson("/customers/" + id, data); },
    deleteCustomer: function (id) { return del("/customers/" + id); },
    meters: function (customerId) { return get("/meters", customerId ? { customer_id: customerId, limit: 1000 } : { limit: 2000 }); },
    createMeter: function (data) { return postJson("/meters", data); },
    updateMeter: function (id, data) { return putJson("/meters/" + id, data); },
    deleteMeter: function (id) { return del("/meters/" + id); },
    contracts: function () { return get("/contracts", { limit: 1000 }); },
    createContract: function (data) { return postJson("/contracts", data); },
    updateContract: function (id, data) { return putJson("/contracts/" + id, data); },
    deleteContract: function (id) { return del("/contracts/" + id); },
    generation: function () { return get("/generation", { limit: 5000 }); },
    consumption: function () { return get("/consumption", { limit: 5000 }); },
    analyticsSummary: function (period) { return get("/analytics/summary", { period: period }); },
    analyticsCustomers: function (period) { return get("/analytics/customers", { period: period }); },
    analyticsWindFarms: function (period) { return get("/analytics/wind-farms", { period: period }); },
    liveRenewables: function (force) { return get("/live/renewables", force ? { force: "true" } : {}); },
    optimize: function (period, minSites, minPct) {
      return get("/matching/optimize", {
        period: period,
        min_sites: minSites,
        min_site_allocation_percent: minPct,
      });
    },
    evaluation: function (customerId, start, end) {
      return get("/analytics/evaluation", { customer_id: customerId, start: start, end: end });
    },
    slots: function (period) { return get("/matching/slots", { period: period }); },
    hourlyMatching: function (period, customerId) {
      return get("/matching/hourly", customerId != null ? { period: period, customer_id: customerId } : { period: period });
    },
    scenario: function (period, opts) {
      opts = opts || {};
      return get("/matching/scenario", {
        period: period,
        farm_ids: opts.farmIds,
        customer_ids: opts.customerIds,
        re_targets: opts.reTargets,
        feed_ins: opts.feedIns,
        transfer_price: opts.transferPrice,
        min_sites: opts.minSites,
        min_site_allocation_percent: opts.minPct,
      });
    },
    investment: function (capexPerMw, omRatePercent, scenario) {
      return get("/analytics/investment", {
        capex_per_mw: capexPerMw,
        om_rate_percent: omRatePercent,
        scenario: scenario,
      });
    },
    settlement: function (customerId, period, transferPrice, wheelingFee) {
      return get("/analytics/settlement", {
        customer_id: customerId,
        period: period,
        transfer_price_per_kwh: transferPrice,
        wheeling_fee_per_kwh: wheelingFee,
      });
    },
    contractRisks: function (period, horizonMonths) {
      return get("/analytics/contract-risks", { period: period, horizon_months: horizonMonths });
    },
    meterBreakdown: function (customerId, period) {
      return get("/analytics/meter-breakdown", { customer_id: customerId, period: period });
    },
    reRecommendations: function (customerId, period) {
      return get("/analytics/re-recommendations", { customer_id: customerId, period: period });
    },
    trecs: function (period, customerId) {
      return get("/trecs", { period: period, customer_id: customerId });
    },
    trecsIssue: function (period) { return post("/trecs/issue", { period: period }); },
    trecRetire: function (batchId) { return post("/trecs/" + batchId + "/retire", {}); },
    customerOptimization: function (customerId, period, minSites, minPct, reTarget, transferPrice) {
      return get("/analytics/customer-optimization", {
        customer_id: customerId,
        period: period,
        min_sites: minSites,
        min_site_allocation_percent: minPct,
        re_target_percent: reTarget,
        transfer_price_per_kwh: transferPrice,
      });
    },
    contractDetail: function (contractId, year) {
      return get("/analytics/contract-detail", { contract_id: contractId, year: year });
    },
  };
})(window);
