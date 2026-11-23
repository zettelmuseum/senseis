#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
: "${ANDROID_HOME:=${ANDROID_SDK_ROOT:-}}"
: "${ANDROID_HOME:?ANDROID_HOME or ANDROID_SDK_ROOT must be set}"
BUILD_TOOLS_VERSION="${BUILD_TOOLS_VERSION:-35.0.0}"
ANDROID_API="${ANDROID_API:-35}"
BUILD_TOOLS="$ANDROID_HOME/build-tools/$BUILD_TOOLS_VERSION"
ANDROID_JAR="$ANDROID_HOME/platforms/android-$ANDROID_API/android.jar"
AAPT="$BUILD_TOOLS/aapt"
D8="$BUILD_TOOLS/d8"
ZIPALIGN="$BUILD_TOOLS/zipalign"
APKSIGNER="$BUILD_TOOLS/apksigner"

for required in "$ANDROID_JAR" "$AAPT" "$D8" "$ZIPALIGN" "$APKSIGNER"; do
  test -e "$required" || { echo "Missing Android build tool: $required" >&2; exit 1; }
done

OUT="$ROOT/app/build"
CLASSES="$OUT/classes"
DEX="$OUT/dex"
mkdir -p "$OUT" "$CLASSES" "$DEX"
rm -rf "$CLASSES" "$DEX"
mkdir -p "$CLASSES" "$DEX"

find "$ROOT/app/src/main/java" -type f -name '*.java' -print0 | xargs -0 javac \
  -encoding UTF-8 -source 8 -target 8 \
  -bootclasspath "$ANDROID_JAR" \
  -d "$CLASSES"

mapfile -t CLASS_FILES < <(find "$CLASSES" -type f -name '*.class' -print | sort)
((${#CLASS_FILES[@]} > 0)) || { echo "No Java class files were produced" >&2; exit 1; }
"$D8" --release --min-api 23 --lib "$ANDROID_JAR" --output "$DEX" "${CLASS_FILES[@]}"
test -s "$DEX/classes.dex"

"$AAPT" package -f \
  -M "$ROOT/app/src/main/AndroidManifest.xml" \
  -A "$ROOT/app/src/main/assets" \
  -I "$ANDROID_JAR" \
  --min-sdk-version 23 \
  --target-sdk-version "$ANDROID_API" \
  --version-code 1 \
  --version-name 1.0 \
  -F "$OUT/senseis-unsigned.apk"
(
  cd "$DEX"
  "$AAPT" add "$OUT/senseis-unsigned.apk" classes.dex
)
"$ZIPALIGN" -f 4 "$OUT/senseis-unsigned.apk" "$OUT/senseis-aligned.apk"

KEYSTORE="$OUT/debug.keystore"
if [[ ! -f "$KEYSTORE" ]]; then
  keytool -genkeypair -v -keystore "$KEYSTORE" -storepass android \
    -alias androiddebugkey -keypass android -keyalg RSA -keysize 2048 \
    -validity 10000 -dname "CN=Senseis Offline,O=Zettelmuseum,C=DE" >/dev/null 2>&1
fi
"$APKSIGNER" sign --ks "$KEYSTORE" --ks-key-alias androiddebugkey \
  --ks-pass pass:android --key-pass pass:android \
  --out "$OUT/SenseisLibrary.apk" "$OUT/senseis-aligned.apk"
"$APKSIGNER" verify --verbose "$OUT/SenseisLibrary.apk"
printf 'APK: %s (%s bytes)\n' "$OUT/SenseisLibrary.apk" "$(stat -c %s "$OUT/SenseisLibrary.apk")"
