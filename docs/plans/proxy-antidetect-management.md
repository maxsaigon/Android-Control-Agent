# Proxy & Antidetect Management — 📋 PLANNED

**Created**: 2026-03-22  
**Last Updated**: 2026-03-22  
**Priority**: High — Cần thiết để tránh ban account do IP trùng lặp trong LAN

---

## Mục tiêu

Xây dựng hệ thống quản lý proxy và antidetect cho từng Android device trong môi trường LAN, nhằm:

1. **Cách ly IP**: Mỗi device có IP riêng biệt, không trùng lặp nhau
2. **Bypass detection**: Vượt qua hệ thống phát hiện bot/spam của các platform
3. **Ổn định LAN**: Duy trì kết nối ADB qua WiFi trong khi proxy traffic đi qua external endpoint
4. **Quản lý tập trung**: Dashboard để gán, kiểm tra, và rotate proxy cho từng device

---

## Phân tích vấn đề hiện tại

### Vấn đề IP sharing trong LAN
Khi nhiều device cùng kết nối WiFi nhà/office, chúng **chia sẻ 1 IP public duy nhất** (NAT). Các platform phát hiện:
- Nhiều account hoạt động từ cùng 1 IP → flag là farm/spam
- Cùng User-Agent pattern + cùng IP → confidence cao hơn khi ban

### Các lớp detection của platform
| Layer | Signal | Mức độ nguy hiểm |
|-------|--------|-----------------|
| **Network** | IP address, ASN, datacenter vs residential | 🔴 Cao |
| **Device** | Android ID, IMEI, Device Model, Build fingerprint | 🔴 Cao |
| **Browser/App** | User-Agent, WebView fingerprint, WebRTC IP leak | 🟠 Trung bình |
| **Behavior** | Thời gian online, tốc độ action, scroll pattern | 🟠 Trung bình |
| **Account** | Email, phone number, SIM card | 🟡 Thấp (đã kiểm soát) |

---

## Kiến trúc giải pháp (Multi-Layer Antidetect)

```
┌─────────────────────────────────────────────────────────────────┐
│                        Android Control Server                     │
│                         (LAN: 192.168.x.x)                       │
│                                                                   │
│  ┌─────────────┐    ┌──────────────────┐    ┌─────────────────┐ │
│  │ Proxy Pool  │    │  Proxy Manager   │    │  Fingerprint    │ │
│  │  Database   │───▶│    Service       │───▶│   Spoofer       │ │
│  └─────────────┘    └──────────────────┘    └─────────────────┘ │
│                              │                        │           │
└──────────────────────────────┼────────────────────────┼──────────┘
                               │ ADB over WiFi          │ ADB shell
                               ▼                        ▼
        ┌──────────────────────────────────────────────────────┐
        │                 Android Devices (LAN)                 │
        │                                                       │
        │  Device 1          Device 2         Device 3         │
        │  ┌──────────┐     ┌──────────┐     ┌──────────┐     │
        │  │ VPN App  │     │ VPN App  │     │ VPN App  │     │
        │  │ Proxy A  │     │ Proxy B  │     │ Proxy C  │     │
        │  │ IP: 1.x  │     │ IP: 2.x  │     │ IP: 3.x  │     │
        │  └──────────┘     └──────────┘     └──────────┘     │
        │                                                       │
        │  Traffic: TikTok/Instagram/... → Proxy → Internet   │
        │  ADB Control: Server → WiFi → Device (không đổi)    │
        └──────────────────────────────────────────────────────┘
```

---

## Implementation Plan

### Phase 1: Database Models & API cơ bản

#### 1.1 Proxy Model (models.py)

```python
class ProxyType(str, Enum):
    HTTP = "http"
    HTTPS = "https"
    SOCKS5 = "socks5"

class ProxyStatus(str, Enum):
    ACTIVE = "active"
    TESTING = "testing"
    FAILED = "failed"
    EXPIRED = "expired"

class Proxy(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str                          # "Proxy VN #1"
    host: str                          # "123.45.67.89" hoặc "proxy.provider.com"
    port: int                          # 8080, 1080, etc.
    proxy_type: ProxyType = ProxyType.HTTP
    username: Optional[str] = None
    password: Optional[str] = None
    country: Optional[str] = None      # "VN", "US", etc.
    city: Optional[str] = None
    provider: Optional[str] = None     # "Brightdata", "Webshare", etc.
    is_residential: bool = False       # residential vs datacenter
    is_mobile: bool = False            # mobile proxy (tốt nhất)
    status: ProxyStatus = ProxyStatus.ACTIVE
    last_checked: Optional[datetime] = None
    latency_ms: Optional[int] = None   # ping latency
    current_ip: Optional[str] = None   # IP sau khi connect
    
    # Assignment tracking
    assigned_device_id: Optional[int] = Field(default=None, foreign_key="device.id")
    assigned_at: Optional[datetime] = None
    
    # Rotation config
    rotation_interval_min: int = 30    # Rotate mỗi X phút
    last_rotated: Optional[datetime] = None
    
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    notes: Optional[str] = None
```

#### 1.2 DeviceFingerprintProfile Model (models.py)

```python
class DeviceFingerprintProfile(SQLModel, table=True):
    """Lưu profile giả mạo cho từng device."""
    
    id: Optional[int] = Field(default=None, primary_key=True)
    device_id: int = Field(foreign_key="device.id", unique=True)
    
    # Device identity spoofing
    fake_android_id: Optional[str] = None    # 16-char hex
    fake_device_model: Optional[str] = None  # "Pixel 7 Pro"
    fake_manufacturer: Optional[str] = None  # "Google"
    fake_brand: Optional[str] = None         # "google"
    fake_build_fingerprint: Optional[str] = None
    fake_serial: Optional[str] = None
    
    # Network identity
    fake_timezone: Optional[str] = None     # "Asia/Ho_Chi_Minh"
    fake_locale: Optional[str] = None       # "vi_VN"
    
    # Tracking
    applied_at: Optional[datetime] = None
    is_applied: bool = False
    
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    notes: Optional[str] = None
```

---

### Phase 2: Proxy Application Methods

#### 2.1 Method A: ADB Global HTTP Proxy (Không cần root, nhưng hạn chế)

```python
# Áp dụng system-wide HTTP proxy qua ADB settings
adb shell settings put global http_proxy {host}:{port}

# Xóa proxy:
adb shell settings delete global http_proxy

# Giới hạn: Chỉ hoạt động với apps biết đọc system proxy
# TikTok/Instagram đôi khi bypass system proxy → dùng Method B
```

#### 2.2 Method B: VPN App Automation (Khuyến nghị — No root)

**Cách hoạt động:**
- Cài sẵn **Drony** hoặc **SocksDroid** trên device
- Server tự động config proxy mới qua ADB intent/adb shell
- App tạo local VPN tunnel, route TẤT CẢ traffic qua proxy
- ADB connection vẫn qua WiFi LAN (không bị ảnh hưởng)

```python
# Cài Drony APK qua ADB
adb install drony.apk

# Gửi config proxy qua ADB broadcast (nếu app support)
adb shell am broadcast -a org.sandrob.drony.CONFIGURE \
    --es proxy_host "proxy.example.com" \
    --es proxy_port "1080" \
    --es proxy_type "SOCKS5"

# Start proxy service
adb shell am start -n org.sandrob.drony/.activity.ListActivity
```

#### 2.3 Method C: Transparent Proxy via iptables (Root required — Tốt nhất)

```bash
# Nếu device có root access, dùng redsocks + iptables
# Cài redsocks binary qua ADB
adb push redsocks /system/bin/redsocks

# Config redsocks
redsocks {
    local_ip = 127.0.0.1;
    local_port = 12345;
    ip = proxy.host.com;
    port = 1080;
    type = socks5;
    login = user;
    password = pass;
}

# Redirect tất cả traffic
iptables -t nat -A OUTPUT -p tcp -j REDIRECT --to-port 12345
```

**Khuyến nghị thực tế cho project này:**
> Method B (VPN App via ADB) là tốt nhất vì devices **không cần root**, dễ scale, và hoạt động với mọi app kể cả TikTok.

---

### Phase 3: Fingerprint Spoofing (Rooted devices)

#### 3.1 Thay đổi Android ID (không cần root - chỉ cần ADB)

```bash
# Android ID có thể thay đổi qua content provider (API < 26)
adb shell content insert \
    --uri content://settings/secure \
    --bind name:s:android_id \
    --bind value:s:$(openssl rand -hex 8)

# Android 8+: Cần root hoặc factory reset
```

#### 3.2 Magisk + LSPosed Modules (Rooted — Toàn diện nhất)

Nếu devices được root với Magisk:

| Module | Chức năng |
|--------|-----------|
| **DeviceSpoofLab** | Spoof build fingerprint, model, manufacturer, serial |
| **Android Faker** | Spoof IMEI, Android ID, MAC address |
| **Device Emulator** | Spoof GSF ID, Advertising ID, MediaDrm ID |
| **MagiskHide Props** | Fake device thành Pixel/Samsung để pass SafetyNet |

#### 3.3 Build.prop Modifications (Root)

```bash
# Thay đổi device model (cần reboot)
adb shell "echo 'ro.product.model=Pixel 7 Pro' >> /system/build.prop"
adb shell "echo 'ro.product.manufacturer=Google' >> /system/build.prop"
adb shell "echo 'ro.product.brand=google' >> /system/build.prop"
```

---

### Phase 4: Backend Service Implementation

#### File Structure mới sẽ thêm:

```
app/
├── models.py                    # [MODIFY] Thêm Proxy, DeviceFingerprintProfile
├── routers/
│   ├── proxies.py               # [NEW] Proxy CRUD + assignment API
│   └── fingerprint.py           # [NEW] Fingerprint profile API
├── services/
│   ├── proxy_service.py         # [NEW] Core proxy management logic
│   │   ├── ProxyHealthChecker   # Ping proxy, verify IP
│   │   ├── ProxyAssigner        # Assign proxy to device
│   │   ├── ProxyRotator         # Auto-rotate theo schedule
│   │   └── ProxyApplier         # Apply proxy via ADB
│   └── fingerprint_service.py   # [NEW] Fingerprint profile management
│       ├── FingerprintProfileGen # Generate fake device profile
│       └── FingerprintApplier   # Apply via ADB commands
└── main.py                      # [MODIFY] Register new routers
```

#### Proxy Service — Core Methods:

```python
class ProxyService:
    async def health_check(proxy: Proxy) -> ProxyCheckResult:
        """Ping proxy, đo latency, lấy current IP."""
    
    async def apply_proxy_to_device(device_id: int, proxy_id: int) -> bool:
        """Apply proxy lên device qua ADB."""
        # 1. Set global http_proxy
        # 2. Launch VPN app với proxy config
        # 3. Verify IP đã thay đổi
    
    async def verify_device_ip(device_id: int) -> str:
        """Kiểm tra IP hiện tại của device (qua curl ifconfig.me)."""
        # adb shell curl -s ifconfig.me
    
    async def rotate_all_assigned(self) -> dict:
        """Rotate tất cả proxy đã được gán, chạy định kỳ."""
    
    async def assign_proxy_to_device(device_id: int, proxy_id: int):
        """Gán proxy cho device trong DB + apply ngay."""
    
    async def get_available_proxy(country: str = None) -> Optional[Proxy]:
        """Tìm proxy chưa được gán hoặc đã cũ nhất."""
```

#### API Endpoints:

```
GET    /api/proxies/              — List all proxies
POST   /api/proxies/              — Add new proxy
PUT    /api/proxies/{id}          — Update proxy
DELETE /api/proxies/{id}          — Remove proxy

POST   /api/proxies/{id}/test     — Health check + verify IP
POST   /api/proxies/{id}/assign   — Assign proxy to device
POST   /api/proxies/{id}/apply    — Apply proxy on device via ADB
POST   /api/proxies/auto-assign   — Auto-assign best proxy to devices
POST   /api/proxies/rotate-all    — Rotate all assigned proxies

GET    /api/devices/{id}/proxy    — Get current proxy of device
DELETE /api/devices/{id}/proxy    — Remove proxy from device
GET    /api/devices/{id}/ip       — Check current public IP

GET    /api/fingerprint/{device_id}       — Get fingerprint profile
POST   /api/fingerprint/{device_id}       — Create/update profile
POST   /api/fingerprint/{device_id}/apply — Apply fingerprint via ADB
POST   /api/fingerprint/generate-all      — Generate profiles for all devices
```

---

### Phase 5: Dashboard UI

#### Tab "Proxy & Antidetect" trên Dashboard:

**Khu vực 1: Proxy Pool**
- Table: Proxy ID, Host:Port, Type, Country, Status, Latency, Assigned To
- Action: Add/Edit/Delete proxy
- Action: Test proxy (verify IP + latency)
- Action: Import từ file CSV

**Khu vực 2: Device Proxy Map**
- Grid hiển thị từng device với current proxy và IP
- Button: Assign proxy, Remove proxy, Verify IP
- Status indicator: 🟢 Proxy active / 🔴 No proxy / 🟡 Checking

**Khu vực 3: Fingerprint Profiles**
- Table: Device, Fake Model, Android ID, Applied status
- Action: Generate random profile, Apply profile

**Khu vực 4: Proxy Health Monitor**
- Real-time status của tất cả proxies
- Last check time, success rate, avg latency

---

### Phase 6: Proxy Provider Integration

Hỗ trợ import proxy từ các provider phổ biến:

| Provider | Type | Giá | Phù hợp |
|----------|------|-----|---------|
| **Bright Data** | Residential/Mobile | $$ | TikTok, Instagram |
| **Webshare** | Residential | $ | YouTube, Facebook |
| **Oxylabs** | Mobile | $$$ | TikTok (tốt nhất) |
| **Smartproxy** | Residential | $$ | Đa dụng |
| **ProxyEmpire** | Mobile/ISP | $$ | Social media |

---

## Quy trình vận hành

### Setup ban đầu:
1. Admin thêm proxy vào pool (nhập tay hoặc import CSV)
2. Hệ thống auto-verify từng proxy (health check)
3. Admin nhấn "Auto-Assign" → hệ thống phân phối proxy đều cho các devices
4. Hệ thống apply proxy lên devices qua ADB (tự động)
5. Hệ thống verify IP của từng device sau khi apply

### Vận hành hàng ngày:
- Scheduler auto-rotate proxy mỗi 30-60 phút (configurable)
- Alert khi proxy fail hoặc IP lộ
- Health check tự động mỗi 5 phút

### Trước khi chạy task:
- ProxyApplier verify proxy vẫn active
- Nếu proxy fail → auto-swap sang proxy khác
- Log IP thực tế tại thời điểm task bắt đầu

---

## Rủi ro & Biện pháp giảm thiểu

| Rủi ro | Giảm thiểu |
|--------|------------|
| Proxy chất lượng thấp bị platform chặn | Dùng mobile/residential proxy uy tín |
| VPN app không apply được | Fallback về ADB http_proxy |
| App bỏ qua system proxy | Dùng transparent proxy (root) |
| Device mất kết nối ADB khi đổi proxy | ADB đi qua WiFi LAN riêng, không qua proxy |
| Platform detect device fingerprint trùng | Fingerprint profile unique cho mỗi device |

---

## Yêu cầu kỹ thuật

- **Không cần root** cho Method A & B
- **Cần root** cho Method C (iptables) và fingerprint spoofing toàn diện
- **VPN App** cần cài sẵn: Drony hoặc SocksDroid APK
- **Python dependencies**: `aiohttp`, `httpx` (health check)
- **Database**: Thêm 2 bảng: `proxy`, `devicefingerprintprofile`

---

## Implementation Checklist

- [ ] Phase 1: Database models (Proxy, DeviceFingerprintProfile)
- [ ] Phase 2: Proxy CRUD router (proxies.py)
- [ ] Phase 3: ProxyService (health check, assign, apply, verify)
- [ ] Phase 4: FingerprintService (generate, apply)
- [ ] Phase 5: API endpoints integration (main.py)
- [ ] Phase 6: Dashboard UI tab mới
- [ ] Phase 7: Auto-rotation scheduler
- [ ] Phase 8: Integration với task execution (auto-verify proxy trước task)
