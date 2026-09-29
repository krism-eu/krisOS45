# KrisOS K1 ISO validation

The ISO branch validates only the **installation path**. Runtime correctness is
owned by `main`.

## Locked payload

The workflow reads `build_files/KrisOS-payload.lock` and requires the exact
main commit, immutable registry reference, manifest digest and expected krisCC
EVRA. It verifies the registry manifest and the main Build M1 Cosign identity,
pulls by digest, checks the OCI revision label and inspects the payload before
building the installer.

The current lock is main `6212322d22ccf170562976bef3c288d531f98bb2`,
digest `sha256:7f1e12e8fbf3b94acb389045dc920d30d998458ca170453a8493810ffdebecff`,
with krisCC `0.7.0-4.fc44.x86_64`.

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
- dedicated ext4 -> `/var/home`
- no disk swap partition; KrisOS uses zram

Create the desktop user manually and enable Anaconda's administrator option.

## Post-install QA

The ISO artifact includes `qa/` scripts extracted directly from the exact
locked main commit, not copied from the installer branch:

- `boot-check.sh`
- `release-check.sh`
- `release-state.py`
- `run-release-vm.sh`

After installation set the expected immutable main reference, expected krisCC
EVRA and admin user, then run `release-check.sh` followed by its reboot
persistence check. Physical QA additionally covers Plasma login, networking,
audio/GPU, suspend/resume, RK add/remove/sync/recovery and krisCC GUI workflows.
