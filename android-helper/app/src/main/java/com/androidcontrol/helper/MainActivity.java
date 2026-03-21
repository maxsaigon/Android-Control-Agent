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
    private LinearLayout lanInfoLayout;
    private LinearLayout cloudConfigLayout;
    private EditText serverUrlInput;
    private EditText usernameInput;
    private EditText passwordInput;
    private EditText deviceNameInput;

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

        // Server URL
        TextView urlLabel = new TextView(this);
        urlLabel.setText("Server URL");
        urlLabel.setTextColor(Color.parseColor("#cccccc"));
        urlLabel.setTextSize(12);
        cloudConfigLayout.addView(urlLabel);

        serverUrlInput = new EditText(this);
        serverUrlInput.setHint("e.g. m.buonme.com");
        serverUrlInput.setTextColor(Color.WHITE);
        serverUrlInput.setHintTextColor(Color.parseColor("#666666"));
        serverUrlInput.setBackgroundColor(Color.parseColor("#16213e"));
        serverUrlInput.setPadding(16, 12, 16, 12);
        serverUrlInput.setText(config.getServerUrl());
        serverUrlInput.setSingleLine(true);
        cloudConfigLayout.addView(serverUrlInput);

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

        // Password
        TextView passwordLabel = new TextView(this);
        passwordLabel.setText("Password");
        passwordLabel.setTextColor(Color.parseColor("#cccccc"));
        passwordLabel.setTextSize(12);
        passwordLabel.setPadding(0, 16, 0, 0);
        cloudConfigLayout.addView(passwordLabel);

        passwordInput = new EditText(this);
        passwordInput.setHint("e.g. admin");
        passwordInput.setTextColor(Color.WHITE);
        passwordInput.setHintTextColor(Color.parseColor("#666666"));
        passwordInput.setBackgroundColor(Color.parseColor("#16213e"));
        passwordInput.setPadding(16, 12, 16, 12);
        passwordInput.setText(config.getPassword());
        passwordInput.setSingleLine(true);
        passwordInput.setInputType(android.text.InputType.TYPE_CLASS_TEXT |
                android.text.InputType.TYPE_TEXT_VARIATION_PASSWORD);
        cloudConfigLayout.addView(passwordInput);

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
        deviceNameInput.setText(config.getDeviceName());
        deviceNameInput.setSingleLine(true);
        cloudConfigLayout.addView(deviceNameInput);

        root.addView(cloudConfigLayout);

        // ─── Save & Connect Button ───
        Button connectBtn = new Button(this);
        connectBtn.setText("💾  Save & Connect");
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
    }

    @Override
    protected void onResume() {
        super.onResume();
        updateStatus();
    }

    private void saveAndConnect() {
        boolean isCloud = cloudConfigLayout.getVisibility() == View.VISIBLE;

        if (isCloud) {
            String url = serverUrlInput.getText().toString().trim();
            String username = usernameInput.getText().toString().trim();
            String password = passwordInput.getText().toString().trim();
            String deviceName = deviceNameInput.getText().toString().trim();

            if (url.isEmpty() || username.isEmpty() || password.isEmpty() || deviceName.isEmpty()) {
                statusText.setText("❌ Please fill in all fields");
                statusText.setTextColor(Color.parseColor("#ff4444"));
                return;
            }

            // Save config
            config.setMode(ConnectionConfig.MODE_CLOUD);
            config.setServerUrl(url);
            config.setUsername(username);
            config.setPassword(password);
            config.setDeviceName(deviceName);

            statusText.setText("🔄 Registering device...");
            statusText.setTextColor(Color.parseColor("#ffaa00"));

            // Register device in background thread, then connect
            executor.execute(() -> registerAndConnect(url, username, password, deviceName));
        } else {
            config.setMode(ConnectionConfig.MODE_LAN);
            restartService();
            statusText.setText("✅ LAN mode saved!");
            statusText.setTextColor(Color.parseColor("#00ff88"));
        }
    }

    /**
     * Call /api/device/register to get a token, then start WebSocket connection.
     * Runs on background thread.
     */
    private void registerAndConnect(String serverUrl, String username,
                                     String password, String deviceName) {
        try {
            // Build register URL
            String registerUrl = config.getRegisterUrl();
            Log.i(TAG, "📝 Registering at: " + registerUrl);

            // Make HTTP POST request
            URL url = new URL(registerUrl);
            HttpURLConnection conn = (HttpURLConnection) url.openConnection();
            conn.setRequestMethod("POST");
            conn.setRequestProperty("Content-Type", "application/json");
            conn.setDoOutput(true);
            conn.setConnectTimeout(10000);
            conn.setReadTimeout(10000);

            // Build JSON body
            JsonObject body = new JsonObject();
            body.addProperty("username", username);
            body.addProperty("password", password);
            body.addProperty("device_name", deviceName);

            try (OutputStream os = conn.getOutputStream()) {
                os.write(body.toString().getBytes(StandardCharsets.UTF_8));
            }

            int responseCode = conn.getResponseCode();

            if (responseCode == 200 || responseCode == 201) {
                // Success — read token from response
                BufferedReader reader = new BufferedReader(
                        new InputStreamReader(conn.getInputStream()));
                StringBuilder sb = new StringBuilder();
                String line;
                while ((line = reader.readLine()) != null) {
                    sb.append(line);
                }
                reader.close();

                JsonObject response = gson.fromJson(sb.toString(), JsonObject.class);
                String token = response.get("token").getAsString();
                int deviceId = response.get("device_id").getAsInt();

                Log.i(TAG, "✅ Registered! device_id=" + deviceId +
                        ", token=" + token.substring(0, Math.min(16, token.length())) + "...");

                // Save token and start connection
                config.setDeviceToken(token);

                mainHandler.post(() -> {
                    statusText.setText("✅ Registered! Connecting...");
                    statusText.setTextColor(Color.parseColor("#00ff88"));
                    restartService();
                });

            } else if (responseCode == 401) {
                mainHandler.post(() -> {
                    statusText.setText("❌ Invalid username or password");
                    statusText.setTextColor(Color.parseColor("#ff4444"));
                });
            } else {
                // Read error body
                BufferedReader reader = new BufferedReader(
                        new InputStreamReader(conn.getErrorStream()));
                StringBuilder sb = new StringBuilder();
                String line;
                while ((line = reader.readLine()) != null) {
                    sb.append(line);
                }
                reader.close();

                final String errorMsg = sb.toString();
                Log.e(TAG, "Register failed: " + responseCode + " " + errorMsg);
                mainHandler.post(() -> {
                    statusText.setText("❌ Registration failed (" + responseCode + ")");
                    statusText.setTextColor(Color.parseColor("#ff4444"));
                });
            }

            conn.disconnect();

        } catch (Exception e) {
            Log.e(TAG, "Registration error", e);
            mainHandler.post(() -> {
                statusText.setText("❌ Connection error: " + e.getMessage());
                statusText.setTextColor(Color.parseColor("#ff4444"));
            });
        }
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
            sb.append("📡 " + config.getServerUrl());
            if (!config.getDeviceName().isEmpty()) {
                sb.append("\n📱 " + config.getDeviceName());
            }
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
