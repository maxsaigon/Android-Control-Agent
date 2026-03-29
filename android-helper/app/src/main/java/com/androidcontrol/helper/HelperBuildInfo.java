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
