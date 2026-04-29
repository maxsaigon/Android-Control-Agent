/**
 * Android Control Dashboard — Redesigned Client-side JavaScript
 */

const API = '';  // Same origin
let devices = [];
let templates = [];
let templateMap = {};
let dashboardOverview = null;
let selectedTemplateName = '';
let refreshTimer = null;
let currentPage = 'dashboard';
let isConfirming = false;
let liveStepData = {};  // {taskId: {current_step, action, detail, steps: [...], started_at}}
let subscribedTasks = new Set();

// ===== AUTH =====

/**
 * Global fetch wrapper — redirects to /login on 401 Unauthorized.
 * Replace all direct fetch() calls with apiFetch() for API requests.
 * For backward compat, we also patch the native fetch below.
 */
let _authRedirectPending = false;
const _originalFetch = window.fetch.bind(window);
window.fetch = async function(url, opts) {
  const res = await _originalFetch(url, opts);
  if (res.status === 401 && !_authRedirectPending) {
    // Only redirect for API calls (not for /auth/* itself)
    const urlStr = typeof url === 'string' ? url : url?.url || '';
    if (!urlStr.includes('/auth/')) {
      _authRedirectPending = true;
      console.warn('🔒 Session expired — redirecting to login');
      window.location.href = '/login?next=' + encodeURIComponent(window.location.pathname);
    }
  }
  return res;
};

async function logout() {
  try {
    await _originalFetch('/auth/logout', { method: 'POST', credentials: 'include' });
  } catch (_) { /* ignore */ }
  window.location.href = '/login';
}

// Load current user info into header
async function loadUserInfo() {
  try {
    const res = await _originalFetch('/auth/me', { credentials: 'include' });
    if (res.ok) {
      const data = await res.json();
      const el = document.getElementById('currentUser');
      if (el) el.textContent = `👤 ${data.username}`;
    }
  } catch (_) { /* optional */ }
}

// ===== INITIALIZATION =====

document.addEventListener('DOMContentLoaded', () => {
    init();
});

async function init() {
    loadUserInfo();  // Load user info async (non-blocking)
    await Promise.all([
        refreshDevices(),
        loadTemplates(),
        refreshRunning(),
        refreshHistory(),
        refreshStats(),
        refreshRecentOutcomes(),
    ]);
    updateCostEstimate();
    // Auto-refresh every 3 seconds
    refreshTimer = setInterval(() => {
        refreshDevices();
        refreshRunning();
        refreshQueueStatus();
        if (currentPage === 'videos') {
            refreshAssignments();
        }
    }, 3000);
    // History + Stats every 10s
    setInterval(refreshHistory, 10000);
    setInterval(refreshStats, 10000);
    setInterval(refreshRecentOutcomes, 10000);
}

// ===== SIDEBAR NAVIGATION =====

function navigateTo(section, btn) {
    currentPage = section;
    // Update nav buttons
    document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
    if (btn) btn.classList.add('active');

    // Update page sections
    document.querySelectorAll('.page-section').forEach(s => s.classList.remove('active'));
    const target = document.getElementById('section' + section.charAt(0).toUpperCase() + section.slice(1));
    if (target) {
        target.classList.remove('active');
        // Force reflow for animation
        void target.offsetHeight;
        target.classList.add('active');
    }

    // Update page title
    const titles = { dashboard: 'Dashboard', devices: 'Devices', scheduler: 'Scheduler', history: 'History', videos: 'Videos & Distribution' };
    document.getElementById('pageTitle').textContent = titles[section] || 'Dashboard';

    // Load data for section
    if (section === 'dashboard') {
        refreshStats();
        refreshRecentOutcomes();
        refreshRunning();
    }
    if (section === 'scheduler') loadSchedules();
    if (section === 'history') refreshHistory();
    if (section === 'videos') {
        refreshVideos();
        refreshAssignments();
        refreshDeviceAccounts();
        _populateAccountDeviceSelect();
    }
}

function toggleSidebar() {
    document.getElementById('sidebar').classList.toggle('open');
}

// ===== STATS =====

async function refreshStats() {
    try {
        const res = await fetch(`${API}/api/dashboard/overview`);
        dashboardOverview = await res.json();
        const snapshot = dashboardOverview.snapshot || {};
        const devicesSnap = snapshot.devices || {};
        const queueSnap = snapshot.queue || {};
        const aiSnap = snapshot.ai || {};
        const primary = dashboardOverview.primary_template;

        document.getElementById('statDevices').textContent = devicesSnap.total ?? 0;
        document.getElementById('statDevicesSub').textContent =
            `${devicesSnap.online || 0} online · ${devicesSnap.busy || 0} busy · ${devicesSnap.offline || 0} offline`;

        document.getElementById('statCommentSessions').textContent = snapshot.active_comment_sessions ?? 0;
        document.getElementById('statTasksSub').textContent =
            `${queueSnap.running_tasks || 0} running · ${snapshot.recent_failures_24h || 0} fails / 24h`;

        document.getElementById('statCost').textContent = `$${(aiSnap.total_cost || 0).toFixed(3)}`;
        document.getElementById('statCostSub').textContent =
            `${snapshot.tasks_today?.total || 0} tasks today`;

        document.getElementById('statRate').textContent = `${aiSnap.recent_success_rate ?? 100}%`;
        document.getElementById('statRateSub').textContent =
            `${aiSnap.success_rate ?? 100}% all-time · ${primary?.title || 'No primary template'}`;

        if (document.getElementById('queueCount')) {
            document.getElementById('queueCount').textContent = queueSnap.running_tasks || 0;
        }

        renderPrimaryTemplateSummary();
        renderTemplateLibrary();
    } catch (e) { /* retry */ }
}

// ===== DEVICES =====

async function refreshDevices() {
    try {
        const res = await fetch(`${API}/api/devices`);
        devices = await res.json();
        renderDevices();
        updateDeviceSelect();
        
        // Also refresh pending links
        await refreshPendingDevices();

    } catch (e) {
        document.getElementById('serverStatus').innerHTML =
            '<span class="pulse" style="background:var(--red)"></span><span style="color:var(--red)">Disconnected</span>';
    }
}

function renderDevices() {
    if (isConfirming) return; // Don't re-render during confirm dialog
    const container = document.getElementById('deviceList');
    const countEl = document.getElementById('deviceCount');
    if (countEl) countEl.textContent = devices.length;

    if (!devices.length) {
        container.innerHTML = '<div class="empty-state"><div class="empty-icon">📱</div><div class="empty-text">Chưa có device nào<br><small style="color:var(--text-muted)">Thêm device ở form bên phải →</small></div></div>';
        return;
    }
    container.innerHTML = '<div class="device-grid">' + devices.map(d => {
        const statusMap = {
            online: { label: '🟢 Online', cls: 'online' },
            offline: { label: '🔴 Offline', cls: 'offline' },
            busy: { label: '🟡 Busy', cls: 'busy' },
            unauthorized: { label: '🔒 Unauthorized', cls: 'unauthorized' },
        };
        const st = statusMap[d.status] || statusMap.offline;
        const lastSeen = d.last_seen
            ? new Date(d.last_seen).toLocaleString('vi-VN', {
                hour: '2-digit', minute: '2-digit',
                day: '2-digit', month: '2-digit'
            })
            : '—';

        return `
            <div class="device-card ${st.cls}" onclick="selectDevice(${d.id})" id="dev-${d.id}">
                <div class="device-header">
                    <span class="device-name">
                        ${d.name}
                        <button class="btn-icon" onclick="event.stopPropagation(); renameDevice(${d.id}, '${d.name.replace(/'/g, "\\'")}')" title="Đổi tên">✏️</button>
                    </span>
                    <span class="device-status status-${d.status}">${st.label}</span>
                </div>
                <div class="device-info">
                    <span>🌐 ${d.ip_address}:${d.adb_port}</span>
                    <span>📱 ${d.device_model || 'Unknown'}</span>
                    ${d.battery_level !== null && d.battery_level !== undefined ? `<span>🔋 ${d.battery_level}%</span>` : ''}
                    ${d.android_version ? `<span>🤖 Android ${d.android_version}</span>` : ''}
                    <span>🕐 ${lastSeen}</span>
                </div>
                ${d.status === 'unauthorized' ? '<div class="device-warning">⚠️ Chấp nhận kết nối ADB trên phone</div>' : ''}
                <div class="device-actions">
                    ${d.status === 'offline'
                        ? `<button class="btn btn-xs btn-primary" onclick="event.stopPropagation(); connectDevice(${d.id})">🔗 Connect</button>`
                        : d.status === 'unauthorized'
                        ? `<button class="btn btn-xs btn-primary" onclick="event.stopPropagation(); connectDevice(${d.id})">🔄 Retry</button>`
                        : `<button class="btn btn-xs btn-ghost" onclick="event.stopPropagation(); disconnectDevice(${d.id})">Disconnect</button>`
                    }
                    <button class="btn btn-xs btn-ghost" onclick="event.stopPropagation(); checkDeviceStatus(${d.id})">📡 Status</button>
                    <button class="btn btn-xs btn-danger" onclick="event.stopPropagation(); deleteDevice(${d.id}, this)">🗑️</button>
                </div>
            </div>
        `;
    }).join('') + '</div>';
}

function selectDevice(id) {
    document.getElementById('deviceSelect').value = id;
    document.querySelectorAll('.device-card').forEach(c => c.classList.remove('selected'));
    const card = document.getElementById(`dev-${id}`);
    if (card) card.classList.add('selected');
}

function updateDeviceSelect() {
    const sel = document.getElementById('deviceSelect');
    const current = sel.value;
    sel.innerHTML = '<option value="">Chọn device...</option>' +
        devices.map(d => `<option value="${d.id}">${d.name} (${d.ip_address}) — ${d.status}</option>`).join('');
    if (current) sel.value = current;
    // Also update account device select on Videos tab
    _populateAccountDeviceSelect();
}

async function connectDevice(id) {
    toast('Connecting...', 'info');
    try {
        const res = await fetch(`${API}/api/devices/${id}/connect`, { method: 'POST' });
        const data = await res.json();
        if (res.ok) {
            toast(`✅ Connected: ${data.device.device_model}`, 'success');
        } else {
            toast(`❌ ${data.detail}`, 'error');
        }
        refreshDevices();
        refreshStats();
    } catch (e) { toast('Connection failed', 'error'); }
}

async function disconnectDevice(id) {
    toast('Disconnecting...', 'info');
    try {
        await fetch(`${API}/api/devices/${id}/disconnect`, { method: 'POST' });
        toast('Disconnected', 'success');
        refreshDevices();
        refreshStats();
    } catch (e) { toast('Failed', 'error'); }
}

async function renameDevice(id, currentName) {
    // Already editing — ignore
    if (isConfirming) return;
    isConfirming = true;

    const card = document.getElementById(`dev-${id}`);
    if (!card) { isConfirming = false; return; }

    const nameEl = card.querySelector('.device-name');
    if (!nameEl) { isConfirming = false; return; }

    // Replace name text with input field
    const oldHTML = nameEl.innerHTML;
    nameEl.innerHTML = `<input type="text" class="rename-input" value="${currentName}" 
        onclick="event.stopPropagation()" 
        onkeydown="if(event.key==='Enter'){saveDeviceName(${id},this.value);event.stopPropagation()}else if(event.key==='Escape'){cancelRename()}"
        onblur="saveDeviceName(${id},this.value)">`;
    const input = nameEl.querySelector('input');
    input.focus();
    input.select();
}

async function saveDeviceName(id, newName) {
    if (!isConfirming) return; // Already saved/cancelled
    isConfirming = false;
    if (!newName || !newName.trim()) {
        refreshDevices();
        return;
    }
    try {
        const res = await fetch(`${API}/api/devices/${id}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: newName.trim() }),
        });
        if (res.ok) {
            toast(`✏️ Đã đổi tên → ${newName.trim()}`, 'success');
        }
    } catch (e) { toast('Đổi tên thất bại', 'error'); }
    refreshDevices();
}

function cancelRename() {
    isConfirming = false;
    refreshDevices();
}

let deleteConfirmId = null;
let deleteConfirmTimer = null;

function deleteDevice(id, btnEl) {
    // Two-click confirmation: first click → "Sure?", second click → delete
    if (deleteConfirmId === id) {
        // Second click — actually delete
        clearTimeout(deleteConfirmTimer);
        deleteConfirmId = null;
        doDeleteDevice(id);
    } else {
        // First click — show confirmation
        if (deleteConfirmTimer) clearTimeout(deleteConfirmTimer);
        deleteConfirmId = id;
        if (btnEl) {
            btnEl.textContent = '⚠️ Sure?';
            btnEl.classList.add('btn-warning');
        }
        // Auto-reset after 3 seconds
        deleteConfirmTimer = setTimeout(() => {
            deleteConfirmId = null;
            if (btnEl) {
                btnEl.textContent = '🗑️';
                btnEl.classList.remove('btn-warning');
            }
        }, 3000);
    }
}

async function doDeleteDevice(id) {
    try {
        await fetch(`${API}/api/devices/${id}`, { method: 'DELETE' });
        toast('🗑️ Đã xóa device', 'success');
        refreshDevices();
        refreshStats();
    } catch (e) { toast('Failed', 'error'); }
}

async function refreshPendingDevices() {
    try {
        const res = await fetch(`${API}/api/device/link/requests`);
        if (!res.ok) return;
        const pending = await res.json();
        
        const countEl = document.getElementById('pendingCount');
        const listEl = document.getElementById('pendingDevicesList');
        const panelEl = document.getElementById('pendingDevicesPanel');
        if (!countEl || !listEl || !panelEl) return;
        
        countEl.textContent = pending.length;
        if (pending.length === 0) {
            panelEl.style.display = 'none';
            listEl.innerHTML = '<div class="empty-state">Không có yêu cầu nào</div>';
            return;
        }
        panelEl.style.display = 'block';
        
        listEl.innerHTML = '<div class="device-grid" style="grid-template-columns: repeat(auto-fill, minmax(320px, 1fr))">' + pending.map(req => {
            const timeAgo = Math.round((new Date() - new Date(req.created_at)) / 60000);
            return `
                <div class="device-card" style="border-color: var(--blue)">
                    <div class="device-header">
                        <span class="device-name">${escapeHtml(req.device_name)}</span>
                        <span class="device-status status-busy">⏳ Pending</span>
                    </div>
                    <div class="device-info">
                        <span>👤 User: ${escapeHtml(req.username)}</span>
                        <span>📱 ${escapeHtml(req.device_model || 'Unknown')}</span>
                        ${req.android_version ? `<span>🤖 Android ${escapeHtml(req.android_version)}</span>` : ''}
                        <span>🕐 ${timeAgo}m ago</span>
                    </div>
                    <div class="device-actions" style="margin-top: 12px">
                        <button class="btn btn-sm btn-primary" style="flex:1" onclick="acceptDeviceLink('${req.request_id}')">✅ Accept</button>
                        <button class="btn btn-sm btn-danger" style="flex:1" onclick="rejectDeviceLink('${req.request_id}')">❌ Reject</button>
                    </div>
                </div>
            `;
        }).join('') + '</div>';
    } catch (e) {
        // ignore
    }
}

async function acceptDeviceLink(requestId) {
    try {
        const res = await fetch(`${API}/api/device/link/requests/${requestId}/accept`, { method: 'POST' });
        if (res.ok) {
            toast('✅ Accepted device', 'success');
            refreshDevices();
        } else {
            const err = await res.json();
            toast(`❌ Failed: ${err.detail || 'Unknown'}`, 'error');
        }
    } catch(e) {
        toast('Failed', 'error');
    }
}

async function rejectDeviceLink(requestId) {
    try {
        const res = await fetch(`${API}/api/device/link/requests/${requestId}/reject`, { method: 'POST' });
        if (res.ok) {
            toast('❌ Rejected device', 'success');
            refreshDevices();
        } else {
            const err = await res.json();
            toast(`❌ Failed: ${err.detail || 'Unknown'}`, 'error');
        }
    } catch(e) {
        toast('Failed', 'error');
    }
}

async function addDevice(event) {
    event.preventDefault();
    const payload = {
        name: document.getElementById('devName').value,
        ip_address: document.getElementById('devIp').value,
        adb_port: parseInt(document.getElementById('devPort').value),
    };

    try {
        const res = await fetch(`${API}/api/devices`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        if (!res.ok) {
            const err = await res.json();
            toast(`❌ ${err.detail}`, 'error');
            return;
        }
        const device = await res.json();
        toast(`📱 Đã thêm "${device.name}"`, 'success');
        document.getElementById('addDeviceForm').reset();
        document.getElementById('devPort').value = '5555';

        await refreshDevices();

        // Auto-connect nếu checkbox checked
        if (document.getElementById('devAutoConnect').checked) {
            toast('🔗 Đang kết nối ADB...', 'info');
            await connectDevice(device.id);
        }
        refreshStats();
    } catch (e) {
        toast(`Lỗi: ${e.message}`, 'error');
    }
}

async function checkDeviceStatus(id) {
    toast('📡 Checking...', 'info');
    try {
        const res = await fetch(`${API}/api/devices/${id}/status`);
        const data = await res.json();
        const batteryInfo = data.battery_level ? ` 🔋${data.battery_level}%` : '';
        if (data.reachable) {
            toast(`✅ ${data.name}: ${data.status}${batteryInfo}`, 'success');
        } else {
            toast(`🔴 ${data.name}: offline — không thể kết nối`, 'error');
        }
        refreshDevices();
    } catch (e) { toast('Check failed', 'error'); }
}

async function scanLAN() {
    const subnet = document.getElementById('scanSubnet').value.trim();
    const port = parseInt(document.getElementById('scanPort').value);
    const btn = document.getElementById('scanBtn');
    const results = document.getElementById('scanResults');

    btn.disabled = true;
    btn.textContent = '⏳ Đang quét...';
    results.innerHTML = '<div class="loading">Quét ' + subnet + '.0/24 — khoảng 5-15 giây...</div>';

    try {
        const res = await fetch(`${API}/api/devices/scan`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ subnet, port }),
        });
        const raw = await res.text();
        let data = {};
        try {
            data = raw ? JSON.parse(raw) : {};
        } catch (_) {
            data = null;
        }

        if (!res.ok) {
            throw new Error(data?.detail || raw || `HTTP ${res.status}`);
        }

        if (!data.devices || data.devices.length === 0) {
            results.innerHTML = '<div class="empty-state"><div class="empty-icon">🔍</div><div class="empty-text">Không tìm thấy thiết bị ADB<br><small style="color:var(--text-muted)">Kiểm tra WiFi Debugging trên phone</small></div></div>';
            return;
        }

        results.innerHTML = data.devices.map(d => {
            const statusMap = {
                connected: { label: '🟢 Connected', cls: 'online' },
                unauthorized: { label: '🔒 Unauthorized', cls: 'unauthorized' },
                unknown: { label: '❓ Unknown', cls: 'offline' },
            };
            const st = statusMap[d.status] || statusMap.unknown;

            return `
                <div class="scan-result ${st.cls}">
                    <div class="scan-result-info">
                        <strong>${d.ip}:${d.port}</strong>
                        <span class="device-status status-${d.status === 'connected' ? 'online' : d.status}">${st.label}</span>
                    </div>
                    <div class="scan-result-meta">
                        ${d.model ? `📱 ${d.model}` : ''}
                        ${d.android_version ? ` · 🤖 Android ${d.android_version}` : ''}
                    </div>
                    <div class="scan-result-actions">
                        ${d.already_registered
                            ? '<span style="color:var(--text-muted);font-size:12px">✅ Đã thêm</span>'
                            : d.status === 'unauthorized'
                            ? '<span style="color:var(--yellow);font-size:12px">🔒 Chấp nhận kết nối trên phone trước</span>'
                            : `<button class="btn btn-xs btn-primary" onclick="addScannedDevice('${d.ip}', ${d.port}, '${d.model || d.ip}')">➕ Thêm</button>`
                        }
                    </div>
                </div>
            `;
        }).join('');

        toast(`🔍 Tìm thấy ${data.devices.length} thiết bị`, 'success');
    } catch (e) {
        results.innerHTML = `<div class="empty-state"><div class="empty-text" style="color:var(--red)">Scan failed: ${escapeHtml(e.message || 'Unknown error')}</div></div>`;
        toast(`Scan failed: ${e.message || 'Unknown error'}`, 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = '🔍 Quét thiết bị';
    }
}

async function addScannedDevice(ip, port, model) {
    const payload = { name: model, ip_address: ip, adb_port: port };
    try {
        const res = await fetch(`${API}/api/devices`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        if (res.ok) {
            const device = await res.json();
            toast(`📱 Đã thêm "${device.name}"`, 'success');
            await connectDevice(device.id);
            refreshDevices();
            // Re-scan to update buttons
            scanLAN();
        } else {
            const err = await res.json();
            toast(`❌ ${err.detail}`, 'error');
        }
    } catch (e) { toast(`Lỗi: ${e.message}`, 'error'); }
}


// ===== TEMPLATES =====
async function loadTemplates() {
    try {
        const res = await fetch(`${API}/api/templates`);
        templates = await res.json();
        templateMap = Object.fromEntries(templates.map(t => [t.name, t]));

        const countEl = document.getElementById('templateCount');
        if (countEl) countEl.textContent = templates.length;

        renderTemplateLibrary();

        const preferred = templates.find(t => t.is_primary) || templates[0];
        if (preferred && (!selectedTemplateName || !templateMap[selectedTemplateName])) {
            selectDashboardTemplate(preferred.name);
        } else if (selectedTemplateName) {
            selectDashboardTemplate(selectedTemplateName);
        }
    } catch (e) { /* templates optional */ }
}

function templateModeChip(mode) {
    const map = {
        hybrid: '<span class="template-chip hybrid">Hybrid</span>',
        script: '<span class="template-chip script">Script</span>',
        ai: '<span class="template-chip ai">AI</span>',
    };
    return map[mode] || `<span class="template-chip muted">${escapeHtml(mode || 'unknown')}</span>`;
}

function templateStatusChip(template) {
    if (template.is_primary) {
        return '<span class="template-chip primary">Primary</span>';
    }
    return `<span class="template-chip ${escapeHtml(template.status || '')}">${escapeHtml(template.status || 'active')}</span>`;
}

function renderTemplateLibrary() {
    const container = document.getElementById('templateLibrary');
    if (!container) return;

    const primary = templates.filter(t => t.is_primary);
    const secondary = templates.filter(
        t => t.platform === 'tiktok' && !t.is_primary && t.implemented
    );
    const other = templates.filter(
        t => t.platform !== 'tiktok' && t.implemented
    );
    const planned = templates.filter(t => !t.implemented || t.status === 'planned');

    const groups = [
        ['Primary', primary],
        ['Secondary TikTok', secondary],
        ['Other Platforms', other],
        ['Planned', planned],
    ].filter(([, items]) => items.length);

    container.innerHTML = groups.map(([title, items]) => `
        <div class="template-library-group">
            <div class="panel-kicker">${title}</div>
            <div class="template-library-grid">
                ${items.map(template => {
                    const active = template.name === selectedTemplateName ? 'active' : '';
                    const running = dashboardOverview?.running?.by_template?.[template.name] || 0;
                    return `
                        <button type="button" class="template-library-card ${active}" onclick="selectDashboardTemplate('${template.name}')">
                            <div class="template-library-top">
                                <div class="template-library-badges">
                                    ${templateStatusChip(template)}
                                    ${templateModeChip(template.mode)}
                                </div>
                                <span class="template-mini-stat">${escapeHtml(template.platform)}</span>
                            </div>
                            <h4>${escapeHtml(template.title)}</h4>
                            <p>${escapeHtml(template.description || 'No description')}</p>
                            <div class="template-library-foot">
                                <span class="template-mini-stat">Risk: ${escapeHtml(template.risk_level || 'medium')}</span>
                                <span class="template-mini-stat">Running: ${running}</span>
                            </div>
                        </button>
                    `;
                }).join('')}
            </div>
        </div>
    `).join('');
}

function renderPrimaryTemplateSummary() {
    const template = templateMap[selectedTemplateName] || dashboardOverview?.primary_template || templates.find(t => t.is_primary) || templates[0];
    if (!template) return;

    const titleEl = document.getElementById('primaryTemplateTitle');
    const descEl = document.getElementById('primaryTemplateDescription');
    const badgesEl = document.getElementById('primaryTemplateBadges');
    const statsEl = document.getElementById('primaryTemplateStats');
    const metaEl = document.getElementById('composerMeta');

    if (titleEl) titleEl.textContent = template.title;
    if (descEl) descEl.textContent = template.description || '';
    if (badgesEl) {
        badgesEl.innerHTML = `
            ${templateStatusChip(template)}
            ${templateModeChip(template.mode)}
            <span class="template-chip muted">Risk ${escapeHtml(template.risk_level || 'medium')}</span>
        `;
    }
    if (metaEl) {
        metaEl.innerHTML = `
            ${templateStatusChip(template)}
            ${templateModeChip(template.mode)}
        `;
    }
    if (statsEl) {
        const runningCount = dashboardOverview?.running?.by_template?.[template.name] || 0;
        const fallbackText = template.fallback_behavior || 'No fallback metadata';
        statsEl.innerHTML = `
            <div class="template-stat-block">
                <span class="template-stat-label">Running now</span>
                <span class="template-stat-value">${runningCount} session(s)</span>
            </div>
            <div class="template-stat-block">
                <span class="template-stat-label">Fallback</span>
                <span class="template-stat-value">${escapeHtml(fallbackText)}</span>
            </div>
            <div class="template-stat-block">
                <span class="template-stat-label">Expected AI calls</span>
                <span class="template-stat-value">${template.mode === 'hybrid' ? '≈ 1 / verified comment' : template.mode === 'ai' ? 'Step-based' : '0'}</span>
            </div>
        `;
    }
}

function buildTemplateField(field, template) {
    const defaultValue = template.default_vars?.[field.key];
    const safeHelp = field.help ? `<small class="field-help">${escapeHtml(field.help)}</small>` : '';
    const id = `field-${field.key}`;
    const full = field.type === 'textarea' ? 'full' : '';

    if (field.type === 'checkbox') {
        return `
            <div class="form-group full ${full}">
                <label class="checkbox-label composer-checkbox">
                    <input type="checkbox" id="${id}" ${defaultValue ? 'checked' : ''} onchange="updateCostEstimate(); updateSubmitButton();">
                    <span>${escapeHtml(field.label || field.key)}</span>
                </label>
                ${safeHelp}
            </div>
        `;
    }

    if (field.type === 'select') {
        const options = Array.isArray(field.options) ? field.options : [];
        return `
            <div class="form-group ${full}">
                <label>${escapeHtml(field.label || field.key)}</label>
                <select id="${id}" onchange="updateCostEstimate(); updateSubmitButton();">
                    ${options.map(option => {
                        const value = typeof option === 'string' ? option : option.value;
                        const label = typeof option === 'string' ? option : option.label;
                        const selected = String(value) === String(defaultValue) ? 'selected' : '';
                        return `<option value="${escapeHtml(String(value))}" ${selected}>${escapeHtml(String(label))}</option>`;
                    }).join('')}
                </select>
                ${safeHelp}
            </div>
        `;
    }

    return `
        <div class="form-group ${full}">
            <label>${escapeHtml(field.label || field.key)}</label>
            <input
                type="${field.type === 'number' ? 'number' : 'text'}"
                id="${id}"
                value="${defaultValue ?? ''}"
                ${field.min !== undefined ? `min="${field.min}"` : ''}
                ${field.max !== undefined ? `max="${field.max}"` : ''}
                ${field.step !== undefined ? `step="${field.step}"` : ''}
                oninput="updateCostEstimate(); updateSubmitButton();"
            >
            ${safeHelp}
        </div>
    `;
}

function renderTemplateFields(template) {
    const container = document.getElementById('dynamicTemplateFields');
    const commandGroup = document.getElementById('composerCommandGroup');
    if (!container || !template) return;

    const fields = Array.isArray(template.ui_fields) ? template.ui_fields : [];
    container.innerHTML = fields.map(field => buildTemplateField(field, template)).join('');

    if (commandGroup) {
        commandGroup.style.display = template.mode === 'ai' ? 'block' : 'none';
    }
}

function renderTemplateDetail(template) {
    const titleEl = document.getElementById('templateDetailTitle');
    const bodyEl = document.getElementById('templateDetail');
    if (!template || !titleEl || !bodyEl) return;

    titleEl.textContent = template.title;
    const defaultVars = Object.entries(template.default_vars || {})
        .map(([key, value]) => `<span><strong>${escapeHtml(key)}</strong>: ${escapeHtml(String(value))}</span>`)
        .join('');
    const capabilities = (template.capabilities || [])
        .map(item => `<span>${escapeHtml(item)}</span>`)
        .join('');
    const limitations = (template.limitations || [])
        .map(item => `<span>${escapeHtml(item)}</span>`)
        .join('');

    bodyEl.innerHTML = `
        <div class="template-detail-copy">${escapeHtml(template.description || '')}</div>
        <div class="template-detail-section">
            <h4>Runtime flow</h4>
            <div class="template-detail-list">${capabilities || '<span>Không có metadata capabilities.</span>'}</div>
        </div>
        <div class="template-detail-section">
            <h4>Defaults</h4>
            <div class="template-detail-list">${defaultVars || '<span>No defaults</span>'}</div>
        </div>
        <div class="template-detail-section">
            <h4>Limitations</h4>
            <div class="template-detail-list">${limitations || '<span>No limitations metadata.</span>'}</div>
        </div>
    `;
}

function selectDashboardTemplate(name) {
    const template = templateMap[name];
    if (!template) return;

    selectedTemplateName = name;
    const selectedEl = document.getElementById('selectedTemplate');
    if (selectedEl) selectedEl.value = name;

    renderTemplateLibrary();
    renderPrimaryTemplateSummary();
    renderTemplateFields(template);
    renderTemplateDetail(template);

    const commandInput = document.getElementById('commandInput');
    if (commandInput && template.mode === 'ai' && !commandInput.value.trim()) {
        commandInput.placeholder = template.description || 'Mô tả yêu cầu cho AI task';
    }

    updateCostEstimate();
    updateSubmitButton();
}

function onTemplateChange() {
    const name = document.getElementById('selectedTemplate')?.value;
    if (name) selectDashboardTemplate(name);
}

// Legacy hook for old cards — map action name directly to template selection.
function selectAction(card) {
    const action = card?.dataset?.action;
    if (action && templateMap[action]) {
        selectDashboardTemplate(action);
    }
}

function updateSubmitButton() {
    const btn = document.getElementById('submitBtn');
    const template = templateMap[selectedTemplateName];
    if (!btn) return;

    if (!template) {
        btn.disabled = true;
        btn.textContent = 'Chọn template để bắt đầu';
        return;
    }

    if (template.mode === 'ai') {
        const cmd = document.getElementById('commandInput')?.value.trim();
        btn.disabled = !cmd;
        btn.textContent = `Run ${template.title}`;
        return;
    }

    btn.disabled = false;
    btn.textContent = `Run ${template.title}`;
}

// ===== SUBMIT TASK =====

function collectTemplateVars(template) {
    const defaults = { ...(template.default_vars || {}) };
    const fields = Array.isArray(template.ui_fields) ? template.ui_fields : [];

    for (const field of fields) {
        const el = document.getElementById(`field-${field.key}`);
        if (!el) continue;

        let value;
        if (field.type === 'checkbox') {
            value = !!el.checked;
        } else if (field.type === 'number') {
            value = Number(el.value);
            if (Number.isNaN(value)) continue;
        } else {
            value = el.value;
        }
        defaults[field.key] = value;
    }

    return defaults;
}

async function submitTask(e) {
    e.preventDefault();

    const template = templateMap[selectedTemplateName];
    if (!template) { toast('Chọn template trước', 'error'); return; }

    const btn = document.getElementById('submitBtn');
    btn.disabled = true;
    btn.textContent = '⏳ Đang gửi...';

    const batchMode = document.getElementById('batchMode').checked;
    const templateVars = collectTemplateVars(template);
    const mode = template.mode === 'ai' ? 'ai' : 'script';

    let payload = {
        command: `${template.title}`,
        template: template.name,
        execution_mode: mode,
        max_steps: 50,
        max_retries: 1,
        template_vars: templateVars,
    };

    if (mode === 'ai') {
        const command = document.getElementById('commandInput').value.trim();
        if (!command) {
            toast('Nhập command cho AI task', 'error');
            btn.disabled = false;
            updateSubmitButton();
            return;
        }

        payload = {
            command,
            template: template.name,
            execution_mode: 'ai',
            max_steps: parseInt(document.getElementById('maxSteps').value, 10) || 20,
            max_retries: parseInt(document.getElementById('maxRetries').value, 10) || 2,
            template_vars: templateVars,
        };
    }

    try {
        let res;
        if (batchMode) {
            const onlineIds = devices.filter(d => d.status !== 'offline').map(d => d.id);
            if (!onlineIds.length) { toast('Không có device online', 'error'); return; }
            res = await fetch(`${API}/api/tasks/batch`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ device_ids: onlineIds, ...payload }),
            });
            const data = await res.json();
            if (res.ok) {
                toast(`🚀 Batch: ${data.submitted} tasks`, 'success');
                data.tasks.forEach(t => subscribeTask(t.id));
            } else {
                toast(`❌ ${data.detail}`, 'error');
            }
        } else {
            const deviceId = document.getElementById('deviceSelect').value;
            if (!deviceId) { toast('Chọn device', 'error'); return; }
            res = await fetch(`${API}/api/tasks`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ device_id: parseInt(deviceId), ...payload }),
            });
            const data = await res.json();
            if (res.ok) {
                toast(`🚀 Task #${data.id} đã gửi`, 'success');
                try { subscribeTask(data.id); } catch (_) { /* WebSocket optional */ }
            } else {
                toast(`❌ ${data.detail}`, 'error');
            }
        }
        refreshRunning();
        refreshStats();
        refreshRecentOutcomes();
    } catch (err) {
        toast('Gửi thất bại', 'error');
    } finally {
        btn.disabled = false;
        updateSubmitButton();
    }
}

function toggleBatchMode() {
    const batch = document.getElementById('batchMode').checked;
    const sel = document.getElementById('deviceSelect');
    sel.disabled = batch;
    if (batch) sel.value = '';
    updateCostEstimate();
}

// ===== COST ESTIMATION =====

const TOKENS_PER_STEP = 680;
const OUTPUT_PER_STEP = 20;
const INPUT_COST_PER_M = 2.50;
const OUTPUT_COST_PER_M = 10.00;

function updateCostEstimate() {
    const template = templateMap[selectedTemplateName];
    const batchMode = document.getElementById('batchMode').checked;
    const onlineDevices = devices.filter(d => d.status !== 'offline').length || 1;
    const multiplier = batchMode ? onlineDevices : 1;

    const modeEl = document.getElementById('estMode');
    const costEl = document.getElementById('estCost');

    if (!modeEl || !costEl) return;

    if (!template) {
        modeEl.textContent = '—';
        costEl.textContent = '—';
        return;
    }

    const vars = collectTemplateVars(template);

    if (template.mode === 'hybrid') {
        const aiEnabled = vars.use_ai !== false;
        const count = Number(vars.count || 0);
        const aiCalls = aiEnabled ? count : 0;
        const cost = (aiCalls * 0.001 * multiplier).toFixed(4);
        modeEl.textContent = `Hybrid${batchMode ? ` ×${onlineDevices}` : ''}${aiEnabled ? '' : ' (AI off)'}`;
        costEl.textContent = aiEnabled ? `~$${cost}` : '$0.00';
        costEl.style.color = aiEnabled ? 'var(--yellow)' : 'var(--green)';
    } else if (template.mode === 'script') {
        modeEl.textContent = `Script${batchMode ? ` ×${onlineDevices}` : ''}`;
        costEl.textContent = '$0.00';
        costEl.style.color = 'var(--green)';
    } else {
        const steps = parseInt(document.getElementById('maxSteps').value) || 20;
        const totalTokensIn = steps * TOKENS_PER_STEP * multiplier;
        const totalTokensOut = steps * OUTPUT_PER_STEP * multiplier;
        const costIn = (totalTokensIn / 1_000_000) * INPUT_COST_PER_M;
        const costOut = (totalTokensOut / 1_000_000) * OUTPUT_COST_PER_M;
        const totalCost = costIn + costOut;

        modeEl.textContent = `AI${batchMode ? ` ×${onlineDevices}` : ''}`;
        costEl.textContent = `$${totalCost.toFixed(4)}`;
        costEl.style.color = 'var(--yellow)';
    }
}

function calcTaskCost(steps) {
    const costIn = (steps * TOKENS_PER_STEP / 1_000_000) * INPUT_COST_PER_M;
    const costOut = (steps * OUTPUT_PER_STEP / 1_000_000) * OUTPUT_COST_PER_M;
    return (costIn + costOut).toFixed(4);
}

// ===== RUNNING TASKS =====

async function refreshRunning() {
    try {
        const [res, liveRes] = await Promise.all([
            fetch(`${API}/api/tasks/running`),
            fetch(`${API}/api/tasks/running/live`).catch(() => null),
        ]);
        const tasks = await res.json();

        // Merge live step data from REST polling (WebSocket fallback)
        if (liveRes && liveRes.ok) {
            const liveData = await liveRes.json();
            for (const [taskId, stepInfo] of Object.entries(liveData)) {
                const tid = parseInt(taskId);
                if (!liveStepData[tid]) {
                    liveStepData[tid] = { steps: [], started_at: Date.now() };
                }
                liveStepData[tid].action = stepInfo.action;
                liveStepData[tid].detail = stepInfo.detail;
                liveStepData[tid].current_step = stepInfo.current_step;
                liveStepData[tid].steps = stepInfo.steps || [];
            }
        }

        const container = document.getElementById('runningTasks');
        document.getElementById('runningCount').textContent = tasks.length;

        if (!tasks.length) {
            container.innerHTML = '<div class="empty-state"><div class="empty-icon">🎯</div><div class="empty-text">No tasks running</div></div>';
            liveStepData = {};
            subscribedTasks.clear();
            return;
        }

        container.innerHTML = tasks.map(t => {
            const device = devices.find(d => d.id === t.device_id);
            const deviceName = device ? device.name : `Device ${t.device_id}`;
            const progress = Math.min((t.steps_taken / t.max_steps) * 100, 100);
            const cmd = t.command.length > 60 ? t.command.substring(0, 60) + '...' : t.command;
            const templateMeta = templateMap[t.template] || null;
            const modeLabel = t.execution_mode === 'script' ? 'SCRIPT' : 'AI';

            // Live step data
            const live = liveStepData[t.id] || {};
            const elapsed = live.started_at
                ? Math.floor((Date.now() - live.started_at) / 1000)
                : 0;
            const elapsedStr = elapsed > 0
                ? `${Math.floor(elapsed / 60)}m${(elapsed % 60).toString().padStart(2, '0')}s`
                : '';

            // Action icon map
            const actionIcons = {
                tap: '👆', key: '⌨️', scroll: '📜', swipe: '👉',
                type: '✏️', wait: '⏳', input: '✏️', error: '❌',
                launch: '🚀', open: '📂', back: '◀️',
                info: 'ℹ️', read_comments: '🗒️', ai_comment: '🧠',
                verify: '✅', comment_retry: '🔁', comment_failed: '⚠️',
                send: '📤',
            };

            const currentAction = live.action || '';
            const currentDetail = live.detail || '';
            const actionIcon = actionIcons[currentAction] || '🔄';

            // Step log (last 3 steps)
            const recentSteps = (live.steps || []).slice(-3).reverse();

            // Auto-subscribe to WebSocket for this task
            if (!subscribedTasks.has(t.id)) {
                subscribedTasks.add(t.id);
                subscribeTask(t.id);
            }

            return `
                <div class="task-card" id="task-${t.id}">
                    <div class="task-card-header">
                        <span class="task-id">${modeLabel} #${t.id}</span>
                        <span class="task-device">📱 ${deviceName}</span>
                    </div>
                    ${templateMeta ? `
                        <div class="task-command" title="${templateMeta.title}">
                            ${templateMeta.title}
                        </div>
                    ` : ''}
                    <div class="task-command" title="${t.command}">${cmd}</div>
                    ${currentAction ? `
                        <div class="task-live-step">
                            <span class="step-action">${actionIcon} ${currentAction}</span>
                            <span class="step-detail">${currentDetail.length > 80 ? currentDetail.substring(0, 80) + '...' : currentDetail}</span>
                        </div>
                    ` : '<div class="task-live-step"><span class="step-action">⏳ Đang khởi tạo...</span></div>'}
                    <div class="task-progress">
                        <div class="progress-bar">
                            <div class="progress-fill ${progress > 75 ? 'progress-warn' : ''}" style="width: ${progress}%"></div>
                        </div>
                        <span class="task-steps">${t.steps_taken}/${t.max_steps}</span>
                        ${elapsedStr ? `<span class="task-elapsed">⏱ ${elapsedStr}</span>` : ''}
                        <button class="btn btn-xs btn-danger" onclick="cancelTask(${t.id})" style="margin-left:6px">✕</button>
                    </div>
                    ${recentSteps.length ? `
                        <div class="task-step-log">
                            ${recentSteps.map(s => `
                                <div class="step-log-item">
                                    <span class="step-num">#${s.step_num}</span>
                                    <span class="step-icon">${actionIcons[s.action] || '•'}</span>
                                    <span class="step-text">${(s.detail || s.action).substring(0, 60)}</span>
                                </div>
                            `).join('')}
                        </div>
                    ` : ''}
                </div>
            `;
        }).join('');
    } catch (e) { /* retry next cycle */ }
}

async function cancelTask(id) {
    try {
        await fetch(`${API}/api/tasks/${id}/cancel`, { method: 'POST' });
        toast(`Task #${id} cancelled`, 'info');
        refreshRunning();
        refreshStats();
    } catch (e) { toast('Cancel failed', 'error'); }
}

// ===== TASK HISTORY =====

let selectedDeviceFilter = 'all';

function buildDeviceTabs() {
    const tabs = document.getElementById('deviceTabs');
    const allBtn = `<button class="device-tab ${selectedDeviceFilter === 'all' ? 'active' : ''}" data-device="all" onclick="selectDeviceTab(this)">Tất cả</button>`;
    const deviceBtns = devices.map(d => {
        const isActive = selectedDeviceFilter == d.id ? 'active' : '';
        const shortName = d.name.length > 15 ? d.name.substring(0, 15) + '…' : d.name;
        return `<button class="device-tab ${isActive}" data-device="${d.id}" onclick="selectDeviceTab(this)">${shortName}</button>`;
    }).join('');
    tabs.innerHTML = allBtn + deviceBtns;
}

function selectDeviceTab(btn) {
    document.querySelectorAll('.device-tab').forEach(t => t.classList.remove('active'));
    btn.classList.add('active');
    selectedDeviceFilter = btn.dataset.device;
    refreshHistory();
}

function formatDuration(startedAt, completedAt) {
    if (!startedAt || !completedAt) return '—';
    const ms = new Date(completedAt) - new Date(startedAt);
    if (ms < 1000) return `${ms}ms`;
    const secs = Math.floor(ms / 1000);
    if (secs < 60) return `${secs}s`;
    const mins = Math.floor(secs / 60);
    const remSecs = secs % 60;
    return `${mins}m${remSecs}s`;
}

function statusIcon(status) {
    const icons = {
        completed: '✅', failed: '❌', cancelled: '🚫',
        running: '⏳', pending: '🔄'
    };
    return icons[status] || '❓';
}

async function refreshHistory() {
    try {
        const filterEl = document.getElementById('historyFilter');
        const filter = filterEl ? filterEl.value : '';
        let url = `${API}/api/tasks?limit=50`;
        if (filter) url += `&status=${filter}`;
        const res = await fetch(url);
        let tasks = await res.json();

        if (selectedDeviceFilter !== 'all') {
            tasks = tasks.filter(t => t.device_id == selectedDeviceFilter);
        }

        buildDeviceTabs();

        // Stats
        const statsEl = document.getElementById('historyStats');
        if (statsEl) {
            const success = tasks.filter(t => t.status === 'completed').length;
            const failed = tasks.filter(t => t.status === 'failed').length;
            const scriptTasks = tasks.filter(t => t.execution_mode === 'script').length;
            const aiTasks = tasks.filter(t => t.execution_mode === 'ai' || t.execution_mode === 'auto').length;
            const totalCost = tasks.reduce((s, t) => {
                if (t.execution_mode === 'script') return s;
                return s + parseFloat(calcTaskCost(t.steps_taken));
            }, 0);

            statsEl.innerHTML = `
                <span class="stat-item">Tổng: <span class="stat-value">${tasks.length}</span></span>
                <span class="stat-item">✅ <span class="stat-value green">${success}</span></span>
                <span class="stat-item">❌ <span class="stat-value red">${failed}</span></span>
                <span class="stat-item">🔧 <span class="stat-value">${scriptTasks}</span></span>
                <span class="stat-item">🧠 <span class="stat-value yellow">${aiTasks}</span></span>
                <span class="stat-item">💰 <span class="stat-value yellow">$${totalCost.toFixed(4)}</span></span>
            `;
        }

        const container = document.getElementById('taskHistory');
        if (!container) return;
        if (!tasks.length) {
            container.innerHTML = '<div class="empty-state"><div class="empty-icon">📋</div><div class="empty-text">Chưa có task nào</div></div>';
            return;
        }

        container.innerHTML = tasks.map(t => {
            const device = devices.find(d => d.id === t.device_id);
            const deviceName = device ? device.name : `Device ${t.device_id}`;
            const duration = formatDuration(t.started_at, t.completed_at);
            const modeClass = t.execution_mode === 'script' ? 'script' : 'ai';
            const modeLabel = t.execution_mode === 'script' ? '🔧 Script' : '🧠 AI';
            const cost = t.execution_mode === 'script' ? '$0' : '$' + calcTaskCost(t.steps_taken);
            const result = t.result || '';
            const cmd = t.command.length > 80 ? t.command.substring(0, 80) + '…' : t.command;
            const time = t.completed_at
                ? new Date(t.completed_at).toLocaleString('vi-VN', {
                    hour: '2-digit', minute: '2-digit',
                    day: '2-digit', month: '2-digit'
                })
                : '—';

            const errorHtml = t.error
                ? `<div class="history-error">⚠️ ${t.error.length > 150 ? t.error.substring(0, 150) + '…' : t.error}</div>`
                : '';

            return `
                <div class="history-card clickable" onclick="openTaskDetail(${t.id})">
                    <div class="history-card-header">
                        <span class="task-id">#${t.id}</span>
                        <span class="history-status status-${t.status}">${statusIcon(t.status)}</span>
                        <span class="mode-badge ${modeClass}">${modeLabel}</span>
                        <span class="history-device">📱 ${deviceName}</span>
                        <span class="history-time">🕐 ${time}</span>
                    </div>
                    <div class="history-card-body">
                        ${result ? `<strong>${result}</strong>` : cmd}
                    </div>
                    <div class="history-card-footer">
                        <span class="tag">⏱ ${duration}</span>
                        <span class="tag">📊 ${t.steps_taken} steps</span>
                        <span class="tag">💰 ${cost}</span>
                        <span class="tag detail-hint">🔍 Chi tiết →</span>
                    </div>
                    ${errorHtml}
                </div>
            `;
        }).join('');
    } catch (e) { /* retry */ }
}

async function refreshRecentOutcomes() {
    const container = document.getElementById('recentOutcomes');
    if (!container) return;

    try {
        const res = await fetch(`${API}/api/tasks?limit=8`);
        const tasks = await res.json();
        const recent = tasks.filter(
            t => t.status === 'completed' || t.status === 'failed' || t.status === 'cancelled'
        ).slice(0, 6);

        if (!recent.length) {
            container.innerHTML = '<div class="empty-state"><div class="empty-icon">LOG</div><div class="empty-text">Chưa có run hoàn tất</div></div>';
            return;
        }

        container.innerHTML = recent.map(t => {
            const template = templateMap[t.template] || null;
            const device = devices.find(d => d.id === t.device_id);
            const summary = t.result || t.command || 'No summary';
            const time = t.completed_at
                ? new Date(t.completed_at).toLocaleString('vi-VN', {
                    hour: '2-digit', minute: '2-digit',
                    day: '2-digit', month: '2-digit'
                })
                : '—';
            return `
                <div class="recent-outcome-card">
                    <div class="recent-outcome-top">
                        <div>
                            <div class="recent-outcome-title">${escapeHtml(template?.title || t.template || `Task #${t.id}`)}</div>
                            <div class="recent-outcome-copy">${escapeHtml(shortenText(summary, 120))}</div>
                        </div>
                        <div class="recent-outcome-meta">
                            <span class="template-chip ${t.status === 'completed' ? 'script' : 'muted'}">${escapeHtml(t.status)}</span>
                            ${template ? templateModeChip(template.mode) : ''}
                        </div>
                    </div>
                    <div class="recent-outcome-foot">
                        <span class="template-mini-stat">${escapeHtml(device?.name || `Device ${t.device_id}`)}</span>
                        <span class="template-mini-stat">${time}</span>
                        <span class="template-mini-stat">${t.execution_mode === 'script' ? '$0' : `$${calcTaskCost(t.steps_taken)}`}</span>
                    </div>
                </div>
            `;
        }).join('');
    } catch (e) {
        container.innerHTML = '<div class="empty-state"><div class="empty-icon">ERR</div><div class="empty-text">Không tải được recent outcomes</div></div>';
    }
}

// ===== TASK DETAIL MODAL =====

async function openTaskDetail(taskId) {
    const modal = document.getElementById('taskDetailModal');
    const titleEl = document.getElementById('modalTitle');
    const bodyEl = document.getElementById('modalBody');
    modal.classList.add('open');
    bodyEl.innerHTML = '<div class="loading">Loading step logs...</div>';

    try {
        // Fetch task info + logs in parallel
        const [taskRes, logsRes] = await Promise.all([
            fetch(`${API}/api/tasks/${taskId}`),
            fetch(`${API}/api/tasks/${taskId}/logs`),
        ]);
        const task = await taskRes.json();
        const logs = await logsRes.json();

        const device = devices.find(d => d.id === task.device_id);
        const deviceName = device ? device.name : `Device ${task.device_id}`;
        const duration = formatDuration(task.started_at, task.completed_at);
        const modeLabel = task.execution_mode === 'script' ? '🔧 Script' : '🧠 AI';

        titleEl.textContent = `Task #${taskId} — ${deviceName}`;

        // Analyze step logs for summary stats
        let videoCount = 0, likeCount = 0, commentCount = 0, followCount = 0;
        let commentTexts = [];
        const actionIcons = {
            tap: '👆', key: '⌨️', scroll: '📜', swipe: '👉', swipe_up: '📜',
            type: '✏️', wait: '⏳', input: '✏️', error: '❌',
            launch: '🚀', open: '📂', back: '◀️', verify: '✅',
            retry: '🔄', double_tap: '❤️', ai_generate: '🧠', ai_fallback: '🤖',
        };

        logs.forEach(log => {
            const d = (log.detail || '').toLowerCase();
            if (log.action === 'swipe_up' || (log.action === 'swipe' && d.includes('next'))) videoCount++;
            if (log.action === 'double_tap' && d.includes('like')) likeCount++;
            if (log.action === 'tap' && d.includes('sent comment')) commentCount++;
            if (log.action === 'tap' && d.includes('follow')) followCount++;
            if (log.action === 'type' && log.detail) {
                const match = log.detail.match(/typed:\s*(.+)/i);
                if (match) commentTexts.push(match[1]);
            }
        });

        // Build summary cards
        let summaryHtml = '<div class="detail-summary">';
        summaryHtml += `<div class="summary-card"><span class="summary-num">${videoCount}</span><span class="summary-label">Videos</span></div>`;
        if (likeCount) summaryHtml += `<div class="summary-card like"><span class="summary-num">${likeCount}</span><span class="summary-label">Likes</span></div>`;
        if (commentCount) summaryHtml += `<div class="summary-card comment"><span class="summary-num">${commentCount}</span><span class="summary-label">Comments</span></div>`;
        if (followCount) summaryHtml += `<div class="summary-card follow"><span class="summary-num">${followCount}</span><span class="summary-label">Follows</span></div>`;
        summaryHtml += `<div class="summary-card"><span class="summary-num">${duration}</span><span class="summary-label">Duration</span></div>`;
        summaryHtml += '</div>';

        // Task info header
        let headerHtml = `
            <div class="detail-header">
                <span class="history-status status-${task.status}">${statusIcon(task.status)} ${task.status}</span>
                <span class="mode-badge ${task.execution_mode === 'script' ? 'script' : 'ai'}">${modeLabel}</span>
                <span>📱 ${deviceName}</span>
            </div>
            <div class="detail-command">${task.command}</div>
            ${task.result ? `<div class="detail-result"><strong>📋 ${task.result}</strong></div>` : ''}
            ${task.error ? `<div class="history-error">⚠️ ${task.error}</div>` : ''}
        `;

        // Comment list
        let commentsHtml = '';
        if (commentTexts.length) {
            commentsHtml = '<div class="detail-comments"><h4>💬 Comments</h4><ul>' +
                commentTexts.map(c => `<li>${c}</li>`).join('') + '</ul></div>';
        }

        // Step timeline
        let timelineHtml = '<div class="detail-timeline"><h4>📊 Step Timeline</h4>';
        if (logs.length) {
            timelineHtml += logs.map(log => {
                const icon = actionIcons[log.action] || '🔄';
                const detail = log.detail || log.action;
                const time = new Date(log.timestamp).toLocaleTimeString('vi-VN', {
                    hour: '2-digit', minute: '2-digit', second: '2-digit'
                });
                // Color based on action
                let cls = '';
                if (log.action === 'error' || log.action === 'retry') cls = 'step-warn';
                else if (log.action === 'verify') cls = 'step-ok';
                else if (log.action === 'type') cls = 'step-type';
                else if (log.action === 'double_tap') cls = 'step-like';

                return `
                    <div class="timeline-step ${cls}">
                        <span class="tl-num">#${log.step}</span>
                        <span class="tl-icon">${icon}</span>
                        <span class="tl-detail">${detail.length > 120 ? detail.substring(0, 120) + '…' : detail}</span>
                        <span class="tl-time">${time}</span>
                    </div>
                `;
            }).join('');
        } else {
            timelineHtml += '<div class="empty-state"><div class="empty-text">Không có step logs (task cũ trước khi bật log)</div></div>';
        }
        timelineHtml += '</div>';

        bodyEl.innerHTML = headerHtml + summaryHtml + commentsHtml + timelineHtml;

    } catch (e) {
        bodyEl.innerHTML = '<div class="empty-state"><div class="empty-text">Lỗi tải dữ liệu</div></div>';
        console.error('openTaskDetail error:', e);
    }
}

function closeTaskDetail(event) {
    if (event && event.target !== event.currentTarget) return;
    document.getElementById('taskDetailModal').classList.remove('open');
}

// ===== QUEUE STATUS =====

async function refreshQueueStatus() {
    try {
        const res = await fetch(`${API}/api/tasks/queue-status`);
        const qs = await res.json();
        document.getElementById('queueCount').textContent = qs.running_tasks;
    } catch (e) { /* ignore */ }
}

// ===== WEBSOCKET =====

function subscribeTask(taskId) {
    if (subscribedTasks.has(taskId)) return;
    subscribedTasks.add(taskId);
    const wsProto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${wsProto}//${location.host}/ws/tasks/${taskId}`);
    ws.onmessage = (e) => {
        const data = JSON.parse(e.data);
        if (data.event === 'started') {
            if (!liveStepData[taskId]) liveStepData[taskId] = { steps: [], started_at: Date.now() };
            liveStepData[taskId].started_at = Date.now();
        } else if (data.event === 'step') {
            if (!liveStepData[taskId]) liveStepData[taskId] = { steps: [], started_at: Date.now() };
            liveStepData[taskId].current_step = data.step_num;
            liveStepData[taskId].action = data.action;
            liveStepData[taskId].detail = data.detail || '';
            liveStepData[taskId].steps.push({
                step_num: data.step_num,
                action: data.action,
                detail: data.detail || '',
            });
            // Update task card in-place for smoother UX
            updateLiveTaskCard(taskId, data);
            if (currentPage === 'videos') {
                renderAssignmentViews();
            }
        } else if (data.event === 'completed') {
            delete liveStepData[taskId];
            subscribedTasks.delete(taskId);
            toast(`✅ Task #${taskId} completed: ${data.reason?.substring(0, 60) || 'Done'}`, 'success');
            refreshRunning();
            refreshHistory();
            refreshDevices();
            refreshStats();
            refreshVideos();
            refreshAssignments();
        } else if (data.event === 'failed') {
            delete liveStepData[taskId];
            subscribedTasks.delete(taskId);
            toast(`❌ Task #${taskId} failed: ${data.error?.substring(0, 60) || 'Error'}`, 'error');
            refreshRunning();
            refreshHistory();
            refreshDevices();
            refreshStats();
            refreshVideos();
            refreshAssignments();
        } else if (data.event === 'retry') {
            toast(`🔄 Task #${taskId} retry #${data.attempt} in ${data.delay}s`, 'info');
        } else if (data.event === 'cancelled') {
            delete liveStepData[taskId];
            subscribedTasks.delete(taskId);
            toast(`⛔ Task #${taskId} cancelled`, 'info');
            refreshRunning();
            refreshVideos();
            refreshAssignments();
        }
    };
    ws.onerror = () => { subscribedTasks.delete(taskId); };
    ws.onclose = () => { subscribedTasks.delete(taskId); };
}

function updateLiveTaskCard(taskId, stepData) {
    const card = document.getElementById(`task-${taskId}`);
    if (!card) return;

    const actionIcons = {
        tap: '👆', key: '⌨️', scroll: '📜', swipe: '👉',
        type: '✏️', wait: '⏳', input: '✏️', error: '❌',
        launch: '🚀', open: '📂', back: '◀️',
    };
    const icon = actionIcons[stepData.action] || '🔄';
    const detail = (stepData.detail || '').substring(0, 80);

    // Update current step display
    const liveEl = card.querySelector('.task-live-step');
    if (liveEl) {
        liveEl.innerHTML = `
            <span class="step-action">${icon} ${stepData.action}</span>
            <span class="step-detail">${detail}</span>
        `;
    }

    // Update step counter
    const stepsEl = card.querySelector('.task-steps');
    if (stepsEl) {
        const parts = stepsEl.textContent.split('/');
        stepsEl.textContent = `${stepData.step_num}/${parts[1] || '?'}`;
    }

    // Update progress bar
    const fillEl = card.querySelector('.progress-fill');
    if (fillEl) {
        const maxSteps = parseInt((stepsEl?.textContent || '0/50').split('/')[1]) || 50;
        const pct = Math.min((stepData.step_num / maxSteps) * 100, 100);
        fillEl.style.width = pct + '%';
        if (pct > 75) fillEl.classList.add('progress-warn');
    }

    // Update step log
    const live = liveStepData[taskId];
    if (live && live.steps.length > 0) {
        const recentSteps = live.steps.slice(-3).reverse();
        let logEl = card.querySelector('.task-step-log');
        if (!logEl) {
            logEl = document.createElement('div');
            logEl.className = 'task-step-log';
            card.appendChild(logEl);
        }
        logEl.innerHTML = recentSteps.map(s => `
            <div class="step-log-item">
                <span class="step-num">#${s.step_num}</span>
                <span class="step-icon">${actionIcons[s.action] || '•'}</span>
                <span class="step-text">${(s.detail || s.action).substring(0, 60)}</span>
            </div>
        `).join('');
    }
}

// ===== TOASTS =====

function toast(message, type = 'info') {
    const container = document.getElementById('toastContainer');
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    el.textContent = message;
    container.appendChild(el);
    setTimeout(() => {
        el.style.opacity = '0';
        el.style.transform = 'translateX(40px)';
        el.style.transition = '0.3s ease';
        setTimeout(() => el.remove(), 300);
    }, 4000);
}

// ===== SCHEDULER =====

const DAYS_LABELS = {
    daily: 'Hàng ngày',
    'mon,tue,wed,thu,fri': 'T2-T6',
    'sat,sun': 'Cuối tuần',
    'mon,wed,fri': 'T2,T4,T6',
    'tue,thu,sat': 'T3,T5,T7',
};

const ACTION_LABELS = {
    tiktok_browse: '🎵 TikTok',
    youtube_watch: '▶️ YouTube',
    facebook_scroll: '📘 Facebook',
    instagram_scroll: '📷 Instagram',
    custom: '🧠 Custom AI',
};

function populateSchedDevices() {
    const sel = document.getElementById('schedDevice');
    if (!sel) return;
    sel.innerHTML = '<option value="">Chọn device...</option>' +
        devices.map(d => `<option value="${d.id}">${d.name}</option>`).join('');
}

async function loadSchedules() {
    populateSchedDevices();
    try {
        const res = await fetch(`${API}/api/schedules`);
        const schedules = await res.json();
        const container = document.getElementById('scheduleList');
        document.getElementById('scheduleCount').textContent = schedules.length;

        if (!schedules.length) {
            container.innerHTML = '<div class="empty-state"><div class="empty-icon">⏰</div><div class="empty-text">Chưa có lịch hẹn giờ</div></div>';
            return;
        }

        // Group by device
        const grouped = {};
        schedules.forEach(s => {
            const key = s.device_id;
            if (!grouped[key]) grouped[key] = [];
            grouped[key].push(s);
        });

        let html = '';
        for (const [deviceId, items] of Object.entries(grouped)) {
            const device = devices.find(d => d.id == deviceId);
            const deviceName = device ? device.name : `Device ${deviceId}`;
            html += `<div class="sched-group-header">📱 ${deviceName}</div>`;
            html += items.map(s => {
                const actionLabel = ACTION_LABELS[s.action] || s.action;
                const daysLabel = DAYS_LABELS[s.days_of_week] || s.days_of_week;
                const nextRun = s.next_run
                    ? new Date(s.next_run).toLocaleString('vi-VN', {
                        hour: '2-digit', minute: '2-digit',
                        day: '2-digit', month: '2-digit'
                    })
                    : '—';
                const lastRun = s.last_run
                    ? new Date(s.last_run).toLocaleString('vi-VN', {
                        hour: '2-digit', minute: '2-digit',
                        day: '2-digit', month: '2-digit'
                    })
                    : 'Chưa chạy';
                const enabledClass = s.enabled ? 'enabled' : 'disabled';

                return `
                    <div class="schedule-card ${enabledClass}">
                        <div class="sched-card-header">
                            <span class="sched-name">${s.name}</span>
                            <div class="sched-actions">
                                <button class="btn-icon" onclick="toggleSchedule(${s.id})" title="${s.enabled ? 'Tắt' : 'Bật'}">
                                    ${s.enabled ? '⏸️' : '▶️'}
                                </button>
                                <button class="btn-icon btn-danger" onclick="deleteSchedule(${s.id})" title="Xóa">
                                    🗑️
                                </button>
                            </div>
                        </div>
                        <div class="sched-card-body">
                            <span class="sched-tag">${actionLabel}</span>
                            <span class="sched-tag">🕐 ${s.start_time}-${s.end_time}</span>
                            <span class="sched-tag">📅 ${daysLabel}</span>
                            <span class="sched-tag">🔁 ×${s.repeat_count}</span>
                            <span class="sched-tag">⏳ ${s.random_delay_min}-${s.random_delay_max}m</span>
                        </div>
                        <div class="sched-card-footer">
                            <span>⏭ Next: ${nextRun}</span>
                            <span>📌 Last: ${lastRun}</span>
                        </div>
                    </div>
                `;
            }).join('');
        }
        container.innerHTML = html;
    } catch (e) {
        console.error('loadSchedules error:', e);
    }
}

async function createSchedule(event) {
    event.preventDefault();
    const action = document.getElementById('schedAction').value;
    const isAi = action === 'custom';
    const delayVal = document.getElementById('schedDelay').value.split('-');

    const payload = {
        device_id: parseInt(document.getElementById('schedDevice').value),
        name: document.getElementById('schedName').value,
        action: action,
        execution_mode: isAi ? 'ai' : 'script',
        command: isAi ? document.getElementById('schedCommand').value : '',
        start_time: document.getElementById('schedStart').value,
        end_time: document.getElementById('schedEnd').value,
        days_of_week: document.getElementById('schedDays').value,
        repeat_count: parseInt(document.getElementById('schedRepeat').value),
        random_delay_min: parseInt(delayVal[0]),
        random_delay_max: parseInt(delayVal[1]),
        script_count: parseInt(document.getElementById('schedScriptCount').value),
        script_view_time: document.getElementById('schedViewTime').value,
        script_like_chance: parseFloat(document.getElementById('schedLikeChance').value),
    };

    try {
        const res = await fetch(`${API}/api/schedules`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        if (!res.ok) throw new Error(await res.text());
        const sched = await res.json();
        toast(`⏰ Đã tạo lịch "${sched.name}"`, 'success');
        document.getElementById('scheduleForm').reset();
        loadSchedules();
    } catch (e) {
        toast(`Lỗi: ${e.message}`, 'error');
    }
}

async function toggleSchedule(id) {
    try {
        const res = await fetch(`${API}/api/schedules/${id}/toggle`, { method: 'POST' });
        const sched = await res.json();
        toast(`⏰ ${sched.name}: ${sched.enabled ? 'Đã bật' : 'Đã tắt'}`, 'info');
        loadSchedules();
    } catch (e) {
        toast('Toggle failed', 'error');
    }
}

async function deleteSchedule(id) {
    if (!confirm('Xóa lịch hẹn giờ này?')) return;
    try {
        await fetch(`${API}/api/schedules/${id}`, { method: 'DELETE' });
        toast('🗑️ Đã xóa lịch', 'info');
        loadSchedules();
    } catch (e) {
        toast('Delete failed', 'error');
    }
}

function onSchedActionChange() {
    const action = document.getElementById('schedAction').value;
    const aiCmd = document.getElementById('schedAiCmd');
    const scriptConfig = document.getElementById('schedScriptConfig');
    if (action === 'custom') {
        aiCmd.style.display = 'block';
        if (scriptConfig) scriptConfig.style.display = 'none';
    } else {
        aiCmd.style.display = 'none';
        if (scriptConfig) scriptConfig.style.display = '';
    }
}

// Token management removed — devices now use login-based registration via /api/device/register

// ===== VIDEO MANAGEMENT =====

let selectedVideoFile = null;
let videoList = [];
let deviceAccounts = [];
let assignmentList = [];
let selectedAssignmentIds = new Set();
let focusedVideoId = null;
let assignmentModalState = null;
let metricsSummaryCache = null;

// --- Metrics Helpers ---

function formatMetricNumber(num) {
    if (num === null || num === undefined) return '—';
    if (num >= 1_000_000) return (num / 1_000_000).toFixed(1) + 'M';
    if (num >= 1_000) return (num / 1_000).toFixed(1) + 'K';
    return String(num);
}

function renderMetricsBadge(status) {
    const labels = {
        pending: '⏳ Pending',
        syncing: '🔄 Syncing',
        synced: '✅ Synced',
        needs_review: '⚠️ Review',
        sync_failed: '❌ Failed',
        disabled: '🚫 Disabled',
    };
    return `<span class="metrics-status-badge ${status || 'pending'}">${labels[status] || status || 'pending'}</span>`;
}

function renderMetricsInline(item) {
    if (!item.has_metrics) return '';
    return `<span class="metrics-inline">
        ${item.latest_views !== null ? `<span class="metric-chip" title="Views">👁 ${formatMetricNumber(item.latest_views)}</span>` : ''}
        ${item.latest_likes !== null ? `<span class="metric-chip" title="Likes">❤ ${formatMetricNumber(item.latest_likes)}</span>` : ''}
        ${item.latest_comments !== null ? `<span class="metric-chip" title="Comments">💬 ${formatMetricNumber(item.latest_comments)}</span>` : ''}
        ${item.latest_shares !== null ? `<span class="metric-chip" title="Shares">↗ ${formatMetricNumber(item.latest_shares)}</span>` : ''}
    </span>`;
}

async function refreshMetricsSummary() {
    try {
        const res = await fetch(`${API}/api/videos/metrics-summary`);
        metricsSummaryCache = await res.json();
    } catch (_) {
        metricsSummaryCache = null;
    }
}

// --- Upload ---

function onDragOver(e) {
    e.preventDefault();
    document.getElementById('uploadZone').classList.add('drag-over');
}

function onDragLeave(e) {
    document.getElementById('uploadZone').classList.remove('drag-over');
}

function onDrop(e) {
    e.preventDefault();
    document.getElementById('uploadZone').classList.remove('drag-over');
    const file = e.dataTransfer.files[0];
    if (file) showFilePreview(file);
}

function onFileSelect(e) {
    const file = e.target.files[0];
    if (file) showFilePreview(file);
}

function showFilePreview(file) {
    selectedVideoFile = file;
    const info = document.getElementById('uploadFileInfo');
    const sizeMB = (file.size / 1024 / 1024).toFixed(1);
    info.innerHTML = `🎬 <strong>${file.name}</strong> · ${sizeMB} MB`;
    document.getElementById('uploadForm').style.display = 'block';
    document.getElementById('videoTitle').value = file.name.replace(/\.[^/.]+$/, '');
}

function cancelUpload() {
    selectedVideoFile = null;
    document.getElementById('uploadForm').style.display = 'none';
    document.getElementById('videoFileInput').value = '';
}

async function uploadVideo() {
    if (!selectedVideoFile) { toast('Chọn file trước', 'error'); return; }

    const title = document.getElementById('videoTitle').value.trim();
    const tags  = document.getElementById('videoTags').value.trim();

    const formData = new FormData();
    formData.append('file', selectedVideoFile);
    if (title) formData.append('title', title);
    if (tags)  formData.append('tags', tags);

    const progress = document.getElementById('uploadProgress');
    const bar = document.getElementById('uploadProgressBar');
    progress.style.display = 'block';
    bar.style.width = '20%';

    try {
        const res = await fetch(`${API}/api/videos/upload`, {
            method: 'POST',
            body: formData,
        });
        bar.style.width = '100%';
        const data = await res.json();

        if (res.status === 200 && data._duplicate) {
            toast('⚠️ Video này đã tồn tại, dùng bản cũ', 'info');
        } else if (res.status === 201) {
            toast(`✅ Upload thành công: ${data.title || data.filename}`, 'success');
        } else {
            toast(`❌ ${data.detail || 'Upload thất bại'}`, 'error');
        }
        cancelUpload();
        refreshVideos();
        refreshAssignments();
        // Update badge count
        const cnt = document.getElementById('videoCount');
        if (cnt) cnt.textContent = parseInt(cnt.textContent || '0') + 1;
    } catch (e) {
        toast(`Upload lỗi: ${e.message}`, 'error');
    } finally {
        progress.style.display = 'none';
        bar.style.width = '0%';
    }
}

function escapeHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function escapeJsString(value) {
    return String(value ?? '')
        .replace(/\\/g, '\\\\')
        .replace(/'/g, "\\'");
}

function formatDateTime(value, fallback = '—') {
    if (!value) return fallback;
    try {
        return new Date(value).toLocaleString('vi-VN', {
            hour: '2-digit',
            minute: '2-digit',
            day: '2-digit',
            month: '2-digit',
        });
    } catch (_) {
        return fallback;
    }
}

function platformIcon(platform) {
    return { tiktok: '🎵', youtube: '▶️', instagram: '📷', facebook: '📘' }[platform] || '📦';
}

function normalizePushStatus(status) {
    return status === 'failed' ? 'push_failed' : (status || 'pending');
}

function renderPushBadge(status) {
    const normalized = normalizePushStatus(status);
    const labels = {
        pending: '⏳ Chưa push',
        pushed: '📱 Đã push',
        uploaded: '✅ Đã upload',
        push_failed: '❌ Push lỗi',
    };
    return `<span class="push-status-badge ${normalized}">${labels[normalized] || normalized}</span>`;
}

function renderUploadBadge(status) {
    const labels = {
        pending: '⏳ Chờ chạy',
        queued: '🟡 Đã queue',
        running: '🟦 Đang chạy',
        uploaded: '✅ Thành công',
        upload_failed: '❌ Upload lỗi',
        verify_failed: '⚠️ Verify lỗi',
    };
    return `<span class="upload-status-badge ${status || 'pending'}">${labels[status] || status || 'pending'}</span>`;
}

function shortenText(value, max = 80) {
    const text = String(value || '');
    return text.length > max ? `${text.substring(0, max)}…` : text;
}

function getVideoById(videoId) {
    return videoList.find(video => video.id === videoId);
}

function getAssignmentById(assignmentId) {
    return assignmentList.find(item => item.id === assignmentId)
        || videoList.flatMap(video => video.assignments || []).find(item => item.id === assignmentId);
}

function getPlatformSummary(video, platform) {
    return (video?.platform_summary || {})[platform] || {
        eligible_targets: 0,
        assigned_targets: 0,
        uploaded_targets: 0,
        running_targets: 0,
        failed_targets: 0,
        missing_targets: 0,
        missing_target_devices: [],
        coverage_complete: false,
    };
}

function getPlatformLabel(platform) {
    const labels = {
        tiktok: 'TikTok',
        youtube: 'YouTube',
        instagram: 'Instagram',
        facebook: 'Facebook',
    };
    return labels[platform] || platform || 'Platform';
}

function getActiveAssignmentPlatform(video = null) {
    const selected = document.getElementById('assignmentPlatformFilter')?.value || '';
    if (selected) return selected;
    if (video?.assignments?.length) return video.assignments[0].platform || 'tiktok';
    return 'tiktok';
}

function getAssignmentTargets(platform) {
    const statusRank = { online: 0, busy: 1, offline: 2 };
    const accountMap = new Map(
        deviceAccounts
            .filter(account => !platform || account.platform === platform)
            .map(account => [account.device_id, account])
    );

    return [...devices]
        .map(device => ({
            device_id: device.id,
            device_name: device.name,
            device_status: device.status,
            device_model: device.device_model,
            platform: platform || accountMap.get(device.id)?.platform || '',
            account_name: accountMap.get(device.id)?.account_name || null,
            account_notes: accountMap.get(device.id)?.notes || null,
            has_account: accountMap.has(device.id),
        }))
        .sort((a, b) => {
            const accountScore = Number(b.has_account) - Number(a.has_account);
            if (accountScore) return accountScore;
            const statusScore = (statusRank[a.device_status] ?? 99) - (statusRank[b.device_status] ?? 99);
            if (statusScore) return statusScore;
            return String(a.device_name || '').localeCompare(String(b.device_name || ''));
        });
}

function renderArtifactActionButton(item, compact = false) {
    if (!item?.artifact_manifest_url) return '';
    const label = compact ? '🗂️' : '🗂️ Artifact';
    return `<a class="btn btn-xs btn-ghost" href="${item.artifact_manifest_url}" target="_blank" rel="noreferrer">${label}</a>`;
}

function renderPrimaryUploadAction(item, compact = false) {
    if (!item) return '';
    if (item.can_push) {
        return `<button class="btn btn-xs btn-ghost" onclick="pushAssignment(${item.id}, this)">📤 Push</button>`;
    }
    if (item.can_rerun || item.rerun_requires_confirm) {
        return `<button class="btn btn-xs btn-primary" onclick="retryFailedAssignment(${item.id}, this)">${compact ? '🔁' : '🔁 Retry'}</button>`;
    }
    if (item.can_run_upload) {
        return `<button class="btn btn-xs btn-primary" onclick="runUploadAssignment(${item.id}, this)">🚀 ${compact ? '' : 'Run'}</button>`;
    }
    return '';
}

function renderLiveTaskState(item) {
    if (!item?.task_id) return '';
    const live = liveStepData[item.task_id];
    if (!live) return '';
    const action = live.action || 'running';
    const detail = shortenText(live.detail || action, 72);
    const stepNum = live.current_step ? `#${live.current_step}` : 'live';
    return `
        <div class="assignment-live-state">
            <span class="assignment-live-step">${stepNum}</span>
            <span class="assignment-live-detail">${escapeHtml(detail)}</span>
        </div>
    `;
}

function getVisibleAssignments() {
    const search = (document.getElementById('assignmentSearch')?.value || '').trim().toLowerCase();
    const deviceId = parseInt(document.getElementById('assignmentDeviceFilter')?.value || '', 10);
    const metricsFilter = document.getElementById('assignmentMetricsFilter')?.value || '';
    return assignmentList.filter(item => {
        if (focusedVideoId && item.video_id !== focusedVideoId) return false;
        if (deviceId && item.device_id !== deviceId) return false;
        if (metricsFilter && (item.metrics_status || 'pending') !== metricsFilter) return false;
        if (!search) return true;
        const haystack = [
            item.video_title,
            item.video_filename,
            item.device_name,
            item.account_name,
            item.device_path,
            item.latest_error,
        ].join(' ').toLowerCase();
        return haystack.includes(search);
    });
}

function syncSelectedAssignments() {
    const visibleIds = new Set(getVisibleAssignments().map(item => item.id));
    selectedAssignmentIds = new Set([...selectedAssignmentIds].filter(id => visibleIds.has(id)));
}

function renderVideoOpsSummary() {
    const container = document.getElementById('videoOpsSummary');
    if (!container) return;

    const activePlatform = getActiveAssignmentPlatform();
    const assignments = assignmentList;
    const platformAssignments = assignments.filter(item => item.platform === activePlatform);
    const readyCount = platformAssignments.filter(item => item.ready_to_upload).length;
    const runningCount = platformAssignments.filter(item => ['queued', 'running'].includes(item.upload_status)).length;
    const uploadedCount = platformAssignments.filter(item => item.upload_status === 'uploaded').length;
    const issueCount = platformAssignments.filter(item => item.has_errors).length;
    const focusedVideo = focusedVideoId ? getVideoById(focusedVideoId) : null;
    const eligibleTargets = videoList.reduce((sum, video) => sum + getPlatformSummary(video, activePlatform).eligible_targets, 0);

    // Metrics summary from cached API response
    const ms = metricsSummaryCache || {};
    const metricsCards = activePlatform === 'tiktok' ? `
        <div class="video-stat-card metrics-card">
            <span class="video-stat-label">📊 Tracked</span>
            <span class="video-stat-value">${ms.total_tracked || 0}</span>
            <span class="video-stat-sub">${ms.synced_count || 0} synced</span>
        </div>
        <div class="video-stat-card metrics-card accent">
            <span class="video-stat-label">👁 Total Views</span>
            <span class="video-stat-value">${formatMetricNumber(ms.total_views || 0)}</span>
            <span class="video-stat-sub">❤ ${formatMetricNumber(ms.total_likes || 0)} · 💬 ${formatMetricNumber(ms.total_comments || 0)}</span>
        </div>
        <div class="video-stat-card metrics-card">
            <span class="video-stat-label">⏳ Pending Sync</span>
            <span class="video-stat-value">${ms.pending_count || 0}</span>
            <span class="video-stat-sub">Chưa sync metrics</span>
        </div>
        <div class="video-stat-card metrics-card warn">
            <span class="video-stat-label">⚠️ Needs Review</span>
            <span class="video-stat-value">${ms.review_count || 0}</span>
            <span class="video-stat-sub">Sync lỗi, cần kiểm tra</span>
        </div>
    ` : '';

    container.innerHTML = `
        <div class="video-stat-card">
            <span class="video-stat-label">Videos</span>
            <span class="video-stat-value">${videoList.length}</span>
            <span class="video-stat-sub">${focusedVideo ? `Đang focus: ${escapeHtml(shortenText(focusedVideo.title || focusedVideo.filename, 26))}` : 'Kho video hiện có'}</span>
        </div>
        <div class="video-stat-card accent">
            <span class="video-stat-label">${escapeHtml(getPlatformLabel(activePlatform))} Targets</span>
            <span class="video-stat-value">${platformAssignments.length}/${eligibleTargets || 0}</span>
            <span class="video-stat-sub">${readyCount} sẵn sàng upload</span>
        </div>
        <div class="video-stat-card success">
            <span class="video-stat-label">Uploaded</span>
            <span class="video-stat-value">${uploadedCount}</span>
            <span class="video-stat-sub">${runningCount} đang chạy</span>
        </div>
        <div class="video-stat-card warn">
            <span class="video-stat-label">Needs Review</span>
            <span class="video-stat-value">${issueCount}</span>
            <span class="video-stat-sub">Lỗi push/upload gần nhất</span>
        </div>
        ${metricsCards}
    `;
}

function renderDistributionFocus() {
    const container = document.getElementById('videoDistributionFocus');
    if (!container) return;

    if (!focusedVideoId) {
        container.innerHTML = `
            <div class="distribution-focus distribution-focus-empty">
                <div>
                    <strong>Distribution Board</strong>
                    <div>Chọn một video để gom toàn bộ assignment TikTok, metadata và hành động vào cùng một chỗ.</div>
                </div>
            </div>
        `;
        return;
    }

    const video = getVideoById(focusedVideoId);
    if (!video) {
        focusedVideoId = null;
        renderDistributionFocus();
        return;
    }

    const activePlatform = getActiveAssignmentPlatform(video);
    const platformLabel = getPlatformLabel(activePlatform);
    const assignments = (video.assignments || []).filter(item => item.platform === activePlatform);
    const primaryAssignment = assignments[0] || null;
    const summary = getPlatformSummary(video, activePlatform);
    const metadataCount = [video.title, video.tags, video.description].filter(Boolean).length;
    const coverageLine = `${summary.assigned_targets}/${summary.eligible_targets} targets assigned · ${summary.uploaded_targets} uploaded · ${summary.failed_targets} failed · ${summary.missing_targets} missing`;
    const targetCards = assignments.map(item => `
        <div class="distribution-target-card assigned">
            <div class="distribution-target-top">
                <div class="distribution-target-name">${escapeHtml(item.device_name || `#${item.device_id}`)}</div>
                <div class="distribution-target-account">${escapeHtml(item.account_name || 'No account')}</div>
            </div>
            <div class="distribution-target-badges">
                ${renderPushBadge(item.push_status)}
                ${renderUploadBadge(item.upload_status)}
                ${item.upload_status === 'uploaded' ? renderMetricsBadge(item.metrics_status) : ''}
            </div>
            ${item.has_metrics ? `<div class="distribution-target-metrics">${renderMetricsInline(item)}</div>` : ''}
            <div class="distribution-target-actions">
                ${renderPrimaryUploadAction(item) || ''}
                ${renderArtifactActionButton(item, true) || ''}
                <button class="btn btn-xs btn-ghost" onclick="openEditAssignmentModal(${item.id})">✏️ Edit</button>
                <button class="btn btn-xs btn-danger" onclick="deleteAssignment(${item.id})">🗑️</button>
                <button class="btn btn-xs btn-ghost" onclick="openAssignmentDetail(${item.id})">Detail</button>
                ${item.upload_status === 'uploaded' ? `<button class="btn btn-xs btn-accent" onclick="openManualMetricsModal(${item.id})">📝</button>` : ''}
            </div>
        </div>
    `).join('');
    const missingCards = (summary.missing_target_devices || []).map(target => `
        <div class="distribution-target-card missing">
            <div class="distribution-target-top">
                <div class="distribution-target-name">${escapeHtml(target.device_name || `#${target.device_id}`)}</div>
                <div class="distribution-target-account">${escapeHtml(target.account_name || 'No account')}</div>
            </div>
            <div class="distribution-target-missing">Chưa có assignment ${escapeHtml(platformLabel)} cho target này</div>
            <div class="distribution-target-actions">
                <button class="btn btn-xs btn-primary" onclick="quickAssignVideoTarget(${video.id}, ${target.device_id}, '${activePlatform}')">📌 Assign</button>
            </div>
        </div>
    `).join('');

    container.innerHTML = `
        <div class="distribution-focus">
            <div class="distribution-focus-main">
                <div class="distribution-focus-title">
                    <span>${platformIcon(activePlatform)} ${escapeHtml(platformLabel)} Focus</span>
                    <button class="btn btn-xs btn-ghost" onclick="clearVideoFocus()">Bỏ focus</button>
                </div>
                <div class="distribution-focus-name">${escapeHtml(video.title || video.filename)}</div>
                <div class="distribution-focus-meta">
                    <span>${metadataCount}/3 metadata fields</span>
                    <span>${assignments.length ? `${assignments.length} assignment` : `Chưa assign ${platformLabel}`}</span>
                    <span>${video.thumbnail ? 'Có thumbnail' : 'Chưa có thumbnail'}</span>
                </div>
                <div class="distribution-focus-coverage">${escapeHtml(coverageLine)}</div>
                <div class="distribution-focus-copy">${escapeHtml(shortenText(video.description || 'Chưa có description cho video này.', 160))}</div>
            </div>
            <div class="distribution-focus-actions">
                <button class="btn btn-sm btn-accent" onclick="openAiSuggestModal(${video.id}, '${escapeJsString(video.title || video.filename)}')">🤖 AI Metadata</button>
                ${primaryAssignment
                    ? `
                        ${renderPrimaryUploadAction(primaryAssignment) || ''}
                        ${renderArtifactActionButton(primaryAssignment) || ''}
                        <button class="btn btn-sm btn-ghost" onclick="openEditAssignmentModal(${primaryAssignment.id})">✏️ Edit</button>
                        <button class="btn btn-sm btn-ghost" onclick="openAssignmentDetail(${primaryAssignment.id})">🔍 Detail</button>
                    `
                    : `<button class="btn btn-sm btn-primary" onclick="openAssignModal(${video.id}, '${escapeJsString(video.title || video.filename)}', '${activePlatform}')">📌 Assign ${escapeHtml(platformLabel)}</button>`
                }
            </div>
        </div>
        <div class="distribution-target-grid">
            ${targetCards || ''}
            ${missingCards || ''}
            ${!targetCards && !missingCards ? `<div class="distribution-target-empty">${escapeHtml(platformLabel)} chưa có target nào khả dụng. Hãy tạo Device Account trước.</div>` : ''}
        </div>
    `;
}

async function refreshVideos() {
    const platform = document.getElementById('videoPlatformFilter')?.value || '';
    const container = document.getElementById('videoGrid');
    if (container) {
        container.innerHTML = '<div class="assignment-skeleton-grid"><div class="assignment-skeleton-card"></div><div class="assignment-skeleton-card"></div><div class="assignment-skeleton-card"></div></div>';
    }
    try {
        const url = platform
            ? `${API}/api/videos?platform=${platform}`
            : `${API}/api/videos`;
        const [videosRes] = await Promise.all([
            fetch(url),
            refreshMetricsSummary(),
        ]);
        videoList = await videosRes.json();
        renderVideoGrid(videoList);
        renderVideoOpsSummary();
        renderDistributionFocus();

        const cnt = document.getElementById('videoCount');
        if (cnt) cnt.textContent = videoList.length;
    } catch (e) { /* retry */ }
}

function renderVideoGrid(videos) {
    const container = document.getElementById('videoGrid');
    if (!container) return;

    if (!videos.length) {
        container.innerHTML = '<div class="empty-state"><div class="empty-icon">🎬</div><div class="empty-text">Chưa có video nào<br><small style="color:var(--text-muted)">Upload video ở panel bên trên</small></div></div>';
        return;
    }

    container.innerHTML = videos.map(video => {
        const sizeMB = (video.file_size / 1024 / 1024).toFixed(1);
        const assignments = video.assignments || [];
        const activePlatform = getActiveAssignmentPlatform(video);
        const platformAssignment = assignments.find(item => item.platform === activePlatform);
        const platformSummary = getPlatformSummary(video, activePlatform);
        const platformLabel = getPlatformLabel(activePlatform);
        const hasAi = video.ai_title || video.ai_tags || video.ai_description;
        const aiIndicator = hasAi ? '<span class="ai-badge" title="AI đã gợi ý">✨</span>' : '';
        const selectedClass = focusedVideoId === video.id ? 'selected' : '';
        const platformBadges = Object.entries(video.platform_summary || {}).length
            ? Object.entries(video.platform_summary || {}).map(([platform, summary]) => `
                <span class="platform-badge ${summary.failed_targets ? 'push_failed' : summary.uploaded_targets ? 'uploaded' : summary.assigned_targets ? 'pushed' : 'pending'}" title="${escapeHtml(platform)}">
                    ${platformIcon(platform)} ${platform} ${summary.assigned_targets}/${summary.eligible_targets}
                </span>
            `).join('')
            : '<span class="video-platform-empty">Chưa assign platform</span>';

        const platformStatus = platformSummary.assigned_targets
            ? `<span class="platform-summary-line">${escapeHtml(platformLabel)} ${platformSummary.uploaded_targets}/${platformSummary.assigned_targets} uploaded · ${platformSummary.missing_targets} missing</span>`
            : `<span class="video-platform-empty">${escapeHtml(platformLabel)} chưa assign</span>`;

        return `
            <div class="video-card ${selectedClass}">
                <div class="video-thumb" ${video.thumbnail ? `style="background:url('${API}/api/videos/${video.id}/thumbnail');background-size:cover;background-position:center"` : ''}>
                    ${video.thumbnail ? '' : '🎬'}
                    <span class="video-size-badge">${sizeMB}MB</span>
                    ${aiIndicator}
                </div>
                <div class="video-info">
                    <div class="video-title-row">
                        <div class="video-title" title="${escapeHtml(video.title || video.filename)}">${escapeHtml(video.title || video.filename)}</div>
                        <span class="video-assignment-count">${assignments.length}</span>
                    </div>
                    <div class="video-meta">${escapeHtml(shortenText(video.tags || video.filename, 44))}</div>
                    <div class="video-platforms">${platformBadges}</div>
                    <div class="video-tiktok-state">${platformStatus}</div>
                </div>
                <div class="video-actions">
                    <button class="btn btn-xs btn-ghost" onclick="focusVideoAssignments(${video.id})">🧭 Focus</button>
                    <button class="btn btn-xs btn-accent" onclick="openAiSuggestModal(${video.id}, '${escapeJsString(video.title || video.filename)}')">🤖 AI</button>
                    ${platformAssignment
                        ? `${renderPrimaryUploadAction(platformAssignment, true) || `<button class="btn btn-xs btn-primary" onclick="openAssignmentDetail(${platformAssignment.id})">🔍 Detail</button>`}`
                        : `<button class="btn btn-xs btn-primary" onclick="openAssignModal(${video.id}, '${escapeJsString(video.title || video.filename)}', '${activePlatform}')">📌 ${escapeHtml(platformLabel)}</button>`
                    }
                    <button class="btn btn-xs btn-ghost" onclick="deleteVideo(${video.id}, this)">🗑️</button>
                </div>
            </div>
        `;
    }).join('');
}

async function autoAssignTikTok() {
    const candidateIds = videoList
        .filter(video => getPlatformSummary(video, 'tiktok').missing_targets > 0)
        .map(video => video.id);

    if (!candidateIds.length) {
        toast('Không có video TikTok nào chưa assign', 'info');
        return;
    }

    try {
        const res = await fetch(`${API}/api/videos/auto-assign`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ platform: 'tiktok', video_ids: candidateIds }),
        });
        const data = await res.json();
        if (!res.ok) {
            toast(`❌ ${data.detail || 'Auto-assign thất bại'}`, 'error');
            return;
        }
        toast(`⚙️ Auto-assigned ${data.assigned}/${candidateIds.length} video cho TikTok`, data.assigned ? 'success' : 'info');
        await Promise.all([refreshVideos(), refreshAssignments()]);
    } catch (e) {
        toast(`Auto-assign lỗi: ${e.message}`, 'error');
    }
}

async function quickAssignVideoTarget(videoId, deviceId, platform) {
    try {
        const res = await fetch(`${API}/api/videos/${videoId}/assign`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ device_id: deviceId, platform }),
        });
        const data = await res.json();
        if (!res.ok) {
            toast(`❌ ${data.detail || 'Assign target thất bại'}`, 'error');
            return;
        }
        focusedVideoId = videoId;
        toast(`✅ Assigned target ${platform}`, 'success');
        await Promise.all([refreshVideos(), refreshAssignments()]);
    } catch (e) {
        toast(`Assign target lỗi: ${e.message}`, 'error');
    }
}

function closeAssignModal() {
    assignmentModalState = null;
    document.getElementById('assignModal')?.remove();
}

function openAssignModal(videoId, videoTitle, initialPlatform = null) {
    const video = getVideoById(videoId);
    assignmentModalState = {
        mode: 'create',
        videoId,
        videoTitle,
        platform: initialPlatform || getActiveAssignmentPlatform(video),
        selectedDeviceId: null,
        assignmentId: null,
    };
    openAssignmentPlannerModal();
}

function openEditAssignmentModal(assignmentId) {
    const assignment = getAssignmentById(assignmentId);
    if (!assignment) {
        toast('Không tìm thấy assignment để sửa', 'error');
        return;
    }

    assignmentModalState = {
        mode: 'edit',
        assignmentId,
        videoId: assignment.video_id,
        videoTitle: assignment.video_title || assignment.video_filename || `Video #${assignment.video_id}`,
        platform: assignment.platform,
        selectedDeviceId: assignment.device_id,
    };
    openAssignmentPlannerModal();
}

function openAssignmentPlannerModal() {
    if (!devices.length) {
        toast('⚠️ Chưa có device nào. Hãy thêm device trước.', 'error');
        return;
    }

    const modal = document.createElement('div');
    modal.id = 'assignModal';
    modal.className = 'modal-overlay open';
    modal.style.cssText = 'z-index:9999';
    modal.innerHTML = `
        <div class="modal-content assignment-planner-modal" onclick="event.stopPropagation()">
            <div class="modal-header">
                <h3>${assignmentModalState.mode === 'edit' ? '✏️ Edit Assignment' : '📌 Assign Video'}: ${escapeHtml(assignmentModalState.videoTitle)}</h3>
                <button class="modal-close" onclick="closeAssignModal()">×</button>
            </div>
            <div class="modal-body">
                <div class="assignment-planner-topbar">
                    <div class="form-group">
                        <label>🌐 Platform</label>
                        <select id="assignPlatformSel" onchange="onAssignmentPlannerPlatformChange()">
                            <option value="tiktok" ${assignmentModalState.platform === 'tiktok' ? 'selected' : ''}>🎵 TikTok</option>
                            <option value="youtube" ${assignmentModalState.platform === 'youtube' ? 'selected' : ''}>▶️ YouTube</option>
                            <option value="instagram" ${assignmentModalState.platform === 'instagram' ? 'selected' : ''}>📷 Instagram</option>
                            <option value="facebook" ${assignmentModalState.platform === 'facebook' ? 'selected' : ''}>📘 Facebook</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label>🔎 Search target</label>
                        <input id="assignTargetSearch" type="text" class="assignment-search" placeholder="Device, account, model..." oninput="renderAssignmentPlannerTargets()">
                    </div>
                </div>
                <div class="assignment-planner-summary" id="assignmentPlannerSummary"></div>
                <div class="assignment-planner-grid" id="assignmentPlannerGrid"></div>
                <div class="info-box">
                    <h4>Assignment Planner</h4>
                    <div>Ưu tiên target đã map account cho platform hiện tại. Khi đổi device/platform, trạng thái push/upload cũ sẽ được reset để tránh dùng nhầm target runtime.</div>
                </div>
                <div class="assignment-planner-actions">
                    ${assignmentModalState.mode === 'edit' ? `<button class="btn btn-danger" onclick="deleteAssignment(${assignmentModalState.assignmentId}, true)">🗑️ Delete Assignment</button>` : ''}
                    <button class="btn btn-primary" onclick="submitAssignmentPlanner()">${assignmentModalState.mode === 'edit' ? '✅ Save Target' : '✅ Assign Video'}</button>
                </div>
            </div>
        </div>`;
    modal.onclick = (e) => { if (e.target === modal) closeAssignModal(); };
    document.body.appendChild(modal);
    renderAssignmentPlannerTargets();
}

function onAssignmentPlannerPlatformChange() {
    if (!assignmentModalState) return;
    assignmentModalState.platform = document.getElementById('assignPlatformSel')?.value || 'tiktok';
    if (assignmentModalState.mode === 'create') {
        assignmentModalState.selectedDeviceId = null;
    }
    renderAssignmentPlannerTargets();
}

function selectAssignmentPlannerTarget(deviceId) {
    if (!assignmentModalState) return;
    assignmentModalState.selectedDeviceId = deviceId;
    renderAssignmentPlannerTargets();
}

function renderAssignmentPlannerTargets() {
    const grid = document.getElementById('assignmentPlannerGrid');
    const summary = document.getElementById('assignmentPlannerSummary');
    if (!grid || !summary || !assignmentModalState) return;

    const platform = document.getElementById('assignPlatformSel')?.value || assignmentModalState.platform || 'tiktok';
    assignmentModalState.platform = platform;
    const search = (document.getElementById('assignTargetSearch')?.value || '').trim().toLowerCase();
    const video = getVideoById(assignmentModalState.videoId);
    const samePlatformAssignments = (video?.assignments || []).filter(item => item.platform === platform);
    const takenByDevice = new Map(
        samePlatformAssignments
            .filter(item => item.id !== assignmentModalState.assignmentId)
            .map(item => [item.device_id, item])
    );
    const targets = getAssignmentTargets(platform).filter(target => {
        if (!search) return true;
        const haystack = [
            target.device_name,
            target.account_name,
            target.device_model,
            target.account_notes,
        ].join(' ').toLowerCase();
        return haystack.includes(search);
    });

    const selectedTarget = targets.find(target => target.device_id === assignmentModalState.selectedDeviceId);
    const mappedCount = targets.filter(target => target.has_account).length;
    summary.innerHTML = `
        <div class="assignment-planner-stat">
            <strong>${targets.length}</strong>
            <span>targets</span>
        </div>
        <div class="assignment-planner-stat">
            <strong>${mappedCount}</strong>
            <span>mapped account</span>
        </div>
        <div class="assignment-planner-stat wide">
            <strong>${selectedTarget ? escapeHtml(selectedTarget.device_name || `#${selectedTarget.device_id}`) : 'Chưa chọn target'}</strong>
            <span>${escapeHtml(selectedTarget?.account_name || 'Chọn device/account phù hợp để assign')}</span>
        </div>
    `;

    if (!targets.length) {
        grid.innerHTML = '<div class="distribution-target-empty">Không có target phù hợp với bộ lọc hiện tại.</div>';
        return;
    }

    grid.innerHTML = targets.map(target => {
        const duplicateAssignment = takenByDevice.get(target.device_id);
        const disabled = Boolean(duplicateAssignment);
        const selected = assignmentModalState.selectedDeviceId === target.device_id;
        const current = assignmentModalState.mode === 'edit'
            && target.device_id === getAssignmentById(assignmentModalState.assignmentId)?.device_id
            && platform === getAssignmentById(assignmentModalState.assignmentId)?.platform;

        return `
            <button
                class="assignment-planner-card ${selected ? 'selected' : ''} ${disabled ? 'disabled' : ''}"
                onclick="${disabled ? '' : `selectAssignmentPlannerTarget(${target.device_id})`}"
                ${disabled ? 'disabled' : ''}
            >
                <div class="assignment-planner-card-top">
                    <div>
                        <div class="assignment-planner-card-title">${escapeHtml(target.device_name || `#${target.device_id}`)}</div>
                        <div class="assignment-planner-card-meta">${escapeHtml(target.account_name || 'No mapped account')}</div>
                    </div>
                    <div class="assignment-planner-card-status ${escapeHtml(String(target.device_status || 'unknown'))}">${escapeHtml(String(target.device_status || 'unknown'))}</div>
                </div>
                <div class="assignment-planner-card-badges">
                    <span class="assignment-mini-chip">${escapeHtml(getPlatformLabel(platform))}</span>
                    ${target.device_model ? `<span class="assignment-mini-chip">${escapeHtml(target.device_model)}</span>` : ''}
                    ${target.has_account ? '<span class="assignment-mini-chip">mapped</span>' : '<span class="assignment-mini-chip warn">unmapped</span>'}
                    ${current ? '<span class="assignment-mini-chip accent">current</span>' : ''}
                    ${duplicateAssignment ? `<span class="assignment-mini-chip danger">used by #${duplicateAssignment.id}</span>` : ''}
                </div>
            </button>
        `;
    }).join('');
}

async function submitAssignmentPlanner() {
    if (!assignmentModalState?.selectedDeviceId) {
        toast('Chọn target trước khi lưu assignment', 'error');
        return;
    }

    const payload = {
        device_id: assignmentModalState.selectedDeviceId,
        platform: assignmentModalState.platform,
    };

    try {
        const isEdit = assignmentModalState.mode === 'edit';
        const url = isEdit
            ? `${API}/api/videos/assignments/${assignmentModalState.assignmentId}`
            : `${API}/api/videos/${assignmentModalState.videoId}/assign`;
        const res = await fetch(url, {
            method: isEdit ? 'PATCH' : 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (!res.ok) {
            toast(`❌ ${data.detail || 'Lưu assignment thất bại'}`, 'error');
            return;
        }

        focusedVideoId = assignmentModalState.videoId;
        toast(
            isEdit
                ? `✅ Đã cập nhật target → ${getPlatformLabel(assignmentModalState.platform)}`
                : `✅ Assigned thành công → ${getPlatformLabel(assignmentModalState.platform)}`,
            'success'
        );
        closeAssignModal();
        await Promise.all([refreshVideos(), refreshAssignments()]);
    } catch (e) {
        toast(`Lỗi: ${e.message}`, 'error');
    }
}

async function deleteAssignment(assignmentId, fromModal = false) {
    const assignment = getAssignmentById(assignmentId);
    if (!assignment) {
        toast('Không tìm thấy assignment để xóa', 'error');
        return;
    }
    const targetLabel = `${assignment.device_name || `#${assignment.device_id}`} · ${getPlatformLabel(assignment.platform)}`;
    if (!window.confirm(`Xóa assignment #${assignment.id} khỏi ${targetLabel}?`)) {
        return;
    }

    try {
        const res = await fetch(`${API}/api/videos/assignments/${assignmentId}`, { method: 'DELETE' });
        if (!res.ok) {
            const data = await res.json();
            toast(`❌ ${data.detail || 'Xóa assignment thất bại'}`, 'error');
            return;
        }
        if (fromModal) closeAssignModal();
        document.getElementById('assignmentDetailModal')?.classList.remove('open');
        toast('🗑️ Đã xóa assignment', 'success');
        await Promise.all([refreshVideos(), refreshAssignments()]);
    } catch (e) {
        toast(`Xóa assignment lỗi: ${e.message}`, 'error');
    }
}

async function pushAssignment(assignmentId, btnEl) {
    const originalLabel = btnEl?.textContent || '📤 Push';
    if (btnEl) {
        btnEl.disabled = true;
        btnEl.textContent = '⏳';
    }
    try {
        const res = await fetch(`${API}/api/videos/assignments/${assignmentId}/push`, { method: 'POST' });
        const data = await res.json();
        if (res.ok) {
            toast(`✅ ${data.message}`, 'success');
        } else {
            toast(`❌ ${data.detail}`, 'error');
        }
        await Promise.all([refreshAssignments(), refreshVideos()]);
    } catch (e) {
        toast(`Push lỗi: ${e.message}`, 'error');
    } finally {
        if (btnEl) {
            btnEl.disabled = false;
            btnEl.textContent = originalLabel;
        }
    }
}

function buildRetryPrompt(assignment) {
    const hint = assignment?.error_hint_label || 'Kiểm tra logs/artifacts trước khi retry.';
    const cooldown = assignment?.rerun_cooldown_remaining_sec
        ? `Cooldown còn ${assignment.rerun_cooldown_remaining_sec}s.`
        : 'Không có cooldown đang chặn.';
    return `${hint}\n\n${cooldown}\n\nTiếp tục retry assignment #${assignment?.id}?`;
}

async function retryFailedAssignment(assignmentId, btnEl) {
    const assignment = getAssignmentById(assignmentId);
    if (!assignment) {
        toast('Không tìm thấy assignment để retry', 'error');
        return;
    }

    if (!window.confirm(buildRetryPrompt(assignment))) {
        return;
    }
    await runUploadAssignment(assignmentId, btnEl, true);
}

async function runUploadAssignment(assignmentId, btnEl, force = false) {
    const originalLabel = btnEl?.textContent || '🚀 Run';
    if (btnEl) {
        btnEl.disabled = true;
        btnEl.textContent = '⏳';
    }
    try {
        const res = await fetch(`${API}/api/videos/assignments/${assignmentId}/run-upload`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ auto_push: true, force }),
        });
        const data = await res.json();
        if (!res.ok) {
            if (!force && res.status === 409) {
                const assignment = getAssignmentById(assignmentId);
                if (assignment?.rerun_requires_confirm && window.confirm(buildRetryPrompt(assignment))) {
                    await runUploadAssignment(assignmentId, btnEl, true);
                    return;
                }
            }
            toast(`❌ ${data.detail || 'Run upload thất bại'}`, 'error');
            return;
        }
        if (data.task_id) {
            subscribeTask(data.task_id);
        }
        toast(`🚀 ${data.message}`, 'success');
        await Promise.all([refreshAssignments(), refreshVideos(), refreshRunning(), refreshHistory()]);
    } catch (e) {
        toast(`Run upload lỗi: ${e.message}`, 'error');
    } finally {
        if (btnEl) {
            btnEl.disabled = false;
            btnEl.textContent = originalLabel;
        }
    }
}

let _deleteVideoConfirmId = null;
let _deleteVideoConfirmTimer = null;

function deleteVideo(videoId, btnEl) {
    if (_deleteVideoConfirmId === videoId) {
        clearTimeout(_deleteVideoConfirmTimer);
        _deleteVideoConfirmId = null;
        _doDeleteVideo(videoId, btnEl);
        return;
    }

    if (_deleteVideoConfirmTimer) clearTimeout(_deleteVideoConfirmTimer);
    _deleteVideoConfirmId = videoId;
    if (btnEl) {
        btnEl.textContent = '⚠️ Sure?';
        btnEl.classList.add('btn-warning');
    }
    _deleteVideoConfirmTimer = setTimeout(() => {
        _deleteVideoConfirmId = null;
        if (btnEl) {
            btnEl.textContent = '🗑️';
            btnEl.classList.remove('btn-warning');
        }
    }, 3000);
}

async function _doDeleteVideo(videoId, btnEl) {
    try {
        await fetch(`${API}/api/videos/${videoId}`, { method: 'DELETE' });
        if (focusedVideoId === videoId) focusedVideoId = null;
        toast('🗑️ Đã xoá video', 'success');
        await Promise.all([refreshVideos(), refreshAssignments()]);
    } catch (e) {
        toast('Xoá thất bại', 'error');
        if (btnEl) {
            btnEl.textContent = '🗑️';
            btnEl.classList.remove('btn-warning');
        }
    }
}

function focusVideoAssignments(videoId) {
    focusedVideoId = videoId;
    renderVideoGrid(videoList);
    renderVideoOpsSummary();
    renderDistributionFocus();
    renderAssignmentViews();
}

function clearVideoFocus() {
    focusedVideoId = null;
    renderVideoGrid(videoList);
    renderVideoOpsSummary();
    renderDistributionFocus();
    renderAssignmentViews();
}

function renderAssignmentViews() {
    syncSelectedAssignments();
    renderDistributionFocus();
    renderVideoOpsSummary();
    renderAssignmentTargetRail();
    renderAssignmentBulkBar();
    renderAssignmentMatrix(getVisibleAssignments());
}

function renderAssignmentTargetRail() {
    const container = document.getElementById('assignmentTargetRail');
    if (!container) return;

    const activePlatform = getActiveAssignmentPlatform();
    const currentDeviceId = document.getElementById('assignmentDeviceFilter')?.value || '';
    const search = (document.getElementById('assignmentSearch')?.value || '').trim().toLowerCase();
    const scopedAssignments = assignmentList.filter(item => {
        if (focusedVideoId && item.video_id !== focusedVideoId) return false;
        if (!search) return true;
        const haystack = [
            item.video_title,
            item.video_filename,
            item.device_name,
            item.account_name,
            item.device_path,
            item.latest_error,
        ].join(' ').toLowerCase();
        return haystack.includes(search);
    });
    const countByDevice = new Map();
    scopedAssignments.forEach(item => {
        countByDevice.set(item.device_id, (countByDevice.get(item.device_id) || 0) + 1);
    });

    const targets = getAssignmentTargets(activePlatform);
    if (!targets.length) {
        container.innerHTML = '';
        return;
    }

    container.innerHTML = `
        <div class="assignment-target-rail">
            <button class="assignment-target-chip ${currentDeviceId ? '' : 'active'}" onclick="selectAssignmentTargetFilter('')">
                <span class="assignment-target-chip-title">All Targets</span>
                <span class="assignment-target-chip-meta">${scopedAssignments.length} assignment</span>
            </button>
            ${targets.map(target => `
                <button class="assignment-target-chip ${String(target.device_id) === currentDeviceId ? 'active' : ''}" onclick="selectAssignmentTargetFilter('${target.device_id}')">
                    <span class="assignment-target-chip-title">${escapeHtml(target.device_name || `#${target.device_id}`)}</span>
                    <span class="assignment-target-chip-meta">
                        ${escapeHtml(target.account_name || 'No account')} · ${countByDevice.get(target.device_id) || 0}
                    </span>
                </button>
            `).join('')}
        </div>
    `;
}

function selectAssignmentTargetFilter(deviceId) {
    const selectEl = document.getElementById('assignmentDeviceFilter');
    if (!selectEl) return;
    selectEl.value = deviceId;
    renderAssignmentViews();
}

function populateAssignmentDeviceFilter() {
    const selectEl = document.getElementById('assignmentDeviceFilter');
    if (!selectEl) return;
    const current = selectEl.value;
    const platform = document.getElementById('assignmentPlatformFilter')?.value || '';
    selectEl.innerHTML = '<option value="">Tất cả device</option>' +
        devices.map(device => {
            const account = deviceAccounts.find(item => item.device_id === device.id && (!platform || item.platform === platform));
            const suffix = account?.account_name ? ` · ${account.account_name}` : '';
            return `<option value="${device.id}">${escapeHtml(`${device.name}${suffix}`)}</option>`;
        }).join('');
    if ([...selectEl.options].some(opt => opt.value === current)) {
        selectEl.value = current;
    }
}

function buildAssignmentQuery() {
    const params = new URLSearchParams();
    const platform = document.getElementById('assignmentPlatformFilter')?.value || '';
    const pushStatus = document.getElementById('assignmentPushFilter')?.value || '';
    const uploadStatus = document.getElementById('assignmentUploadFilter')?.value || '';
    const actionableOnly = document.getElementById('assignmentActionableOnly')?.checked;

    if (platform) params.set('platform', platform);
    if (pushStatus) params.set('push_status', pushStatus);
    if (uploadStatus) params.set('upload_status', uploadStatus);
    if (actionableOnly) params.set('actionable_only', 'true');

    return params.toString() ? `?${params.toString()}` : '';
}

async function refreshAssignments() {
    const container = document.getElementById('assignmentMatrix');
    if (container) {
        container.innerHTML = '<div class="assignment-skeleton-grid"><div class="assignment-skeleton-row"></div><div class="assignment-skeleton-row"></div><div class="assignment-skeleton-row"></div></div>';
    }
    try {
        populateAssignmentDeviceFilter();
        const res = await fetch(`${API}/api/videos/assignments${buildAssignmentQuery()}`);
        assignmentList = await res.json();
        renderAssignmentViews();
        renderAssignmentPlannerTargets();
    } catch (e) { /* retry */ }
}

function clearAssignmentFilters() {
    const platform = document.getElementById('assignmentPlatformFilter');
    const device = document.getElementById('assignmentDeviceFilter');
    const push = document.getElementById('assignmentPushFilter');
    const upload = document.getElementById('assignmentUploadFilter');
    const search = document.getElementById('assignmentSearch');
    const actionable = document.getElementById('assignmentActionableOnly');
    const metrics = document.getElementById('assignmentMetricsFilter');

    if (platform) platform.value = 'tiktok';
    if (device) device.value = '';
    if (push) push.value = '';
    if (upload) upload.value = '';
    if (search) search.value = '';
    if (actionable) actionable.checked = false;
    if (metrics) metrics.value = '';
    focusedVideoId = null;
    selectedAssignmentIds.clear();
    refreshAssignments();
}

function toggleAssignmentSelection(assignmentId, checked) {
    if (checked) selectedAssignmentIds.add(assignmentId);
    else selectedAssignmentIds.delete(assignmentId);
    renderAssignmentBulkBar();
}

function toggleAllAssignments(checked) {
    const visible = getVisibleAssignments();
    if (checked) {
        visible.forEach(item => selectedAssignmentIds.add(item.id));
    } else {
        visible.forEach(item => selectedAssignmentIds.delete(item.id));
    }
    renderAssignmentViews();
}

function renderAssignmentBulkBar() {
    const container = document.getElementById('assignmentBulkBar');
    if (!container) return;

    const visible = getVisibleAssignments();
    const selected = visible.filter(item => selectedAssignmentIds.has(item.id));
    const pushable = selected.filter(item => item.can_push);
    const runnable = selected.filter(item => item.can_run_upload);
    const visibleRunnable = visible.filter(item => item.can_run_upload);
    const visiblePushable = visible.filter(item => item.can_push);
    const retryable = selected.filter(item => item.can_rerun || item.rerun_requires_confirm);
    const visibleRetryable = visible.filter(item => item.can_rerun || item.rerun_requires_confirm);

    container.innerHTML = `
        <div class="bulkbar-main">
            <div class="bulkbar-title">${selected.length ? `${selected.length} assignment đã chọn` : `${visible.length} assignment đang hiển thị`}</div>
            <div class="bulkbar-sub">TikTok-first flow: assign → push → run upload → review logs/artifacts.</div>
        </div>
        <div class="bulkbar-actions">
            <button class="btn btn-sm btn-ghost" ${pushable.length ? '' : 'disabled'} onclick="pushAssignmentsBatch([${pushable.map(item => item.id).join(',')}])">📤 Push Selected</button>
            <button class="btn btn-sm btn-primary" ${runnable.length ? '' : 'disabled'} onclick="runAssignmentsBatch([${runnable.map(item => item.id).join(',')}])">🚀 Run Selected</button>
            <button class="btn btn-sm btn-ghost" ${retryable.length ? '' : 'disabled'} onclick="retryAssignmentsBatch([${retryable.map(item => item.id).join(',')}])">🔁 Retry Selected</button>
            <button class="btn btn-sm btn-ghost" ${visiblePushable.length ? '' : 'disabled'} onclick="pushAssignmentsBatch([${visiblePushable.map(item => item.id).join(',')}])">📦 Push Visible</button>
            <button class="btn btn-sm btn-primary" ${visibleRunnable.length ? '' : 'disabled'} onclick="runAssignmentsBatch([${visibleRunnable.map(item => item.id).join(',')}])">⚡ Run All Ready</button>
            <button class="btn btn-sm btn-ghost" ${visibleRetryable.length ? '' : 'disabled'} onclick="retryAssignmentsBatch([${visibleRetryable.map(item => item.id).join(',')}])">🛟 Retry Failed</button>
            <button class="btn btn-sm btn-ghost" ${selected.length ? '' : 'disabled'} onclick="selectedAssignmentIds.clear(); renderAssignmentViews()">Clear</button>
        </div>
    `;
}

async function pushAssignmentsBatch(ids) {
    const assignmentIds = ids.filter(Boolean);
    if (!assignmentIds.length) {
        toast('Không có assignment nào cần push', 'info');
        return;
    }

    try {
        const res = await fetch(`${API}/api/videos/assignments/push-batch`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ assignment_ids: assignmentIds }),
        });
        const data = await res.json();
        if (!res.ok) {
            toast(`❌ ${data.detail || 'Batch push thất bại'}`, 'error');
            return;
        }
        toast(`📤 Push xong ${data.succeeded}/${data.total} assignment`, data.failed ? 'info' : 'success');
        await Promise.all([refreshAssignments(), refreshVideos()]);
    } catch (e) {
        toast(`Batch push lỗi: ${e.message}`, 'error');
    }
}

async function runAssignmentsBatch(ids) {
    return runAssignmentsBatchWithOptions(ids, { force: false });
}

async function retryAssignmentsBatch(ids) {
    const assignmentIds = ids.filter(Boolean);
    if (!assignmentIds.length) {
        toast('Không có assignment failed nào để retry', 'info');
        return;
    }
    if (!window.confirm(`Retry ${assignmentIds.length} assignment failed? Hãy kiểm tra artifact/log trước nếu lỗi liên quan gallery hoặc verify.`)) {
        return;
    }
    return runAssignmentsBatchWithOptions(assignmentIds, { force: true });
}

async function runAssignmentsBatchWithOptions(ids, { force = false } = {}) {
    const assignmentIds = ids.filter(Boolean);
    if (!assignmentIds.length) {
        toast('Không có assignment nào sẵn sàng upload', 'info');
        return;
    }

    try {
        const res = await fetch(`${API}/api/videos/assignments/run-batch`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ assignment_ids: assignmentIds, auto_push: true, force }),
        });
        const data = await res.json();
        if (!res.ok) {
            toast(`❌ ${data.detail || 'Batch run thất bại'}`, 'error');
            return;
        }
        (data.results || []).forEach(item => {
            if (item.task_id) subscribeTask(item.task_id);
        });
        toast(`🚀 Queue ${data.succeeded}/${data.total} assignment`, data.failed ? 'info' : 'success');
        await Promise.all([refreshAssignments(), refreshVideos(), refreshRunning(), refreshHistory()]);
    } catch (e) {
        toast(`Batch run lỗi: ${e.message}`, 'error');
    }
}

function renderAssignmentMatrix(assignments) {
    const container = document.getElementById('assignmentMatrix');
    if (!container) return;

    if (!assignments.length) {
        container.innerHTML = '<div class="empty-state"><div class="empty-icon">📊</div><div class="empty-text">Không có assignment phù hợp bộ lọc hiện tại</div></div>';
        return;
    }

    const allSelected = assignments.length > 0 && assignments.every(item => selectedAssignmentIds.has(item.id));
    const rows = assignments.map(item => {
        const selected = selectedAssignmentIds.has(item.id);
        const lastEvent = item.uploaded_at || item.last_run_at || item.pushed_at || item.created_at;
        const taskLink = item.task_id
            ? `<button class="btn btn-xs btn-ghost" onclick="openTaskDetail(${item.task_id})">🧾 Task</button>`
            : '';
        const artifactLink = renderArtifactActionButton(item);
        const errorLine = item.latest_error
            ? `<div class="assignment-error-line">${escapeHtml(shortenText(item.latest_error, 120))}</div>`
            : '';
        const hintLine = item.error_hint_label
            ? `<div class="assignment-hint-line">${escapeHtml(item.error_hint_label)}</div>`
            : '';
        const liveHtml = renderLiveTaskState(item);

        // Performance column content
        const metricsHtml = item.has_metrics
            ? `<div class="assignment-metrics-line">${renderMetricsInline(item)}</div>`
            : '';
        const metricsStatusHtml = item.upload_status === 'uploaded'
            ? renderMetricsBadge(item.metrics_status)
            : '<span class="metrics-status-badge na">—</span>';
        const syncedAt = item.metrics_last_synced_at
            ? `<div class="assignment-secondary">${formatDateTime(item.metrics_last_synced_at)}</div>`
            : '';

        return `
            <tr class="${selected ? 'selected' : ''}">
                <td><input type="checkbox" ${selected ? 'checked' : ''} onchange="toggleAssignmentSelection(${item.id}, this.checked)"></td>
                <td>
                    <div class="assignment-primary">${escapeHtml(shortenText(item.video_title || item.video_filename || `#${item.video_id}`, 48))}</div>
                    <div class="assignment-secondary">#${item.video_id} · ${escapeHtml(item.video_filename || '')}</div>
                    ${errorLine}
                    ${hintLine}
                </td>
                <td>
                    <div class="assignment-primary">${escapeHtml(item.device_name || `#${item.device_id}`)}</div>
                    <div class="assignment-secondary">${escapeHtml(item.account_name || 'Chưa map account')}</div>
                    <div class="assignment-chip-row">
                        <span class="assignment-mini-chip">${escapeHtml(getPlatformLabel(item.platform))}</span>
                        <span class="assignment-mini-chip">${escapeHtml(item.device_status || 'unknown')}</span>
                    </div>
                </td>
                <td>
                    <div class="assignment-primary">${platformIcon(item.platform)} ${escapeHtml(item.platform)}</div>
                    <div class="assignment-secondary">${escapeHtml(item.device_path || 'Chưa có device path')}</div>
                </td>
                <td>${renderPushBadge(item.push_status)}</td>
                <td>${renderUploadBadge(item.upload_status)}</td>
                <td>
                    ${metricsStatusHtml}
                    ${metricsHtml}
                    ${syncedAt}
                </td>
                <td>
                    <div class="assignment-primary">${formatDateTime(lastEvent)}</div>
                    <div class="assignment-secondary">${item.task_status ? `task ${item.task_status}` : 'chưa tạo task'}</div>
                    ${liveHtml}
                </td>
                <td class="assignment-actions-cell">
                    <button class="btn btn-xs btn-ghost" onclick="openEditAssignmentModal(${item.id})">✏️ Edit</button>
                    <button class="btn btn-xs btn-danger" onclick="deleteAssignment(${item.id})">🗑️</button>
                    <button class="btn btn-xs btn-ghost" onclick="openAssignmentDetail(${item.id})">🔍 Detail</button>
                    ${renderPrimaryUploadAction(item) || ''}
                    ${artifactLink || ''}
                    ${taskLink}
                </td>
            </tr>
        `;
    }).join('');

    container.innerHTML = `
        <div class="assignment-table-wrap">
            <table class="assignment-table assignment-board-table">
                <thead>
                    <tr>
                        <th><input type="checkbox" ${allSelected ? 'checked' : ''} onchange="toggleAllAssignments(this.checked)"></th>
                        <th>Video</th>
                        <th>Device / Account</th>
                        <th>Platform / Path</th>
                        <th>Push</th>
                        <th>Upload</th>
                        <th>Performance</th>
                        <th>Last Event</th>
                        <th>Action</th>
                    </tr>
                </thead>
                <tbody>${rows}</tbody>
            </table>
        </div>
    `;
}

async function openAssignmentDetail(assignmentId) {
    const assignment = getAssignmentById(assignmentId);
    if (!assignment) {
        toast('Không tìm thấy assignment', 'error');
        return;
    }

    const modal = document.getElementById('assignmentDetailModal');
    const title = document.getElementById('assignmentDetailTitle');
    const body = document.getElementById('assignmentDetailBody');
    title.textContent = `Assignment #${assignment.id} · ${assignment.video_title || assignment.video_filename || assignment.video_id}`;
    body.innerHTML = '<div class="loading">Loading assignment review...</div>';
    modal.classList.add('open');

    let logs = [];
    let artifact = null;
    try {
        const requests = [];
        if (assignment.task_id) {
            requests.push(fetch(`${API}/api/tasks/${assignment.task_id}/logs`).then(r => r.ok ? r.json() : []));
        } else {
            requests.push(Promise.resolve([]));
        }
        requests.push(fetch(`${API}/api/videos/assignments/${assignment.id}/artifacts`).then(r => r.ok ? r.json() : null));
        [logs, artifact] = await Promise.all(requests);
    } catch (_) {
        logs = [];
        artifact = null;
    }

    const recentSteps = (logs || []).slice(-8).map(log => `
        <div class="assignment-detail-step">
            <span class="assignment-detail-step-num">#${log.step}</span>
            <span class="assignment-detail-step-action">${escapeHtml(log.action)}</span>
            <span class="assignment-detail-step-detail">${escapeHtml(shortenText(log.detail || log.action, 120))}</span>
        </div>
    `).join('');

    const artifactLinks = artifact
        ? `
            <div class="assignment-detail-artifacts">
                <div class="assignment-detail-line"><strong>Session:</strong> ${escapeHtml(artifact.session_name || '—')}</div>
                <div class="assignment-detail-line"><strong>Finished:</strong> ${formatDateTime(artifact.finished_at)}</div>
                <div class="assignment-detail-link-row">
                    ${artifact.manifest_url ? `<a class="btn btn-xs btn-ghost" href="${artifact.manifest_url}" target="_blank" rel="noreferrer">Manifest</a>` : ''}
                    ${artifact.screenrecord_url ? `<a class="btn btn-xs btn-ghost" href="${artifact.screenrecord_url}" target="_blank" rel="noreferrer">Screenrecord</a>` : ''}
                    ${artifact.latest_snapshot?.screenshot_url ? `<a class="btn btn-xs btn-ghost" href="${artifact.latest_snapshot.screenshot_url}" target="_blank" rel="noreferrer">Latest Screenshot</a>` : ''}
                    ${artifact.latest_snapshot?.xml_url ? `<a class="btn btn-xs btn-ghost" href="${artifact.latest_snapshot.xml_url}" target="_blank" rel="noreferrer">Latest XML</a>` : ''}
                </div>
            </div>
        `
        : '<div class="assignment-detail-line">Chưa có artifact cho assignment này.</div>';

    body.innerHTML = `
        <div class="assignment-detail-grid">
            <div class="assignment-detail-card">
                <h4>Pipeline State</h4>
                <div class="assignment-detail-badges">${renderPushBadge(assignment.push_status)} ${renderUploadBadge(assignment.upload_status)}</div>
                <div class="assignment-detail-line"><strong>Device:</strong> ${escapeHtml(assignment.device_name || `#${assignment.device_id}`)}</div>
                <div class="assignment-detail-line"><strong>Account:</strong> ${escapeHtml(assignment.account_name || 'Chưa map')}</div>
                <div class="assignment-detail-line"><strong>Device path:</strong> ${escapeHtml(assignment.device_path || 'Chưa push')}</div>
                <div class="assignment-detail-line"><strong>Task:</strong> ${assignment.task_id ? `#${assignment.task_id} · ${escapeHtml(assignment.task_status || 'unknown')}` : 'Chưa có'}</div>
                <div class="assignment-detail-line"><strong>Retry hint:</strong> ${escapeHtml(assignment.error_hint_label || 'Không cần')}</div>
            </div>
            <div class="assignment-detail-card">
                <h4>Video Metadata</h4>
                <div class="assignment-detail-line"><strong>Title:</strong> ${escapeHtml(assignment.video_title || '—')}</div>
                <div class="assignment-detail-line"><strong>Tags:</strong> ${escapeHtml(assignment.video_tags || '—')}</div>
                <div class="assignment-detail-line"><strong>Description:</strong> ${escapeHtml(assignment.video_description || '—')}</div>
            </div>
            <div class="assignment-detail-card">
                <h4>Timeline</h4>
                <div class="assignment-detail-line"><strong>Created:</strong> ${formatDateTime(assignment.created_at)}</div>
                <div class="assignment-detail-line"><strong>Pushed:</strong> ${formatDateTime(assignment.pushed_at)}</div>
                <div class="assignment-detail-line"><strong>Last run:</strong> ${formatDateTime(assignment.last_run_at)}</div>
                <div class="assignment-detail-line"><strong>Uploaded:</strong> ${formatDateTime(assignment.uploaded_at)}</div>
            </div>
            <div class="assignment-detail-card">
                <h4>Review</h4>
                <div class="assignment-detail-line"><strong>Last error:</strong> ${escapeHtml(assignment.latest_error || 'Không có')}</div>
                <div class="assignment-detail-line"><strong>Task result:</strong> ${escapeHtml(assignment.task_result || assignment.task_error || 'Chưa có')}</div>
                <div class="assignment-detail-line"><strong>Cooldown:</strong> ${assignment.rerun_cooldown_remaining_sec ? `${assignment.rerun_cooldown_remaining_sec}s` : 'Không chặn'}</div>
            </div>
            <div class="assignment-detail-card">
                <h4>Artifacts</h4>
                ${artifactLinks}
            </div>
            <div class="assignment-detail-card metrics-detail-card">
                <h4>📊 Performance</h4>
                <div class="assignment-detail-badges">${renderMetricsBadge(assignment.metrics_status)}</div>
                <div class="assignment-detail-line"><strong>Views:</strong> ${formatMetricNumber(assignment.latest_views)}</div>
                <div class="assignment-detail-line"><strong>Likes:</strong> ${formatMetricNumber(assignment.latest_likes)}</div>
                <div class="assignment-detail-line"><strong>Comments:</strong> ${formatMetricNumber(assignment.latest_comments)}</div>
                <div class="assignment-detail-line"><strong>Shares:</strong> ${formatMetricNumber(assignment.latest_shares)}</div>
                <div class="assignment-detail-line"><strong>Last synced:</strong> ${formatDateTime(assignment.metrics_last_synced_at)}</div>
                ${assignment.metrics_error ? `<div class="assignment-error-line">${escapeHtml(shortenText(assignment.metrics_error, 120))}</div>` : ''}
                ${assignment.upload_status === 'uploaded' ? `<button class="btn btn-xs btn-accent" onclick="openManualMetricsModal(${assignment.id})">📝 Manual Input</button>` : ''}
            </div>
            <div class="assignment-detail-card">
                <h4>Recent Task Steps</h4>
                ${recentSteps || '<div class="assignment-detail-line">Chưa có step logs.</div>'}
            </div>
        </div>
        <div class="assignment-detail-actions">
            <button class="btn btn-sm btn-ghost" onclick="openEditAssignmentModal(${assignment.id})">✏️ Edit Target</button>
            <button class="btn btn-sm btn-danger" onclick="deleteAssignment(${assignment.id})">🗑️ Delete</button>
            ${renderPrimaryUploadAction(assignment) || ''}
            ${renderArtifactActionButton(assignment) || ''}
            ${assignment.task_id ? `<button class="btn btn-sm btn-ghost" onclick="openTaskDetail(${assignment.task_id})">🧾 Open Task Detail</button>` : ''}
        </div>
    `;
}

function closeAssignmentDetail(event) {
    if (event && event.target !== event.currentTarget) return;
    document.getElementById('assignmentDetailModal').classList.remove('open');
}

function openAiSuggestModal(videoId, videoTitle) {
    const video = videoList.find(v => v.id === videoId);
    const hasExisting = video && (video.ai_title || video.ai_tags || video.ai_description);

    const modal = document.createElement('div');
    modal.id = 'aiSuggestModal';
    modal.className = 'modal-overlay open';
    modal.style.cssText = 'z-index:9999';

    let existingHtml = '';
    if (hasExisting) {
        existingHtml = `
            <div class="ai-suggest-existing">
                <h4>✨ Gợi ý hiện có</h4>
                <div class="ai-field"><span class="ai-label">Title</span><span class="ai-value">${escapeHtml(video.ai_title || '—')}</span></div>
                <div class="ai-field"><span class="ai-label">Tags</span><span class="ai-value">${escapeHtml(video.ai_tags || '—')}</span></div>
                <div class="ai-field"><span class="ai-label">Desc</span><span class="ai-value">${escapeHtml(video.ai_description || '—')}</span></div>
                <div style="display:flex;gap:8px;margin-top:12px">
                    <button class="btn btn-xs btn-primary" onclick="applyAiSuggestions(${videoId})">✅ Apply</button>
                    <button class="btn btn-xs btn-ghost" onclick="requestAiSuggest(${videoId})">🔄 Tạo lại</button>
                </div>
            </div>
            <hr style="border-color:rgba(255,255,255,0.1);margin:16px 0">`;
    }

    modal.innerHTML = `
        <div class="modal-content" onclick="event.stopPropagation()" style="max-width:480px">
            <div class="modal-header">
                <h3>🤖 AI Suggest: ${escapeHtml(videoTitle)}</h3>
                <button class="modal-close" onclick="document.getElementById('aiSuggestModal').remove()">×</button>
            </div>
            <div class="modal-body">
                ${existingHtml}
                <div id="aiCacheBadges" style="margin-bottom:12px"></div>
                <div class="form-group">
                    <label>🌐 Platform target</label>
                    <select id="aiPlatformSel">
                        <option value="tiktok">🎵 TikTok</option>
                        <option value="youtube">▶️ YouTube</option>
                        <option value="instagram">📷 Instagram</option>
                        <option value="facebook">📘 Facebook</option>
                    </select>
                </div>
                <div class="form-group">
                    <label>🗣️ Ngôn ngữ output</label>
                    <select id="aiLangSel">
                        <option value="vi">🇻🇳 Tiếng Việt</option>
                        <option value="en">🇺🇸 English</option>
                        <option value="ja">🇯🇵 日本語</option>
                        <option value="ko">🇰🇷 한국어</option>
                        <option value="zh">🇨🇳 中文</option>
                        <option value="th">🇹🇭 ภาษาไทย</option>
                        <option value="id">🇮🇩 Bahasa Indonesia</option>
                        <option value="auto">🤖 Auto-detect</option>
                    </select>
                </div>
                <div style="display:flex;gap:8px">
                    <button class="btn btn-primary" style="flex:1" onclick="requestAiSuggest(${videoId}, false)">⚡ Lấy gợi ý</button>
                    <button class="btn btn-ghost" onclick="requestAiSuggest(${videoId}, true)" title="Tạo mới (tốn token)">🔄 Tạo mới</button>
                </div>
                <div id="aiSuggestResult" style="margin-top:16px"></div>
            </div>
        </div>`;
    modal.onclick = (e) => { if (e.target === modal) modal.remove(); };
    document.body.appendChild(modal);
    _loadAiCache(videoId);
}

async function _loadAiCache(videoId) {
    try {
        const res = await fetch(`${API}/api/videos/${videoId}/ai-cache`);
        if (!res.ok) return;
        const cache = await res.json();
        const badgesDiv = document.getElementById('aiCacheBadges');
        if (!badgesDiv || !cache.length) return;

        const langFlags = { vi: '🇻🇳', en: '🇺🇸', ja: '🇯🇵', ko: '🇰🇷', zh: '🇨🇳', th: '🇹🇭', id: '🇮🇩', auto: '🤖' };
        const badges = cache.map(c => {
            const flag = langFlags[c.language] || '🌐';
            return `<span class="ai-cache-badge" onclick="_loadCachedResult(${videoId}, '${c.language}', '${c.platform}')" title="${escapeHtml(`${c.platform} / ${c.language}`)}">${flag} ${escapeHtml(c.language)}/${escapeHtml(c.platform)}</span>`;
        }).join(' ');
        badgesDiv.innerHTML = `<div style="font-size:11px;color:var(--text-muted);margin-bottom:4px">💾 Cached (click to load, 0 tokens):</div>${badges}`;
    } catch (e) { /* ignore */ }
}

async function _loadCachedResult(videoId, language, platform) {
    const langSel = document.getElementById('aiLangSel');
    const platSel = document.getElementById('aiPlatformSel');
    if (langSel) langSel.value = language;
    if (platSel) platSel.value = platform;
    await requestAiSuggest(videoId, false);
}

async function requestAiSuggest(videoId, force = false) {
    const platform = document.getElementById('aiPlatformSel')?.value || 'tiktok';
    const language = document.getElementById('aiLangSel')?.value || 'vi';
    const resultDiv = document.getElementById('aiSuggestResult');
    if (resultDiv) {
        const msg = force
            ? '🤖 AI đang tạo mới (tốn token)...<br><small>5-15 giây</small>'
            : '⚡ Đang tải...';
        resultDiv.innerHTML = `<div style="text-align:center;padding:24px"><div class="spinner"></div><div style="margin-top:12px;color:var(--text-muted);font-size:13px">${msg}</div></div>`;
    }

    try {
        const res = await fetch(`${API}/api/videos/${videoId}/ai-suggest`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ platform, language, force }),
        });
        const data = await res.json();

        if (!res.ok) {
            if (resultDiv) resultDiv.innerHTML = `<div class="ai-error">❌ ${escapeHtml(data.detail || 'AI generation failed')}</div>`;
            toast('❌ AI suggest thất bại', 'error');
            return;
        }

        const cacheLabel = data.cached
            ? '<span style="color:#4ade80;font-size:11px">⚡ Từ cache (0 tokens)</span>'
            : '<span style="color:#f59e0b;font-size:11px">🤖 Mới tạo</span>';
        toast(data.cached ? '⚡ Loaded from cache!' : '✨ AI đã tạo gợi ý mới!', 'success');

        if (resultDiv) {
            resultDiv.innerHTML = `
                <div class="ai-suggest-result">
                    <h4>✨ Kết quả AI ${cacheLabel}</h4>
                    <div style="font-size:11px;color:var(--text-muted);margin-bottom:8px">🌐 ${escapeHtml(data.language || language)} / ${escapeHtml(data.platform || platform)}</div>
                    <div class="ai-field"><span class="ai-label">Title</span><span class="ai-value">${escapeHtml(data.ai_title || '—')}</span></div>
                    <div class="ai-field"><span class="ai-label">Tags</span><span class="ai-value">${escapeHtml(data.ai_tags || '—')}</span></div>
                    <div class="ai-field"><span class="ai-label">Desc</span><span class="ai-value">${escapeHtml(data.ai_description || '—')}</span></div>
                    <button class="btn btn-primary btn-block" style="margin-top:12px" onclick="applyAiSuggestions(${videoId})">✅ Apply gợi ý → Video</button>
                </div>`;
        }

        await refreshVideos();
        _loadAiCache(videoId);
    } catch (e) {
        if (resultDiv) resultDiv.innerHTML = `<div class="ai-error">❌ Lỗi: ${escapeHtml(e.message)}</div>`;
        toast(`AI lỗi: ${e.message}`, 'error');
    }
}

async function applyAiSuggestions(videoId) {
    try {
        const res = await fetch(`${API}/api/videos/${videoId}/apply-ai`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({}),
        });
        const data = await res.json();
        if (res.ok) {
            toast('✅ Đã apply AI suggestions', 'success');
            document.getElementById('aiSuggestModal')?.remove();
            await refreshVideos();
            renderDistributionFocus();
        } else {
            toast(`❌ ${data.detail || 'Apply thất bại'}`, 'error');
        }
    } catch (e) {
        toast(`Lỗi: ${e.message}`, 'error');
    }
}

async function refreshDeviceAccounts() {
    try {
        const res = await fetch(`${API}/api/device-accounts`);
        deviceAccounts = await res.json();
        renderAccountList(deviceAccounts);
        if (currentPage === 'videos') {
            renderAssignmentViews();
            renderAssignmentPlannerTargets();
        }
    } catch (e) { /* retry */ }
}

function renderAccountList(accounts) {
    const container = document.getElementById('accountList');
    if (!container) return;
    if (!accounts.length) {
        container.innerHTML = '<div style="font-size:12px;color:var(--text-muted);text-align:center;padding:12px">Chưa có account nào</div>';
        return;
    }

    const icons = { tiktok: '🎵', youtube: '▶️', instagram: '📷', facebook: '📘' };
    container.innerHTML = accounts.map(account => `
        <div class="account-list-item">
            <div>
                <div class="account-name">${escapeHtml(account.account_name || '(unnamed)')}</div>
                <div class="account-plat">${icons[account.platform] || '?'} ${escapeHtml(account.platform)} · ${escapeHtml(account.device_name || `#${account.device_id}`)}</div>
            </div>
            <button class="btn btn-xs btn-danger" onclick="deleteDeviceAccount(${account.id})">🗑️</button>
        </div>
    `).join('');
}

async function saveDeviceAccount(e) {
    e.preventDefault();
    const deviceId = parseInt(document.getElementById('accountDevice').value);
    const platform = document.getElementById('accountPlatform').value;
    const accountName = document.getElementById('accountName').value.trim();
    const notes = document.getElementById('accountNotes').value.trim();

    if (!deviceId) {
        toast('Chọn device', 'error');
        return;
    }

    try {
        const res = await fetch(`${API}/api/device-accounts`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ device_id: deviceId, platform, account_name: accountName || null, notes: notes || null }),
        });
        if (!res.ok) {
            const err = await res.json();
            toast(`❌ ${err.detail}`, 'error');
            return;
        }

        toast('✅ Đã lưu account', 'success');
        document.getElementById('accountForm').reset();
        await refreshDeviceAccounts();
        await refreshAssignments();
    } catch (e) {
        toast(`Lỗi: ${e.message}`, 'error');
    }
}

async function deleteDeviceAccount(id) {
    try {
        await fetch(`${API}/api/device-accounts/${id}`, { method: 'DELETE' });
        toast('🗑️ Đã xoá mapping', 'success');
        await refreshDeviceAccounts();
        await refreshAssignments();
    } catch (e) {
        toast('Xoá thất bại', 'error');
    }
}

function _populateAccountDeviceSelect() {
    const sel = document.getElementById('accountDevice');
    if (!sel) return;
    const cur = sel.value;
    sel.innerHTML = '<option value="">Chọn device...</option>' +
        devices.map(d => `<option value="${d.id}">${escapeHtml(d.name)}</option>`).join('');
    if (cur) sel.value = cur;
    populateAssignmentDeviceFilter();
}

// ===== MANUAL METRICS MODAL =====

function openManualMetricsModal(assignmentId) {
    const assignment = getAssignmentById(assignmentId);
    if (!assignment) {
        toast('Không tìm thấy assignment', 'error');
        return;
    }

    const modal = document.createElement('div');
    modal.id = 'manualMetricsModal';
    modal.className = 'modal-overlay open';
    modal.style.cssText = 'z-index:10001';
    modal.innerHTML = `
        <div class="modal-content" onclick="event.stopPropagation()" style="max-width:420px">
            <div class="modal-header">
                <h3>📝 Manual Metrics Input</h3>
                <button class="modal-close" onclick="closeManualMetricsModal()">×</button>
            </div>
            <div class="modal-body">
                <div class="info-box">
                    <strong>${escapeHtml(assignment.video_title || assignment.video_filename || `#${assignment.video_id}`)}</strong>
                    <div>${escapeHtml(assignment.device_name || '')} · ${escapeHtml(assignment.account_name || '')}</div>
                </div>
                <div class="form-group">
                    <label>👁 Views</label>
                    <input type="number" id="manualMetricsViews" min="0" value="${assignment.latest_views ?? ''}">
                </div>
                <div class="form-group">
                    <label>❤ Likes</label>
                    <input type="number" id="manualMetricsLikes" min="0" value="${assignment.latest_likes ?? ''}">
                </div>
                <div class="form-group">
                    <label>💬 Comments</label>
                    <input type="number" id="manualMetricsComments" min="0" value="${assignment.latest_comments ?? ''}">
                </div>
                <div class="form-group">
                    <label>↗ Shares</label>
                    <input type="number" id="manualMetricsShares" min="0" value="${assignment.latest_shares ?? ''}">
                </div>
                <button class="btn btn-primary" onclick="submitManualMetrics(${assignmentId})" style="width:100%;margin-top:12px">💾 Save Metrics</button>
            </div>
        </div>
    `;
    modal.onclick = (e) => { if (e.target === modal) closeManualMetricsModal(); };
    document.body.appendChild(modal);
}

function closeManualMetricsModal() {
    document.getElementById('manualMetricsModal')?.remove();
}

async function submitManualMetrics(assignmentId) {
    const views = document.getElementById('manualMetricsViews')?.value;
    const likes = document.getElementById('manualMetricsLikes')?.value;
    const comments = document.getElementById('manualMetricsComments')?.value;
    const shares = document.getElementById('manualMetricsShares')?.value;

    const payload = {};
    if (views !== '' && views !== undefined) payload.views = parseInt(views);
    if (likes !== '' && likes !== undefined) payload.likes = parseInt(likes);
    if (comments !== '' && comments !== undefined) payload.comments = parseInt(comments);
    if (shares !== '' && shares !== undefined) payload.shares = parseInt(shares);

    if (!Object.keys(payload).length) {
        toast('Nhập ít nhất 1 giá trị', 'error');
        return;
    }

    try {
        const res = await fetch(`${API}/api/videos/assignments/${assignmentId}/metrics`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (!res.ok) {
            toast(`❌ ${data.detail || 'Save metrics thất bại'}`, 'error');
            return;
        }
        toast('✅ Đã lưu metrics', 'success');
        closeManualMetricsModal();
        await Promise.all([refreshAssignments(), refreshVideos()]);
    } catch (e) {
        toast(`Lỗi: ${e.message}`, 'error');
    }
}
