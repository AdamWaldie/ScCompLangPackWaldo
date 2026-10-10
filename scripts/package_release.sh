#!/usr/bin/env bash
# Packages dist/<CHANNEL> into release assets: versioned files in <out>/ and, when <latest> is given,
# fixed-name copies there for the floating "latest" release (installers and auto-updaters).
# Usage: scripts/package_release.sh <CHANNEL> <out> [latest]
set -euo pipefail
ch=$1 out=$2 latest=${3:-}
root=$(cd "$(dirname "$0")/.." && pwd)
version=$(python "$root/scripts/version_info.py" --channel "$ch" version)
rm -rf "$out" && mkdir -p "$out"
out=$(cd "$out" && pwd)
(cd "$root/dist/$ch/remix"   && zip -qrX "$out/ScCompLangPackWaldo-$version-$ch.zip" data user.cfg)
(cd "$root/dist/$ch/classic" && zip -qrX "$out/ScCompLangPackWaldo-Classic-$version-$ch.zip" data user.cfg)
cp "$root/dist/$ch/remix/changes.ini"   "$out/ScCompLangPackWaldo-$version-$ch-changes.ini"
cp "$root/dist/$ch/classic/changes.ini" "$out/ScCompLangPackWaldo-Classic-$version-$ch-changes.ini"
if [ -n "$latest" ]; then
  rm -rf "$latest" && mkdir -p "$latest"
  for f in "$out"/*; do
    cp "$f" "$latest/$(basename "$f" | sed "s/-$version-$ch/-$ch/")"
  done
fi
