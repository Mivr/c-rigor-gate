"""The AndroidManifest.xml of a `c_apk`, rendered from validated attributes (stdlib only).

    apk_manifest.py SPEC.json LIB OUT

SPEC.json is what the `c_apk` macro declared: package, label, version_code, version_name, orientation, permissions.
LIB is the file name of the packaged shared object (`libclub.so`); its soname is the NativeActivity `lib_name`.
Everything else is fixed here: minSdk 28, targetSdk 35 (plan P320, section 5), `hasCode="false"` (no dex: Java support is
T-A6), `extractNativeLibs="false"` (the 16 KB aligned, stored object is mapped from the APK), one NativeActivity.
`render` is also what `apk_check.py` compares the APK's manifest against, so the two cannot drift apart.
Every attribute is checked against a pattern first, so nothing reaches the XML that could close an attribute or add an element.
"""

import json
import re
import sys

MIN_SDK = 28
TARGET_SDK = 35
ENTRY = "ANativeActivity_onCreate"
ORIENTATIONS = ("landscape", "portrait", "sensorLandscape", "unspecified")
PERMISSIONS = {"INTERNET": "android.permission.INTERNET"}
_PACKAGE = re.compile(r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+")
_LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,39}")
_VERSION_NAME = re.compile(r"[0-9A-Za-z][0-9A-Za-z._-]{0,31}")
_LIB = re.compile(r"lib([a-z][a-z0-9_]*)\.so")
_KEYS = ("label", "orientation", "package", "permissions", "version_code", "version_name")

_TEMPLATE = """<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="{package}"
    android:versionCode="{version_code}"
    android:versionName="{version_name}">
  <uses-sdk android:minSdkVersion="{min_sdk}" android:targetSdkVersion="{target_sdk}" />
{permissions}  <application
      android:label="{label}"
      android:hasCode="false"
      android:extractNativeLibs="false"
      android:allowBackup="false">
    <activity
        android:name="android.app.NativeActivity"
        android:exported="true"
        android:screenOrientation="{orientation}"
        android:configChanges="orientation|keyboardHidden|screenSize">
      <meta-data android:name="android.app.lib_name" android:value="{lib_name}" />
      <intent-filter>
        <action android:name="android.intent.action.MAIN" />
        <category android:name="android.intent.category.LAUNCHER" />
      </intent-filter>
    </activity>
  </application>
</manifest>
"""


def validate(spec):
    """The reasons `spec` is not an acceptable manifest declaration (empty: it is)."""
    if not isinstance(spec, dict) or sorted(spec) != list(_KEYS):
        return ["the declaration must have exactly the keys %s" % ", ".join(_KEYS)]
    found = []
    package, label, name = spec["package"], spec["label"], spec["version_name"]
    code, orientation, permissions = spec["version_code"], spec["orientation"], spec["permissions"]
    if not isinstance(package, str) or not _PACKAGE.fullmatch(package) or len(package) > 120:
        found.append("package %r is not a dotted lower-case Java package name" % (package,))
    if not isinstance(label, str) or not _LABEL.fullmatch(label):
        found.append("label %r must match %s" % (label, _LABEL.pattern))
    if not isinstance(name, str) or not _VERSION_NAME.fullmatch(name):
        found.append("version_name %r must match %s" % (name, _VERSION_NAME.pattern))
    if type(code) is not int or not 1 <= code <= 2100000000:
        found.append("version_code %r must be an integer from 1 to 2100000000" % (code,))
    if orientation not in ORIENTATIONS:
        found.append("orientation %r is not one of %s" % (orientation, ", ".join(ORIENTATIONS)))
    if not isinstance(permissions, list) or any(p not in PERMISSIONS for p in permissions) or len(set(permissions)) != len(permissions):
        found.append("permissions must be a list without repeats from %s" % ", ".join(sorted(PERMISSIONS)))
    return found


def render(spec, lib_file):
    """The manifest text; SystemExit with every reason when the declaration or the object name is not acceptable."""
    found = validate(spec)
    match = _LIB.fullmatch(lib_file)
    if not match:
        found.append("the packaged object %r must be named lib<name>.so with <name> matching [a-z][a-z0-9_]*" % (lib_file,))
    if found:
        sys.exit("apk_manifest: " + "; ".join(found))
    permissions = "".join('  <uses-permission android:name="%s" />\n' % PERMISSIONS[p] for p in spec["permissions"])
    return _TEMPLATE.format(package=spec["package"], version_code=spec["version_code"], version_name=spec["version_name"],
                            min_sdk=MIN_SDK, target_sdk=TARGET_SDK, permissions=permissions, label=spec["label"],
                            orientation=spec["orientation"], lib_name=match.group(1))


def main(argv):
    if len(argv) != 4:
        sys.exit(__doc__)
    with open(argv[1], encoding="utf-8") as handle:
        spec = json.load(handle)
    text = render(spec, argv[2])
    with open(argv[3], "w", encoding="utf-8") as handle:
        handle.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
