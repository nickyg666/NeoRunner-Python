#!/usr/bin/env bash
# Build the NeoRunner Velocity router plugin against a Velocity proxy jar.
#
# Usage: build.sh <velocity-proxy.jar> [output.jar]
#
# No gradle/maven needed: the plugin uses only public API classes plus the
# runtime @Plugin/@Subscribe annotations from the proxy jar, and ships a
# hand-written velocity-plugin.json descriptor.
set -euo pipefail

VEL_JAR="${1:?usage: build.sh <velocity-proxy.jar> [output.jar]}"
OUT="${2:-$(dirname "$0")/neorunner-router-1.0.0.jar}"
SRC_DIR="$(dirname "$0")/src"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

mkdir -p "$WORK/classes"
find "$SRC_DIR" -name '*.java' > "$WORK/sources.txt"
javac --release 17 -cp "$VEL_JAR" -d "$WORK/classes" @"$WORK/sources.txt"
cp "$(dirname "$0")/velocity-plugin.json" "$WORK/classes/"
jar cf "$OUT" -C "$WORK/classes" .
echo "built: $OUT ($(stat -c%s "$OUT") bytes)"
