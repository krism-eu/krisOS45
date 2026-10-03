# K1 Fedora 45 payload for krisCC 0.8.2

The installer embeds one exact signed KrisOS45 payload. The `m1` channel is
recorded as the installed system's future manual update target.

- Payload commit: `dd2237d95e9d0e4fc3d58c72cb589245a6241ee6`
- Immutable source: `ghcr.io/krism-eu/krisos45:build-37122693739-1`
- Installed target: `ghcr.io/krism-eu/krisos45:m1`
- Manifest digest: `sha256:edacc9d403ece4d6f5aa50326a1051b94da5234c198be0504913bf57dc0e4a5c`
- krisCC: `0.8.2-1.fc45.x86_64`
- Successful candidate run: https://github.com/krism-eu/krisOS45/actions/runs/37122693739

## Evidence at the lock update

Source checks, build, container integration, immutable publication, Cosign
verification and anonymous manifest access passed for this candidate.
Real-hardware boot/reboot/recovery acceptance has not been recorded for this
digest. The previous payload's hardware acceptance must not be attributed to it.

At this update `m1` still points to the previous digest
`sha256:995957957b589019cdb536f1f2b67ef443e1023c5911277965d1fbba2c96345f`.
Promote the exact new digest through `promote-m1.yml` before starting the ISO
workflow. Updating this lock does not promote the payload or certify a new ISO.

## Remaining release sequence

1. Test the new immutable digest on the intended host and record the outcome.
2. Promote that exact signed digest to `m1`.
3. Run `build-k1-final-iso.yml` on `iso`.
4. Validate the generated ISO's interactive installation and first boot before
   treating it as a final installer.

The ISO workflow verifies source digest, `m1` equality, the
`publish-candidate.yml@refs/heads/main` Cosign identity, OCI revision and krisCC
version. It extracts the three maintained host QA scripts from the locked
payload commit. Anaconda runtime, partitioning and user creation remain
interactive and unchanged.
