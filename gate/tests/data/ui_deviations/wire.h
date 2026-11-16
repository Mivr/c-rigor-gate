/* apps/lockers/lkapp/wire/wire.h: the lockers composition root (DESIGN 4.8, 2.4). Level L2. Included as
 * "apps/lockers/lkapp/wire/wire.h". It lays out the one static object lk_mem_t, constructs every adapter from the ports
 * of an lk_wire_io_t (real or simulated), patches LK_WIRING, fills the runtime cfg, starts the three step functions on
 * threads (or lets a test step them) and decides the exit code. Deps: lkapp/runtime, lkapp/e2e, lk/config, lk/syncbody
 * (via synchttp), lkadp/{inventoryfile, bookfile, auditfile, codeshttp, synchttp, e2eclock}, relay/{driver, pulse},
 * posix_listen, rtprio, fp, lk/book, lk/code, lkrx (folds, reactors), lkui/catalog, lib/rt/{rx, mbox, tlog}, lib/ds/blob.
 * No allocation, no mutable static data (the caller owns the lk_mem_t), no recursion, bounded loops. Not thread-safe except
 * as stated per function. lk/config/config.h is NOT included here (its lk_config_t was named like the fold_core config
 * slice, now lk_config_slice_t; G1 CLOSED): the parsed config lives in opaque bytes of lk_mem_t.
 *
 * RS = the Rust kiosk, the behaviour oracle (D8). RS-main = apps/lockers main.rs, RS-sess = session lib.rs, RS-boot = boot
 * lib.rs, RS-desk = desktop.rs. Rust wins over the docs unless the C architecture (step functions on threads, mailboxes,
 * LK_WIRING) makes the Rust rule inapplicable; each such case is a Deviation (D) below.
 *
 * ---- Argv (lk_wire_parse_args; RS-main dispatch 60-83, tests 152-227) -----------------------------------------------
 * A1  argv[0] is the program name and is skipped (Rust skip(1)). Exactly two more arguments must follow: a flag and a
 *     NON-EMPTY path. "--config <path>" is RUN, "--check-config <path>" is CHECK. Anything else (no argument, an unknown
 *     flag, a missing or empty path, a third argument, argc <= 0, argv NULL, a NULL element) is USAGE. (D1: parse_launch is
 *     not staged; this is derived from RS-main's tests: [] and ["--missing"] and ["--check-config", ""] are USAGE.)
 *     The returned path points into argv (it is not copied).
 * A2  Exit codes (RS-main 33-37): LK_WIRE_EXIT_OK 0, LK_WIRE_EXIT_FAIL 1, LK_WIRE_EXIT_USAGE 2. USAGE writes ONE non-empty
 *     line (ending in LF) with io->write_err and touches nothing else (RS-main prints the error and returns USAGE).
 *     The USAGE line is exactly "usage: lockers --config <path> | --check-config <path>" (C only: RS-main prints the text of
 *     lockers_config's LaunchError::Usage, which is not staged; this is the C text).
 * A3  CHECK hands over to lkapp/checkconfig through io->check_config (lkapp/checkconfig depends on wire, not the other way
 *     round): lk_wire_run calls io->check_config(io->ctx, path) ONCE and returns its value; nothing else happens (no config
 *     read, no directory, no lock, no relay call, no thread, nothing written). A NULL hook is USAGE (2).
 *
 * A4  lk_wire_run with m NULL or io NULL returns LK_WIRE_EXIT_FAIL (1) before it looks at argv: no hook, no callback, no
 *     line (C only: Rust has no NULL; with no io there is nothing to write on, and a missing object is a failed start,
 *     never USAGE or CHECK).
 *
 * ---- Boot order and fail-closed rules (lk_wire_init; RS-sess open_session_sharing 331-434, RS-main launch_config 86-115) --
 * Every failure below writes ONE line (the text, then LF) with io->write_err and returns its error; every error maps to
 * LK_WIRE_EXIT_FAIL. No relay frame of any kind is written by init, and nothing is started. In this order:
 * (Z) Cleanup (RS-sess Drop 105-128: dropping the session closes the board link, which releases its lock): when init
 *     fails after B5 opened the board (io->open_relay answered true), then when init returns the inner transport has been
 *     closed exactly once and the lock, if it was held, released exactly once, whichever step failed (B5's driver refusal,
 *     B6, B7, B8, B10, B11). A failure before that (B1-B4, B5's lock key, open_relay false) closes and releases nothing.
 *     A successful init closes nothing (T4 does).
 * B1  io->read_config(path, buf, 8192): UNREADABLE (or a text over 8192 bytes, D2) -> LK_WIRE_E_CONFIG, "could not read the
 *     config file"; EXPOSED (readable by group or others) -> E_CONFIG, "config file is readable by group or others".
 *     The mode check is the callback's (kfs has no mode). RS-main 90-96.
 * B2  lk_config_parse (lk_config_parse_harness when io->harness) of the text: an error -> E_CONFIG, the sentence of
 *     lk_config_err_line. RS-main 100-107. With io->harness the four soak keys are known; without it they are UNKNOWN.
 * B3  io->open_dir(data_dir, create=true): false -> LK_WIRE_E_DATA_DIR, "could not create the data directory"
 *     (RS-boot 37, RS-sess 151-156; the directory is created with mode 0700 by the callback). Then the audit directory
 *     (config audit_dir, else "<data_dir>/audit" as lk_config_audit_dir) the same way and with the same failure.
 * B4  Inventory (RS-sess load_inventory 140-145): inventory_file "" -> the built-in table; else the path is split at its
 *     LAST '/' into a directory (the whole text before it; "." when there is no '/'; "/" for a root file) and a name, the
 *     directory is opened with io->open_dir(dir, create=false) and inventoryfile_load reads the name (16 KiB cap). Any
 *     failure, the open included -> LK_WIRE_E_INVENTORY, "could not load the locker inventory".
 * B5  Relay (RS-sess 349 DialingBoard::start; RS waveshare-relay connect_board: "Connect, holding relay_lock_path for the life of
 *     the driver. The TCP connection is opened only after the lock is held. A contended lock is ConnectError::Busy and does
 *     not open a socket"; RS DialingBoard keeps an empty link slot until a dial succeeds, open returns I/O and never pulses
 *     while it is empty, dials repeat at relay_retry_period): io->open_relay(&addr) gives the inner transport; false ->
 *     LK_WIRE_E_BOOT, "kiosk worker did not start" (D3). The driver gets a WRAPPER transport (lk_mem_t.transport) and a
 *     relay_lock_t that always says ACQUIRED and whose release does nothing (no per-flight file lock, as RS: acquire_flight
 *     is for drivers without a lifetime lock). The lock key is relay_lock_path(addr, port, io->lock_dir).
 *     (1) Every connection attempt takes the lock FIRST: one ports_lock acquire with a deadline already passed (the clock
 *         now), before any inner connect_start; it is held as long as the connection lives and released when the wrapper's
 *         close is called (stop, or the driver closing after a link drop), never earlier. With io->relay_connected the
 *         lock is taken at init for the already-open connection.
 *     (2) A busy or unavailable lock (any status but OK) is a FAILED DIAL: no inner connect_start (no socket), the relay
 *         counts as down (relay_status up 0, the boot reactor announces relay_down), the dial repeats at the driver's
 *         redial period (1 s), and no frame is ever written. At init it makes the driver start DOWN even with
 *         relay_connected. It is never a boot error. An inner connect_start that fails releases the lock again.
 *     (3) Within a connection a flight (open, probe) takes no further file lock: one acquire per connection.
 *     (4) The lock key holds at most 255 bytes (lock_key is 256 with its NUL). A relay_lock_path that does not fit, or that
 *         refuses (a dir kind that is not one of its three), is LK_WIRE_E_BOOT "kiosk worker did not start" BEFORE
 *         io->open_relay is called: no board, no lock call, no close (C only: RS-LOCK's path is a PathBuf and cannot
 *         overflow). A key of exactly 255 bytes is accepted.
 *     (5) relay_driver_init refusing is E_BOOT "kiosk worker did not start", after the board opened (so cleanup (Z) closes
 *         it). The only argument the caller supplies that it checks and init does not check up front is the clock's
 *         now_ms: a clock table whose now_ms is NULL (init checks only that the ports and their ops tables are present,
 *         which is E_ARG with no line). C only.
 *     The driver starts UP iff io->relay_connected and the lock was taken, else DOWN (OPEN/READ are refused with
 *     RELAY_OFFLINE while it dials). drain, write, read and connect_poll pass through unchanged.
 * B6  Objects: slices (session starts at the clock's now with the 2 s splash), rx over LK_WIRING (B9), mailboxes (core
 *     inbox 3 lanes 8/16/128, opener inbox 8, net inbox 16, scene slot), the two codeset blobs (owner core, in the codes
 *     slice's refs table), the snapshot blob pool (2 blobs), bookfile, auditfile (an open failure is NOT fatal, RS
 *     "a_failed_start_audit_keeps_the_kiosk_up"), codeshttp, synchttp, the runtime core/opener/net objects, tlog rings.
 *     An object that refuses its cfg -> LK_WIRE_E_BOOT, "kiosk worker did not start". So is an io->version longer than
 *     LK_AUDIT_VERSION_MAX bytes (the copy has a fixed buffer; exactly that many bytes are accepted. C only: RS-sess keeps
 *     a String, and fail closed beats a truncated version in the audit log). Sync off (sync_url ""): synchttp
 *     is initialised with a placeholder and never used (boot_config.sync_on is 0, so no cmd_sync_upload exists).
 *     The placeholder URL is an http:// loopback one, which synchttp accepts only with a `plain` port: that is io->sync_plain.
 *     (L305) The io ports: B6 passes codes_stream as codeshttp_cfg_t.stream, codes_plain as codeshttp_cfg_t.plain,
 *     sync_stream as synchttp_cfg_t.stream and sync_plain as synchttp_cfg_t.plain. A URL's scheme picks the port: an
 *     `http://` loopback URL (the club e2e harness's codes_url, the sync-off placeholder) dials ONLY the plain port, an
 *     `https://` URL ONLY the stream (TLS) port; so a boot with codes_url=http://127.0.0.1:N makes no call on codes_stream.
 * B7  Book (RS-sess worker; lkrx/boot B6): bookfile_load into the BOOK slice. OK or EMPTY: post book_loaded {entries =
 *     lk_book_count, uncertain = number of reservations with pending != 0}. A store error is NOT a boot error: post
 *     book_load_failed {reason 0}; the storage fault screen (LKS_FAULT_STORAGE) shows once the 2 s splash minimum passed
 *     (lkrx/view R1) and the pad does nothing until the kiosk is started again. The book is never saved after a failed load.
 *     A book_* post that cannot be queued (the UI lane of the core inbox is full) is a boot error: LK_WIRE_E_BOOT, "kiosk
 *     worker did not start" (RS BootError::Boot; C only: a kiosk whose first message was lost would sit on the splash for
 *     ever, so it fails closed). The lane has 128 places, so the two boot posts fit exactly when 126 are taken.
 * B8  Then post boot_config {codes_refresh_secs, codes_cache_max_age_secs, sync_interval_secs (each saturated at
 *     UINT32_MAX), version_id = io->version_id, language, sync_on = (sync_url != "")}. Both posts use the UI lane of
 *     the core inbox, in the order book_* then boot_config (they are queued before any thread exists, DESIGN 4.8 step 5).
 *     A boot_config post that cannot be queued is the same boot error as B7's (E_BOOT, "kiosk worker did not start").
 *     The boot reactor answers boot_config with app_started, cmd_codes_refresh and a READ relay probe (never a pulse).
 * B9  LK_WIRING is COPIED (R8): wiring.folds/reactors point at the lk_mem_t's own arrays, fold i's fn is the real fold
 *     (lk_fold_session .. lk_fold_secret, LK_FOLD_* order) and reactor i's fn is the real reactor (lk_react_pad, codes,
 *     visit, shift, boot, notice, sync, LK_RX_* order); every other field is LK_WIRING's. LK_WIRING itself is const.
 * B10 Wall clock (RS clock offset): ports_wall over io->wall plus config clock_offset_ms (sec/ms arithmetic; UNSYNCED
 *     stays UNSYNCED). With io->harness and the soak keys clock_epoch_ms or clock_advance_file selecting it
 *     (virtual_selected) the core's wall is lkadp/e2eclock over that wall: epoch = clock_epoch_ms or the wall at init,
 *     scale = clock_scale, the two files as (directory, name) pairs split like B4 and opened with open_dir(create=false);
 *     a file whose directory cannot be opened is not configured. Monotonic deadlines always use io->clock.
 *     lk_e2eclock_init refusing its cfg (lkadp/e2eclock: a scale of 0, or, for a file whose directory opened, an empty or
 *     over-long name such as the path "/clk/") is LK_WIRE_E_BOOT, "kiosk worker did not start" (RS soak_clock.rs open_scaled
 *     and parse_scale errors are boot errors, RS-main 100-107). Without virtual_selected nothing about the files is
 *     checked and no e2eclock is made.
 * B11 e2e: only when io->harness && lk_e2e_requested(io->e2e_env). The listener is lkapp/e2e's lk_e2e_listener_ops_t over
 *     a posix_listen plis_t built on io->listen_sys/listen_ctx (listen -> plis_listen, accept -> plis_accept, read ->
 *     plis_recv, write -> plis_send, close_conn -> plis_close_conn, close -> plis_close; PLIS_OK/AGAIN/NET/ARG map to
 *     LK_E2E_LIS_*; an io->listen_sys that is NULL with the gate open makes plis_init refuse: LK_WIRE_E_E2E, "ui event
 *     loop failed", nothing announced, no listener call; C only, since the seam is C's), the catalog is lk_catalog, the tree buffer LK_E2E_TREE_CAP
 *     bytes of lk_mem_t, the language the
 *     configured one at init and, from then on, the language of the newest published scene (E2E LANGUAGE, closes D5). lk_e2e_init failing ->
 *     LK_WIRE_E_E2E, "ui event loop failed" (RS-desk 96-117 + RS-boot 47).
 *     On success write_out gets lk_e2e_announce's "CLUB_A11Y 127.0.0.1:PORT\n" (before init returns). Without the
 *     gate no listener call is made and nothing is announced.
 *
 * ---- The step host (single thread; threads call the same functions) -------------------------------------------------------
 * lk_wire_core_step / opener_step / net_step call lkrt_core_step / lkrt_opener_step / lkrt_net_step on the objects built by
 * init and return their wake. lk_wire_core_step adds the BOOT CODES WATCH (D6): while no codes_loaded was seen, a
 * codes_failed with reason LK_CFAIL_CACHE_MISSING or LK_CFAIL_CACHE_OLD in the rx log is the fatal "could not refresh
 * allowed codes" stop of RS-boot 52-55: lk_wire_fatal becomes LK_WIRE_EXIT_FAIL, lk_wire_stopping true, and the text is
 * "could not refresh allowed codes: no saved list" (MISSING) or "...: saved list too old" (OLD) (RS-boot 56-60;
 * "unreadable" cannot be told from "missing", D7), printed once by lk_wire_run after the join. A later codes_failed, and
 * any codes_failed after a codes_loaded, is not fatal (the stale banner is fold_status's).
 * E2E LANGUAGE (closes D5). The a11y text of the e2e tree is in the language of the visitor's screen, as the UI thread renders it:
 * every lk_wire_ui_step that holds a published scene calls lk_e2e_set_lang(e2e, snapshot.lang) BEFORE lk_e2e_step, so a language
 * switch (or the idle reset) published by the runtime (runtime.h C5, the snapshot's `lang`) shows in the next tree reply, not
 * only after a restart. When no scene was published yet, or the adopt is refused (a damaged copy), the language is left as it
 * was and lk_e2e_step gets a NULL scene (its rule E4). The configured language is only the first one (B11).
 * lk_wire_ui_step(now): with e2e live, copies the newest published scene (mbox_latest_read), adopts it as a scene_t with
 * scene_adopt (G2) and runs lk_e2e_step once; returns its wake; LK_E2E_NEVER when e2e is not live or was stopped. lk_wire_post: one intent into the
 * UI lane (lkrt_ui_post). lk_wire_scene: mbox_latest_read of the scene slot.
 * READ-ONLY ACCESSORS (for a step host that observes the kiosk, such as the lockers UI model adapter; they change nothing
 * and take no lock, so a threaded host calls them only from the thread that steps the core, or after stop):
 *   lk_wire_event_log(m): the rx event log of the core (rx_log), or NULL for a NULL or never-initialised m (io NULL).
 *   lk_wire_stats(m, out): the counters of the three step functions (lkrt_core_stats, lkrt_opener_stats,
 *     lkrt_net_stats) into *out; false and *out zeroed for a NULL out (then nothing written), a NULL or never-initialised
 *     m, or a refusal of any of the three (never a partial copy).
 *   lk_wire_relay_busy(m): relay_driver_is_busy of the kiosk's driver (a command in flight); false for a NULL or
 *     never-initialised m.
 *
 * ---- Threads (lk_wire_start / lk_wire_stop; RS-sess spawn_worker 231-310) ---------------------------------------------------
 * T1  start: io->osal mem_lock once (best effort, never fatal), then thread_start in the order OPENER, NET, CORE on the
 *     static stacks of lk_mem_t (opener 64 KiB, net 256 KiB, core 128 KiB). A second start (threads already started) is
 *     refused: LK_WIRE_E_ARG, nothing started (no mem_lock, no thread_start). A thread_start failure stops the ones started,
 *     joins them and returns LK_WIRE_E_BOOT (text "kiosk worker did not start"). The UI thread belongs to the shell.
 * T2  the OPENER thread first raises its own priority: rtprio_inherit, rtprio_plan(io->platform), rtprio_apply on io->osal,
 *     one line via io->write_err "opener priority: <rtprio_log>" (RS arm_opener_thread 312-314; hardware-safety rule 3;
 *     a refusal is logged and the thread goes on). Then it loops opener_step. Core and net never ask for priority.
 * T3  every thread loops: step, then wait until min(wake, now + LK_WIRE_POLL_MS) on a private sleeper (D8: mbox has no
 *     wait-without-take, so the hosts poll; the bound keeps a posted command within 5 ms), until stop. Only the runtime
 *     posts to the opener inbox (cmd_open, cmd_relay_probe); the root never builds a relay command or frame.
 * T4  stop (lk_wire_stop; quit, signal, window closed, or a fatal): sets the stop flag, wakes the sleepers, and closes the
 *     OPENER INBOX first (a post to it after stop is MBOX_CLOSED), so nothing new is accepted; a cmd_open already waiting
 *     in it is dropped, never pulsed: the opener never starts a command after stop. Then it joins the threads. A pulse in
 *     flight is stepped to its result (the board turns the coil off itself, flash-on; the watchdog all-off is the driver's).
 *     TRANSPORT CLOSE: when stop returns with the driver idle, the transport has been closed exactly once, whether or not
 *     threads ran (stop closes it itself if the opener has not); with a pulse in flight the close happens when that pulse
 *     finishes (in a step host: in the opener step that produces the result). So every coil is off once the transport is
 *     closed. Idempotent; also works with no threads started. Without threads (step host) the opener step keeps running
 *     the in-flight command, takes no new one, and closes when idle.
 *
 * ---- kfs objects and threads (L281; ports.h: "one thread at a time per kfs object"; L284: posix_fs temp name per file) ----------
 * K1  Every ports_kfs_t that wire hands out is used by ONE thread after start (init, before any thread exists, may use any of
 *     them). The core and the net thread each get their OWN kfs object: separate open_dir calls of the SAME data directory and
 *     the SAME audit directory (files stay where Rust keeps them; no new directory, no layout change). Today (G9a, closed by L281/L288):
 *       data   (data_dir)   core: bookfile (book), auditfile salt, runtime free_bytes   | net: codeshttp (codes.cache), synchttp (sync.state)
 *       audit  (audit_dir)  core: auditfile append/list/truncate/remove                 | net: synchttp (E1 collect, lists the day files)
 *       clk_adv, clk_frz    the e2eclock files: the ONE EXCEPTION to K1, used by core and net, only under clk_mu (K3)
 *       inventory dir       init only (B4), not kept
 *     STORAGE (fields of lk_mem_t, readable by tests): m->data, m->audit are the CORE's objects (bookfile, auditfile, the core cfg's
 *     `data`); m->net_data, m->net_audit are the NET thread's: codeshttp's `kfs` and synchttp's `data` get m->net_data, synchttp's
 *     `audit` gets m->net_audit. Nothing of the net side may be carved out of another buffer (no overlay of boot_scratch).
 *     With the K1 and K3 fields sizeof(lk_mem_t) is 2554752 bytes (under LK_WIRE_MEM_MAX, 4 MiB; layout_test asserts the bound).
 *     OPEN ORDER. The two extra opens are the first thing lkw_adapters (B6) does, so after B10's clock directories and before any
 *     object is made: the open_dir calls of one init are, in this order, (1) data_dir create=true, (2) audit dir create=true,
 *     (3) the inventory file's directory create=false (only with inventory_file), (4, 5) the clock files' directories create=false
 *     (only with the virtual clock: advance file, then freeze file, each only when configured), then (6) data_dir again and (7) the
 *     audit dir again, both create=false (B3 created them) into m->net_data and m->net_audit.
 *     FAILURE. A net open_dir that answers false is, like B3's, LK_WIRE_E_DATA_DIR with the line "could not create the data
 *     directory" (the data one and the audit one alike: there is one text), after the board opened, so cleanup (Z) closes the
 *     transport once and releases the lock once. kfs objects have no close: wire closes none, the io owns them.
 * K2  A FILE is written by one thread only. Writers: book, audit.salt and the audit day files (append, truncate, remove): core;
 *     codes.cache and sync.state: net. A reader on the other thread only where this header says so: synchttp reads the audit day
 *     files from net (list, read_at). A day file that core is still appending is read as a prefix; its last line may be torn and
 *     is a line without LF that syncbody P1-P6 pass over (synchttp E1; the next step reads it whole). Two kfs objects on one
 *     directory write through separate temp names, because posix_fs names its temp per file (L284, "." + name + ".tmp"), so
 *     they no longer collide (G9c, closed by L284/L286).
 * K3  ONE e2eclock object serves the core wall and the net wall (never two: they would not share the latched files). Wire
 *     serialises it with an osal mutex around every now_utc, as posixio S1 does for the clock, so one object reads and latches
 *     the files and its kfs (clk_adv, clk_frz) are used by one thread at a time (G9b, closed by L281/L288).
 *     STORAGE: m->clk_mu (ports_mutex_t, a mutex of its own: NOT m->mu, which the thread join holds while it joins, so a wall
 *     read from a thread being joined would deadlock on it); m->sw (lk_wire_swall_t: the e2eclock's wall port, the osal and
 *     &m->clk_mu); m->wall (the core's wall, which the core cfg gets) and m->net_wall (which codeshttp gets). With the virtual
 *     clock both are the SAME serialised port {sw's ops, &m->sw}. Without it (no harness, or no soak key selects the virtual
 *     clock) there is no e2eclock: m->wall and m->net_wall are both the plain offset wall of B10 (stateless, not wrapped), no
 *     mutex is made and none is ever taken.
 *     BOOT: the mutex is made in B10 with mutex_init(want inherit = false), after lk_e2eclock_init succeeded. A refusing osal
 *     (mutex_init answers any status but OK, or the callback is NULL) is LK_WIRE_E_BOOT, "kiosk worker did not start" (cleanup Z
 *     applies). READ: now_utc takes the mutex, reads the e2eclock wall, releases it; a mutex_lock that fails (or a NULL
 *     callback) is PORTS_WALL_E_UNSYNCED with out untouched (the host has no trustworthy time); a failed unlock does not change
 *     the answer. DESTROY: never; like the other mutexes of lk_mem_t it dies with the process (cleanup Z does not destroy it).
 *     Tests: tests/kfsthreads_test.c (k1_*, k2_*, k3_*). All of them pass since L288 (k3_every_clock_file_call_holds_the_clock_mutex
 *     is the clock files' test; the k2_* tests and k3_without_the_virtual_clock_no_mutex_is_taken guard the writer rule and the plain wall).
 *     G9  CLOSED ((a) and (b) by L281/L288, (c) by L284/L286: posix_fs per-key temp name). It was: (a) separate kfs objects per
 *     thread for data and audit (same directories); (b) the e2eclock wall mutex; (c) a dependency on L284, the posix_fs
 *     per-file temp name, before K1+K2 hold on real files.
 *
 * ---- Run (lk_wire_run) ------------------------------------------------------------------------------------------------------
 * R1  parse args (A1, A3); init (B1..B11), error -> its line, exit 1; start (T1), error -> its line, exit 1; ui_run:
 *     io->ui_run(io->ctx, m) blocks until the window closes (NULL: waits until lk_wire_stopping); then stop (T4);
 *     a fatal prints its line, exit 1; ui_run returning non-zero is exit 1; else exit 0. RS-main 108-114.
 *
 * ---- Snapshot fill (lk_wire_snapshot_fill; runtime.h C4 cmd_sync_upload; synchttp SN1) ------------------------------
 * S1  ctx is a const lk_secret_slice_t*, book_slice a const lk_book_slice_t*. False (blob untouched) when an argument is
 *     NULL, blob_size < SYNCHTTP_SNAP_HEADER, the secret is not ready, the book is not loaded, or book.now_ms < 0.
 * S2  Rows, in book order, for every reservation r that is active at book.now_ms (lk_resv_active) or uncertain
 *     (lk_resv_uncertain): code_hash = SHA-256(salt[32] || ASCII digits of the code) (fp_sha256; the audit fingerprint),
 *     first_scan_at = max(first_scan_ms, 0), openings, locker, pending, rsv 0. Head: taken_at = book.now_ms, count, rsv 0.
 *     More rows than min(256, (blob_size - 16) / 48) -> false (never a truncated snapshot; the blob is then unspecified).
 *
 * ---- Gaps in the dependency headers (reported, not fixed here) ----------------------------------------------------------
 * G1  CLOSED (L278: the slice is lk_config_slice_t). lk_config_t was defined twice (lk/config/config.h and
 *     lkrx/fold_core.h, the config slice): no TU can include both, so the parsed config is opaque bytes here and config.h
 *     is used only in src/config.c. Wire still keeps the parsed config opaque (a later option: include config.h here).
 * G2  CLOSED (L283: scene_adopt in lib/ui/scene/scene.h; the snapshot carries `lang`, runtime.h C5). It was: scene.h has no "adopt a
 *     published snapshot": the UI side rebuilt a scene_t by scene_init and assigning n_nodes and args_used (public fields).
 *     The snapshot also carried no language (D5).
 * G3  mbox has no "wait for a post without taking" (T3 polls); runtime.h tells the host to block in mbox_take, which
 *     would consume the event.
 * G4  The codes miss kind "unreadable" (RS CodesMiss::Unreadable) is merged into CACHE_MISSING by codeshttp N4 (D7).
 * G5  The offline line "lockers: Codes offline: using the list saved at HH:MM" (runbook 2) is an event fact the root cannot see.
 * G6  CLOSED (L272/L282: the real io builder is lkapp/posixio, lk_posixio_build; the TLS arena sits beside lk_mem_t in the
 *     shell's posixio object). It was: Real io construction (posix_fs/net/lock/clock/rand over libc, tls_stream with the CA
 *     bundle and heap, the 768 KiB TLS arena of DESIGN 5.1) is not part of this module: the shell builds an lk_wire_io_t;
 *     lk_mem_t holds no TLS arena.
 * G8  CLOSED (L267/L271: lkrx/boot B10 requests the periodic cmd_codes_refresh, corr LK_BOOT_CORR_REFRESH). It was: No reactor emits the periodic
 * cmd_codes_refresh (lkrx/boot B2 asks only for the first one, lkrx/codes D1 leaves the period to boot): the
 *     refresh schedule and its free-blob choice have no owner, so the root cannot run them (tests send the command).
 * G7  The runtime has no hook for the core to ask the root to stop: the root reads the rx log (D6).
 * Deviations: D1 argv derived (A1). D2 config text cap 8 KiB (C only). D3 open_relay can fail. D4 as RS: the lock is held for the life of the connection
 * for the process. D5 CLOSED (L283, E2E LANGUAGE): was e2e language fixed. D6 boot codes fatal found in the rx log, asynchronously. D7 "unreadable" merged.
 * D8 polling hosts. */
#ifndef LKWIRE_WIRE_H
#define LKWIRE_WIRE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "apps/lockers/lkadp/auditfile/auditfile.h"
#include "apps/lockers/lkadp/bookfile/bookfile.h"
#include "apps/lockers/lkadp/codeshttp/codeshttp.h"
#include "apps/lockers/lkadp/e2eclock/e2eclock.h"
#include "apps/lockers/lkadp/synchttp/synchttp.h"
#include "apps/lockers/lkapp/e2e/e2e.h"
#include "apps/lockers/lkapp/runtime/runtime.h"
#include "apps/lockers/lkrx/fold_core/fold_core.h"
#include "apps/lockers/lkrx/fold_status/fold_status.h"
#include "apps/lockers/relay/driver/driver.h"
#include "apps/lockers/relay/pulse/pulse.h"
#include "lib/io/posix_listen/posix_listen.h"
#include "lib/rt/rtprio/rtprio.h"

#define LK_WIRE_EXIT_OK 0
#define LK_WIRE_EXIT_FAIL 1
#define LK_WIRE_EXIT_USAGE 2
#define LK_WIRE_CONFIG_MAX 8192u
#define LK_WIRE_INVENTORY_MAX 16384u
#define LK_WIRE_POLL_MS 5u
#define LK_WIRE_OWNER_CORE 1u
#define LK_WIRE_OWNER_NET 2u
#define LK_WIRE_CODES_CAP 10240u
#define LK_WIRE_QCAP 64u
#define LK_WIRE_LOG_CAP 1024u
#define LK_WIRE_SNAP_BLOBS 2u
#define LK_WIRE_SNAP_BLOB_BYTES 12304u
#define LK_WIRE_CFG_BYTES 2560u
#define LK_WIRE_SOAK_BYTES 640u
#define LK_WIRE_STACK_CORE 131072u
#define LK_WIRE_STACK_OPENER 65536u
#define LK_WIRE_STACK_NET 262144u
#define LK_WIRE_MEM_MAX (4u << 20) /* sizeof(lk_mem_t) must not exceed it (the DESIGN 5 budget without UI and TLS) */

typedef struct lk_mem lk_mem_t;

typedef enum { LK_WIRE_ARGS_RUN = 0, LK_WIRE_ARGS_CHECK, LK_WIRE_ARGS_USAGE } lk_wire_mode_t;
typedef struct {
    lk_wire_mode_t mode;
    core_str_t path; /* RUN, CHECK: into argv; USAGE: {NULL, 0} */
} lk_wire_args_t;

typedef enum {
    LK_WIRE_OK = 0,
    /* init: E_ARG, with no line written and m untouched, is exactly: m NULL; io NULL; or any of io->read_config, open_dir,
     * open_relay, write_out, write_err, osal, osal->ops, clock.ops, wall.ops, rand.ops, lock.ops, codes_stream.ops,
     * sync_stream.ops, codes_plain.ops, sync_plain.ops NULL (all four, whatever the URL schemes: the plain ports are
     * required too). A port table that is present but has a NULL callback is NOT E_ARG: it is not checked up front
     * and the first user refuses it (for the clock's now_ms see B5 (5): E_BOOT). check_config, ui_run and listen_sys are
     * optional here (listen_sys is needed only with the e2e gate open, B11: E_E2E). start: a second lk_wire_start while
     * threads are started (T1). */
    LK_WIRE_E_ARG,
    LK_WIRE_E_CONFIG,
    LK_WIRE_E_DATA_DIR,
    LK_WIRE_E_INVENTORY,
    LK_WIRE_E_BOOT,
    LK_WIRE_E_E2E
} lk_wire_err_t;

typedef enum { LK_WIRE_READ_OK = 0, LK_WIRE_READ_UNREADABLE, LK_WIRE_READ_EXPOSED } lk_wire_read_t;

typedef struct { /* the relay board address from the config (mirror of lk_cfg_addr_t) */
    uint8_t family; /* 4 or 6 */
    uint8_t ip[16];
    uint16_t port;
    uint32_t scope_id;
} lk_wire_addr_t;

/* Everything the root needs from the world. Every pointer/callback is required unless marked optional. ctx is passed to
 * each callback. Callbacks other than write_err/write_out/ui_run run on the thread that calls init; write_err is also called by
 * the opener thread (T2). */
typedef struct {
    void *ctx;
    lk_wire_read_t (*read_config)(void *ctx, core_str_t path, void *buf, size_t cap, size_t *n);
    bool (*open_dir)(void *ctx, core_str_t path, bool create, ports_kfs_t *out);
    bool (*open_relay)(void *ctx, const lk_wire_addr_t *addr, relay_transport_t *out);
    void (*write_out)(void *ctx, core_str_t text);
    void (*write_err)(void *ctx, core_str_t text);
    int (*check_config)(void *ctx, core_str_t path); /* optional (A3) */
    int (*ui_run)(void *ctx, lk_mem_t *m);      /* optional (R1) */
    const ports_osal_t *osal;
    ports_clock_t clock;
    ports_wall_t wall;
    ports_random_t rand;
    ports_lock_t lock;
    ports_stream_t codes_stream, sync_stream; /* TLS: https:// URLs only (tls_stream_port) */
    ports_stream_t codes_plain, sync_plain;   /* plain TCP: http:// loopback URLs only (pnet_stream_port) (L305) */
    const plis_sys_t *listen_sys; /* optional unless the e2e gate is open */
    void *listen_ctx;
    const char *e2e_env; /* getenv("CLUB_E2E"), may be NULL */
    core_str_t version;  /* app_started's version text, at most LK_AUDIT_VERSION_MAX bytes */
    uint32_t version_id;
    relay_lock_dir_t lock_dir;
    rtprio_platform_t platform;
    bool harness;           /* the e2e/soak build */
    bool relay_connected;   /* B5 */
} lk_wire_io_t;

typedef struct {
    ports_wall_t inner; /* io->wall */
    int64_t offset_ms;  /* config clock_offset_ms (B10) */
} lk_wire_wall_t;

typedef struct { /* K3: the e2eclock wall port behind its own mutex */
    ports_wall_t inner;      /* lk_e2eclock_wall(...) */
    const ports_osal_t *osal; /* io->osal */
    ports_mutex_t *mu;       /* &lk_mem_t.clk_mu */
} lk_wire_swall_t;

/* lk_mem_t: the one static object. Its parts are the wire's; the fields named in the comments are READABLE by tests. */
struct lk_mem {
    unsigned char cfg_[LK_WIRE_CFG_BYTES] __attribute__((aligned(16)));   /* the parsed lockers.conf (opaque, G1) */
    unsigned char soak_[LK_WIRE_SOAK_BYTES] __attribute__((aligned(16))); /* the harness soak keys (opaque) */
    rx_t rx;
    rx_slice_t sl[LK_SLICE_COUNT];
    rx_fold_desc_t folds[LK_FOLD_COUNT];       /* B9 */
    rx_reactor_desc_t reacts[LK_RX_COUNT];     /* B9 */
    rx_wiring_t wiring;                        /* B9 */
    lk_session_t ses;
    lk_book_slice_t book;
    lk_clock_t clk;
    lk_inventory_slice_t inv;
    lk_config_slice_t slice_cfg;                   /* the config SLICE (fold_config), not lockers.conf */
    lk_notice_slice_t notice;
    lk_codes_slice_t codes;
    lk_relay_slice_t relay;
    lk_health_slice_t health;
    lk_shift_slice_t shift;
    lk_secret_slice_t secret;
    ev_t queue[LK_WIRE_QCAP], logst[LK_WIRE_LOG_CAP];
    ev_t lane0[LKRT_CORE_LANE_OPENER_CAP], lane1[LKRT_CORE_LANE_NET_CAP], lane2[LKRT_CORE_LANE_UI_CAP];
    ev_t op_lane[LKRT_OPENER_INBOX_CAP], net_lane[LKRT_NET_INBOX_CAP], sleep_lane[1], osleep_lane[1];
    mbox_t inbox, opener_inbox, net_inbox;
    mbox_t sleeper, osleeper;                  /* private sleepers of T3: core and net wait on sleeper, which T4 closes; the opener on osleeper */
    mbox_latest_t slot;
    lkrt_scene_snap_t slot_buf[2];
    lkrt_scene_snap_t ui_snap;
    ports_kfs_t data, audit;
    ports_kfs_t net_data, net_audit;           /* K1: the net thread's own objects (codeshttp kfs, synchttp data and audit) */
    bookfile_t bf;
    auditfile_t af;
    char bf_scratch[BOOKFILE_SCRATCH_MIN];
    unsigned char boot_scratch[LK_WIRE_INVENTORY_MAX] __attribute__((aligned(16))); /* config 8 KiB | inventory 16 KiB */
    unsigned char scratch[65536] __attribute__((aligned(16)));
    unsigned char index[4096] __attribute__((aligned(8)));
    blob_pool_t cpool, spool;
    blob_h_t ch[2];
    unsigned char cslots[2u * 389376u] __attribute__((aligned(16)));
    unsigned char sslots[LK_WIRE_SNAP_BLOBS * LK_WIRE_SNAP_BLOB_BYTES];
    uint8_t cown[2], sown[LK_WIRE_SNAP_BLOBS];
    uint16_t cnext[2], cgen[2], snext[LK_WIRE_SNAP_BLOBS], sgen[LK_WIRE_SNAP_BLOBS];
    tlog_rec_t tl_core[32], tl_opener[32], tl_net[32];
    tlog_t tlog_core, tlog_opener, tlog_net;
    relay_transport_t transport, inner; /* transport: the wrapper the driver gets (B5); inner: io->open_relay's */
    relay_lock_t rlock;
    relay_driver_t driver;
    codeshttp_t chttp;
    synchttp_t shttp;
    lkrt_core_cfg_t core_cfg;                  /* the cfg given to lkrt_core_init (readable) */
    lkrt_opener_cfg_t opener_cfg;
    lkrt_net_cfg_t net_cfg;
    lkrt_core_t core;
    lkrt_opener_t opener;
    lkrt_net_t net;
    lkrt_ui_t ui;
    plis_t plis;
    lk_e2e_t e2e;
    lk_e2eclock_t e2eclock;
    lk_wire_wall_t ow;
    ports_wall_t wall;                         /* the core's wall port (B10) */
    ports_wall_t net_wall;                     /* K3: codeshttp's wall; with the virtual clock the same port as wall */
    lk_wire_swall_t sw;                        /* K3 */
    ports_mutex_t clk_mu;                      /* K3: the e2eclock's mutex (not mu) */
    ports_kfs_t clk_adv, clk_frz;              /* B10: the e2eclock files' directories */
    bool e2e_live;
    char tree[LK_E2E_TREE_CAP];
    char version[LK_AUDIT_VERSION_MAX + 1u];
    char lock_key[256];
    _Alignas(16) unsigned char cwork[CODESHTTP_WORK_BYTES];
    _Alignas(16) unsigned char swork[SYNCHTTP_WORK_BYTES];
    _Alignas(16) unsigned char stack_core[LK_WIRE_STACK_CORE];
    _Alignas(16) unsigned char stack_opener[LK_WIRE_STACK_OPENER];
    _Alignas(16) unsigned char stack_net[LK_WIRE_STACK_NET];
    ports_thread_t th[3];
    ports_mutex_t mu;
    const lk_wire_io_t *io;                    /* kept: must outlive the lk_mem_t's use */
    uint64_t log_cursor, ui_ver;
    uint8_t started, stop, fatal, codes_seen, fatal_reason, closed, lock_held; /* started: bit i = thread i (0 opener, 1 net, 2 core) */
};

_Static_assert(LK_WIRE_SNAP_BLOB_BYTES == 16u + 256u * 48u, "snapshot blob: head and 256 rows");

lk_wire_args_t lk_wire_parse_args(int argc, const char *const *argv);
int lk_wire_run(lk_mem_t *m, const lk_wire_io_t *io, int argc, const char *const *argv);
lk_wire_err_t lk_wire_init(lk_mem_t *m, const lk_wire_io_t *io, core_str_t config_path);
lk_wire_err_t lk_wire_start(lk_mem_t *m);
void lk_wire_stop(lk_mem_t *m);
bool lk_wire_stopping(lk_mem_t *m);
int lk_wire_fatal(const lk_mem_t *m); /* LK_WIRE_EXIT_OK (no fatal) or LK_WIRE_EXIT_FAIL */
uint64_t lk_wire_core_step(lk_mem_t *m, uint64_t now);
uint64_t lk_wire_opener_step(lk_mem_t *m, uint64_t now);
uint64_t lk_wire_net_step(lk_mem_t *m, uint64_t now);
uint64_t lk_wire_ui_step(lk_mem_t *m, uint64_t now);
bool lk_wire_post(lk_mem_t *m, const ev_t *e);
bool lk_wire_scene(lk_mem_t *m, uint64_t seen_ver, lkrt_scene_snap_t *out, uint64_t *ver);
bool lk_wire_snapshot_fill(void *ctx, const void *book_slice, void *blob, size_t blob_size);

typedef struct {
    lkrt_core_stats_t core;
    lkrt_opener_stats_t opener;
    lkrt_net_stats_t net;
} lk_wire_stats_t;

const elog_t *lk_wire_event_log(const lk_mem_t *m);
bool lk_wire_stats(const lk_mem_t *m, lk_wire_stats_t *out);
bool lk_wire_relay_busy(const lk_mem_t *m);

#endif
