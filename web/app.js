(() => {
  const THEME_KEY = "aas-theme";
  const html = document.documentElement;
  const messagesEl = document.getElementById("messagesContainer");
  const typingEl = document.getElementById("typingIndicator");
  const form = document.getElementById("composer");
  const input = document.getElementById("chatInput");
  const sendBtn = document.getElementById("sendBtn");
  const stateLabel = document.getElementById("stateLabel");
  const sessionLabel = document.getElementById("sessionLabel");
  const stepLabel = document.getElementById("stepLabel");
  const flowHint = document.getElementById("flowHint");
  const stageStepper = document.getElementById("stageStepper");
  const quickEl = document.getElementById("quickReplies");
  const themeBtn = document.getElementById("themeToggleBtn");
  const themeLabel = document.getElementById("themeLabel");
  const restartBtn = document.getElementById("restartBtn");
  const micBtn = document.getElementById("micBtn");
  const endCallBtn = document.getElementById("endCallBtn");
  const callStage = document.getElementById("callStage");
  const voiceStatus = document.getElementById("voiceStatus");
  const liveTranscript = document.getElementById("liveTranscript");
  const ttsToggle = document.getElementById("ttsToggle");
  const stopSpeakBtn = document.getElementById("stopSpeakBtn");
  const speechSupport = document.getElementById("speechSupport");
  const currentPrompt = document.getElementById("currentPrompt");
  const progressFill = document.getElementById("progressFill");
  const livePill = document.getElementById("livePill");
  const livePillText = document.getElementById("livePillText");
  const elevenMount = document.getElementById("elevenMount");
  const deckLabel = document.getElementById("deckLabel");

  const API_BASE = String(window.AAS_API_BASE || "")
    .trim()
    .replace(/\/$/, "");

  function apiUrl(path) {
    const p = path.startsWith("/") ? path : `/${path}`;
    return API_BASE ? `${API_BASE}${p}` : p;
  }

  let sessionId = null;
  let state = null;
  let busy = false;
  let ttsEnabled = localStorage.getItem("aas-tts") !== "off";
  let recognition = null;
  let listening = false;
  let finalSpeech = "";
  let ttsUnlocked = false;
  let pendingSpeech = null;
  let speakWatchdog = null;
  let preferredVoice = null;
  let suppressPendingSpeech = false;
  let micPrimed = false;
  let callActive = false;
  let listenResumeTimer = null;
  let elevenAgentId = null;
  let elevenConversation = null;
  let voiceTransport = "browser"; // browser | elevenlabs

  const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) ||
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);

  function callHint() {
    if (voiceTransport === "elevenlabs") {
      return callActive
        ? "On call with Lockline · speak naturally"
        : "Start call — ElevenLabs voice agent";
    }
    if (!recognition) return "Type below or tap a suggested reply";
    return callActive
      ? "Listening for your turn…"
      : "Start call — speak freely, Lockline replies";
  }

  function clearListenResume() {
    if (listenResumeTimer) {
      clearTimeout(listenResumeTimer);
      listenResumeTimer = null;
    }
  }

  function syncCallChrome() {
    callStage.classList.toggle("is-in-call", callActive);
    micBtn.setAttribute("aria-label", callActive ? "End call" : "Start call");
    if (endCallBtn) endCallBtn.classList.toggle("hidden", !callActive);
    if (deckLabel) {
      deckLabel.textContent =
        voiceTransport === "elevenlabs"
          ? callActive
            ? "Live · ElevenLabs"
            : "ElevenLabs line"
          : callActive
            ? "Live call"
            : "Voice line";
    }
    syncLivePill();
  }

  function scheduleListenAfterSpeak() {
    clearListenResume();
    if (!callActive || voiceTransport !== "browser" || busy || listening) return;
    listenResumeTimer = window.setTimeout(() => {
      listenResumeTimer = null;
      if (callActive && !busy && !listening) startListening({ fromLoop: true });
    }, 280);
  }

  const STAGE_LABELS = [
    "Acknowledge",
    "Name",
    "Intent",
    "Topic",
    "Time",
    "Pick slot",
    "Confirm",
    "Done",
  ];

  const QUICK_BY_STATE = {
    DISCLAIMER_AWAIT_ACK: ["yes", "I understand"],
    COLLECT_NAME: ["Priya Sharma", "Ambrosh Patel"],
    INTENT_ROUTING: ["book new", "reschedule", "cancel", "what to prepare", "check availability"],
    BOOK_TOPIC: ["KYC Onboarding", "SIP Mandates", "Statements/Tax Docs", "Withdrawals", "Account Changes"],
    BOOK_TIME_PREFERENCE: ["time monday afternoon", "tomorrow morning", "time tuesday evening"],
    BOOK_OFFER_SLOTS: ["1", "2", "first", "second"],
    BOOK_CONFIRM: ["confirm", "yes"],
    RESCHEDULE_COLLECT_CODE: [],
    RESCHEDULE_OFFER_SLOTS: ["1", "2", "first", "second"],
    CANCEL_COLLECT_CODE: [],
    CANCEL_CONFIRM: ["confirm", "no"],
    PREPARE_TOPIC_OR_GENERIC: ["topic kyc", "SIP"],
    AVAILABILITY_QUERY: ["time monday afternoon", "tomorrow morning"],
    CLOSE: ["Restart session"],
  };

  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function applyTheme(mode) {
    const dark = mode === "dark";
    html.classList.toggle("dark", dark);
    themeLabel.textContent = dark ? "Light" : "Dark";
    localStorage.setItem(THEME_KEY, mode);
    document.body.classList.remove("theme-flash");
    void document.body.offsetWidth;
    document.body.classList.add("theme-flash");
  }

  function initTheme() {
    const saved = localStorage.getItem(THEME_KEY);
    if (saved === "light" || saved === "dark") applyTheme(saved);
    else applyTheme("light");
  }

  function syncLivePill() {
    if (!livePill || !livePillText) return;
    let mode = "idle";
    let label = callActive ? "On call" : "Ready";
    if (listening) {
      mode = "listening";
      label = "Listening";
    } else if (callStage.classList.contains("is-speaking")) {
      mode = "speaking";
      label = "Speaking";
    } else if (busy) {
      mode = "thinking";
      label = "Thinking";
    } else if (callActive) {
      mode = "listening";
      label = "On call";
    }
    livePill.dataset.mode = mode;
    livePillText.textContent = label;
  }

  function setBusy(v) {
    busy = v;
    sendBtn.disabled = v || !input.value.trim();
    input.disabled = v;
    typingEl.classList.toggle("hidden", !v);
    callStage.classList.toggle("is-busy", v);
    quickEl.querySelectorAll("button").forEach((b) => {
      b.disabled = v;
    });
    syncLivePill();
  }

  function stageFromState(s) {
    switch (s) {
      case "DISCLAIMER_AWAIT_ACK":
      case "GREET":
        return { index: 0, hint: "" };
      case "COLLECT_NAME":
        return { index: 1, hint: "" };
      case "INTENT_ROUTING":
        return { index: 2, hint: "" };
      case "BOOK_TOPIC":
      case "PREPARE_TOPIC_OR_GENERIC":
        return { index: 3, hint: "" };
      case "BOOK_TIME_PREFERENCE":
      case "AVAILABILITY_QUERY":
        return { index: 4, hint: "" };
      case "BOOK_OFFER_SLOTS":
      case "RESCHEDULE_OFFER_SLOTS":
        return { index: 5, hint: s.startsWith("RESCHEDULE") ? "Reschedule flow" : "" };
      case "BOOK_CONFIRM":
      case "CANCEL_CONFIRM":
        return { index: 6, hint: s.startsWith("CANCEL") ? "Cancel flow" : "" };
      case "RESCHEDULE_COLLECT_CODE":
        return { index: 3, hint: "Reschedule flow" };
      case "CANCEL_COLLECT_CODE":
        return { index: 3, hint: "Cancel flow" };
      case "CLOSE":
        return { index: 7, hint: "" };
      default:
        return { index: 2, hint: "" };
    }
  }

  function renderStage(nextState) {
    const { index, hint } = stageFromState(nextState);
    stepLabel.textContent = STAGE_LABELS[index] || "—";
    flowHint.textContent = hint;
    if (progressFill) {
      const pct = Math.max(6, Math.round((index / (STAGE_LABELS.length - 1)) * 100));
      progressFill.style.width = `${pct}%`;
    }
    const steps = stageStepper.querySelectorAll(".stage-step");
    steps.forEach((el) => {
      const n = Number(el.getAttribute("data-step"));
      el.classList.toggle("is-active", n === index);
      el.classList.toggle("is-done", n < index);
      el.classList.toggle("is-alt", Boolean(hint) && n === index);
    });
  }

  function setMeta(nextState, sid) {
    state = nextState;
    stateLabel.textContent = nextState || "—";
    if (sid) {
      sessionId = sid;
      sessionLabel.textContent = `Session ${sid.slice(0, 8).toUpperCase()}`;
    }
    renderStage(nextState);
    renderQuickReplies();
    if (!callActive && !busy && nextState === "COLLECT_NAME") {
      voiceStatus.textContent =
        "Tap a name chip, type your name, or Start call to speak it";
    }
  }

  function extractSlots(text) {
    const lines = text.split("\n");
    const slots = [];
    for (const line of lines) {
      const m = line.match(/^\s*([12])\.\s+(.+)$/);
      if (m) slots.push({ n: m[1], label: m[2].trim() });
    }
    return slots;
  }

  function extractBookingCode(text) {
    const m = text.match(/Booking code:\s*([A-Z]{2}-[A-Z]\d{3})/i);
    return m ? m[1].toUpperCase() : null;
  }

  function extractSecureUrl(text) {
    const m = text.match(/https?:\/\/\S+/);
    return m ? m[0] : null;
  }

  function appendLog(role, text) {
    const line = document.createElement("div");
    line.className = `turn-line ${role}`;
    line.innerHTML = `
      <div class="who">${role === "user" ? "You" : role === "error" ? "Error" : "Assistant"}</div>
      <div>${escapeHtml(text)}</div>`;
    messagesEl.appendChild(line);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function presentAssistantMessages(msgs) {
    if (!msgs?.length) return;
    for (let i = 0; i < msgs.length - 1; i++) appendLog("assistant", msgs[i]);
    showPrompt(msgs[msgs.length - 1]);
  }

  function showPrompt(text) {
    const slots = extractSlots(text);
    const code = extractBookingCode(text);
    const url = extractSecureUrl(text);

    let htmlBody = `<p class="prompt-text">${escapeHtml(text)}</p>`;

    if (slots.length) {
      htmlBody += `<div class="slot-grid">`;
      for (const s of slots) {
        htmlBody += `
          <button type="button" data-send="${escapeHtml(s.n)}" class="slot-tile">
            <div class="n">${escapeHtml(s.n)}</div>
            <div class="label">${escapeHtml(s.label)}</div>
            <div class="hint">Tap to choose</div>
          </button>`;
      }
      htmlBody += `</div>`;
    }

    if (code) {
      htmlBody += `
        <div class="booking-card">
          <div class="who">Provisional booking</div>
          <div class="code-row">
            <span>CODE: <strong>${escapeHtml(code)}</strong></span>
            <button type="button" data-copy="${escapeHtml(code)}">Copy</button>
          </div>
          ${url ? `<a href="${escapeHtml(url)}" target="_blank" rel="noopener">Open secure details link</a>` : ""}
        </div>`;
    }

    currentPrompt.classList.remove("prompt-swap");
    void currentPrompt.offsetWidth;
    currentPrompt.innerHTML = htmlBody;
    currentPrompt.classList.add("prompt-swap");
    appendLog("assistant", text);
  }

  function userTurn(text) {
    appendLog("user", text);
  }

  function errorTurn(text) {
    appendLog("error", text);
    currentPrompt.innerHTML = `<p class="prompt-text">${escapeHtml(text)}</p>`;
  }

  function boundaryNote() {
    appendLog(
      "assistant",
      "Pre-booking boundary: do not share phone, email, tax IDs, or bank details here."
    );
  }

  function renderQuickReplies() {
    quickEl.innerHTML = "";
    const chips = QUICK_BY_STATE[state] || [];
    if (state === "COLLECT_NAME") {
      input.placeholder = "Type your name (e.g. Priya Sharma)…";
      if (!busy) {
        queueMicrotask(() => input.focus());
      }
    } else {
      input.placeholder = "Or type your reply…";
    }
    for (const text of chips) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "action-chip";
      btn.textContent = text;
      btn.disabled = busy;
      btn.addEventListener("click", () => {
        suppressPendingSpeech = true;
        unlockTts();
        if (text === "Restart session") {
          restartSession();
          return;
        }
        sendMessage(text);
      });
      quickEl.appendChild(btn);
    }
  }

  function syncSendEnabled() {
    sendBtn.disabled = busy || !input.value.trim();
  }

  function clearSpeakWatchdog() {
    if (speakWatchdog) {
      clearInterval(speakWatchdog);
      speakWatchdog = null;
    }
  }

  function stopSpeaking() {
    clearSpeakWatchdog();
    pendingSpeech = null;
    if (window.speechSynthesis) {
      try {
        window.speechSynthesis.cancel();
      } catch (_) {
        /* ignore */
      }
    }
    callStage.classList.remove("is-speaking");
    syncLivePill();
  }

  function pickVoice() {
    if (!window.speechSynthesis) return null;
    const voices = window.speechSynthesis.getVoices() || [];
    if (!voices.length) return preferredVoice;
    preferredVoice =
      voices.find((v) => /^en-US/i.test(v.lang) && /natural|premium|enhanced|neural/i.test(v.name)) ||
      voices.find((v) => /^en-US/i.test(v.lang) && /Samantha|Alex|Allison|Ava|Susan|Jenny/i.test(v.name)) ||
      voices.find((v) => /^en-US/i.test(v.lang)) ||
      voices.find((v) => /^en/i.test(v.lang)) ||
      voices[0];
    return preferredVoice;
  }

  function unlockTts() {
    if (!window.speechSynthesis) return;
    if (!ttsUnlocked) {
      ttsUnlocked = true;
      // Warm the engine inside a user gesture (required by Chrome/Safari).
      try {
        window.speechSynthesis.cancel();
        const warm = new SpeechSynthesisUtterance(" ");
        warm.volume = 0;
        warm.rate = 2;
        window.speechSynthesis.speak(warm);
        window.speechSynthesis.cancel();
      } catch (_) {
        /* ignore */
      }
      pickVoice();
    }
    // Replay queued greeting unless mic/chip is about to send a new turn.
    queueMicrotask(() => {
      if (suppressPendingSpeech) {
        suppressPendingSpeech = false;
        pendingSpeech = null;
        return;
      }
      if (pendingSpeech && ttsEnabled) {
        const queued = pendingSpeech;
        pendingSpeech = null;
        speakTexts(queued, { force: true });
      }
    });
  }

  function forSpeech(text) {
    return String(text)
      .replace(/\bKYC\b/gi, "K Y C")
      .replace(/\bSIP\b/gi, "S I P")
      .replace(/\bIST\b/g, "I S T")
      .replace(/\bPII\b/gi, "personal information")
      .replace(/\bK Y C\b/g, "K Y C");
  }

  function speakTexts(texts, opts = {}) {
    if (!ttsEnabled || !window.speechSynthesis || !texts?.length) return;
    const joined = texts
      .filter(Boolean)
      .map(forSpeech)
      .join(". ")
      .replace(/\s+/g, " ")
      .trim();
    if (!joined) return;

    if (!ttsUnlocked && !opts.force) {
      pendingSpeech = texts;
      voiceStatus.textContent = "Start call (or tap a chip) to hear the assistant";
      return;
    }

    clearSpeakWatchdog();
    try {
      window.speechSynthesis.cancel();
    } catch (_) {
      /* ignore */
    }

    // Chrome: cancel() then speak() in the same turn often drops audio.
    window.setTimeout(() => {
      if (!ttsEnabled) return;
      const u = new SpeechSynthesisUtterance(joined);
      const voice = pickVoice();
      if (voice) u.voice = voice;
      u.lang = "en-US";
      u.rate = 1;
      u.pitch = 1;
      u.volume = 1;
      callStage.classList.add("is-speaking");
      syncLivePill();
      voiceStatus.textContent = "Speaking…";
      u.onend = () => {
        clearSpeakWatchdog();
        callStage.classList.remove("is-speaking");
        syncLivePill();
        if (!busy && !listening) {
          voiceStatus.textContent = callHint();
        }
        scheduleListenAfterSpeak();
      };
      u.onerror = () => {
        clearSpeakWatchdog();
        callStage.classList.remove("is-speaking");
        syncLivePill();
        if (!busy && !listening) {
          voiceStatus.textContent = callHint();
        }
        scheduleListenAfterSpeak();
      };
      try {
        window.speechSynthesis.speak(u);
        if (window.speechSynthesis.paused) window.speechSynthesis.resume();
        // Chrome can freeze mid-utterance; nudge resume while speaking.
        speakWatchdog = window.setInterval(() => {
          if (!window.speechSynthesis.speaking) {
            clearSpeakWatchdog();
            return;
          }
          if (window.speechSynthesis.paused) window.speechSynthesis.resume();
        }, 2500);
      } catch (_) {
        callStage.classList.remove("is-speaking");
        syncLivePill();
      }
    }, 60);
  }

  function syncTtsButton() {
    ttsToggle.textContent = ttsEnabled ? "TTS on" : "TTS off";
    ttsToggle.classList.toggle("is-active", ttsEnabled);
  }

  function initTtsVoices() {
    if (!window.speechSynthesis) {
      speechSupport.textContent = "Speech synthesis unavailable in this browser";
      return;
    }
    pickVoice();
    window.speechSynthesis.onvoiceschanged = () => pickVoice();
  }

  function initSpeech() {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) {
      speechSupport.textContent =
        "Voice input unavailable here — use Type / suggested replies (Chrome Android works best)";
      voiceStatus.textContent = "Type below or tap a suggested reply";
      if (voiceTransport !== "elevenlabs") {
        micBtn.disabled = true;
        micBtn.setAttribute("aria-label", "Microphone unavailable");
      }
      return;
    }
    speechSupport.textContent =
      "Continuous call · Chrome / Edge recommended · speak after Lockline finishes";
    micBtn.setAttribute("aria-label", "Start call");
    recognition = new SR();
    recognition.lang = "en-US";
    recognition.interimResults = !isIOS;
    // One utterance per turn; we restart after the assistant speaks.
    recognition.continuous = false;

    recognition.onstart = () => {
      listening = true;
      micBtn.classList.add("listening");
      callStage.classList.add("is-listening");
      syncLivePill();
      voiceStatus.textContent = "Listening… speak now";
      liveTranscript.textContent = "";
      finalSpeech = "";
    };
    recognition.onerror = (e) => {
      listening = false;
      micBtn.classList.remove("listening");
      callStage.classList.remove("is-listening");
      syncLivePill();
      if (e.error === "not-allowed" || e.error === "service-not-allowed") {
        voiceStatus.textContent =
          "Mic blocked — allow microphone in Settings, or type below";
        if (callActive) endCall({ silent: true });
        return;
      }
      if (e.error === "aborted") {
        voiceStatus.textContent = callHint();
        return;
      }
      voiceStatus.textContent = callHint();
      if (callActive && !busy && (e.error === "no-speech" || e.error === "audio-capture")) {
        scheduleListenAfterSpeak();
      }
    };
    recognition.onend = () => {
      listening = false;
      micBtn.classList.remove("listening");
      callStage.classList.remove("is-listening");
      syncLivePill();
      const text = (finalSpeech || "").trim();
      liveTranscript.textContent = text ? `Heard: “${text}”` : "";
      if (text) {
        voiceStatus.textContent = "Thinking…";
        sendMessage(text);
        return;
      }
      voiceStatus.textContent = callHint();
      if (callActive && !busy) scheduleListenAfterSpeak();
    };
    recognition.onresult = (event) => {
      let interim = "";
      let finals = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const t = event.results[i][0].transcript;
        if (event.results[i].isFinal) finals += t;
        else interim += t;
      }
      if (finals) finalSpeech = (finalSpeech + " " + finals).trim();
      liveTranscript.textContent = finalSpeech || interim;
    };
  }

  async function ensureMicPermission() {
    if (micPrimed || !navigator.mediaDevices?.getUserMedia) return true;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      stream.getTracks().forEach((t) => t.stop());
      micPrimed = true;
      return true;
    } catch (_) {
      voiceStatus.textContent =
        "Mic permission denied — allow microphone, or type below";
      return false;
    }
  }

  async function startListening(opts = {}) {
    if (!recognition || busy || listening || !callActive) return;
    if (voiceTransport !== "browser") return;
    if (!opts.fromLoop) stopSpeaking();
    else if (callStage.classList.contains("is-speaking")) return;
    const ok = await ensureMicPermission();
    if (!ok) {
      endCall({ silent: true });
      return;
    }
    try {
      recognition.start();
    } catch (_) {
      /* already started */
    }
  }

  function stopListening() {
    if (!recognition) return;
    try {
      recognition.stop();
    } catch (_) {
      /* ignore */
    }
  }

  async function startElevenCall() {
    if (!elevenAgentId) throw new Error("No ElevenLabs agent id");
    voiceStatus.textContent = "Connecting voice agent…";
    const mod = await import("https://esm.sh/@elevenlabs/client@1.26.0");
    const Conversation = mod.Conversation || mod.default?.Conversation;
    if (!Conversation?.startSession) {
      throw new Error("ElevenLabs client failed to load");
    }
    elevenConversation = await Conversation.startSession({
      agentId: elevenAgentId,
      connectionType: "webrtc",
      onConnect: () => {
        voiceStatus.textContent = "Connected — speak naturally";
        syncCallChrome();
      },
      onDisconnect: () => {
        elevenConversation = null;
        if (callActive) endCall({ silent: true });
      },
      onError: (err) => {
        const msg =
          (typeof err === "string" && err) ||
          err?.message ||
          String(err) ||
          "Voice agent error";
        errorTurn(msg);
        voiceStatus.textContent = msg;
      },
      onModeChange: (payload) => {
        const mode = payload?.mode || payload;
        callStage.classList.toggle("is-listening", mode === "listening");
        callStage.classList.toggle("is-speaking", mode === "speaking");
        micBtn.classList.toggle("listening", mode === "listening");
        if (mode === "listening") voiceStatus.textContent = "Listening…";
        else if (mode === "speaking") voiceStatus.textContent = "Speaking…";
        syncLivePill();
      },
      onMessage: (payload) => {
        const source = payload?.source || payload?.role || "";
        const text =
          (typeof payload === "string" && payload) ||
          payload?.message ||
          payload?.text ||
          "";
        if (!text) return;
        const fromUser = /user|human/i.test(String(source));
        if (fromUser) {
          userTurn(text);
          liveTranscript.textContent = `Heard: “${text}”`;
        } else {
          showPrompt(text);
          liveTranscript.textContent = "";
        }
      },
    });
  }

  async function startCall() {
    if (callActive) return;
    unlockTts();
    clearListenResume();
    const ok = await ensureMicPermission();
    if (!ok) return;

    callActive = true;
    syncCallChrome();

    if (voiceTransport === "elevenlabs" && elevenAgentId) {
      try {
        await startElevenCall();
        voiceStatus.textContent = callHint();
      } catch (err) {
        callActive = false;
        syncCallChrome();
        errorTurn(err.message || "Could not start ElevenLabs call");
        voiceStatus.textContent =
          "ElevenLabs unavailable — set agent id or use browser call";
        // Fall back to browser continuous call
        voiceTransport = "browser";
        if (recognition) {
          callActive = true;
          syncCallChrome();
          voiceStatus.textContent = "Browser call — speak after Lockline";
          if (!pendingSpeech && !callStage.classList.contains("is-speaking")) {
            scheduleListenAfterSpeak();
          }
        }
      }
      return;
    }

    voiceStatus.textContent = "Call started — speak after Lockline";
    if (!callStage.classList.contains("is-speaking") && !pendingSpeech) {
      scheduleListenAfterSpeak();
    }
  }

  async function endCall(opts = {}) {
    clearListenResume();
    callActive = false;
    stopListening();
    if (!opts.keepSpeech) stopSpeaking();
    if (elevenConversation) {
      try {
        await elevenConversation.endSession();
      } catch (_) {
        /* ignore */
      }
      elevenConversation = null;
    }
    syncCallChrome();
    if (!opts.silent) voiceStatus.textContent = callHint();
  }

  async function toggleCall() {
    suppressPendingSpeech = true;
    unlockTts();
    if (callActive) await endCall();
    else await startCall();
  }

  async function loadVoiceConfig() {
    try {
      const res = await fetch(apiUrl("/voice/config"));
      if (!res.ok) return;
      const cfg = await res.json();
      elevenAgentId =
        (cfg.elevenlabs_agent_id || window.ELEVENLABS_AGENT_ID || "").trim() ||
        null;
      if (elevenAgentId) {
        voiceTransport = "elevenlabs";
        if (deckLabel) deckLabel.textContent = "ElevenLabs line";
        speechSupport.textContent =
          "ElevenLabs Conversational AI · custom LLM → Lockline Orchestrator";
        if (elevenMount) {
          elevenMount.classList.remove("hidden");
          elevenMount.innerHTML =
            `<p class="speech-support">Agent <span class="mono">${escapeHtml(
              elevenAgentId.slice(0, 12)
            )}…</span> — Start call for natural turn-taking</p>`;
        }
      }
    } catch (_) {
      /* offline / CORS — keep browser transport */
    }
    syncCallChrome();
  }

  async function createSession() {
    messagesEl.innerHTML = "";
    currentPrompt.innerHTML = `<p class="prompt-placeholder">Starting session…</p>`;
    boundaryNote();
    stopSpeaking();
    setBusy(true);
    try {
      if (!API_BASE && /\.vercel\.app$/i.test(location.hostname)) {
        throw new Error(
          "API not linked — set Vercel env AAS_API_BASE to your Railway URL, then redeploy"
        );
      }
      const res = await fetch(apiUrl("/session"), { method: "POST" });
      if (!res.ok) throw new Error(`Could not start session (${res.status})`);
      const data = await res.json();
      setMeta(data.state, data.session_id);
      presentAssistantMessages(data.messages || []);
      // ElevenLabs owns audio when that transport is active.
      if (voiceTransport === "browser") {
        speakTexts(data.messages || []);
      }
    } catch (err) {
      errorTurn(err.message || "Failed to connect");
      setMeta("error");
    } finally {
      setBusy(false);
    }
  }

  async function readApiError(res) {
    const text = await res.text().catch(() => "");
    try {
      const detail = JSON.parse(text);
      if (typeof detail.detail === "string") return detail.detail;
      if (Array.isArray(detail.detail)) {
        return detail.detail.map((d) => d.msg || JSON.stringify(d)).join("; ");
      }
    } catch (_) {
      /* plain text body */
    }
    const trimmed = (text || "").trim();
    if (trimmed && trimmed.length < 240) return trimmed;
    return `Request failed (${res.status})`;
  }

  async function sendMessage(text) {
    if (!sessionId || busy || !text.trim()) return;
    userTurn(text.trim());
    setBusy(true);
    const confirmish = /^(confirm|yes|ok|okay|proceed|book it)$/i.test(text.trim());
    voiceStatus.textContent = confirmish
      ? "Booking your slot…"
      : "Thinking…";
    const controller = new AbortController();
    const abortTimer = window.setTimeout(() => controller.abort(), 90000);
    try {
      const res = await fetch(apiUrl(`/session/${sessionId}/message`), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: text.trim() }),
        signal: controller.signal,
      });
      if (!res.ok) throw new Error(await readApiError(res));
      const data = await res.json();
      setMeta(data.state, sessionId);
      presentAssistantMessages(data.messages || []);
      if (voiceTransport === "browser") {
        speakTexts(data.messages || []);
      }
      voiceStatus.textContent = callHint();
    } catch (err) {
      const msg = String(err && err.message ? err.message : err);
      // Safari often surfaces network/HTTP failures as "Load failed"
      if (/abort/i.test(msg)) {
        errorTurn("That took too long — tap Confirm again (booking uses a faster path now)");
      } else {
        errorTurn(
          /load failed|failed to fetch|networkerror/i.test(msg)
            ? "Connection glitch — tap a suggestion or type again"
            : msg || "Something went wrong"
        );
      }
      voiceStatus.textContent = callHint();
      if (callActive && voiceTransport === "browser") scheduleListenAfterSpeak();
    } finally {
      window.clearTimeout(abortTimer);
      setBusy(false);
    }
  }

  async function restartSession() {
    if (!confirm("Restart advisory pre-booking session?")) return;
    await endCall({ silent: true, keepSpeech: true });
    await createSession();
  }

  themeBtn.addEventListener("click", () => {
    applyTheme(html.classList.contains("dark") ? "light" : "dark");
  });

  restartBtn.addEventListener("click", restartSession);

  // Unlock browser TTS on first real gesture (page-load speech is blocked).
  // iOS often requires touchend (not only touchstart) to unlock audio.
  ["pointerdown", "pointerup", "keydown"].forEach((evt) => {
    document.addEventListener(evt, unlockTts, { once: true, capture: true });
  });

  micBtn.addEventListener("click", async (e) => {
    e.preventDefault();
    await toggleCall();
  });
  if (endCallBtn) {
    endCallBtn.addEventListener("click", async (e) => {
      e.preventDefault();
      await endCall();
    });
  }

  ttsToggle.addEventListener("click", () => {
    unlockTts();
    ttsEnabled = !ttsEnabled;
    localStorage.setItem("aas-tts", ttsEnabled ? "on" : "off");
    syncTtsButton();
    if (!ttsEnabled) {
      stopSpeaking();
      return;
    }
    // Audible confirmation so users know speakers / TTS work.
    speakTexts(["Voice replies are on"], { force: true });
  });
  stopSpeakBtn.addEventListener("click", () => {
    stopSpeaking();
    if (callActive && voiceTransport === "browser") scheduleListenAfterSpeak();
  });

  document.querySelector(".studio")?.addEventListener("click", (e) => {
    const send = e.target.closest("[data-send]");
    if (send) {
      suppressPendingSpeech = true;
      unlockTts();
      sendMessage(send.getAttribute("data-send"));
      return;
    }
    unlockTts();
    const copy = e.target.closest("[data-copy]");
    if (copy) {
      const val = copy.getAttribute("data-copy");
      navigator.clipboard?.writeText(val).then(() => {
        copy.textContent = "Copied";
        setTimeout(() => {
          copy.textContent = "Copy";
        }, 1200);
      });
    }
  });

  input.addEventListener("input", syncSendEnabled);

  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      form.requestSubmit();
    }
  });

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text || busy) return;
    input.value = "";
    syncSendEnabled();
    sendMessage(text);
  });

  initTheme();
  syncTtsButton();
  initTtsVoices();
  initSpeech();
  (async () => {
    await loadVoiceConfig();
    voiceStatus.textContent =
      ttsEnabled && window.speechSynthesis && voiceTransport === "browser"
        ? `Tap Start call once to enable sound · ${callHint()}`
        : callHint();
    await createSession();
  })();
})();
