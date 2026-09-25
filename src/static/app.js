// ApplyFlow Frontend Application Logic (Enhanced with Lightbox & Developer Logs)

let statusPollInterval = null;
let devLogsPollInterval = null;
let currentActiveTab = "tab-apply";

// Developer Logs State
let allLogs = [];
let currentLogFilter = "ALL";
let lastLogId = 0;

// Lightbox Zoom & Pan State
let currentZoom = 1.0;
let isPanning = false;
let startX = 0;
let startY = 0;
let translateX = 0;
let translateY = 0;

document.addEventListener("DOMContentLoaded", () => {
  initTabs();
  initMockServerToggle();
  initApplyFlow();
  initProfile();
  initQABank();
  initHistory();
  initScreenshotLightbox();
  initDevLogs();
  initSetupWizard();
  initProfileResumeUpload();
  initBrowserAuthManager();

  // Background poll for log count on startup
  pollDevLogsCount();
  setInterval(pollDevLogsCount, 3000);
});

// Toast notification helper
function showToast(message, type = "info") {
  const container = document.getElementById("toast-container");
  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;
  toast.innerText = message;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = "0";
    setTimeout(() => toast.remove(), 300);
  }, 3500);
}

// Tab navigation
function initTabs() {
  document.querySelectorAll(".nav-item").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".nav-item").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".tab-pane").forEach((p) => p.classList.remove("active"));

      btn.classList.add("active");
      const targetId = btn.getAttribute("data-tab");
      document.getElementById(targetId).classList.add("active");
      currentActiveTab = targetId;

      if (targetId === "tab-profile") loadProfile();
      if (targetId === "tab-qa") loadQABank();
      if (targetId === "tab-history") loadHistory();
    });
  });
}

// Mock ATS Server Toggle
function initMockServerToggle() {
  const btn = document.getElementById("btn-toggle-mock");
  const dot = document.getElementById("mock-status-dot");
  const quickMockBtn = document.getElementById("btn-quick-mock");

  function updateMockStatus() {
    fetch("/api/mock-server/status")
      .then((r) => r.json())
      .then((data) => {
        if (data.running) {
          dot.classList.add("active");
          btn.innerText = "Stop Mock Server";
        } else {
          dot.classList.remove("active");
          btn.innerText = "Start Mock Server";
        }
      })
      .catch(() => {});
  }

  btn.addEventListener("click", () => {
    fetch("/api/mock-server/toggle", { method: "POST" })
      .then((r) => r.json())
      .then(() => {
        updateMockStatus();
        showToast("Mock ATS server state toggled", "info");
      });
  });

  quickMockBtn.addEventListener("click", () => {
    document.getElementById("target-url-input").value = "http://127.0.0.1:8088/";
    // Ensure mock server is running
    fetch("/api/mock-server/status")
      .then((r) => r.json())
      .then((data) => {
        if (!data.running) {
          fetch("/api/mock-server/toggle", { method: "POST" }).then(() => updateMockStatus());
        }
      });
  });

  updateMockStatus();
}

// =========================================================================
// SCREENSHOT LIGHTBOX VIEWER
// =========================================================================

function initScreenshotLightbox() {
  const modal = document.getElementById("modal-screenshot-lightbox");
  const img = document.getElementById("lightbox-img");
  const panSurface = document.getElementById("lightbox-pan-surface");
  const viewport = document.getElementById("lightbox-viewport");

  // Open triggers
  document.getElementById("job-screenshot-wrapper").addEventListener("click", () => {
    const src = document.getElementById("job-screenshot-img").src;
    if (src && !src.endsWith("/")) {
      openScreenshotLightbox(src, "Initial Job Posting Ingestion");
    }
  });

  document.getElementById("post-fill-screenshot-wrapper").addEventListener("click", () => {
    const src = document.getElementById("post-fill-screenshot-img").src;
    if (src && !src.endsWith("/")) {
      openScreenshotLightbox(src, "Post-Fill Verification Snapshot");
    }
  });

  // Controls
  document.getElementById("btn-close-lightbox").addEventListener("click", closeScreenshotLightbox);
  modal.addEventListener("click", (e) => {
    if (e.target === modal) closeScreenshotLightbox();
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      if (modal.style.display === "flex") closeScreenshotLightbox();
      if (document.getElementById("modal-dev-logs").style.display === "flex") closeDevLogs();
    }
  });

  document.getElementById("btn-zoom-in").addEventListener("click", () => {
    currentZoom = Math.min(currentZoom + 0.25, 4.0);
    applyZoom();
  });

  document.getElementById("btn-zoom-out").addEventListener("click", () => {
    currentZoom = Math.max(currentZoom - 0.25, 0.5);
    applyZoom();
  });

  document.getElementById("btn-zoom-reset").addEventListener("click", () => {
    currentZoom = 1.0;
    translateX = 0;
    translateY = 0;
    applyZoom();
  });

  // Mouse wheel zoom
  viewport.addEventListener("wheel", (e) => {
    e.preventDefault();
    if (e.deltaY < 0) {
      currentZoom = Math.min(currentZoom + 0.15, 4.0);
    } else {
      currentZoom = Math.max(currentZoom - 0.15, 0.4);
    }
    applyZoom();
  }, { passive: false });

  // Pan / Drag implementation
  viewport.addEventListener("mousedown", (e) => {
    if (e.button !== 0) return;
    isPanning = true;
    startX = e.clientX - translateX;
    startY = e.clientY - translateY;
  });

  window.addEventListener("mousemove", (e) => {
    if (!isPanning) return;
    translateX = e.clientX - startX;
    translateY = e.clientY - startY;
    applyZoom();
  });

  window.addEventListener("mouseup", () => {
    isPanning = false;
  });

  function applyZoom() {
    panSurface.style.transform = `translate(${translateX}px, ${translateY}px) scale(${currentZoom})`;
  }
}

function openScreenshotLightbox(src, title = "Screenshot Inspection") {
  const modal = document.getElementById("modal-screenshot-lightbox");
  const img = document.getElementById("lightbox-img");
  const filenameEl = document.getElementById("lightbox-filename");
  const titleEl = document.getElementById("lightbox-title");
  const extBtn = document.getElementById("btn-open-external");

  img.src = src;
  titleEl.innerText = title;
  const fname = src.split("/").pop().split("\\").pop();
  filenameEl.innerText = fname || "screenshot.png";
  extBtn.href = src;

  currentZoom = 1.0;
  translateX = 0;
  translateY = 0;
  document.getElementById("lightbox-pan-surface").style.transform = "translate(0px, 0px) scale(1)";

  modal.style.display = "flex";
}

function closeScreenshotLightbox() {
  document.getElementById("modal-screenshot-lightbox").style.display = "none";
}

// =========================================================================
// DEVELOPER CONSOLE & REAL-TIME LOGS
// =========================================================================

function initDevLogs() {
  const btnOpen = document.getElementById("btn-open-dev-logs");
  const btnClose = document.getElementById("btn-close-dev-logs");
  const modal = document.getElementById("modal-dev-logs");
  const btnClear = document.getElementById("btn-clear-logs");
  const btnCopy = document.getElementById("btn-copy-logs");

  btnOpen.addEventListener("click", openDevLogs);
  btnClose.addEventListener("click", closeDevLogs);

  modal.addEventListener("click", (e) => {
    if (e.target === modal) closeDevLogs();
  });

  // Filter pills
  document.querySelectorAll(".log-filter-pills .filter-pill").forEach((pill) => {
    pill.addEventListener("click", () => {
      document.querySelectorAll(".log-filter-pills .filter-pill").forEach((p) => p.classList.remove("active"));
      pill.classList.add("active");
      currentLogFilter = pill.getAttribute("data-filter");
      renderDevLogs();
    });
  });

  // Clear logs
  btnClear.addEventListener("click", () => {
    fetch("/api/logs/clear", { method: "POST" })
      .then(() => {
        allLogs = [];
        lastLogId = 0;
        renderDevLogs();
        showToast("Log buffer cleared", "info");
      });
  });

  // Copy logs
  btnCopy.addEventListener("click", () => {
    if (allLogs.length === 0) {
      showToast("No logs to copy", "warning");
      return;
    }
    const text = allLogs
      .map((l) => `[${l.timestamp}] [${l.level}] ${l.message}`)
      .join("\n");
    navigator.clipboard.writeText(text).then(() => {
      showToast("Logs copied to clipboard!", "success");
    });
  });
}

function openDevLogs() {
  document.getElementById("modal-dev-logs").style.display = "flex";
  fetchDevLogs(true);
  if (devLogsPollInterval) clearInterval(devLogsPollInterval);
  devLogsPollInterval = setInterval(() => fetchDevLogs(false), 900);
}

function closeDevLogs() {
  document.getElementById("modal-dev-logs").style.display = "none";
  if (devLogsPollInterval) {
    clearInterval(devLogsPollInterval);
    devLogsPollInterval = null;
  }
}

function pollDevLogsCount() {
  fetch("/api/logs?since_id=" + lastLogId)
    .then((r) => r.json())
    .then((data) => {
      if (data.logs && data.logs.length > 0) {
        allLogs = allLogs.concat(data.logs);
        lastLogId = allLogs[allLogs.length - 1].id;
      }
      const badge = document.getElementById("dev-logs-badge");
      if (badge) badge.innerText = allLogs.length;
      const countEl = document.getElementById("dev-logs-count");
      if (countEl) countEl.innerText = `${allLogs.length} events`;
    })
    .catch(() => {});
}

function fetchDevLogs(forceScroll = false) {
  fetch("/api/logs?since_id=" + lastLogId)
    .then((r) => r.json())
    .then((data) => {
      let hasNew = false;
      if (data.logs && data.logs.length > 0) {
        allLogs = allLogs.concat(data.logs);
        lastLogId = allLogs[allLogs.length - 1].id;
        hasNew = true;
      }
      const badge = document.getElementById("dev-logs-badge");
      if (badge) badge.innerText = allLogs.length;
      const countEl = document.getElementById("dev-logs-count");
      if (countEl) countEl.innerText = `${allLogs.length} events`;

      if (hasNew || forceScroll) {
        renderDevLogs();
      }
    })
    .catch(() => {});
}

function renderDevLogs() {
  const terminal = document.getElementById("dev-logs-terminal");
  const filtered = allLogs.filter((l) => {
    if (currentLogFilter === "ALL") return true;
    return l.level === currentLogFilter;
  });

  terminal.innerHTML = "";
  if (filtered.length === 0) {
    terminal.innerHTML = `<div class="terminal-welcome">No log entries matching filter '${currentLogFilter}'.</div>`;
    return;
  }

  filtered.forEach((log) => {
    const line = document.createElement("div");
    line.className = "log-line";
    line.innerHTML = `
      <span class="log-time">${escapeHtml(log.timestamp)}</span>
      <span class="log-tag ${log.level}">[${log.level}]</span>
      <span class="log-msg">${escapeHtml(log.message)}</span>
    `;
    terminal.appendChild(line);
  });

  const autoScroll = document.getElementById("chk-auto-scroll").checked;
  if (autoScroll) {
    terminal.scrollTop = terminal.scrollHeight;
  }
}

// =========================================================================
// APPLY FLOW LOGIC
// =========================================================================

function initApplyFlow() {
  const btnScan = document.getElementById("btn-scan");
  const urlInput = document.getElementById("target-url-input");
  const loadingCard = document.getElementById("scan-loading");
  const scorecardContainer = document.getElementById("scorecard-container");
  const progressContainer = document.getElementById("autofill-progress-container");
  const preflightContainer = document.getElementById("preflight-container");

  btnScan.addEventListener("click", () => {
    const url = urlInput.value.trim();
    if (!url) {
      showToast("Please enter a valid job posting URL", "warning");
      return;
    }

    const authBox = document.getElementById("auth-required-box");
    if (authBox) authBox.style.display = "none";
    loadingCard.style.display = "flex";
    scorecardContainer.style.display = "none";
    progressContainer.style.display = "none";
    preflightContainer.style.display = "none";
    btnScan.disabled = true;

    fetch("/api/scan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: url }),
    })
      .then((r) => {
        if (!r.ok) throw new Error("Failed to scan page.");
        return r.json();
      })
      .then((data) => {
        loadingCard.style.display = "none";
        btnScan.disabled = false;

        if (data.status === "credentials_required" || data.status === "auth_required") {
          if (authBox) {
            authBox.style.display = "block";
            const titleEl = document.getElementById("auth-req-title");
            const descEl = document.getElementById("auth-req-desc");
            const credsForm = document.getElementById("auth-req-creds-form");
            const btnAuto = document.getElementById("btn-auth-req-auto");

            if (titleEl) titleEl.innerText = `Sign-In Required for ${data.platform || "Portal"}`;
            if (descEl) descEl.innerText = data.message || `${data.platform || "Platform"} requires authentication.`;

            if (data.status === "credentials_required") {
              if (credsForm) credsForm.style.display = "block";
              if (btnAuto) btnAuto.style.display = "none";
              showToast(`Enter ${data.platform || "job portal"} credentials below to auto-login via .env!`, "warning");
            } else {
              if (credsForm) credsForm.style.display = "none";
              if (btnAuto && data.has_credentials) btnAuto.style.display = "inline-flex";
              showToast(`Authentication needed on ${data.platform || "job portal"}!`, "warning");
            }
          }
          return;
        }

        if (authBox) authBox.style.display = "none";
        renderScorecard(data);
      })
      .catch((err) => {
        loadingCard.style.display = "none";
        btnScan.disabled = false;
        showToast(err.message || "Error scanning page", "error");
      });
  });

  // Inline .env Credentials Save & Auto-Login Trigger
  const btnAuthSaveAndLogin = document.getElementById("btn-auth-save-and-login");
  if (btnAuthSaveAndLogin) {
    btnAuthSaveAndLogin.addEventListener("click", () => {
      const email = document.getElementById("auth-inline-email").value.trim();
      const pwd = document.getElementById("auth-inline-pwd").value.trim();
      if (!email || !pwd) {
        showToast("Please enter both email and password.", "warning");
        return;
      }
      btnAuthSaveAndLogin.disabled = true;
      btnAuthSaveAndLogin.innerText = "Saving to .env...";

      fetch("/api/credentials/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          linkedin_email: email,
          linkedin_password: pwd,
        }),
      })
        .then((r) => r.json())
        .then(() => {
          showToast("Credentials saved to .env! Attempting automated AI login...", "success");
          btnAuthSaveAndLogin.disabled = false;
          btnAuthSaveAndLogin.innerText = "💾 Save to .env & Auto-Log In";
          const credsForm = document.getElementById("auth-req-creds-form");
          if (credsForm) credsForm.style.display = "none";
          btnScan.click();
        })
        .catch((err) => {
          btnAuthSaveAndLogin.disabled = false;
          btnAuthSaveAndLogin.innerText = "💾 Save to .env & Auto-Log In";
          showToast("Error saving credentials: " + err.message, "error");
        });
    });
  }

  // Auth Required Card Actions
  const btnAuthReqLogin = document.getElementById("btn-auth-req-login");
  const btnAuthReqRetry = document.getElementById("btn-auth-req-retry");
  const btnAuthReqAuto = document.getElementById("btn-auth-req-auto");

  if (btnAuthReqAuto) {
    btnAuthReqAuto.addEventListener("click", () => {
      btnScan.click();
    });
  }
  if (btnAuthReqLogin) {
    btnAuthReqLogin.addEventListener("click", () => {
      openBrowserAuthModal();
      document.getElementById("btn-login-linkedin").click();
    });
  }
  if (btnAuthReqRetry) {
    btnAuthReqRetry.addEventListener("click", () => {
      const authBox = document.getElementById("auth-required-box");
      if (authBox) authBox.style.display = "none";
      btnScan.click();
    });
  }

  document.getElementById("btn-proceed-autofill").addEventListener("click", () => {
    scorecardContainer.style.display = "none";
    progressContainer.style.display = "block";
    document.getElementById("fill-steps-body").innerHTML = "";

    fetch("/api/autofill/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: urlInput.value.trim() }),
    })
      .then((r) => r.json())
      .then(() => {
        startStatusPolling();
      });
  });

  document.getElementById("btn-abort-autofill").addEventListener("click", () => {
    fetch("/api/autofill/abort", { method: "POST" });
    scorecardContainer.style.display = "none";
    showToast("Application run aborted by user.", "info");
  });

  // Modal Question Handlers
  document.getElementById("btn-submit-q-answer").addEventListener("click", () => {
    const val = document.getElementById("modal-q-input").value.trim();
    fetch("/api/autofill/answer", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ answer: val }),
    }).then(() => {
      document.getElementById("modal-question").style.display = "none";
    });
  });

  document.getElementById("btn-skip-q-answer").addEventListener("click", () => {
    fetch("/api/autofill/answer", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ answer: "" }),
    }).then(() => {
      document.getElementById("modal-question").style.display = "none";
    });
  });

  // Modal Essay Handlers
  document.getElementById("btn-essay-accept").addEventListener("click", () => {
    fetch("/api/autofill/essay", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ choice: "accept" }),
    }).then(() => {
      document.getElementById("modal-essay").style.display = "none";
    });
  });

  document.getElementById("btn-essay-edit").addEventListener("click", () => {
    const customText = document.getElementById("modal-essay-text").value;
    fetch("/api/autofill/essay", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ choice: "edit", text: customText }),
    }).then(() => {
      document.getElementById("modal-essay").style.display = "none";
    });
  });

  document.getElementById("btn-essay-skip").addEventListener("click", () => {
    fetch("/api/autofill/essay", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ choice: "skip" }),
    }).then(() => {
      document.getElementById("modal-essay").style.display = "none";
    });
  });

  // Final Submit Handlers
  document.getElementById("btn-final-submit").addEventListener("click", () => {
    fetch("/api/autofill/submit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ submit: true }),
    }).then(() => {
      showToast("Application submitted in browser!", "success");
      stopStatusPolling();
    });
  });

  document.getElementById("btn-final-leave-open").addEventListener("click", () => {
    fetch("/api/autofill/submit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ submit: false }),
    }).then(() => {
      showToast("Form finalized without submitting.", "info");
      stopStatusPolling();
    });
  });

  // 2FA Verification PIN Handler
  const btnSubmitPin = document.getElementById("btn-submit-pin");
  const pinInput = document.getElementById("modal-pin-input");
  if (btnSubmitPin) {
    btnSubmitPin.addEventListener("click", () => {
      const pinVal = pinInput ? pinInput.value.trim() : "";
      if (!pinVal) {
        showToast("Please enter the verification PIN", "warning");
        return;
      }
      btnSubmitPin.disabled = true;
      btnSubmitPin.innerText = "Submitting...";

      fetch("/api/browser/submit-pin", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pin: pinVal }),
      })
        .then((r) => {
          if (!r.ok) throw new Error("Failed to submit PIN");
          return r.json();
        })
        .then(() => {
          showToast("2FA PIN submitted to browser! Resuming...", "success");
          btnSubmitPin.disabled = false;
          btnSubmitPin.innerText = "Submit 2FA PIN 🚀";
          const pinModal = document.getElementById("modal-pin");
          if (pinModal) {
            pinModal.style.display = "none";
            pinModal.classList.add("hidden");
          }
          if (pinInput) pinInput.value = "";
        })
        .catch((err) => {
          btnSubmitPin.disabled = false;
          btnSubmitPin.innerText = "Submit 2FA PIN 🚀";
          showToast("Error submitting PIN: " + err.message, "error");
        });
    });

    if (pinInput) {
      pinInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          btnSubmitPin.click();
        }
      });
    }
  }
}

function renderScorecard(data) {
  const container = document.getElementById("scorecard-container");
  container.style.display = "block";

  document.getElementById("job-company-badge").innerText = data.company || "Company";
  document.getElementById("job-title-display").innerText = data.job_title || "Position";
  document.getElementById("job-desc-text").innerText = data.description || "No description text extracted.";

  const imgEl = document.getElementById("job-screenshot-img");
  const wrapperEl = document.getElementById("job-screenshot-wrapper");
  if (data.initial_screenshot) {
    imgEl.src = data.initial_screenshot;
    wrapperEl.style.display = "block";
  } else {
    wrapperEl.style.display = "none";
  }

  const score = data.score || {};
  const chance = score.estimated_callback_chance || 0;
  const chanceEl = document.getElementById("score-chance-val");
  const circleEl = document.getElementById("score-chance-badge");

  chanceEl.innerText = `${chance}%`;
  if (chance >= 65) {
    circleEl.style.borderColor = "#16a34a";
    circleEl.style.boxShadow = "4px 4px 0px #16a34a";
    chanceEl.style.color = "#16a34a";
  } else if (chance >= 35) {
    circleEl.style.borderColor = "#ca8a04";
    circleEl.style.boxShadow = "4px 4px 0px #ca8a04";
    chanceEl.style.color = "#ca8a04";
  } else {
    circleEl.style.borderColor = "#dc2626";
    circleEl.style.boxShadow = "4px 4px 0px #dc2626";
    chanceEl.style.color = "#dc2626";
  }

  const rec = score.recommendation || "BORDERLINE";
  const recBanner = document.getElementById("rec-banner");
  document.getElementById("score-recommendation-val").innerText = rec;
  if (rec === "STRONG FIT") {
    recBanner.style.backgroundColor = "#bbf7d0";
    recBanner.style.borderColor = "#16a34a";
  } else if (rec === "BORDERLINE") {
    recBanner.style.backgroundColor = "#fef08a";
    recBanner.style.borderColor = "#ca8a04";
  } else {
    recBanner.style.backgroundColor = "#fecdd3";
    recBanner.style.borderColor = "#e11d48";
  }

  // Dealbreakers
  const dbBox = document.getElementById("dealbreakers-box");
  const dbList = document.getElementById("dealbreakers-list");
  dbList.innerHTML = "";
  if (score.dealbreakers && score.dealbreakers.length > 0) {
    dbBox.style.display = "block";
    score.dealbreakers.forEach((item) => {
      const li = document.createElement("li");
      li.innerText = item;
      dbList.appendChild(li);
    });
  } else {
    dbBox.style.display = "none";
  }

  // Brutal Reality
  const brList = document.getElementById("brutal-reality-list");
  brList.innerHTML = "";
  (score.brutal_reality || []).forEach((item) => {
    const li = document.createElement("li");
    li.innerText = item;
    brList.appendChild(li);
  });

  // Strengths
  const stList = document.getElementById("strengths-list");
  stList.innerHTML = "";
  (score.strengths || []).forEach((item) => {
    const li = document.createElement("li");
    li.innerText = item;
    stList.appendChild(li);
  });
}

function startStatusPolling() {
  if (statusPollInterval) clearInterval(statusPollInterval);

  statusPollInterval = setInterval(() => {
    fetch("/api/status")
      .then((r) => r.json())
      .then((session) => {
        handleSessionUpdate(session);
      })
      .catch(() => {});
  }, 900);
}

function stopStatusPolling() {
  if (statusPollInterval) {
    clearInterval(statusPollInterval);
    statusPollInterval = null;
  }
}

function handleSessionUpdate(session) {
  // Update Live Fill Steps Table
  const tbody = document.getElementById("fill-steps-body");
  if (session.fill_steps && session.fill_steps.length > 0) {
    tbody.innerHTML = "";
    session.fill_steps.forEach((step) => {
      const tr = document.createElement("tr");
      const badgeClass =
        step.status === "FILLED"
          ? "badge-success"
          : step.status === "SKIPPED"
          ? "badge-warning"
          : "badge-danger";

      tr.innerHTML = `
        <td style="color: var(--text-muted); font-family: var(--font-mono); font-size:11px;">${step.time || ""}</td>
        <td><strong>${escapeHtml(step.field)}</strong></td>
        <td><span class="badge ${badgeClass}">${step.status}</span></td>
        <td style="color: var(--text-secondary);">${escapeHtml(step.value || "-")}</td>
      `;
      tbody.appendChild(tr);
    });
  }

  // Handle Waiting for Question
  const qModal = document.getElementById("modal-question");
  if (session.status === "waiting_for_input" && session.pending_question) {
    qModal.style.display = "flex";
    document.getElementById("modal-q-label").innerText = `"${session.pending_question.label}"`;
    document.getElementById("modal-q-input").value = "";

    const optsContainer = document.getElementById("modal-q-options-container");
    const optsList = document.getElementById("modal-q-options-list");
    optsList.innerHTML = "";

    if (session.pending_question.options && session.pending_question.options.length > 0) {
      optsContainer.style.display = "block";
      session.pending_question.options.forEach((opt) => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "option-pill-btn";
        btn.innerText = opt;
        btn.onclick = () => {
          document.getElementById("modal-q-input").value = opt;
        };
        optsList.appendChild(btn);
      });
    } else {
      optsContainer.style.display = "none";
    }
  } else if (session.status !== "waiting_for_input") {
    qModal.style.display = "none";
  }

  // Handle Waiting for Essay
  const essayModal = document.getElementById("modal-essay");
  if (session.status === "waiting_for_essay" && session.pending_essay) {
    essayModal.style.display = "flex";
    document.getElementById("modal-essay-question").innerText = `"${session.pending_essay.question}"`;
    document.getElementById("modal-essay-text").value = session.pending_essay.draft || "";
  } else if (session.status !== "waiting_for_essay") {
    essayModal.style.display = "none";
  }

  // Handle Waiting for 2FA Verification PIN
  const pinModal = document.getElementById("modal-pin");
  if (session.status === "waiting_for_pin") {
    if (pinModal) {
      pinModal.style.display = "flex";
      pinModal.classList.remove("hidden");
      if (session.pending_pin) {
        const promptEl = document.getElementById("modal-pin-prompt");
        if (promptEl) promptEl.innerText = session.pending_pin;
      }
      const pinInput = document.getElementById("modal-pin-input");
      if (pinInput && document.activeElement !== pinInput) {
        pinInput.focus();
      }
    }
  } else if (pinModal && session.status !== "waiting_for_pin") {
    pinModal.style.display = "none";
    pinModal.classList.add("hidden");
  }

  // Handle Review Ready (Pre-Flight Review)
  if (session.status === "review_ready") {
    document.getElementById("autofill-progress-container").style.display = "none";
    const preflight = document.getElementById("preflight-container");
    preflight.style.display = "block";

    document.getElementById("stat-filled").innerText = session.summary.filled || 0;
    document.getElementById("stat-skipped").innerText = session.summary.skipped || 0;
    document.getElementById("stat-qa-added").innerText = session.summary.added || 0;

    if (session.post_screenshot) {
      document.getElementById("post-fill-screenshot-img").src = session.post_screenshot;
    }
  }

  // Handle Completed or Error
  if (session.status === "completed") {
    showToast("Application lifecycle complete!", "success");
    stopStatusPolling();
  } else if (session.status === "error") {
    showToast(`Error: ${session.error_message}`, "error");
    stopStatusPolling();
  }
}

// =========================================================================
// PROFILE TAB
// =========================================================================

function initProfile() {
  document.getElementById("btn-save-profile").addEventListener("click", () => {
    const updated = {
      personal: {
        first_name: document.getElementById("prof-first-name").value.trim(),
        last_name: document.getElementById("prof-last-name").value.trim(),
        full_name: document.getElementById("prof-full-name").value.trim(),
        email: document.getElementById("prof-email").value.trim(),
        phone: document.getElementById("prof-phone").value.trim(),
        address: document.getElementById("prof-address").value.trim(),
        city: document.getElementById("prof-city").value.trim(),
        state: document.getElementById("prof-state").value.trim(),
        postal_code: document.getElementById("prof-postal").value.trim(),
      },
      links: {
        linkedin: document.getElementById("prof-linkedin").value.trim(),
        github: document.getElementById("prof-github").value.trim(),
        portfolio: document.getElementById("prof-portfolio").value.trim(),
      },
      authorization: {
        us_work_authorized: document.getElementById("prof-auth-us").value,
        requires_sponsorship: document.getElementById("prof-auth-sponsorship").value,
        security_clearance: document.getElementById("prof-auth-clearance").value,
      },
      skills: document
        .getElementById("prof-skills")
        .value.split(",")
        .map((s) => s.trim())
        .filter(Boolean),
      resume_file: document.getElementById("prof-resume-file").value.trim(),
      preferences: {
        desired_salary: document.getElementById("prof-salary").value.trim(),
        notice_period: document.getElementById("prof-notice").value.trim(),
      },
    };

    fetch("/api/profile", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(updated),
    })
      .then((r) => r.json())
      .then(() => showToast("Profile saved successfully!", "success"))
      .catch(() => showToast("Failed to save profile", "error"));
  });
}

function loadProfile() {
  fetch("/api/profile")
    .then((r) => r.json())
    .then((p) => {
      const pers = p.personal || {};
      document.getElementById("prof-first-name").value = pers.first_name || "";
      document.getElementById("prof-last-name").value = pers.last_name || "";
      document.getElementById("prof-full-name").value = pers.full_name || "";
      document.getElementById("prof-email").value = pers.email || "";
      document.getElementById("prof-phone").value = pers.phone || "";
      document.getElementById("prof-address").value = pers.address || "";
      document.getElementById("prof-city").value = pers.city || "";
      document.getElementById("prof-state").value = pers.state || "";
      document.getElementById("prof-postal").value = pers.postal_code || "";

      const links = p.links || {};
      document.getElementById("prof-linkedin").value = links.linkedin || "";
      document.getElementById("prof-github").value = links.github || "";
      document.getElementById("prof-portfolio").value = links.portfolio || "";

      const auth = p.authorization || {};
      document.getElementById("prof-auth-us").value = auth.us_work_authorized || "Yes";
      document.getElementById("prof-auth-sponsorship").value = auth.requires_sponsorship || "No";
      document.getElementById("prof-auth-clearance").value = auth.security_clearance || "None";

      document.getElementById("prof-skills").value = (p.skills || []).join(", ");
      document.getElementById("prof-resume-file").value = p.resume_file || "sample_resume.pdf";
      const activeBadge = document.getElementById("active-resume-badge");
      if (activeBadge) activeBadge.innerText = p.resume_file || "sample_resume.pdf";

      const pref = p.preferences || {};
      document.getElementById("prof-salary").value = pref.desired_salary || "";
      document.getElementById("prof-notice").value = pref.notice_period || "";
    });
}

// =========================================================================
// QA BANK TAB
// =========================================================================

function initQABank() {
  const searchInput = document.getElementById("qa-search-input");
  searchInput.addEventListener("input", (e) => {
    const q = e.target.value.toLowerCase();
    document.querySelectorAll("#qa-table-body tr").forEach((tr) => {
      const text = tr.innerText.toLowerCase();
      tr.style.display = text.includes(q) ? "" : "none";
    });
  });

  const modal = document.getElementById("modal-add-qa");
  document.getElementById("btn-open-add-qa-modal").addEventListener("click", () => {
    modal.style.display = "flex";
    document.getElementById("add-qa-question").value = "";
    document.getElementById("add-qa-answer").value = "";
  });

  document.getElementById("btn-cancel-new-qa").addEventListener("click", () => {
    modal.style.display = "none";
  });

  document.getElementById("btn-save-new-qa").addEventListener("click", () => {
    const question = document.getElementById("add-qa-question").value.trim();
    const answer = document.getElementById("add-qa-answer").value.trim();
    const fieldType = document.getElementById("add-qa-type").value;
    const category = document.getElementById("add-qa-category").value.trim();

    if (!question || !answer) {
      showToast("Question and answer are required.", "warning");
      return;
    }

    fetch("/api/qa", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question: question,
        answer: answer,
        field_type: fieldType,
        category: category,
      }),
    })
      .then((r) => r.json())
      .then(() => {
        modal.style.display = "none";
        loadQABank();
        showToast("New Q&A pair added to knowledge bank!", "success");
      });
  });
}

function loadQABank() {
  fetch("/api/qa")
    .then((r) => r.json())
    .then((entries) => {
      const tbody = document.getElementById("qa-table-body");
      tbody.innerHTML = "";
      entries.forEach((item) => {
        const tr = document.createElement("tr");
        const patsHtml = (item.question_patterns || [])
          .slice(0, 3)
          .map((p) => `<div style="font-size:12px; color:var(--text-secondary);">• ${escapeHtml(p)}</div>`)
          .join("");

        tr.innerHTML = `
          <td><span class="badge badge-info">${escapeHtml(item.category || "custom")}</span></td>
          <td>${patsHtml}</td>
          <td><strong style="color:var(--accent-success);">${escapeHtml(item.answer)}</strong></td>
          <td><code style="font-size:11px;">${item.field_type || "text"}</code></td>
          <td>
            <button class="btn btn-sm btn-outline btn-delete-qa" data-id="${item.id}">Delete</button>
          </td>
        `;

        tr.querySelector(".btn-delete-qa").onclick = () => {
          if (confirm("Delete this Q&A entry?")) {
            fetch(`/api/qa/${item.id}`, { method: "DELETE" }).then(() => loadQABank());
          }
        };

        tbody.appendChild(tr);
      });
    });
}

// =========================================================================
// HISTORY TAB
// =========================================================================

function initHistory() {}

function loadHistory() {
  fetch("/api/history")
    .then((r) => r.json())
    .then((logs) => {
      const tbody = document.getElementById("history-table-body");
      tbody.innerHTML = "";
      if (logs.length === 0) {
        tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; color:var(--text-muted); padding: 24px;">No applications logged yet.</td></tr>`;
        return;
      }

      logs.forEach((log) => {
        const tr = document.createElement("tr");
        const dateStr = log.applied_at ? log.applied_at.substring(0, 19).replace("T", " ") : "-";
        const scoreBadge =
          log.match_score >= 65
            ? "badge-success"
            : log.match_score >= 35
            ? "badge-warning"
            : "badge-danger";

        const screenshotUrl = log.screenshot_path
          ? `/screenshots/${log.screenshot_path.split('\\').pop().split('/').pop()}`
          : "";

        tr.innerHTML = `
          <td style="color:var(--text-muted); font-family: var(--font-mono); font-size:12px;">${dateStr}</td>
          <td><strong>${escapeHtml(log.company)}</strong></td>
          <td>${escapeHtml(log.job_title)}</td>
          <td><span class="badge ${scoreBadge}">${Math.round(log.match_score)}%</span></td>
          <td><span class="badge badge-info">${log.status}</span></td>
          <td>
            ${
              screenshotUrl
                ? `<button class="btn btn-sm btn-outline btn-view-history-screen" data-src="${screenshotUrl}" data-title="${escapeHtml(log.job_title)} at ${escapeHtml(log.company)}">🔍 View Screen</button>`
                : "-"
            }
          </td>
        `;

        if (screenshotUrl) {
          tr.querySelector(".btn-view-history-screen").onclick = (e) => {
            const target = e.currentTarget;
            openScreenshotLightbox(target.getAttribute("data-src"), target.getAttribute("data-title"));
          };
        }

        tbody.appendChild(tr);
      });
    });
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

// =========================================================================
// FIRST-TIME SETUP WIZARD & RESUME PARSING
// =========================================================================

let wizardUploadedFilename = "sample_resume.pdf";

function initSetupWizard() {
  const modal = document.getElementById("modal-setup-wizard");
  const btnReopen = document.getElementById("btn-reopen-setup");
  const btnSkip = document.getElementById("btn-skip-setup");
  const btnComplete = document.getElementById("btn-complete-setup");
  const dropzone = document.getElementById("wizard-resume-dropzone");
  const fileInput = document.getElementById("wizard-resume-file-input");
  const btnBrowse = document.getElementById("btn-browse-wizard-resume");
  const statusPill = document.getElementById("setup-status-pill");

  // Check setup status on load
  fetch("/api/setup/status")
    .then((r) => r.json())
    .then((data) => {
      if (data.is_setup_completed) {
        if (statusPill) {
          statusPill.innerText = "READY";
          statusPill.style.backgroundColor = "var(--accent-green)";
          statusPill.style.color = "var(--ink)";
        }
      } else {
        if (statusPill) {
          statusPill.innerText = "SETUP";
          statusPill.style.backgroundColor = "var(--accent-yellow)";
          statusPill.style.color = "var(--ink)";
        }
        // Auto-open wizard on first time
        modal.style.display = "flex";
      }
    })
    .catch(() => {});

  // Pre-fill Step 3 QA Knowledge Bank fields from existing database
  fetch("/api/qa")
    .then((r) => r.json())
    .then((entries) => {
      const qaMap = {};
      entries.forEach((e) => { qaMap[e.id] = e.answer; });
      if (qaMap["work_authorization_us"]) document.getElementById("wiz-qa-auth").value = qaMap["work_authorization_us"];
      if (qaMap["sponsorship_requirement"]) document.getElementById("wiz-qa-sponsorship").value = qaMap["sponsorship_requirement"];
      if (qaMap["clearance_status"]) document.getElementById("wiz-qa-clearance").value = qaMap["clearance_status"];
      if (qaMap["notice_period"]) document.getElementById("wiz-qa-notice").value = qaMap["notice_period"];
      if (qaMap["salary_expectations"]) document.getElementById("wiz-qa-salary").value = qaMap["salary_expectations"];
      if (qaMap["years_of_experience"]) document.getElementById("wiz-qa-yoe").value = qaMap["years_of_experience"];
      if (qaMap["remote_work_comfort"]) document.getElementById("wiz-qa-remote").value = qaMap["remote_work_comfort"];
      if (qaMap["background_check_consent"]) document.getElementById("wiz-qa-background").value = qaMap["background_check_consent"];
      if (qaMap["eeoc_gender"]) document.getElementById("wiz-qa-gender").value = qaMap["eeoc_gender"];
      if (qaMap["eeoc_veteran"]) document.getElementById("wiz-qa-veteran").value = qaMap["eeoc_veteran"];
      if (qaMap["eeoc_disability"]) document.getElementById("wiz-qa-disability").value = qaMap["eeoc_disability"];
    })
    .catch(() => {});

  // Re-open wizard button
  if (btnReopen) {
    btnReopen.addEventListener("click", () => {
      modal.style.display = "flex";
    });
  }

  // Skip setup
  if (btnSkip) {
    btnSkip.addEventListener("click", () => {
      modal.style.display = "none";
      showToast("Setup skipped. You can configure your profile anytime in Master Profile.", "info");
    });
  }

  // Browse files
  if (btnBrowse) {
    btnBrowse.addEventListener("click", (e) => {
      e.stopPropagation();
      fileInput.click();
    });
  }

  if (dropzone) {
    dropzone.addEventListener("click", () => {
      fileInput.click();
    });

    fileInput.addEventListener("change", () => {
      if (fileInput.files && fileInput.files[0]) {
        handleWizardResumeUpload(fileInput.files[0]);
      }
    });

    // Drag and drop events for wizard
    ["dragenter", "dragover"].forEach((eventName) => {
      dropzone.addEventListener(eventName, (e) => {
        e.preventDefault();
        e.stopPropagation();
        dropzone.classList.add("drag-over");
      });
    });

    ["dragleave", "drop"].forEach((eventName) => {
      dropzone.addEventListener(eventName, (e) => {
        e.preventDefault();
        e.stopPropagation();
        dropzone.classList.remove("drag-over");
      });
    });

    dropzone.addEventListener("drop", (e) => {
      if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0]) {
        handleWizardResumeUpload(e.dataTransfer.files[0]);
      }
    });
  }

  // Complete setup handler
  if (btnComplete) {
    btnComplete.addEventListener("click", () => {
      const loc = document.getElementById("wiz-location").value.trim();
      let city = "";
      let state = "";
      if (loc.includes(",")) {
        const parts = loc.split(",");
        city = parts[0].trim();
        state = parts[1].trim();
      } else {
        city = loc;
      }

      const qa_answers = {
        "work_authorization_us": document.getElementById("wiz-qa-auth").value,
        "sponsorship_requirement": document.getElementById("wiz-qa-sponsorship").value,
        "clearance_status": document.getElementById("wiz-qa-clearance").value,
        "notice_period": document.getElementById("wiz-qa-notice").value.trim(),
        "salary_expectations": document.getElementById("wiz-qa-salary").value.trim(),
        "years_of_experience": document.getElementById("wiz-qa-yoe").value.trim(),
        "remote_work_comfort": document.getElementById("wiz-qa-remote").value,
        "background_check_consent": document.getElementById("wiz-qa-background").value,
        "eeoc_gender": document.getElementById("wiz-qa-gender").value,
        "eeoc_veteran": document.getElementById("wiz-qa-veteran").value,
        "eeoc_disability": document.getElementById("wiz-qa-disability").value,
      };

      const customQ = document.getElementById("wiz-custom-q").value.trim();
      const customA = document.getElementById("wiz-custom-a").value.trim();
      const custom_qa = [];
      if (customQ && customA) {
        custom_qa.push({ question: customQ, answer: customA, field_type: "text", category: "custom" });
      }

      const payload = {
        profile: {
          personal: {
            first_name: document.getElementById("wiz-first-name").value.trim(),
            last_name: document.getElementById("wiz-last-name").value.trim(),
            full_name: document.getElementById("wiz-full-name").value.trim(),
            email: document.getElementById("wiz-email").value.trim(),
            phone: document.getElementById("wiz-phone").value.trim(),
            address: "",
            city: city,
            state: state,
            postal_code: "",
            country: "United States",
          },
          links: {
            linkedin: document.getElementById("wiz-linkedin").value.trim(),
            github: document.getElementById("wiz-github").value.trim(),
            portfolio: document.getElementById("wiz-portfolio").value.trim(),
          },
          skills: document.getElementById("wiz-skills").value
            .split(",")
            .map((s) => s.trim())
            .filter(Boolean),
          authorization: {
            us_work_authorized: document.getElementById("wiz-qa-auth").value,
            requires_sponsorship: document.getElementById("wiz-qa-sponsorship").value,
            security_clearance: document.getElementById("wiz-qa-clearance").value,
          },
          preferences: {
            desired_salary: document.getElementById("wiz-qa-salary").value.trim(),
            notice_period: document.getElementById("wiz-qa-notice").value.trim(),
          },
          resume_file: wizardUploadedFilename,
        },
        qa_answers: qa_answers,
        custom_qa: custom_qa,
      };

      btnComplete.disabled = true;
      btnComplete.innerText = "Saving Profile & QA Bank...";

      fetch("/api/setup/complete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
        .then((r) => r.json())
        .then(() => {
          btnComplete.disabled = false;
          btnComplete.innerText = "Save Everything & Launch ApplyFlow 🚀";
          modal.style.display = "none";
          if (statusPill) {
            statusPill.innerText = "READY";
            statusPill.style.backgroundColor = "var(--accent-green)";
            statusPill.style.color = "var(--ink)";
          }
          showToast("Setup complete! Master Profile and QA Knowledge Bank saved permanently.", "success");
          loadProfile();
          loadQABank();
        })
        .catch((err) => {
          btnComplete.disabled = false;
          btnComplete.innerText = "Save Everything & Launch ApplyFlow 🚀";
          showToast("Error saving setup: " + err.message, "error");
        });
    });
  }
}

function handleWizardResumeUpload(file) {
  const statusEl = document.getElementById("wizard-upload-status");
  const msgEl = document.getElementById("wizard-upload-msg");
  const bannerEl = document.getElementById("wizard-parsed-banner");
  const summaryEl = document.getElementById("wizard-parsed-summary");
  const stepPill = document.getElementById("wizard-step-pill");

  statusEl.style.display = "flex";
  bannerEl.style.display = "none";
  msgEl.innerText = `Uploading '${file.name}' & extracting with local AI...`;

  const formData = new FormData();
  formData.append("file", file);

  fetch("/api/resume/upload", {
    method: "POST",
    body: formData,
  })
    .then((r) => {
      if (!r.ok) throw new Error("Resume upload failed.");
      return r.json();
    })
    .then((data) => {
      statusEl.style.display = "none";
      wizardUploadedFilename = data.filename;

      const prof = data.profile || {};
      const pers = prof.personal || {};
      const links = prof.links || {};
      const pref = prof.preferences || {};
      const auth = prof.authorization || {};

      document.getElementById("wiz-first-name").value = pers.first_name || "";
      document.getElementById("wiz-last-name").value = pers.last_name || "";
      document.getElementById("wiz-full-name").value = pers.full_name || "";
      document.getElementById("wiz-email").value = pers.email || "";
      document.getElementById("wiz-phone").value = pers.phone || "";

      let loc = pers.city || "";
      if (pers.state) loc += (loc ? ", " : "") + pers.state;
      document.getElementById("wiz-location").value = loc;

      document.getElementById("wiz-linkedin").value = links.linkedin || "";
      document.getElementById("wiz-github").value = links.github || "";
      document.getElementById("wiz-portfolio").value = links.portfolio || "";

      document.getElementById("wiz-skills").value = (prof.skills || []).join(", ");
      
      // Sync QA fields if extracted
      if (pref.desired_salary) document.getElementById("wiz-qa-salary").value = pref.desired_salary;
      if (pref.notice_period) document.getElementById("wiz-qa-notice").value = pref.notice_period;
      if (auth.us_work_authorized) document.getElementById("wiz-qa-auth").value = auth.us_work_authorized;
      if (auth.requires_sponsorship) document.getElementById("wiz-qa-sponsorship").value = auth.requires_sponsorship;

      summaryEl.innerText = `✓ Successfully extracted '${data.filename}'! Candidate: ${pers.full_name || 'Extracted'}, Skills: ${(prof.skills || []).length} identified.`;
      bannerEl.style.display = "block";
      stepPill.innerText = "STEP 2: REVIEW & SAVE";
      stepPill.className = "badge badge-success";

      showToast(`Resume '${data.filename}' extracted! Please review fields below.`, "success");
    })
    .catch((err) => {
      statusEl.style.display = "none";
      showToast("Resume parsing error: " + err.message, "error");
    });
}

function initProfileResumeUpload() {
  const dropzone = document.getElementById("profile-resume-dropzone");
  const fileInput = document.getElementById("profile-resume-file-input");
  const btnBrowse = document.getElementById("btn-browse-profile-resume");
  const statusEl = document.getElementById("profile-upload-status");
  const activeBadge = document.getElementById("active-resume-badge");

  if (!dropzone) return;

  btnBrowse.addEventListener("click", (e) => {
    e.stopPropagation();
    fileInput.click();
  });

  dropzone.addEventListener("click", () => {
    fileInput.click();
  });

  fileInput.addEventListener("change", () => {
    if (fileInput.files && fileInput.files[0]) {
      handleProfileResumeUpload(fileInput.files[0]);
    }
  });

  ["dragenter", "dragover"].forEach((eventName) => {
    dropzone.addEventListener(eventName, (e) => {
      e.preventDefault();
      e.stopPropagation();
      dropzone.classList.add("drag-over");
    });
  });

  ["dragleave", "drop"].forEach((eventName) => {
    dropzone.addEventListener(eventName, (e) => {
      e.preventDefault();
      e.stopPropagation();
      dropzone.classList.remove("drag-over");
    });
  });

  dropzone.addEventListener("drop", (e) => {
    if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleProfileResumeUpload(e.dataTransfer.files[0]);
    }
  });

  function handleProfileResumeUpload(file) {
    statusEl.style.display = "flex";
    const msgEl = document.getElementById("profile-upload-msg");
    msgEl.innerText = `Uploading '${file.name}' & extracting profile with local AI...`;

    const formData = new FormData();
    formData.append("file", file);

    fetch("/api/resume/upload", {
      method: "POST",
      body: formData,
    })
      .then((r) => {
        if (!r.ok) throw new Error("Upload failed.");
        return r.json();
      })
      .then((data) => {
        statusEl.style.display = "none";
        if (activeBadge) activeBadge.innerText = data.filename;
        document.getElementById("prof-resume-file").value = data.filename;

        const prof = data.profile || {};
        const pers = prof.personal || {};
        const links = prof.links || {};
        const pref = prof.preferences || {};
        const auth = prof.authorization || {};

        if (pers.first_name) document.getElementById("prof-first-name").value = pers.first_name;
        if (pers.last_name) document.getElementById("prof-last-name").value = pers.last_name;
        if (pers.full_name) document.getElementById("prof-full-name").value = pers.full_name;
        if (pers.email) document.getElementById("prof-email").value = pers.email;
        if (pers.phone) document.getElementById("prof-phone").value = pers.phone;
        if (pers.city) document.getElementById("prof-city").value = pers.city;
        if (pers.state) document.getElementById("prof-state").value = pers.state;
        if (pers.postal_code) document.getElementById("prof-postal").value = pers.postal_code;

        if (links.linkedin) document.getElementById("prof-linkedin").value = links.linkedin;
        if (links.github) document.getElementById("prof-github").value = links.github;
        if (links.portfolio) document.getElementById("prof-portfolio").value = links.portfolio;

        if (prof.skills && prof.skills.length > 0) {
          document.getElementById("prof-skills").value = prof.skills.join(", ");
        }
        if (pref.desired_salary) document.getElementById("prof-salary").value = pref.desired_salary;
        if (pref.notice_period) document.getElementById("prof-notice").value = pref.notice_period;

        if (auth.us_work_authorized) document.getElementById("prof-auth-us").value = auth.us_work_authorized;
        if (auth.requires_sponsorship) document.getElementById("prof-auth-sponsorship").value = auth.requires_sponsorship;

        showToast(`Resume '${data.filename}' uploaded and auto-extracted! Click 'Save Profile Changes' to persist.`, "success");
      })
      .catch((err) => {
        statusEl.style.display = "none";
        showToast("Resume parsing failed: " + err.message, "error");
      });
  }
}

// =========================================================================
// BROWSER LOGIN & PERSISTENT SESSION MANAGER
// =========================================================================

function loadCredentialsStatus() {
  fetch("/api/credentials/status")
    .then((r) => r.json())
    .then((data) => {
      const statusText = document.getElementById("env-creds-status-text");
      const liEmail = document.getElementById("env-cred-linkedin-email");
      const indEmail = document.getElementById("env-cred-indeed-email");

      if (data.linkedin_email && liEmail && !liEmail.value) {
        liEmail.value = data.linkedin_email;
      }
      if (data.indeed_email && indEmail && !indEmail.value) {
        indEmail.value = data.indeed_email;
      }

      if (statusText) {
        const liStatus = data.has_linkedin ? "LinkedIn: ✓ Saved" : "LinkedIn: ⚠ Not Set";
        const indStatus = data.has_indeed ? "Indeed: ✓ Saved" : "Indeed: ⚠ Not Set";
        statusText.innerText = `${liStatus} · ${indStatus}`;
        statusText.style.color = (data.has_linkedin || data.has_indeed) ? "#16a34a" : "var(--text-muted)";
      }
    })
    .catch(() => {});
}

function openBrowserAuthModal() {
  const modal = document.getElementById("modal-browser-login");
  if (modal) {
    modal.classList.remove("hidden");
    modal.style.display = "flex";
  }
  checkBrowserAuthStatus();
  loadCredentialsStatus();
}

function closeBrowserAuthModal() {
  const modal = document.getElementById("modal-browser-login");
  if (modal) {
    modal.classList.add("hidden");
    modal.style.display = "none";
  }
}

function checkBrowserAuthStatus() {
  fetch("/api/browser/status")
    .then((r) => r.json())
    .then((data) => {
      const activeBox = document.getElementById("active-browser-controls");
      if (activeBox) {
        activeBox.style.display = data.is_active ? "flex" : "none";
      }
    })
    .catch(() => {});
}

function initBrowserAuthManager() {
  const btnOpenAuth = document.getElementById("btn-open-browser-auth");
  const btnQuickLogin = document.getElementById("btn-quick-login");
  const btnCloseModal = document.getElementById("btn-close-browser-modal");
  const modal = document.getElementById("modal-browser-login");

  if (btnOpenAuth) {
    btnOpenAuth.addEventListener("click", openBrowserAuthModal);
  }
  if (btnQuickLogin) {
    btnQuickLogin.addEventListener("click", openBrowserAuthModal);
  }
  if (btnCloseModal) {
    btnCloseModal.addEventListener("click", closeBrowserAuthModal);
  }
  if (modal) {
    modal.addEventListener("click", (e) => {
      if (e.target === modal) closeBrowserAuthModal();
    });
  }

  // Load credentials status initially
  loadCredentialsStatus();

  // Save Credentials to .env Button
  const btnSaveEnvCreds = document.getElementById("btn-save-env-creds");
  if (btnSaveEnvCreds) {
    btnSaveEnvCreds.addEventListener("click", () => {
      const liEmail = document.getElementById("env-cred-linkedin-email").value.trim();
      const liPwd = document.getElementById("env-cred-linkedin-pwd").value.trim();
      const indEmail = document.getElementById("env-cred-indeed-email").value.trim();
      const indPwd = document.getElementById("env-cred-indeed-pwd").value.trim();

      const payload = {};
      if (liEmail) payload.linkedin_email = liEmail;
      if (liPwd) payload.linkedin_password = liPwd;
      if (indEmail) payload.indeed_email = indEmail;
      if (indPwd) payload.indeed_password = indPwd;

      if (Object.keys(payload).length === 0) {
        showToast("Please enter at least an email or password to save", "warning");
        return;
      }

      btnSaveEnvCreds.disabled = true;
      btnSaveEnvCreds.innerText = "Saving...";

      fetch("/api/credentials/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
        .then((r) => r.json())
        .then((res) => {
          btnSaveEnvCreds.disabled = false;
          btnSaveEnvCreds.innerText = "💾 Save Credentials to .env";
          showToast(`Saved to .env (${res.updated.join(", ")})!`, "success");
          loadCredentialsStatus();
        })
        .catch((err) => {
          btnSaveEnvCreds.disabled = false;
          btnSaveEnvCreds.innerText = "💾 Save Credentials to .env";
          showToast("Error saving credentials: " + err.message, "error");
        });
    });
  }

  // Test Auto-Login LinkedIn Button
  const btnTestAutoLinkedin = document.getElementById("btn-test-auto-linkedin");
  if (btnTestAutoLinkedin) {
    btnTestAutoLinkedin.addEventListener("click", () => {
      showToast("Launching browser with .env credentials for LinkedIn...", "info");
      fetch("/api/browser/open-login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url: "https://www.linkedin.com/login",
          platform: "LinkedIn",
        }),
      })
        .then((r) => r.json())
        .then(() => {
          const activeBox = document.getElementById("active-browser-controls");
          if (activeBox) activeBox.style.display = "flex";
          showToast("Chromium opened! Logged-in session will persist automatically.", "success");
        })
        .catch((err) => {
          showToast("Failed launching browser: " + err.message, "error");
        });
    });
  }

  // LinkedIn Login Trigger
  const btnLoginLinkedin = document.getElementById("btn-login-linkedin");
  if (btnLoginLinkedin) {
    btnLoginLinkedin.addEventListener("click", () => {
      showToast("Launching Chromium for LinkedIn login...", "info");
      fetch("/api/browser/open-login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url: "https://www.linkedin.com/login",
          platform: "LinkedIn",
        }),
      })
        .then((r) => r.json())
        .then(() => {
          const activeBox = document.getElementById("active-browser-controls");
          if (activeBox) activeBox.style.display = "flex";
          showToast("Chromium opened! Log into LinkedIn on screen, then click 'Done / Save Session'", "success");
        })
        .catch((err) => {
          showToast("Failed launching browser: " + err.message, "error");
        });
    });
  }

  // Indeed Login Trigger
  const btnLoginIndeed = document.getElementById("btn-login-indeed");
  if (btnLoginIndeed) {
    btnLoginIndeed.addEventListener("click", () => {
      showToast("Launching Chromium for Indeed login...", "info");
      fetch("/api/browser/open-login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url: "https://secure.indeed.com/account/login",
          platform: "Indeed",
        }),
      })
        .then((r) => r.json())
        .then(() => {
          const activeBox = document.getElementById("active-browser-controls");
          if (activeBox) activeBox.style.display = "flex";
          showToast("Chromium opened! Log into Indeed, then click 'Done / Save Session'", "success");
        })
        .catch((err) => {
          showToast("Failed launching browser: " + err.message, "error");
        });
    });
  }

  // Custom Site Login Trigger
  const btnLoginCustom = document.getElementById("btn-login-custom");
  const customUrlInput = document.getElementById("custom-auth-url");
  if (btnLoginCustom && customUrlInput) {
    btnLoginCustom.addEventListener("click", () => {
      const targetUrl = customUrlInput.value.trim();
      if (!targetUrl) {
        showToast("Please enter a custom URL to open", "warning");
        return;
      }
      showToast(`Launching Chromium for ${targetUrl}...`, "info");
      fetch("/api/browser/open-login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url: targetUrl,
          platform: "Custom Site",
        }),
      })
        .then((r) => r.json())
        .then(() => {
          const activeBox = document.getElementById("active-browser-controls");
          if (activeBox) activeBox.style.display = "flex";
          showToast("Chromium opened! Log in and click 'Done / Save Session'", "success");
        })
        .catch((err) => {
          showToast("Failed launching browser: " + err.message, "error");
        });
    });
  }

  // Done / Close Session Button
  const btnFinishLogin = document.getElementById("btn-finish-login");
  if (btnFinishLogin) {
    btnFinishLogin.addEventListener("click", () => {
      fetch("/api/browser/close-login", { method: "POST" })
        .then((r) => r.json())
        .then(() => {
          const activeBox = document.getElementById("active-browser-controls");
          if (activeBox) activeBox.style.display = "none";
          closeBrowserAuthModal();
          showToast("Session saved! Your login cookies are now remembered for all applications.", "success");
        })
        .catch((err) => {
          showToast("Error closing session: " + err.message, "error");
        });
    });
  }
}

