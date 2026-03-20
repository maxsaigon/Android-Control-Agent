package com.androidcontrol.helper;

import android.app.Activity;
import android.content.Intent;
import android.os.Build;
import android.os.Bundle;
import android.provider.Settings;
import android.util.Log;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.RadioButton;
import android.widget.RadioGroup;
import android.widget.TextView;
import android.view.Gravity;
import android.view.View;
import android.graphics.Color;
import android.graphics.Typeface;

import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.NetworkInterface;
import java.util.Enumeration;

/**
 * Main activity with dual connection mode UI:
 * - LAN Mode: shows local IP + WS port (original behavior)
 * - Cloud Mode: input fields for server URL + device token
 */
public class MainActivity extends Activity {

    private static final String TAG = "ACHelper.Main";

    private ConnectionConfig config;
    private TextView statusText;
    private LinearLayout lanInfoLayout;
    private LinearLayout cloudConfigLayout;
    private EditText serverUrlInput;
    private EditText tokenInput;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        config = new ConnectionConfig(this);

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setGravity(Gravity.CENTER_HORIZONTAL);
        root.setPadding(48, 48, 48, 48);
        root.setBackgroundColor(Color.parseColor("#1a1a2e"));

        // Title
        TextView title = new TextView(this);
        title.setText("AC Helper");
        title.setTextSize(28);
        title.setTextColor(Color.WHITE);
        title.setTypeface(null, Typeface.BOLD);
        title.setGravity(Gravity.CENTER);
        root.addView(title);

        // Status
        statusText = new TextView(this);
        statusText.setTextSize(14);
        statusText.setTextColor(Color.parseColor("#aaaaaa"));
        statusText.setGravity(Gravity.CENTER);
        statusText.setPadding(0, 24, 0, 24);
        root.addView(statusText);

        // ─── Mode Selector ───
        TextView modeLabel = new TextView(this);
        modeLabel.setText("Connection Mode");
        modeLabel.setTextSize(16);
        modeLabel.setTextColor(Color.WHITE);
        modeLabel.setTypeface(null, Typeface.BOLD);
        modeLabel.setPadding(0, 24, 0, 8);
        root.addView(modeLabel);

        RadioGroup modeGroup = new RadioGroup(this);
        modeGroup.setOrientation(RadioGroup.HORIZONTAL);

        RadioButton lanRadio = new RadioButton(this);
        lanRadio.setText("🏠 LAN");
        lanRadio.setTextColor(Color.WHITE);
        lanRadio.setId(View.generateViewId());

        RadioButton cloudRadio = new RadioButton(this);
        cloudRadio.setText("☁️ Cloud");
        cloudRadio.setTextColor(Color.WHITE);
        cloudRadio.setId(View.generateViewId());

        modeGroup.addView(lanRadio);
        modeGroup.addView(cloudRadio);
        root.addView(modeGroup);

        // ─── LAN Info ───
        lanInfoLayout = new LinearLayout(this);
        lanInfoLayout.setOrientation(LinearLayout.VERTICAL);
        lanInfoLayout.setPadding(0, 16, 0, 16);

        TextView ipText = new TextView(this);
        String ip = getDeviceIP();
        ipText.setText("WebSocket: ws://" + ip + ":38301");
        ipText.setTextSize(14);
        ipText.setTextColor(Color.parseColor("#e94560"));
        ipText.setGravity(Gravity.CENTER);
        lanInfoLayout.addView(ipText);

        root.addView(lanInfoLayout);

        // ─── Cloud Config ───
        cloudConfigLayout = new LinearLayout(this);
        cloudConfigLayout.setOrientation(LinearLayout.VERTICAL);
        cloudConfigLayout.setPadding(0, 16, 0, 16);

        TextView urlLabel = new TextView(this);
        urlLabel.setText("Server URL");
        urlLabel.setTextColor(Color.parseColor("#cccccc"));
        urlLabel.setTextSize(12);
        cloudConfigLayout.addView(urlLabel);

        serverUrlInput = new EditText(this);
        serverUrlInput.setHint("e.g. abc.com or 192.168.1.100:8000");
        serverUrlInput.setTextColor(Color.WHITE);
        serverUrlInput.setHintTextColor(Color.parseColor("#666666"));
        serverUrlInput.setBackgroundColor(Color.parseColor("#16213e"));
        serverUrlInput.setPadding(16, 12, 16, 12);
        serverUrlInput.setText(config.getServerUrl());
        serverUrlInput.setSingleLine(true);
        cloudConfigLayout.addView(serverUrlInput);

        TextView tokenLabel = new TextView(this);
        tokenLabel.setText("Device Token");
        tokenLabel.setTextColor(Color.parseColor("#cccccc"));
        tokenLabel.setTextSize(12);
        tokenLabel.setPadding(0, 16, 0, 0);
        cloudConfigLayout.addView(tokenLabel);

        tokenInput = new EditText(this);
        tokenInput.setHint("Paste token from dashboard");
        tokenInput.setTextColor(Color.WHITE);
        tokenInput.setHintTextColor(Color.parseColor("#666666"));
        tokenInput.setBackgroundColor(Color.parseColor("#16213e"));
        tokenInput.setPadding(16, 12, 16, 12);
        tokenInput.setText(config.getDeviceToken());
        tokenInput.setSingleLine(true);
        cloudConfigLayout.addView(tokenInput);

        root.addView(cloudConfigLayout);

        // ─── Save & Connect Button ───
        Button connectBtn = new Button(this);
        connectBtn.setText("💾  Save & Connect");
        connectBtn.setBackgroundColor(Color.parseColor("#e94560"));
        connectBtn.setTextColor(Color.WHITE);
        connectBtn.setOnClickListener(v -> saveAndRestart());
        LinearLayout.LayoutParams btnParams = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT);
        btnParams.setMargins(0, 24, 0, 16);
        connectBtn.setLayoutParams(btnParams);
        root.addView(connectBtn);

        // ─── Accessibility Settings Button ───
        Button accessibilityBtn = new Button(this);
        accessibilityBtn.setText("⚙️  Accessibility Settings");
        accessibilityBtn.setBackgroundColor(Color.parseColor("#16213e"));
        accessibilityBtn.setTextColor(Color.WHITE);
        accessibilityBtn.setOnClickListener(v -> {
            Intent intent = new Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS);
            startActivity(intent);
        });
        LinearLayout.LayoutParams accBtnParams = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT);
        accBtnParams.setMargins(0, 0, 0, 0);
        accessibilityBtn.setLayoutParams(accBtnParams);
        root.addView(accessibilityBtn);

        // ─── Mode toggle logic ───
        modeGroup.setOnCheckedChangeListener((group, checkedId) -> {
            if (checkedId == lanRadio.getId()) {
                lanInfoLayout.setVisibility(View.VISIBLE);
                cloudConfigLayout.setVisibility(View.GONE);
            } else {
                lanInfoLayout.setVisibility(View.GONE);
                cloudConfigLayout.setVisibility(View.VISIBLE);
            }
        });

        // Set initial state
        if (config.isCloudMode()) {
            cloudRadio.setChecked(true);
            lanInfoLayout.setVisibility(View.GONE);
            cloudConfigLayout.setVisibility(View.VISIBLE);
        } else {
            lanRadio.setChecked(true);
            lanInfoLayout.setVisibility(View.VISIBLE);
            cloudConfigLayout.setVisibility(View.GONE);
        }

        setContentView(root);
    }

    @Override
    protected void onResume() {
        super.onResume();
        updateStatus();
    }

    private void saveAndRestart() {
        // Determine which radio is selected
        boolean isCloud = cloudConfigLayout.getVisibility() == View.VISIBLE;

        if (isCloud) {
            String url = serverUrlInput.getText().toString().trim();
            String token = tokenInput.getText().toString().trim();

            if (url.isEmpty() || token.isEmpty()) {
                statusText.setText("❌ Please fill in both Server URL and Device Token");
                statusText.setTextColor(Color.parseColor("#ff4444"));
                return;
            }

            config.setMode(ConnectionConfig.MODE_CLOUD);
            config.setServerUrl(url);
            config.setDeviceToken(token);
        } else {
            config.setMode(ConnectionConfig.MODE_LAN);
        }

        // Restart WebSocket service with new config
        Intent wsIntent = new Intent(this, WebSocketService.class);
        wsIntent.putExtra(WebSocketService.EXTRA_MODE, config.getMode());
        stopService(wsIntent);

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(wsIntent);
        } else {
            startService(wsIntent);
        }

        updateStatus();
        statusText.setText("✅ Configuration saved! Connecting...");
        statusText.setTextColor(Color.parseColor("#00ff88"));
    }

    private void updateStatus() {
        HelperAccessibilityService service = HelperAccessibilityService.getInstance();
        StringBuilder sb = new StringBuilder();

        if (service != null) {
            sb.append("✅ Accessibility: ACTIVE\n");
        } else {
            sb.append("❌ Accessibility: INACTIVE\n");
        }

        if (config.isCloudMode()) {
            sb.append("☁️ Mode: CLOUD\n");
            sb.append("📡 " + config.getServerUrl());
        } else {
            sb.append("🏠 Mode: LAN\n");
            sb.append("🔌 ws://" + getDeviceIP() + ":38301");
        }

        statusText.setText(sb.toString());
        statusText.setTextColor(service != null ?
                Color.parseColor("#00ff88") : Color.parseColor("#ff4444"));
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
