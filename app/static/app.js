/**
 * Android Control Dashboard — Redesigned Client-side JavaScript
 */

const API = '';  // Same origin
let devices = [];
let templates = [];
let refreshTimer = null;

// ===== INITIALIZATION =====

document.addEventListener('DOMContentLoaded', () => {
    init();
});

async function init() {
    await Promise.all([
        refreshDevices(),
        loadTemplates(),
        refreshRunning(),
        refreshHistory(),
        refreshStats(),
    ]);
    updateCostEstimate();
    // Auto-refresh every 3 seconds
    refreshTimer = setInterval(() => {
        refreshDevices();
        refreshRunning();
        refreshQueueStatus();
    }, 3000);
    // History + Stats every 10s
    setInterval(refreshHistory, 10000);
    setInterval(refreshStats, 10000);
}

// ===== SIDEBAR NAVIGATION =====

function navigateTo(section, btn) {
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
    const titles = { dashboard: 'Dashboard', devices: 'Devices', scheduler: 'Scheduler' };
    document.getElementById('pageTitle').textContent = titles[section] || 'Dashboard';

    // Load data for section
    if (section === 'scheduler') loadSchedules();
}

function toggleSidebar() {
    document.getElementById('sidebar').classList.toggle('open');
}

// ===== STATS =====

async function refreshStats() {
    try {
        const res = await fetch(`${API}/api/stats`);
        const data = await res.json();

        document.getElementById('statDevices').textContent = data.devices.total;
        document.getElementById('statDevicesSub').textContent =
            `${data.devices.online} online · ${data.devices.offline} offline`;

        document.getElementById('statTasksToday').textContent = data.tasks_today.total;
        document.getElementById('statTasksSub').textContent =
            `${data.tasks_today.completed} done · ${data.tasks_today.running} running`;

        document.getElementById('statCost').textContent = `$${data.total_cost.toFixed(3)}`;
        document.getElementById('statRate').textContent = `${data.success_rate}%`;
    } catch (e) { /* retry */ }
}

// ===== DEVICES =====

async function refreshDevices() {
    try {
        const res = await fetch(`${API}/api/devices`);
        devices = await res.json();
        renderDevices();
        updateDeviceSelect();
    } catch (e) {
        document.getElementById('serverStatus').innerHTML =
            '<span class="pulse" style="background:var(--red)"></span><span style="color:var(--red)">Disconnected</span>';
    }
}

function renderDevices() {
    const container = document.getElementById('deviceList');
    if (!devices.length) {
        container.innerHTML = '<div class="empty-state"><div class="empty-icon">📱</div><div class="empty-text">No devices registered</div></div>';
        return;
    }
    container.innerHTML = '<div class="device-grid">' + devices.map(d => `
        <div class="device-card" onclick="selectDevice(${d.id})" id="dev-${d.id}">
            <div class="device-header">
                <span class="device-name">${d.name}</span>
                <span class="device-status status-${d.status}">${d.status}</span>
            </div>
            <div class="device-info">
                <span>📍 ${d.ip_address}</span>
                <span>📱 ${d.device_model || '—'}</span>
                ${d.battery_level !== null ? `<span>🔋 ${d.battery_level}%</span>` : ''}
                ${d.android_version ? `<span>🤖 v${d.android_version}</span>` : ''}
            </div>
            <div class="device-actions">
                ${d.status === 'offline'
                    ? `<button class="btn btn-xs btn-primary" onclick="event.stopPropagation(); connectDevice(${d.id})">Connect</button>`
                    : `<button class="btn btn-xs btn-ghost" onclick="event.stopPropagation(); disconnectDevice(${d.id})">Disconnect</button>`
                }
                <button class="btn btn-xs btn-danger" onclick="event.stopPropagation(); deleteDevice(${d.id})">Delete</button>
            </div>
        </div>
    `).join('') + '</div>';
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

async function deleteDevice(id) {
    if (!confirm('Delete this device?')) return;
    try {
        await fetch(`${API}/api/devices/${id}`, { method: 'DELETE' });
        toast('Device deleted', 'success');
        refreshDevices();
        refreshStats();
    } catch (e) { toast('Failed', 'error'); }
}

// ===== TEMPLATES =====

async function loadTemplates() {
    try {
        const res = await fetch(`${API}/api/templates`);
        templates = await res.json();
        const sel = document.getElementById('templateSelect');
        sel.innerHTML = '<option value="">No template</option>' +
            templates.map(t => `<option value="${t.name}">${t.title}</option>`).join('');
    } catch (e) { /* templates optional */ }
}

function onTemplateChange() {
    const name = document.getElementById('templateSelect').value;
    const tpl = templates.find(t => t.name === name);
    if (tpl) {
        document.getElementById('commandInput').placeholder = tpl.description;
    }
}

// ===== ACTION CARDS =====

function selectAction(card) {
    document.querySelectorAll('.action-card').forEach(c => c.classList.remove('selected'));
    card.classList.add('selected');

    const action = card.dataset.action;
    const mode = card.dataset.mode;
    document.getElementById('selectedAction').value = action;
    document.getElementById('executionMode').value = mode;

    document.getElementById('scriptConfig').style.display = mode === 'script' ? 'block' : 'none';
    document.getElementById('aiConfig').style.display = mode === 'ai' ? 'block' : 'none';

    const btn = document.getElementById('submitBtn');
    btn.disabled = false;
    if (mode === 'script') {
        btn.textContent = `🔧 Chạy ${card.querySelector('.action-name').textContent} — $0`;
    } else {
        btn.textContent = '🧠 Chạy AI Task';
    }

    updateCostEstimate();
}

// ===== SUBMIT TASK =====

async function submitTask(e) {
    e.preventDefault();

    const action = document.getElementById('selectedAction').value;
    const mode = document.getElementById('executionMode').value;
    if (!action) { toast('Chọn hành động trước', 'error'); return; }

    if (mode === 'ai') {
        const cmd = document.getElementById('commandInput').value.trim();
        if (!cmd) { toast('⚠️ Nhập lệnh cho AI', 'error'); return; }
    }

    const btn = document.getElementById('submitBtn');
    btn.disabled = true;
    btn.textContent = '⏳ Đang gửi...';

    const batchMode = document.getElementById('batchMode').checked;

    let payload;
    if (mode === 'script') {
        const count = parseInt(document.getElementById('scriptCount').value) || 5;
        const viewTimeStr = document.getElementById('scriptViewTime').value || '5-15';
        const likeChance = parseFloat(document.getElementById('scriptLikeChance').value);
        const [vtMin, vtMax] = viewTimeStr.split('-').map(Number);

        payload = {
            command: `Script: ${action}`,
            template: action,
            execution_mode: 'script',
            max_steps: 50,
            max_retries: 1,
            template_vars: {
                count,
                view_time_min: vtMin || 5,
                view_time_max: vtMax || 15,
                like_chance: likeChance,
            },
        };
    } else {
        const command = document.getElementById('commandInput').value;
        const template = document.getElementById('templateSelect').value || null;
        const maxSteps = parseInt(document.getElementById('maxSteps').value) || 20;
        const maxRetries = parseInt(document.getElementById('maxRetries').value) || 2;

        payload = {
            command,
            template,
            execution_mode: 'ai',
            max_steps: maxSteps,
            max_retries: maxRetries,
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
                subscribeTask(data.id);
            } else {
                toast(`❌ ${data.detail}`, 'error');
            }
        }
        refreshRunning();
        refreshStats();
    } catch (err) {
        toast('Gửi thất bại', 'error');
    } finally {
        btn.disabled = false;
        const selectedCard = document.querySelector('.action-card.selected');
        if (selectedCard) {
            const nm = selectedCard.querySelector('.action-name').textContent;
            btn.textContent = mode === 'script' ? `🔧 Chạy ${nm} — $0` : '🧠 Chạy AI Task';
        } else {
            btn.textContent = 'Chọn hành động để bắt đầu';
        }
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
    const mode = document.getElementById('executionMode').value;
    const batchMode = document.getElementById('batchMode').checked;
    const onlineDevices = devices.filter(d => d.status !== 'offline').length || 1;
    const multiplier = batchMode ? onlineDevices : 1;

    const modeEl = document.getElementById('estMode');
    const costEl = document.getElementById('estCost');

    if (!mode) {
        modeEl.textContent = '—';
        costEl.textContent = '—';
        return;
    }

    if (mode === 'script') {
        modeEl.textContent = `🔧 Script${batchMode ? ` ×${onlineDevices}` : ''}`;
        costEl.textContent = '$0.00';
        costEl.style.color = 'var(--green)';
    } else {
        const steps = parseInt(document.getElementById('maxSteps').value) || 20;
        const totalTokensIn = steps * TOKENS_PER_STEP * multiplier;
        const totalTokensOut = steps * OUTPUT_PER_STEP * multiplier;
        const costIn = (totalTokensIn / 1_000_000) * INPUT_COST_PER_M;
        const costOut = (totalTokensOut / 1_000_000) * OUTPUT_COST_PER_M;
        const totalCost = costIn + costOut;

        modeEl.textContent = `🧠 AI${batchMode ? ` ×${onlineDevices}` : ''}`;
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
        const res = await fetch(`${API}/api/tasks/running`);
        const tasks = await res.json();
        const container = document.getElementById('runningTasks');
        document.getElementById('runningCount').textContent = tasks.length;

        if (!tasks.length) {
            container.innerHTML = '<div class="empty-state"><div class="empty-icon">🎯</div><div class="empty-text">No tasks running</div></div>';
            return;
        }

        container.innerHTML = tasks.map(t => {
            const device = devices.find(d => d.id === t.device_id);
            const deviceName = device ? device.name : `Device ${t.device_id}`;
            const progress = Math.min((t.steps_taken / t.max_steps) * 100, 100);
            const cmd = t.command.length > 50 ? t.command.substring(0, 50) + '...' : t.command;
            const modeLabel = t.execution_mode === 'script' ? '🔧' : '🧠';
            return `
                <div class="task-card" id="task-${t.id}">
                    <div class="task-card-header">
                        <span class="task-id">${modeLabel} #${t.id}</span>
                        <span class="task-device">📱 ${deviceName}</span>
                    </div>
                    <div class="task-command" title="${t.command}">${cmd}</div>
                    <div class="task-progress">
                        <div class="progress-bar">
                            <div class="progress-fill" style="width: ${progress}%"></div>
                        </div>
                        <span class="task-steps">${t.steps_taken}/${t.max_steps}</span>
                        <button class="btn btn-xs btn-danger" onclick="cancelTask(${t.id})" style="margin-left:6px">✕</button>
                    </div>
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
        const filter = document.getElementById('historyFilter').value;
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

        const container = document.getElementById('taskHistory');
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
            const cmd = t.command.length > 100 ? t.command.substring(0, 100) + '…' : t.command;
            const result = t.result || '';
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
                <div class="history-card">
                    <div class="history-card-header">
                        <span class="task-id">#${t.id}</span>
                        <span class="history-status status-${t.status}">${statusIcon(t.status)}</span>
                        <span class="mode-badge ${modeClass}">${modeLabel}</span>
                        <span class="history-device">📱 ${deviceName}</span>
                    </div>
                    <div class="history-card-body">
                        ${result ? `<strong>${result}</strong>` : cmd}
                    </div>
                    <div class="history-card-footer">
                        <span class="tag">⏱ ${duration}</span>
                        <span class="tag">📊 ${t.steps_taken} steps</span>
                        <span class="tag">💰 ${cost}</span>
                        <span class="tag">🕐 ${time}</span>
                    </div>
                    ${errorHtml}
                </div>
            `;
        }).join('');
    } catch (e) { /* retry */ }
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
    const ws = new WebSocket(`ws://${location.host}/ws/tasks/${taskId}`);
    ws.onmessage = (e) => {
        const data = JSON.parse(e.data);
        if (data.event === 'step') {
            refreshRunning();
        } else if (data.event === 'completed') {
            toast(`✅ Task #${taskId} completed: ${data.reason?.substring(0, 60) || 'Done'}`, 'success');
            refreshRunning();
            refreshHistory();
            refreshDevices();
            refreshStats();
        } else if (data.event === 'failed') {
            toast(`❌ Task #${taskId} failed: ${data.error?.substring(0, 60) || 'Error'}`, 'error');
            refreshRunning();
            refreshHistory();
            refreshDevices();
            refreshStats();
        } else if (data.event === 'retry') {
            toast(`🔄 Task #${taskId} retry #${data.attempt} in ${data.delay}s`, 'info');
        }
    };
    ws.onerror = () => {};
    ws.onclose = () => {};
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
