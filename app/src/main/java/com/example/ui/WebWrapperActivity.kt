package com.example.ui

import android.Manifest
import android.annotation.SuppressLint
import android.app.Activity
import android.app.DownloadManager
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.graphics.Color
import android.media.MediaScannerConnection
import android.net.Uri
import android.net.http.SslError
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.os.VibrationEffect
import android.os.Vibrator
import android.util.Base64
import android.view.KeyEvent
import android.view.View
import android.view.ViewGroup
import android.webkit.CookieManager
import android.webkit.DownloadListener
import android.webkit.JavascriptInterface
import android.webkit.SslErrorHandler
import android.webkit.URLUtil
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout
import android.widget.ProgressBar
import android.widget.Toast
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import androidx.core.content.FileProvider
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.documentfile.provider.DocumentFile
import com.example.R
import com.example.data.SessionManager
import com.example.service.FileDownloadService
import com.google.android.material.bottomsheet.BottomSheetDialog
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import java.io.File
import java.util.concurrent.TimeUnit

class WebWrapperActivity : AppCompatActivity() {

    private lateinit var webView: WebView
    private lateinit var progressBar: ProgressBar

    private var serverIp: String = ""
    private var serverPort: Int = 8080
    private var authToken: String = ""

    private var fileUploadCallback: ValueCallback<Array<Uri>>? = null
    private var isReceiverRegistered = false

    companion object {
        const val EXTRA_IP = "EXTRA_IP"
        const val EXTRA_PORT = "EXTRA_PORT"
        const val EXTRA_TOKEN = "EXTRA_TOKEN"
        private const val DOWNLOAD_CHANNEL_ID = "arn_downloads_channel"
    }

    // 1. File picker launcher for uploading individual or multiple files
    private val filePickerLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (fileUploadCallback == null) return@registerForActivityResult

        val uris: Array<Uri>? = if (result.resultCode == Activity.RESULT_OK && result.data != null) {
            val clipData = result.data?.clipData
            if (clipData != null && clipData.itemCount > 0) {
                Array(clipData.itemCount) { i -> clipData.getItemAt(i).uri }
            } else if (result.data?.data != null) {
                arrayOf(result.data!!.data!!)
            } else {
                null
            }
        } else {
            null
        }

        // Clear any folder relative path hooks for normal file uploads
        webView.evaluateJavascript(
            "window.__arnSelectedFolderName = null; window.__arnFileRelativePaths = null;",
            null
        )

        fileUploadCallback?.onReceiveValue(uris)
        fileUploadCallback = null
    }

    // 2. Folder picker launcher: extracts full hierarchy so files arrive inside their folder on the PC
    private val folderPickerLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (fileUploadCallback == null) return@registerForActivityResult

        val treeUri = if (result.resultCode == Activity.RESULT_OK) result.data?.data else null
        if (treeUri != null) {
            Toast.makeText(this, "جاري تحضير المجلد وهيكل الملفات للرفع...", Toast.LENGTH_SHORT).show()
            CoroutineScope(Dispatchers.IO).launch {
                val rootDoc = DocumentFile.fromTreeUri(this@WebWrapperActivity, treeUri)
                val folderName = rootDoc?.name ?: "Folder"
                val uris = mutableListOf<Uri>()
                val relativePathMap = mutableMapOf<String, String>()

                if (rootDoc != null) {
                    traverseFolderWithPaths(rootDoc, folderName, uris, relativePathMap)
                }

                withContext(Dispatchers.Main) {
                    if (uris.isNotEmpty()) {
                        // Inject relative paths map into web JavaScript so FormData appends folder path
                        val jsonMap = JSONObject(relativePathMap as Map<*, *>).toString()
                        webView.evaluateJavascript(
                            """
                            window.__arnSelectedFolderName = '$folderName';
                            window.__arnFileRelativePaths = $jsonMap;
                            """.trimIndent(),
                            null
                        )

                        fileUploadCallback?.onReceiveValue(uris.toTypedArray())
                        Toast.makeText(
                            this@WebWrapperActivity,
                            "تم تجهيز مجلد \"$folderName\" يحتوي على ${uris.size} ملف للرفع ⚡",
                            Toast.LENGTH_LONG
                        ).show()
                    } else {
                        webView.evaluateJavascript(
                            "window.__arnSelectedFolderName = null; window.__arnFileRelativePaths = null;",
                            null
                        )
                        fileUploadCallback?.onReceiveValue(null)
                        Toast.makeText(this@WebWrapperActivity, "المجلد فارغ أو لا يحتوي على ملفات", Toast.LENGTH_SHORT).show()
                    }
                    fileUploadCallback = null
                }
            }
        } else {
            fileUploadCallback?.onReceiveValue(null)
            fileUploadCallback = null
        }
    }

    private fun traverseFolderWithPaths(
        dir: DocumentFile,
        currentPath: String,
        uris: MutableList<Uri>,
        relativePathMap: MutableMap<String, String>
    ) {
        val files = dir.listFiles()
        for (file in files) {
            val name = file.name ?: continue
            if (file.isDirectory) {
                traverseFolderWithPaths(file, "$currentPath/$name", uris, relativePathMap)
            } else if (file.isFile) {
                uris.add(file.uri)
                relativePathMap[name] = "$currentPath/$name"
            }
        }
    }

    // Permission launcher for system notifications on Android 13+
    private val notificationPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { /* Permission result handled */ }

    // Broadcast receiver fallback for DownloadManager
    private val downloadCompleteReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            if (intent?.action != DownloadManager.ACTION_DOWNLOAD_COMPLETE) return
            val downloadId = intent.getLongExtra(DownloadManager.EXTRA_DOWNLOAD_ID, -1L)
            if (downloadId == -1L) return

            val dm = getSystemService(Context.DOWNLOAD_SERVICE) as? DownloadManager ?: return
            val query = DownloadManager.Query().setFilterById(downloadId)
            val cursor = dm.query(query) ?: return

            try {
                if (cursor.moveToFirst()) {
                    val statusIndex = cursor.getColumnIndex(DownloadManager.COLUMN_STATUS)
                    val status = if (statusIndex != -1) cursor.getInt(statusIndex) else -1

                    if (status == DownloadManager.STATUS_SUCCESSFUL) {
                        val titleIndex = cursor.getColumnIndex(DownloadManager.COLUMN_TITLE)
                        val mimeIndex = cursor.getColumnIndex(DownloadManager.COLUMN_MEDIA_TYPE)
                        val filename = if (titleIndex != -1) cursor.getString(titleIndex) else "ملف محمل"
                        val mimeType = if (mimeIndex != -1 && !cursor.getString(mimeIndex).isNullOrEmpty()) {
                            cursor.getString(mimeIndex)
                        } else {
                            if (filename.endsWith(".zip", ignoreCase = true)) "application/zip" else "*/*"
                        }

                        val downloadsDir = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS)
                        val localFile = File(downloadsDir, filename)
                        if (localFile.exists()) {
                            MediaScannerConnection.scanFile(
                                this@WebWrapperActivity,
                                arrayOf(localFile.absolutePath),
                                arrayOf(mimeType)
                            ) { _, _ -> }
                        }

                        val downloadedUri = dm.getUriForDownloadedFile(downloadId)
                        showDownloadCompleteNotification(filename, mimeType, downloadedUri)
                    }
                }
            } catch (e: Exception) {
                e.printStackTrace()
            } finally {
                cursor.close()
            }
        }
    }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        serverIp = intent.getStringExtra(EXTRA_IP) ?: ""
        serverPort = intent.getIntExtra(EXTRA_PORT, 8080)
        authToken = intent.getStringExtra(EXTRA_TOKEN) ?: ""

        if (serverIp.isEmpty() || authToken.isEmpty()) {
            Toast.makeText(this, "بيانات الاتصال غير مكتملة", Toast.LENGTH_SHORT).show()
            returnToGateway()
            return
        }

        createNotificationChannel()
        checkNotificationPermission()
        registerDownloadReceiver()

        buildNativeLayout()
        configureSmartWebView()
        loadRemoteMobileUrl()
        setupBackNavigation()
    }

    private fun checkNotificationPermission() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED
            ) {
                notificationPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
            }
        }
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                DOWNLOAD_CHANNEL_ID,
                "تنزيلات الملفات والمجلدات",
                NotificationManager.IMPORTANCE_HIGH
            ).apply {
                description = "إشعارات اكتمال تنزيل الملفات والمجلدات المضغوطة من الحاسوب"
                enableVibration(true)
            }
            val manager = getSystemService(NotificationManager::class.java)
            manager?.createNotificationChannel(channel)
        }
    }

    private fun registerDownloadReceiver() {
        if (!isReceiverRegistered) {
            val filter = IntentFilter(DownloadManager.ACTION_DOWNLOAD_COMPLETE)
            ContextCompat.registerReceiver(
                this,
                downloadCompleteReceiver,
                filter,
                ContextCompat.RECEIVER_EXPORTED
            )
            isReceiverRegistered = true
        }
    }

    private fun showDownloadCompleteNotification(filename: String, mimeType: String, contentUri: Uri?) {
        val openIntent = Intent(Intent.ACTION_VIEW).apply {
            if (contentUri != null) {
                setDataAndType(contentUri, mimeType)
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
            }
        }

        val pendingIntent = PendingIntent.getActivity(
            this,
            System.currentTimeMillis().toInt(),
            openIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        val notification = NotificationCompat.Builder(this, DOWNLOAD_CHANNEL_ID)
            .setSmallIcon(android.R.drawable.stat_sys_download_done)
            .setContentTitle("اكتمل التنزيل بنجاح 📥")
            .setContentText("$filename — انقر لفتح الملف/المجلد")
            .setContentIntent(pendingIntent)
            .setAutoCancel(true)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setDefaults(NotificationCompat.DEFAULT_ALL)
            .build()

        try {
            NotificationManagerCompat.from(this).notify(
                (System.currentTimeMillis() % 10000).toInt(),
                notification
            )
        } catch (_: SecurityException) {}

        Toast.makeText(this, "اكتمل تنزيل: $filename (محفوظ في التنزيلات)", Toast.LENGTH_LONG).show()
    }

    private fun buildNativeLayout() {
        val root = FrameLayout(this).apply {
            setBackgroundColor(Color.parseColor("#070C16"))
            layoutParams = ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT
            )
        }

        webView = WebView(this).apply {
            layoutParams = FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT
            )
            setBackgroundColor(Color.parseColor("#070C16"))
        }

        // Sleek horizontal progress bar at top edge
        progressBar = ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal).apply {
            layoutParams = FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                8
            )
            max = 100
            progressTintList = android.content.res.ColorStateList.valueOf(Color.parseColor("#22D3EE"))
        }

        root.addView(webView)
        root.addView(progressBar)
        setContentView(root)

        ViewCompat.setOnApplyWindowInsetsListener(root) { view, insets ->
            val systemBars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            view.setPadding(0, systemBars.top, 0, systemBars.bottom)
            insets
        }
    }

    // Bridge to receive blob/data downloads directly from web JavaScript
    inner class AndroidDownloadBridge {
        @JavascriptInterface
        fun downloadBlob(base64Data: String, mimeType: String, filenameRaw: String) {
            runOnUiThread {
                saveBase64Download(base64Data, mimeType, filenameRaw)
            }
        }
    }

    fun saveBase64Download(base64Data: String, mimeType: String, filenameRaw: String) {
        CoroutineScope(Dispatchers.IO).launch {
            try {
                var filename = filenameRaw.trim()
                if (filename.isEmpty() || filename.startsWith("download", ignoreCase = true)) {
                    filename = "Folder_${System.currentTimeMillis() % 100000}.zip"
                }
                val isZip = mimeType.contains("zip") || filename.endsWith(".zip", ignoreCase = true)
                if (isZip && !filename.endsWith(".zip", ignoreCase = true)) {
                    filename = "$filename.zip"
                }

                val cleanBase64 = if (base64Data.contains(",")) {
                    base64Data.substringAfter(",")
                } else {
                    base64Data
                }

                val bytes = Base64.decode(cleanBase64, Base64.DEFAULT)
                val downloadsDir = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS)
                val targetFile = File(downloadsDir, filename)
                targetFile.writeBytes(bytes)

                val finalMime = if (isZip) "application/zip" else mimeType

                MediaScannerConnection.scanFile(
                    this@WebWrapperActivity,
                    arrayOf(targetFile.absolutePath),
                    arrayOf(finalMime)
                ) { _, _ -> }

                val contentUri = FileProvider.getUriForFile(
                    this@WebWrapperActivity,
                    "${applicationContext.packageName}.fileprovider",
                    targetFile
                )

                withContext(Dispatchers.Main) {
                    showDownloadCompleteNotification(filename, finalMime, contentUri)
                    Toast.makeText(this@WebWrapperActivity, "تم تنزيل المجلد: $filename بنجاح 📥", Toast.LENGTH_LONG).show()
                }
            } catch (e: Exception) {
                withContext(Dispatchers.Main) {
                    Toast.makeText(this@WebWrapperActivity, "فشل حفظ المجلد: ${e.message}", Toast.LENGTH_SHORT).show()
                }
            }
        }
    }

    @SuppressLint("SetJavaScriptEnabled")
    private fun configureSmartWebView() {
        webView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            databaseEnabled = true

            // Fast hardware-accelerated rendering
            @Suppress("DEPRECATION")
            setRenderPriority(WebSettings.RenderPriority.HIGH)
            cacheMode = WebSettings.LOAD_DEFAULT
            mixedContentMode = WebSettings.MIXED_CONTENT_ALWAYS_ALLOW

            // Media & responsive viewport
            mediaPlaybackRequiresUserGesture = false
            allowFileAccess = true
            useWideViewPort = true
            loadWithOverviewMode = true
            setSupportZoom(false)

            // Custom user agent
            userAgentString = "ARN-ShutdownPanel-AndroidShell/2.0 " + userAgentString
        }

        // Add download bridge interface for blob downloads
        webView.addJavascriptInterface(AndroidDownloadBridge(), "AndroidDownloadBridge")

        webView.webChromeClient = object : WebChromeClient() {
            override fun onProgressChanged(view: WebView?, newProgress: Int) {
                progressBar.progress = newProgress
                progressBar.visibility = if (newProgress in 1..99) View.VISIBLE else View.GONE
            }

            // Handles file and folder uploads from web input file elements to the PC
            override fun onShowFileChooser(
                webView: WebView?,
                filePathCallback: ValueCallback<Array<Uri>>?,
                fileChooserParams: FileChooserParams?
            ): Boolean {
                fileUploadCallback?.onReceiveValue(null)
                fileUploadCallback = filePathCallback

                showUploadChoiceBottomSheet(fileChooserParams)
                return true
            }
        }

        webView.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView?, request: WebResourceRequest?): Boolean {
                val url = request?.url ?: return false

                if (url.scheme == "arn") {
                    when (url.host) {
                        "change-server" -> {
                            returnToGateway()
                            return true
                        }
                        "logout" -> {
                            SessionManager(this@WebWrapperActivity).clearSession(serverIp, serverPort)
                            returnToGateway()
                            return true
                        }
                    }
                }
                return false
            }

            override fun onPageFinished(view: WebView?, url: String?) {
                super.onPageFinished(view, url)
                // Inject token and upload/download interception hooks
                view?.evaluateJavascript(
                    """
                    try {
                        if (typeof localStorage !== 'undefined') {
                            localStorage.setItem('remote_token', '$authToken');
                            localStorage.setItem('token', '$authToken');
                            localStorage.setItem('authToken', '$authToken');
                        }
                        if (typeof sessionStorage !== 'undefined') {
                            sessionStorage.setItem('token', '$authToken');
                        }
                    } catch(e) {}

                    // Hook FormData.append to preserve folder structure on upload
                    if (!window.__arnFormDataHooked) {
                        window.__arnFormDataHooked = true;
                        const origAppend = FormData.prototype.append;
                        FormData.prototype.append = function(name, value, filename) {
                            if (value instanceof File) {
                                let targetName = filename || value.name;
                                if (window.__arnFileRelativePaths && window.__arnFileRelativePaths[value.name]) {
                                    targetName = window.__arnFileRelativePaths[value.name];
                                } else if (window.__arnSelectedFolderName && !targetName.startsWith(window.__arnSelectedFolderName + '/')) {
                                    targetName = window.__arnSelectedFolderName + '/' + targetName;
                                }
                                return origAppend.call(this, name, value, targetName);
                            }
                            return origAppend.apply(this, arguments);
                        };
                    // Hook blob link clicks for folder downloads with smart name detection
                    if (!window.__arnBlobHooked) {
                        window.__arnBlobHooked = true;
                        const origClick = HTMLAnchorElement.prototype.click;
                        HTMLAnchorElement.prototype.click = function() {
                            const href = this.href || '';
                            if (href.startsWith('blob:') || href.startsWith('data:')) {
                                let downloadName = (this.getAttribute('download') || '').trim();
                                if (!downloadName || downloadName.startsWith('download') || downloadName.endsWith('.bin')) {
                                    const row = this.closest('tr') || this.closest('.file-item') || this.closest('.item') || this.closest('li') || this.parentElement;
                                    if (row) {
                                        const nameEl = row.querySelector('.name, .filename, .title, .file-name, [data-name]');
                                        if (nameEl) {
                                            downloadName = (nameEl.getAttribute('data-name') || nameEl.textContent || '').trim();
                                        }
                                    }
                                }
                                if (!downloadName) {
                                    downloadName = 'Folder_' + (Date.now() % 100000) + '.zip';
                                } else if (!downloadName.endsWith('.zip')) {
                                    downloadName += '.zip';
                                }

                                fetch(href)
                                    .then(r => r.blob())
                                    .then(blob => {
                                        const reader = new FileReader();
                                        reader.onloadend = function() {
                                            if (window.AndroidDownloadBridge) {
                                                window.AndroidDownloadBridge.downloadBlob(
                                                    reader.result,
                                                    blob.type || 'application/zip',
                                                    downloadName
                                                );
                                            }
                                        };
                                        reader.readAsDataURL(blob);
                                    })
                                    .catch(() => origClick.call(this));
                                return;
                            }
                            origClick.call(this);
                        };
                    }
                    """.trimIndent(),
                    null
                )

                // Check if page rendered the JSON error {"ok": false, "error": "Not found"}
                view?.evaluateJavascript("(function() { return document.body ? document.body.innerText : ''; })()") { bodyText ->
                    val text = bodyText?.trim() ?: ""
                    if (text.contains("Not found") && (text.contains("\"ok\": false") || text.contains("Pretty-print"))) {
                        tryFallbackPath()
                    }
                }
            }

            override fun onReceivedSslError(view: WebView?, handler: SslErrorHandler?, error: SslError?) {
                // Auto-accept self-signed SSL certificates for LAN environments
                handler?.proceed()
            }

            override fun onReceivedError(view: WebView?, request: WebResourceRequest?, error: WebResourceError?) {
                if (request?.isForMainFrame == true) {
                    showOfflineRetryPage()
                }
            }
        }

        // Direct Download listener supporting chunked ZIP streams and blob downloads
        webView.setDownloadListener(DownloadListener { url, _, contentDisposition, mimetype, _ ->
            if (url.startsWith("blob:") || url.startsWith("data:")) {
                webView.evaluateJavascript(
                    """
                    (function() {
                        fetch('$url')
                            .then(r => r.blob())
                            .then(blob => {
                                const reader = new FileReader();
                                reader.onloadend = function() {
                                    if (window.AndroidDownloadBridge) {
                                        window.AndroidDownloadBridge.downloadBlob(reader.result, blob.type || 'application/zip', 'Folder_' + (Date.now() % 100000) + '.zip');
                                    }
                                };
                                reader.readAsDataURL(blob);
                            });
                    })();
                    """.trimIndent(),
                    null
                )
                return@DownloadListener
            }

            startDirectStreamDownload(url, contentDisposition, mimetype)
        })
    }

    private fun startDirectStreamDownload(rawUrl: String, contentDisposition: String?, rawMime: String?) {
        var downloadUrl = rawUrl
        if (!downloadUrl.contains("token=")) {
            downloadUrl = if (downloadUrl.contains("?")) {
                "$downloadUrl&token=$authToken"
            } else {
                "$downloadUrl?token=$authToken"
            }
        }

        // 1. Try extracting actual item/folder name from the URL query parameter (e.g. path=... or file=...)
        var filename = ""
        try {
            val uri = Uri.parse(downloadUrl)
            val pathParam = uri.getQueryParameter("path")
                ?: uri.getQueryParameter("file")
                ?: uri.getQueryParameter("name")

            if (!pathParam.isNullOrEmpty()) {
                val clean = pathParam.replace('\\', '/').trimEnd('/')
                val lastPart = clean.substringAfterLast('/')
                if (lastPart.isNotEmpty() && !lastPart.startsWith("download", ignoreCase = true)) {
                    filename = lastPart
                }
            }
        } catch (_: Exception) {}

        if (filename.isEmpty() || filename.startsWith("download", ignoreCase = true)) {
            filename = URLUtil.guessFileName(downloadUrl, contentDisposition, rawMime)
        }

        val isZip = (rawMime != null && (rawMime.contains("zip") || rawMime.contains("compressed") || rawMime.contains("archive")))
                || (downloadUrl.lowercase().contains("zip") || downloadUrl.lowercase().contains("folder") || downloadUrl.lowercase().contains("dir"))
                || (contentDisposition != null && contentDisposition.lowercase().contains(".zip"))

        if (isZip && !filename.endsWith(".zip", ignoreCase = true)) {
            filename = if (filename.contains(".")) {
                filename.substringBeforeLast(".") + ".zip"
            } else {
                "$filename.zip"
            }
        }

        if (filename.startsWith("download", ignoreCase = true)) {
            filename = "Folder_${System.currentTimeMillis() % 100000}.zip"
        }

        val cookie = try { CookieManager.getInstance().getCookie(downloadUrl) } catch (_: Exception) { null }

        // Start Foreground Service so download continues uninterrupted even if the user exits the app!
        FileDownloadService.startDownload(
            this,
            downloadUrl,
            authToken,
            cookie,
            filename
        )
        Toast.makeText(this, "بدأ التنزيل في الخلفية: $filename (مستمر حتى لو خرجت من التطبيق) ⚡", Toast.LENGTH_LONG).show()
    }

    private fun enqueueDownloadManager(downloadUrl: String, filename: String, mimeType: String) {
        try {
            val uri = Uri.parse(downloadUrl)
            val cookie = try { CookieManager.getInstance().getCookie(downloadUrl) } catch (_: Exception) { null }
            val request = DownloadManager.Request(uri).apply {
                if (mimeType.isNotEmpty() && mimeType != "application/octet-stream") {
                    setMimeType(mimeType)
                }
                if (!cookie.isNullOrEmpty()) {
                    addRequestHeader("Cookie", cookie)
                }
                addRequestHeader("X-Auth-Token", authToken)
                setTitle(filename)
                setDescription("تنزيل من الحاسوب عبر ARN Shutdown Panel")
                setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
                setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, filename)
            }
            val dm = getSystemService(Context.DOWNLOAD_SERVICE) as DownloadManager
            dm.enqueue(request)
        } catch (e: Exception) {
            Toast.makeText(this, "فشل بدء التنزيل: ${e.message}", Toast.LENGTH_SHORT).show()
        }
    }

    private fun showUploadChoiceBottomSheet(fileChooserParams: WebChromeClient.FileChooserParams?) {
        val bottomSheet = BottomSheetDialog(this)
        val sheetView = layoutInflater.inflate(R.layout.bottom_sheet_upload_choice, null)
        bottomSheet.setContentView(sheetView)

        val btnChoiceFiles = sheetView.findViewById<View>(R.id.btnChoiceFiles)
        val btnChoiceFolder = sheetView.findViewById<View>(R.id.btnChoiceFolder)
        val btnChoiceCancel = sheetView.findViewById<View>(R.id.btnChoiceCancel)

        var optionChosen = false

        btnChoiceFiles?.setOnClickListener {
            optionChosen = true
            bottomSheet.dismiss()
            val intent = Intent(Intent.ACTION_GET_CONTENT).apply {
                addCategory(Intent.CATEGORY_OPENABLE)
                type = "*/*"
                putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true)
            }
            try {
                filePickerLauncher.launch(Intent.createChooser(intent, "اختر ملفات لرفعها إلى الحاسوب"))
            } catch (e: Exception) {
                fileUploadCallback?.onReceiveValue(null)
                fileUploadCallback = null
                Toast.makeText(this, "تعذر فتح محدد الملفات: ${e.message}", Toast.LENGTH_SHORT).show()
            }
        }

        btnChoiceFolder?.setOnClickListener {
            optionChosen = true
            bottomSheet.dismiss()
            val intent = Intent(Intent.ACTION_OPEN_DOCUMENT_TREE).apply {
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION)
            }
            try {
                folderPickerLauncher.launch(Intent.createChooser(intent, "اختر مجلداً لرفع محتواه بالكامل"))
            } catch (e: Exception) {
                fileUploadCallback?.onReceiveValue(null)
                fileUploadCallback = null
                Toast.makeText(this, "تعذر فتح محدد المجلدات: ${e.message}", Toast.LENGTH_SHORT).show()
            }
        }

        btnChoiceCancel?.setOnClickListener {
            bottomSheet.dismiss()
        }

        bottomSheet.setOnDismissListener {
            if (!optionChosen && fileUploadCallback != null) {
                fileUploadCallback?.onReceiveValue(null)
                fileUploadCallback = null
            }
        }

        bottomSheet.show()
    }

    private val candidatePaths = listOf("", "mobile.html", "index.html")
    private var currentPathIndex = 0

    private fun loadRemoteMobileUrl() {
        try {
            val cookieManager = CookieManager.getInstance()
            cookieManager.setAcceptCookie(true)
            cookieManager.setAcceptThirdPartyCookies(webView, true)
            cookieManager.setCookie("http://$serverIp:$serverPort", "token=$authToken; path=/")
            cookieManager.setCookie("http://$serverIp:$serverPort", "X-Auth-Token=$authToken; path=/")
            cookieManager.flush()
        } catch (_: Exception) {}

        loadPath(candidatePaths[currentPathIndex])
    }

    private fun loadPath(path: String) {
        val pathPart = if (path.isEmpty()) "" else "$path"
        val targetUrl = "http://$serverIp:$serverPort/$pathPart?token=$authToken"
        val headers = mapOf("X-Auth-Token" to authToken)
        webView.loadUrl(targetUrl, headers)
    }

    private fun tryFallbackPath() {
        currentPathIndex++
        if (currentPathIndex < candidatePaths.size) {
            val nextPath = candidatePaths[currentPathIndex]
            loadPath(nextPath)
        }
    }

    private fun showOfflineRetryPage() {
        val html = """
            <!DOCTYPE html>
            <html dir="rtl" lang="ar">
            <head>
                <meta charset="utf-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
                <style>
                    * { box-sizing: border-box; margin: 0; padding: 0; }
                    body {
                        background-color: #070c16;
                        color: #e8f4ff;
                        font-family: 'Cairo', system-ui, -apple-system, sans-serif;
                        display: flex;
                        flex-direction: column;
                        align-items: center;
                        justify-content: center;
                        min-height: 100vh;
                        padding: 32px 24px;
                        text-align: center;
                    }
                    .glow-box {
                        width: 90px;
                        height: 90px;
                        border-radius: 28px;
                        background: radial-gradient(circle, rgba(34, 211, 238, 0.2) 0%, rgba(7, 12, 22, 0) 70%);
                        display: flex;
                        align-items: center;
                        justify-content: center;
                        font-size: 46px;
                        margin-bottom: 24px;
                        border: 1px solid rgba(34, 211, 238, 0.3);
                        box-shadow: 0 0 30px rgba(34, 211, 238, 0.15);
                    }
                    h2 {
                        color: #22d3ee;
                        font-size: 22px;
                        font-weight: 700;
                        margin-bottom: 12px;
                    }
                    p {
                        color: #7d90a8;
                        font-size: 14px;
                        line-height: 1.7;
                        max-width: 320px;
                        margin-bottom: 32px;
                    }
                    .server-tag {
                        display: inline-block;
                        background: #0f172a;
                        border: 1px solid #1e293b;
                        color: #38bdf8;
                        padding: 6px 14px;
                        border-radius: 999px;
                        font-size: 12px;
                        margin-bottom: 24px;
                        direction: ltr;
                    }
                    .btn-retry {
                        background: linear-gradient(135deg, #0ea5e9, #22d3ee);
                        color: #04101e;
                        border: none;
                        padding: 15px 36px;
                        border-radius: 999px;
                        font-size: 15px;
                        font-weight: bold;
                        cursor: pointer;
                        box-shadow: 0 4px 20px rgba(34, 211, 238, 0.35);
                        width: 100%;
                        max-width: 260px;
                        transition: opacity 0.2s;
                    }
                    .btn-change {
                        background: transparent;
                        color: #94a3b8;
                        border: 1px solid #1e293b;
                        padding: 12px 28px;
                        border-radius: 999px;
                        font-size: 13px;
                        margin-top: 14px;
                        cursor: pointer;
                        width: 100%;
                        max-width: 260px;
                    }
                    .credits {
                        margin-top: 40px;
                        font-size: 11px;
                        color: #475569;
                    }
                </style>
            </head>
            <body>
                <div class="glow-box">⚡</div>
                <h2>تعذر الاتصال بالحاسوب</h2>
                <div class="server-tag">$serverIp:$serverPort</div>
                <p>تأكد من تشغيل الكمبيوتر، اتصاله بنفس شبكة Wi-Fi، وأن برنامج Shutdown Panel قيد التشغيل.</p>
                <button class="btn-retry" onclick="location.reload()">إعادة المحاولة 🔄</button>
                <button class="btn-change" onclick="window.location.href='arn://change-server'">تغيير الخادم / تسجيل الخروج</button>
                <div class="credits">ARN Technology — عبده رجب نصار</div>
            </body>
            </html>
        """.trimIndent()
        webView.loadDataWithBaseURL(null, html, "text/html", "UTF-8", null)
    }

    private fun setupBackNavigation() {
        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (webView.canGoBack()) {
                    webView.goBack()
                } else {
                    // Send task to background so connection remains active
                    moveTaskToBack(true)
                }
            }
        })
    }

    private fun returnToGateway() {
        val intent = Intent(this, GatewayActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK
        }
        startActivity(intent)
        finish()
    }

    // Intercept phone hardware Volume Up / Volume Down keys to control PC volume
    override fun onKeyDown(keyCode: Int, event: KeyEvent?): Boolean {
        when (keyCode) {
            KeyEvent.KEYCODE_VOLUME_UP -> {
                triggerPcVolumeControl(isVolumeUp = true)
                return true
            }
            KeyEvent.KEYCODE_VOLUME_DOWN -> {
                triggerPcVolumeControl(isVolumeUp = false)
                return true
            }
        }
        return super.onKeyDown(keyCode, event)
    }

    override fun onKeyUp(keyCode: Int, event: KeyEvent?): Boolean {
        if (keyCode == KeyEvent.KEYCODE_VOLUME_UP || keyCode == KeyEvent.KEYCODE_VOLUME_DOWN) {
            return true
        }
        return super.onKeyUp(keyCode, event)
    }

    private fun triggerPcVolumeControl(isVolumeUp: Boolean) {
        vibrateShort()
        val actionKey = if (isVolumeUp) "vol_up" else "vol_down"
        val step = if (isVolumeUp) 5 else -5
        val labelAr = if (isVolumeUp) "🔊 رفع صوت الكمبيوتر (+)" else "🔉 خفض صوت الكمبيوتر (-)"

        webView.evaluateJavascript(
            """
            (function() {
                // 1. Show sleek floating glassmorphic HUD on screen
                let hud = document.getElementById('__arn_vol_hud');
                if (!hud) {
                    hud = document.createElement('div');
                    hud.id = '__arn_vol_hud';
                    hud.style.cssText = 'position:fixed;top:24px;left:50%;transform:translateX(-50%);background:rgba(15,23,42,0.92);color:#22d3ee;border:1px solid #22d3ee;padding:10px 22px;border-radius:999px;font-family:Cairo,sans-serif;font-size:14px;font-weight:bold;z-index:999999;box-shadow:0 4px 20px rgba(34,211,238,0.3);transition:opacity 0.25s;pointer-events:none;direction:rtl;';
                    document.body.appendChild(hud);
                }
                hud.textContent = '$labelAr';
                hud.style.opacity = '1';
                clearTimeout(window.__arnVolHudTimer);
                window.__arnVolHudTimer = setTimeout(() => { hud.style.opacity = '0'; }, 1200);

                // 2. Try clicking existing volume button in the web UI if present
                const selectors = isUp => isUp
                    ? ['[data-action="vol_up"]', '[data-action="volume_up"]', '[onclick*="vol_up"]', '[onclick*="volume_up"]', '[onclick*="volUp"]', '#btnVolUp', '#volUp']
                    : ['[data-action="vol_down"]', '[data-action="volume_down"]', '[onclick*="vol_down"]', '[onclick*="volume_down"]', '[onclick*="volDown"]', '#btnVolDown', '#volDown'];

                const list = selectors(${if (isVolumeUp) "true" else "false"});
                for (const sel of list) {
                    const btn = document.querySelector(sel);
                    if (btn) {
                        btn.click();
                        return 'clicked_dom';
                    }
                }

                // 3. Try adjusting volume range slider if visible in the DOM
                const slider = document.querySelector('input[type="range"][id*="vol" i], input[type="range"][class*="vol" i], input[type="range"][oninput*="vol" i]');
                if (slider) {
                    const current = parseInt(slider.value || '50', 10);
                    const next = Math.max(0, Math.min(100, current + ($step)));
                    slider.value = next;
                    slider.dispatchEvent(new Event('input', { bubbles: true }));
                    slider.dispatchEvent(new Event('change', { bubbles: true }));
                    hud.textContent = '$labelAr (' + next + '%)';
                    return 'adjusted_slider';
                }

                // 4. Fallback: send direct authenticated API call to ShutdownPanel server
                const headers = {
                    'Content-Type': 'application/json',
                    'X-Auth-Token': '$authToken'
                };
                fetch('/api/media', {
                    method: 'POST',
                    headers: headers,
                    body: JSON.stringify({ action: '$actionKey', key: '$actionKey' })
                }).catch(() => {});

                fetch('/api/system/volume', {
                    method: 'POST',
                    headers: headers,
                    body: JSON.stringify({ action: '$actionKey', delta: $step })
                }).catch(() => {});

                return 'api_sent';
            })();
            """.trimIndent(),
            null
        )
    }

    private fun vibrateShort() {
        try {
            val vibrator = getSystemService(Context.VIBRATOR_SERVICE) as? Vibrator
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                vibrator?.vibrate(VibrationEffect.createOneShot(35, VibrationEffect.DEFAULT_AMPLITUDE))
            } else {
                @Suppress("DEPRECATION")
                vibrator?.vibrate(35)
            }
        } catch (_: Exception) {}
    }

    override fun onDestroy() {
        if (isReceiverRegistered) {
            try {
                unregisterReceiver(downloadCompleteReceiver)
            } catch (_: Exception) {}
            isReceiverRegistered = false
        }
        fileUploadCallback?.onReceiveValue(null)
        fileUploadCallback = null
        webView.destroy()
        super.onDestroy()
    }
}
