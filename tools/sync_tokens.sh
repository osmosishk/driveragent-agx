#!/bin/sh
# Copy the DriverAgent design tokens of the rk console (the standard) to dashboard/static/tokens.css.
# Usage: tools/sync_tokens.sh <driveragent tokens.css> <driveragent commit>
#   e.g. scp rk3588-da01:driveragent/rk/console/ui/src/styles/tokens.css /tmp/tokens.css
#        tools/sync_tokens.sh /tmp/tokens.css "$(ssh rk3588-da01 git -C driveragent rev-parse --short HEAD)"
# The first line of the copy names the source and the commit. Do not edit the copy: change the DA01 file.
set -eu
src=${1:?usage: tools/sync_tokens.sh <tokens.css> <commit>}
commit=${2:?usage: tools/sync_tokens.sh <tokens.css> <commit>}
dst="$(cd "$(dirname "$0")/.." && pwd)/dashboard/static/tokens.css"
tmp="$dst.new"
{ echo "/* source: driveragent rk/console/ui/src/styles/tokens.css, commit $commit. Do not edit this copy. */"
  cat "$src"; } > "$tmp"
mv "$tmp" "$dst"
echo "tokens.css: copied from $src (commit $commit)"
