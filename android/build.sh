#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Small SDK-only debug build: no Gradle, native libraries, Python, or npm dependencies.
set -euo pipefail

viewer_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
sdk_dir="${ANDROID_SDK_ROOT:-${ANDROID_HOME:-}}"
build_tools_version="${ANDROID_BUILD_TOOLS_VERSION:-35.0.0}"
platform_version="${ANDROID_PLATFORM_VERSION:-35}"
if [[ -z "$sdk_dir" ]]; then
    printf '%s\n' 'Set ANDROID_SDK_ROOT to an Android SDK containing platforms;android-35 and build-tools;35.0.0.' >&2
    exit 1
fi
tools_dir="$sdk_dir/build-tools/$build_tools_version"
android_jar="$sdk_dir/platforms/android-$platform_version/android.jar"
if [[ -n "${JAVA_HOME:-}" ]]; then
    java_bin="$JAVA_HOME/bin"
else
    java_bin="$(dirname -- "$(command -v javac || true)")"
fi
for binary in javac java jar keytool; do
    if [[ ! -x "$java_bin/$binary" ]]; then
        printf 'Missing JDK tool: %s. Install a full JDK 17 or newer and set JAVA_HOME.\n' "$binary" >&2
        exit 1
    fi
done
for binary in aapt2 d8 zipalign apksigner; do
    if [[ ! -x "$tools_dir/$binary" ]]; then
        printf 'Missing Android SDK tool: %s\n' "$tools_dir/$binary" >&2
        exit 1
    fi
done
[[ -f "$android_jar" ]] || { printf 'Missing platform: %s\n' "$android_jar" >&2; exit 1; }
command -v zip >/dev/null || { printf '%s\n' 'Install the zip command.' >&2; exit 1; }

build_dir="$viewer_dir/.build"
dist_dir="$viewer_dir/dist"
mkdir -p "$build_dir" "$dist_dir"
rm -rf -- "$build_dir/generated" "$build_dir/classes" "$build_dir/dex"
mkdir -p "$build_dir/generated" "$build_dir/classes" "$build_dir/dex" "$build_dir/assets"
cp "$viewer_dir/../LICENSE" "$build_dir/assets/LICENSE"
"$tools_dir/aapt2" compile --dir "$viewer_dir/res" -o "$build_dir/resources.zip"
"$tools_dir/aapt2" link -o "$build_dir/resources.apk" \
    --manifest "$viewer_dir/AndroidManifest.xml" -I "$android_jar" -A "$build_dir/assets" \
    --java "$build_dir/generated" --debug-mode "$build_dir/resources.zip"
find "$viewer_dir/src" "$build_dir/generated" -name '*.java' -print > "$build_dir/sources.txt"
"$java_bin/javac" --release 8 -encoding UTF-8 -classpath "$android_jar" \
    -d "$build_dir/classes" @"$build_dir/sources.txt"
"$java_bin/jar" cf "$build_dir/classes.jar" -C "$build_dir/classes" .
"$tools_dir/d8" --min-api 22 --lib "$android_jar" --output "$build_dir/dex" "$build_dir/classes.jar"
cp "$build_dir/resources.apk" "$build_dir/unsigned.apk"
zip -q -j -X "$build_dir/unsigned.apk" "$build_dir"/dex/classes*.dex
"$tools_dir/zipalign" -f -p 4 "$build_dir/unsigned.apk" "$build_dir/aligned.apk"
if [[ ! -f "$build_dir/debug.keystore" ]]; then
    "$java_bin/keytool" -genkeypair -noprompt -keystore "$build_dir/debug.keystore" \
        -storetype JKS -storepass android -keypass android -alias androiddebugkey \
        -dname 'CN=Android Debug,O=Android,C=US' -keyalg RSA -keysize 2048 -validity 10000
fi
apk="$dist_dir/auggmented-scoreboard-viewer-debug.apk"
"$tools_dir/apksigner" sign --ks "$build_dir/debug.keystore" \
    --ks-key-alias androiddebugkey --ks-pass pass:android --key-pass pass:android \
    --out "$apk" "$build_dir/aligned.apk"
"$tools_dir/apksigner" verify --verbose "$apk"
"$tools_dir/zipalign" -c -p 4 "$apk"
printf '\nBuilt server-connected debug viewer: %s\n' "$apk"
printf '%s\n' 'This APK requires a running scoreboard server. It is not a standalone scoreboard.'
