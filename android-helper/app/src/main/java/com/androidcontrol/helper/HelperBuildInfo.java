package com.androidcontrol.helper;

import com.google.gson.JsonObject;

/**
 * Centralizes helper build metadata so the app, logs, and server all report
 * the same release identifiers.
 */
public final class HelperBuildInfo {

    private HelperBuildInfo() {}

    public static JsonObject asJson() {
        JsonObject info = new JsonObject();
        info.addProperty("release_name", BuildConfig.HELPER_RELEASE_NAME);
        info.addProperty("version_name", BuildConfig.VERSION_NAME);
        info.addProperty("version_code", BuildConfig.VERSION_CODE);
        info.addProperty("build_sha", BuildConfig.HELPER_BUILD_SHA);
        info.addProperty("build_time_utc", BuildConfig.HELPER_BUILD_TIME_UTC);
        info.addProperty("package_name", BuildConfig.APPLICATION_ID);
        info.addProperty("protocol_version", 1);
        info.addProperty("sdk_int", android.os.Build.VERSION.SDK_INT);
        com.google.gson.JsonArray capabilities = new com.google.gson.JsonArray();
        for (String action : new String[]{"tap", "swipe", "long_press", "type_text",
                "click_node", "global_action", "get_ui_tree", "get_screen_size", "start_stream"}) {
            capabilities.add(action);
        }
        if (android.os.Build.VERSION.SDK_INT >= 30) capabilities.add("screenshot");
        info.add("capabilities", capabilities);
        HelperAccessibilityService service = HelperAccessibilityService.getInstance();
        if (service != null) {
            int[] size = service.getScreenSize();
            info.addProperty("screen_width", size[0]);
            info.addProperty("screen_height", size[1]);
        }
        return info;
    }

    public static String shortLabel() {
        return BuildConfig.VERSION_NAME + " (" + BuildConfig.VERSION_CODE + ")";
    }

    public static String releaseLabel() {
        return BuildConfig.HELPER_RELEASE_NAME + " " + shortLabel();
    }

    public static String debugLabel() {
        return "sha " + BuildConfig.HELPER_BUILD_SHA + " • " + BuildConfig.HELPER_BUILD_TIME_UTC + " UTC";
    }
}
