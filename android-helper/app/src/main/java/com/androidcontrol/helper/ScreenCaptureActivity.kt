package com.androidcontrol.helper

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.media.projection.MediaProjectionManager
import android.os.Bundle
import android.util.Log

/**
 * Requests the system MediaProjection grant and hands it to ScreenStreamService.
 *
 * Android intentionally requires user consent for each new projection session.
 */
class ScreenCaptureActivity : Activity() {
    companion object {
        private const val TAG = "ACHelper.Capture"
        private const val REQUEST_CAPTURE = 6101
        private const val EXTRA_URL = "livekit_url"
        private const val EXTRA_TOKEN = "livekit_token"
        private const val EXTRA_ROOM = "livekit_room"

        @JvmStatic
        fun request(context: Context, url: String, token: String, room: String) {
            val intent = Intent(context, ScreenCaptureActivity::class.java)
                .putExtra(EXTRA_URL, url)
                .putExtra(EXTRA_TOKEN, token)
                .putExtra(EXTRA_ROOM, room)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            context.startActivity(intent)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val projectionManager =
            getSystemService(MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
        startActivityForResult(projectionManager.createScreenCaptureIntent(), REQUEST_CAPTURE)
    }

    @Deprecated("Deprecated by Android; retained for minSdk 28 compatibility")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != REQUEST_CAPTURE) return

        if (resultCode == RESULT_OK && data != null) {
            ScreenStreamService.start(
                this,
                resultCode,
                data,
                intent.getStringExtra(EXTRA_URL).orEmpty(),
                intent.getStringExtra(EXTRA_TOKEN).orEmpty(),
                intent.getStringExtra(EXTRA_ROOM).orEmpty(),
            )
        } else {
            Log.w(TAG, "Screen capture permission denied")
            ScreenStreamService.markPermissionDenied()
        }
        finish()
    }
}

