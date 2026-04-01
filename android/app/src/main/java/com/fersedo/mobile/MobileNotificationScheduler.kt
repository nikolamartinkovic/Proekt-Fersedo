package com.fersedo.mobile

import android.content.Context
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import java.util.concurrent.TimeUnit

object MobileNotificationScheduler {
    private const val PERIODIC_WORK_NAME = "fersedo_mobile_notifications_periodic"
    private const val IMMEDIATE_WORK_NAME = "fersedo_mobile_notifications_immediate"

    fun schedule(context: Context) {
        val constraints = Constraints.Builder()
            .setRequiredNetworkType(NetworkType.CONNECTED)
            .build()

        val periodicRequest = PeriodicWorkRequestBuilder<MobileNotificationWorker>(15, TimeUnit.MINUTES)
            .setConstraints(constraints)
            .build()

        val oneTimeRequest = OneTimeWorkRequestBuilder<MobileNotificationWorker>()
            .setConstraints(constraints)
            .build()

        WorkManager.getInstance(context).enqueueUniquePeriodicWork(
            PERIODIC_WORK_NAME,
            ExistingPeriodicWorkPolicy.UPDATE,
            periodicRequest,
        )
        WorkManager.getInstance(context).enqueueUniqueWork(
            IMMEDIATE_WORK_NAME,
            ExistingWorkPolicy.REPLACE,
            oneTimeRequest,
        )
    }
}
