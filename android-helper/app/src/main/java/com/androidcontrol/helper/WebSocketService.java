package com.androidcontrol.helper;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.net.ConnectivityManager;
import android.net.Network;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.util.Log;

import org.java_websocket.WebSocket;
import org.java_websocket.drafts.Draft;
import org.java_websocket.enums.ReadyState;
import org.java_websocket.exceptions.InvalidDataException;
import org.java_websocket.framing.CloseFrame;
import org.java_websocket.handshake.ClientHandshake;
import org.java_websocket.handshake.ServerHandshakeBuilder;
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
    private ConnectivityManager.NetworkCallback networkCallback;
    private ConnectionConfig config;
    private String currentMode = ConnectionConfig.MODE_LAN;
    private volatile boolean relinkInProgress = false;
    private final Handler relinkHandler = new Handler(Looper.getMainLooper());
    private Runnable relinkPollRunnable;

    @Override
    public void onCreate() {
        super.onCreate();
        createNotificationChannel();
        config = new ConnectionConfig(this);
        Log.i(TAG, "Helper service booting: " + HelperBuildInfo.releaseLabel() +
                " | " + HelperBuildInfo.debugLabel());
        registerNetworkCallback();
    }

    private void registerNetworkCallback() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
            ConnectivityManager cm = (ConnectivityManager) getSystemService(Context.CONNECTIVITY_SERVICE);
            if (cm != null) {
                networkCallback = new ConnectivityManager.NetworkCallback() {
                    @Override
                    public void onAvailable(Network network) {
                        Log.i(TAG, "🌐 Network available");
                    }

                    @Override
                    public void onLost(Network network) {
                        Log.w(TAG, "🌐 Network lost");
                        if (cloudClient != null && cloudClient.isOpen()) {
                            Log.i(TAG, "Closing cloud client aggressively due to network loss");
                            cloudClient.close();
                        }
                    }
                };
                cm.registerDefaultNetworkCallback(networkCallback);
            }
        }
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

        if (ConnectionConfig.MODE_CLOUD.equals(mode) && config.isReadyToConnect()) {
            startCloudMode();
        } else if (ConnectionConfig.MODE_CLOUD.equals(mode) && config.isConfigured()) {
            // No cached token yet — need to register first via MainActivity
            Log.w(TAG, "⚠️ Cloud mode set but no token cached — waiting for user to register");
            startForeground(NOTIFICATION_ID, buildNotification(
                    "Cloud Mode — waiting for registration..."));
        } else {
            startLanMode();
        }

        return START_STICKY;
    }

    // --- LAN Mode (WebSocket Server) ---

    private void startLanMode() {
        if (wsServer != null) return;

        startForeground(NOTIFICATION_ID, buildNotification(
                "LAN Mode \u2014 " + HelperBuildInfo.shortLabel() + " \u2014 port " + WS_PORT));

        wsServer = new HelperWebSocketServer(new InetSocketAddress(WS_PORT), config.getLanToken());
        wsServer.setReuseAddr(true);
        wsServer.start();
        Log.i(TAG, "🏠 LAN mode: WebSocket server started on port " + WS_PORT);
    }

    // --- Cloud Mode (WebSocket Client) ---

    private void startCloudMode() {
        // Keep a single client instance alive while it is open/connecting/reconnecting.
        // onStartCommand() can be called multiple times; recreating here causes
        // self-disconnect loops right after successful connection.
        if (cloudClient != null) {
            ReadyState state = cloudClient.getReadyState();
            if (state != ReadyState.CLOSED) {
                Log.i(TAG, "☁️ Cloud client already active/recovering (state=" + state + "), skip recreate");
                return;
            }
            cloudClient.shutdown();
            cloudClient = null;
        }

        String wsUrl = config.getCloudWsUrl();
        Log.i(TAG, "☁️ Cloud mode: connecting to " + wsUrl);

        startForeground(NOTIFICATION_ID, buildNotification(
                "Cloud Mode — " + HelperBuildInfo.shortLabel() + " — connecting..."));

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
                    String msg = "Cloud Mode — disconnected ❌";
                    if (reason != null && !reason.trim().isEmpty()) {
                        msg += " (" + reason + ")";
                    }
                    updateNotification(msg);
                    Log.w(TAG, "☁️ Cloud disconnected: " + reason);
                }

                @Override
                public void onReconnecting(int attempt, long delayMs) {
                    updateNotification("Cloud Mode — reconnecting (" + attempt + ")...");
                }

                @Override
                public void onAuthInvalid(String reason) {
                    handleAuthInvalid(reason);
                }
            });
            cloudClient.connect();
        } catch (Exception e) {
            Log.e(TAG, "Failed to start cloud client", e);
            // Fallback to LAN mode
            startLanMode();
        }
    }

    private void handleAuthInvalid(String reason) {
        String msg = reason == null || reason.trim().isEmpty()
                ? "token invalid"
                : reason.trim();
        Log.w(TAG, "☁️ Token invalid/revoked: " + msg);
        config.clearCloudBinding();
        relinkInProgress = false;
        updateNotification("Cloud Mode — token revoked, requesting approval...");
        requestRelink();
    }

    private void requestRelink() {
        if (relinkInProgress) {
            return;
        }
        String username = config.getUsername();
        String deviceName = config.getDeviceName();
        if (username == null || username.trim().isEmpty()
                || deviceName == null || deviceName.trim().isEmpty()) {
            updateNotification("Cloud Mode — relink required (open app)");
            return;
        }

        relinkInProgress = true;
        DeviceLinkClient.requestLink(config, username, deviceName, new DeviceLinkClient.LinkCallback() {
            @Override
            public void onPending(String requestId) {
                config.setLinkRequestId(requestId);
                updateNotification("Cloud Mode — waiting for re-approval...");
                startRelinkPolling(requestId);
                relinkInProgress = false;
            }

            @Override
            public void onApproved(String token) {
                config.setDeviceToken(token);
                config.clearLinkRequestId();
                stopRelinkPolling();
                updateNotification("Cloud Mode — re-approved, reconnecting...");
                relinkInProgress = false;
                startCloudMode();
            }

            @Override
            public void onRejected(String reason) {
                String text = "Cloud Mode — re-approval rejected";
                if (reason != null && !reason.trim().isEmpty()) {
                    text += " (" + reason + ")";
                }
                updateNotification(text);
                stopRelinkPolling();
                relinkInProgress = false;
            }

            @Override
            public void onError(String error) {
                String text = "Cloud Mode — relink request failed";
                if (error != null && !error.trim().isEmpty()) {
                    text += " (" + error + ")";
                }
                updateNotification(text);
                relinkInProgress = false;
            }
        });
    }

    private void startRelinkPolling(String requestId) {
        stopRelinkPolling();
        relinkPollRunnable = new Runnable() {
            @Override
            public void run() {
                DeviceLinkClient.pollStatus(config, requestId, new DeviceLinkClient.LinkCallback() {
                    @Override
                    public void onPending(String ignored) {
                        updateNotification("Cloud Mode — waiting for re-approval...");
                    }

                    @Override
                    public void onApproved(String token) {
                        config.setDeviceToken(token);
                        config.clearLinkRequestId();
                        stopRelinkPolling();
                        updateNotification("Cloud Mode — re-approved, reconnecting...");
                        startCloudMode();
                    }

                    @Override
                    public void onRejected(String reason) {
                        String text = "Cloud Mode — re-approval rejected";
                        if (reason != null && !reason.trim().isEmpty()) {
                            text += " (" + reason + ")";
                        }
                        updateNotification(text);
                        stopRelinkPolling();
                    }

                    @Override
                    public void onError(String error) {
                        // Keep polling on transient network errors.
                    }
                });
                if (relinkPollRunnable != null && !config.hasToken()) {
                    relinkHandler.postDelayed(this, 4000);
                }
            }
        };
        relinkHandler.post(relinkPollRunnable);
    }

    private void stopRelinkPolling() {
        if (relinkPollRunnable != null) {
            relinkHandler.removeCallbacks(relinkPollRunnable);
            relinkPollRunnable = null;
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
        stopRelinkPolling();
        if (networkCallback != null && Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
            ConnectivityManager cm = (ConnectivityManager) getSystemService(Context.CONNECTIVITY_SERVICE);
            if (cm != null) {
                cm.unregisterNetworkCallback(networkCallback);
            }
        }
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
     * Requires token auth in handshake.
     */
    private static class HelperWebSocketServer extends WebSocketServer {

        private final String expectedToken;

        public HelperWebSocketServer(InetSocketAddress address, String token) {
            super(address);
            this.expectedToken = token;
        }

        @Override
        public ServerHandshakeBuilder onWebsocketHandshakeReceivedAsServer(WebSocket conn, Draft draft, ClientHandshake request) throws InvalidDataException {
            ServerHandshakeBuilder builder = super.onWebsocketHandshakeReceivedAsServer(conn, draft, request);
            String path = request.getResourceDescriptor();
            if (path == null || !path.contains("token=" + expectedToken)) {
                Log.w(TAG, "Rejecting LAN connection: invalid or missing token (path=" + path + ")");
                throw new InvalidDataException(CloseFrame.POLICY_VALIDATION, "Invalid token");
            }
            return builder;
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
