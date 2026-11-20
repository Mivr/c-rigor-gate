package org.example.club;

/** The smallest glue class: a Runnable that counts how often the UI thread ran it. */
public final class Tick implements Runnable {
    private int runs;

    @Override
    public void run() {
        runs++;
    }

    public int runs() {
        return runs;
    }
}
