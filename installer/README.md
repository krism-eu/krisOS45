# KrisOS Fedora 45 installer

This directory contains the minimal installer path for KrisOS.

## Goals

- Fedora 45 Anaconda runtime pinned to 45.25-1.fc45, independent from the installed KrisOS payload.
- `bootc-generic-iso`, not the legacy `anaconda-iso` path.
- Exact validated KrisOS bootc payload embedded in the ISO, while Anaconda storage and user setup remain interactive.
- No destructive automatic partitioning.
- Manual ext4 layout with separate `/var/home` supported by Fedora 45 Anaconda.
- Manual user creation: the intended desktop user must be marked as administrator (wheel); no account credentials or autologin are baked into the image.
- Reduce avoidable disk-discovery delay without disabling generic storage discovery.

## Build

The supported offline build is `.github/workflows/build-k1-final-iso.yml` on
`k1.0-final-iso`. It verifies the payload digest and Cosign identity,
pulls by digest, assigns the locked target reference locally, and builds the ISO.
The installer branch contains no duplicate KrisOS runtime source; post-install QA
scripts are extracted from the exact main commit named by
`build_files/KrisOS-payload.lock`.

For a local build, first reproduce that workflow's signature/digest verification
and rootful Podman payload import. Then export `KRISOS_PAYLOAD_REF` to the locked
published target and `KRISOS_PAYLOAD_IMAGE_ID` to the verified local image ID before
running `bash installer/build-installer.sh` as a normal user with sudo access.
The script refuses a missing or mismatched local payload. It requires Podman and
uses Image Builder pinned by digest in the script; any IMAGE_BUILDER_IMAGE override
must also be a digest reference. No `latest` default or tag-only override is used.

The payload is embedded for offline installation. Partitioning and user creation
remain interactive. Artifacts and SHA256SUMS are written under installer/output/.

## Installation layout

Do not use automatic partition clearing while validating the installer. In Anaconda storage configuration, use the existing/free disk space and assign:

- EFI System Partition -> `/boot/efi` (vfat)
- dedicated ext4 partition -> `/boot`
- dedicated ext4 partition -> `/`
- dedicated ext4 partition -> `/var/home`

Do not select automatic storage, automatic partition clearing, LVM autopartitioning, or a swap partition for the K1.0 validation install.

`/var/home` is intentional: KrisOS exposes `/home` as a symlink to `/var/home`, matching bootc/OSTree conventions.

No swap partition is required; KrisOS uses zram.

## User creation

Keep user creation interactive in Anaconda. For the K1.0 physical validation:

- create the intended desktop account manually;
- enable the Anaconda **administrator** option so the account is a member of `wheel`;
- do not enable automatic login;
- do not bake a password, password hash, or user-specific secret into the installer image.

KrisOS sets the image-level `useradd` default home root to `/var/home` and rebuilds the SELinux homedir policy before Anaconda creates users. The installed-system validation checks both `wheel` membership and the real `/var/home/<user>` SELinux label.

## Disk discovery policy

The ISO boot entry currently adds:

- `inst.wait_for_disks=0`
- `inst.noibft`

This removes Anaconda's extra wait and avoids iBFT probing. We intentionally do **not** disable multipath, mdraid, LVM, USB, device-mapper, or generic block probing yet. Fedora 45 must first be measured on the physical validation machine; only a confirmed slow subsystem should be disabled.

## Installer interaction contract

The ISO starts the normal graphical Anaconda flow. It does **not** provide
`clearpart`, `autopart`, `part`, `user`, `rootpw`, `reboot` or
`shutdown` directives, and the boot entry does not use `inst.ks=`,
`inst.cmdline` or `inst.noninteractive`.

Only the bootc payload source/target is preselected. Storage, formatting and
desktop-user creation remain explicit installer choices. The payload container
is embedded by Image Builder through `--bootc-installer-payload-ref`; this
option is used with the recommended `bootc-generic-iso` image type and does
not select the historical `bootc-installer` image type.

## Security note

The ISO boot entry explicitly uses `selinux=1 enforcing=0`. This keeps the SELinux LSM and policy active in the live installer while making access denials permissive during the Anaconda runtime. `selinux=0` is forbidden because it disables SELinux rather than merely relaxing enforcement, and `enforcing=1` is forbidden for the live installer because the container-derived installer tree is not validated for enforcing-mode boot.

The interactive Anaconda defaults explicitly contain `selinux --enforcing` for the installed system. The embedded KrisOS payload also carries `SELINUX=enforcing` in `/etc/selinux/config`. Post-install validation must confirm `getenforce == Enforcing` and that the installed kernel command line contains neither `selinux=0` nor `enforcing=0`.

`SHA256SUMS` detects corruption or accidental changes to a downloaded installer artifact. It is not a replacement for a future signed-release policy such as Cosign.
