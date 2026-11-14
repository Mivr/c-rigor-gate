package org.example.owner;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/** A receiver in a second, explicitly listed Java package (the component name of a provisioned device cannot move). */
public final class Owner extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        // nothing to do: the example only proves a second package is declared, compiled, dexed and checked
    }
}
