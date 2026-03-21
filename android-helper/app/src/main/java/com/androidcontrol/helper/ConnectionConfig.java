package com.androidcontrol.helper;

import android.content.Context;
import android.content.SharedPreferences;

/**
 * Persists cloud connection config in SharedPreferences.
 *
 * Config values:
 * - mode: "lan" (default) or "cloud"
 * - server_url: e.g. "m.buonme.com"
 * - username: login username for device registration
 * - password: login password for device registration
 * - device_name: human-readable name for this device
 * - device_token: auto-generated token from register API (not user-entered)
 */
public class ConnectionConfig {

    private static final String PREFS_NAME = "ac_helper_config";
    private static final String KEY_MODE = "connection_mode";
    private static final String KEY_SERVER_URL = "server_url";
    private static final String KEY_USERNAME = "username";
    private static final String KEY_PASSWORD = "password";
    private static final String KEY_DEVICE_NAME = "device_name";
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

    public String getUsername() {
        return prefs.getString(KEY_USERNAME, "");
    }

    public void setUsername(String username) {
        prefs.edit().putString(KEY_USERNAME, username).apply();
    }

    public String getPassword() {
        return prefs.getString(KEY_PASSWORD, "");
    }

    public void setPassword(String password) {
        prefs.edit().putString(KEY_PASSWORD, password).apply();
    }

    public String getDeviceName() {
        return prefs.getString(KEY_DEVICE_NAME, "");
    }

    public void setDeviceName(String name) {
        prefs.edit().putString(KEY_DEVICE_NAME, name).apply();
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

    /**
     * Check if cloud config has enough info to attempt registration + connection.
     */
    public boolean isConfigured() {
        return !getServerUrl().isEmpty()
                && !getUsername().isEmpty()
                && !getPassword().isEmpty()
                && !getDeviceName().isEmpty();
    }

    /**
     * Check if we have a cached token from a previous successful registration.
     */
    public boolean hasToken() {
        return !getDeviceToken().isEmpty();
    }

    /**
     * Build the registration API URL.
     * Example: https://m.buonme.com/api/device/register
     */
    public String getRegisterUrl() {
        String base = getServerUrl();
        if (base.endsWith("/")) {
            base = base.substring(0, base.length() - 1);
        }
        if (!base.startsWith("http://") && !base.startsWith("https://")) {
            base = "https://" + base;
        }
        return base + "/api/device/register";
    }

    /**
     * Build the full WebSocket URL for cloud connection.
     * Example: wss://m.buonme.com/ws/device/TOKEN_HERE
     */
    public String getCloudWsUrl() {
        String base = getServerUrl();
        if (base.endsWith("/")) {
            base = base.substring(0, base.length() - 1);
        }
        if (!base.startsWith("ws://") && !base.startsWith("wss://")) {
            if (base.startsWith("https://")) {
                base = "wss://" + base.substring(8);
            } else if (base.startsWith("http://")) {
                base = "ws://" + base.substring(7);
            } else {
                base = "wss://" + base;
            }
        }
        return base + "/ws/device/" + getDeviceToken();
    }
}
