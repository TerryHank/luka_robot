#!/usr/bin/env bash
set -euo pipefail

WS="${LUKA_WS:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
DATA="${LUKA_DATA:-$HOME/luka_data}"
LEGACY_DATA_COMMIT="${LUKA_LEGACY_DATA_COMMIT:-eb935d1ac7973dfabb7fe7c8771cc9fd04510b6d}"

mkdir -p "$WS/build" "$WS/install" "$WS/log"
mkdir -p "$DATA/maps" "$DATA/ml_models" "$DATA/recordings/bags"
mkdir -p "$DATA/recordings/stereo_calibration"

export_legacy_dir() {
  local git_path="$1"
  local destination="$2"
  local marker="$3"
  if find "$destination" -mindepth 1 -maxdepth 1 -print -quit | grep -q .; then
    echo "[workspace] keep existing $destination"
    return 0
  fi
  if ! git -C "$WS" cat-file -e "$LEGACY_DATA_COMMIT:$git_path" 2>/dev/null; then
    echo "[workspace] no legacy tree $git_path at $LEGACY_DATA_COMMIT"
    return 0
  fi
  local tmp
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN
  git -C "$WS" archive "$LEGACY_DATA_COMMIT" "$git_path" | tar -x -C "$tmp"
  mkdir -p "$destination"
  cp -a "$tmp/$git_path/." "$destination/"
  touch "$destination/$marker"
  echo "[workspace] restored $git_path -> $destination"
  rm -rf "$tmp"
  trap - RETURN
}

export_legacy_dir "map/maps" "$DATA/maps" ".migrated_from_git"
export_legacy_dir   "sensing/stereo_calibration/captures_20260924_163409"   "$DATA/recordings/stereo_calibration/captures_20260924_163409"   ".migrated_from_git"

mkdir -p "$DATA/ml_models/person_follow"

printf '%s\n' "LUKA_WS=$WS"
printf '%s\n' "LUKA_DATA=$DATA"
printf '%s\n' "maps=$DATA/maps"
printf '%s\n' "ml_models=$DATA/ml_models"
printf '%s\n' "recordings=$DATA/recordings"
printf '%s\n' "bags=$DATA/recordings/bags"

echo "[workspace] ready"
