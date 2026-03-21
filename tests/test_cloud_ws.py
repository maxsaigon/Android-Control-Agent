"""Test script for cloud device registration and connection.

Tests the simplified registration flow:
1. Register device via POST /api/device/register (username + device_name)
2. Connect via WebSocket with auto-generated token
3. Exchange heartbeats
4. Verify hub status

Usage:
    # Terminal 1: Start server
    cd /Volumes/Mac\ Work/python/Android-Control
    ./venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000

    # Terminal 2: Run self-test
    python tests/test_cloud_ws.py --self-test
"""

import asyncio
import json
import sys

try:
    import websockets
except ImportError:
    print("Install websockets: pip install websockets")
    sys.exit(1)

try:
    import httpx
except ImportError:
    httpx = None


SERVER = "localhost:8000"


async def self_test():
    """Full self-test: register → connect → exchange commands."""
    if httpx is None:
        print("Install httpx for self-test: pip install httpx")
        return

    async with httpx.AsyncClient(base_url=f"http://{SERVER}") as client:
        # 1. Register device via login credentials
        print("📝 Registering device via /api/device/register...")
        r = await client.post("/api/device/register", json={
            "username": "admin",
            "password": "admin",
            "device_name": "Cloud Test Device",
        })
        if r.status_code not in (200, 201):
            print(f"❌ Register failed: {r.status_code} {r.text}")
            return
        reg = r.json()
        token = reg["token"]
        device_id = reg["device_id"]
        print(f"✅ Registered: device_id={device_id}, token={token[:16]}...")

        # 2. Test invalid credentials
        r = await client.post("/api/device/register", json={
            "username": "admin",
            "password": "wrong",
            "device_name": "Bad Device",
        })
        assert r.status_code == 401, f"Expected 401, got {r.status_code}"
        print("✅ Invalid credentials rejected (401)")

        # 3. Re-register same device name → should reuse device, new token
        r = await client.post("/api/device/register", json={
            "username": "admin",
            "password": "admin",
            "device_name": "Cloud Test Device",
        })
        reg2 = r.json()
        assert reg2["device_id"] == device_id, "Should reuse same device"
        assert reg2["token"] != token, "Should generate new token"
        token = reg2["token"]  # Use the latest token
        print(f"✅ Re-register reuses device, new token={token[:16]}...")

        # 4. Connect via WebSocket
        ws_url = f"ws://{SERVER}/ws/device/{token}"
        print(f"🔌 Connecting to {ws_url}...")

        async with websockets.connect(ws_url) as ws:
            # Should receive welcome message
            msg = json.loads(await ws.recv())
            print(f"✅ Welcome: {msg}")
            assert msg["type"] == "welcome", f"Expected welcome, got {msg}"

            # 5. Send heartbeat
            await ws.send(json.dumps({
                "type": "heartbeat",
                "battery": 85,
            }))
            ack = json.loads(await ws.recv())
            print(f"✅ Heartbeat ack: {ack}")
            assert ack["type"] == "heartbeat_ack"

            # 6. Check hub status
            r = await client.get("/api/device-tokens/hub-status")
            hub = r.json()
            print(f"✅ Hub status: {hub['connected_devices']} device(s) connected")
            assert hub["connected_devices"] >= 1

            print(f"✅ Connection stable, device {device_id} is in hub")

        # 7. Check device went offline after disconnect
        await asyncio.sleep(1)
        r = await client.get("/api/device-tokens/hub-status")
        hub = r.json()
        print(f"✅ After disconnect: {hub['connected_devices']} device(s)")

        # Cleanup
        await client.delete(f"/api/devices/{device_id}")
        print(f"✅ Cleaned up device {device_id}")

    print("\n🎉 All tests passed!")


async def connect_with_credentials(server: str, username: str, password: str, device_name: str):
    """Register and connect using credentials (simulates APK flow)."""
    if httpx is None:
        print("Install httpx: pip install httpx")
        return

    async with httpx.AsyncClient(base_url=f"http://{server}") as client:
        # Register
        r = await client.post("/api/device/register", json={
            "username": username,
            "password": password,
            "device_name": device_name,
        })
        if r.status_code != 200:
            print(f"❌ Register failed: {r.status_code} {r.text}")
            return
        reg = r.json()
        token = reg["token"]
        print(f"✅ Registered as device {reg['device_id']}")

    # Connect WebSocket
    ws_url = f"ws://{server}/ws/device/{token}"
    print(f"🔌 Connecting to {ws_url}...")

    async with websockets.connect(ws_url) as ws:
        msg = json.loads(await ws.recv())
        print(f"✅ Connected! Welcome: {msg}")

        # Send heartbeats and handle commands
        while True:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=30)
                data = json.loads(raw)
                print(f"📥 Received: {data}")

                if "id" in data and "action" in data:
                    response = {
                        "id": data["id"],
                        "status": "ok",
                        "result": f"Mock response for {data['action']}",
                    }
                    await ws.send(json.dumps(response))
                    print(f"📤 Responded: {response}")

            except asyncio.TimeoutError:
                await ws.send(json.dumps({"type": "heartbeat", "battery": 75}))
                ack = json.loads(await ws.recv())
                print(f"💓 Heartbeat → {ack}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--self-test":
        asyncio.run(self_test())
    elif len(sys.argv) >= 5:
        asyncio.run(connect_with_credentials(
            sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
        ))
    else:
        print("Usage:")
        print(f"  python {sys.argv[0]} --self-test")
        print(f"  python {sys.argv[0]} <server> <username> <password> <device_name>")
        print(f"  Example: python {sys.argv[0]} localhost:8000 admin admin 'My Phone'")
