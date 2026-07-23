const state = {
  devices: [],
  media: [],
  selectedId: null,
  resources: null,
};

const $ = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: options.body instanceof FormData ? {} : { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    if (response.status === 401) {
      window.location.href = `/login?next=${encodeURIComponent(window.location.pathname)}`;
      throw new Error("Phiên đăng nhập đã hết hạn");
    }
    let message = `${response.status} ${response.statusText}`;
    try {
      const payload = await response.json();
      message = payload.detail || message;
    } catch (_) {
      // Keep HTTP status when the response is not JSON.
    }
    throw new Error(message);
  }
  return response.status === 204 ? null : response.json();
}

function icon(name) {
  return `<svg aria-hidden="true"><use href="#i-${name}"></use></svg>`;
}

function toast(message, type = "info") {
  const node = document.createElement("div");
  node.className = `toast is-${type}`;
  node.setAttribute("role", type === "error" ? "alert" : "status");
  node.textContent = message;
  $("toastRegion").append(node);
  window.setTimeout(() => node.remove(), 3800);
}

function selectedDevice() {
  return state.devices.find((device) => device.id === state.selectedId) || null;
}

function requireDevice() {
  const device = selectedDevice();
  if (!device) {
    toast("Hãy chọn một thiết bị trước.", "error");
    return null;
  }
  return device;
}

function renderDevices() {
  const query = $("deviceSearch").value.trim().toLowerCase();
  const visible = state.devices.filter((device) => device.name.toLowerCase().includes(query));
  $("deviceCount").textContent = state.devices.length;
  $("onlineCount").textContent = state.devices.filter((device) => device.status === "online").length;
  if (!visible.length) {
    $("deviceList").innerHTML = `<div class="empty-card">${state.devices.length ? "Không tìm thấy thiết bị." : "Chưa có thiết bị. Thêm cloud device hoặc ADB target để bắt đầu."}</div>`;
    return;
  }
  $("deviceList").innerHTML = visible.map((device) => `
    <button class="device-card ${device.id === state.selectedId ? "is-selected" : ""}" data-device-id="${device.id}">
      <span class="device-card__icon">${icon("device")}</span>
      <span>
        <span class="device-card__name">${escapeHtml(device.name)}</span>
        <span class="device-card__meta">${escapeHtml(device.transport.toUpperCase())}${device.battery_level != null ? ` · ${device.battery_level}%` : ""}</span>
      </span>
      <span class="status-dot is-${device.status}" aria-label="${device.status}"></span>
    </button>
  `).join("");
  document.querySelectorAll("[data-device-id]").forEach((button) => {
    button.addEventListener("click", () => selectDevice(Number(button.dataset.deviceId)));
  });
}

function renderSelected() {
  const device = selectedDevice();
  $("launchTikTokButton").disabled = !device;
  $("runBrowseButton").disabled = !device;
  $("pushMediaButton").disabled = !device || !state.media.length;
  if (!device) {
    $("selectedDeviceName").textContent = "Chọn một thiết bị";
    $("selectedDeviceMeta").textContent = "Thiết bị được chọn sẽ xuất hiện tại đây";
    $("selectedStatus").textContent = "offline";
    $("selectedStatus").className = "status-badge is-offline";
    return;
  }
  $("selectedDeviceName").textContent = device.name;
  $("selectedDeviceMeta").textContent = `${device.transport.toUpperCase()}${device.address ? ` · ${device.address}` : ""}${device.helper?.version_name ? ` · Helper ${device.helper.version_name}` : ""}`;
  $("selectedStatus").textContent = device.status;
  $("selectedStatus").className = `status-badge is-${device.status}`;
}

function selectDevice(id) {
  state.selectedId = id;
  renderDevices();
  renderSelected();
  resetScreen();
}

function resetScreen() {
  $("deviceScreen").hidden = true;
  $("deviceScreen").removeAttribute("src");
  $("screenEmpty").hidden = false;
  $("screenUpdated").textContent = "Chưa chụp";
}

async function refreshDevices() {
  state.devices = await api("/api/devices");
  if (state.selectedId && !state.devices.some((device) => device.id === state.selectedId)) {
    state.selectedId = null;
  }
  if (!state.selectedId && state.devices.length) state.selectedId = state.devices[0].id;
  renderDevices();
  renderSelected();
}

async function runAction(action, params = {}) {
  const device = requireDevice();
  if (!device) return null;
  return api(`/api/devices/${device.id}/actions/${action}`, {
    method: "POST",
    body: JSON.stringify({ params }),
  });
}

async function refreshScreen() {
  try {
    const response = await runAction("screenshot");
    if (!response) return;
    const result = response.result || {};
    const data = result.data || result.image_base64 || (typeof result === "string" ? result : null);
    if (!data) throw new Error("Helper không trả về dữ liệu ảnh");
    $("deviceScreen").src = `data:image/${result.format || result.mime?.split("/")[1] || "png"};base64,${data}`;
    $("deviceScreen").hidden = false;
    $("screenEmpty").hidden = true;
    $("screenUpdated").textContent = `Vừa chụp · ${new Date().toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" })}`;
  } catch (error) {
    toast(`Không chụp được màn hình: ${error.message}`, "error");
  }
}

async function refreshRuns() {
  const runs = await api("/api/runs?limit=12");
  if (!runs.length) {
    $("activityList").innerHTML = '<div class="empty-activity">Chưa có workflow nào được chạy.</div>';
    return;
  }
  $("activityList").innerHTML = runs.map((run) => {
    const lastStep = run.steps.at(-1);
    return `
      <article class="activity-item">
        <span class="activity-marker is-${run.status}"></span>
        <div class="activity-copy">
          <strong>${escapeHtml(run.workflow)} · ${escapeHtml(run.status)}</strong>
          <span>${escapeHtml(lastStep?.detail || run.error || `${run.steps.length} bước`)}</span>
          <time>${formatTime(run.started_at || run.created_at)}</time>
        </div>
      </article>
    `;
  }).join("");
}

async function refreshMedia() {
  state.media = await api("/api/media");
  $("mediaSelect").innerHTML = state.media.length
    ? state.media.map((item) => `<option value="${item.id}">${escapeHtml(item.filename)} · ${formatBytes(item.size_bytes)}</option>`).join("")
    : '<option value="">Chưa có media</option>';
  renderSelected();
}

async function refreshAll() {
  try {
    await Promise.all([refreshDevices(), refreshRuns(), refreshMedia()]);
  } catch (error) {
    toast(`Không thể làm mới: ${error.message}`, "error");
  }
}

async function createDevice(event) {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  try {
    const result = await api("/api/devices", {
      method: "POST",
      body: JSON.stringify({
        name: form.get("name"),
        transport: form.get("transport"),
        address: form.get("address"),
      }),
    });
    const output = $("provisionResult");
    output.hidden = false;
    output.innerHTML = result.token
      ? `<strong>Token chỉ hiển thị một lần:</strong><br>${escapeHtml(result.token)}<br><br><strong>WebSocket:</strong><br>${escapeHtml(result.websocket_url)}`
      : "ADB device đã được tạo.";
    state.selectedId = result.device.id;
    await refreshDevices();
    toast("Đã tạo thiết bị.", "success");
  } catch (error) {
    toast(`Không tạo được thiết bị: ${error.message}`, "error");
  }
}

async function uploadMedia(file) {
  if (!file) return;
  const form = new FormData();
  form.append("file", file);
  try {
    await api("/api/media", { method: "POST", body: form });
    await refreshMedia();
    toast(`Đã lưu ${file.name}.`, "success");
  } catch (error) {
    toast(`Upload thất bại: ${error.message}`, "error");
  } finally {
    $("mediaFile").value = "";
  }
}

function bindEvents() {
  $("deviceSearch").addEventListener("input", renderDevices);
  $("addDeviceButton").addEventListener("click", () => {
    $("provisionResult").hidden = true;
    $("deviceDialog").showModal();
  });
  $("deviceForm").addEventListener("submit", createDevice);
  $("refreshAllButton").addEventListener("click", refreshAll);
  $("refreshScreenButton").addEventListener("click", refreshScreen);
  $("launchTikTokButton").addEventListener("click", async () => {
    try {
      await runAction("launch_app", { package: "com.ss.android.ugc.trill" });
      toast("Đã gửi lệnh mở TikTok.", "success");
    } catch (error) {
      toast(error.message, "error");
    }
  });
  document.querySelectorAll("[data-key]").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        await runAction("global_action", { action: button.dataset.key });
      } catch (error) {
        toast(error.message, "error");
      }
    });
  });
  document.querySelectorAll("[data-swipe]").forEach((button) => {
    button.addEventListener("click", async () => {
      const up = button.dataset.swipe === "up";
      try {
        await runAction("swipe", {
          x1: 540, y1: up ? 1700 : 520, x2: 540, y2: up ? 520 : 1700, duration: 340,
        });
      } catch (error) {
        toast(error.message, "error");
      }
    });
  });
  $("textForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const text = $("deviceText").value;
    if (!text) return;
    try {
      await runAction("type_text", { text });
      $("deviceText").value = "";
      toast("Đã gửi văn bản.", "success");
    } catch (error) {
      toast(error.message, "error");
    }
  });
  $("mediaFile").addEventListener("change", (event) => uploadMedia(event.target.files[0]));
  $("pushMediaButton").addEventListener("click", async () => {
    const device = requireDevice();
    const mediaId = $("mediaSelect").value;
    if (!device || !mediaId) return;
    try {
      await api(`/api/devices/${device.id}/media/${mediaId}`, { method: "POST" });
      toast("Media đã được đẩy tới DCIM.", "success");
    } catch (error) {
      toast(error.message, "error");
    }
  });
  $("runBrowseButton").addEventListener("click", async () => {
    const device = requireDevice();
    if (!device) return;
    try {
      await api(`/api/devices/${device.id}/runs`, {
        method: "POST",
        body: JSON.stringify({
          workflow: "tiktok.browse",
          params: {
            count: Number($("browseCount").value),
            view_seconds: Number($("viewSeconds").value),
          },
        }),
      });
      toast("Workflow đã vào hàng đợi.", "success");
      await refreshRuns();
    } catch (error) {
      toast(error.message, "error");
    }
  });
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;",
  }[char]));
}

function formatTime(value) {
  return new Date(value).toLocaleString("vi-VN", {
    day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
  });
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
}

async function init() {
  bindEvents();
  try {
    state.resources = await api("/api/resources");
    $("serverUrl").textContent = state.resources.public_url;
    $("serverDot").classList.add("is-online");
    await refreshAll();
  } catch (error) {
    $("serverLabel").textContent = "Control plane unavailable";
    toast(error.message, "error");
  }
  window.setInterval(() => {
    refreshDevices().catch(() => {});
    refreshRuns().catch(() => {});
  }, 4000);
}

init();
