package org.example.club;

import android.app.Application;
import android.app.admin.DeviceAdminReceiver;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/** A minimal device-admin receiver with the application class and the boot receiver a dedicated device needs. */
public final class Admin extends DeviceAdminReceiver {
    @Override
    public void onEnabled(Context context, Intent intent) {
        super.onEnabled(context, intent);
    }

    /** The process entry. */
    public static final class App extends Application {
        @Override
        public void onCreate() {
            super.onCreate();
        }
    }

    /** BOOT_COMPLETED. */
    public static final class Boot extends BroadcastReceiver {
        @Override
        public void onReceive(Context context, Intent intent) {
            // nothing to do: the example only proves that the receiver is declared, compiled and packaged
        }
    }
}
