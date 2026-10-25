#!/usr/bin/env bash
# Build WhatsApp's official sample sticker app (https://github.com/WhatsApp/stickers) with the packs
# written by ios_stickers_to_android.py, and print the command to install it.
#
# Usage: build_sticker_app.sh ASSETS_DIR [APPLICATION_ID]
#   ASSETS_DIR       output of ios_stickers_to_android.py (contains contents.json)
#   APPLICATION_ID   unique id of your app, e.g. com.yourname.iphonestickers
#                    (WhatsApp's sample refuses ids starting with com.example or com.whatsapp)
#
# Needs git, a JDK (17 or newer) and the Android SDK (platform 34 and build-tools).
# ANDROID_HOME is used if set, otherwise the Homebrew android-commandlinetools location.
set -euo pipefail

ASSETS=$(cd "$1" && pwd)
APP_ID=${2:-com.local.iphonestickers}
SAMPLE_COMMIT=06144a1f6077bbb346e1230032fc4e0bce996d03  # tested version of WhatsApp/stickers
SDK=${ANDROID_HOME:-$(brew --prefix 2>/dev/null)/share/android-commandlinetools}
WORK=$(mktemp -d -t whatsapp-stickers)

[ -f "$ASSETS/contents.json" ] || { echo "No contents.json in $ASSETS" >&2; exit 1; }
[ -d "$SDK/platforms/android-34" ] || { echo "Android platform 34 not found in $SDK (sdkmanager 'platforms;android-34')" >&2; exit 1; }

git clone -q https://github.com/WhatsApp/stickers.git "$WORK/stickers"
git -C "$WORK/stickers" checkout -q "$SAMPLE_COMMIT"
cd "$WORK/stickers/Android"

# The sample targets old tools: build with a current SDK and a Gradle that runs on recent JDKs.
sed -i.bak -e "s/compileSdkVersion 30/compileSdkVersion 34/" \
           -e "s/minSdkVersion 15/minSdkVersion 21/" \
           -e "s/applicationId \"com.example.samplestickerapp\"/applicationId \"$APP_ID\"/" app/build.gradle
sed -i.bak "s/gradle-8.7-bin.zip/gradle-8.10.2-bin.zip/" gradle/wrapper/gradle-wrapper.properties
sed -i.bak "s|<string name=\"app_name\">.*</string>|<string name=\"app_name\">iPhone Stickers</string>|" \
    app/src/main/res/values/strings.xml
find . -name "*.bak" -delete  # sed -i backups break the Android resource merge
echo "sdk.dir=$SDK" > local.properties

rm -rf app/src/main/assets
cp -R "$ASSETS" app/src/main/assets
./gradlew --no-daemon -q assembleDebug

APK="$WORK/stickers/Android/app/build/outputs/apk/debug/app-debug.apk"
echo "Built: $APK"
echo "Install it on the phone (owner profile) with:"
echo "  adb install --user 0 \"$APK\""
echo "Then open \"iPhone Stickers\" and tap + on every pack, then \"Add to WhatsApp\"."
echo "Keep the app installed: WhatsApp loads the stickers from it."
