package com.example.service

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.media.MediaScannerConnection
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.os.IBinder
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import androidx.core.content.FileProvider
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.File
import java.net.URLDecoder
import java.util.concurrent.TimeUnit

class FileDownloadService : Service() {

    private val serviceJob = Job()
    private val serviceScope = CoroutineScope(Dispatchers.IO + serviceJob)

    companion object {
        const val CHANNEL_ID = "arn_background_downloads_channel"
        private const val EXTRA_URL = "EXTRA_URL"
        private const val EXTRA_TOKEN = "EXTRA_TOKEN"
        private const val EXTRA_COOKIE = "EXTRA_COOKIE"
        private const val EXTRA_FILENAME_HINT = "EXTRA_FILENAME_HINT"

        fun startDownload(
            context: Context,
            downloadUrl: String,
            authToken: String,
            cookie: String?,
            filenameHint: String
        ) {
            val intent = Intent(context, FileDownloadService::class.java).apply {
                putExtra(EXTRA_URL, downloadUrl)
                putExtra(EXTRA_TOKEN, authToken)
                putExtra(EXTRA_COOKIE, cookie)
                putExtra(EXTRA_FILENAME_HINT, filenameHint)
            }
            ContextCompat.startForegroundService(context, intent)
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val downloadUrl = intent?.getStringExtra(EXTRA_URL) ?: run {
            stopSelf()
            return START_NOT_STICKY
        }
        val authToken = intent.getStringExtra(EXTRA_TOKEN) ?: ""
        val cookie = intent.getStringExtra(EXTRA_COOKIE)
        val filenameHint = intent.getStringExtra(EXTRA_FILENAME_HINT) ?: "download.zip"

        val notificationId = (System.currentTimeMillis() % 10000).toInt() + 100
        startForeground(notificationId, buildProgressNotification(filenameHint))

        serviceScope.launch {
            executeDownload(downloadUrl, authToken, cookie, filenameHint, notificationId)
            stopForeground(STOP_FOREGROUND_DETACH)
            stopSelf()
        }

        return START_NOT_STICKY
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "تنزيلات الخلفية المستمرة",
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = "متابعة تنزيل الملفات والمجلدات حتى عند الخروج من التطبيق"
            }
            val manager = getSystemService(NotificationManager::class.java)
            manager?.createNotificationChannel(channel)
        }
    }

    private fun buildProgressNotification(filename: String): android.app.Notification {
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.stat_sys_download)
            .setContentTitle("جاري التنزيل في الخلفية...")
            .setContentText(filename)
            .setProgress(0, 0, true)
            .setOngoing(true)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .build()
    }

    private fun executeDownload(
        downloadUrl: String,
        authToken: String,
        cookie: String?,
        filenameHint: String,
        notificationId: Int
    ) {
        try {
            val okClient = OkHttpClient.Builder()
                .connectTimeout(30, TimeUnit.SECONDS)
                .readTimeout(300, TimeUnit.SECONDS)
                .build()

            val reqBuilder = Request.Builder()
                .url(downloadUrl)
                .addHeader("X-Auth-Token", authToken)
            if (!cookie.isNullOrEmpty()) {
                reqBuilder.addHeader("Cookie", cookie)
            }

            val response = okClient.newCall(reqBuilder.build()).execute()
            if (response.isSuccessful) {
                val body = response.body
                if (body != null) {
                    val resolvedFilename = resolveActualFilename(response, downloadUrl, filenameHint)
                    val downloadsDir = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS)
                    val targetFile = File(downloadsDir, resolvedFilename)

                    body.byteStream().use { input ->
                        targetFile.outputStream().use { output ->
                            input.copyTo(output)
                        }
                    }

                    val mimeType = if (resolvedFilename.endsWith(".zip", ignoreCase = true)) {
                        "application/zip"
                    } else {
                        response.header("Content-Type") ?: "*/*"
                    }

                    MediaScannerConnection.scanFile(
                        this,
                        arrayOf(targetFile.absolutePath),
                        arrayOf(mimeType)
                    ) { _, _ -> }

                    val contentUri = FileProvider.getUriForFile(
                        this,
                        "${applicationContext.packageName}.fileprovider",
                        targetFile
                    )

                    showCompletionNotification(resolvedFilename, mimeType, contentUri, notificationId)
                }
            }
        } catch (e: Exception) {
            e.printStackTrace()
        }
    }

    private fun resolveActualFilename(
        response: okhttp3.Response,
        downloadUrl: String,
        hint: String
    ): String {
        // 1. Check Content-Disposition header from server
        val contentDisp = response.header("Content-Disposition")
        if (!contentDisp.isNullOrEmpty()) {
            val extracted = extractFilenameFromContentDisposition(contentDisp)
            if (!extracted.isNullOrEmpty() && !extracted.equals("download", ignoreCase = true)) {
                return sanitizeFilename(extracted)
            }
        }

        // 2. Check query parameter `path`, `file`, or `name` in the URL
        try {
            val uri = Uri.parse(downloadUrl)
            val pathParam = uri.getQueryParameter("path")
                ?: uri.getQueryParameter("file")
                ?: uri.getQueryParameter("name")

            if (!pathParam.isNullOrEmpty()) {
                val cleanPath = pathParam.replace('\\', '/').trimEnd('/')
                val lastPart = cleanPath.substringAfterLast('/')
                if (lastPart.isNotEmpty() && !lastPart.equals("download", ignoreCase = true)) {
                    val isZip = response.header("Content-Type")?.contains("zip") == true
                            || downloadUrl.contains("zip")
                            || downloadUrl.contains("folder")
                    val finalName = if (isZip && !lastPart.endsWith(".zip", ignoreCase = true)) {
                        "$lastPart.zip"
                    } else {
                        lastPart
                    }
                    return sanitizeFilename(URLDecoder.decode(finalName, "UTF-8"))
                }
            }
        } catch (_: Exception) {}

        // 3. Check filenameHint if meaningful
        if (hint.isNotEmpty() && !hint.startsWith("download", ignoreCase = true)) {
            return sanitizeFilename(hint)
        }

        // 4. Timestamp-based unique name
        val isZip = response.header("Content-Type")?.contains("zip") == true
                || downloadUrl.contains("zip")
                || downloadUrl.contains("folder")
        val ext = if (isZip) ".zip" else ""
        return "Folder_${System.currentTimeMillis() % 100000}$ext"
    }

    private fun extractFilenameFromContentDisposition(header: String): String? {
        try {
            // Check filename*=UTF-8''...
            val utf8Regex = """filename\*=UTF-8''([^;]+)""".toRegex(RegexOption.IGNORE_CASE)
            val utf8Match = utf8Regex.find(header)
            if (utf8Match != null) {
                return URLDecoder.decode(utf8Match.groupValues[1].trim(), "UTF-8")
            }

            // Check filename="..."
            val quotedRegex = """filename="([^"]+)"""".toRegex(RegexOption.IGNORE_CASE)
            val quotedMatch = quotedRegex.find(header)
            if (quotedMatch != null) {
                return quotedMatch.groupValues[1].trim()
            }

            // Check filename=...
            val unquotedRegex = """filename=([^;]+)""".toRegex(RegexOption.IGNORE_CASE)
            val unquotedMatch = unquotedRegex.find(header)
            if (unquotedMatch != null) {
                return unquotedMatch.groupValues[1].trim()
            }
        } catch (_: Exception) {}
        return null
    }

    private fun sanitizeFilename(name: String): String {
        return name.replace("[\\\\/:*?\"<>|]".toRegex(), "_")
    }

    private fun showCompletionNotification(
        filename: String,
        mimeType: String,
        contentUri: Uri,
        notificationId: Int
    ) {
        val openIntent = Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(contentUri, mimeType)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
        }

        val pendingIntent = PendingIntent.getActivity(
            this,
            notificationId,
            openIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        val notification = NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.stat_sys_download_done)
            .setContentTitle("اكتمل التنزيل بنجاح 📥")
            .setContentText("$filename — انقر لفتح الملف/المجلد")
            .setContentIntent(pendingIntent)
            .setAutoCancel(true)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .build()

        NotificationManagerCompat.from(this).notify(notificationId, notification)
    }

    override fun onDestroy() {
        serviceJob.cancel()
        super.onDestroy()
    }
}
