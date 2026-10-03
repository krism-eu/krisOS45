# KrisOS K1 ISO validation

The ISO branch validates only the **installation path**. Runtime correctness is
owned by `main`.

## Locked payload

The workflow reads `build_files/KrisOS-payload.lock` and requires the exact
Fedora 45 payload commit, immutable registry reference, manifest digest and expected krisCC
EVRA. It verifies the registry manifest and the
`publish-candidate.yml@refs/heads/main` Cosign identity,
pulls by digest, checks the OCI revision label and inspects the payload before
building the installer.

The exact payload identity is recorded in `build_files/KrisOS-payload.lock`.
Validation evidence and outstanding host acceptance are recorded in
`docs/K1_STABLE_BACKUP.md`. The locked digest must be promoted to `m1` before
the ISO build; the workflow rejects a different update-channel digest.

## Installer contract

Fedora 45 Anaconda remains graphical and interactive. The ISO preselects only the
verified bootc payload and localization. It must not contain unattended storage,
credentials, automatic reboot/shutdown or external Kickstart selection.

The live installer keeps SELinux enabled but permissive
(`selinux=1 enforcing=0`); the installed system requests enforcing mode.

Validation layout:

- EFI System Partition -> `/boot/efi` (vfat)
- dedicated ext4 -> `/boot`
- dedicated ext4 -> `/`
- dedicated ext4 -> `/home` in Anaconda (persistent `/var/home` in the payload)
- no disk swap partition; KrisOS uses zram

Create the desktop user manually and enable Anaconda's administrator option.

## Post-install QA

The ISO artifact includes `qa/` scripts extracted directly from the exact
locked payload commit, not copied from the installer branch:

- `boot-check.sh`
- `release-check.sh`
- `release-state.py`

There is no VM orchestrator in the current payload. Host checks and reboot,
switch and recovery drills are coordinated manually.

After installation set the expected immutable Fedora 45 payload reference, expected krisCC
EVRA and admin user, then run `release-check.sh` followed by its reboot
persistence check. Physical QA additionally covers Plasma login, networking,
audio/GPU, suspend/resume, RK add/remove/sync/recovery and krisCC GUI workflows.
