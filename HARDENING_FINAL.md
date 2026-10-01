# KrisOS45 hardening — consolidated candidate

Base: original KrisOS45 snapshot at commit `613c430b2c7894778d76da085ddb0d206e201ee8`.

This candidate deliberately preserves the original SELinux/home model. The experimental SELinux/store/order changes introduced in failed intermediate candidates are not included.

## Included hardening

- `rk` exact root:root `0600` transaction lock, protected RPM-owned namespaces, transaction-wide symlink validation with nested incoming symlinks rejected, exact root-owned pre-existing symlink reuse, special/setuid/capability rejection, strict existing-directory metadata validation, a narrowly allowlisted Fedora UsrMerge `/usr/sbin -> /usr/bin` directory alias, fail-safe `status --json` state reporting, and a traceback-free CLI boundary compatible with the modern libdnf5 SWIG exception hierarchy.
- Overlay recovery durability: `needs-sync` is persisted before destructive recovery and is armed on overlay relabel/mount failure so the next boot retries a rebuild.
- Exact disabled/masked update-timer checks at image build and release validation time.
- Real release-VM `rk add` / reboot / switch / resync / `rk rm` / reboot persistence checks.
- Shared `tests/local-hardening-check.sh` used by both local validation and GitHub CI. It resolves the Fedora base to an immutable digest before building; the krisCC adoption candidate build follows the same digest-pinning rule.
- CI privilege separation:
  - PR/manual validation is read-only.
  - main/scheduled publication may publish and keylessly sign an immutable candidate digest, but cannot advance `m1`.
  - `m1` promotion is a separate protected-environment workflow and requires Cosign identity verification plus the real VM gate before the digest is copied to `m1`.

## Verification in this package

Run the source/regression gate:

```bash
./tests/source-hardening-check.sh
```

Run the complete local gate (requires Podman, Skopeo, network access, and the locked krisCC release asset):

```bash
./tests/local-hardening-check.sh
```

The local gate and GitHub build workflows call the same build/test path rather than maintaining separate build recipes.

## Stable-promotion environment

The `stable-promotion` GitHub environment must provide:

- `KRISOS_E2E_SSH_KEY`
- `KRISOS_E2E_KNOWN_HOSTS`
- `KRISOS_E2E_TARGET`
- optional `KRISOS_EXPECT_ADMIN_USER`

Environment protection/review should be configured in GitHub so stable promotion is explicitly authorized.

## krisCC release access prerequisite

The current integration deliberately fetches `krism-eu/krisCC` release assets
from a public repository. `github.token` / `GITHUB_TOKEN` belongs to the
KrisOS45 workflow repository and must not be treated as a credential for a
private cross-repository krisCC release. If krisCC becomes private, the fetch
path must be redesigned around an explicitly authorized least-privilege GitHub
App/token; fork PR validation cannot depend on a repository secret. The SHA-256
lock remains the artifact-integrity check regardless of repository visibility.

## Network-online policy for rk recovery

`krisos-sync.service` orders after and wants `network-online.target`, but the
image intentionally does not enable `NetworkManager-wait-online.service`. A slow
or unavailable network can therefore make the first sync attempt fail; recovery
remains fail-safe and convergent through the service restart policy and the
10-minute retry timer. This avoids adding disconnected-network boot latency. If
strict first-attempt online semantics become a product requirement, enabling the
wait-online producer is an explicit boot-time tradeoff rather than a hidden
dependency.

## Remaining external blocker

The current locked krisCC release publishes the RPM and SHA256SUMS but no independently verifiable RPM/signature artifact. This repository therefore continues to verify the locked SHA256 and does **not** invent a signing key or claim signature verification that upstream does not provide. Upstream signing can be made mandatory once krisCC publishes a verifiable signature and trusted key/identity.
