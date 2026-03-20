package com.androidcontrol.helper;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.os.Build;
import android.os.IBinder;
import android.util.Log;

import org.java_websocket.WebSocket;
import org.java_websocket.handshake.ClientHandshake;
import org.java_websocket.server.WebSocketServer;

import java.net.InetSocketAddress;
import java.net.URI;

/**
 * Foreground service that supports DUAL MODE:
 *
 * 1. LAN Mode (default): Runs a WebSocket SERVER on port 38301.
 *    PC connects TO the device. Original behavior.
 *
 * 2. Cloud Mode: Runs a WebSocket CLIENT that connects OUT to the
 *    cloud server. Device authenticates with a token.
 *
 * Both modes use the same CommandHandler and JSON protocol, so all
 * device control functionality works identically.
 */
public class WebSocketService extends Service {

    private static final String TAG = "ACHelper.WS";
    private static final int NOTIFICATION_ID = 1001;
    private static final String CHANNEL_ID = "ac_helper_channel";
    private static final int WS_PORT = 38301;

    /**
     * Intent extra to force a specific mode (for restarts).
     */
    public static final String EXTRA_MODE = "connection_mode";

    private HelperWebSocketServer wsServer;
    private CloudWebSocketClient cloudClient;
    private ConnectionConfig config;
    private String currentMode = ConnectionConfig.MODE_LAN;

    @Override
    public void onCreate() {
        super.onCreate();
        createNotificationChannel();
        config = new ConnectionConfig(this);
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        // Determine mode
        String mode = config.getMode();
        if (intent != null && intent.hasExtra(EXTRA_MODE)) {
            mode = intent.getStringExtra(EXTRA_MODE);
        }

        // Stop existing connections if mode changed
        if (!mode.equals(currentMode)) {
            stopAll();
        }
        currentMode = mode;

        if (ConnectionConfig.MODE_CLOUD.equals(mode) && config.isConfigured()) {
            startCloudMode();
        } else {
            startLanMode();
        }

        return START_STICKY;
    }

    // --- LAN Mode (WebSocket Server) ---

    private void startLanMode() {
        if (wsServer != null) return;

        startForeground(NOTIFICATION_ID, buildNotification(
                "LAN Mode — WebSocket server on port " + WS_PORT));

        wsServer = new HelperWebSocketServer(new InetSocketAddress(WS_PORT));
        wsServer.setReuseAddr(true);
        wsServer.start();
        Log.i(TAG, "🏠 LAN mode: WebSocket server started on port " + WS_PORT);
    }

    // --- Cloud Mode (WebSocket Client) ---

    private void startCloudMode() {
        if (cloudClient != null && cloudClient.isOpen()) return;

        String wsUrl = config.getCloudWsUrl();
        Log.i(TAG, "☁️ Cloud mode: connecting to " + wsUrl);

        startForeground(NOTIFICATION_ID, buildNotification(
                "Cloud Mode — connecting to server..."));

        try {
            URI uri = new URI(wsUrl);
            cloudClient = new CloudWebSocketClient(uri);
            cloudClient.setConnectionListener(new CloudWebSocketClient.ConnectionListener() {
                @Override
                public void onConnected() {
                    updateNotification("Cloud Mode — connected ✅");
                    Log.i(TAG, "☁️ Cloud connected!");
                }

                @Override
                public void onDisconnected(String reason) {
                    updateNotification("Cloud Mode — disconnected ❌");
                    Log.w(TAG, "☁️ Cloud disconnected: " + reason);
                }

                @Override
                public void onReconnecting(int attempt, long delayMs) {
                    updateNotification("Cloud Mode — reconnecting (" + attempt + ")...");
                }
            });
            cloudClient.connect();
        } catch (Exception e) {
            Log.e(TAG, "Failed to start cloud client", e);
            // Fallback to LAN mode
            startLanMode();
        }
    }

    // --- Lifecycle ---

    private void stopAll() {
        if (wsServer != null) {
            try {
                wsServer.stop(1000);
            } catch (InterruptedException e) {
                Log.e(TAG, "Error stopping WS server", e);
            }
            wsServer = null;
        }
        if (cloudClient != null) {
            cloudClient.shutdown();
            cloudClient = null;
        }
    }

    @Override
    public void onDestroy() {
        stopAll();
        super.onDestroy();
        Log.i(TAG, "WebSocket service destroyed");
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    // --- Notification ---

    private void createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel channel = new NotificationChannel(
                    CHANNEL_ID,
                    getString(R.string.notification_channel_name),
                    NotificationManager.IMPORTANCE_LOW
            );
            channel.setDescription("Keeps AC Helper service running");
            NotificationManager nm = getSystemService(NotificationManager.class);
            nm.createNotificationChannel(channel);
        }
    }

    private Notification buildNotification(String text) {
        Intent intent = new Intent(this, MainActivity.class);
        PendingIntent pi = PendingIntent.getActivity(
                this, 0, intent,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
        );

        Notification.Builder builder;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            builder = new Notification.Builder(this, CHANNEL_ID);
        } else {
            builder = new Notification.Builder(this);
        }

        return builder
                .setContentTitle(getString(R.string.notification_title))
                .setContentText(text)
                .setSmallIcon(android.R.drawable.ic_menu_manage)
                .setContentIntent(pi)
                .setOngoing(true)
                .build();
    }

    private void updateNotification(String text) {
        NotificationManager nm = getSystemService(NotificationManager.class);
        if (nm != null) {
            nm.notify(NOTIFICATION_ID, buildNotification(text));
        }
    }

    // --- Status ---

    public String getCurrentMode() {
        return currentMode;
    }

    public boolean isCloudConnected() {
        return cloudClient != null && cloudClient.isOpen();
    }

    /**
     * WebSocket server that handles client connections and routes commands.
     * (Same as before — LAN mode only)
     */
    private static class HelperWebSocketServer extends WebSocketServer {

        public HelperWebSocketServer(InetSocketAddress address) {
            super(address);
        }

        @Override
        public void onOpen(WebSocket conn, ClientHandshake handshake) {
            Log.i(TAG, "Client connected: " + conn.getRemoteSocketAddress());
        }

        @Override
        public void onClose(WebSocket conn, int code, String reason, boolean remote) {
            Log.i(TAG, "Client disconnected: " + reason);
        }

        @Override
        public void onMessage(WebSocket conn, String message) {
            Log.d(TAG, "Received: " + message);
            CommandHandler.handle(message, response -> {
                if (conn.isOpen()) {
                    conn.send(response);
                }
            });
        }

        @Override
        public void onError(WebSocket conn, Exception ex) {
            Log.e(TAG, "WebSocket error", ex);
        }

        @Override
        public void onStart() {
            Log.i(TAG, "WebSocket server started");
        }
    }
}
