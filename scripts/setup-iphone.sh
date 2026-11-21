#!/bin/bash
# Prepares this checkout for installing the app on your own iPhone with a free Apple Account.
#   scripts/setup-iphone.sh [TEAM_ID]
# Writes Config/Signing.local.xcconfig and GongbangAssistant/RoundupSecrets.plist; Git ignores both.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
signing="$root/Config/Signing.local.xcconfig"
secrets="$root/GongbangAssistant/RoundupSecrets.plist"
team="${1:-}"

if [[ -n "$team" && ! "$team" =~ ^[A-Z0-9]{10}$ ]]; then
  echo "Team ID는 영문 대문자와 숫자 10자리입니다: $team" >&2
  exit 1
fi

if [[ -f "$signing" ]]; then
  prefix="$(sed -n 's/^GB_BUNDLE_ID_PREFIX = //p' "$signing")"
  [[ -n "$team" ]] || team="$(sed -n 's/^DEVELOPMENT_TEAM = //p' "$signing")"
else
  # A bundle ID must be unique across every Apple account, so a random tail follows the user name.
  user="$(id -un | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9')"
  tail="$(LC_ALL=C tr -dc 'a-z0-9' < /dev/urandom | head -c 4 || true)"
  prefix="com.gongbang.${user:-member}${tail}"
fi

{
  echo "// Written by scripts/setup-iphone.sh. Keep this file out of Git."
  echo "GB_BUNDLE_ID_PREFIX = $prefix"
  [[ -z "$team" ]] || echo "DEVELOPMENT_TEAM = $team"
} > "$signing"

if [[ ! -f "$secrets" ]]; then
  read -r -p "README의 서버 연결 설정에 적힌 앱 키를 붙여 넣으세요: " key
  if [[ -z "$key" ]]; then
    echo "앱 키가 비어 있습니다." >&2
    exit 1
  fi
  sed "s|replace-with-the-server-ROUNDUP_API_KEY|$key|" "$root/Config/RoundupSecrets.example.plist" > "$secrets"
fi

echo "번들 ID: $prefix.GongbangAssistant"
if [[ -n "$team" ]]; then
  echo "Team: $team"
else
  echo "Team: 아직 없음. Xcode의 Signing & Capabilities에서 고르면 됩니다."
fi
echo "서버 설정: $secrets"
