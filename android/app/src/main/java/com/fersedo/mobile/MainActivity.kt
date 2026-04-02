package com.fersedo.mobile

import android.Manifest
import android.annotation.SuppressLint
import android.app.AlertDialog
import android.app.DownloadManager
import android.content.BroadcastReceiver
import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.net.Uri
import android.net.http.SslError
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.os.Message
import android.view.View
import android.webkit.CookieManager
import android.webkit.DownloadListener
import android.webkit.PermissionRequest
import android.webkit.SslErrorHandler
import android.webkit.URLUtil
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.addCallback
import androidx.activity.result.contract.ActivityResultContracts.RequestPermission
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat
import androidx.core.content.FileProvider
import androidx.core.splashscreen.SplashScreen.Companion.installSplashScreen
import androidx.core.app.NotificationManagerCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import com.fersedo.mobile.databinding.ActivityMainBinding
import java.io.BufferedInputStream
import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.net.HttpURLConnection
import java.net.URL
import java.security.SecureRandom
import java.security.cert.X509Certificate
import javax.net.ssl.HostnameVerifier
import javax.net.ssl.HttpsURLConnection
import javax.net.ssl.SSLContext
import javax.net.ssl.TrustManager
import javax.net.ssl.X509TrustManager
import org.json.JSONObject

class MainActivity : ComponentActivity() {
    private lateinit var binding: ActivityMainBinding
    private var filePathCallback: ValueCallback<Array<Uri>>? = null
    private var pendingPermissionRequest: PermissionRequest? = null
    private var cameraCaptureUri: Uri? = null
    private val pendingPdfDownloads = mutableSetOf<Long>()
    private var hasCheckedForAppUpdate = false

    private val downloadCompleteReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            if (intent?.action != DownloadManager.ACTION_DOWNLOAD_COMPLETE) return
            val downloadId = intent.getLongExtra(DownloadManager.EXTRA_DOWNLOAD_ID, -1L)
            if (downloadId == -1L || !pendingPdfDownloads.remove(downloadId)) return
            openDownloadedPdf(downloadId)
        }
    }

    private val notificationPermissionLauncher =
        registerForActivityResult(RequestPermission()) { granted ->
            if (granted) {
                MobileNotificationScheduler.schedule(this)
            }
        }

    private val filePickerLauncher =
        registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
            val callback = filePathCallback ?: return@registerForActivityResult
            val selectedUris = WebChromeClient.FileChooserParams.parseResult(result.resultCode, result.data)
            val resultUris = when {
                selectedUris != null -> selectedUris
                result.resultCode == RESULT_OK && cameraCaptureUri != null -> arrayOf(cameraCaptureUri!!)
                else -> null
            }
            callback.onReceiveValue(resultUris)
            filePathCallback = null
            cameraCaptureUri = null
        }

    private val permissionLauncher =
        registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { result ->
            val granted = result.values.all { it }
            val request = pendingPermissionRequest
            pendingPermissionRequest = null
            if (granted && request != null) {
                request.grant(request.resources)
            } else {
                request?.deny()
            }
        }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        installSplashScreen()
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, true)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)
        ViewCompat.requestApplyInsets(binding.root)
        registerDownloadReceiver()

        val webUrl = getString(R.string.web_base_url)
        ensureNotificationPermission()
        MobileNotificationScheduler.schedule(this)

        binding.retryButton.setOnClickListener {
            hideErrorCard()
            binding.webView.reload()
        }

        binding.swipeRefreshLayout.setOnRefreshListener {
            binding.webView.reload()
        }
        binding.swipeRefreshLayout.setColorSchemeResources(R.color.fersedo_primary, R.color.fersedo_accent)

        binding.webView.apply {
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.allowFileAccess = true
            settings.allowContentAccess = true
            settings.loadsImagesAutomatically = true
            settings.mediaPlaybackRequiresUserGesture = false
            settings.cacheMode = WebSettings.LOAD_DEFAULT
            settings.mixedContentMode = WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE
            settings.useWideViewPort = false
            settings.loadWithOverviewMode = false
            settings.builtInZoomControls = false
            settings.displayZoomControls = false
            settings.setSupportZoom(false)
            settings.javaScriptCanOpenWindowsAutomatically = true
            settings.setSupportMultipleWindows(true)
            settings.userAgentString = settings.userAgentString + " FersedoMobileWebView/1.0"

            CookieManager.getInstance().setAcceptCookie(true)
            CookieManager.getInstance().setAcceptThirdPartyCookies(this, true)

            webChromeClient = object : WebChromeClient() {
                override fun onShowFileChooser(
                    webView: WebView?,
                    filePathCallback: ValueCallback<Array<Uri>>?,
                    fileChooserParams: FileChooserParams?
                ): Boolean {
                    this@MainActivity.filePathCallback?.onReceiveValue(null)
                    this@MainActivity.filePathCallback = filePathCallback

                    try {
                        val chooserIntent = buildFileChooserIntent(fileChooserParams)
                        filePickerLauncher.launch(chooserIntent)
                        return true
                    } catch (_: ActivityNotFoundException) {
                        this@MainActivity.filePathCallback = null
                        Toast.makeText(
                            this@MainActivity,
                            getString(R.string.camera_error_message),
                            Toast.LENGTH_LONG,
                        ).show()
                    } catch (_: IOException) {
                        this@MainActivity.filePathCallback = null
                        Toast.makeText(
                            this@MainActivity,
                            getString(R.string.camera_error_message),
                            Toast.LENGTH_LONG,
                        ).show()
                    }

                    return false
                }

                override fun onPermissionRequest(request: PermissionRequest) {
                    val permissions = buildRuntimePermissions(request.resources)
                    if (permissions.isEmpty()) {
                        request.grant(request.resources)
                        return
                    }

                    val missing = permissions.filterNot { hasRuntimePermission(it) }
                    if (missing.isEmpty()) {
                        request.grant(request.resources)
                    } else {
                        pendingPermissionRequest = request
                        permissionLauncher.launch(missing.toTypedArray())
                    }
                }

                override fun onCreateWindow(
                    view: WebView?,
                    isDialog: Boolean,
                    isUserGesture: Boolean,
                    resultMsg: Message?
                ): Boolean {
                    val transport = resultMsg?.obj as? WebView.WebViewTransport ?: return false
                    transport.webView = binding.webView
                    resultMsg.sendToTarget()
                    return true
                }
            }

            webViewClient = object : WebViewClient() {
                override fun shouldOverrideUrlLoading(view: WebView?, request: WebResourceRequest?): Boolean {
                    val uri = request?.url ?: return false
                    return when (uri.scheme) {
                        "http", "https" -> {
                            if (uri.host == getString(R.string.trusted_internal_host)) {
                                false
                            } else {
                                startActivity(Intent(Intent.ACTION_VIEW, uri))
                                Toast.makeText(
                                    this@MainActivity,
                                    getString(R.string.external_browser),
                                    Toast.LENGTH_SHORT,
                                ).show()
                                true
                            }
                        }

                        "tel", "mailto", "geo" -> {
                            startActivity(Intent(Intent.ACTION_VIEW, uri))
                            true
                        }

                        else -> false
                    }
                }

                override fun onPageStarted(view: WebView?, url: String?, favicon: Bitmap?) {
                    binding.progressBar.visibility = View.VISIBLE
                    hideErrorCard()
                }

                override fun onPageFinished(view: WebView?, url: String?) {
                    binding.progressBar.visibility = View.GONE
                    binding.swipeRefreshLayout.isRefreshing = false
                    applyAndroidSafeAreaInset()
                    checkForAppUpdateOnce()
                }

                override fun onReceivedSslError(
                    view: WebView?,
                    handler: SslErrorHandler,
                    error: SslError?
                ) {
                    val trustedHost = getString(R.string.trusted_internal_host)
                    if (error?.url?.contains(trustedHost) == true) {
                        handler.proceed()
                    } else {
                        handler.cancel()
                        showErrorCard(getString(R.string.ssl_error_message))
                        Toast.makeText(
                            this@MainActivity,
                            getString(R.string.ssl_error_message),
                            Toast.LENGTH_LONG,
                        ).show()
                    }
                }

                override fun onReceivedError(
                    view: WebView?,
                    request: WebResourceRequest?,
                    error: WebResourceError?
                ) {
                    if (request?.isForMainFrame == true) {
                        binding.progressBar.visibility = View.GONE
                        binding.swipeRefreshLayout.isRefreshing = false
                        showErrorCard(error?.description?.toString().orEmpty())
                    }
                }
            }

            setDownloadListener(createDownloadListener())
            loadUrl(webUrl)
        }

        handleLaunchIntent(intent)

        onBackPressedDispatcher.addCallback(this) {
            if (binding.webView.canGoBack()) {
                binding.webView.goBack()
            } else {
                finish()
            }
        }
    }

    override fun onPause() {
        binding.webView.onPause()
        super.onPause()
    }

    override fun onResume() {
        super.onResume()
        binding.webView.onResume()
        MobileNotificationScheduler.schedule(this)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleLaunchIntent(intent)
    }

    override fun onDestroy() {
        binding.webView.apply {
            stopLoading()
            destroy()
        }
        unregisterReceiver(downloadCompleteReceiver)
        super.onDestroy()
    }

    private fun createDownloadListener(): DownloadListener {
        return DownloadListener { url, userAgent, contentDisposition, mimeType, _ ->
            val guessedFileName = URLUtil.guessFileName(url, contentDisposition, mimeType)
            val cookie = CookieManager.getInstance().getCookie(url)
            val uri = Uri.parse(url)

            if (uri.host == getString(R.string.trusted_internal_host)) {
                downloadInternalFile(
                    url = url,
                    fileName = guessedFileName,
                    mimeType = mimeType ?: guessMimeTypeFromName(guessedFileName),
                    userAgent = userAgent,
                    cookie = cookie,
                    referer = binding.webView.url ?: getString(R.string.web_base_url),
                )
                return@DownloadListener
            }

            val request = DownloadManager.Request(Uri.parse(url)).apply {
                setMimeType(mimeType)
                addRequestHeader("User-Agent", userAgent)
                if (!cookie.isNullOrBlank()) {
                    addRequestHeader("Cookie", cookie)
                }
                addRequestHeader("Referer", binding.webView.url ?: getString(R.string.web_base_url))
                setDescription(getString(R.string.download_description))
                setTitle(guessedFileName)
                setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
                setDestinationInExternalPublicDir(
                    Environment.DIRECTORY_DOWNLOADS,
                    guessedFileName,
                )
            }
            val manager = getSystemService(Context.DOWNLOAD_SERVICE) as DownloadManager
            val downloadId = manager.enqueue(request)
            if (
                (mimeType ?: "").contains("pdf", ignoreCase = true) ||
                guessedFileName.endsWith(".pdf", ignoreCase = true)
            ) {
                pendingPdfDownloads += downloadId
            }
            Toast.makeText(this, getString(R.string.download_started), Toast.LENGTH_SHORT).show()
        }
    }

    private fun downloadInternalFile(
        url: String,
        fileName: String,
        mimeType: String,
        userAgent: String,
        cookie: String?,
        referer: String,
    ) {
        Toast.makeText(this, getString(R.string.download_started), Toast.LENGTH_SHORT).show()

        Thread {
            val targetDir = File(getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS), "Fersedo")
            if (!targetDir.exists()) {
                targetDir.mkdirs()
            }

            val safeFileName = fileName.ifBlank { "fersedo_download" }
            val targetFile = File(targetDir, safeFileName)

            try {
                val endpoint = URL(url)
                val connection = (endpoint.openConnection() as HttpURLConnection).apply {
                    requestMethod = "GET"
                    connectTimeout = 20000
                    readTimeout = 60000
                    setRequestProperty("User-Agent", userAgent)
                    setRequestProperty("Referer", referer)
                    if (!cookie.isNullOrBlank()) {
                        setRequestProperty("Cookie", cookie)
                    }
                }

                if (connection is HttpsURLConnection && endpoint.host == getString(R.string.trusted_internal_host)) {
                    trustInternalHost(connection)
                }

                connection.connect()
                if (connection.responseCode !in 200..299) {
                    throw IOException("HTTP ${connection.responseCode}")
                }

                BufferedInputStream(connection.inputStream).use { input ->
                    FileOutputStream(targetFile).use { output ->
                        input.copyTo(output)
                    }
                }
                connection.disconnect()

                runOnUiThread {
                    openDownloadedFile(targetFile, mimeType)
                }
            } catch (error: Exception) {
                runOnUiThread {
                    Toast.makeText(
                        this,
                        "Преземањето не успеа: ${error.message ?: "непозната грешка"}",
                        Toast.LENGTH_LONG,
                    ).show()
                }
            }
        }.start()
    }

    private fun registerDownloadReceiver() {
        val filter = IntentFilter(DownloadManager.ACTION_DOWNLOAD_COMPLETE)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            registerReceiver(downloadCompleteReceiver, filter, Context.RECEIVER_NOT_EXPORTED)
        } else {
            registerReceiver(downloadCompleteReceiver, filter)
        }
    }

    private fun openDownloadedPdf(downloadId: Long) {
        val manager = getSystemService(Context.DOWNLOAD_SERVICE) as DownloadManager
        val query = DownloadManager.Query().setFilterById(downloadId)
        manager.query(query)?.use { cursor ->
            if (!cursor.moveToFirst()) return

            val status = cursor.getInt(cursor.getColumnIndexOrThrow(DownloadManager.COLUMN_STATUS))
            if (status != DownloadManager.STATUS_SUCCESSFUL) return

            val mimeType = cursor.getString(cursor.getColumnIndexOrThrow(DownloadManager.COLUMN_MEDIA_TYPE))
                ?: "application/pdf"
            val downloadUri = manager.getUriForDownloadedFile(downloadId) ?: return

            openDownloadedUri(downloadUri, mimeType)
        }
    }

    private fun openDownloadedFile(file: File, mimeType: String) {
        val authority = "${packageName}.fileprovider"
        val fileUri = FileProvider.getUriForFile(this, authority, file)
        openDownloadedUri(fileUri, mimeType)
    }

    private fun openDownloadedUri(uri: Uri, mimeType: String) {
        val openIntent = Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(uri, mimeType)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }

        try {
            startActivity(openIntent)
        } catch (_: ActivityNotFoundException) {
            Toast.makeText(
                this,
                getString(R.string.no_pdf_viewer_found),
                Toast.LENGTH_LONG,
            ).show()
        }
    }

    private fun checkForAppUpdateOnce() {
        if (hasCheckedForAppUpdate) return
        hasCheckedForAppUpdate = true

        Thread {
            try {
                val metadataUrl = getString(R.string.web_base_url).trimEnd('/') + "/android/release-meta"
                val endpoint = URL(metadataUrl)
                val connection = (endpoint.openConnection() as HttpURLConnection).apply {
                    requestMethod = "GET"
                    connectTimeout = 12000
                    readTimeout = 15000
                    setRequestProperty("Accept", "application/json")
                }

                if (connection is HttpsURLConnection && endpoint.host == getString(R.string.trusted_internal_host)) {
                    trustInternalHost(connection)
                }

                connection.connect()
                if (connection.responseCode !in 200..299) {
                    connection.disconnect()
                    return@Thread
                }

                val rawJson = connection.inputStream.bufferedReader().use { it.readText() }
                connection.disconnect()

                val root = JSONObject(rawJson)
                val androidMeta = root.optJSONObject("android") ?: return@Thread
                val remoteVersionCode = androidMeta.optLong("version_code", 0L)
                val remoteVersionName = androidMeta.optString("version_name", "").trim()
                val remoteVersionKey = androidMeta.optString("version_key", "").trim()
                val remoteDownloadUrl = androidMeta.optString("download_url", "").trim()

                if (remoteVersionCode <= 0L || remoteDownloadUrl.isBlank()) return@Thread

                val installedVersion = getInstalledVersionInfo()
                val hasUpdate =
                    remoteVersionCode > installedVersion.code ||
                    (remoteVersionCode == installedVersion.code &&
                        remoteVersionName.isNotBlank() &&
                        remoteVersionName != installedVersion.name)

                if (!hasUpdate) return@Thread

                val prefs = getSharedPreferences("fersedo_updates", Context.MODE_PRIVATE)
                val dismissedVersionKey = prefs.getString(KEY_DISMISSED_UPDATE_VERSION, null)
                if (!remoteVersionKey.isNullOrBlank() && dismissedVersionKey == remoteVersionKey) {
                    return@Thread
                }

                runOnUiThread {
                    if (isFinishing || isDestroyed) return@runOnUiThread
                    showAppUpdateDialog(
                        remoteVersionName = remoteVersionName.ifBlank { remoteVersionCode.toString() },
                        remoteVersionKey = remoteVersionKey,
                        downloadUrl = remoteDownloadUrl,
                    )
                }
            } catch (_: Exception) {
                // Silent by design: update check should never block app usage.
            }
        }.start()
    }

    private fun showAppUpdateDialog(
        remoteVersionName: String,
        remoteVersionKey: String,
        downloadUrl: String,
    ) {
        AlertDialog.Builder(this)
            .setTitle("Достапно е ажурирање")
            .setMessage(
                "Инсталирана е постара верзија на Fersedo. " +
                    "Достапна е нова APK верзија $remoteVersionName. " +
                    "Дали сакаш сега да ја преземеш?"
            )
            .setNegativeButton("Подоцна") { dialog, _ ->
                if (remoteVersionKey.isNotBlank()) {
                    getSharedPreferences("fersedo_updates", Context.MODE_PRIVATE)
                        .edit()
                        .putString(KEY_DISMISSED_UPDATE_VERSION, remoteVersionKey)
                        .apply()
                }
                dialog.dismiss()
            }
            .setPositiveButton("Ажурирај") { dialog, _ ->
                startApkUpdateDownload(downloadUrl, remoteVersionName)
                dialog.dismiss()
            }
            .setCancelable(true)
            .show()
    }

    private fun startApkUpdateDownload(downloadUrl: String, remoteVersionName: String) {
        val uri = Uri.parse(downloadUrl)
        val fileName = "Fersedo-v${remoteVersionName}.apk"
        val userAgent = binding.webView.settings.userAgentString ?: "FersedoMobileWebView"
        val referer = binding.webView.url ?: getString(R.string.web_base_url)
        val cookie = CookieManager.getInstance().getCookie(getString(R.string.web_base_url))

        if (uri.host == getString(R.string.trusted_internal_host)) {
            downloadInternalFile(
                url = downloadUrl,
                fileName = fileName,
                mimeType = "application/vnd.android.package-archive",
                userAgent = userAgent,
                cookie = cookie,
                referer = referer,
            )
            return
        }

        startActivity(Intent(Intent.ACTION_VIEW, uri))
    }

    private fun getInstalledVersionInfo(): InstalledVersionInfo {
        val packageInfo = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            packageManager.getPackageInfo(packageName, PackageManager.PackageInfoFlags.of(0))
        } else {
            @Suppress("DEPRECATION")
            packageManager.getPackageInfo(packageName, 0)
        }

        val versionCode = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            packageInfo.longVersionCode
        } else {
            @Suppress("DEPRECATION")
            packageInfo.versionCode.toLong()
        }

        return InstalledVersionInfo(
            name = packageInfo.versionName.orEmpty(),
            code = versionCode,
        )
    }

    private fun guessMimeTypeFromName(fileName: String): String {
        return when {
            fileName.endsWith(".pdf", ignoreCase = true) -> "application/pdf"
            fileName.endsWith(".xlsx", ignoreCase = true) -> "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            fileName.endsWith(".xls", ignoreCase = true) -> "application/vnd.ms-excel"
            else -> "*/*"
        }
    }

    private fun buildRuntimePermissions(resources: Array<String>): List<String> {
        val permissions = mutableListOf<String>()
        resources.forEach { resource ->
            when (resource) {
                PermissionRequest.RESOURCE_VIDEO_CAPTURE -> permissions += Manifest.permission.CAMERA
                PermissionRequest.RESOURCE_AUDIO_CAPTURE -> permissions += Manifest.permission.RECORD_AUDIO
            }
        }
        return permissions.distinct()
    }

    private fun hasRuntimePermission(permission: String): Boolean {
        return ContextCompat.checkSelfPermission(this, permission) == PackageManager.PERMISSION_GRANTED
    }

    @Throws(IOException::class)
    private fun buildFileChooserIntent(fileChooserParams: WebChromeClient.FileChooserParams?): Intent {
        val contentSelectionIntent = fileChooserParams?.createIntent() ?: Intent(Intent.ACTION_GET_CONTENT).apply {
            addCategory(Intent.CATEGORY_OPENABLE)
            type = "*/*"
        }

        val acceptsImages = fileChooserParams?.acceptTypes?.any { it.contains("image") } == true
        val initialIntents = mutableListOf<Intent>()
        if (acceptsImages) {
            createImageCaptureIntent()?.let(initialIntents::add)
        }

        return Intent(Intent.ACTION_CHOOSER).apply {
            putExtra(Intent.EXTRA_INTENT, contentSelectionIntent)
            putExtra(Intent.EXTRA_TITLE, getString(R.string.file_chooser_title))
            putExtra(Intent.EXTRA_INITIAL_INTENTS, initialIntents.toTypedArray())
        }
    }

    @Throws(IOException::class)
    private fun createImageCaptureIntent(): Intent? {
        val photoFile = createImageFile()
        val authority = "${packageName}.fileprovider"
        cameraCaptureUri = FileProvider.getUriForFile(this, authority, photoFile)

        return Intent(android.provider.MediaStore.ACTION_IMAGE_CAPTURE).apply {
            putExtra(android.provider.MediaStore.EXTRA_OUTPUT, cameraCaptureUri)
            addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
    }

    @Throws(IOException::class)
    private fun createImageFile(): File {
        val timeStamp = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.getDefault()).format(Date())
        val storageDir = getExternalFilesDir(Environment.DIRECTORY_PICTURES) ?: cacheDir
        return File.createTempFile("Fersedo_${timeStamp}_", ".jpg", storageDir)
    }

    private fun showErrorCard(message: String) {
        binding.errorMessage.text =
            if (message.isBlank()) getString(R.string.error_message_default) else message
        binding.errorCard.visibility = View.VISIBLE
    }

    private fun hideErrorCard() {
        binding.errorCard.visibility = View.GONE
    }

    private fun applyAndroidSafeAreaInset() {
        val script = """
            (function() {
                document.documentElement.classList.add('android-webview');
                document.documentElement.style.setProperty('--app-safe-top', '0px');
            })();
        """.trimIndent()
        binding.webView.evaluateJavascript(script, null)
    }

    private fun ensureNotificationPermission() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) {
            return
        }
        if (NotificationManagerCompat.from(this).areNotificationsEnabled()) {
            return
        }
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) ==
            PackageManager.PERMISSION_GRANTED
        ) {
            return
        }
        notificationPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
    }

    private fun handleLaunchIntent(intent: Intent?) {
        val targetUrl = intent?.getStringExtra(EXTRA_TARGET_URL)?.trim().orEmpty()
        if (targetUrl.isBlank()) {
            return
        }

        val absoluteUrl = when {
            targetUrl.startsWith("http://") || targetUrl.startsWith("https://") -> targetUrl
            else -> getString(R.string.web_base_url).trimEnd('/') + "/" + targetUrl.trimStart('/')
        }
        binding.webView.post { binding.webView.loadUrl(absoluteUrl) }
    }

    private fun trustInternalHost(connection: HttpsURLConnection) {
        val trustAll = arrayOf<TrustManager>(
            object : X509TrustManager {
                override fun checkClientTrusted(chain: Array<out X509Certificate>?, authType: String?) = Unit
                override fun checkServerTrusted(chain: Array<out X509Certificate>?, authType: String?) = Unit
                override fun getAcceptedIssuers(): Array<X509Certificate> = emptyArray()
            }
        )

        val sslContext = SSLContext.getInstance("TLS")
        sslContext.init(null, trustAll, SecureRandom())
        connection.sslSocketFactory = sslContext.socketFactory
        connection.hostnameVerifier = HostnameVerifier { host, _ ->
            host == getString(R.string.trusted_internal_host)
        }
    }

    data class InstalledVersionInfo(
        val name: String,
        val code: Long,
    )

    companion object {
        private const val KEY_DISMISSED_UPDATE_VERSION = "dismissed_update_version"
        const val EXTRA_TARGET_URL = "target_url"
    }
}
