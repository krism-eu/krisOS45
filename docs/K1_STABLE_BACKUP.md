# K1.0 Fedora 45 locked payload

The K1 installer consumes one exact signed KrisOS45 payload build and records
the normal `m1` channel only as the installed system's future manual update
target.

- KrisOS45 payload commit: `c23475bb8e1d516555903c1b590e65cd1243420f`
- Immutable source ref: `ghcr.io/krism-eu/krisos45:build-36691073744-1`
- Installed target channel: `ghcr.io/krism-eu/krisos45:m1`
- Manifest digest: `sha256:51f7b103fa575e6d4b48c2dd47eccc641450d6138c5c703c228c5acf4c5cd2b8`
- Fedora 45 Minimal base digest: `sha256:cd3f098bf8490b6f8b9881730b483332e814bf97178cf54af77ddf4d96f406d4`
- krisCC in payload: `0.7.10-1.fc45.x86_64`
- Validated Build M1 run: `36691073744`

The source payload passed the complete Build M1 workflow and was then booted
on the target hardware by exact digest. Hardware acceptance confirmed a clean
KrisOS overlay state, SELinux Enforcing, native `libcanberra-backend-pulse`
with successful Plasma startup sound, and the corrected dracut crypt generator
embedded in the initramfs.

The ISO workflow verifies the source tag against the locked digest and verifies
the Cosign identity of `build-m1.yml@refs/heads/main`. The installer embeds
that exact source image while setting `m1` as the installed target reference
for future user-triggered updates.

Any runtime change requires a new successful payload build, hardware acceptance
of its exact digest, and a deliberate update of `KrisOS-payload.lock`.
