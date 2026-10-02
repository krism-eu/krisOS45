#!/usr/bin/env bash
set -euo pipefail

source build_files/KrisOS-payload.lock
test "$KRISOS_COMMIT" = "2e07f3528b5aa3011f5826ce524029ec60e7f63e"
test "$KRISOS_SOURCE_REF" = "ghcr.io/krism-eu/krisos45:build-36909460134-1"
test "$KRISOS_TARGET_REF" = "ghcr.io/krism-eu/krisos45:m1"
test "$KRISOS_DIGEST" = "sha256:995957957b589019cdb536f1f2b67ef443e1023c5911277965d1fbba2c96345f"
test "$KRISOS_KRISCC" = "0.8.1-1.fc45.x86_64"

# Installer branch only: runtime source remains on main.
test ! -e Containerfile
test ! -e bin
test ! -e systemd
test ! -e scripts
test ! -e build_files/krisCC.lock
test ! -e .github/workflows/build-m1.yml
test ! -e .github/workflows/sync-kriscc.yml

# Graphical, interactive, non-destructive installer.
grep -Fq 'bootc-generic-iso' installer/build-installer.sh
grep -Fq -- '--bootc-installer-payload-ref "$source_ref"' installer/build-installer.sh
grep -Fq -- '--build-arg KRISOS_SOURCE_REF="$source_ref"' installer/build-installer.sh
grep -Fq -- '--build-arg KRISOS_TARGET_REF="$target_ref"' installer/build-installer.sh
grep -Fq 'ARG KRISOS_SOURCE_REF' installer/Containerfile
grep -Fq 'ARG KRISOS_TARGET_REF' installer/Containerfile
grep -Fq 'ARG ANACONDA_NEVR=45.27-1.fc45' installer/Containerfile
grep -Fq 'bootc --source-imgref=registry:$KRISOS_SOURCE_REF --target-imgref=$KRISOS_TARGET_REF' installer/Containerfile
if grep -Eq '^[[:space:]]*(clearpart|autopart|part|partition|logvol|volgroup|user|rootpw|reboot|shutdown)([[:space:]]|$)' installer/Containerfile; then
  echo "ERROR: installer container bakes unattended/destructive directives" >&2
  exit 1
fi
if grep -Eq 'inst\.(ks|cmdline|noninteractive)' installer/iso.yaml; then
  echo "ERROR: ISO kernel arguments enable unattended installation" >&2
  exit 1
fi

# SELinux live/target contract.
grep -Fq 'selinux=1 enforcing=0' installer/iso.yaml
grep -Fq "'selinux --enforcing'" installer/Containerfile

# Preserve the validated Anaconda chage workaround.
grep -Fq 'KrisOS workaround retained from the validated installer lineage' installer/Containerfile
grep -Fq '(["-P", root] if root != "/" else [])' installer/Containerfile
! grep -Fq 'util.execWithRedirect("chage", rootargs + ["-d", "", username])' installer/Containerfile

# Fedora 45 VT handoff.
grep -Fq 'rm -f /etc/systemd/system/autovt@.service' installer/Containerfile
grep -Fq 'systemctl enable anaconda-shell@.service' installer/Containerfile

# Keep only the proven bootc/composefs fstab post hook.
test -s installer/krisos-fstab-finalize.ks
test ! -e installer/krisos-home-labels-finalize.ks
grep -Fq 'COPY krisos-fstab-finalize.ks /usr/share/anaconda/krisos-fstab-finalize.ks' installer/Containerfile
! grep -Fq 'krisos-home-labels-finalize' installer/Containerfile
grep -Fq 'test "$(grep -c '"'"'^%post --nochroot --erroronfail$'"'"' /usr/share/anaconda/interactive-defaults.ks)" -eq 1' installer/Containerfile
grep -Fq 'chroot "$sysroot" /usr/bin/bootc internals fixup-etc-fstab' installer/krisos-fstab-finalize.ks

# Payload owns the internal /var/home model and SELinux policy.
git fetch --no-tags origin "$KRISOS_COMMIT"
main_container="$(mktemp)"
trap 'rm -f "$main_container"' EXIT
git show "$KRISOS_COMMIT:Containerfile" > "$main_container"
grep -Fq "sed -ri 's|^HOME=.*$|HOME=/var/home|' /etc/default/useradd" "$main_container"
grep -Fq 'semodule -B' "$main_container"
grep -Fq 'matchpathcon -n /var/home/kris' "$main_container"
grep -Fq 'matchpathcon -n /var/home/kris/.config' "$main_container"
grep -Fq 'matchpathcon -n /var/home/kris/.local/share' "$main_container"

# User-facing Anaconda mountpoint is /home, never /var/home.
grep -Fq 'dedicated ext4 partition -> `/home`' installer/README.md
grep -Fq 'Do not assign the separate home filesystem to `/var/home` directly.' installer/README.md
grep -Fq '/boot/efi' installer/README.md
grep -Fq 'administrator' installer/README.md
grep -Fq 'zram' installer/README.md

echo "K1 installer-only contract passed"
