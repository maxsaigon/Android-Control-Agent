package com.androidcontrol.helper

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.IBinder
import android.util.Log
import io.livekit.android.LiveKit
import io.livekit.android.room.Room
import io.livekit.android.room.track.screencapture.ScreenCaptureParams
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch

/** Foreground service that publishes the Android screen to a LiveKit room. */
class ScreenStreamService : Service() {
    companion object {
        private const val TAG = "ACHelper.Stream"
        private const val CHANNEL_ID = "ac_helper_screen_stream"
        private const val NOTIFICATION_ID = 102
        private const val ACTION_START = "com.androidcontrol.helper.START_STREAM"
        private const val ACTION_STOP = "com.androidcontrol.helper.STOP_STREAM"
        private const val EXTRA_RESULT_CODE = "projection_result_code"
        private const val EXTRA_RESULT_DATA = "projection_result_data"
        private const val EXTRA_URL = "livekit_url"
        private const val EXTRA_TOKEN = "livekit_token"
        private const val EXTRA_ROOM = "livekit_room"

        @Volatile private var state = "idle"
        @Volatile private var roomName = ""
        @Volatile private var lastError = ""

        @JvmStatic
        fun request(context: Context, url: String, token: String, room: String) {
            state = "awaiting_permission"
            roomName = room
            lastError = ""
            ScreenCaptureActivity.request(context, url, token, room)
        }

        @JvmStatic
        fun start(
            context: Context,
            resultCode: Int,
            resultData: Intent,
            url: String,
            token: String,
            room: String,
        ) {
            val intent = Intent(context, ScreenStreamService::class.java)
                .setAction(ACTION_START)
                .putExtra(EXTRA_RESULT_CODE, resultCode)
                .putExtra(EXTRA_RESULT_DATA, resultData)
                .putExtra(EXTRA_URL, url)
                .putExtra(EXTRA_TOKEN, token)
                .putExtra(EXTRA_ROOM, room)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(intent)
            } else {
                context.startService(intent)
            }
        }

        @JvmStatic
        fun stop(context: Context) {
            context.startService(
                Intent(context, ScreenStreamService::class.java).setAction(ACTION_STOP)
            )
        }

        @JvmStatic
        fun status(): String = state

        @JvmStatic
        fun currentRoom(): String = roomName

        @JvmStatic
        fun error(): String = lastError

        @JvmStatic
        fun markPermissionDenied() {
            state = "permission_denied"
            lastError = "Screen capture permission denied"
        }
    }

    private val serviceJob = SupervisorJob()
    private val scope = CoroutineScope(serviceJob + Dispatchers.IO)
    private var connectJob: Job? = null
    private var room: Room? = null

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> stopStreaming()
            ACTION_START -> {
                startForeground(NOTIFICATION_ID, buildNotification("Connecting screen stream…"))
                connectAndPublish(intent)
            }
        }
        return START_NOT_STICKY
    }

    private fun connectAndPublish(intent: Intent) {
        connectJob?.cancel()
        val url = intent.getStringExtra(EXTRA_URL).orEmpty()
        val token = intent.getStringExtra(EXTRA_TOKEN).orEmpty()
        roomName = intent.getStringExtra(EXTRA_ROOM).orEmpty()
        val resultData = if (Build.VERSION.SDK_INT >= 33) {
            intent.getParcelableExtra(EXTRA_RESULT_DATA, Intent::class.java)
        } else {
            @Suppress("DEPRECATION")
            intent.getParcelableExtra(EXTRA_RESULT_DATA)
        }

        if (url.isBlank() || token.isBlank() || resultData == null) {
            fail("Missing LiveKit connection or MediaProjection data")
            return
        }

        state = "connecting"
        connectJob = scope.launch {
            try {
                val nextRoom = LiveKit.create(applicationContext)
                room = nextRoom
                nextRoom.connect(url, token)
                val captureParams = ScreenCaptureParams(
                    mediaProjectionPermissionResultData = resultData,
                    notificationId = NOTIFICATION_ID,
                    notification = buildNotification("Sharing screen · $roomName"),
                    onStop = { stopStreaming() },
                )
                nextRoom.localParticipant.setScreenShareEnabled(true, captureParams)
                state = "streaming"
                lastError = ""
                updateNotification("Sharing screen · $roomName")
                Log.i(TAG, "Screen stream published to room=$roomName")
            } catch (error: Exception) {
                Log.e(TAG, "Screen stream failed", error)
                fail(error.message ?: error.javaClass.simpleName)
            }
        }
    }

    private fun stopStreaming() {
        connectJob?.cancel()
        connectJob = null
        scope.launch {
            try {
                room?.localParticipant?.setScreenShareEnabled(false)
                room?.disconnect()
            } catch (error: Exception) {
                Log.w(TAG, "Stream cleanup error", error)
            } finally {
                room = null
                state = "idle"
                roomName = ""
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf()
            }
        }
    }

    private fun fail(message: String) {
        state = "error"
        lastError = message
        updateNotification("Screen stream failed")
        Log.e(TAG, message)
    }

    override fun onDestroy() {
        room = null
        scope.cancel()
        if (state == "streaming" || state == "connecting") {
            state = "idle"
        }
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "Android screen streaming",
                NotificationManager.IMPORTANCE_LOW,
            )
            getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
        }
    }

    private fun buildNotification(text: String): Notification {
        val pendingIntent = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val builder = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            Notification.Builder(this, CHANNEL_ID)
        } else {
            Notification.Builder(this)
        }
        return builder
            .setContentTitle("Android Control · Live screen")
            .setContentText(text)
            .setSmallIcon(android.R.drawable.ic_menu_view)
            .setContentIntent(pendingIntent)
            .setOngoing(true)
            .build()
    }

    private fun updateNotification(text: String) {
        getSystemService(NotificationManager::class.java)
            .notify(NOTIFICATION_ID, buildNotification(text))
    }
}
