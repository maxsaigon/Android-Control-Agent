package com.androidcontrol.helper;

import android.app.Activity;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageInfo;
import android.content.pm.PackageInstaller;
import android.content.pm.PackageManager;
import android.content.pm.Signature;
import android.net.Uri;
import android.os.Build;
import android.provider.Settings;
import android.widget.Toast;
import com.google.gson.JsonObject;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URI;
import java.security.MessageDigest;
import java.util.HashSet;
import java.util.Set;

/** Installs only server-selected, same-certificate upgrades. No task scheduling here. */
public final class HelperUpdater {
    private static Context context;
    private static boolean running;
    private static Intent confirmation;
    private static final String CHANNEL = "helper_updates";
    private static final int NOTIFICATION = 1002;

    public static synchronized void initialize(Context app) {
        context = app.getApplicationContext();
        SharedPreferences prefs = prefs(context);
        if (prefs.getInt("target", 0) == BuildConfig.VERSION_CODE) {
            state("installed", "");
        } else if (!running && "downloading".equals(status(context))) {
            state("failed", "Download interrupted; retry from dashboard");
        }
    }

    private static SharedPreferences prefs(Context app) {
        return app.getSharedPreferences("helper_update", Context.MODE_PRIVATE);
    }

    public static String status(Context app) {
        return prefs(app).getString("state", "idle");
    }

    public static JsonObject metadata() {
        JsonObject result = new JsonObject();
        if (context == null) return result;
        SharedPreferences p = prefs(context);
        result.addProperty("state", p.getString("state", "idle"));
        result.addProperty("job_id", p.getInt("job_id", 0));
        result.addProperty("error", p.getString("error", ""));
        result.addProperty("can_install", context.getPackageManager().canRequestPackageInstalls());
        return result;
    }

    static void state(String state, String error) {
        prefs(context).edit().putString("state", state).putString("error", error).commit();
    }

    public static synchronized String start(JsonObject release) {
        if (context == null) throw new IllegalStateException("Helper service is not ready");
        int job = release.get("job_id").getAsInt();
        if (running || "installing".equals(status(context)) || "waiting_user_action".equals(status(context))) {
            if (prefs(context).getInt("job_id", 0) == job) return status(context);
            throw new IllegalStateException("An update is already in progress");
        }
        int version = release.get("version_code").getAsInt();
        if (version <= BuildConfig.VERSION_CODE) throw new IllegalArgumentException("Update must increase versionCode");
        if (!context.getPackageManager().canRequestPackageInstalls()) {
            state("needs_permission", "Open Helper and allow updates, then retry on dashboard");
            throw new IllegalStateException("Allow installation from this Helper first");
        }
        prefs(context).edit().putInt("target", version).putInt("job_id", job).commit();
        running = true;
        state("downloading", "");
        new Thread(() -> {
            try { downloadAndInstall(release); }
            catch (Exception e) { state("failed", e.getMessage() == null ? e.toString() : e.getMessage()); }
            finally { synchronized (HelperUpdater.class) { running = false; } }
        }, "helper-update").start();
        return "downloading";
    }

    private static void downloadAndInstall(JsonObject release) throws Exception {
        String base = new ConnectionConfig(context).getServerUrl();
        if (!base.startsWith("http")) base = "https://" + base;
        URI origin = new URI(base);
        URI url = origin.resolve(release.get("download_path").getAsString());
        if (!"https".equals(url.getScheme()) || !origin.getAuthority().equals(url.getAuthority())) {
            throw new SecurityException("Updates require HTTPS on the configured server");
        }
        long size = release.get("file_size_bytes").getAsLong();
        if (size <= 0 || size > 150L * 1024 * 1024) throw new IllegalArgumentException("Invalid APK size");
        File apk = new File(context.getCacheDir(), "helper-update.apk");
        if (apk.getParentFile().getUsableSpace() < size * 2) throw new IllegalStateException("Not enough free storage");
        HttpURLConnection conn = (HttpURLConnection) url.toURL().openConnection();
        conn.setConnectTimeout(15000);
        conn.setReadTimeout(30000);
        conn.setInstanceFollowRedirects(false);
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        try {
            if (conn.getResponseCode() != 200) throw new IllegalStateException("APK download HTTP " + conn.getResponseCode());
            long received = 0;
            try (InputStream in = conn.getInputStream(); OutputStream out = new FileOutputStream(apk)) {
                byte[] buffer = new byte[65536];
                int count;
                while ((count = in.read(buffer)) != -1) {
                    received += count;
                    if (received > size) throw new SecurityException("APK exceeds release size");
                    out.write(buffer, 0, count);
                    digest.update(buffer, 0, count);
                }
            }
            if (received != size || !hex(digest.digest()).equalsIgnoreCase(release.get("sha256").getAsString())) {
                throw new SecurityException("APK checksum or size mismatch");
            }
            PackageManager pm = context.getPackageManager();
            PackageInfo candidate = pm.getPackageArchiveInfo(apk.getAbsolutePath(), PackageManager.GET_SIGNING_CERTIFICATES);
            PackageInfo current = pm.getPackageInfo(context.getPackageName(), PackageManager.GET_SIGNING_CERTIFICATES);
            if (candidate == null || !context.getPackageName().equals(candidate.packageName)
                    || candidate.getLongVersionCode() != release.get("version_code").getAsInt()
                    || candidate.getLongVersionCode() <= current.getLongVersionCode()
                    || !signers(candidate).equals(signers(current))) {
                throw new SecurityException("APK package, version or certificate mismatch");
            }
            PackageInstaller installer = pm.getPackageInstaller();
            PackageInstaller.SessionParams params = new PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL);
            params.setAppPackageName(context.getPackageName());
            params.setSize(size);
            if (Build.VERSION.SDK_INT >= 31) params.setRequireUserAction(PackageInstaller.SessionParams.USER_ACTION_NOT_REQUIRED);
            int sessionId = installer.createSession(params);
            try (PackageInstaller.Session session = installer.openSession(sessionId)) {
                try (InputStream in = new FileInputStream(apk); OutputStream out = session.openWrite("base.apk", 0, size)) {
                    byte[] buffer = new byte[65536];
                    int count;
                    while ((count = in.read(buffer)) != -1) out.write(buffer, 0, count);
                    session.fsync(out);
                }
                Intent result = new Intent(context, UpdateReceiver.class);
                result.putExtra("update_session", sessionId);
                int flags = PendingIntent.FLAG_UPDATE_CURRENT;
                if (Build.VERSION.SDK_INT >= 31) flags |= PendingIntent.FLAG_MUTABLE;
                PendingIntent callback = PendingIntent.getBroadcast(context, sessionId, result, flags);
                prefs(context).edit().putInt("session_id", sessionId).commit();
                state("installing", "");
                session.commit(callback.getIntentSender());
            } catch (Exception e) {
                installer.abandonSession(sessionId);
                throw e;
            }
        } finally {
            conn.disconnect();
            apk.delete();
        }
    }

    private static Set<String> signers(PackageInfo info) {
        if (info.signingInfo == null) throw new SecurityException("Unsigned APK");
        Set<String> result = new HashSet<>();
        for (Signature signature : info.signingInfo.getApkContentsSigners()) result.add(signature.toCharsString());
        if (result.isEmpty()) throw new SecurityException("Unsigned APK");
        return result;
    }

    private static String hex(byte[] bytes) {
        StringBuilder result = new StringBuilder();
        for (byte b : bytes) result.append(String.format("%02x", b & 255));
        return result.toString();
    }

    static void installResult(Context app, Intent result) {
        initialize(app);
        if (result.getIntExtra("update_session", -1) != prefs(context).getInt("session_id", -2)) return;
        int status = result.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE);
        if (status == PackageInstaller.STATUS_PENDING_USER_ACTION) {
            confirmation = result.getParcelableExtra(Intent.EXTRA_INTENT);
            state("waiting_user_action", "Confirm installation on the device");
            if (confirmation != null) {
                NotificationManager nm = context.getSystemService(NotificationManager.class);
                nm.createNotificationChannel(new NotificationChannel(CHANNEL, "Helper updates", NotificationManager.IMPORTANCE_HIGH));
                PendingIntent action = PendingIntent.getActivity(context, 0, confirmation,
                        PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
                nm.notify(NOTIFICATION, new Notification.Builder(context, CHANNEL)
                        .setSmallIcon(android.R.drawable.stat_sys_download_done)
                        .setContentTitle("Helper update ready")
                        .setContentText("Tap to confirm installation")
                        .setContentIntent(action).setAutoCancel(true).build());
            }
        } else if (status == PackageInstaller.STATUS_SUCCESS) {
            state("installed", "");
        } else {
            confirmation = null;
            state("failed", result.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE));
        }
    }

    public static void continueInstall(Activity activity) {
        if (!activity.getPackageManager().canRequestPackageInstalls()) {
            activity.startActivity(new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                    Uri.parse("package:" + activity.getPackageName())));
        } else if (confirmation != null) {
            activity.startActivity(confirmation);
        } else {
            Toast.makeText(activity, "Updates allowed. Start/retry from dashboard; check notifications for pending installation.", Toast.LENGTH_LONG).show();
        }
    }
}
