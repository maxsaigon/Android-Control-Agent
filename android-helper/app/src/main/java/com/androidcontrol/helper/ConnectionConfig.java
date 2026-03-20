package com.androidcontrol.helper;

import android.content.Context;
import android.content.SharedPreferences;

/**
 * Persists cloud connection config in SharedPreferences.
 *
 * Config values:
 * - mode: "lan" (default) or "cloud"
 * - server_url: e.g. "wss://abc.com" or "ws://192.168.1.100:8000"
 * - device_token: authentication token from the dashboard
 */
public class ConnectionConfig {

    private static final String PREFS_NAME = "ac_helper_config";
    private static final String KEY_MODE = "connection_mode";
    private static final String KEY_SERVER_URL = "server_url";
    private static final String KEY_DEVICE_TOKEN = "device_token";

    public static final String MODE_LAN = "lan";
    public static final String MODE_CLOUD = "cloud";

    private final SharedPreferences prefs;

    public ConnectionConfig(Context context) {
        prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);
    }

    public String getMode() {
        return prefs.getString(KEY_MODE, MODE_LAN);
    }

    public void setMode(String mode) {
        prefs.edit().putString(KEY_MODE, mode).apply();
    }

    public String getServerUrl() {
        return prefs.getString(KEY_SERVER_URL, "");
    }

    public void setServerUrl(String url) {
        prefs.edit().putString(KEY_SERVER_URL, url).apply();
    }

    public String getDeviceToken() {
        return prefs.getString(KEY_DEVICE_TOKEN, "");
    }

    public void setDeviceToken(String token) {
        prefs.edit().putString(KEY_DEVICE_TOKEN, token).apply();
    }

    public boolean isCloudMode() {
        return MODE_CLOUD.equals(getMode());
    }

    public boolean isConfigured() {
        return !getServerUrl().isEmpty() && !getDeviceToken().isEmpty();
    }

    /**
     * Build the full WebSocket URL for cloud connection.
     * Example: wss://abc.com/ws/device/TOKEN_HERE
     */
    public String getCloudWsUrl() {
        String base = getServerUrl();
        // Remove trailing slash
        if (base.endsWith("/")) {
            base = base.substring(0, base.length() - 1);
        }
        // Add ws:// or wss:// prefix if missing
        if (!base.startsWith("ws://") && !base.startsWith("wss://")) {
            if (base.startsWith("https://")) {
                base = "wss://" + base.substring(8);
            } else if (base.startsWith("http://")) {
                base = "ws://" + base.substring(7);
            } else {
                base = "ws://" + base;
            }
        }
        return base + "/ws/device/" + getDeviceToken();
    }
}
