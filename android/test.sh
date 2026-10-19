#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
set -euo pipefail
viewer_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ -n "${JAVA_HOME:-}" ]]; then
    java_bin="$JAVA_HOME/bin"
else
    java_bin="$(dirname -- "$(command -v javac || true)")"
fi
[[ -x "$java_bin/javac" ]] || { printf '%s\n' 'Install a full JDK 17 or newer and set JAVA_HOME.' >&2; exit 1; }
test_dir="$(mktemp -d "${TMPDIR:-/tmp}/scoreboard-android-tests.XXXXXX")"
trap 'rm -rf -- "$test_dir"' EXIT
"$java_bin/javac" --release 8 -encoding UTF-8 -d "$test_dir" \
    "$viewer_dir/src/org/auggmented/scoreboard/viewer/ViewerPolicy.java" \
    "$viewer_dir/tests/ViewerPolicyTest.java"
"$java_bin/java" -cp "$test_dir" org.auggmented.scoreboard.viewer.ViewerPolicyTest
