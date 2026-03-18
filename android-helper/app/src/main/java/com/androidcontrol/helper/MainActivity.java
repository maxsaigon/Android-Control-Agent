package com.androidcontrol.helper;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.provider.Settings;
import android.util.Log;
import android.widget.LinearLayout;
import android.widget.Button;
import android.widget.TextView;
import android.view.Gravity;
import android.graphics.Color;

import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.NetworkInterface;
import java.util.Enumeration;

/**
 * Simple status activity — shows service status and provides
 * a button to open Accessibility settings.
 */
public class MainActivity extends Activity {

    private static final String TAG = "ACHelper.Main";
    private TextView statusText;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        layout.setGravity(Gravity.CENTER);
        layout.setPadding(48, 48, 48, 48);
        layout.setBackgroundColor(Color.parseColor("#1a1a2e"));

        // Title
        TextView title = new TextView(this);
        title.setText("AC Helper");
        title.setTextSize(28);
        title.setTextColor(Color.WHITE);
        title.setGravity(Gravity.CENTER);
        layout.addView(title);

        // Status
        statusText = new TextView(this);
        statusText.setTextSize(16);
        statusText.setTextColor(Color.parseColor("#aaaaaa"));
        statusText.setGravity(Gravity.CENTER);
        statusText.setPadding(0, 32, 0, 32);
        layout.addView(statusText);

        // IP info
        TextView ipText = new TextView(this);
        String ip = getDeviceIP();
        ipText.setText("WebSocket: ws://" + ip + ":38301");
        ipText.setTextSize(14);
        ipText.setTextColor(Color.parseColor("#e94560"));
        ipText.setGravity(Gravity.CENTER);
        ipText.setPadding(0, 0, 0, 48);
        layout.addView(ipText);

        // Enable Accessibility button
        Button enableBtn = new Button(this);
        enableBtn.setText("Open Accessibility Settings");
        enableBtn.setOnClickListener(v -> {
            Intent intent = new Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS);
            startActivity(intent);
        });
        layout.addView(enableBtn);

        setContentView(layout);
    }

    @Override
    protected void onResume() {
        super.onResume();
        updateStatus();
    }

    private void updateStatus() {
        HelperAccessibilityService service = HelperAccessibilityService.getInstance();
        if (service != null) {
            statusText.setText("✅ Accessibility Service: ACTIVE\n🔌 WebSocket Server: RUNNING");
            statusText.setTextColor(Color.parseColor("#00ff88"));
        } else {
            statusText.setText("❌ Accessibility Service: INACTIVE\n\nPlease enable 'AC Helper' in\nAccessibility Settings");
            statusText.setTextColor(Color.parseColor("#ff4444"));
        }
    }

    private String getDeviceIP() {
        try {
            Enumeration<NetworkInterface> interfaces = NetworkInterface.getNetworkInterfaces();
            while (interfaces.hasMoreElements()) {
                NetworkInterface ni = interfaces.nextElement();
                Enumeration<InetAddress> addresses = ni.getInetAddresses();
                while (addresses.hasMoreElements()) {
                    InetAddress addr = addresses.nextElement();
                    if (!addr.isLoopbackAddress() && addr instanceof Inet4Address) {
                        return addr.getHostAddress();
                    }
                }
            }
        } catch (Exception e) {
            Log.e(TAG, "Error getting IP", e);
        }
        return "unknown";
    }
}
