package com.fersedo.mobile

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.webkit.CookieManager
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.net.HttpURLConnection
import java.net.URL
import java.security.SecureRandom
import java.security.cert.X509Certificate
import javax.net.ssl.HostnameVerifier
import javax.net.ssl.HttpsURLConnection
import javax.net.ssl.SSLContext
import javax.net.ssl.TrustManager
import javax.net.ssl.X509TrustManager

class MobileNotificationWorker(
    appContext: Context,
    params: WorkerParameters,
) : CoroutineWorker(appContext, params) {

    override suspend fun doWork(): Result {
        val prefs = applicationContext.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        val baseUrl = applicationContext.getString(R.string.web_base_url)
        val trustedHost = applicationContext.getString(R.string.trusted_internal_host)
        val cookie = CookieManager.getInstance().getCookie(baseUrl)

        if (cookie.isNullOrBlank()) {
            return Result.success()
        }

        val sinceId = prefs.getLong(KEY_LAST_NOTIFICATION_ID, 0L)
        val payload = fetchNotificationPayload(baseUrl, trustedHost, cookie, sinceId) ?: return Result.retry()

        if (!payload.optBoolean("success", false)) {
            return Result.retry()
        }

        createNotificationChannel()

        val items = payload.optJSONArray("items")
        if (items != null) {
            for (index in 0 until items.length()) {
                val item = items.optJSONObject(index) ?: continue
                showNotification(item)
            }
        }

        val lastId = payload.optLong("last_id", sinceId)
        prefs.edit().putLong(KEY_LAST_NOTIFICATION_ID, lastId).apply()
        return Result.success()
    }

    private fun fetchNotificationPayload(
        baseUrl: String,
        trustedHost: String,
        cookie: String,
        sinceId: Long,
    ): JSONObject? {
        val endpoint = URL("$baseUrl/api/mobile_notifications/poll?since_id=$sinceId")
        val connection = (endpoint.openConnection() as HttpURLConnection).apply {
            requestMethod = "GET"
            connectTimeout = 15000
            readTimeout = 15000
            setRequestProperty("Accept", "application/json")
            setRequestProperty("Cookie", cookie)
            setRequestProperty("X-Requested-With", "com.fersedo.mobile")
        }

        if (connection is HttpsURLConnection && endpoint.host == trustedHost) {
            trustInternalHost(connection)
        }

        return try {
            val responseCode = connection.responseCode
            if (responseCode == HttpURLConnection.HTTP_UNAUTHORIZED) {
                JSONObject().apply {
                    put("success", true)
                    put("last_id", sinceId)
                    put("items", org.json.JSONArray())
                }
            } else if (responseCode !in 200..299) {
                null
            } else {
                val text = BufferedReader(InputStreamReader(connection.inputStream)).use { it.readText() }
                JSONObject(text)
            }
        } finally {
            connection.disconnect()
        }
    }

    private fun showNotification(item: JSONObject) {
        val notificationId = item.optInt("id", (System.currentTimeMillis() % Int.MAX_VALUE).toInt())
        val targetUrl = item.optString("url", "/welcome")
        val title = item.optString("title", "Fersedo")
        val body = item.optString("body", "")

        val openIntent = Intent(applicationContext, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
            putExtra(MainActivity.EXTRA_TARGET_URL, targetUrl)
        }

        val pendingIntent = PendingIntent.getActivity(
            applicationContext,
            notificationId,
            openIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )

        val notification = NotificationCompat.Builder(applicationContext, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_stat_fersedo)
            .setContentTitle(title)
            .setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setAutoCancel(true)
            .setContentIntent(pendingIntent)
            .build()

        NotificationManagerCompat.from(applicationContext).notify(notificationId, notification)
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
            return
        }

        val manager = applicationContext.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        val channel = NotificationChannel(
            CHANNEL_ID,
            applicationContext.getString(R.string.notification_channel_name),
            NotificationManager.IMPORTANCE_HIGH,
        ).apply {
            description = applicationContext.getString(R.string.notification_channel_description)
        }
        manager.createNotificationChannel(channel)
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
            host == applicationContext.getString(R.string.trusted_internal_host)
        }
    }

    companion object {
        const val CHANNEL_ID = "fersedo_alerts"
        const val PREFS_NAME = "fersedo_mobile"
        const val KEY_LAST_NOTIFICATION_ID = "last_mobile_notification_id"
    }
}
