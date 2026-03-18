---
name: ui-dashboard
description: Sub-agent chuyên xử lý UI và Dashboard cho Android Control System. Cung cấp design system, architecture guide, coding standards, và component patterns.
---

# UI/Dashboard Sub-Agent

Bạn là sub-agent chuyên trách **toàn bộ phần giao diện web (Dashboard)** cho dự án Android Control System. Mọi thay đổi liên quan đến HTML, CSS, JavaScript của dashboard đều thuộc phạm vi của bạn.

---

## 1. Architecture Overview

### File Structure
```
app/static/
├── index.html    # Single-page dashboard (155 lines)
├── style.css     # Premium dark theme (604 lines)
└── app.js        # Client-side logic (384 lines)

app/
├── main.py       # FastAPI app, serves /dashboard and /static/*
├── models.py     # SQLModel: Device, Task, TaskLog + Pydantic schemas
├── routers/
│   ├── devices.py  # /api/devices/* endpoints
│   ├── tasks.py    # /api/tasks/* endpoints
│   └── ws.py       # /ws/tasks/{task_id} WebSocket
└── services/       # Business logic (adb_agent, task_queue, device_manager, etc.)
```

### How Dashboard is Served
```python
# app/main.py
app.mount("/static", StaticFiles(directory="app/static"), name="static")

@app.get("/dashboard")
def dashboard():
    return FileResponse("app/static/index.html")
```

### API Endpoints Used by Dashboard
| Method   | Endpoint                    | Purpose                    | Used in          |
|----------|-----------------------------|----------------------------|------------------|
| `GET`    | `/api/devices`              | List all devices           | `refreshDevices()` |
| `POST`   | `/api/devices`              | Register new device        | —                |
| `POST`   | `/api/devices/{id}/connect` | Connect via ADB            | `connectDevice()` |
| `POST`   | `/api/devices/{id}/disconnect` | Disconnect              | `disconnectDevice()` |
| `DELETE` | `/api/devices/{id}`         | Delete device              | `deleteDevice()` |
| `GET`    | `/api/templates`            | List task templates        | `loadTemplates()` |
| `POST`   | `/api/tasks`                | Submit single task         | `submitTask()` |
| `POST`   | `/api/tasks/batch`          | Submit to multiple devices | `submitTask()` |
| `GET`    | `/api/tasks?limit=&status=` | Task history               | `refreshHistory()` |
| `GET`    | `/api/tasks/running`        | Running tasks              | `refreshRunning()` |
| `GET`    | `/api/tasks/queue-status`   | Queue status               | `refreshQueueStatus()` |
| `POST`   | `/api/tasks/{id}/cancel`    | Cancel running task        | `cancelTask()` |
| `WS`     | `/ws/tasks/{task_id}`       | Real-time updates          | `subscribeTask()` |

---

## 2. Design System

### Color Palette (CSS Variables)
```css
/* Backgrounds */
--bg-primary: #0f1117;     /* Page background */
--bg-secondary: #161822;   /* Header background */
--bg-panel: #1a1d2e;       /* Panel background */
--bg-card: #222539;        /* Card background */
--bg-hover: #2a2e45;       /* Hover state */
--bg-input: #1e2134;       /* Input fields */

/* Text */
--text-primary: #e8eaf0;   /* Main text */
--text-secondary: #8b90a5; /* Secondary text */
--text-muted: #5a5f78;     /* Muted/disabled text */

/* Accent (Indigo) */
--accent: #6366f1;
--accent-light: #818cf8;
--accent-glow: rgba(99, 102, 241, 0.15);
--accent-hover: #4f46e5;

/* Status Colors */
--green: #22c55e;    /* Online, Completed */
--red: #ef4444;      /* Offline, Failed, Danger */
--yellow: #eab308;   /* Busy, Warning, Cost */
--blue: #3b82f6;     /* Info, Running */

/* Each status color has a semi-transparent background variant */
--green-bg: rgba(34, 197, 94, 0.1);
--red-bg: rgba(239, 68, 68, 0.1);
--yellow-bg: rgba(234, 179, 8, 0.1);
--blue-bg: rgba(59, 130, 246, 0.1);

/* Shared */
--border: #2a2d40;
--radius: 12px;
--radius-sm: 8px;
--transition: 0.2s ease;
```

### Typography
- **Font**: `'Inter'` from Google Fonts (weights: 300, 400, 500, 600, 700)
- **Fallback**: `-apple-system, sans-serif`
- **Scale**: 10px (notes) → 11px (badges/labels) → 12px (body/secondary) → 13px (body/primary) → 14px (panel headers/buttons) → 18px (logo)
- **Labels**: `text-transform: uppercase; letter-spacing: 0.5px; font-weight: 500`

### Layout
- **Grid**: `grid-template-columns: 280px 1fr 1fr` (3-column layout)
- **Devices panel**: spans full height (left sidebar)
- **Submit panel**: column 2, row 1
- **Running panel**: column 3, row 1
- **History panel**: columns 2-3, row 2
- **Responsive**: 2-column at ≤1100px, 1-column at ≤700px

### Animations
- `pulse` — Green dot heartbeat (server status)
- `slideIn` — Task card entrance animation
- `progressPulse` — Progress bar breathing
- `toastIn` — Toast notification slide-in from right

---

## 3. Coding Standards

### HTML
- Sử dụng **semantic elements**: `<header>`, `<main>`, `<section>`
- Mỗi panel là `<section class="panel {name}-panel">`
- Tất cả interactive elements phải có **unique IDs**
- Inline event handlers OK cho simplicity: `onclick="functionName()"`

### CSS
- **BEM-like naming**: `.panel-header`, `.device-card`, `.task-progress`
- **Status classes**: `.status-online`, `.status-busy`, `.status-offline`, `.status-completed`, `.status-failed`, `.status-running`, `.status-pending`, `.status-cancelled`
- **Button variants**: `.btn` + `.btn-primary` / `.btn-danger` / `.btn-ghost` + size `.btn-sm` / `.btn-xs` / `.btn-block`
- Luôn dùng **CSS variables** cho colors, không hardcode
- Transitions: dùng `var(--transition)` cho consistency

### JavaScript
- **No frameworks** — Vanilla JS only
- **API calls**: `fetch()` with `${API}/api/...` pattern (API = '' for same origin)
- **Dynamic HTML**: Template literals with backticks
- **Auto-refresh**: `setInterval` — 3s cho devices/running, 10s cho history
- **Error handling**: try/catch với toast notifications
- **WebSocket**: Subscribe per task, auto-close on completion

### Toast Notifications
```javascript
toast(message, type);  // type: 'info' | 'success' | 'error'
```

### Cost Estimation Formula
```javascript
const TOKENS_PER_STEP = 680;
const OUTPUT_PER_STEP = 20;
const INPUT_COST_PER_M = 2.50;   // GPT-4o
const OUTPUT_COST_PER_M = 10.00;

const totalCost = (steps * TOKENS_PER_STEP / 1_000_000) * INPUT_COST_PER_M
                + (steps * OUTPUT_PER_STEP / 1_000_000) * OUTPUT_COST_PER_M;
```

---

## 4. Common Tasks

### 4.1 Thêm Panel Mới

1. **HTML** (`index.html`): Thêm `<section>` mới trong `<main class="grid">`
```html
<section class="panel {name}-panel">
    <div class="panel-header">
        <h2>🔧 Panel Title</h2>
    </div>
    <div class="panel-body scrollable" id="{name}Content">
        <div class="empty-state">No data</div>
    </div>
</section>
```

2. **CSS** (`style.css`): Thêm grid placement
```css
.{name}-panel { grid-column: 2 / 4; }
```

3. **JS** (`app.js`): Thêm refresh function
```javascript
async function refresh{Name}() {
    try {
        const res = await fetch(`${API}/api/{endpoint}`);
        const data = await res.json();
        const container = document.getElementById('{name}Content');
        // Render data...
    } catch (e) { /* retry */ }
}
```

4. Gọi trong `init()` và thêm vào `setInterval` nếu cần auto-refresh.

### 4.2 Thêm API Endpoint Phục Vụ UI

1. Thêm route trong `app/routers/` hoặc `app/main.py`
2. Nếu cần model mới → thêm Pydantic schema trong `app/models.py`
3. Update bảng API endpoints trong SKILL.md này

### 4.3 Tạo Modal/Dialog

Xem component patterns trong `resources/component_patterns.md` → mục "Modal Pattern".

### 4.4 Thêm Theme Toggle (Dark/Light)

1. Tạo thêm một bộ CSS variables với prefix `[data-theme="light"]`
2. Thêm toggle button vào header
3. Lưu preference vào `localStorage`

---

## 5. Quality Checklist

Trước khi hoàn thành bất kỳ thay đổi UI nào, kiểm tra:

- [ ] Tất cả element IDs là unique
- [ ] CSS classes mới tuân theo naming convention
- [ ] Responsive hoạt động ở cả 3 breakpoints (desktop, tablet ≤1100px, mobile ≤700px)
- [ ] Fetch calls có error handling + toast
- [ ] Không hardcode colors — dùng CSS variables
- [ ] Animations smooth, không janky
- [ ] Empty states hiển thị đúng khi không có data
- [ ] Chạy `bash .agents/skills/ui-dashboard/scripts/validate_ui.sh` để kiểm tra

---

## 6. Backend Data Models Reference

### Device
| Field           | Type     | Notes                         |
|-----------------|----------|-------------------------------|
| id              | int      | Primary key                   |
| name            | str      | Display name                  |
| ip_address      | str      | ADB TCP/IP address            |
| adb_port        | int      | Default: 5555                 |
| status          | enum     | online / offline / busy       |
| last_seen       | datetime | Last heartbeat                |
| android_version | str?     | e.g., "13"                    |
| device_model    | str?     | e.g., "Pixel 7"              |
| battery_level   | int?     | 0-100                        |

### Task
| Field          | Type     | Notes                                    |
|----------------|----------|------------------------------------------|
| id             | int      | Primary key                              |
| device_id      | int      | FK → Device                              |
| command        | str      | Natural language command                  |
| template       | str?     | Template name if used                     |
| execution_mode | str      | "auto" / "script" / "ai"                |
| max_steps      | int      | Default: 20                              |
| status         | enum     | pending/running/completed/failed/cancelled |
| result         | str?     | AI completion summary                     |
| steps_taken    | int      | Actual steps executed                     |
| error          | str?     | Error message if failed                   |
| retry_count    | int      | Current retry attempt                     |
| max_retries    | int      | Max retries allowed                       |
