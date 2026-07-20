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

  function get(path, params) {
    return fetch(V1 + path + qs(params), { headers: { Accept: "application/json" } })
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

  global.api = {
    ApiError: ApiError,
    customers: function () { return get("/customers", { limit: 1000 }); },
    windFarms: function () { return get("/wind-farms", { limit: 1000 }); },
    contracts: function () { return get("/contracts", { limit: 1000 }); },
    generation: function () { return get("/generation", { limit: 5000 }); },
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
    investment: function (capexPerMw, omRatePercent) {
      return get("/analytics/investment", {
        capex_per_mw: capexPerMw,
        om_rate_percent: omRatePercent,
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
  };
})(window);
