#!/bin/sh
# Copy nesp32's link library for the console into vendor/nesp32.
#
#   tools/update_nesp32.sh /path/to/nesp32
#
# nesp.inc is copied as it is. nesp_proto.inc and link.inc are made by
# nesp32's own tools, the second with --timeout: the ROM keeps its NMI off
# but for a vblank's writes, so the receiver gives up by counting. VERSION
# names the nesp32 commit they came from. Run it when nesp32's link
# protocol changes, and commit what it writes.
set -eu
nesp32=${1:?usage: $0 /path/to/nesp32}
here=$(cd "$(dirname "$0")/.." && pwd)
out=$here/vendor/nesp32
build=$(mktemp -d)
trap 'rm -rf "$build"' EXIT

python3 "$nesp32/tools/gen_proto.py" "$build" >/dev/null
python3 "$nesp32/nes/lib/gen_link.py" "$build" "$out/link.inc" --timeout
cp "$nesp32/nes/lib/nesp.inc" "$build/nesp_proto.inc" "$out/"
{
    # dirty only if what the files are made from has changed
    dirty=
    git -C "$nesp32" diff --quiet HEAD -- nes/lib proto tools/gen_proto.py || dirty=-dirty
    echo "nesp32 $(git -C "$nesp32" describe --tags --always)$dirty"
    echo "$(git -C "$nesp32" rev-parse HEAD)"
    echo "https://github.com/Armitage64/nesp32"
} > "$out/VERSION"
cat "$out/VERSION"
