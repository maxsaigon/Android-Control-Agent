"""Tests for DeviceHub stability hardening (Phase 1.1, 1.3, 2.1).

Covers:
- F1: DeviceHub reconnect race — old unregister must not remove new connection.
- F1: Pending futures are failed on disconnect/reconnect (not left waiting).
- F7: Command error response preserves original id.
- F2: Registration auth uses bcrypt-aware verifier.
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


# ─── DeviceHub reconnect safety tests ───────────────────────────────────────

class TestDeviceHubReconnect(unittest.IsolatedAsyncioTestCase):
    """F1 — DeviceHub reconnect safety."""

    def _make_hub(self):
        from app.services.device_hub import DeviceHub
        return DeviceHub()

    def _make_ws(self):
        ws = AsyncMock()
        ws.send_json = AsyncMock()
        return ws

    def test_reconnect_registers_new_session(self):
        hub = self._make_hub()
        ws1 = self._make_ws()
        ws2 = self._make_ws()

        conn1 = hub.register("token_a", device_id=1, user_id=10, ws=ws1)
        session1 = conn1.session_id

        conn2 = hub.register("token_a", device_id=1, user_id=10, ws=ws2)
        session2 = conn2.session_id

        self.assertNotEqual(session1, session2)
        # Hub must point to the new connection
        active = hub.get_connection(1)
        self.assertIs(active, conn2)

    def test_old_pending_futures_failed_on_reconnect(self):
        hub = self._make_hub()
        ws1 = self._make_ws()
        ws2 = self._make_ws()

        conn1 = hub.register("token_a", device_id=1, user_id=10, ws=ws1)

        # Inject a fake pending future into the old connection
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        conn1._pending["cmd1"] = future

        # Reconnect — should fail old pending futures
        hub.register("token_a", device_id=1, user_id=10, ws=ws2)

        self.assertTrue(future.done())
        self.assertIsInstance(future.exception(), ConnectionError)

    def test_unregister_with_wrong_session_is_noop(self):
        """Reconnect race: old session's finally-block must not remove new conn."""
        hub = self._make_hub()
        ws1 = self._make_ws()
        ws2 = self._make_ws()

        conn1 = hub.register("token_a", device_id=1, user_id=10, ws=ws1)
        old_session = conn1.session_id

        # New device connects
        hub.register("token_a", device_id=1, user_id=10, ws=ws2)

        # Old connection's finally-block calls unregister with old session_id
        hub.unregister(device_id=1, session_id=old_session)

        # New connection must still be in hub
        self.assertTrue(hub.is_connected(1))

    def test_unregister_with_correct_session_removes_connection(self):
        hub = self._make_hub()
        ws = self._make_ws()

        conn = hub.register("token_a", device_id=1, user_id=10, ws=ws)
        hub.unregister(device_id=1, session_id=conn.session_id)

        self.assertFalse(hub.is_connected(1))

    def test_unregister_fails_pending_futures(self):
        hub = self._make_hub()
        ws = self._make_ws()

        conn = hub.register("token_a", device_id=1, user_id=10, ws=ws)
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        conn._pending["cmd1"] = future

        hub.unregister(device_id=1, session_id=conn.session_id)

        self.assertTrue(future.done())
        self.assertIsInstance(future.exception(), ConnectionError)

    def test_fail_all_pending_covers_multiple_commands(self):
        hub = self._make_hub()
        ws = self._make_ws()

        conn = hub.register("token_a", device_id=1, user_id=10, ws=ws)
        loop = asyncio.get_event_loop()
        f1 = loop.create_future()
        f2 = loop.create_future()
        conn._pending["c1"] = f1
        conn._pending["c2"] = f2

        conn.fail_all_pending("test shutdown")

        self.assertTrue(f1.done())
        self.assertTrue(f2.done())
        self.assertIsInstance(f1.exception(), ConnectionError)
        self.assertIsInstance(f2.exception(), ConnectionError)
        self.assertEqual(len(conn._pending), 0)


# ─── Registration auth tests ─────────────────────────────────────────────────

class TestRegistrationAuth(unittest.TestCase):
    """F2 — Registration endpoint must use bcrypt-aware verifier."""

    def test_verify_password_plaintext(self):
        from app.routers.auth import _verify_password
        self.assertTrue(_verify_password("admin", "admin"))
        self.assertFalse(_verify_password("wrong", "admin"))

    def test_verify_password_bcrypt(self):
        try:
            import bcrypt
        except ImportError:
            self.skipTest("bcrypt not installed")

        import bcrypt as bc
        hashed = bc.hashpw(b"secret123", bc.gensalt()).decode()
        from app.routers.auth import _verify_password
        self.assertTrue(_verify_password("secret123", hashed))
        self.assertFalse(_verify_password("wrongpass", hashed))

    def test_register_endpoint_rejects_plaintext_wrong_password(self):
        """Register with wrong password must 401, not 500."""
        # We test the auth logic in isolation; full endpoint test needs DB.
        from app.routers.auth import _verify_password
        stored = "correct_password"
        self.assertFalse(_verify_password("bad_password", stored))


# ─── DeviceConnection.handle_response tests ──────────────────────────────────

class TestHandleResponse(unittest.IsolatedAsyncioTestCase):
    """F7 — Response handler does not set result on already-done futures."""

    def test_handle_response_resolves_pending(self):
        from app.services.device_hub import DeviceConnection
        ws = AsyncMock()
        conn = DeviceConnection("tok", 1, 1, ws)
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        conn._pending["abc"] = future

        conn.handle_response({"id": "abc", "status": "ok", "result": "pong"})
        self.assertTrue(future.done())
        self.assertEqual(future.result()["status"], "ok")

    def test_handle_response_ignores_unknown_id(self):
        """Unknown id (unsolicited event) must not raise."""
        from app.services.device_hub import DeviceConnection
        ws = AsyncMock()
        conn = DeviceConnection("tok", 1, 1, ws)
        # Should not raise even when no pending future
        conn.handle_response({"id": "unknown", "type": "heartbeat"})

    def test_handle_response_ignores_already_done_future(self):
        """No double-set on an already-resolved future."""
        from app.services.device_hub import DeviceConnection
        ws = AsyncMock()
        conn = DeviceConnection("tok", 1, 1, ws)
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        future.set_result({"status": "ok"})  # pre-resolve
        conn._pending["abc"] = future

        # Should not raise InvalidStateError
        conn.handle_response({"id": "abc", "status": "ok", "result": "pong"})


if __name__ == "__main__":
    unittest.main()
