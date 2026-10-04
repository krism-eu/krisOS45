#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

# Fast syntax/import gate before the behavioral suites.
bash -n tests/source-hardening-check.sh
bash -n tests/local-hardening-check.sh
bash -n systemd/krisos-overlay.sh
bash -n tests/boot-check.sh
bash -n tests/release-check.sh
bash -n scripts/fetch-kriscc-component.sh
bash -n scripts/repair-home-labels.sh
bash -n scripts/check-initramfs-accounts.sh
bash -n scripts/resolve-base.sh
python3 -m py_compile bin/rk tools/source_snapshot.py

# Behavioral/unit contracts. Image/runtime invariants are asserted by the
# Containerfile, local-hardening-check.sh and release-check.sh rather than by
# grepping their implementation text here.
for test in \
    tests/test_rk.py \
    tests/test_rk_recovery.py \
    tests/test_release_state.py \
    tests/test_release_shell.py \
    tests/test_overlay_recovery.py \
    tests/test_overlay_identity.py; do
    python3 "$test"
done

# Source-only architecture exclusions that deliberately have no runtime
# behavior to test: retired helpers/strategies must not return.
test ! -e systemd/krisos-bluetooth-firstboot.service
test ! -e scripts/check-home-policy.sh
test ! -e scripts/relocate-selinux-store.sh
! grep -Fq 'store-root=/etc/selinux' Containerfile
! grep -Fq '/var/lib/selinux ->' Containerfile

echo 'PASS: KrisOS45 source hardening gate'
