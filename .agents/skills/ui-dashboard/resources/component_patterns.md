# Component Patterns Reference

Code snippets chuẩn cho tất cả UI components trong Android Control Dashboard.
Copy & customize khi cần tạo component mới.

---

## 1. Panel

```html
<section class="panel {name}-panel">
    <div class="panel-header">
        <h2>🔧 Title</h2>
        <!-- Optional: action button or filter -->
        <button class="btn btn-sm btn-ghost" onclick="refresh{Name}()">↻ Refresh</button>
    </div>
    <div class="panel-body scrollable" id="{name}Content">
        <div class="empty-state">No data</div>
    </div>
</section>
```

```css
.{name}-panel { grid-column: 2 / 4; } /* Adjust grid placement */
```

---

## 2. Device Card

```html
<div class="device-card" onclick="selectDevice(${d.id})" id="dev-${d.id}">
    <div class="device-header">
        <span class="device-name">${d.name}</span>
        <span class="device-status status-${d.status}">${d.status}</span>
    </div>
    <div class="device-info">
        <span>📍 ${d.ip_address}</span>
        <span>📱 ${d.device_model || '—'}</span>
        ${d.battery_level !== null ? `<span>🔋 ${d.battery_level}%</span>` : ''}
    </div>
    <div class="device-actions">
        <button class="btn btn-xs btn-primary" onclick="event.stopPropagation(); connectDevice(${d.id})">Connect</button>
        <button class="btn btn-xs btn-danger" onclick="event.stopPropagation(); deleteDevice(${d.id})">Delete</button>
    </div>
</div>
```

---

## 3. Task Card (Running)

```html
<div class="task-card" id="task-${t.id}">
    <div class="task-card-header">
        <span class="task-id">#${t.id}</span>
        <span class="task-device">${deviceName}</span>
    </div>
    <div class="task-command" title="${t.command}">${truncatedCmd}</div>
    <div class="task-progress">
        <div class="progress-bar">
            <div class="progress-fill" style="width: ${progress}%"></div>
        </div>
        <span class="task-steps">${t.steps_taken}/${t.max_steps}</span>
        <button class="btn btn-xs btn-danger" onclick="cancelTask(${t.id})" style="margin-left:8px">✕</button>
    </div>
</div>
```

---

## 4. History Item (Grid Row)

```html
<div class="history-item">
    <span class="task-id">#${t.id}</span>
    <span class="history-status status-${t.status}">${t.status}</span>
    <span class="history-command" title="${t.command}">${truncatedCmd}</span>
    <span class="history-steps">${t.steps_taken} steps · $${cost}</span>
    <span class="history-time">${time}</span>
</div>
```

```css
.history-item {
    display: grid;
    grid-template-columns: 50px 80px 1fr 100px 80px;
    gap: 12px;
    align-items: center;
    padding: 10px 0;
    border-bottom: 1px solid var(--border);
    font-size: 12px;
}
```

---

## 5. Form Controls

```html
<!-- Select -->
<div class="form-group">
    <label>Label</label>
    <select id="exampleSelect" required>
        <option value="">Select...</option>
    </select>
</div>

<!-- Text Input -->
<div class="form-group">
    <label>Label</label>
    <input type="number" id="exampleInput" value="20" min="1" max="50">
</div>

<!-- Textarea -->
<div class="form-group">
    <label>Label</label>
    <textarea id="exampleTextarea" rows="3" placeholder="Enter command..." required></textarea>
</div>

<!-- Checkbox -->
<div class="form-group">
    <label class="checkbox-label">
        <input type="checkbox" id="exampleCheck" onchange="toggleExample()">
        <span>Enable feature</span>
    </label>
</div>

<!-- Two-column row -->
<div class="form-row">
    <div class="form-group half">
        <label>Left</label>
        <input type="number" id="left" value="20">
    </div>
    <div class="form-group half">
        <label>Right</label>
        <input type="number" id="right" value="2">
    </div>
</div>
```

---

## 6. Buttons

```html
<!-- Primary (gradient indigo) -->
<button class="btn btn-primary">▶ Action</button>
<button class="btn btn-primary btn-block">Full Width</button>

<!-- Danger (red outline) -->
<button class="btn btn-danger">Delete</button>
<button class="btn btn-xs btn-danger">✕</button>

<!-- Ghost (transparent outline) -->
<button class="btn btn-ghost">Cancel</button>
<button class="btn btn-sm btn-ghost">↻ Refresh</button>
```

---

## 7. Status Badges

```html
<span class="device-status status-online">online</span>
<span class="device-status status-busy">busy</span>
<span class="device-status status-offline">offline</span>

<span class="history-status status-completed">completed</span>
<span class="history-status status-failed">failed</span>
<span class="history-status status-running">running</span>
<span class="history-status status-pending">pending</span>
<span class="history-status status-cancelled">cancelled</span>
```

---

## 8. Toast Notification

```javascript
// Usage
toast('✅ Action completed', 'success');
toast('❌ Something failed', 'error');
toast('ℹ️ Info message', 'info');

// Implementation (already in app.js)
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
```

---

## 9. Progress Bar

```html
<div class="progress-bar">
    <div class="progress-fill" style="width: ${percent}%"></div>
</div>
```

```css
.progress-bar {
    flex: 1; height: 4px;
    background: var(--bg-input);
    border-radius: 2px; overflow: hidden;
}
.progress-fill {
    height: 100%;
    background: linear-gradient(90deg, var(--accent), var(--accent-light));
    border-radius: 2px;
    transition: width 0.5s ease;
}
```

---

## 10. Modal / Dialog (Template)

Chưa có trong code hiện tại — dùng template này khi cần:

```html
<!-- Add to index.html before </body> -->
<div class="modal-overlay" id="exampleModal" style="display:none">
    <div class="modal">
        <div class="modal-header">
            <h3>Modal Title</h3>
            <button class="btn btn-xs btn-ghost" onclick="closeModal('exampleModal')">✕</button>
        </div>
        <div class="modal-body">
            <!-- Content here -->
        </div>
        <div class="modal-footer">
            <button class="btn btn-ghost" onclick="closeModal('exampleModal')">Cancel</button>
            <button class="btn btn-primary" onclick="confirmAction()">Confirm</button>
        </div>
    </div>
</div>
```

```css
/* Add to style.css */
.modal-overlay {
    position: fixed; inset: 0;
    background: rgba(0, 0, 0, 0.6);
    backdrop-filter: blur(4px);
    display: flex; align-items: center; justify-content: center;
    z-index: 300;
    animation: fadeIn 0.2s ease;
}
.modal {
    background: var(--bg-panel);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    width: 90%; max-width: 480px;
    animation: slideUp 0.3s ease;
}
.modal-header {
    display: flex; justify-content: space-between; align-items: center;
    padding: 16px 20px;
    border-bottom: 1px solid var(--border);
}
.modal-header h3 { font-size: 15px; font-weight: 600; }
.modal-body { padding: 20px; }
.modal-footer {
    display: flex; justify-content: flex-end; gap: 8px;
    padding: 14px 20px;
    border-top: 1px solid var(--border);
}
@keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
@keyframes slideUp {
    from { opacity: 0; transform: translateY(16px); }
    to { opacity: 1; transform: translateY(0); }
}
```

```javascript
// Add to app.js
function openModal(id) { document.getElementById(id).style.display = 'flex'; }
function closeModal(id) { document.getElementById(id).style.display = 'none'; }
```

---

## 11. Cost Estimation Box

```html
<div class="cost-estimate" id="costEstimate">
    <div class="cost-header">
        <span class="cost-icon">💰</span>
        <span class="cost-title">Estimated Cost</span>
    </div>
    <div class="cost-details">
        <div class="cost-row">
            <span>Tokens (max)</span>
            <span id="estTokens">13,600</span>
        </div>
        <div class="cost-row">
            <span>Est. Cost</span>
            <span id="estCost" class="cost-value">$0.038</span>
        </div>
        <div class="cost-note">~680 tokens/step × GPT-4o ($2.50/1M in + $10/1M out)</div>
    </div>
</div>
```

---

## 12. Empty State

```html
<div class="empty-state">No items to display</div>
<div class="loading">Loading data...</div>
```
