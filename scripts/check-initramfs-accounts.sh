#!/usr/bin/env bash
# Run during the image build, before publishing an initramfs with missing identities.
set -euo pipefail
image="$(realpath -- "${1:?initramfs path required}")"
tmp="$(mktemp -d)"
trap 'rm -rf -- "$tmp"' EXIT
(cd "$tmp" && lsinitrd --unpack "$image")
for group in root audio disk utmp clock tty kmem input video render tss; do
    chroot "$tmp" /usr/bin/getent group "$group" >/dev/null || {
        echo "initramfs cannot resolve group: $group" >&2
        exit 1
    }
done
chroot "$tmp" /usr/bin/getent passwd tss >/dev/null
