# KrisOS45 Fedora 45 installer

This directory contains the final-candidate installer path for KrisOS45.

## Goals

- Fedora 45 Anaconda runtime pinned to 45.27-1.fc45, independent from the installed KrisOS payload.
- `bootc-generic-iso`, not the legacy `anaconda-iso` path.
- Embed the exact signed KrisOS45 payload while recording `m1` as the installed system's manual update channel; hardware acceptance is recorded separately.
- Keep Anaconda storage and user setup interactive and non-destructive.
- Use a physically separate ext4 home partition assigned to the logical `/home` mount point in Anaconda.
- Keep the payload's OSTree/bootc model intact: `/home` resolves to persistent `/var/home`; Anaconda must not mount the separate home filesystem directly at `/var/home`.
- Manual user creation: the desktop user must be marked as administrator (wheel); no credentials or autologin are baked into the image.

## Locked payload

`build_files/KrisOS-payload.lock` separates the exact install source from the future update channel:

- `KRISOS_SOURCE_REF` is the immutable successful build tag; see `docs/K1_STABLE_BACKUP.md` for hardware acceptance status;
- `KRISOS_DIGEST` pins that source content exactly;
- `KRISOS_TARGET_REF` is `ghcr.io/krism-eu/krisos45:m1`, recorded in the installed system for user-triggered future updates;
- the ISO workflow verifies the payload's Cosign identity against `publish-candidate.yml@refs/heads/main` and requires `m1` to match the locked digest.

The ISO never rebuilds KrisOS itself.

## Installation layout

In Anaconda storage configuration use the intended disk/free space and assign:

- EFI System Partition -> `/boot/efi` (vfat)
- dedicated ext4 partition -> `/boot`
- dedicated ext4 partition -> `/`
- dedicated ext4 partition -> `/home`

Do not assign the separate home filesystem to `/var/home` directly.

`/home` is intentional in the installer UI. The KrisOS payload already owns the bootc/OSTree compatibility mapping to persistent `/var/home`, including `HOME=/var/home` as the image-level useradd/SELinux policy root.

Do not use automatic partition clearing, LVM autopartitioning or a swap partition for the final validation install. KrisOS uses zram.

## User creation

Keep user creation interactive:

- create the intended desktop account manually;
- enable the Anaconda **administrator** option so the account is in `wheel`;
- do not enable automatic login;
- do not bake a password, password hash or user-specific secret into the installer image.

## Fresh-install finalization

The live installer remains SELinux-enabled/permissive (`selinux=1 enforcing=0`), while the installed KrisOS target is enforcing.

The installer retains only the proven fresh-install adaptations:

- Anaconda's target `chage` operation uses shadow-utils prefix mode (`-P`) instead of `-R`, preserving the previously validated bootc/libselinux workaround.
- The bootc/composefs fstab finalizer remains in place.
- There is **no installer-side home relabel hook**. With the separate filesystem assigned to `/home`, Anaconda/bootc and the payload policy own home creation and labeling. Post-install QA checks the result before any repair is considered.
- Fedora 45's live-image `autovt@.service` alias is removed before enabling Anaconda's own VT alias.

These are installer-only adaptations; they do not alter the KrisOS runtime payload.

## Build

The supported build is `.github/workflows/build-k1-final-iso.yml` on `iso`.

For a local reproduction, first verify the exact source digest/signature and import that image into rootful Podman. Then set:

- `KRISOS_SOURCE_REF` to the validated immutable build tag;
- `KRISOS_TARGET_REF` to the intended update-channel tag;
- `KRISOS_PAYLOAD_IMAGE_ID` to the verified local source image ID.

Run `bash installer/build-installer.sh` as a normal user with sudo access. The script uses Image Builder pinned by digest and refuses localhost/digest refs where a published tag is required.

Artifacts and `SHA256SUMS` are written below `installer/output/`.

## Disk discovery policy

The ISO boot entry keeps:

- `inst.wait_for_disks=0`
- `inst.noibft`

It does not disable generic USB, device-mapper, multipath, mdraid or LVM discovery.

## Installer interaction contract

The ISO starts graphical Anaconda. It does not provide `clearpart`, `autopart`, `part`, `user`, `rootpw`, `reboot` or `shutdown` directives, and does not use `inst.ks=`, `inst.cmdline` or `inst.noninteractive`.

The exact immutable source payload is embedded through `--bootc-installer-payload-ref`; the installed target image reference is the separate `m1` channel.

## Security

The live ISO explicitly uses `selinux=1 enforcing=0`; the installed target explicitly uses `selinux --enforcing`. `selinux=0` is forbidden.

Post-install validation must confirm SELinux Enforcing, the `/home -> /var/home` model, the separate home filesystem, correct labels, correct ESP/fstab/bootloader state and a clean first reboot.
