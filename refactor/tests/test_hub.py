import asyncio

from android_control.hub import DeviceHub


class FakeWebSocket:
    def __init__(self):
        self.sent = []

    async def send_json(self, payload):
        self.sent.append(payload)


def test_hub_correlates_command_response():
    async def exercise():
        hub = DeviceHub(timeout=1)
        connection = hub.register(7, FakeWebSocket())

        task = asyncio.create_task(connection.command("tap", {"x": 1, "y": 2}))
        await asyncio.sleep(0)
        command = connection.websocket.sent[0]
        connection.receive({"id": command["id"], "status": "ok", "result": "done"})

        assert await task == "done"

    asyncio.run(exercise())


def test_reconnect_guard_does_not_remove_new_session():
    hub = DeviceHub()
    old = hub.register(7, FakeWebSocket())
    new = hub.register(7, FakeWebSocket())

    assert hub.unregister(7, old.session_id) is False
    assert hub.get(7) is new
    assert hub.unregister(7, new.session_id) is True
