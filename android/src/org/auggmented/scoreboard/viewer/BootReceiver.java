// SPDX-License-Identifier: GPL-3.0-or-later
package org.auggmented.scoreboard.viewer;

import android.Manifest;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.os.Build;

/** Offers a launch notification; it deliberately does not bypass background-start restrictions. */
public final class BootReceiver extends BroadcastReceiver {
    @Override public void onReceive(Context context, Intent intent) {
        if (!Intent.ACTION_BOOT_COMPLETED.equals(intent.getAction())) return;
        SharedPreferences preferences = context.getSharedPreferences(MainActivity.PREFERENCES, Context.MODE_PRIVATE);
        if (!preferences.getBoolean("notify_after_boot", false)
                || preferences.getString("server_url", "").isEmpty()) return;
        if (Build.VERSION.SDK_INT >= 33 && context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED) return;
        NotificationManager manager = (NotificationManager) context.getSystemService(Context.NOTIFICATION_SERVICE);
        if (manager == null) return;
        String channelId = "scoreboard-startup";
        if (Build.VERSION.SDK_INT >= 26) {
            manager.createNotificationChannel(new NotificationChannel(channelId,
                    "Scoreboard startup", NotificationManager.IMPORTANCE_LOW));
        }
        int flags = PendingIntent.FLAG_UPDATE_CURRENT;
        if (Build.VERSION.SDK_INT >= 23) flags |= PendingIntent.FLAG_IMMUTABLE;
        PendingIntent launch = PendingIntent.getActivity(context, 0,
                new Intent(context, MainActivity.class), flags);
        Notification.Builder builder = Build.VERSION.SDK_INT >= 26
                ? new Notification.Builder(context, channelId) : new Notification.Builder(context);
        manager.notify(1, builder.setSmallIcon(org.auggmented.scoreboard.viewer.R.drawable.viewer_icon)
                .setContentTitle("Open Auggmented Scoreboard")
                .setContentText("Tap to open your saved scoreboard server.")
                .setContentIntent(launch).setAutoCancel(true).build());
    }
}
