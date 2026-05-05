package com.androidcontrol.helper;

import android.os.Handler;
import android.os.Looper;
import android.util.Log;

import com.google.gson.Gson;
import com.google.gson.JsonObject;

import org.java_websocket.client.WebSocketClient;
import org.java_websocket.handshake.ServerHandshake;

import java.net.URI;
import java.util.Timer;
import java.util.TimerTask;

/**
 * WebSocket CLIENT that connects to a remote cloud server.
 *
 * This is the reverse of the existing WebSocket server:
 * - LAN mode: Device runs WS server, PC connects to device
 * - Cloud mode: Device runs WS client, connects OUT to cloud server
 *
 * Uses the same JSON protocol and CommandHandler for processing,
 * so all existing functionality works identically in both modes.
 *
 * Features:
 * - Auto-reconnect with exponential backoff (2s → 4s → 8s → ... → 60s)
 * - Periodic heartbeat every 30 seconds
 * - Handles welcome message from server
 */
public class CloudWebSocketClient extends WebSocketClient {

    private static final String TAG = "ACHelper.Cloud";
    private static final Gson gson = new Gson();
    private static final long HEARTBEAT_INTERVAL_MS = 30_000; // 30 seconds

    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private Timer heartbeatTimer;
    private boolean shouldReconnect = true;
    private boolean reconnectScheduled = false;
    private int reconnectAttempt = 0;
    private long lastHeartbeatAckMs = 0;
    private static final int MAX_RECONNECT_DELAY_MS = 60_000; // 60s max

    private ConnectionListener listener;

    public interface ConnectionListener {
        void onConnected();
        void onDisconnected(String reason);
        void onReconnecting(int attempt, long delayMs);
        void onAuthInvalid(String reason);
    }

    public CloudWebSocketClient(URI serverUri) {
        super(serverUri);
        // Give generous timeout — Cloudflare Tunnel + mobile networks
        // can introduce jitter. The server sends keepalive pings every 25s,
        // so 90s without ANY frame means the connection is truly dead.
        this.setConnectionLostTimeout(90);
    }

    public void setConnectionListener(ConnectionListener listener) {
        this.listener = listener;
    }

    @Override
    public void onOpen(ServerHandshake handshake) {
        Log.i(TAG, "☁️ Connected to cloud server: " + getURI());
        Log.i(TAG, "☁️ Helper build: " + HelperBuildInfo.releaseLabel() +
                " | " + HelperBuildInfo.debugLabel());
        reconnectAttempt = 0;
        reconnectScheduled = false;
        lastHeartbeatAckMs = System.currentTimeMillis();
        sendHello();
        startHeartbeat();
        if (listener != null) {
            mainHandler.post(() -> listener.onConnected());
        }
    }

    @Override
    public void onMessage(String message) {
        try {
            JsonObject data = gson.fromJson(message, JsonObject.class);

            // Handle server's welcome message
            if (data.has("type") && "welcome".equals(data.get("type").getAsString())) {
                Log.i(TAG, "☁️ Welcome from server: device_id=" +
                        (data.has("device_id") ? data.get("device_id").getAsInt() : "?"));
                return;
            }

            // Handle heartbeat ack
            if (data.has("type") && "heartbeat_ack".equals(data.get("type").getAsString())) {
                Log.d(TAG, "💓 Heartbeat ack received");
                lastHeartbeatAckMs = System.currentTimeMillis();
                return;
            }

            // Handle server-side keepalive ping — just acknowledge receipt
            if (data.has("type") && "server_ping".equals(data.get("type").getAsString())) {
                lastHeartbeatAckMs = System.currentTimeMillis();
                return;
            }

            // Regular command from server — route through CommandHandler
            if (data.has("id") && data.has("action")) {
                Log.d(TAG, "📥 Command: " + data.get("action").getAsString());
                CommandHandler.handle(message, response -> {
                    if (isOpen()) {
                        send(response);
                    }
                });
                return;
            }

            Log.d(TAG, "☁️ Unknown message: " + message);
        } catch (Exception e) {
            Log.e(TAG, "Error processing message: " + message, e);
        }
    }

    @Override
    public void onClose(int code, String reason, boolean remote) {
        Log.w(TAG, "☁️ Disconnected from cloud (code=" + code + ", reason=" + reason +
                ", remote=" + remote + ")");
        stopHeartbeat();

        String normalizedReason = reason == null ? "" : reason.toLowerCase();
        boolean authInvalid = code == org.java_websocket.framing.CloseFrame.POLICY_VALIDATION
                || code == 4001
                || normalizedReason.contains("invalid")
                || normalizedReason.contains("inactive")
                || normalizedReason.contains("revoked");
        if (authInvalid) {
            Log.e(TAG, "Server rejected connection (token revoked/invalid). Stopping reconnect.");
            shouldReconnect = false;
            if (listener != null) {
                mainHandler.post(() -> listener.onAuthInvalid(reason));
            }
        }

        if (listener != null) {
            mainHandler.post(() -> listener.onDisconnected(reason));
        }

        // Auto-reconnect with exponential backoff
        if (shouldReconnect) {
            scheduleReconnect();
        }
    }

    @Override
    public void onError(Exception ex) {
        Log.e(TAG, "☁️ WebSocket error", ex);
    }

    // --- Heartbeat ---

    private void startHeartbeat() {
        stopHeartbeat();
        heartbeatTimer = new Timer("cloud-heartbeat", true);
        heartbeatTimer.scheduleAtFixedRate(new TimerTask() {
            @Override
            public void run() {
                if (isOpen()) {
                    long now = System.currentTimeMillis();
                    if (now - lastHeartbeatAckMs > HEARTBEAT_INTERVAL_MS * 3.5) {
                        Log.w(TAG, "No heartbeat_ack for " + (now - lastHeartbeatAckMs) + "ms! Connection stale, forcing reconnect.");
                        close();
                        return;
                    }
                    try {
                        JsonObject hb = new JsonObject();
                        hb.addProperty("type", "heartbeat");
                        // TODO: add battery level from BatteryManager
                        hb.add("helper", HelperBuildInfo.asJson());
                        send(hb.toString());
                        Log.d(TAG, "💓 Heartbeat sent");
                    } catch (Exception e) {
                        Log.e(TAG, "Heartbeat error", e);
                    }
                }
            }
        }, HEARTBEAT_INTERVAL_MS, HEARTBEAT_INTERVAL_MS);
    }

    private void sendHello() {
        if (!isOpen()) {
            return;
        }
        try {
            JsonObject hello = new JsonObject();
            hello.addProperty("type", "hello");
            hello.add("helper", HelperBuildInfo.asJson());
            send(hello.toString());
            Log.i(TAG, "👋 Helper hello sent: " + HelperBuildInfo.shortLabel());
        } catch (Exception e) {
            Log.e(TAG, "Failed to send helper hello", e);
        }
    }

    private void stopHeartbeat() {
        if (heartbeatTimer != null) {
            heartbeatTimer.cancel();
            heartbeatTimer = null;
        }
    }

    // --- Reconnect ---

    private void scheduleReconnect() {
        if (reconnectScheduled) {
            return;
        }
        reconnectScheduled = true;
        reconnectAttempt++;
        // Exponential backoff: 2s, 4s, 8s, 16s, 32s, 60s, 60s, ...
        long delay = Math.min(
                (long) Math.pow(2, reconnectAttempt) * 1000,
                MAX_RECONNECT_DELAY_MS
        );
        Log.i(TAG, "🔄 Reconnecting in " + (delay / 1000) + "s (attempt " + reconnectAttempt + ")");

        if (listener != null) {
            final long d = delay;
            final int a = reconnectAttempt;
            mainHandler.post(() -> listener.onReconnecting(a, d));
        }

        mainHandler.postDelayed(() -> {
            reconnectScheduled = false;
            if (shouldReconnect) {
                try {
                    reconnect();
                } catch (Exception e) {
                    Log.e(TAG, "Reconnect failed", e);
                    scheduleReconnect(); // Try again
                }
            }
        }, delay);
    }

    // --- Lifecycle ---

    /**
     * Disconnect and stop reconnecting.
     */
    public void shutdown() {
        shouldReconnect = false;
        stopHeartbeat();
        try {
            closeBlocking();
        } catch (Exception e) {
            Log.e(TAG, "Error during shutdown", e);
        }
    }
}
