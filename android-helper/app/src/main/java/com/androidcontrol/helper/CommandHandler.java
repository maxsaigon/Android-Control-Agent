package com.androidcontrol.helper;

import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageManager;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;
import android.view.accessibility.AccessibilityNodeInfo;

import com.google.gson.Gson;
import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import java.util.ArrayList;
import java.util.List;

/**
 * Routes incoming WebSocket JSON commands to AccessibilityService actions.
 *
 * Protocol:
 *   Request:  {"id": "xxx", "action": "tap", "params": {"x": 100, "y": 200}}
 *   Response: {"id": "xxx", "status": "ok", "result": "tapped at (100, 200)"}
 *   Error:    {"id": "xxx", "status": "error", "error": "message"}
 */
public class CommandHandler {

    private static final String TAG = "ACHelper.Cmd";
    private static final Gson gson = new Gson();
    private static final Handler mainHandler = new Handler(Looper.getMainLooper());

    public interface ResponseCallback {
        void send(String response);
    }

    public static void handle(String message, ResponseCallback callback) {
        try {
            JsonObject cmd = JsonParser.parseString(message).getAsJsonObject();
            String id = cmd.has("id") ? cmd.get("id").getAsString() : "";
            String action = cmd.has("action") ? cmd.get("action").getAsString() : "";
            JsonObject params = cmd.has("params") ? cmd.getAsJsonObject("params") : new JsonObject();

            HelperAccessibilityService service = HelperAccessibilityService.getInstance();

            switch (action) {
                case "ping":
                    sendOk(callback, id, "pong");
                    break;

                case "tap":
                    handleTap(service, id, params, callback);
                    break;

                case "swipe":
                    handleSwipe(service, id, params, callback);
                    break;

                case "long_press":
                    handleLongPress(service, id, params, callback);
                    break;

                case "type_text":
                    handleTypeText(service, id, params, callback);
                    break;

                case "click_node":
                    handleClickNode(service, id, params, callback);
                    break;

                case "global_action":
                    handleGlobalAction(service, id, params, callback);
                    break;

                case "get_ui_tree":
                    handleGetUITree(service, id, callback);
                    break;

                case "get_screen_size":
                    handleGetScreenSize(service, id, callback);
                    break;

                case "get_device_info":
                    handleGetDeviceInfo(service, id, callback);
                    break;

                case "get_foreground_app":
                    handleGetForegroundApp(service, id, callback);
                    break;

                case "launch_app":
                    handleLaunchApp(service, id, params, callback);
                    break;

                case "force_stop":
                    handleForceStop(service, id, params, callback);
                    break;

                case "list_packages":
                    handleListPackages(service, id, params, callback);
                    break;

                default:
                    sendError(callback, id, "Unknown action: " + action);
            }
        } catch (Exception e) {
            Log.e(TAG, "Command parse error", e);
            sendError(callback, "", "Parse error: " + e.getMessage());
        }
    }

    // --- Action handlers ---

    private static void handleTap(HelperAccessibilityService service, String id,
                                   JsonObject params, ResponseCallback callback) {
        if (service == null) { sendError(callback, id, "Service not running"); return; }
        int x = params.get("x").getAsInt();
        int y = params.get("y").getAsInt();
        service.tap(x, y, new HelperAccessibilityService.GestureCallback() {
            @Override
            public void onSuccess(String result) { sendOk(callback, id, result); }
            @Override
            public void onError(String error) { sendError(callback, id, error); }
        });
    }

    private static void handleSwipe(HelperAccessibilityService service, String id,
                                     JsonObject params, ResponseCallback callback) {
        if (service == null) { sendError(callback, id, "Service not running"); return; }
        int x1 = params.get("x1").getAsInt();
        int y1 = params.get("y1").getAsInt();
        int x2 = params.get("x2").getAsInt();
        int y2 = params.get("y2").getAsInt();
        int duration = params.has("duration") ? params.get("duration").getAsInt() : 300;
        service.swipe(x1, y1, x2, y2, duration, new HelperAccessibilityService.GestureCallback() {
            @Override
            public void onSuccess(String result) { sendOk(callback, id, result); }
            @Override
            public void onError(String error) { sendError(callback, id, error); }
        });
    }

    private static void handleLongPress(HelperAccessibilityService service, String id,
                                         JsonObject params, ResponseCallback callback) {
        if (service == null) { sendError(callback, id, "Service not running"); return; }
        int x = params.get("x").getAsInt();
        int y = params.get("y").getAsInt();
        int duration = params.has("duration") ? params.get("duration").getAsInt() : 1000;
        service.longPress(x, y, duration, new HelperAccessibilityService.GestureCallback() {
            @Override
            public void onSuccess(String result) { sendOk(callback, id, result); }
            @Override
            public void onError(String error) { sendError(callback, id, error); }
        });
    }

    private static void handleTypeText(HelperAccessibilityService service, String id,
                                        JsonObject params, ResponseCallback callback) {
        if (service == null) { sendError(callback, id, "Service not running"); return; }
        String text = params.get("text").getAsString();
        mainHandler.post(() -> {
            boolean ok = service.typeText(text);
            if (ok) {
                sendOk(callback, id, "Typed: " + text);
            } else {
                sendError(callback, id, "Failed to type — no focused EditText");
            }
        });
    }

    private static void handleClickNode(HelperAccessibilityService service, String id,
                                         JsonObject params, ResponseCallback callback) {
        if (service == null) { sendError(callback, id, "Service not running"); return; }
        String text = params.has("text") ? params.get("text").getAsString() : "";
        mainHandler.post(() -> {
            boolean ok = service.clickByText(text);
            if (ok) {
                sendOk(callback, id, "Clicked: " + text);
            } else {
                sendError(callback, id, "Element not found: " + text);
            }
        });
    }

    private static void handleGlobalAction(HelperAccessibilityService service, String id,
                                            JsonObject params, ResponseCallback callback) {
        if (service == null) { sendError(callback, id, "Service not running"); return; }
        String action = params.get("action").getAsString().toLowerCase();
        boolean ok;
        switch (action) {
            case "back":   ok = service.goBack(); break;
            case "home":   ok = service.goHome(); break;
            case "recents": ok = service.openRecents(); break;
            case "notifications": ok = service.openNotifications(); break;
            default:
                sendError(callback, id, "Unknown global action: " + action);
                return;
        }
        if (ok) {
            sendOk(callback, id, "Pressed " + action);
        } else {
            sendError(callback, id, "Global action failed: " + action);
        }
    }

    private static void handleGetUITree(HelperAccessibilityService service, String id,
                                         ResponseCallback callback) {
        if (service == null) { sendError(callback, id, "Service not running"); return; }
        mainHandler.post(() -> {
            JsonArray tree = service.getUITree();
            JsonObject result = new JsonObject();
            result.add("elements", tree);
            sendOkJson(callback, id, result);
        });
    }

    private static void handleGetScreenSize(HelperAccessibilityService service, String id,
                                             ResponseCallback callback) {
        if (service == null) { sendError(callback, id, "Service not running"); return; }
        int[] size = service.getScreenSize();
        JsonObject result = new JsonObject();
        result.addProperty("width", size[0]);
        result.addProperty("height", size[1]);
        sendOkJson(callback, id, result);
    }

    private static void handleGetDeviceInfo(HelperAccessibilityService service, String id,
                                             ResponseCallback callback) {
        if (service == null) { sendError(callback, id, "Service not running"); return; }
        sendOkJson(callback, id, service.getDeviceInfo());
    }

    private static void handleGetForegroundApp(HelperAccessibilityService service, String id,
                                                ResponseCallback callback) {
        if (service == null) { sendError(callback, id, "Service not running"); return; }
        mainHandler.post(() -> {
            // getRootInActiveWindow package is the foreground app
            AccessibilityNodeInfo root = service.getRootInActiveWindow();
            String pkg = "";
            if (root != null) {
                pkg = root.getPackageName() != null ? root.getPackageName().toString() : "";
                root.recycle();
            }
            sendOk(callback, id, pkg);
        });
    }

    private static void handleLaunchApp(HelperAccessibilityService service, String id,
                                         JsonObject params, ResponseCallback callback) {
        if (service == null) { sendError(callback, id, "Service not running"); return; }
        String packageName = params.get("package").getAsString();
        try {
            Context ctx = service.getApplicationContext();
            Intent intent = ctx.getPackageManager().getLaunchIntentForPackage(packageName);
            if (intent != null) {
                intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                ctx.startActivity(intent);
                sendOk(callback, id, "Launched: " + packageName);
            } else {
                sendError(callback, id, "No launch intent for: " + packageName);
            }
        } catch (Exception e) {
            sendError(callback, id, "Launch failed: " + e.getMessage());
        }
    }

    private static void handleForceStop(HelperAccessibilityService service, String id,
                                         JsonObject params, ResponseCallback callback) {
        // AccessibilityService cannot force-stop apps directly.
        // We'll try via shell if available, otherwise report limitation.
        String packageName = params.get("package").getAsString();
        try {
            Runtime.getRuntime().exec(new String[]{"am", "force-stop", packageName});
            sendOk(callback, id, "Force-stopped: " + packageName);
        } catch (Exception e) {
            sendError(callback, id, "Cannot force-stop without root/shell: " + e.getMessage());
        }
    }

    private static void handleListPackages(HelperAccessibilityService service, String id,
                                            JsonObject params, ResponseCallback callback) {
        if (service == null) { sendError(callback, id, "Service not running"); return; }
        boolean thirdPartyOnly = params.has("third_party_only") && params.get("third_party_only").getAsBoolean();

        PackageManager pm = service.getPackageManager();
        List<ApplicationInfo> apps = pm.getInstalledApplications(0);
        JsonArray packages = new JsonArray();

        for (ApplicationInfo app : apps) {
            if (thirdPartyOnly && (app.flags & ApplicationInfo.FLAG_SYSTEM) != 0) {
                continue;
            }
            packages.add(app.packageName);
        }

        sendOkJson(callback, id, packages);
    }

    // --- Response helpers ---

    private static void sendOk(ResponseCallback callback, String id, String result) {
        JsonObject resp = new JsonObject();
        resp.addProperty("id", id);
        resp.addProperty("status", "ok");
        resp.addProperty("result", result);
        callback.send(resp.toString());
    }

    private static void sendOkJson(ResponseCallback callback, String id, JsonObject result) {
        JsonObject resp = new JsonObject();
        resp.addProperty("id", id);
        resp.addProperty("status", "ok");
        resp.add("result", result);
        callback.send(resp.toString());
    }

    private static void sendOkJson(ResponseCallback callback, String id, JsonArray result) {
        JsonObject resp = new JsonObject();
        resp.addProperty("id", id);
        resp.addProperty("status", "ok");
        resp.add("result", result);
        callback.send(resp.toString());
    }

    private static void sendError(ResponseCallback callback, String id, String error) {
        JsonObject resp = new JsonObject();
        resp.addProperty("id", id);
        resp.addProperty("status", "error");
        resp.addProperty("error", error);
        callback.send(resp.toString());
    }
}
