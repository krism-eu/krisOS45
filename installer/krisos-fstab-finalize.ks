# KrisOS installer-only finalization for bootc-managed Anaconda installs.
# Operate on Anaconda's installed system root, never the physical sysimage view.
%post --nochroot --erroronfail
set -eu

sysroot=/mnt/sysroot
fstab="$sysroot/etc/fstab"
anaconda_stamp='Created by anaconda'
bootc_stamp='Updated by bootc-fstab-edit.service'

[ -d "$sysroot" ] || { echo "KrisOS target system root is missing: $sysroot" >&2; exit 1; }
[ -f "$fstab" ] || { echo "KrisOS target fstab is missing" >&2; exit 1; }
grep -Fq "$anaconda_stamp" "$fstab" || {
    echo "KrisOS target fstab was not created by Anaconda" >&2
    exit 1
}

root_count="$(awk '
  /^[[:space:]]*#/ || NF < 4 { next }
  $2 == "/" { count++ }
  END { print count + 0 }
' "$fstab")"
[ "$root_count" -eq 1 ] || {
    echo "KrisOS expected exactly one active root entry in fstab, found $root_count" >&2
    exit 1
}

root_is_ro() {
    awk '
      /^[[:space:]]*#/ || NF < 4 { next }
      $2 == "/" {
        n = split($4, opts, ",")
        for (i = 1; i <= n; i++)
          if (opts[i] == "ro") found = 1
      }
      END { exit found ? 0 : 1 }
    ' "$fstab"
}

if grep -Fq "$bootc_stamp" "$fstab"; then
    root_is_ro || {
        echo "bootc fstab marker exists but root is not read-only" >&2
        exit 1
    }
    exit 0
fi

if root_is_ro; then
    # bootc itself does not add the marker when no edit is needed. Add only its
    # canonical stamp so the generator will not schedule a no-op editor later.
    printf '\n# %s\n' "$bootc_stamp" >> "$fstab"
else
    [ -x "$sysroot/usr/bin/bootc" ] || {
        echo "bootc is missing from the installed target" >&2
        exit 1
    }
    chroot "$sysroot" /usr/bin/bootc internals fixup-etc-fstab
fi

grep -Fq "$bootc_stamp" "$fstab"
root_is_ro
%end
