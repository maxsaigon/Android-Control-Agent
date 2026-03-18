# ProGuard rules for AC Helper

# Keep WebSocket server classes
-keep class org.java_websocket.** { *; }

# Keep Gson serialization
-keep class com.google.gson.** { *; }

# Keep our command handler and service
-keep class com.androidcontrol.helper.** { *; }
