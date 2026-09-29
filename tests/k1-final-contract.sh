#!/usr/bin/env bash
set -euo pipefail

# This branch owns only the installer. The installed OS is the exact signed main payload.
source build_files/KrisOS-payload.lock
test "$KRISOS_COMMIT" = "544535a6a21a1cb9f446c2d5b5497c6ab1e57eb2"
test "$KRISOS_TARGET_REF" = "ghcr.io/krism-eu/krisos:544535a6a21a1cb9f446c2d5b5497c6ab1e57eb2"
test "$KRISOS_DIGEST" = "sha256:7a30064f3d979e9ff56ff80cf845b4fbdc10f5543988df9b73f967a348eee40e"
test "$KRISOS_KRISCC" = "0.7.9-1.fc44.x86_64"

# Runtime sources and runtime workflows belong to main and must not drift here.
test ! -e Containerfile
test ! -e bin
test ! -e systemd
test ! -e scripts
test ! -e build_files/krisCC.lock
test ! -e build_files/krisCC-candidate.lock
test ! -e .github/workflows/build-m1.yml
test ! -e .github/workflows/sync-kriscc.yml
test ! -e .github/workflows/build-installer.yml

# Installer must remain graphical, interactive and non-destructive.
grep -Fq 'bootc-generic-iso' installer/build-installer.sh
grep -Fq -- '--bootc-installer-payload-ref "$payload_ref"' installer/build-installer.sh
grep -Fq -- '--build-arg KRISOS_PAYLOAD_REF="$payload_ref"' installer/build-installer.sh
grep -Fq 'ARG KRISOS_PAYLOAD_REF' installer/Containerfile
grep -Fq 'ARG ANACONDA_NEVR=45.25-1.fc45' installer/Containerfile
grep -Fq 'anaconda-${ANACONDA_NEVR}' installer/Containerfile
grep -Fq 'anaconda-install-img-deps-${ANACONDA_NEVR}' installer/Containerfile
grep -Fq 'anaconda-dracut-${ANACONDA_NEVR}' installer/Containerfile
grep -Fq "grep -Fxq 'Alias=autovt@.service'" installer/Containerfile
grep -Fq "grep -Fxq 'ReserveVT=2'" installer/Containerfile
grep -Fq "grep -Fxq 'StandardInput=null'" installer/Containerfile
grep -Fq 'systemctl enable anaconda-shell@.service' installer/Containerfile
test ! -e installer/anaconda-shell.conf
! grep -Fq 'ln -s /usr/lib/systemd/system/anaconda-shell@.service' installer/Containerfile
grep -Fq "'graphical'" installer/Containerfile
grep -Fq 'bootc --source-imgref=registry:$KRISOS_PAYLOAD_REF --target-imgref=$KRISOS_PAYLOAD_REF' installer/Containerfile
if grep -Eq '^[[:space:]]*(clearpart|autopart|part|partition|logvol|volgroup|user|rootpw|reboot|shutdown)([[:space:]]|$)' installer/Containerfile; then
  echo "ERROR: installer container bakes unattended/destructive directives" >&2
  exit 1
fi
if grep -Eq 'inst\.(ks|cmdline|noninteractive)' installer/iso.yaml; then
  echo "ERROR: ISO boot arguments enable unattended installation" >&2
  exit 1
fi

# SELinux installer behavior is intentionally frozen after host acceptance.
grep -Fq 'selinux=1 enforcing=0' installer/iso.yaml
if grep -Eq '(^|[[:space:]])(selinux=0|enforcing=1)([[:space:]]|$)' installer/iso.yaml; then
  echo "ERROR: live installer SELinux contract changed" >&2
  exit 1
fi
grep -Fq "'selinux --enforcing'" installer/Containerfile

# fstab finalization is installer-only and must be narrowly idempotent.
test -s installer/krisos-fstab-finalize.ks
grep -Fq 'COPY krisos-fstab-finalize.ks /usr/share/anaconda/krisos-fstab-finalize.ks' installer/Containerfile
grep -Fq '/usr/share/anaconda/krisos-fstab-finalize.ks \' installer/Containerfile
grep -Fq '>> /usr/share/anaconda/interactive-defaults.ks' installer/Containerfile
grep -Fq '%post --nochroot --erroronfail' installer/krisos-fstab-finalize.ks
grep -Fq 'sysroot=/mnt/sysroot' installer/krisos-fstab-finalize.ks
grep -Fq 'fstab="$sysroot/etc/fstab"' installer/krisos-fstab-finalize.ks
! grep -Fq '/mnt/sysimage' installer/krisos-fstab-finalize.ks
grep -Fq "anaconda_stamp='Created by anaconda'" installer/krisos-fstab-finalize.ks
grep -Fq "bootc_stamp='Updated by bootc-fstab-edit.service'" installer/krisos-fstab-finalize.ks
grep -Fq 'opts[i] == "ro"' installer/krisos-fstab-finalize.ks
grep -Fq 'root_count="$(awk' installer/krisos-fstab-finalize.ks
grep -Fq 'chroot "$sysroot" /usr/bin/bootc internals fixup-etc-fstab' installer/krisos-fstab-finalize.ks
grep -Fq 'root_is_ro' installer/krisos-fstab-finalize.ks
if grep -Eq '(^|[[:space:]])(systemctl|daemon-reload)([[:space:]]|$)' installer/krisos-fstab-finalize.ks; then
  echo "ERROR: fstab finalizer must not add a runtime daemon-reload workaround" >&2
  exit 1
fi

# Fresh-home SELinux finalization must reuse main's validated helper and only
# apply when its non-destructive preview reports a real mismatch.
test -s installer/krisos-home-labels-finalize.ks
grep -Fq 'COPY krisos-home-labels-finalize.ks /usr/share/anaconda/krisos-home-labels-finalize.ks' installer/Containerfile
grep -Fq '/usr/share/anaconda/krisos-home-labels-finalize.ks \' installer/Containerfile
grep -Fq "grep -c '^%post --nochroot --erroronfail$'" installer/Containerfile
grep -Fq "grep -c '^%end$'" installer/Containerfile
grep -Fq '%post --nochroot --erroronfail' installer/krisos-home-labels-finalize.ks
grep -Fq 'sysroot=/mnt/sysroot' installer/krisos-home-labels-finalize.ks
! grep -Fq '/mnt/sysimage' installer/krisos-home-labels-finalize.ks
grep -Fq 'helper=/usr/libexec/krisos/repair-home-labels' installer/krisos-home-labels-finalize.ks
grep -Fq "grep -Fxq 'HOME=/var/home'" installer/krisos-home-labels-finalize.ks
grep -Fq "grep -Eq '^SELINUX=enforcing$'" installer/krisos-home-labels-finalize.ks
grep -Fq 'preview="$(chroot "$sysroot" "$helper" "$user")"' installer/krisos-home-labels-finalize.ks
grep -Fq 'chroot "$sysroot" "$helper" --apply "$user"' installer/krisos-home-labels-finalize.ks
grep -Fq 'test -z "$(chroot "$sysroot" "$helper" "$user")"' installer/krisos-home-labels-finalize.ks
if grep -Eq 'restorecon[[:space:]].*(-R|-F)|(^|[[:space:]])(chcon|semanage|semodule)([[:space:]]|$)' installer/krisos-home-labels-finalize.ks; then
  echo "ERROR: home-label finalizer must not broaden SELinux policy or relabel recursively" >&2
  exit 1
fi

# Pin the integration contract to the exact main source behind the payload:
# main owns /var/home defaults/policy and the conservative four-path helper.
git fetch --no-tags origin "$KRISOS_COMMIT"
main_container="$(mktemp)"
main_helper="$(mktemp)"
trap 'rm -f "$main_container" "$main_helper"' EXIT
git show "$KRISOS_COMMIT:Containerfile" > "$main_container"
git show "$KRISOS_COMMIT:scripts/repair-home-labels.sh" > "$main_helper"
grep -Fq "sed -ri 's|^HOME=.*$|HOME=/var/home|' /etc/default/useradd" "$main_container"
grep -Fq 'semodule -B' "$main_container"
grep -Fq 'matchpathcon -n /var/home/kris' "$main_container"
grep -Fq 'matchpathcon -n /var/home/kris/.config' "$main_container"
grep -Fq 'matchpathcon -n /var/home/kris/.local/share' "$main_container"
grep -Fq "grep -Eq '^SELINUX=enforcing$' /etc/selinux/config" "$main_container"
grep -Fq 'COPY scripts/repair-home-labels.sh /usr/libexec/krisos/repair-home-labels' "$main_container"
grep -Fq '"$resolved" "$resolved/.config" "$resolved/.local" "$resolved/.local/share"' "$main_helper"
if grep -Eq 'restorecon[[:space:]].*(-R|-F)' "$main_helper"; then
  echo "ERROR: main home-label helper became recursive or force-relabeling" >&2
  exit 1
fi

# Preserve the approved interactive partitioning contract documented for K1.
grep -Fq '/boot/efi' installer/README.md
grep -Fq '/var/home' installer/README.md
grep -Fq 'administrator' installer/README.md
grep -Fq 'No swap partition' installer/README.md

echo "K1 installer-only contract passed"
