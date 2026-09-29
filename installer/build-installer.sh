#!/usr/bin/bash
set -euo pipefail

if [[ $EUID -eq 0 ]]; then
    echo "Run this script as your normal user; it invokes sudo only where needed." >&2
    exit 1
fi

if ! command -v podman >/dev/null 2>&1; then
    echo "Missing required command: podman" >&2
    exit 1
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
output_dir="$repo_root/installer/output"
installer_image="${KRISOS_INSTALLER_IMAGE:-localhost/krisos-installer:k1.0}"
payload_ref="${KRISOS_PAYLOAD_REF:?Set KRISOS_PAYLOAD_REF to the validated KrisOS update-channel reference}"
payload_image_id="${KRISOS_PAYLOAD_IMAGE_ID:?Set KRISOS_PAYLOAD_IMAGE_ID to the verified local payload image ID}"
image_builder_image="${IMAGE_BUILDER_IMAGE:-ghcr.io/osbuild/image-builder@sha256:ee8729672bb2e901a9942d1e272b615cd695a58f5417c73d3d0b1b275d833fc5}"

if [[ "$payload_ref" == localhost/* || "$payload_ref" == *@sha256:* ]]; then
    echo "Complete ISO builds require a published update-channel ref, not localhost or a digest target." >&2
    exit 1
fi
if [[ "$image_builder_image" != *@sha256:* ]]; then
    echo "Complete ISO builds require an immutable Image Builder digest reference." >&2
    exit 1
fi

sudo rm -rf -- "$output_dir"
mkdir -p "$output_dir"

printf 'Using pre-verified KrisOS payload channel: %s\n' "$payload_ref"
if ! sudo podman image exists "$payload_ref"; then
    echo "Verified local payload image is missing: $payload_ref" >&2
    exit 1
fi
payload_actual_id="$(sudo podman image inspect "$payload_ref" --format '{{.Id}}')"
if [[ "$payload_actual_id" != "$payload_image_id" ]]; then
    printf 'Payload image ID mismatch: expected %s, got %s\n' "$payload_image_id" "$payload_actual_id" >&2
    exit 1
fi
printf 'Payload image ID: %s\n' "$payload_actual_id"

printf 'Building Fedora 45 Anaconda bootc installer runtime...\n'
build_ok=0
for attempt in 1 2 3; do
    if sudo podman build \
        --pull=always \
        --build-arg KRISOS_PAYLOAD_REF="$payload_ref" \
        -f "$repo_root/installer/Containerfile" \
        -t "$installer_image" \
        "$repo_root/installer"; then
        build_ok=1
        break
    fi
    printf 'Installer runtime build attempt %s/3 failed; retrying after a transient registry error...\n' "$attempt" >&2
    sleep 10
done
if [[ "$build_ok" -ne 1 ]]; then
    echo "Unable to build the Fedora 45 Anaconda installer runtime after 3 attempts." >&2
    exit 1
fi

printf 'Pulling pinned Image Builder...\n'
sudo podman pull "$image_builder_image"
builder_expected="${image_builder_image##*@}"
builder_actual="$(sudo podman image inspect "$image_builder_image" --format '{{.Digest}}')"
if [[ "$builder_actual" != "$builder_expected" ]]; then
    printf 'Image Builder digest mismatch: expected %s, got %s\n' "$builder_expected" "$builder_actual" >&2
    exit 1
fi
printf 'Image Builder digest: %s\n' "$builder_actual"

printf 'Building interactive bootc-generic-iso with embedded payload %s...\n' "$payload_ref"
sudo podman run \
    --rm \
    --privileged \
    --security-opt label=type:unconfined_t \
    -v /var/lib/containers/storage:/var/lib/containers/storage \
    -v "$output_dir:/output" \
    "$image_builder_image" \
    build \
    --with-manifest \
    --output-dir /output \
    --bootc-ref "$installer_image" \
    --bootc-installer-payload-ref "$payload_ref" \
    --bootc-default-fs ext4 \
    bootc-generic-iso

sudo chown -R "$(id -u):$(id -g)" "$output_dir"

raw_iso="$(find "$output_dir" -type f -name '*.iso' -print -quit)"
if [[ -z "$raw_iso" ]]; then
    echo "Image Builder completed without producing an ISO." >&2
    exit 1
fi

release_base="KrisOS-ISO-K1.0-x86_64"
iso="$output_dir/$release_base.iso"
if [[ "$raw_iso" != "$iso" ]]; then
    mv -f -- "$raw_iso" "$iso"
fi

raw_manifest="$(find "$output_dir" -type f -name '*.osbuild-manifest.json' -print -quit)"
if [[ -n "$raw_manifest" ]]; then
    manifest="$output_dir/$release_base.osbuild-manifest.json"
    if [[ "$raw_manifest" != "$manifest" ]]; then
        mv -f -- "$raw_manifest" "$manifest"
    fi
fi

(
    cd "$output_dir"
    find . -type f ! -name SHA256SUMS -print0 \
        | LC_ALL=C sort -z \
        | xargs -0 sha256sum > SHA256SUMS
)

printf '\nKrisOS K1.0 installer ISO:\n%s\n' "$iso"
printf '\nInstaller artifacts:\n'
find "$output_dir" -maxdepth 3 -type f -printf '%s %p\n' | sort -n
