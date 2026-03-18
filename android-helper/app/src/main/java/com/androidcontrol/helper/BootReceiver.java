package com.androidcontrol.helper;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.os.Build;
import android.util.Log;

/**
 * Starts WebSocket service on device boot.
 *
 * Note: The AccessibilityService will auto-start if enabled in settings,
 * but we also start the WebSocket service explicitly.
 */
public class BootReceiver extends BroadcastReceiver {

    private static final String TAG = "ACHelper.Boot";

    @Override
    public void onReceive(Context context, Intent intent) {
        if (Intent.ACTION_BOOT_COMPLETED.equals(intent.getAction())) {
            Log.i(TAG, "Boot completed — starting WebSocket service");
            Intent serviceIntent = new Intent(context, WebSocketService.class);
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(serviceIntent);
            } else {
                context.startService(serviceIntent);
            }
        }
    }
}
