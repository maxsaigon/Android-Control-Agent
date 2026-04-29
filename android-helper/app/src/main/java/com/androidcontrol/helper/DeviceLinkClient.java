package com.androidcontrol.helper;

import android.content.Context;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;

import com.google.gson.Gson;
import com.google.gson.JsonObject;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

public class DeviceLinkClient {

    private static final String TAG = "ACHelper.Link";
    private static final Gson gson = new Gson();

    public interface LinkCallback {
        void onPending(String requestId);
        void onApproved(String token);
        void onRejected(String reason);
        void onError(String error);
    }

    public static void requestLink(ConnectionConfig config, String username, String deviceName, LinkCallback callback) {
        new Thread(() -> {
            try {
                String baseUrl = config.getServerUrl();
                if (baseUrl.endsWith("/")) baseUrl = baseUrl.substring(0, baseUrl.length() - 1);
                if (!baseUrl.startsWith("http")) baseUrl = "https://" + baseUrl;

                URL url = new URL(baseUrl + "/api/device/link/request");
                HttpURLConnection conn = (HttpURLConnection) url.openConnection();
                conn.setRequestMethod("POST");
                conn.setRequestProperty("Content-Type", "application/json");
                conn.setDoOutput(true);

                JsonObject body = new JsonObject();
                body.addProperty("username", username);
                body.addProperty("device_name", deviceName);
                body.addProperty("device_model", Build.MODEL);
                body.addProperty("android_version", Build.VERSION.RELEASE);
                body.addProperty("sdk_int", Build.VERSION.SDK_INT);
                body.addProperty("manufacturer", Build.MANUFACTURER);

                JsonObject helperInfo = HelperBuildInfo.asJson();
                body.add("helper", helperInfo);

                try (OutputStream os = conn.getOutputStream()) {
                    os.write(body.toString().getBytes(StandardCharsets.UTF_8));
                }

                int code = conn.getResponseCode();
                if (code == 200 || code == 201) {
                    BufferedReader reader = new BufferedReader(new InputStreamReader(conn.getInputStream()));
                    StringBuilder sb = new StringBuilder();
                    String line;
                    while ((line = reader.readLine()) != null) sb.append(line);
                    reader.close();

                    JsonObject res = gson.fromJson(sb.toString(), JsonObject.class);
                    String reqId = res.get("request_id").getAsString();
                    new Handler(Looper.getMainLooper()).post(() -> callback.onPending(reqId));
                } else {
                    new Handler(Looper.getMainLooper()).post(() -> callback.onError("Failed with code " + code));
                }
                conn.disconnect();
            } catch (Exception e) {
                Log.e(TAG, "Request link error", e);
                new Handler(Looper.getMainLooper()).post(() -> callback.onError(e.getMessage()));
            }
        }).start();
    }

    public static void pollStatus(ConnectionConfig config, String requestId, LinkCallback callback) {
        new Thread(() -> {
            try {
                String baseUrl = config.getServerUrl();
                if (baseUrl.endsWith("/")) baseUrl = baseUrl.substring(0, baseUrl.length() - 1);
                if (!baseUrl.startsWith("http")) baseUrl = "https://" + baseUrl;

                URL url = new URL(baseUrl + "/api/device/link/status/" + requestId);
                HttpURLConnection conn = (HttpURLConnection) url.openConnection();
                conn.setRequestMethod("GET");

                int code = conn.getResponseCode();
                if (code == 200) {
                    BufferedReader reader = new BufferedReader(new InputStreamReader(conn.getInputStream()));
                    StringBuilder sb = new StringBuilder();
                    String line;
                    while ((line = reader.readLine()) != null) sb.append(line);
                    reader.close();

                    JsonObject res = gson.fromJson(sb.toString(), JsonObject.class);
                    String status = res.get("status").getAsString();
                    
                    new Handler(Looper.getMainLooper()).post(() -> {
                        if ("approved".equals(status)) {
                            String token = res.get("device_token").getAsString();
                            callback.onApproved(token);
                        } else if ("rejected".equals(status)) {
                            String msg = res.has("message") ? res.get("message").getAsString() : "Rejected";
                            callback.onRejected(msg);
                        } else if ("expired".equals(status)) {
                            callback.onRejected("Request expired");
                        } else {
                            callback.onPending(requestId);
                        }
                    });
                } else {
                    new Handler(Looper.getMainLooper()).post(() -> callback.onError("Poll failed " + code));
                }
                conn.disconnect();
            } catch (Exception e) {
                new Handler(Looper.getMainLooper()).post(() -> callback.onError(e.getMessage()));
            }
        }).start();
    }
}
