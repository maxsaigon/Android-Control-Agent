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

/**
 * Foreground service that runs a WebSocket server.
 *
 * Receives JSON commands from PC, routes them to the
 * AccessibilityService via CommandHandler.
 */
public class WebSocketService extends Service {

    private static final String TAG = "ACHelper.WS";
    private static final int NOTIFICATION_ID = 1001;
    private static final String CHANNEL_ID = "ac_helper_channel";
    private static final int WS_PORT = 38301;

    private HelperWebSocketServer wsServer;

    @Override
    public void onCreate() {
        super.onCreate();
        createNotificationChannel();
        startForeground(NOTIFICATION_ID, buildNotification());

        // Start WebSocket server
        wsServer = new HelperWebSocketServer(new InetSocketAddress(WS_PORT));
        wsServer.setReuseAddr(true);
        wsServer.start();
        Log.i(TAG, "WebSocket server started on port " + WS_PORT);
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        if (wsServer != null) {
            try {
                wsServer.stop(1000);
            } catch (InterruptedException e) {
                Log.e(TAG, "Error stopping WebSocket server", e);
            }
        }
        super.onDestroy();
        Log.i(TAG, "WebSocket service destroyed");
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

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

    private Notification buildNotification() {
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
                .setContentText(String.format(getString(R.string.notification_text), WS_PORT))
                .setSmallIcon(android.R.drawable.ic_menu_manage)
                .setContentIntent(pi)
                .setOngoing(true)
                .build();
    }

    /**
     * WebSocket server that handles client connections and routes commands.
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
            // Route to CommandHandler on main thread
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
