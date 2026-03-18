package com.androidcontrol.helper;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.GestureDescription;
import android.content.Intent;
import android.graphics.Path;
import android.os.Build;
import android.os.Bundle;
import android.util.DisplayMetrics;
import android.util.Log;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;

/**
 * AccessibilityService that provides device control capabilities.
 *
 * Capabilities:
 * - Read UI tree (getRootInActiveWindow)
 * - Tap/swipe via dispatchGesture
 * - Click/set text on nodes via performAction
 * - Global actions (Back, Home, Recents, Notifications)
 * - Screenshot (API 28+)
 */
public class HelperAccessibilityService extends AccessibilityService {

    private static final String TAG = "ACHelper";
    private static HelperAccessibilityService instance;

    @Override
    public void onServiceConnected() {
        super.onServiceConnected();
        instance = this;
        Log.i(TAG, "AccessibilityService connected");

        // Start WebSocket service
        Intent wsIntent = new Intent(this, WebSocketService.class);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(wsIntent);
        } else {
            startService(wsIntent);
        }
    }

    @Override
    public void onAccessibilityEvent(AccessibilityEvent event) {
        // We primarily use on-demand queries, not event-driven
    }

    @Override
    public void onInterrupt() {
        Log.w(TAG, "AccessibilityService interrupted");
    }

    @Override
    public void onDestroy() {
        instance = null;
        super.onDestroy();
        Log.i(TAG, "AccessibilityService destroyed");
    }

    public static HelperAccessibilityService getInstance() {
        return instance;
    }

    // --- Gesture Actions ---

    /**
     * Tap at screen coordinates using dispatchGesture.
     */
    public void tap(int x, int y, GestureCallback callback) {
        Path path = new Path();
        path.moveTo(x, y);

        GestureDescription.StrokeDescription stroke =
                new GestureDescription.StrokeDescription(path, 0, 50);

        GestureDescription gesture = new GestureDescription.Builder()
                .addStroke(stroke)
                .build();

        dispatchGesture(gesture, new GestureResultCallback() {
            @Override
            public void onCompleted(GestureDescription gestureDescription) {
                if (callback != null) callback.onSuccess("Tapped at (" + x + ", " + y + ")");
            }

            @Override
            public void onCancelled(GestureDescription gestureDescription) {
                if (callback != null) callback.onError("Tap gesture cancelled");
            }
        }, null);
    }

    /**
     * Swipe from (x1,y1) to (x2,y2) with specified duration.
     */
    public void swipe(int x1, int y1, int x2, int y2, int durationMs, GestureCallback callback) {
        Path path = new Path();
        path.moveTo(x1, y1);
        path.lineTo(x2, y2);

        GestureDescription.StrokeDescription stroke =
                new GestureDescription.StrokeDescription(path, 0, durationMs);

        GestureDescription gesture = new GestureDescription.Builder()
                .addStroke(stroke)
                .build();

        dispatchGesture(gesture, new GestureResultCallback() {
            @Override
            public void onCompleted(GestureDescription gestureDescription) {
                if (callback != null) callback.onSuccess(
                        "Swiped (" + x1 + "," + y1 + ") → (" + x2 + "," + y2 + ")");
            }

            @Override
            public void onCancelled(GestureDescription gestureDescription) {
                if (callback != null) callback.onError("Swipe gesture cancelled");
            }
        }, null);
    }

    /**
     * Long press at coordinates (swipe to same point with long duration).
     */
    public void longPress(int x, int y, int durationMs, GestureCallback callback) {
        Path path = new Path();
        path.moveTo(x, y);

        GestureDescription.StrokeDescription stroke =
                new GestureDescription.StrokeDescription(path, 0, Math.max(durationMs, 500));

        GestureDescription gesture = new GestureDescription.Builder()
                .addStroke(stroke)
                .build();

        dispatchGesture(gesture, new GestureResultCallback() {
            @Override
            public void onCompleted(GestureDescription gestureDescription) {
                if (callback != null) callback.onSuccess("Long pressed at (" + x + ", " + y + ")");
            }

            @Override
            public void onCancelled(GestureDescription gestureDescription) {
                if (callback != null) callback.onError("Long press cancelled");
            }
        }, null);
    }

    // --- Node Actions ---

    /**
     * Set text on the currently focused EditText.
     */
    public boolean typeText(String text) {
        AccessibilityNodeInfo root = getRootInActiveWindow();
        if (root == null) return false;

        AccessibilityNodeInfo focused = root.findFocus(AccessibilityNodeInfo.FOCUS_INPUT);
        if (focused != null) {
            Bundle args = new Bundle();
            args.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text);
            boolean result = focused.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args);
            focused.recycle();
            root.recycle();
            return result;
        }

        // Fallback: find first EditText
        AccessibilityNodeInfo editText = findFirstEditText(root);
        if (editText != null) {
            Bundle args = new Bundle();
            args.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text);
            boolean result = editText.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args);
            editText.recycle();
            root.recycle();
            return result;
        }

        root.recycle();
        return false;
    }

    /**
     * Click a node found by text or content description.
     */
    public boolean clickByText(String text) {
        AccessibilityNodeInfo root = getRootInActiveWindow();
        if (root == null) return false;

        // Try by text
        java.util.List<AccessibilityNodeInfo> nodes = root.findAccessibilityNodeInfosByText(text);
        for (AccessibilityNodeInfo node : nodes) {
            if (node.isClickable()) {
                boolean result = node.performAction(AccessibilityNodeInfo.ACTION_CLICK);
                node.recycle();
                root.recycle();
                return result;
            }
            // Try parent if node isn't clickable
            AccessibilityNodeInfo parent = node.getParent();
            if (parent != null && parent.isClickable()) {
                boolean result = parent.performAction(AccessibilityNodeInfo.ACTION_CLICK);
                parent.recycle();
                node.recycle();
                root.recycle();
                return result;
            }
            if (parent != null) parent.recycle();
            node.recycle();
        }

        root.recycle();
        return false;
    }

    // --- Global Actions ---

    public boolean goBack() {
        return performGlobalAction(GLOBAL_ACTION_BACK);
    }

    public boolean goHome() {
        return performGlobalAction(GLOBAL_ACTION_HOME);
    }

    public boolean openRecents() {
        return performGlobalAction(GLOBAL_ACTION_RECENTS);
    }

    public boolean openNotifications() {
        return performGlobalAction(GLOBAL_ACTION_NOTIFICATIONS);
    }

    // --- UI Tree ---

    /**
     * Get UI tree as JSON array.
     */
    public JsonArray getUITree() {
        JsonArray elements = new JsonArray();
        AccessibilityNodeInfo root = getRootInActiveWindow();
        if (root == null) return elements;

        traverseTree(root, elements, 0);
        root.recycle();
        return elements;
    }

    private int traverseTree(AccessibilityNodeInfo node, JsonArray elements, int index) {
        if (node == null) return index;

        JsonObject el = new JsonObject();
        el.addProperty("index", index);
        el.addProperty("text", safeString(node.getText()));
        el.addProperty("resource_id", safeString(node.getViewIdResourceName()));
        el.addProperty("class", safeString(node.getClassName()));
        el.addProperty("package", safeString(node.getPackageName()));
        el.addProperty("content_desc", safeString(node.getContentDescription()));
        el.addProperty("clickable", node.isClickable());
        el.addProperty("scrollable", node.isScrollable());

        // Bounds
        android.graphics.Rect bounds = new android.graphics.Rect();
        node.getBoundsInScreen(bounds);
        JsonArray boundsArr = new JsonArray();
        boundsArr.add(bounds.left);
        boundsArr.add(bounds.top);
        boundsArr.add(bounds.right);
        boundsArr.add(bounds.bottom);
        el.add("bounds", boundsArr);

        elements.add(el);
        index++;

        // Recurse children
        for (int i = 0; i < node.getChildCount(); i++) {
            AccessibilityNodeInfo child = node.getChild(i);
            if (child != null) {
                index = traverseTree(child, elements, index);
                child.recycle();
            }
        }

        return index;
    }

    // --- Screen Info ---

    public int[] getScreenSize() {
        DisplayMetrics metrics = getResources().getDisplayMetrics();
        return new int[]{metrics.widthPixels, metrics.heightPixels};
    }

    public JsonObject getDeviceInfo() {
        JsonObject info = new JsonObject();
        info.addProperty("android_version", Build.VERSION.RELEASE);
        info.addProperty("device_model", Build.MODEL);
        info.addProperty("sdk_int", Build.VERSION.SDK_INT);
        info.addProperty("manufacturer", Build.MANUFACTURER);
        return info;
    }

    // --- Helpers ---

    private AccessibilityNodeInfo findFirstEditText(AccessibilityNodeInfo node) {
        if (node == null) return null;
        String className = safeString(node.getClassName());
        if (className.contains("EditText")) {
            return node;
        }
        for (int i = 0; i < node.getChildCount(); i++) {
            AccessibilityNodeInfo child = node.getChild(i);
            if (child != null) {
                AccessibilityNodeInfo found = findFirstEditText(child);
                if (found != null) return found;
                child.recycle();
            }
        }
        return null;
    }

    private String safeString(CharSequence cs) {
        return cs != null ? cs.toString() : "";
    }

    // --- Callback interface ---

    public interface GestureCallback {
        void onSuccess(String result);
        void onError(String error);
    }
}
