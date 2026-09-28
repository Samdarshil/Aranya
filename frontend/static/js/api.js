// Aranya AI — API client
//
// Talks to the FastAPI backend in backend/api/main.py. This file has no
// build step and no dependencies — open index.html directly or serve
// the frontend/static/ folder with any static file server.
//
// STATUS: written and syntax-checked (node --check) in the authoring
// sandbox, but never run against a live backend there — this sandbox
// has no network access to install FastAPI/uvicorn, so the backend this
// talks to has never actually been started here. See docs/STATUS.md.

const Api = (() => {
  const STORAGE_KEY = "aranya_session";

  function getBaseUrl() {
    return localStorage.getItem("aranya_api_base") || "https://aranya-ai-backend-9209.onrender.com";
  }

  function setBaseUrl(url) {
    localStorage.setItem("aranya_api_base", url);
  }

  function getSession() {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : null;
  }

  function setSession(session) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
  }

  function clearSession() {
    localStorage.removeItem(STORAGE_KEY);
  }

  async function request(path, { method = "GET", form = null, json = null, auth = true, query = null } = {}) {
    let url = getBaseUrl() + path;
    if (query) {
      const qs = new URLSearchParams(
        Object.fromEntries(Object.entries(query).filter(([, v]) => v !== null && v !== undefined))
      );
      url += "?" + qs.toString();
    }

    const headers = {};
    const session = getSession();
    if (auth && session && session.access_token) {
      headers["Authorization"] = "Bearer " + session.access_token;
    }

    let body = null;
    if (form) {
      body = new FormData();
      for (const [k, v] of Object.entries(form)) {
        if (v !== null && v !== undefined) body.append(k, v);
      }
    } else if (json) {
      headers["Content-Type"] = "application/json";
      body = JSON.stringify(json);
    }

    let resp;
    try {
      resp = await fetch(url, { method, headers, body });
    } catch (networkErr) {
      throw new ApiError(
        `Could not reach the Aranya server at ${getBaseUrl()}. ` +
        `Check the server is running and the address is correct.`,
        0
      );
    }

    if (!resp.ok) {
      let detail = resp.statusText;
      try {
        const errJson = await resp.json();
        detail = errJson.detail || detail;
      } catch (_) { /* body wasn't JSON — keep statusText */ }
      throw new ApiError(detail, resp.status);
    }

    const contentType = resp.headers.get("content-type") || "";
    return contentType.includes("application/json") ? resp.json() : resp.text();
  }

  class ApiError extends Error {
    constructor(message, status) {
      super(message);
      this.status = status;
    }
  }

  return {
    getBaseUrl, setBaseUrl, getSession, setSession, clearSession, ApiError,

    // -- Auth ---------------------------------------------------------
    requestOtp: (phone, email) =>
      request("/api/v1/auth/request-otp", { form: { phone, email: email || null }, auth: false, method: "POST" }),
    verifyOtp: (phone, code, name, email) =>
      request("/api/v1/auth/verify-otp", { form: { phone, code, name, email: email || null }, auth: false, method: "POST" }),

    // -- Vision ---------------------------------------------------------
    cropScan: (farmId, fieldRef, cropName, file, isDemo) =>
      request("/api/v1/vision/crop-scan", {
        method: "POST",
        form: { farm_id: farmId, field_ref: fieldRef, crop_name: cropName, image: file, is_demo: isDemo },
      }),
    livestockScan: (farmId, animalRef, species, file, isDemo) =>
      request("/api/v1/vision/livestock-scan", {
        method: "POST",
        form: { farm_id: farmId, animal_ref: animalRef, species, image: file, is_demo: isDemo },
      }),

    // -- Weather / Soil / Planning ---------------------------------------
    weatherCheck: (farmId, lat, lng) =>
      request(`/api/v1/farms/${farmId}/weather`, { query: { lat, lng } }),
    soilTest: (farmId, fields) =>
      request(`/api/v1/farms/${farmId}/soil-test`, { method: "POST", form: fields }),
    planningQuery: (farmId, fieldRef, cropName, lat, lng) =>
      request(`/api/v1/farms/${farmId}/planning`, { query: { field_ref: fieldRef, crop_name: cropName, lat, lng } }),
    marketCheck: (farmId, cropName, marketName) =>
      request(`/api/v1/farms/${farmId}/market`, { query: { crop_name: cropName, market_name: marketName } }),
    logExpense: (farmId, fieldRef, cropName, category, amount) =>
      request(`/api/v1/farms/${farmId}/expenses`, {
        method: "POST", form: { field_ref: fieldRef, crop_name: cropName, category, amount },
      }),
    logSale: (farmId, fieldRef, cropName, quantityKg, pricePerKg) =>
      request(`/api/v1/farms/${farmId}/sales`, {
        method: "POST",
        form: { field_ref: fieldRef, crop_name: cropName, quantity_kg: quantityKg, price_per_kg: pricePerKg },
      }),
    fieldEconomics: (farmId, fieldRef, cropName) =>
      request(`/api/v1/farms/${farmId}/economics`, { query: { field_ref: fieldRef, crop_name: cropName } }),
    startNewCropCycle: (farmId, fieldRef, newCropName) =>
      request(`/api/v1/farms/${farmId}/crop-cycles`, {
        method: "POST", form: { field_ref: fieldRef, new_crop_name: newCropName },
      }),
    schemeMatch: (farmId, landAcres, category) =>
      request(`/api/v1/farms/${farmId}/schemes`, { query: { land_acres: landAcres, category: category || null } }),
    researchQuery: (farmId, query, cropName) =>
      request(`/api/v1/farms/${farmId}/research`, { query: { query, crop_name: cropName || null } }),
    recordOutcome: (farmId, sourceAgent, followedAdvice, outcome) =>
      request(`/api/v1/farms/${farmId}/outcomes`, {
        method: "POST",
        form: { source_agent: sourceAgent, followed_advice: followedAdvice, outcome },
      }),
    agentTrackRecord: (farmId, sourceAgent) =>
      request(`/api/v1/agents/${sourceAgent}/track-record`, { query: { farm_id: farmId } }),

    // -- History / Alerts / Chat -----------------------------------------
    fieldHistory: (farmId, fieldRef, cropName) =>
      request(`/api/v1/farms/${farmId}/fields/${encodeURIComponent(fieldRef)}/history`, { query: { crop_name: cropName } }),
    activeAlerts: (farmId) => request(`/api/v1/farms/${farmId}/alerts`),
    acknowledgeAlert: (farmId, alertId) =>
      request(`/api/v1/farms/${farmId}/alerts/${alertId}/acknowledge`, { method: "POST" }),
    pendingConsultations: (farmId) => request(`/api/v1/farms/${farmId}/consultations`),
    chat: (farmId, message, lat, lng) =>
      request(`/api/v1/farms/${farmId}/chat`, { method: "POST", form: { message, lat, lng } }),
  };
})();
