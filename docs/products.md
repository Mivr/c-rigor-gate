# Registered products

Each product has a gate-owned directory `products/<name>/` (`product.toml`, `policy.toml`, `expected-tests.json`,
`tasks/`; optional `architecture.toml`, [layering.md](layering.md), and `decoupling.toml` with its
`decoupling-baseline.toml`, [decoupling.md](decoupling.md)). Products never edit it; see [grade.md](grade.md) and [product-checks.md](product-checks.md).

| Product | Repo | Layout `include` | Notes |
|---|---|---|---|
| `annas-c` | `Mivr/annas-c` | `core/**`, `json/**`, `url/**`, ... (14 module directories) | The model product; policy is the standard deny list. |
| `business-apps` | `Mivr/business-apps` (private monorepo, cell `biz`) | `lib/**` | Add `apps/**` when the first app module lands (a pattern that matches nothing is `stale-include`). `main` holds `lib/base/core` only (131 tests), moved from annas-c `core`. |

## `c_library` parameters and `exported_deps` (T110)
`c_library(name, srcs, headers, deps, exported_deps, visibility, system_libs)`. `deps` are private: their headers are not
visible to the library's dependents. `exported_deps` (a literal list of labels, `c_library` only) are passed to the cxx
library as exported deps, so their headers and link inputs reach every dependent transitively. For every gate check
(facts, layering/architecture edges, fan-out counts, the mutants package, the witness scope) they are deps of THIS library:
the edge is `B -> C`, it must be allowed for B exactly as a plain dep is, and a dependent `A -> B` gains no edge to `C`.
If A's own sources use `C` (call its symbols), the `symbols` gate still reports `undeclared-symbol` unless A lists `C`
directly in `deps`: the gate checks symbols against the DIRECT deps' exports, never against what a header makes visible,
and that is unchanged. A label in both `deps` and `exported_deps` fails the package load with a clear message. `rigor buckfiles` accepts
`exported_deps` on `c_library` only, checked like `deps`.

**When to export.** Export exactly the libraries whose headers the library's PUBLIC headers include. Never export for
convenience, to save a dependent a line, or because the library's `.c` files use it (that is a private `deps` entry).

## Linking a sysroot library (T095)
A module that needs libpthread (business-apps `lib/io/osal`, the only module allowed to call pthread) declares it on its
library, and the product policy repeats it in that module's table (the gate's cross-check; both directions are errors):

```python
c_library(name = "osal", srcs = ["osal.c"], headers = ["osal.h"], system_libs = ["pthread"])
```
```toml
[module."//lib/io/osal:osal"]
system_libs = ["pthread"]
allow = ["pthread_create", "pthread_join"]    # the symbols it references are still checked as usual
```
`system_libs` is an allow-list of bare sysroot library names in `rules/c.bzl`: `pthread` (no link flag in the Android mode), `android` and `log` (T-G1: `-landroid`, `-llog`, Android mode only), and `X11` (T117: libX11 and its
link-time closure, [product-checks.md](product-checks.md#system-libraries-t095)); a new entry needs a product that needs it. It becomes the exported post-link flag `-lpthread`, resolved in the pinned sysroot by the toolchain's own link
line (never a host path), so every binary, test and mutant binary that links the library gets it; `c_mutants` reads the
flags from the library's link info (the module and its `deps`) and puts them after the objects and archives of its raw
links. The facts record `system_libs` per module. Details and findings: [product-checks.md](product-checks.md#system-libraries-t095).
Self-test: the last steps of `selftest/mutate.sh` (a real pthread in release and san, a binary, and the mutants of two modules).

## `c_android_so`: a shared object for Android (T-G2)
`c_android_so(name, exports, srcs, deps, system_libs, visibility)` links `lib<name>.so` for the `android` mode only
(`--target-platforms toolchains//:android_release`; every other mode reports it incompatible, and `c_binary` and `c_test`
are incompatible with the android mode). `exports` is the exact list of dynamic symbols: a generated GNU version script
makes them global and everything else local, `--no-undefined`, `relro`/`now` and `--gc-sections` are fixed, the flags are
the release list itself (`_RELEASE_COMPILE`), and the link is 16 KB page aligned. The output is checked by
`rules/elf_check.py` before it is published as the target's output: ELF64 AArch64 shared object with the standard header
sizes, every `PT_LOAD` segment aligned to a power of two that is a multiple of 16384 with offset and vaddr congruent, a real
string table, and a dynamic symbol table that defines exactly `exports` (no more, none missing, none twice). Nothing may
`deps` on a `c_android_so` or on what it derives (`<name>_facts`, `<name>__lib`, `<name>__map`): `buckfiles` refuses it.

**What `rigor grade` does with it** (`grade_checks._android_facts`): `<name>_facts` (kind `c_android_so`, rule
`c_android_facts`, which a `kind(c_facts, //...)` Linux query never selects) is built for `toolchains//:android_release`
together with the `android_so` output itself and `toolchains//:libc_symbols_android`. A `c_android_so` without its facts
target, or any build failure there, makes the fact gates NOT_RUN, which fails the verdict. The facts then go through the
same gates as every module, in the one directory: `semantic-suppressions`, `symbols` (the NDK export list is the reserved
list for the Android kinds, `facts_symbols.run(libc_android=...)`), `layering`, `decoupling` (kind judged: declared deps =
used deps) and `structure` (structure targets for the module are built in the android mode, `c_android_structure`, NDK
clang and roots). Canaries `android-so-denied-symbol` (a `getenv` call) and `android-so-inline-asm` fail the grade.

**What it does NOT grade (condition for T-A2)**: the facts cover the `.so`'s own `srcs` as the NDK compiles them. The
libraries in its dependency closure are graded from their Linux release facts only, so code under `#ifdef __ANDROID__`,
`__BIONIC__` or `__aarch64__` in a closure library is compiled for Android but never scanned, and no check compares the
release and android compiles of a library (no android `mode-divergence`). T-A2 must add an android facts twin per
library of that closure (a distinct facts label, selected by the closure of the `android_so` targets) and that comparison
before a product ships a closure that contains such code; until then a product must keep platform-conditional code in
the `c_android_so`'s own sources. Example: `examples/android`. Self-test: `selftest/android.sh`; unit tests:
`gate/tests/test_elf_check.py`, `gate/tests/test_grade_android.py`.

## `c_apk`: a signed APK of one `c_android_so` (T-G3)
`c_apk(name, so, package, label, version_code, version_name, orientation, permissions, assets, java_srcs, java_classes, java_packages, res_xml, application_class, receivers, launch_mode, lock_task_mode, exclude_from_recents, soft_input_mode, categories, visibility)` packages the
checked output of ONE `c_android_so` of the same BUCK file (`so = ":club"`; never its `__lib`, `buckfiles` refuses any `__`
or foreign label) into `<name>.apk`, and defines `<name>_check`. Android mode only. No other keyword exists: no `deps`, no
`srcs`, no flag, no manifest file or manifest XML, no javac or d8 option, no annotation processor, no SDK level, no signing
argument (`buckfiles` and the macro both refuse them).
The shared object must export exactly `ANativeActivity_onCreate`.

| Step (all on RE, pinned SDK) | What |
|---|---|
| manifest | `rules/apk_manifest.py` renders AndroidManifest.xml from the declaration. Validated: `package` (dotted lower-case), `label`, `version_name` (patterns), `version_code` (1..2100000000), `orientation` (landscape, portrait, sensorLandscape, unspecified), `permissions` (from `INTERNET`, `RECEIVE_BOOT_COMPLETED`), and the Java declarations below. Fixed: minSdk 28, targetSdk 35, `hasCode="true"` exactly when `java_srcs` is given (else `"false"`), `extractNativeLibs="false"`, one NativeActivity whose `lib_name` is the soname. |
| java (`java_srcs` only) | `rules/apk_java.py` runs the pinned JDK's javac (`java -m jdk.compiler/com.sun.tools.javac.Main`, `toolchains//:javac`) on the sources against platform-35 `android.jar` as boot class path: `-source 8 -target 8`, `-Xlint:all,-options`, `-Werror`, `-proc:none` (no annotation processor), `-implicit:none`, UTF-8. Then the pinned d8 (`--min-api 28 --lib android.jar`) into exactly one `classes.dex`. |
| res (`res_xml` only) | `aapt2 compile` of the files placed under `res/xml/`, passed to the link with `-R` |
| link | `aapt2 link` against platform-35 `android.jar` (and `assets`, plain file names under `assets/`, and the compiled `res_xml`) |
| pack | `rules/apk_pack.py` adds `classes.dex` (when there is Java) and `lib/arm64-v8a/lib<name>.so`; every entry STORED, fixed time and mode |
| align | `zipalign -f -P 16 4` (the stored object starts at a multiple of 16384) |
| sign | `apksigner sign` with the **TEST-ONLY debug key** `toolchains/android_debug.keystore` (public password `android`, alias `androiddebugkey`; its certificate SHA-256 is `toolchains/android_debug.cert.sha256`). It protects nothing: every product signs with the same public key. |

**Java and XML resources (T-G3b)**, all closed data (no manifest XML is accepted anywhere):
- `java_srcs`: plain `.java` file names of the BUCK package (a path such as `sub/X.java` or `../x/X.java` is refused). `java_classes`:
  the binary names (`org.example.club.A`, nested `org.example.club.A$B`) the dex must define, inside `package`; non-empty exactly
  when `java_srcs` is. Lambdas and other d8 synthetics would appear as classes of their own and must be declared too.
- `java_packages`: the Java packages the dex may define classes in; explicit dotted lower-case names (at least two parts, no wildcard),
  default `[package]` (giving the list replaces the default, so list the app package too). Every `java_classes` entry, `application_class`
  and receiver name must lie directly in one listed package (a sub-package is a different package and must be listed), and
  `apk_java.py` reads the `package` line of every `java_srcs` file and refuses one that is missing or not listed. Never allowed, as
  an entry or a prefix: `java`, `javax`, `android`, `androidx`, `dalvik`, `kotlin`, `com.android`. Use: a component whose name is fixed
  by an already provisioned device (the lockers' `org.simple.club.deviceowner.ClubDeviceAdminReceiver` in the app package
  `org.simple.club.lockers`) is listed as its own package, not by allowing "the parent package". The dex check still demands exactly
  `java_classes`. Example: `examples/android:app_pkg`.
- `res_xml`: plain `[a-z][a-z0-9_]*.xml` names, compiled by aapt2 into `res/xml/<name>.xml`.
- `application_class`: one of `java_classes` (the manifest's `android:name` of `<application>`).
- `receivers`: list (at most 8) of dicts with `name` (one of `java_classes`), `permission` (`""` or `BIND_DEVICE_ADMIN`), `exported`
  (True/False, always written out), `actions` (from `DEVICE_ADMIN_ENABLED`, `BOOT_COMPLETED`) and `meta_data` (only
  `"android.app.device_admin"`, mapped to a `res_xml` name without `.xml`).
- Activity: `launch_mode` (standard, singleTop, singleTask, singleInstance), `lock_task_mode` (`if_whitelisted`), `exclude_from_recents`,
  `soft_input_mode` (stateHidden, stateAlwaysHidden, adjustResize, adjustPan, adjustNothing) and `categories` (HOME, DEFAULT: added
  after LAUNCHER to the MAIN intent filter).
- `permissions` allow-list, each entry justified: `INTERNET` (sockets of the app), `RECEIVE_BOOT_COMPLETED` (a `BOOT_COMPLETED`
  receiver of a dedicated device that must come back after a power cut). `BIND_DEVICE_ADMIN` is a receiver `permission`, never a
  `uses-permission`. Adding to any of these closed lists is a gate change with its own review and a unit and selftest case.
- Without `java_srcs`, `res_xml` and the new keywords the rendered manifest and the APK are byte-for-byte what they were before T-G3b
  (proved on `examples/android:app`, sha256 `186b1b6d...68ae` before and after).
- Why not `--release 8`: it needs the JDK's `lib/ct.sym`, which the pinned tree does not hold (a member added to the tree means a new
  manifest and a new fetch). `-source 8 -target 8 -bootclasspath android.jar` is the same language level and checks against the real
  platform API; `-Xlint:all` stays on with `-Werror`, except the `options` category, whose only message is "source value 8 is obsolete".

`<name>_check` (a build action; `buck2 build` of it fails when the APK is not acceptable, and the grader builds the
`_check` of every `c_apk`, `grade_checks._android_facts`) runs `rules/apk_check.py`: **entries** (exactly the manifest,
`resources.arsc`, the object, the declared assets, `res/xml/<name>.xml` for each `res_xml` and `classes.dex` exactly when there is Java; no other file, no META-INF, no repeated name), **dex**
(`classes.dex` parses as a dex file by the small parser in `apk_check.py`: magic, header, adler32, bounds; its `class_defs` are exactly `java_classes`, none missing, none extra), **library** (STORED,
data at a multiple of 16384, then `rules/elf_check.py`: AArch64 shared object, LOAD alignment 16384, dynamic exports exactly
`ANativeActivity_onCreate`), **zipalign** (`-c -P 16 -v 4`), **signature** (`apksigner verify --min-sdk-version 28`: one
signer, v2 or v3 scheme (with minSdk 28 apksigner writes v3 only), and the signer certificate's SHA-256 equals the debug
certificate's), **manifest** (`aapt2 dump xmltree` of the APK equals that of the manifest rendered again from the declaration, receivers, application class and activity attributes included; the expected one is linked with stand-in `res/xml` files of the same names, so the resource ids agree).
`<name>_check[run]` is the same command without the APK (`buck2 run --target-platforms toolchains//:android_release
'//pkg:<name>_check[run]' -- OTHER.apk`).

**Release signing does not exist yet.** Nothing in `rules/apk*` reads an environment variable, a file of the product or a
config value; a release-signed APK fails the `signature` check by its certificate digest, so a release step must be a
separate, gate-owned step outside `c_apk` with its own check (open item). The lockers' own Java and JNI belong to T-A6.

**Pins** (the Rust kiosk's `toolchains/android.bzl`, owner-approved; same URLs, sha256 and sizes): build-tools r35
(`build-tools_r35_linux.zip`, sha256 `bd3a4966...1d88`), platform-35 r02 (`platform-35_r02.zip`, `0988caca...c8e0`), Temurin
JDK 21.0.6+7 (`OpenJDK21U-jdk_x64_linux_hotspot_21.0.6_7.tar.gz`, `a2650fba...dbae`). Members only (`toolchains/BUCK`):
`aapt2`, `zipalign`, `lib64/libc++.so`, `apksigner.jar`, `d8.jar`; `android.jar`; `bin/java`, `bin/keytool`, `lib/modules`,
the JVM and its libraries, `conf`, `lib/security`. Each tree has a manifest (`toolchains/{android_build_tools,android_platform,jdk}.manifest`)
and is verified by the `toolchain` grade gate with the other three (`toolchain_verify.TREES`). The tools are `toolchains//:aapt2`,
`:zipalign`, `:keytool`, `:apksigner`, `:d8`, `:javac` (RunInfo; javac is a module of the JDK's `lib/modules`, no `bin/javac` is fetched).

Examples: `examples/android:app` (no Java), `examples/android:app_java` (a Runnable, a DeviceAdminReceiver with application and boot
receiver, one `res/xml` file, the dedicated-device activity attributes). Self-test: `selftest/android.sh` (builds the APK and breaks
it: a misaligned APK, an extra file, a wrong export, an APK signed by another key, another manifest; and the Java one: a dex with an
extra class, a missing declared class, a corrupt dex, no dex, an undeclared res file, an undeclared receiver; a `java_srcs` file outside the
package, an unknown attribute and a javac warning are refused at analysis or by `-Werror`; each must fail with its own check). Unit tests:
`gate/tests/test_apk_rules.py`, `test_buckfiles.py`, `test_grade_android.py`, `test_toolchain_verify.py`.

## G25: the allocation deny list (P002)
`business-apps` adds, to annas-c's standard `[global]` deny list, every way to get memory outside a caller-supplied arena
or static storage. A reference to one of them in a graded module is a `symbols` FAIL (`denied-symbol`) unless that
module lists it in `allow` or is a trusted gate module (`gate//ctest:ctest`):

`malloc`, `calloc`, `realloc`, `free`, `aligned_alloc`, `posix_memalign`, `memalign`, `valloc`, `pvalloc`,
`reallocarray`, `strdup`, `strndup`, `asprintf`, `vasprintf`, `getline`, `getdelim`, `open_memstream`, `mmap`,
`munmap`, `mremap`, `brk`, `sbrk`.

Canaries `alloc-deny` (malloc and free) and `alloc-deny-strdup` keep it red.
