"""The AndroidManifest.xml of a `c_apk`, rendered from validated attributes (stdlib only).

    apk_manifest.py SPEC.json LIB OUT

SPEC.json is what the `c_apk` macro declared: package, label, version_code, version_name, orientation, permissions, and
optionally (T-G3b) application_class, receivers, activity, java_classes and res_xml. All of it is closed data: names from fixed
tables, class names that must be declared `java_classes` of the package, resources that must be declared `res_xml`. No raw XML.
LIB is the file name of the packaged shared object (`libclub.so`); its soname is the NativeActivity `lib_name`.
Everything else is fixed here: minSdk 28, targetSdk 35 (plan P320, section 5), `hasCode="true"` exactly when `java_classes`
is not empty (a classes.dex is packaged) and "false" otherwise, `extractNativeLibs="false"` (the 16 KB aligned, stored object
is mapped from the APK), one NativeActivity.
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
# uses-permission allow-list (each addition is justified in docs/products.md): INTERNET (sockets), RECEIVE_BOOT_COMPLETED (a
# BOOT_COMPLETED receiver of a dedicated device).
PERMISSIONS = {"INTERNET": "android.permission.INTERNET", "RECEIVE_BOOT_COMPLETED": "android.permission.RECEIVE_BOOT_COMPLETED"}
# What a <receiver> may be protected by, listen for, and point its meta-data at (closed; docs/products.md).
RECEIVER_PERMISSIONS = {"BIND_DEVICE_ADMIN": "android.permission.BIND_DEVICE_ADMIN"}
RECEIVER_ACTIONS = {"DEVICE_ADMIN_ENABLED": "android.app.action.DEVICE_ADMIN_ENABLED",
                    "BOOT_COMPLETED": "android.intent.action.BOOT_COMPLETED"}
RECEIVER_META = ("android.app.device_admin",)           # the meta-data names; the value is a declared res_xml resource
LAUNCH_MODES = ("", "standard", "singleTop", "singleTask", "singleInstance")
LOCK_TASK_MODES = ("", "if_whitelisted")
SOFT_INPUT_MODES = ("", "stateHidden", "stateAlwaysHidden", "adjustResize", "adjustPan", "adjustNothing")
CATEGORIES = {"HOME": "android.intent.category.HOME", "DEFAULT": "android.intent.category.DEFAULT"}
MAX_RECEIVERS = 8
_PACKAGE = re.compile(r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+")
_LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,39}")
_VERSION_NAME = re.compile(r"[0-9A-Za-z][0-9A-Za-z._-]{0,31}")
_LIB = re.compile(r"lib([a-z][a-z0-9_]*)\.so")
_KEYS = ("label", "orientation", "package", "permissions", "version_code", "version_name")
_OPTIONAL = {"application_class": "", "receivers": [], "java_classes": [], "res_xml": [],
             "activity": {"launch_mode": "", "lock_task_mode": "", "exclude_from_recents": False, "soft_input_mode": "", "categories": []}}
_ACTIVITY_KEYS = ("categories", "exclude_from_recents", "launch_mode", "lock_task_mode", "soft_input_mode")
_RECEIVER_KEYS = ("actions", "exported", "meta_data", "name", "permission")
_CLASS = re.compile(r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*\.[A-Za-z_][A-Za-z0-9_]*(\$[A-Za-z0-9_]+)*")
_RES_XML = re.compile(r"[a-z][a-z0-9_]{0,39}\.xml")

_TEMPLATE = """<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="{package}"
    android:versionCode="{version_code}"
    android:versionName="{version_name}">
  <uses-sdk android:minSdkVersion="{min_sdk}" android:targetSdkVersion="{target_sdk}" />
{permissions}  <application
{application_name}      android:label="{label}"
      android:hasCode="{has_code}"
      android:extractNativeLibs="false"
      android:allowBackup="false">
    <activity
        android:name="android.app.NativeActivity"
        android:exported="true"
{activity_attributes}        android:screenOrientation="{orientation}"
        android:configChanges="orientation|keyboardHidden|screenSize">
      <meta-data android:name="android.app.lib_name" android:value="{lib_name}" />
      <intent-filter>
        <action android:name="android.intent.action.MAIN" />
        <category android:name="android.intent.category.LAUNCHER" />
{categories}      </intent-filter>
    </activity>
{receivers}  </application>
</manifest>
"""


def _full(spec):
    """The declaration with every optional key present (the six required ones are checked by `validate`)."""
    full = dict(spec)
    for key, default in _OPTIONAL.items():
        full.setdefault(key, json.loads(json.dumps(default)))
    return full


def _is_class(value, package):
    return isinstance(value, str) and _CLASS.fullmatch(value) is not None and value.startswith(package + ".") and len(value) <= 200


def _list_of(value, allowed):
    return isinstance(value, list) and all(isinstance(v, str) and v in allowed for v in value) and len(set(value)) == len(value)


def _activity_problems(activity):
    if not isinstance(activity, dict) or sorted(activity) != list(_ACTIVITY_KEYS):
        return ["activity must have exactly the keys %s" % ", ".join(_ACTIVITY_KEYS)]
    found = []
    for key, allowed in (("launch_mode", LAUNCH_MODES), ("lock_task_mode", LOCK_TASK_MODES), ("soft_input_mode", SOFT_INPUT_MODES)):
        if activity[key] not in allowed or not isinstance(activity[key], str):
            found.append("activity %s %r is not one of %s" % (key, activity[key], ", ".join(repr(a) for a in allowed if a)))
    if type(activity["exclude_from_recents"]) is not bool:
        found.append("activity exclude_from_recents must be true or false")
    if not _list_of(activity["categories"], CATEGORIES):
        found.append("activity categories must be a list without repeats from %s" % ", ".join(sorted(CATEGORIES)))
    return found


def _receiver_problems(receiver, package, classes, res_names):
    if not isinstance(receiver, dict) or sorted(receiver) != list(_RECEIVER_KEYS):
        return ["a receiver must have exactly the keys %s" % ", ".join(_RECEIVER_KEYS)]
    found = []
    name = receiver["name"]
    if not _is_class(name, package) or name not in classes:
        found.append("receiver %r must be one of the declared java_classes" % (name,))
    if receiver["permission"] != "" and receiver["permission"] not in RECEIVER_PERMISSIONS:
        found.append("receiver permission %r is not one of %s" % (receiver["permission"], ", ".join(sorted(RECEIVER_PERMISSIONS))))
    if type(receiver["exported"]) is not bool:
        found.append("receiver exported must be true or false")
    if not _list_of(receiver["actions"], RECEIVER_ACTIONS):
        found.append("receiver actions must be a list without repeats from %s" % ", ".join(sorted(RECEIVER_ACTIONS)))
    meta = receiver["meta_data"]
    if not isinstance(meta, dict) or any(k not in RECEIVER_META or not isinstance(v, str) or v + ".xml" not in res_names for k, v in meta.items()):
        found.append("receiver meta_data must map names from %s to a declared res_xml resource (without .xml)" % ", ".join(RECEIVER_META))
    return found


def validate(spec):
    """The reasons `spec` is not an acceptable manifest declaration (empty: it is)."""
    if not isinstance(spec, dict) or not set(_KEYS) <= set(spec) or not set(spec) <= set(_KEYS) | set(_OPTIONAL):
        return ["the declaration must have the keys %s and may have %s" % (", ".join(_KEYS), ", ".join(sorted(_OPTIONAL)))]
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
    if found:
        return found
    return found + _java_problems(_full(spec), package)


def _java_problems(spec, package):
    classes, res = spec["java_classes"], spec["res_xml"]
    found = []
    if not isinstance(classes, list) or len(set(map(str, classes))) != len(classes) or not all(_is_class(c, package) for c in classes):
        return ["java_classes must be a list without repeats of class names inside the package %s" % package]
    if not isinstance(res, list) or len(set(map(str, res))) != len(res) or not all(isinstance(r, str) and _RES_XML.fullmatch(r) for r in res):
        return ["res_xml must be a list without repeats of file names matching %s" % _RES_XML.pattern]
    app = spec["application_class"]
    if app != "" and (not _is_class(app, package) or app not in classes):
        found.append("application_class %r must be one of the declared java_classes" % (app,))
    found += _activity_problems(spec["activity"])
    receivers = spec["receivers"]
    if not isinstance(receivers, list) or len(receivers) > MAX_RECEIVERS:
        return found + ["receivers must be a list of at most %d" % MAX_RECEIVERS]
    for receiver in receivers:
        found += _receiver_problems(receiver, package, classes, res)
    names = [r.get("name") for r in receivers if isinstance(r, dict)]
    if len(set(map(str, names))) != len(names):
        found.append("receivers must not repeat a class")
    return found


def _activity_text(activity):
    attrs = (("launch_mode", "launchMode"), ("lock_task_mode", "lockTaskMode"), ("soft_input_mode", "windowSoftInputMode"))
    text = "".join('        android:%s="%s"\n' % (attr, activity[key]) for key, attr in attrs if activity[key])
    if activity["exclude_from_recents"]:
        text += '        android:excludeFromRecents="true"\n'
    return text


def _receiver_text(receiver):
    text = '    <receiver\n        android:name="%s"\n' % receiver["name"]
    if receiver["permission"]:
        text += '        android:permission="%s"\n' % RECEIVER_PERMISSIONS[receiver["permission"]]
    text += '        android:exported="%s">\n' % ("true" if receiver["exported"] else "false")
    for key, resource in receiver["meta_data"].items():
        text += '      <meta-data android:name="%s" android:resource="@xml/%s" />\n' % (key, resource)
    if receiver["actions"]:
        text += "      <intent-filter>\n"
        text += "".join('        <action android:name="%s" />\n' % RECEIVER_ACTIONS[a] for a in receiver["actions"])
        text += "      </intent-filter>\n"
    return text + "    </receiver>\n"


def render(spec, lib_file):
    """The manifest text; SystemExit with every reason when the declaration or the object name is not acceptable."""
    found = validate(spec)
    match = _LIB.fullmatch(lib_file)
    if not match:
        found.append("the packaged object %r must be named lib<name>.so with <name> matching [a-z][a-z0-9_]*" % (lib_file,))
    if found:
        sys.exit("apk_manifest: " + "; ".join(found))
    spec = _full(spec)
    permissions = "".join('  <uses-permission android:name="%s" />\n' % PERMISSIONS[p] for p in spec["permissions"])
    application_name = '      android:name="%s"\n' % spec["application_class"] if spec["application_class"] else ""
    categories = "".join('        <category android:name="%s" />\n' % CATEGORIES[c] for c in spec["activity"]["categories"])
    return _TEMPLATE.format(package=spec["package"], version_code=spec["version_code"], version_name=spec["version_name"],
                            min_sdk=MIN_SDK, target_sdk=TARGET_SDK, permissions=permissions, label=spec["label"],
                            orientation=spec["orientation"], lib_name=match.group(1), application_name=application_name,
                            has_code="true" if spec["java_classes"] else "false", categories=categories,
                            activity_attributes=_activity_text(spec["activity"]),
                            receivers="".join(_receiver_text(r) for r in spec["receivers"]))


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
