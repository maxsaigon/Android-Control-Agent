package com.androidcontrol.helper;

import android.app.Activity;
import android.content.Intent;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
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

import com.google.gson.Gson;
import com.google.gson.JsonObject;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.NetworkInterface;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.Enumeration;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * Main activity with dual connection mode UI:
 * - LAN Mode: shows local IP + WS port (original behavior)
 * - Cloud Mode: login-based registration (server URL + username + password + device name)
 *
 * Cloud flow: user enters credentials → app calls /api/device/register →
 * server auto-creates device + token → app connects WebSocket with token.
 * No manual token copying needed!
 */
public class MainActivity extends Activity {

    private static final String TAG = "ACHelper.Main";
    private static final Gson gson = new Gson();
    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private final Handler mainHandler = new Handler(Looper.getMainLooper());

    private ConnectionConfig config;
    private TextView statusText;
    private TextView versionText;
    private LinearLayout lanInfoLayout;
    private LinearLayout cloudConfigLayout;
    private EditText usernameInput;
    private EditText deviceNameInput;
    private Button connectBtn;
    private Runnable pollRunnable;

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
        title.setText(getString(R.string.app_name));
        title.setTextSize(28);
        title.setTextColor(Color.WHITE);
        title.setTypeface(null, Typeface.BOLD);
        title.setGravity(Gravity.CENTER);
        root.addView(title);

        versionText = new TextView(this);
        versionText.setText(buildVersionLabel());
        versionText.setTextSize(12);
        versionText.setTextColor(Color.parseColor("#9ea6d6"));
        versionText.setGravity(Gravity.CENTER);
        versionText.setPadding(0, 8, 0, 8);
        root.addView(versionText);

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
        ipText.setText("WebSocket: ws://" + ip + ":38301/?token=" + config.getLanToken());
        ipText.setTextSize(14);
        ipText.setTextColor(Color.parseColor("#e94560"));
        ipText.setGravity(Gravity.CENTER);
        ipText.setTextIsSelectable(true);
        lanInfoLayout.addView(ipText);

        root.addView(lanInfoLayout);

        // ─── Cloud Config ───
        cloudConfigLayout = new LinearLayout(this);
        cloudConfigLayout.setOrientation(LinearLayout.VERTICAL);
        cloudConfigLayout.setPadding(0, 16, 0, 16);

        // Username
        TextView usernameLabel = new TextView(this);
        usernameLabel.setText("Username");
        usernameLabel.setTextColor(Color.parseColor("#cccccc"));
        usernameLabel.setTextSize(12);
        usernameLabel.setPadding(0, 16, 0, 0);
        cloudConfigLayout.addView(usernameLabel);

        usernameInput = new EditText(this);
        usernameInput.setHint("e.g. admin");
        usernameInput.setTextColor(Color.WHITE);
        usernameInput.setHintTextColor(Color.parseColor("#666666"));
        usernameInput.setBackgroundColor(Color.parseColor("#16213e"));
        usernameInput.setPadding(16, 12, 16, 12);
        usernameInput.setText(config.getUsername());
        usernameInput.setSingleLine(true);
        cloudConfigLayout.addView(usernameInput);

        // Device Name
        TextView deviceNameLabel = new TextView(this);
        deviceNameLabel.setText("Device Name");
        deviceNameLabel.setTextColor(Color.parseColor("#cccccc"));
        deviceNameLabel.setTextSize(12);
        deviceNameLabel.setPadding(0, 16, 0, 0);
        cloudConfigLayout.addView(deviceNameLabel);

        deviceNameInput = new EditText(this);
        deviceNameInput.setHint("e.g. Pixel 7, Samsung A54...");
        deviceNameInput.setTextColor(Color.WHITE);
        deviceNameInput.setHintTextColor(Color.parseColor("#666666"));
        deviceNameInput.setBackgroundColor(Color.parseColor("#16213e"));
        deviceNameInput.setPadding(16, 12, 16, 12);
        String savedName = config.getDeviceName();
        if (savedName.isEmpty()) savedName = android.os.Build.MODEL;
        deviceNameInput.setText(savedName);
        deviceNameInput.setSingleLine(true);
        cloudConfigLayout.addView(deviceNameInput);

        root.addView(cloudConfigLayout);

        // ─── Save & Connect Button ───
        connectBtn = new Button(this);
        connectBtn.setText("Request Access");
        connectBtn.setBackgroundColor(Color.parseColor("#e94560"));
        connectBtn.setTextColor(Color.WHITE);
        connectBtn.setOnClickListener(v -> saveAndConnect());
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
        Log.i(TAG, "🚀 " + HelperBuildInfo.releaseLabel() + " | " + HelperBuildInfo.debugLabel());
    }

    @Override
    protected void onResume() {
        super.onResume();
        updateStatus();
        
        if (config.isCloudMode()) {
            if (!config.getLinkRequestId().isEmpty() && !config.hasToken()) {
                startPollingStatus();
            } else if (config.hasToken()) {
                connectBtn.setVisibility(View.GONE);
                usernameInput.setVisibility(View.GONE);
                deviceNameInput.setVisibility(View.GONE);
            }
        }
    }

    @Override
    protected void onPause() {
        super.onPause();
        stopPollingStatus();
    }

    private void saveAndConnect() {
        boolean isCloud = cloudConfigLayout.getVisibility() == View.VISIBLE;

        if (isCloud) {
            String username = usernameInput.getText().toString().trim();
            String deviceName = deviceNameInput.getText().toString().trim();

            if (username.isEmpty() || deviceName.isEmpty()) {
                statusText.setText("❌ Please fill in all fields");
                statusText.setTextColor(Color.parseColor("#ff4444"));
                return;
            }

            // Save config
            config.setMode(ConnectionConfig.MODE_CLOUD);
            config.setUsername(username);
            config.setDeviceName(deviceName);
            
            // clear old token if any
            config.setDeviceToken("");
            config.clearLinkRequestId();

            statusText.setText("🔄 Requesting access...");
            statusText.setTextColor(Color.parseColor("#ffaa00"));
            connectBtn.setEnabled(false);

            DeviceLinkClient.requestLink(config, username, deviceName, new DeviceLinkClient.LinkCallback() {
                @Override
                public void onPending(String requestId) {
                    config.setLinkRequestId(requestId);
                    statusText.setText("⏳ Waiting for admin approval...");
                    startPollingStatus();
                }

                @Override
                public void onApproved(String token) {
                    // Not expected here usually but handled
                    handleApproved(token);
                }

                @Override
                public void onRejected(String reason) {
                    statusText.setText("❌ Rejected: " + reason);
                    statusText.setTextColor(Color.parseColor("#ff4444"));
                    connectBtn.setEnabled(true);
                }

                @Override
                public void onError(String error) {
                    statusText.setText("❌ Error: " + error);
                    statusText.setTextColor(Color.parseColor("#ff4444"));
                    connectBtn.setEnabled(true);
                }
            });
        } else {
            config.setMode(ConnectionConfig.MODE_LAN);
            restartService();
            statusText.setText("✅ LAN mode saved!");
            statusText.setTextColor(Color.parseColor("#00ff88"));
        }
    }
    
    private void startPollingStatus() {
        if (pollRunnable != null) return;
        pollRunnable = new Runnable() {
            @Override
            public void run() {
                String reqId = config.getLinkRequestId();
                if (reqId.isEmpty() || config.hasToken()) {
                    stopPollingStatus();
                    return;
                }
                
                DeviceLinkClient.pollStatus(config, reqId, new DeviceLinkClient.LinkCallback() {
                    @Override
                    public void onPending(String requestId) {
                        statusText.setText("⏳ Waiting for admin approval...");
                    }

                    @Override
                    public void onApproved(String token) {
                        handleApproved(token);
                    }

                    @Override
                    public void onRejected(String reason) {
                        statusText.setText("❌ Rejected: " + reason);
                        statusText.setTextColor(Color.parseColor("#ff4444"));
                        connectBtn.setEnabled(true);
                        connectBtn.setText("Retry Request");
                        config.clearLinkRequestId();
                        stopPollingStatus();
                    }

                    @Override
                    public void onError(String error) {
                        // Keep polling silently
                    }
                });
                
                if (pollRunnable != null) {
                    mainHandler.postDelayed(this, 3000);
                }
            }
        };
        mainHandler.post(pollRunnable);
    }
    
    private void stopPollingStatus() {
        if (pollRunnable != null) {
            mainHandler.removeCallbacks(pollRunnable);
            pollRunnable = null;
        }
    }
    
    private void handleApproved(String token) {
        stopPollingStatus();
        config.setDeviceToken(token);
        config.clearLinkRequestId();
        
        statusText.setText("✅ Approved! Connecting...");
        statusText.setTextColor(Color.parseColor("#00ff88"));
        connectBtn.setVisibility(View.GONE);
        usernameInput.setVisibility(View.GONE);
        deviceNameInput.setVisibility(View.GONE);
        
        restartService();
    }

    private void restartService() {
        Intent wsIntent = new Intent(this, WebSocketService.class);
        wsIntent.putExtra(WebSocketService.EXTRA_MODE, config.getMode());
        stopService(wsIntent);

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(wsIntent);
        } else {
            startService(wsIntent);
        }

        updateStatus();
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
            if (!config.getDeviceName().isEmpty()) {
                sb.append("📱 ").append(config.getDeviceName());
            }
        } else {
            sb.append("🏠 Mode: LAN\n");
            sb.append("🔌 ws://" + getDeviceIP() + ":38301\n");
            sb.append("🔑 Token: " + config.getLanToken());
        }

        sb.append("\n🏷️ ").append(HelperBuildInfo.shortLabel());
        sb.append("\n🧾 ").append(HelperBuildInfo.debugLabel());

        statusText.setText(sb.toString());
        versionText.setText(buildVersionLabel());
        statusText.setTextColor(service != null ?
                Color.parseColor("#00ff88") : Color.parseColor("#ff4444"));
    }

    private String buildVersionLabel() {
        return HelperBuildInfo.releaseLabel() + "\n" + HelperBuildInfo.debugLabel();
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
