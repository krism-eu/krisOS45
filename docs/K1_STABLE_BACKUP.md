# K1.0 Fedora 45 locked payload

The K1 installer consumes one exact signed KrisOS45 payload build and records
the normal `m1` channel only as the installed system's future manual update
target.

- KrisOS45 payload commit: `2e07f3528b5aa3011f5826ce524029ec60e7f63e`
- Immutable source ref: `ghcr.io/krism-eu/krisos45:build-36909460134-1`
- Installed target channel: `ghcr.io/krism-eu/krisos45:m1`
- Manifest digest: `sha256:995957957b589019cdb536f1f2b67ef443e1023c5911277965d1fbba2c96345f`
- krisCC in payload: `0.8.1-1.fc45.x86_64`
- Validated Publish M1 Candidate run: `36909460134`
- Hardware runtime acceptance: `ROCK-SOLID-CHECK-PASS` on the exact promoted digest

This source payload passed the hardened KrisOS45 candidate workflow, immutable
publication, Cosign verification, anonymous pull verification, exact-digest M1
promotion, and subsequent real-hardware runtime validation.

The ISO workflow verifies the immutable source tag against the locked digest,
requires the current `m1` tag to resolve to that same digest, and verifies the
Cosign identity of `publish-candidate.yml@refs/heads/main`. The installer embeds
that exact source image while setting `m1` as the installed target reference for
future user-triggered updates.

Any runtime payload change requires a new validated immutable candidate, exact
promotion, hardware acceptance, and a deliberate update of this lock before a
new ISO is treated as final.
