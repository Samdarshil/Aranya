// Aranya AI — app logic
//
// Single-page view switching (no router needed for this many screens).
// STATUS: syntax-checked (node --check) but never run against a live
// backend or in a real browser in the authoring sandbox — no network
// access there to install/run the FastAPI backend this expects. See
// docs/STATUS.md. The rendering and state logic below is straightforward
// DOM manipulation with no external dependency, so it's low-risk, but
// "written correctly" is not the same claim as "verified working" —
// test it against a real running backend before relying on it.

(() => {
  "use strict";

  let currentFarmId = null;
  let lastKnownLocation = null; // {lat, lng} — reused by planning if weather was checked first

  // ---------------------------------------------------------------------
  // View navigation
  // ---------------------------------------------------------------------
  function showView(viewId) {
    document.querySelectorAll(".view").forEach((el) => { el.hidden = el.id !== viewId; });
    document.querySelectorAll(".bottom-nav button, .sidebar-nav button").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.nav === viewId);
    });
    if (viewId === "view-alerts") loadFullAlertsList();
  }

  document.addEventListener("click", (e) => {
    const navTarget = e.target.closest("[data-nav]");
    if (navTarget) showView(navTarget.dataset.nav);
  });

  // ---------------------------------------------------------------------
  // Error / loading helpers
  // ---------------------------------------------------------------------
  function showError(slotId, message) {
    const slot = document.getElementById(slotId);
    slot.innerHTML = `<div class="error-banner">${escapeHtml(message)}</div>`;
  }
  function clearSlot(slotId) {
    document.getElementById(slotId).innerHTML = "";
  }
  function showLoading(slotId, message) {
    document.getElementById(slotId).innerHTML = `<div class="spinner-text">${escapeHtml(message)}</div>`;
  }
  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = String(str);
    return div.innerHTML;
  }
  function currentFarmIdOrWarn(slotId) {
    const val = document.getElementById("home-farm-id").value;
    if (!val) {
      showError(slotId, "Enter a Farm ID on the Home screen first.");
      return null;
    }
    return Number(val);
  }

  // ---------------------------------------------------------------------
  // Recommendation rendering — same shape for every agent's output
  // (RecommendationOut.from_domain on the backend), so one renderer
  // covers crop scan, livestock scan, weather, soil, and planning.
  // ---------------------------------------------------------------------
  function renderRecommendation(rec) {
    const severity = (rec.severity || "info").toLowerCase();
    const confidencePct = Math.round((rec.confidence || 0) * 100);
    const evidenceItems = (rec.evidence || [])
      .map((e) => `<li>${escapeHtml(e.description)}</li>`)
      .join("");

    const escalation = rec.escalate_to_expert
      ? `<div class="escalation-notice">&#9888;&#65039; <strong>Consider an expert:</strong> ${escapeHtml(rec.escalation_reason || "")}</div>`
      : "";

    return `
      <div class="rec-panel severity-${severity}">
        <div class="rec-problem">${escapeHtml(rec.problem)}</div>

        <div class="rec-row">
          <div class="rec-label">What to do</div>
          <div>${escapeHtml(rec.recommended_action)}</div>
        </div>

        <div class="rec-row">
          <div class="rec-label">Why</div>
          <div>${escapeHtml(rec.reasoning)}</div>
        </div>

        ${evidenceItems ? `
        <div class="rec-row">
          <div class="rec-label">Evidence</div>
          <ul class="evidence-list">${evidenceItems}</ul>
        </div>` : ""}

        <div class="rec-row">
          <div class="rec-label">Confidence: ${confidencePct}%</div>
          <div class="confidence-bar-track">
            <div class="confidence-bar-fill" style="width: ${confidencePct}%"></div>
          </div>
        </div>

        ${rec.monitoring_plan ? `
        <div class="rec-row">
          <div class="rec-label">Next check</div>
          <div>${escapeHtml(rec.monitoring_plan)}</div>
        </div>` : ""}

        ${escalation}

        <div class="rec-row outcome-feedback" data-source-agent="${escapeHtml(rec.source_agent || "")}">
          <div class="rec-label">Did you follow this, and did it help?</div>
          <div class="outcome-buttons">
            <button class="btn-outcome" data-outcome="improved" data-followed="true">Followed it — improved</button>
            <button class="btn-outcome" data-outcome="no_change" data-followed="true">Followed it — no change</button>
            <button class="btn-outcome" data-outcome="worsened" data-followed="true">Followed it — worsened</button>
            <button class="btn-outcome" data-outcome="no_change" data-followed="false">Didn't follow it</button>
          </div>
          <div class="outcome-confirm" hidden></div>
        </div>
      </div>
    `;
  }

  // ---------------------------------------------------------------------
  // Login
  // ---------------------------------------------------------------------
  document.getElementById("api-base-input").value = Api.getBaseUrl();
  document.getElementById("btn-save-api-base").addEventListener("click", () => {
    const val = document.getElementById("api-base-input").value.trim();
    if (val) Api.setBaseUrl(val);
  });

  document.getElementById("btn-request-otp").addEventListener("click", async () => {
    const phone = document.getElementById("login-phone").value.trim();
    const email = document.getElementById("login-email").value.trim();
    if (!phone) return showError("login-error-slot", "Enter a phone number.");
    clearSlot("login-error-slot");
    try {
      const result = await Api.requestOtp(phone, email);
      document.getElementById("login-step-phone").hidden = true;
      document.getElementById("login-step-otp").hidden = false;
      const hint = document.getElementById("otp-debug-hint");
      if (result.debug_code) {
        // No SMS/email provider is configured on the backend — dev-mode
        // fallback, code is returned directly. See backend/security/auth_service.py.
        hint.textContent = `No delivery provider is configured — your code is ${result.debug_code} (dev mode only).`;
      } else if (result.delivered_via && result.delivered_via.length) {
        hint.textContent = `Code sent via ${result.delivered_via.join(" and ")}.`;
      }
    } catch (err) {
      showError("login-error-slot", err.message);
    }
  });

  document.getElementById("btn-back-to-phone").addEventListener("click", () => {
    document.getElementById("login-step-otp").hidden = true;
    document.getElementById("login-step-phone").hidden = false;
  });

  document.getElementById("btn-verify-otp").addEventListener("click", async () => {
    const phone = document.getElementById("login-phone").value.trim();
    const email = document.getElementById("login-email").value.trim();
    const code = document.getElementById("login-otp").value.trim();
    const name = document.getElementById("login-name").value.trim() || "New Farmer";
    clearSlot("login-error-slot");
    try {
      const result = await Api.verifyOtp(phone, code, name, email);
      Api.setSession(result);
      showView("view-home");
      document.getElementById("bottom-nav").hidden = false;
      document.getElementById("app-sidebar").hidden = false;
    } catch (err) {
      showError("login-error-slot", err.message);
    }
  });

  function logOut() {
    Api.clearSession();
    document.getElementById("bottom-nav").hidden = true;
    document.getElementById("app-sidebar").hidden = true;
    showView("view-login");
  }
  document.getElementById("btn-logout").addEventListener("click", logOut);
  document.getElementById("btn-logout-sidebar").addEventListener("click", logOut);

  // ---------------------------------------------------------------------
  // Home / Alerts
  // ---------------------------------------------------------------------
  function renderAlertCard(alert) {
    return `
      <div class="alert-banner">
        <div class="alert-title">${escapeHtml(alert.problem)}</div>
        <div class="alert-meta">${escapeHtml(alert.subject_ref)} &middot; ${escapeHtml(alert.severity)} severity &middot; ${escapeHtml(alert.created_at)}</div>
        <button class="btn btn-secondary" data-ack="${alert.id}">Mark as seen</button>
      </div>
    `;
  }

  async function loadHomeAlerts() {
    const farmId = document.getElementById("home-farm-id").value;
    if (!farmId) return;
    const slot = document.getElementById("home-alerts-slot");
    try {
      const alerts = await Api.activeAlerts(Number(farmId));
      if (alerts.length === 0) {
        slot.innerHTML = "";
        return;
      }
      slot.innerHTML = alerts.slice(0, 3).map(renderAlertCard).join("");
    } catch (err) {
      // Non-fatal on the home screen — don't block the rest of the UI
      // over an alerts fetch failure.
      slot.innerHTML = "";
    }
  }

  async function loadFullAlertsList() {
    const farmId = document.getElementById("home-farm-id").value;
    const container = document.getElementById("alerts-full-list");
    const consultContainer = document.getElementById("consultations-list");
    if (!farmId) {
      container.innerHTML = `<div class="empty-state">Set a Farm ID on the Home screen first.</div>`;
      consultContainer.innerHTML = "";
      return;
    }
    container.innerHTML = `<div class="spinner-text">Loading alerts&hellip;</div>`;
    try {
      const alerts = await Api.activeAlerts(Number(farmId));
      container.innerHTML = alerts.length
        ? alerts.map(renderAlertCard).join("")
        : `<div class="empty-state">No active alerts. Aranya is watching.</div>`;
    } catch (err) {
      container.innerHTML = `<div class="error-banner">${escapeHtml(err.message)}</div>`;
    }

    consultContainer.innerHTML = `<div class="spinner-text">Loading&hellip;</div>`;
    try {
      const consultations = await Api.pendingConsultations(Number(farmId));
      consultContainer.innerHTML = consultations.length
        ? consultations.map(renderConsultationCard).join("")
        : `<div class="empty-state">No cases waiting on an expert right now.</div>`;
    } catch (err) {
      consultContainer.innerHTML = `<div class="error-banner">${escapeHtml(err.message)}</div>`;
    }
  }

  function renderConsultationCard(c) {
    // Read-only here: resolving a consultation is an expert-only action
    // (role-checked on the backend) and this build has no separate
    // expert-facing view — see docs/STATUS.md.
    return `
      <div class="alert-banner">
        <div class="alert-title">${escapeHtml(c.problem)}</div>
        <div class="alert-meta">${escapeHtml(c.source_agent)} &middot; ${escapeHtml(c.severity)} severity &middot; waiting since ${escapeHtml(c.requested_at)}</div>
      </div>
    `;
  }

  document.addEventListener("click", async (e) => {
    const ackBtn = e.target.closest("[data-ack]");
    if (!ackBtn) return;
    const farmId = document.getElementById("home-farm-id").value;
    if (!farmId) return showToast("Set a Farm ID on the Home screen first.");
    try {
      await Api.acknowledgeAlert(Number(farmId), Number(ackBtn.dataset.ack));
      ackBtn.closest(".alert-banner").remove();
    } catch (err) {
      showToast("Could not update the alert: " + err.message);
    }
  });

  document.addEventListener("click", async (e) => {
    const outcomeBtn = e.target.closest(".btn-outcome");
    if (!outcomeBtn) return;
    const container = outcomeBtn.closest(".outcome-feedback");
    const sourceAgent = container.dataset.sourceAgent;
    const farmId = document.getElementById("home-farm-id").value;
    const confirmSlot = container.querySelector(".outcome-confirm");
    if (!farmId) {
      confirmSlot.hidden = false;
      confirmSlot.textContent = "Set a Farm ID on the Home screen first.";
      return;
    }
    try {
      await Api.recordOutcome(
        Number(farmId), sourceAgent, outcomeBtn.dataset.followed === "true", outcomeBtn.dataset.outcome,
      );
      container.querySelector(".outcome-buttons").hidden = true;
      confirmSlot.hidden = false;
      confirmSlot.textContent = "Thanks — recorded. This helps Aranya track what actually works.";
    } catch (err) {
      confirmSlot.hidden = false;
      confirmSlot.textContent = "Could not record that: " + err.message;
    }
  });

  document.getElementById("home-farm-id").addEventListener("change", loadHomeAlerts);

  // ---------------------------------------------------------------------
  // Crop scan
  // ---------------------------------------------------------------------
  document.getElementById("btn-submit-crop-scan").addEventListener("click", async () => {
    const farmId = currentFarmIdOrWarn("crop-scan-error-slot");
    if (!farmId) return;
    const fieldRef = document.getElementById("crop-field-ref").value.trim();
    const cropName = document.getElementById("crop-name").value;
    const file = document.getElementById("crop-photo").files[0];
    if (!fieldRef) return showError("crop-scan-error-slot", "Enter a field name.");
    if (!file) return showError("crop-scan-error-slot", "Choose or take a photo first.");

    clearSlot("crop-scan-error-slot");
    showLoading("crop-scan-result-slot", "Analyzing the photo\u2026");
    try {
      const rec = await Api.cropScan(farmId, fieldRef, cropName, file, false);
      document.getElementById("crop-scan-result-slot").innerHTML = renderRecommendation(rec);
    } catch (err) {
      clearSlot("crop-scan-result-slot");
      showError("crop-scan-error-slot", err.message);
    }
  });

  // ---------------------------------------------------------------------
  // Livestock scan
  // ---------------------------------------------------------------------
  document.getElementById("btn-submit-livestock-scan").addEventListener("click", async () => {
    const farmId = currentFarmIdOrWarn("livestock-scan-error-slot");
    if (!farmId) return;
    const animalRef = document.getElementById("animal-ref").value.trim();
    const species = document.getElementById("animal-species").value;
    const file = document.getElementById("animal-photo").files[0];
    if (!animalRef) return showError("livestock-scan-error-slot", "Enter an animal ID or name.");
    if (!file) return showError("livestock-scan-error-slot", "Choose or take a photo first.");

    clearSlot("livestock-scan-error-slot");
    showLoading("livestock-scan-result-slot", "Analyzing the photo\u2026");
    try {
      const rec = await Api.livestockScan(farmId, animalRef, species, file, false);
      document.getElementById("livestock-scan-result-slot").innerHTML = renderRecommendation(rec);
    } catch (err) {
      clearSlot("livestock-scan-result-slot");
      showError("livestock-scan-error-slot", err.message);
    }
  });

  // ---------------------------------------------------------------------
  // Weather
  // ---------------------------------------------------------------------
  document.getElementById("btn-use-my-location").addEventListener("click", () => {
    if (!navigator.geolocation) {
      return showError("weather-error-slot", "Location isn't available in this browser.");
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        document.getElementById("weather-lat").value = pos.coords.latitude;
        document.getElementById("weather-lng").value = pos.coords.longitude;
      },
      (err) => showError("weather-error-slot", "Could not get your location: " + err.message)
    );
  });

  document.getElementById("btn-check-weather").addEventListener("click", async () => {
    const farmId = currentFarmIdOrWarn("weather-error-slot");
    if (!farmId) return;
    const lat = Number(document.getElementById("weather-lat").value);
    const lng = Number(document.getElementById("weather-lng").value);
    if (!lat || !lng) return showError("weather-error-slot", "Enter or fetch a location first.");

    clearSlot("weather-error-slot");
    showLoading("weather-result-slot", "Checking the forecast\u2026");
    try {
      const rec = await Api.weatherCheck(farmId, lat, lng);
      document.getElementById("weather-result-slot").innerHTML = renderRecommendation(rec);
      lastKnownLocation = { lat, lng };
    } catch (err) {
      clearSlot("weather-result-slot");
      showError("weather-error-slot", err.message);
    }
  });

  // ---------------------------------------------------------------------
  // Soil
  // ---------------------------------------------------------------------
  document.getElementById("btn-submit-soil").addEventListener("click", async () => {
    const farmId = currentFarmIdOrWarn("soil-error-slot");
    if (!farmId) return;
    const fieldRef = document.getElementById("soil-field-ref").value.trim();
    if (!fieldRef) return showError("soil-error-slot", "Enter a field name.");

    const fields = {
      field_ref: fieldRef,
      crop_name: document.getElementById("soil-crop-name").value,
      ph: document.getElementById("soil-ph").value || null,
      nitrogen_ppm: document.getElementById("soil-n").value || null,
      phosphorus_ppm: document.getElementById("soil-p").value || null,
      potassium_ppm: document.getElementById("soil-k").value || null,
      source: document.getElementById("soil-source").value,
    };
    if (!fields.ph && !fields.nitrogen_ppm && !fields.phosphorus_ppm && !fields.potassium_ppm) {
      return showError("soil-error-slot", "Enter at least one measurement (pH or N/P/K).");
    }

    clearSlot("soil-error-slot");
    showLoading("soil-result-slot", "Evaluating soil data\u2026");
    try {
      const rec = await Api.soilTest(farmId, fields);
      document.getElementById("soil-result-slot").innerHTML = renderRecommendation(rec);
    } catch (err) {
      clearSlot("soil-result-slot");
      showError("soil-error-slot", err.message);
    }
  });

  // ---------------------------------------------------------------------
  // Planning
  // ---------------------------------------------------------------------
  document.getElementById("btn-submit-planning").addEventListener("click", async () => {
    const farmId = currentFarmIdOrWarn("planning-error-slot");
    if (!farmId) return;
    const fieldRef = document.getElementById("planning-field-ref").value.trim();
    const cropName = document.getElementById("planning-crop-name").value;
    if (!fieldRef) return showError("planning-error-slot", "Enter a field name.");

    clearSlot("planning-error-slot");
    showLoading("planning-result-slot", "Checking soil, weather, and season\u2026");
    try {
      const lat = lastKnownLocation ? lastKnownLocation.lat : null;
      const lng = lastKnownLocation ? lastKnownLocation.lng : null;
      const rec = await Api.planningQuery(farmId, fieldRef, cropName, lat, lng);
      document.getElementById("planning-result-slot").innerHTML = renderRecommendation(rec);
    } catch (err) {
      clearSlot("planning-result-slot");
      showError("planning-error-slot", err.message);
    }
  });

  // ---------------------------------------------------------------------
  // Market
  // ---------------------------------------------------------------------
  document.getElementById("btn-check-market").addEventListener("click", async () => {
    const farmId = currentFarmIdOrWarn("market-error-slot");
    if (!farmId) return;
    const cropName = document.getElementById("market-crop-name").value;
    const marketName = document.getElementById("market-name").value.trim();
    if (!marketName) return showError("market-error-slot", "Enter a market/mandi name.");

    clearSlot("market-error-slot");
    showLoading("market-result-slot", "Checking today's price\u2026");
    try {
      const rec = await Api.marketCheck(farmId, cropName, marketName);
      document.getElementById("market-result-slot").innerHTML = renderRecommendation(rec);
    } catch (err) {
      clearSlot("market-result-slot");
      showError("market-error-slot", err.message);
    }
  });

  // ---------------------------------------------------------------------
  // Economics
  // ---------------------------------------------------------------------
  document.getElementById("btn-log-expense").addEventListener("click", async () => {
    const farmId = currentFarmIdOrWarn("economics-error-slot");
    if (!farmId) return;
    const fieldRef = document.getElementById("econ-field-ref").value.trim();
    const cropName = document.getElementById("econ-crop-name").value;
    const category = document.getElementById("econ-expense-category").value;
    const amount = Number(document.getElementById("econ-expense-amount").value);
    if (!fieldRef) return showError("economics-error-slot", "Enter a field name.");
    if (!amount) return showError("economics-error-slot", "Enter an expense amount.");
    clearSlot("economics-error-slot");
    try {
      await Api.logExpense(farmId, fieldRef, cropName, category, amount);
      document.getElementById("econ-expense-amount").value = "";
    } catch (err) {
      showError("economics-error-slot", err.message);
    }
  });

  document.getElementById("btn-log-sale").addEventListener("click", async () => {
    const farmId = currentFarmIdOrWarn("economics-error-slot");
    if (!farmId) return;
    const fieldRef = document.getElementById("econ-field-ref").value.trim();
    const cropName = document.getElementById("econ-crop-name").value;
    const qty = Number(document.getElementById("econ-sale-qty").value);
    const price = Number(document.getElementById("econ-sale-price").value);
    if (!fieldRef) return showError("economics-error-slot", "Enter a field name.");
    if (!qty || !price) return showError("economics-error-slot", "Enter quantity and price.");
    clearSlot("economics-error-slot");
    try {
      await Api.logSale(farmId, fieldRef, cropName, qty, price);
      document.getElementById("econ-sale-qty").value = "";
      document.getElementById("econ-sale-price").value = "";
    } catch (err) {
      showError("economics-error-slot", err.message);
    }
  });

  document.getElementById("btn-view-economics").addEventListener("click", async () => {
    const farmId = currentFarmIdOrWarn("economics-error-slot");
    if (!farmId) return;
    const fieldRef = document.getElementById("econ-field-ref").value.trim();
    const cropName = document.getElementById("econ-crop-name").value;
    if (!fieldRef) return showError("economics-error-slot", "Enter a field name.");
    clearSlot("economics-error-slot");
    showLoading("economics-result-slot", "Adding it up\u2026");
    try {
      const rec = await Api.fieldEconomics(farmId, fieldRef, cropName);
      document.getElementById("economics-result-slot").innerHTML = renderRecommendation(rec);
    } catch (err) {
      clearSlot("economics-result-slot");
      showError("economics-error-slot", err.message);
    }
  });

  document.getElementById("btn-start-cycle").addEventListener("click", async () => {
    const farmId = currentFarmIdOrWarn("economics-error-slot");
    if (!farmId) return;
    const fieldRef = document.getElementById("econ-field-ref").value.trim();
    const newCrop = document.getElementById("econ-crop-name").value;
    if (!fieldRef) return showError("economics-error-slot", "Enter a field name.");
    if (!confirm(`Start a new ${newCrop} cycle for ${fieldRef}? This ends the current cycle's tracking.`)) return;
    clearSlot("economics-error-slot");
    try {
      await Api.startNewCropCycle(farmId, fieldRef, newCrop);
      clearSlot("economics-result-slot");
      document.getElementById("economics-result-slot").innerHTML =
        `<div class="empty-state">New ${escapeHtml(newCrop)} cycle started for ${escapeHtml(fieldRef)}.</div>`;
    } catch (err) {
      showError("economics-error-slot", err.message);
    }
  });

  // ---------------------------------------------------------------------
  // Schemes
  // ---------------------------------------------------------------------
  document.getElementById("btn-check-schemes").addEventListener("click", async () => {
    const farmId = currentFarmIdOrWarn("scheme-error-slot");
    if (!farmId) return;
    const landAcres = document.getElementById("scheme-land-acres").value;
    const category = document.getElementById("scheme-category").value;
    if (!landAcres && !category) {
      return showError("scheme-error-slot", "Enter a land size or select a category.");
    }
    clearSlot("scheme-error-slot");
    showLoading("scheme-result-slot", "Checking eligible schemes\u2026");
    try {
      const rec = await Api.schemeMatch(farmId, landAcres || null, category);
      document.getElementById("scheme-result-slot").innerHTML = renderRecommendation(rec);
    } catch (err) {
      clearSlot("scheme-result-slot");
      showError("scheme-error-slot", err.message);
    }
  });

  // ---------------------------------------------------------------------
  // Research
  // ---------------------------------------------------------------------
  document.getElementById("btn-submit-research").addEventListener("click", async () => {
    const farmId = currentFarmIdOrWarn("research-error-slot");
    if (!farmId) return;
    const query = document.getElementById("research-query").value.trim();
    const cropName = document.getElementById("research-crop-name").value;
    if (!query) return showError("research-error-slot", "Describe what you're seeing first.");
    clearSlot("research-error-slot");
    showLoading("research-result-slot", "Searching\u2026");
    try {
      const rec = await Api.researchQuery(farmId, query, cropName);
      document.getElementById("research-result-slot").innerHTML = renderRecommendation(rec);
    } catch (err) {
      clearSlot("research-result-slot");
      showError("research-error-slot", err.message);
    }
  });

  // ---------------------------------------------------------------------
  // Chat
  // ---------------------------------------------------------------------
  function appendChatBubble(text, from) {
    const log = document.getElementById("chat-log");
    const bubble = document.createElement("div");
    bubble.className = `chat-bubble from-${from}`;
    bubble.textContent = text;
    log.appendChild(bubble);
    log.scrollTop = log.scrollHeight;
  }

  document.getElementById("chat-llm-hint").textContent =
    "Aranya answers questions about weather, field history, animal history, and planting timing. " +
    "Photo scans need the dedicated Scan screens for now.";

  async function sendChatMessage() {
    const input = document.getElementById("chat-input");
    const message = input.value.trim();
    if (!message) return;
    const farmId = document.getElementById("home-farm-id").value;
    if (!farmId) {
      appendChatBubble("Set a Farm ID on the Home screen first.", "aranya");
      return;
    }
    appendChatBubble(message, "farmer");
    input.value = "";

    try {
      const lat = lastKnownLocation ? lastKnownLocation.lat : null;
      const lng = lastKnownLocation ? lastKnownLocation.lng : null;
      const result = await Api.chat(Number(farmId), message, lat, lng);
      if (result.type === "clarification" || result.type === "error") {
        appendChatBubble(result.message, "aranya");
      } else if (result.type === "recommendation") {
        appendChatBubble(`${result.what_happened} — ${result.what_to_do}`, "aranya");
      } else if (result.type === "history") {
        appendChatBubble(
          result.message || `${result.scan_count} record(s) on file. Latest: ${result.latest_status || result.latest_risk_level || "n/a"}.`,
          "aranya"
        );
      } else {
        appendChatBubble("I'm not sure how to show that yet.", "aranya");
      }
    } catch (err) {
      appendChatBubble("Something went wrong: " + err.message, "aranya");
    }
  }

  document.getElementById("btn-send-chat").addEventListener("click", sendChatMessage);
  document.getElementById("chat-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter") sendChatMessage();
  });

  // ---------------------------------------------------------------------
  // Splash screen — hidden the instant boot() finishes its real work,
  // never a fixed fake delay pretending something is loading.
  // ---------------------------------------------------------------------
  function hideSplash() {
    const splash = document.getElementById("splash");
    if (splash) splash.classList.add("splash-hidden");
  }

  // ---------------------------------------------------------------------
  // Toasts — lightweight, non-blocking notifications. Purely a visual
  // upgrade over the two places this file used to call the browser's
  // native alert(); the information shown is unchanged, just the
  // presentation. confirm() dialogs (e.g. before starting a new crop
  // cycle) are left as native browser dialogs on purpose — replacing a
  // blocking confirmation with a custom async modal would change
  // interaction behavior, which is outside this pass's scope.
  // ---------------------------------------------------------------------
  function showToast(message) {
    const stack = document.getElementById("toast-stack");
    if (!stack) { alert(message); return; }
    const el = document.createElement("div");
    el.className = "toast";
    el.textContent = message;
    stack.appendChild(el);
    setTimeout(() => {
      el.classList.add("toast-leaving");
      setTimeout(() => el.remove(), 260);
    }, 3200);
  }

  // ---------------------------------------------------------------------
  // Image preview — purely additive: shows a thumbnail of the selected
  // photo before upload. Does not touch the existing submit handlers or
  // the file input's value in any way.
  // ---------------------------------------------------------------------
  function wireImagePreview(inputId, previewId) {
    const input = document.getElementById(inputId);
    const preview = document.getElementById(previewId);
    if (!input || !preview) return;
    input.addEventListener("change", () => {
      const file = input.files[0];
      if (!file) { preview.classList.remove("has-image"); return; }
      const reader = new FileReader();
      reader.onload = (e) => {
        preview.querySelector("img").src = e.target.result;
        preview.classList.add("has-image");
      };
      reader.readAsDataURL(file);
    });
  }
  wireImagePreview("crop-photo", "crop-photo-preview");
  wireImagePreview("animal-photo", "animal-photo-preview");

  // ---------------------------------------------------------------------
  // Boot
  // ---------------------------------------------------------------------
  function boot() {
    const session = Api.getSession();
    if (session && session.access_token) {
      document.getElementById("bottom-nav").hidden = false;
      document.getElementById("app-sidebar").hidden = false;
      showView("view-home");
    } else {
      showView("view-login");
    }
    hideSplash();
  }
  boot();
})();
