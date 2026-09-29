> **Documento storico.** Descrive il candidato 0.7.0-6 e non rappresenta lo stato corrente del payload. La sorgente di verità per la versione krisCC attuale è `build_files/krisCC.lock`.

# Candidate corrective update: krisCC 0.7.0-6

CC source: `3a298572e91f7b7342c48d5bbede61f73efc90d7`.
Component build: https://github.com/krism-eu/krisCC/actions/runs/35543821653 .

The component lock selects the exact RPM and SHA-256; image CI success is required
before the image can be published. Desktop acceptance remains a host check.

## Changes

- krisCC: real procfs RAM sampling, lazy creation of pages, consistent native
  Kirigami presentation, quick user-only trash action with confirmation.
- Explicit desktop components: plasma-milou (Overview), upower, p11-kit-server, iputils.
- Minimal initrd NSS configuration and immutable account databases. Build-time
  chroot checks resolve the accounts previously missing in tmpfiles/udev logs.
- Pinned Node 24 GitHub Actions.

## Persistent home labels

`/home` resolving to a separate filesystem on `/var/home` is supported. An image
switch does not itself repair labels on existing persistent files. Preview:

```sh
sudo /usr/libexec/krisos/repair-home-labels "$USER"
```

Apply the four-path repair explicitly:

```sh
sudo /usr/libexec/krisos/repair-home-labels --apply "$USER"
```

The helper follows the existing SELinux policy, does not recurse, does not use
`restorecon -F`, and skips symlinked configuration directories. It does not
assert that unexamined descendants are correct. Re-login, verify actual label
matches and check for new AVCs and Plasma Login log creation.

## Acceptance after switching

Record the booted image digest and installed krisCC NEVRA. Inspect the new boot
journal for unknown initrd users/groups, plasma-milou load errors, missing UPower or
p11-kit server, and QML errors. Navigate all CC pages and internal tabs, resize
the window, verify live RAM and quick trash confirmation without deleting data.
Check Background activation, audio after display sleep, and startup resource
use separately. Keep the rollback deployment until these checks pass.

No removal of Xwayland/XCB or change to rk's /usr-only payload policy is included.
No broad home relabel or automatic reboot is added.
