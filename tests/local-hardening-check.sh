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
