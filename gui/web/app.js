// ============================================================
// Shutdown Panel v2 — Desktop UI logic
// ============================================================
let currentLang = "ar";
let currentTheme = "dark";
let settings = {};
let selectedTimerAction = "shutdown";
let pendingActionToConfirm = null;
let activeCountdown = null;
let audioCtx = null;
let schedSelectedDays = [0, 1, 2, 3, 4, 5, 6];

// ------------------------------------------------------------ Sound
function playBeep(freq = 880, duration = 0.08) {
  if (!settings.sounds) return;
  try {
    const AudioCtor = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtor) return;
    audioCtx = audioCtx || new AudioCtor();
    if (audioCtx.state === "suspended") audioCtx.resume();
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    osc.type = "sine";
    osc.frequency.value = freq;
    gain.gain.value = 0.05;
    osc.connect(gain);
    gain.connect(audioCtx.destination);
    osc.start();
    osc.stop(audioCtx.currentTime + duration);
  } catch (e) {}
}

function showToast(text, kind = "info") {
  const container = document.getElementById("toastContainer");
  if (!container) return;
  const el = document.createElement("div");
  el.className = `toast toast-${kind === "ok" ? "ok" : (kind === "warn" ? "warn" : "danger")}`;
  el.textContent = text;
  container.appendChild(el);
  setTimeout(() => {
    el.style.opacity = "0";
    el.style.transform = "translateY(8px)";
    setTimeout(() => el.remove(), 200);
  }, 3200);
}

function pad(n) { return String(Math.max(0, Math.floor(n))).padStart(2, "0"); }

function formatHMS(totalSecs) {
  const s = Math.max(0, Math.floor(totalSecs));
  return `${pad(Math.floor(s / 3600))}:${pad(Math.floor((s % 3600) / 60))}:${pad(s % 60)}`;
}

function updateStartButtonState(isRunning) {
  const btn = document.getElementById("btnStartMain");
  const lbl = document.getElementById("lblStartBtn");
  const boltIcon = document.getElementById("boltIcon");
  if (!btn || !lbl) return;

  if (isRunning) {
    btn.classList.remove("cyan-glow");
    btn.classList.add("danger-glow", "btn-running");
    btn.style.borderColor = "var(--danger)";
    btn.style.color = "var(--danger)";
    lbl.textContent = t(currentLang, "cancelCountdown");
    if (boltIcon) boltIcon.innerHTML = icons.ban || `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="4.93" y1="4.93" x2="19.07" y2="19.07"/></svg>`;
  } else {
    btn.classList.remove("danger-glow", "btn-running");
    btn.classList.add("cyan-glow");
    btn.style.borderColor = "";
    btn.style.color = "";
    lbl.textContent = t(currentLang, "startCountdown");
    if (boltIcon) boltIcon.innerHTML = icons.zap;
  }
}

// ------------------------------------------------------------ Python callbacks
window.__onCountdownTick = function (state) {
  const runBox = document.getElementById("runningCountdownBox");
  if (!state || !state.action) {
    activeCountdown = null;
    if (runBox) runBox.style.display = "none";
    updateStartButtonState(false);
    return;
  }
  activeCountdown = state;
  if (runBox) runBox.style.display = "block";
  updateStartButtonState(true);

  document.getElementById("cdTimeDisplay").textContent = formatHMS(state.remainingSecs || 0);

  const total = state.totalSecs || 1;
  const rem = state.remainingSecs || 0;
  const pct = Math.max(0, Math.min(100, ((total - rem) / total) * 100));
  document.getElementById("cdProgressBar").style.width = `${pct}%`;

  const btnPause = document.getElementById("lblBtnPause");
  if (state.paused) {
    if (btnPause) btnPause.textContent = t(currentLang, "resume");
    const pIco = document.getElementById("cdPauseIcon");
    if (pIco) pIco.innerHTML = icons.play;
  } else {
    if (btnPause) btnPause.textContent = t(currentLang, "pause");
    const pIco = document.getElementById("cdPauseIcon");
    if (pIco) pIco.innerHTML = icons.pause;
  }
};

window.__onToast = function (msg, kind) {
  showToast(msg, kind);
  if (kind === "warn") playBeep(880, 0.15);
  else if (kind === "ok") playBeep(520, 0.1);
};

// ------------------------------------------------------------ Time options
function populateTimeOptions() {
  const selH = document.getElementById("selectHours");
  const selM = document.getElementById("selectMinutes");
  selH.innerHTML = "";
  selM.innerHTML = "";
  for (let i = 0; i <= 24; i++) {
    const opt = document.createElement("option");
    opt.value = i;
    opt.textContent = `${pad(i)} ${t(currentLang, "hourUnit")}`;
    selH.appendChild(opt);
  }
  for (let i = 0; i <= 59; i++) {
    const opt = document.createElement("option");
    opt.value = i;
    opt.textContent = `${pad(i)} ${t(currentLang, "minuteUnit")}`;
    if (i === 5) opt.selected = true;
    selM.appendChild(opt);
  }
}

// ------------------------------------------------------------ Icons
function setIcon(id, iconHtml) {
  const el = document.getElementById(id);
  if (el) el.innerHTML = iconHtml;
}

function renderAllIcons() {
  setIcon("brandPowerIcon", icons.power);
  setIcon("headerPowerIcon", icons.power);
  setIcon("minIcon", icons.minus);
  setIcon("closeIcon", icons.close);
  setIcon("aboutIcon", icons.info);
  setIcon("aboutCloseIcon", icons.close);
  setIcon("themeIcon", currentTheme === "dark"
    ? `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>`
    : icons.sleep);
  setIcon("tabIconTimer", icons.clock);
  setIcon("tabIconRemote", icons.remote);
  setIcon("tabIconQuick", icons.zap);
  setIcon("tabIconSettings", icons.gear);
  setIcon("tabIconSched", icons.calendar || "🗓️");
  setIcon("boltIcon", icons.zap);
  setIcon("cdPauseIcon", icons.pause);
  setIcon("cdCancelIcon", icons.ban);
  setIcon("copyIcon", icons.copy);
  setIcon("remoteWifiIcon", icons.remote);
  setIcon("abortBanIcon", icons.ban);
  setIcon("qIconShutdown", icons.power);
  setIcon("qIconRestart", icons.restart);
  setIcon("qIconSleep", icons.sleep);
  setIcon("qIconDisplayOff", icons.display_off);
  setIcon("qIconLock", icons.lock);
  setIcon("qIconSignout", icons.signout);
}

// ------------------------------------------------------------ i18n
function applyI18n() {
  document.documentElement.lang = currentLang;
  document.documentElement.dir = currentLang === "ar" ? "rtl" : "ltr";
  document.documentElement.setAttribute("data-theme", currentTheme);

  document.getElementById("btnLangToggle").textContent = currentLang === "ar" ? "EN" : "AR";
  const set = (id, key) => { const el = document.getElementById(id); if (el) el.textContent = t(currentLang, key); };

  set("lblSubtitle", "subtitle");
  set("lblTabTimer", "timer");
  set("lblTabRemote", "remote");
  set("lblTabQuick", "quick");
  set("lblTabSched", "schedules");
  set("lblTabSettings", "settings");

  set("lblSetTime", "setShutdownTime");
  set("lblHours", "hours");
  set("lblMinutes", "minutes");
  set("lblStartBtn", "startCountdown");
  set("lblBottomHint", "cancelHint");
  set("lblRemaining", "remaining");

  set("p5m", "min5");
  set("p15m", "min15");
  set("p30m", "min30");
  set("p1h", "hour1");

  set("qLblShutdown", "shutdown");
  set("qLblRestart", "restart");
  set("qLblSleep", "sleep");
  set("qLblDisplayOff", "display_off");
  set("qLblLock", "lock");
  set("qLblSignout", "signout");

  set("lblAbortTile", "abort");
  set("lblBtnAbort", "abort");

  set("lblRemoteTitle", "remote");
  set("lblRemoteDescription", "remoteHelp");
  set("lblBindAddr", "bindAddress");
  set("lblPortNum", "listenPort");
  set("lblTokenTitle", "token");
  set("lblAuthCredentials", "saveCredentials");
  set("lblUsername", "username");
  set("lblPassword", "password");
  set("btnSaveCredentials", "saveCredentials");
  set("lblClientsTitle", "clients");
  set("lblQrTitle", "qrTitle");
  set("lblQrDesc", "qrDesc");
  set("btnCopyFullLink", "copyFullLink");

  set("lblSetLang", "language");
  set("lblSetTheme", "theme");
  set("lblSetSounds", "sounds");
  set("lblSetConfirm", "confirmActions");
  set("lblSetForce", "forceShutdown");
  set("lblSetWarn", "warnBeforeLabel");
  set("lblSetStats", "showStatsLabel");
  set("lblSetAutostart", "autoStartLabel");
  set("lblSetStartMinimized", "startMinimizedLabel");
  set("lblSetStartMinimizedDesc", "startMinimizedDesc");
  set("lblSetWidgetStyle", "widgetStyleLabel");
  set("lblSetWidgetStyleDesc", "widgetStyleDesc");
  set("lblSetCountdownStyle", "countdownStyleLabel");
  set("lblSetCountdownStyleDesc", "countdownStyleDesc");

  set("lblSchedTitle", "scheduleWeekly");
  set("lblSchedDesc", "scheduleDesc");
  set("lblSchedAction", "addAction");
  set("lblSchedTime", "timeLabel");
  set("btnAddSchedule", "addSchedule");
  set("noSchedulesMsg", "noSchedules");
  set("lblBtnCancel", "cancelCountdown");

  set("aboutDialogTitle", "aboutDialogTitle");
  set("aboutDeveloper", "aboutDeveloper");
  set("aboutCopyright", "aboutCopyright");
  set("aboutDesc", "aboutDesc");
  set("btnAboutOk", "aboutOk");
  const btnAboutEl = document.getElementById("btnAbout");
  if (btnAboutEl) btnAboutEl.title = t(currentLang, "about");

  populateTimeOptions();
  renderSchedules();
  updateStartButtonState(Boolean(activeCountdown));
}

// ------------------------------------------------------------ Tabs
document.querySelectorAll(".tab-pill").forEach(tabBtn => {
  tabBtn.addEventListener("click", () => {
    document.querySelectorAll(".tab-pill").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".pane").forEach(p => p.classList.remove("active"));
    tabBtn.classList.add("active");
    const target = tabBtn.getAttribute("data-tab");
    document.getElementById(`pane-${target}`).classList.add("active");
    if (target === "schedules") refreshSchedules();
  });
});

// ------------------------------------------------------------ Action pills & presets
document.querySelectorAll(".action-pill-btn").forEach(pill => {
  pill.addEventListener("click", () => {
    document.querySelectorAll(".action-pill-btn").forEach(b => b.classList.remove("active"));
    pill.classList.add("active");
    selectedTimerAction = pill.getAttribute("data-action");
  });
});

document.querySelectorAll(".preset-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    const secs = parseInt(btn.getAttribute("data-secs"), 10);
    document.getElementById("selectHours").value = Math.floor(secs / 3600);
    document.getElementById("selectMinutes").value = Math.floor((secs % 3600) / 60);
    startTimer(secs);
  });
});

// ------------------------------------------------------------ Window controls
document.getElementById("btnMinimize").addEventListener("click", () => {
  if (window.pywebview && window.pywebview.api) window.pywebview.api.minimize_window();
});
document.getElementById("btnClose").addEventListener("click", () => {
  if (window.pywebview && window.pywebview.api) window.pywebview.api.close_window();
});

const themeList = ["dark", "light", "ocean", "forest", "sunset", "purple", "midnight"];
document.getElementById("btnThemeToggle").addEventListener("click", () => {
  let idx = themeList.indexOf(currentTheme);
  currentTheme = themeList[(idx + 1) % themeList.length];
  document.getElementById("cfgTheme").value = currentTheme;
  renderAllIcons();
  saveSettings();
});

document.getElementById("btnLangToggle").addEventListener("click", () => {
  currentLang = currentLang === "ar" ? "en" : "ar";
  document.getElementById("cfgLang").value = currentLang;
  document.getElementById("btnLangToggle").textContent = currentLang === "ar" ? "EN" : "AR";
  applyI18n();
  saveSettings();
});

// Esc closes modals
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    hideAboutModal();
    const confirmModal = document.getElementById("confirmModal");
    if (confirmModal) confirmModal.classList.remove("open");
    pendingActionToConfirm = null;
  }
});

// ------------------------------------------------------------ External URL & About Modal (Rules 1 & 2)
function openExternalUrl(url) {
  if (!url) return;
  if (window.pywebview && window.pywebview.api && window.pywebview.api.open_url) {
    window.pywebview.api.open_url(url);
  } else {
    window.open(url, "_blank");
  }
}

async function showAboutModal() {
  const modal = document.getElementById("aboutModal");
  if (!modal) return;
  try {
    if (window.pywebview && window.pywebview.api && window.pywebview.api.get_version) {
      const v = await window.pywebview.api.get_version();
      const badge = document.getElementById("aboutVersionTag");
      if (badge) badge.textContent = `v${v}`;
    }
  } catch (e) {}
  modal.classList.add("open");
}

function hideAboutModal() {
  const modal = document.getElementById("aboutModal");
  if (modal) modal.classList.remove("open");
}

const btnAbout = document.getElementById("btnAbout");
if (btnAbout) btnAbout.addEventListener("click", showAboutModal);

const versionFooter = document.getElementById("versionFooter");
if (versionFooter) versionFooter.addEventListener("click", showAboutModal);

const btnAboutClose = document.getElementById("btnAboutClose");
if (btnAboutClose) btnAboutClose.addEventListener("click", hideAboutModal);

const btnAboutOk = document.getElementById("btnAboutOk");
if (btnAboutOk) btnAboutOk.addEventListener("click", hideAboutModal);

const aboutModal = document.getElementById("aboutModal");
if (aboutModal) {
  aboutModal.addEventListener("click", (e) => {
    if (e.target === aboutModal) hideAboutModal();
  });
}

document.querySelectorAll(".about-social-btn").forEach(btn => {
  btn.addEventListener("click", (e) => {
    e.preventDefault();
    const url = btn.getAttribute("data-url");
    if (url) openExternalUrl(url);
  });
});


// ------------------------------------------------------------ Metrics polling
async function pollMetrics() {
  if (!window.pywebview || !window.pywebview.api) return;
  try {
    const info = await window.pywebview.api.system_info();

    document.getElementById("cpuVal").textContent = `${info.cpuPercent.toFixed(1)}%`;
    document.getElementById("ramVal").textContent = `${info.ramPercent.toFixed(1)}%`;

    const tempRow = document.getElementById("tempRow");
    if (info.tempC !== null && info.tempC !== undefined) {
      document.getElementById("tempDivider").style.display = "inline";
      tempRow.style.display = "inline";
      document.getElementById("tempVal").textContent = `${info.tempC.toFixed(0)}°`;
    } else {
      document.getElementById("tempDivider").style.display = "none";
      tempRow.style.display = "none";
    }

    const battPill = document.getElementById("batteryPill");
    if (info.batteryPercent !== null && info.batteryPercent !== undefined) {
      battPill.style.display = "inline-flex";
      const v = document.getElementById("batteryVal");
      v.textContent = info.batteryPercent + "%" + (info.batteryPlugged ? " ⚡" : "");
      battPill.classList.toggle("low", info.batteryPercent <= 20 && !info.batteryPlugged);
    } else {
      battPill.style.display = "none";
    }

    if (info.countdown) window.__onCountdownTick(info.countdown);
  } catch (e) {}
}

// ------------------------------------------------------------ Timer
async function startTimer(customSecs = null) {
  const h = parseInt(document.getElementById("selectHours").value, 10) || 0;
  const m = parseInt(document.getElementById("selectMinutes").value, 10) || 0;
  const total = customSecs !== null ? customSecs : (h * 3600 + m * 60);

  if (total <= 0) {
    showToast(t(currentLang, "invalidTime"), "warn");
    playBeep(220, 0.12);
    return;
  }
  playBeep(740, 0.09);

  if (settings.askConfirm) {
    pendingActionToConfirm = { action: selectedTimerAction, delaySecs: total };
    showConfirmDialog(selectedTimerAction, total);
  } else {
    executeConfirmed(selectedTimerAction, total);
  }
}

document.getElementById("btnStartMain").addEventListener("click", async () => {
  if (activeCountdown) {
    await window.pywebview.api.cancel_countdown();
    window.__onCountdownTick(null);
    showToast(t(currentLang, "cancelled"), "ok");
  } else {
    startTimer();
  }
});

document.getElementById("btnPauseResume").addEventListener("click", async () => {
  if (!activeCountdown) return;
  if (activeCountdown.paused) await window.pywebview.api.resume_countdown();
  else await window.pywebview.api.pause_countdown();
});

const btnCancel = document.getElementById("btnCancelTimer");
if (btnCancel) {
  btnCancel.addEventListener("click", async () => {
    await window.pywebview.api.cancel_countdown();
    window.__onCountdownTick(null);
    showToast(t(currentLang, "cancelled"), "ok");
  });
}

document.getElementById("lblBottomHint").addEventListener("dblclick", async () => {
  if (activeCountdown) {
    await window.pywebview.api.cancel_countdown();
    window.__onCountdownTick(null);
    showToast(t(currentLang, "cancelled"), "ok");
  }
});

// ------------------------------------------------------------ Confirm dialog
async function showConfirmDialog(action, delaySecs) {
  try {
    const preview = await window.pywebview.api.preview_action(action, delaySecs, settings.force);
    document.getElementById("modalCmdDisplay").textContent = preview.display || action;
  } catch (e) {
    document.getElementById("modalCmdDisplay").textContent = action;
  }
  const msgKey = {
    shutdown: "confirmShutdown",
    restart: "confirmRestart",
    sleep: "confirmSleep",
    display_off: "displayOffMsg",
    lock: "confirmLock",
    signout: "confirmSignout"
  }[action] || "confirmSignout";
  document.getElementById("modalBody").textContent = t(currentLang, msgKey);
  document.getElementById("confirmModal").classList.add("open");
}

async function executeConfirmed(action, delaySecs) {
  if (delaySecs > 0) {
    const st = await window.pywebview.api.start_countdown(action, delaySecs, settings.force);
    window.__onCountdownTick(st);
    showToast(t(currentLang, "started"), "ok");
  } else {
    const res = await window.pywebview.api.execute_action(action, settings.force);
    if (res.ok) showToast(t(currentLang, "executed") + ": " + res.display, "ok");
    else showToast(res.error || "Execution failed", "warn");
  }
}

document.getElementById("modalCancel").addEventListener("click", () => {
  document.getElementById("confirmModal").classList.remove("open");
  pendingActionToConfirm = null;
});

document.getElementById("modalConfirm").addEventListener("click", () => {
  document.getElementById("confirmModal").classList.remove("open");
  if (pendingActionToConfirm) {
    executeConfirmed(pendingActionToConfirm.action, pendingActionToConfirm.delaySecs);
    pendingActionToConfirm = null;
  }
});

// ------------------------------------------------------------ Quick actions
document.getElementById("btnHeaderPower").addEventListener("click", () => {
  if (settings.askConfirm) {
    pendingActionToConfirm = { action: "shutdown", delaySecs: 0 };
    showConfirmDialog("shutdown", 0);
  } else {
    executeConfirmed("shutdown", 0);
  }
});

document.querySelectorAll(".action-tile").forEach(tile => {
  tile.addEventListener("click", () => {
    const act = tile.getAttribute("data-action");
    if (settings.askConfirm) {
      pendingActionToConfirm = { action: act, delaySecs: 0 };
      showConfirmDialog(act, 0);
    } else {
      executeConfirmed(act, 0);
    }
  });
});

document.getElementById("btnAbortSys").addEventListener("click", async () => {
  const res = await window.pywebview.api.abort_action();
  if (res.ok) showToast(t(currentLang, "cancelled") + " (shutdown /a)", "ok");
  else showToast(res.error || t(currentLang, "noPendingShutdown"), "warn");
});

const btnTriggerLock = document.getElementById("btnTriggerCustomLock");
if (btnTriggerLock) {
  btnTriggerLock.addEventListener("click", async () => {
    const input = document.getElementById("inputDesktopLockMsg");
    const msg = input ? input.value.trim() : "";
    try {
      const res = await window.pywebview.api.lock_screen(msg);
      if (res && res.ok) {
        showToast("تم تفعيل قفل الشاشة المخصص 🔒", "ok");
      } else {
        showToast((res && res.error) || "تعذر قفل الشاشة", "warn");
      }
    } catch (e) {
      showToast(String(e), "warn");
    }
  });
}

window.__onLockStateChanged = function(isLocked, msg) {
  const badge = document.getElementById("badgeDesktopLockStatus");
  const btn = document.getElementById("btnTriggerCustomLock");
  if (!badge) return;
  if (isLocked) {
    badge.textContent = "مقفل 🔒";
    badge.style.background = "rgba(239, 68, 68, 0.2)";
    badge.style.color = "#f87171";
    if (btn) btn.textContent = "🔒 الشاشة مقفلة حالياً";
  } else {
    badge.textContent = "مفتوح";
    badge.style.background = "rgba(148, 163, 184, 0.15)";
    badge.style.color = "var(--muted)";
    if (btn) btn.textContent = "🔒 قفل الشاشة الآن";
  }
};

// ------------------------------------------------------------ Remote server
async function refreshRemoteStatus() {
  if (!window.pywebview || !window.pywebview.api) return;
  try {
    const st = await window.pywebview.api.remote_status();
    const serverLabel = document.getElementById("lblServerStatus");
    const serverBadge = document.getElementById("lblRemoteBadge");
    const serverBtn = document.getElementById("btnServerToggle");

    if (st.running) {
      const scheme = st.https ? "https 🔒" : "http";
      serverLabel.textContent = `${scheme} ${st.bind}:${st.port}`;
      serverLabel.style.color = "var(--ok)";
      serverBadge.textContent = t(currentLang, "connected");
      serverBadge.style.background = "rgba(52,211,153,0.15)";
      serverBadge.style.color = "var(--ok)";
      serverBtn.textContent = t(currentLang, "disableRemote");
      serverBtn.className = "ghost-btn danger";
    } else {
      serverLabel.textContent = t(currentLang, "disconnected");
      serverLabel.style.color = "var(--muted)";
      serverBadge.textContent = t(currentLang, "disconnected");
      serverBadge.style.background = "rgba(251,113,133,0.15)";
      serverBadge.style.color = "var(--danger)";
      serverBtn.textContent = t(currentLang, "enableRemote");
      serverBtn.className = "ghost-btn";
    }

    const tokenValEl = document.getElementById("remoteTokenVal");
    if (tokenValEl) tokenValEl.textContent = st.token || "------";

    const qrImg = document.getElementById("qrCodeImg");
    if (qrImg && st.qrDataUri) qrImg.src = st.qrDataUri;

    const urlsDiv = document.getElementById("remoteUrls");
    urlsDiv.innerHTML = "";
    let fullConnUrl = "";
    if (st.running && st.urls) {
      st.urls.slice(0, 2).forEach(u => {
        if (!fullConnUrl) fullConnUrl = u;
        const d = document.createElement("div");
        d.textContent = u;
        urlsDiv.appendChild(d);
      });
    }

    const btnCopyFull = document.getElementById("btnCopyFullLink");
    if (btnCopyFull) {
      btnCopyFull.onclick = () => {
        if (fullConnUrl) {
          navigator.clipboard.writeText(fullConnUrl);
          showToast(t(currentLang, "copied"), "ok");
        }
      };
    }

    const clList = document.getElementById("clientsList");
    if (st.clients && st.clients.length > 0) {
      clList.innerHTML = "";
      st.clients.forEach(c => {
        const item = document.createElement("div");
        item.style.cssText = "display:flex;justify-content:space-between;padding:6px 10px;background:var(--panel);border-radius:8px;margin-bottom:4px;";
        item.innerHTML = `<span>📱 ${c.ip} (${c.userAgent})</span><span style="color:var(--ok);">${c.lastAction || t(currentLang, "connected")}</span>`;
        clList.appendChild(item);
      });
    } else {
      clList.textContent = t(currentLang, "noClients");
    }
  } catch (e) {}
}

document.getElementById("btnServerToggle").addEventListener("click", async () => {
  const st = await window.pywebview.api.remote_status();
  if (st.running) {
    await window.pywebview.api.remote_stop();
    settings.remoteEnabled = false;
  } else {
    try {
      await window.pywebview.api.remote_start();
      settings.remoteEnabled = true;
    } catch (e) {
      showToast(String(e), "warn");
      settings.remoteEnabled = false;
    }
  }
  await window.pywebview.api.set_settings(settings);
  refreshRemoteStatus();
});

const btnRotate = document.getElementById("btnRotateToken");
if (btnRotate) {
  btnRotate.addEventListener("click", async () => {
    const tkn = await window.pywebview.api.remote_rotate_token();
    const tokenVal = document.getElementById("remoteTokenVal");
    if (tokenVal) tokenVal.textContent = tkn;
    refreshRemoteStatus();
    showToast(t(currentLang, "generateToken"), "ok");
  });
}

const btnCopy = document.getElementById("btnCopyToken");
if (btnCopy) {
  btnCopy.addEventListener("click", () => {
    const tokenVal = document.getElementById("remoteTokenVal");
    if (tokenVal) {
      navigator.clipboard.writeText(tokenVal.textContent);
      showToast(t(currentLang, "copied"), "ok");
    }
  });
}

// ------------------------------------------------------------ Schedules
const DAY_ORDER = [0, 1, 2, 3, 4, 5, 6]; // 0 = Sunday (matches Python engine)

function renderDayChips() {
  const wrap = document.getElementById("schedDays");
  if (!wrap) return;
  wrap.innerHTML = "";
  DAY_ORDER.forEach(d => {
    const chip = document.createElement("div");
    chip.className = "day-chip" + (schedSelectedDays.includes(d) ? " active" : "");
    chip.textContent = t(currentLang, "days")[d] || d;
    chip.onclick = () => {
      if (schedSelectedDays.includes(d))
        schedSelectedDays = schedSelectedDays.filter(x => x !== d);
      else schedSelectedDays.push(d);
      renderDayChips();
    };
    wrap.appendChild(chip);
  });
}

let schedulesCache = [];

async function refreshSchedules() {
  if (!window.pywebview || !window.pywebview.api) return;
  try {
    schedulesCache = await window.pywebview.api.schedules_list();
    renderSchedules();
  } catch (e) {}
}

function renderSchedules() {
  const list = document.getElementById("schedulesList");
  if (!list) return;
  const noMsg = document.getElementById("noSchedulesMsg");
  list.innerHTML = "";
  if (!schedulesCache || !schedulesCache.length) {
    list.appendChild(noMsg);
    noMsg.style.display = "block";
    return;
  }
  const dayNames = t(currentLang, "days");
  schedulesCache.forEach(s => {
    const row = document.createElement("div");
    row.className = "sched-row" + (s.enabled ? "" : " disabled");

    const info = document.createElement("div");
    info.className = "sched-info";
    const timeEl = document.createElement("div");
    timeEl.className = "sched-time";
    timeEl.textContent = s.time;
    const descEl = document.createElement("div");
    descEl.className = "sched-desc";
    const daysTxt = s.days.length === 7
      ? t(currentLang, "everyDay")
      : s.days.map(d => dayNames[d]).join("، ");
    descEl.textContent = `${t(currentLang, s.action)} · ${daysTxt}`;
    info.appendChild(timeEl);
    info.appendChild(descEl);

    const actions = document.createElement("div");
    actions.className = "sched-actions";

    const togBtn = document.createElement("button");
    togBtn.className = "ghost-btn";
    togBtn.textContent = s.enabled ? "⏸" : "▶";
    togBtn.title = s.enabled ? "إيقاف" : "تفعيل";
    togBtn.onclick = async () => {
      await window.pywebview.api.schedules_toggle(s.id);
      refreshSchedules();
    };

    const delBtn = document.createElement("button");
    delBtn.className = "ghost-btn danger";
    delBtn.textContent = "🗑";
    delBtn.onclick = async () => {
      if (confirm(t(currentLang, "confirmDeleteSched"))) {
        await window.pywebview.api.schedules_remove(s.id);
        showToast(t(currentLang, "scheduleRemoved"), "ok");
        refreshSchedules();
      }
    };

    actions.appendChild(togBtn);
    actions.appendChild(delBtn);
    row.appendChild(info);
    row.appendChild(actions);
    list.appendChild(row);
  });
}

document.getElementById("btnAddSchedule").addEventListener("click", async () => {
  const action = document.getElementById("schedAction").value;
  const time = document.getElementById("schedTime").value || "23:00";
  if (!schedSelectedDays.length) {
    showToast(t(currentLang, "invalidTime"), "warn");
    return;
  }
  await window.pywebview.api.schedules_add(action, time, schedSelectedDays);
  showToast(t(currentLang, "scheduleAdded"), "ok");
  refreshSchedules();
});

// ------------------------------------------------------------ Settings
async function loadSettings() {
  if (!window.pywebview || !window.pywebview.api) return;
  settings = await window.pywebview.api.get_settings();
  currentLang = settings.language || "ar";
  currentTheme = settings.theme || "dark";

  document.getElementById("cfgLang").value = currentLang;
  document.getElementById("cfgTheme").value = currentTheme;
  document.getElementById("cfgSounds").checked = settings.sounds ?? true;
  document.getElementById("cfgConfirm").checked = settings.askConfirm ?? false;
  document.getElementById("cfgForce").checked = settings.force ?? false;
  document.getElementById("cfgWarnBefore").value = settings.warnBefore ?? 30;
  document.getElementById("cfgShowStats").checked = settings.showStats ?? true;
  document.getElementById("cfgAutoStart").checked = settings.autoStart ?? false;
  document.getElementById("cfgStartMinimized").checked = settings.startMinimized ?? true;
  document.getElementById("cfgWidgetStyle").value = settings.widgetStyle || "cyber";
  document.getElementById("cfgCountdownStyle").value = settings.countdownStyle || "hud";

  // HTTPS availability + state
  const httpsAvail = await window.pywebview.api.https_supported();
  const httpsCheck = document.getElementById("cfgHttps");
  const httpsBadge = document.getElementById("httpsAvailBadge");
  httpsCheck.disabled = !httpsAvail;
  httpsCheck.checked = httpsAvail && (settings.httpsEnabled ?? false);
  if (httpsAvail) {
    httpsBadge.textContent = "SSL";
    httpsBadge.className = "secure-badge";
  } else {
    httpsBadge.textContent = "✖";
    httpsBadge.className = "secure-badge off";
    httpsBadge.title = t(currentLang, "httpsUnavailable");
  }

  applyStatsVisibility();

  // Version footer
  try {
    const v = await window.pywebview.api.get_version();
    document.getElementById("versionFooter").textContent = `Shutdown Panel · v${v}`;
  } catch (e) {}

  renderAllIcons();
  applyI18n();
  renderDayChips();

  const ips = await window.pywebview.api.network_interfaces();
  const bindSelect = document.getElementById("selectBindAddr");
  bindSelect.innerHTML = `<option value="0.0.0.0">0.0.0.0</option>`;
  ips.forEach(ip => {
    bindSelect.innerHTML += `<option value="${ip}">${ip}</option>`;
  });
  if (settings.remoteBind) bindSelect.value = settings.remoteBind;
  if (settings.remotePort) document.getElementById("inputPortNum").value = settings.remotePort;
  if (document.getElementById("inputRemoteUsername"))
    document.getElementById("inputRemoteUsername").value = settings.remoteUsername || "admin";
  if (document.getElementById("inputRemotePassword"))
    document.getElementById("inputRemotePassword").value = settings.remotePassword || "admin";
}

function applyStatsVisibility() {
  const row = document.getElementById("statsRow");
  if (row) row.style.display = settings.showStats === false ? "none" : "flex";
}

function saveSettings() {
  settings.language = document.getElementById("cfgLang").value;
  settings.theme = document.getElementById("cfgTheme").value;
  settings.sounds = document.getElementById("cfgSounds").checked;
  settings.askConfirm = document.getElementById("cfgConfirm").checked;
  settings.force = document.getElementById("cfgForce").checked;
  settings.warnBefore = parseInt(document.getElementById("cfgWarnBefore").value, 10) || 0;
  settings.showStats = document.getElementById("cfgShowStats").checked;
  settings.autoStart = document.getElementById("cfgAutoStart").checked;
  settings.startMinimized = document.getElementById("cfgStartMinimized").checked;
  settings.widgetStyle = document.getElementById("cfgWidgetStyle").value;
  settings.countdownStyle = document.getElementById("cfgCountdownStyle").value;
  const httpsCheck = document.getElementById("cfgHttps");
  if (!httpsCheck.disabled) settings.httpsEnabled = httpsCheck.checked;
  settings.remoteBind = document.getElementById("selectBindAddr").value;
  settings.remotePort = parseInt(document.getElementById("inputPortNum").value, 10) || 8080;
  const uInp = document.getElementById("inputRemoteUsername");
  const pInp = document.getElementById("inputRemotePassword");
  if (uInp) settings.remoteUsername = uInp.value.trim() || "admin";
  if (pInp) settings.remotePassword = pInp.value.trim() || "admin";

  currentLang = settings.language;
  currentTheme = settings.theme;
  applyI18n();
  applyStatsVisibility();

  if (window.pywebview && window.pywebview.api) {
    window.pywebview.api.set_settings(settings);
  }
}

document.getElementById("cfgLang").addEventListener("change", saveSettings);
document.getElementById("cfgTheme").addEventListener("change", saveSettings);
document.getElementById("cfgSounds").addEventListener("change", saveSettings);
document.getElementById("cfgConfirm").addEventListener("change", saveSettings);
document.getElementById("cfgForce").addEventListener("change", saveSettings);
document.getElementById("cfgWarnBefore").addEventListener("change", saveSettings);
document.getElementById("cfgShowStats").addEventListener("change", saveSettings);
document.getElementById("cfgAutoStart").addEventListener("change", saveSettings);
document.getElementById("cfgStartMinimized").addEventListener("change", saveSettings);
document.getElementById("cfgWidgetStyle").addEventListener("change", saveSettings);
document.getElementById("cfgCountdownStyle").addEventListener("change", saveSettings);
document.getElementById("cfgHttps").addEventListener("change", saveSettings);
document.getElementById("selectBindAddr").addEventListener("change", saveSettings);
document.getElementById("inputPortNum").addEventListener("change", saveSettings);

const btnSaveCreds = document.getElementById("btnSaveCredentials");
if (btnSaveCreds) {
  btnSaveCreds.addEventListener("click", async () => {
    const u = (document.getElementById("inputRemoteUsername").value || "admin").trim();
    const p = (document.getElementById("inputRemotePassword").value || "admin").trim();
    if (window.pywebview && window.pywebview.api) {
      await window.pywebview.api.remote_set_credentials(u, p);
      showToast(t(currentLang, "credentialsSaved"), "ok");
      refreshRemoteStatus();
    }
  });
}

function hideSplashScreen() {
  const splash = document.getElementById("appSplashScreen");
  if (splash) splash.classList.add("hide");
}

// ------------------------------------------------------------ Init
window.addEventListener("pywebviewready", async () => {
  try {
    await loadSettings();
    refreshRemoteStatus();
    refreshSchedules();
    setInterval(pollMetrics, 1500);
    setInterval(refreshRemoteStatus, 5000);
    setInterval(refreshSchedules, 20000);
  } catch (err) {
    console.error("App init error:", err);
  } finally {
    setTimeout(hideSplashScreen, 300);
  }
});

// Fallback: hide the splash unconditionally
setTimeout(hideSplashScreen, 1800);
