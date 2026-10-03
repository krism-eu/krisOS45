#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

bash -n systemd/krisos-overlay.sh
bash -n tests/boot-check.sh
bash -n tests/release-check.sh
bash -n scripts/fetch-kriscc-component.sh
bash -n scripts/repair-home-labels.sh
bash -n scripts/check-initramfs-accounts.sh
bash -n scripts/resolve-base.sh
python3 -m py_compile bin/rk tools/source_snapshot.py

for test in \
    tests/test_rk.py \
    tests/test_rk_recovery.py \
    tests/test_release_state.py \
    tests/test_release_shell.py \
    tests/test_overlay_recovery.py \
    tests/test_overlay_identity.py; do
    python3 "$test"
done

# Runtime hardening invariants.
grep -Fxq 'f /var/lib/krisos/lock 0600 root root -' build_files/tmpfiles-krisos.conf
grep -Fq "stat.S_IMODE(info.st_mode) != 0o600" bin/rk
grep -Fq "'/usr/sbin': '/usr/bin'" bin/rk
grep -Fq "'/usr/share/dbus-1/system.d'" bin/rk
grep -Fq "'/usr/share/dbus-1/system-services'" bin/rk
grep -Fq "'/usr/share/factory'" bin/rk
grep -Fq "'/usr/lib/environment.d'" bin/rk
grep -Fq "'/usr/lib/binfmt.d'" bin/rk
grep -Fq "'/usr/etc'" bin/rk
grep -Fq '%{FILEUSERNAME}' bin/rk
grep -Fq '%{FILEGROUPNAME}' bin/rk
grep -Fq 'validate_payloads([pkg.get_package_path() for pkg in incoming])' bin/rk
grep -Fq '_reject_nested_manifest_symlinks(links)' bin/rk
grep -Fq '_is_identical_root_symlink(file, link_target)' bin/rk
grep -Fq 'mark_recovery_intent' systemd/krisos-overlay.sh
grep -Fq 'state_error' bin/rk
grep -Fq 'except Exception as error:' bin/rk
grep -Fq "return ' '.join(str(error).splitlines()).strip()" bin/rk
grep -Fq "print('rk:', type(error).__name__, message, file=sys.stderr)" bin/rk
grep -Fq 'assert_masked bootc-fetch-apply-updates.timer' Containerfile
grep -Fq 'assert_masked dnf-makecache.timer' Containerfile
grep -Fq 'assert_masked dnf5-makecache.timer' Containerfile
grep -Fq 'bootc auto-apply timer masked' tests/release-check.sh
grep -Fq 'Restart=on-failure' systemd/krisos-sync.service
grep -Fq 'RestartSec=30s' systemd/krisos-sync.service
grep -Fq 'OnUnitInactiveSec=10min' systemd/krisos-sync.timer
grep -Fq "sed -i 's/^#AutoEnable=true$/AutoEnable=false/' /etc/bluetooth/main.conf" Containerfile
grep -Fq 'rm -f /etc/xdg/autostart/backintime.desktop' Containerfile
grep -Fq 'Environment=LANG=it_IT.UTF-8' Containerfile
test ! -e systemd/krisos-bluetooth-firstboot.service
! grep -Fq 'systemctl enable krisos-bluetooth-firstboot.service' Containerfile
! grep -Fq 'systemctl enable NetworkManager-wait-online.service' Containerfile

# SELinux/home contract is intentionally the original KrisOS45 implementation.
# Reject the experimental candidate-only helpers/relocation strategies.
grep -Fq 'HOME=/var/home' Containerfile
grep -Fq 'semodule -B' Containerfile
grep -Fq 'matchpathcon -n /var/home/kris' Containerfile
test ! -e scripts/check-home-policy.sh
test ! -e scripts/relocate-selinux-store.sh
! grep -Fq 'store-root=/etc/selinux' Containerfile
! grep -Fq '/var/lib/selinux ->' Containerfile

# GitHub workflow security/serialization invariants live in test_release_shell.py.

echo 'PASS: KrisOS45 source hardening gate'
