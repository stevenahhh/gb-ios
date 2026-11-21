#!/bin/bash
# Builds, signs, installs, and launches the app on a USB-connected iPhone.
#   scripts/install-iphone.sh [DEVICE_UDID]
# Needs an Apple Account added in Xcode > Settings > Accounts and scripts/setup-iphone.sh run once.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
signing="$root/Config/Signing.local.xcconfig"
derived="$root/build/device"
export DEVELOPER_DIR="${DEVELOPER_DIR:-/Applications/Xcode.app/Contents/Developer}"

if [[ ! -f "$signing" || ! -f "$root/GongbangAssistant/RoundupSecrets.plist" ]]; then
  echo "먼저 scripts/setup-iphone.sh를 실행하세요." >&2
  exit 1
fi

team="$(sed -n 's/^DEVELOPMENT_TEAM = //p' "$signing")"
if [[ -z "$team" ]]; then
  team="$(defaults read com.apple.dt.Xcode IDEProvisioningTeamByIdentifier 2>/dev/null \
    | sed -n 's/^ *teamID = \([A-Z0-9]\{10\}\);/\1/p' | head -1 || true)"
fi
if [[ -z "$team" ]]; then
  echo "Team을 찾지 못했습니다. Xcode > Settings > Accounts에 Apple Account를 추가하거나 scripts/setup-iphone.sh TEAM_ID를 실행하세요." >&2
  exit 1
fi

udid="${1:-}"
if [[ -z "$udid" ]]; then
  devices="$(mktemp)"
  trap 'rm -f "$devices"' EXIT
  xcrun devicectl list devices --json-output "$devices" >/dev/null
  udid="$(/usr/bin/python3 -c '
import json, sys
for d in json.load(open(sys.argv[1]))["result"]["devices"]:
    hw, conn = d.get("hardwareProperties", {}), d.get("connectionProperties", {})
    if hw.get("platform") == "iOS" and hw.get("reality") == "physical" and conn.get("tunnelState") == "connected":
        print(hw["udid"]); break
' "$devices")"
fi
if [[ -z "$udid" ]]; then
  echo "연결된 iPhone이 없습니다. 케이블로 연결하고 iPhone에서 신뢰를 누른 뒤 다시 실행하세요." >&2
  exit 1
fi

echo "Team ${team}, 기기 ${udid}에 빌드합니다."
xcodebuild -project "$root/GongbangAssistant.xcodeproj" -scheme GongbangAssistant -configuration Debug \
  -destination "id=$udid" -derivedDataPath "$derived" \
  -allowProvisioningUpdates -allowProvisioningDeviceRegistration \
  DEVELOPMENT_TEAM="$team" build -quiet

app="$derived/Build/Products/Debug-iphoneos/GongbangAssistant.app"
bundle_id="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$app/Info.plist")"
xcrun devicectl device install app --device "$udid" "$app"
if ! xcrun devicectl device process launch --device "$udid" "$bundle_id"; then
  echo "설치는 끝났습니다. 실행이 막혔다면 iPhone의 설정 > 일반 > VPN 및 기기 관리에서 개발자를 신뢰한 뒤 앱 아이콘을 누르세요." >&2
fi
