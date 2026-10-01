#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
requested="${KRISOS_BASE_IMAGE:-$(sed -n 's/^ARG BASE_IMAGE=//p' Containerfile | head -n1)}"
[[ -n "$requested" ]] || { echo "Cannot resolve BASE_IMAGE from Containerfile" >&2; exit 1; }

if [[ "$requested" =~ @sha256:[0-9a-f]{64}$ ]]; then
    resolved="$requested"
else
    command -v skopeo >/dev/null 2>&1 || { echo "skopeo is required to resolve the Fedora base digest" >&2; exit 1; }
    digest="$(skopeo inspect --format '{{.Digest}}' "docker://$requested")"
    [[ "$digest" =~ ^sha256:[0-9a-f]{64}$ ]] || { echo "Invalid base digest: $digest" >&2; exit 1; }
    repo="${requested%:*}"
    resolved="${repo}@${digest}"
fi

printf 'requested=%s\nresolved=%s\n' "$requested" "$resolved" > fedora45-base.txt
printf '%s\n' "$resolved"
