#!/usr/bin/env bash
# This is the same build/integration gate used by GitHub validation and candidate publishing.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
tag="${KRISOS_LOCAL_TAG:-localhost/krisos45:hardening-final}"
source_revision="${KRISOS_SOURCE_REVISION:-local}"

say() { printf '\n==> %s\n' "$*"; }
fail() { printf '\nFAIL: %s\n' "$*" >&2; exit 1; }

command -v podman >/dev/null 2>&1 || fail "podman non trovato"
command -v skopeo >/dev/null 2>&1 || fail "skopeo non trovato"

say 'Source/unit/invariant gate'
./tests/source-hardening-check.sh

if [[ ! -s build_files/krisCC/krisCC.rpm ]]; then
    say 'Recupero krisCC RPM fissato dal lock'
    ./scripts/fetch-kriscc-component.sh
fi

say 'Risoluzione digest esatto della base Fedora 45'
resolved_base="$(./scripts/resolve-base.sh)"
[[ "$resolved_base" =~ @sha256:[0-9a-f]{64}$ ]] || fail "base non risolta a digest: $resolved_base"
echo "Base: $resolved_base"

say 'Build Podman sul digest risolto'
podman build --pull=always \
    --build-arg "BASE_IMAGE=$resolved_base" \
    --label 'org.opencontainers.image.source=https://github.com/krism-eu/krisOS45' \
    --label "org.opencontainers.image.revision=$source_revision" \
    -t "$tag" . 2>&1 | tee build.log

say 'Inspect immagine costruita'
test "$(podman inspect "$tag" --format '{{ index .Config.Labels "containers.bootc" }}')" = '1'
test "$(podman inspect "$tag" --format '{{ index .Config.Labels "ostree.bootable" }}')" = '1'
test "$(podman inspect "$tag" --format '{{ index .Config.Labels "org.opencontainers.image.version" }}')" = '0.1.0-m1'
test "$(podman inspect "$tag" --format '{{ index .Config.Labels "org.opencontainers.image.source" }}')" = 'https://github.com/krism-eu/krisOS45'
test "$(podman inspect "$tag" --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}')" = "$source_revision"

say 'Desktop startup policy invariants'
podman run --rm --entrypoint /usr/bin/bash "$tag" -lc '
  set -euo pipefail
  grep -Fxq "AutoEnable=false" /etc/bluetooth/main.conf
  test ! -e /usr/lib/systemd/system/krisos-bluetooth-firstboot.service
  systemctl is-enabled NetworkManager-wait-online.service 2>&1 | grep -qx disabled
  test ! -e /etc/xdg/autostart/backintime.desktop
  test -f /usr/lib/systemd/system/plasmalogin.service.d/10-krisos-locale.conf
  grep -Fxq "Environment=LANG=it_IT.UTF-8" /usr/lib/systemd/system/plasmalogin.service.d/10-krisos-locale.conf
  test -f /etc/tmpfiles.d/root.conf
  test ! -s /etc/tmpfiles.d/root.conf
  rpm -q kf6-sonnet-hunspell hunspell-it >/dev/null
'

say 'repair-home-labels functional contract'
podman run --rm --security-opt label=disable --entrypoint /usr/bin/bash "$tag" -lc '
  set -euo pipefail
  printf "krisrepair:x:42420:42420::/var/home/krisrepair:/usr/sbin/nologin\n" >> /etc/passwd
  printf "krisrepairbad:x:42421:42421::/var/home/nested/krisrepairbad:/usr/sbin/nologin\n" >> /etc/passwd
  mkdir -p /var/home/krisrepair/.config /var/home/krisrepair/.local/share /var/home/nested/krisrepairbad
  mkdir -p /tmp/repair-home-labels-bin
  cat > /tmp/repair-home-labels-bin/restorecon <<"EOF"
#!/bin/sh
printf "%s\n" "$*" >> /tmp/repair-home-labels.calls
EOF
  chmod 0755 /tmp/repair-home-labels-bin/restorecon
  PATH=/tmp/repair-home-labels-bin:$PATH /usr/libexec/krisos/repair-home-labels krisrepair
  test "$(wc -l < /tmp/repair-home-labels.calls)" -eq 4
  grep -Fxq -- "-v -n -- /var/home/krisrepair" /tmp/repair-home-labels.calls
  grep -Fxq -- "-v -n -- /var/home/krisrepair/.config" /tmp/repair-home-labels.calls
  grep -Fxq -- "-v -n -- /var/home/krisrepair/.local" /tmp/repair-home-labels.calls
  grep -Fxq -- "-v -n -- /var/home/krisrepair/.local/share" /tmp/repair-home-labels.calls
  : > /tmp/repair-home-labels.calls
  PATH=/tmp/repair-home-labels-bin:$PATH /usr/libexec/krisos/repair-home-labels --apply krisrepair
  test "$(wc -l < /tmp/repair-home-labels.calls)" -eq 4
  grep -Fxq -- "-v -- /var/home/krisrepair" /tmp/repair-home-labels.calls
  ! grep -Fq -- "-n" /tmp/repair-home-labels.calls
  if PATH=/tmp/repair-home-labels-bin:$PATH /usr/libexec/krisos/repair-home-labels krisrepairbad >/tmp/repair-home-labels.bad 2>&1; then
    echo "nested home unexpectedly accepted" >&2
    exit 1
  fi
  grep -Fq "Home must resolve to a direct child of /var/home." /tmp/repair-home-labels.bad
'

say 'Regression suite dentro la stessa immagine'
podman run --rm --security-opt label=disable \
    -v "$root:/src:ro" -w /src --entrypoint /usr/bin/bash "$tag" -lc '
      set -euo pipefail
      python3 tests/test_rk.py
      python3 tests/test_rk_recovery.py
      python3 tests/test_release_state.py
      python3 tests/test_release_shell.py
      python3 tests/test_overlay_recovery.py
      python3 tests/test_overlay_identity.py
    '

say 'Transazione DNF/RPM reale in container usa-e-getta'
podman run --rm --security-opt label=disable \
    -e RK_DISPOSABLE_CONTAINER_TEST=1 \
    -v "$root/tests/test_rk_container.py:/tmp/test-rk.py:ro" \
    --entrypoint python3 "$tag" /tmp/test-rk.py 2>&1 | tee rk-integration.log

printf '\nPASS: KRISOS45 HARDENING FINAL — source + build + container integration\n'
printf 'Image: %s\n' "$tag"
printf 'Resolved base recorded in: %s/fedora45-base.txt\n' "$root"
