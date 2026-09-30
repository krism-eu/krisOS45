# K1.0 Fedora 45 locked payload

The K1 installer consumes one exact signed KrisOS45 payload build and records
the normal `m1` channel only as the installed system's future manual update
target.

- KrisOS45 payload commit: `613c430b2c7894778d76da085ddb0d206e201ee8`
- Immutable source ref: `ghcr.io/krism-eu/krisos45:build-36748128019-1`
- Installed target channel: `ghcr.io/krism-eu/krisos45:m1`
- Manifest digest: `sha256:cd3363dec2573cde2fddd18de7833f3e5687a710d2362283e493e79433b5cd59`
- Fedora 45 Minimal base digest: `sha256:cd3f098bf8490b6f8b9881730b483332e814bf97178cf54af77ddf4d96f406d4`
- krisCC in payload: `0.8.1-1.fc45.x86_64`
- Validated Build M1 run: `36748128019`

This source payload passed the complete Build M1 workflow, including the
krisCC component integrity checks, image inspection, real signed RPM package
layer integration, immutable publication, Cosign verification and anonymous
pull verification.

The ISO workflow verifies the source tag against the locked digest and verifies
the Cosign identity of `build-m1.yml@refs/heads/main`. The installer embeds
that exact source image while setting `m1` as the installed target reference
for future user-triggered updates.

This lock identifies the CI-validated ISO candidate. Hardware acceptance of the
new payload/installer must be performed against this exact digest before the
candidate is treated as the final hardware-accepted K1 image.
