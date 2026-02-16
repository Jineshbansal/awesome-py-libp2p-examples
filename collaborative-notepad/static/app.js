const RECONNECT_BASE_MS = 1000;
const RECONNECT_MAX_MS = 16000;

let ws = null;
let reconnectDelay = RECONNECT_BASE_MS;
let reconnectTimer = null;
let isConnected = false;

let suppressInput = false;
let lastKnownText = "";

const editorEl = document.getElementById("editor");
const wsUrlEl = document.getElementById("wsUrl");
const btnConnectEl = document.getElementById("btnConnect");
const statusDotEl = document.getElementById("statusDot");
const statusTextEl = document.getElementById("statusText");
const docIdEl = document.getElementById("docId");
const docInfoEl = document.getElementById("docInfo");
const peerCountEl = document.getElementById("peerCount");
const peerInfoEl = document.getElementById("peerInfo");
const charCountEl = document.getElementById("charCount");
const logPanelEl = document.getElementById("logPanel");

function toggleConnection() {
  if (isConnected) {
    disconnect();
  } else {
    connect();
  }
}

function connect() {
  const url = wsUrlEl.value.trim();
  if (!url) return;

  setStatus("connecting", "Connecting...");
  log("info", `Connecting to ${url}...`);

  try {
    ws = new WebSocket(url);
  } catch (e) {
    log("error", `Invalid URL: ${e.message}`);
    setStatus("disconnected", "Disconnected");
    return;
  }

  ws.onopen = () => {
    isConnected = true;
    reconnectDelay = RECONNECT_BASE_MS;
    setStatus("connected", "Connected");
    btnConnectEl.textContent = "Disconnect";
    btnConnectEl.className = "btn-disconnect";
    log("info", "Connected to backend peer");
  };

  ws.onmessage = (event) => {
    try {
      handleMessage(event.data);
    } catch (e) {
      log("error", "Message handling error: " + e.message);
    }
  };

  ws.onclose = (event) => {
    if (isConnected) {
      log("warn", "Connection lost — will reconnect...");
    }
    isConnected = false;
    setStatus("disconnected", "Disconnected");
    btnConnectEl.textContent = "Connect";
    btnConnectEl.className = "btn-connect";
    scheduleReconnect();
  };

  ws.onerror = () => {
    log("error", "WebSocket error");
  };
}

function disconnect() {
  clearTimeout(reconnectTimer);
  reconnectTimer = null;
  if (ws) {
    ws.onclose = null;
    ws.close();
    ws = null;
  }
  isConnected = false;
  setStatus("disconnected", "Disconnected");
  btnConnectEl.textContent = "Connect";
  btnConnectEl.className = "btn-connect";
  log("info", "Disconnected");
}

function scheduleReconnect() {
  if (reconnectTimer) return;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    if (!isConnected) {
      log("info", `Reconnecting (delay ${reconnectDelay}ms)...`);
      connect();
      reconnectDelay = Math.min(reconnectDelay * 2, RECONNECT_MAX_MS);
    }
  }, reconnectDelay);
}

function handleMessage(raw) {
  let msg;
  try {
    msg = JSON.parse(raw);
  } catch (e) {
    return;
  }

  switch (msg.type) {
    case "FULL_STATE":
      suppressInput = true;
      const cursor = editorEl.selectionStart;
      editorEl.value = msg.text || "";
      lastKnownText = editorEl.value;
      editorEl.selectionStart = editorEl.selectionEnd = Math.min(
        cursor,
        editorEl.value.length,
      );
      suppressInput = false;
      updateCharCount();
      if (msg.doc_id) {
        docIdEl.textContent = msg.doc_id;
        docInfoEl.style.display = "flex";
      }
      if (msg.peer_count !== undefined) {
        peerCountEl.textContent = msg.peer_count;
        peerInfoEl.style.display = "flex";
      }
      if (msg.peer_id) {
        log(
          "info",
          `Synced doc "${msg.doc_id || "default"}" from peer ${msg.peer_id.substring(0, 12)}...`,
        );
      }
      break;

    case "INSERT":
    case "DELETE":
      if (msg.text !== undefined) {
        suppressInput = true;
        const pos = editorEl.selectionStart;
        const oldLen = editorEl.value.length;
        editorEl.value = msg.text;
        lastKnownText = editorEl.value;
        const diff = editorEl.value.length - oldLen;
        editorEl.selectionStart = editorEl.selectionEnd = Math.max(
          0,
          pos + diff,
        );
        suppressInput = false;
        updateCharCount();
      }
      break;

    case "PEER_COUNT":
      peerCountEl.textContent = msg.count;
      peerInfoEl.style.display = "flex";
      break;

    case "PEER_JOIN":
      log(
        "info",
        `Peer joined: ${(msg.client_id || msg.peer_id || "").substring(0, 16)}`,
      );
      break;

    case "PEER_LEAVE":
      log(
        "info",
        `Peer left: ${(msg.client_id || msg.peer_id || "").substring(0, 16)}`,
      );
      break;

    case "CURSOR":
      break;

    default:
      break;
  }
}

let debounceTimer = null;

editorEl.addEventListener("input", () => {
  if (suppressInput) return;
  if (!isConnected || !ws) return;

  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => {
    sendDiff();
  }, 30);
});

function sendDiff() {
  const newText = editorEl.value;
  const oldText = lastKnownText;

  if (newText === oldText) return;

  let prefixLen = 0;
  const minLen = Math.min(oldText.length, newText.length);
  while (prefixLen < minLen && oldText[prefixLen] === newText[prefixLen]) {
    prefixLen++;
  }

  let suffixLen = 0;
  while (
    suffixLen < oldText.length - prefixLen &&
    suffixLen < newText.length - prefixLen &&
    oldText[oldText.length - 1 - suffixLen] ===
      newText[newText.length - 1 - suffixLen]
  ) {
    suffixLen++;
  }

  const deletedCount = oldText.length - prefixLen - suffixLen;
  const insertedText = newText.substring(prefixLen, newText.length - suffixLen);

  const ops = [];

  for (let i = deletedCount - 1; i >= 0; i--) {
    ops.push({ type: "DELETE", position: prefixLen + i });
  }

  for (let i = 0; i < insertedText.length; i++) {
    ops.push({
      type: "INSERT",
      position: prefixLen + i,
      char: insertedText[i],
    });
  }

  if (ops.length > 0) {
    try {
      ws.send(JSON.stringify({ type: "BATCH", ops: ops }));
    } catch (e) {
      log("error", "Send failed: " + e.message);
      return;
    }
    lastKnownText = newText;
    updateCharCount();
  }
}

function setStatus(state, text) {
  statusDotEl.className = "status-dot " + state;
  statusTextEl.textContent = text;
}

function updateCharCount() {
  charCountEl.textContent = editorEl.value.length;
}

function log(level, message) {
  const now = new Date();
  const time = now.toLocaleTimeString("en-US", { hour12: false });
  const entry = document.createElement("div");
  entry.className = "log-entry " + level;
  entry.innerHTML = `<span class="time">${time}</span>${escapeHtml(message)}`;
  logPanelEl.appendChild(entry);
  logPanelEl.scrollTop = logPanelEl.scrollHeight;

  while (logPanelEl.children.length > 200) {
    logPanelEl.removeChild(logPanelEl.firstChild);
  }
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

editorEl.addEventListener("keyup", updateCharCount);
updateCharCount();

window.addEventListener("load", () => {
  const params = new URLSearchParams(window.location.search);
  const wsParam = params.get("ws");
  if (wsParam) {
    wsUrlEl.value = wsParam;
  }
  log("info", "Ready — click Connect or press Enter in the address field");
});

wsUrlEl.addEventListener("keypress", (e) => {
  if (e.key === "Enter") toggleConnection();
});
