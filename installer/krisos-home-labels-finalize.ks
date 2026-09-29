# KrisOS installer-only SELinux home finalization.
# The final main payload owns policy/defaults and the conservative repair helper.
# This hook only acts if the just-created fresh-install home actually differs
# from that policy; already-correct installs are left untouched.
%post --nochroot --erroronfail
set -eu

sysroot=/mnt/sysroot
helper=/usr/libexec/krisos/repair-home-labels

[ -d "$sysroot" ] || {
    echo "KrisOS target system root is missing: $sysroot" >&2
    exit 1
}
[ -x "$sysroot$helper" ] || {
    echo "KrisOS home-label helper missing from installed payload" >&2
    exit 1
}
grep -Fxq 'HOME=/var/home' "$sysroot/etc/default/useradd"
grep -Eq '^SELINUX=enforcing$' "$sysroot/etc/selinux/config"

for home in "$sysroot"/var/home/*; do
    [ -d "$home" ] || continue
    [ ! -L "$home" ] || continue
    user=${home##*/}

    # Only real local users accepted by the target helper can be touched.
    chroot "$sysroot" getent passwd "$user" >/dev/null 2>&1 || continue

    preview="$(chroot "$sysroot" "$helper" "$user")"
    if [ -n "$preview" ]; then
        chroot "$sysroot" "$helper" --apply "$user"
    fi

    # A fresh install must leave the four selected paths aligned to target policy.
    # The helper is intentionally non-recursive and skips symlinks.
    test -z "$(chroot "$sysroot" "$helper" "$user")"
done
%end
