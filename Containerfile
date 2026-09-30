# KrisOS M1 — persistent /usr overlay plus restricted rk package layer.
# M1 includes additive rk transactions, deployment sync and recovery.

# Fedora 45 is still Branched. Scheduled builds follow the current Minimal
# compose through :latest; CI resolves that tag to an exact digest for each run
# before building, so every published image remains traceable and reproducible.
# After Fedora 45 becomes stable the schedule is reduced to weekly.
ARG BASE_IMAGE=quay.io/bootc-devel/fedora-bootc-45-minimal:latest

# Fedora 45 keeps the r8169 RTL8168H Ethernet blob in the broad linux-firmware
# package rather than realtek-firmware. Use a disposable stage to source only
# the one required blob (plus its license material) from Fedora's signed RPM;
# linux-firmware itself never enters the final image.
FROM ${BASE_IMAGE} AS rtl8168-firmware-source
RUN set -eux; \
    dnf5 -y --setopt=install_weak_deps=False --exclude='*.i686' distro-sync; \
    dnf5 -y --setopt=install_weak_deps=False --exclude='*.i686' install linux-firmware; \
    test -f /usr/lib/firmware/rtl_nic/rtl8168h-2.fw.xz; \
    rpm -qf /usr/lib/firmware/rtl_nic/rtl8168h-2.fw.xz | grep -q '^linux-firmware-'; \
    test -d /usr/share/licenses/linux-firmware; \
    install -d -m 0755 /out/firmware/rtl_nic /out/licenses; \
    rpm -q --qf '%{NAME}\t%{EPOCHNUM}:%{VERSION}-%{RELEASE}.%{ARCH}\n' linux-firmware > /out/rtl8168-source-nevra.txt; \
    cp -a /usr/lib/firmware/rtl_nic/rtl8168h-2.fw.xz /out/firmware/rtl_nic/; \
    cp -a /usr/share/licenses/linux-firmware/. /out/licenses/

FROM ${BASE_IMAGE}

# Keep a Branched compose aligned with the repositories it advertises. This is
# intentionally part of the image build until Fedora 45 reaches stable.
RUN set -eux; \
    dnf5 -y --setopt=install_weak_deps=False --exclude='*.i686' distro-sync; \
    dnf5 check --dependencies; \
    ! rpm -qa --qf '%{ARCH}\n' | grep -qx i686; \
    dnf5 clean all; \
    rm -rf /run/dnf /var/cache/libdnf5 /var/lib/dnf/repos; \
    rm -f /var/log/dnf5.log /var/cache/ldconfig/aux-cache

ARG RELEASE=0.1.0-m1
LABEL org.opencontainers.image.title="krisos"
LABEL org.opencontainers.image.version="${RELEASE}"
LABEL org.opencontainers.image.description="Fedora 45 bootc Minimal + persistent additive /usr overlay and rk package layer (M1)"
LABEL containers.bootc="1"
LABEL ostree.bootable="1"

# Install only the hardware blob observed missing on the validated RTL8168H
# system. Keep provenance/license material while avoiding the broad firmware RPM.
COPY --from=rtl8168-firmware-source /out/firmware/rtl_nic/rtl8168h-2.fw.xz /usr/lib/firmware/rtl_nic/rtl8168h-2.fw.xz
COPY --from=rtl8168-firmware-source /out/licenses/ /usr/share/licenses/krisos-rtl8168-firmware/
COPY --from=rtl8168-firmware-source /out/rtl8168-source-nevra.txt /usr/share/krisos/firmware-provenance/rtl8168h-2-source-nevra.txt

# Global DNF5 policy: KrisOS is x86_64/noarch only. User-facing package
# operations in M1 inherit this and the wrapper will reject attempts to bypass
# the architecture/exclude policy. Repository countme is disabled through the
# DNF5 override layer rather than by editing Fedora-owned repo definitions.
RUN install -d -m 0755 /etc/dnf/libdnf5.conf.d /etc/dnf/repos.override.d /etc/xdg/KDE
COPY build_files/dnf-krisos.conf /etc/dnf/libdnf5.conf.d/90-krisos.conf
COPY build_files/90-krisos-privacy.repo /etc/dnf/repos.override.d/90-krisos-privacy.repo
COPY build_files/KDE-UserFeedback.conf /etc/xdg/KDE/UserFeedback.conf

# Immutable KrisOS package delta. Fedora owns every RPM already present in
# the resolved Fedora bootc base: exclude those names from the layering transaction and
# verify their exact installed EVRAs are unchanged afterwards. If the desktop
# requires a newer Fedora-owned RPM, the build must fail and the base digest
# must move forward instead.
COPY build_files/base-packages.txt /tmp/base-packages.txt
RUN set -eux; \
    rpm -qa --qf '%{NAME}\n' > /tmp/fedora-base-names.raw; \
    sed -e '/^gpg-pubkey$/d' \
      /tmp/fedora-base-names.raw > /tmp/fedora-base-names.filtered; \
    LC_ALL=C sort -u \
      /tmp/fedora-base-names.filtered > /tmp/fedora-base-names.txt; \
    test -s /tmp/fedora-base-names.txt; \
    for pkg in bootc bootupd dracut ostree systemd rpm dnf5 kernel-core; do \
      if ! grep -Fxq "$pkg" /tmp/fedora-base-names.txt; then \
        echo "Resolved Fedora base sanity check failed: missing $pkg" >&2; \
        exit 1; \
      fi; \
    done; \
    sed \
      -e 's/\r$//' \
      -e 's/[[:space:]]*#.*$//' \
      -e 's/^[[:space:]]*//' \
      -e 's/[[:space:]]*$//' \
      -e '/^$/d' \
      /tmp/base-packages.txt > /tmp/krisos-delta-names.raw; \
    LC_ALL=C sort -u \
      /tmp/krisos-delta-names.raw > /tmp/krisos-delta-names.txt; \
    LC_ALL=C comm -12 \
      /tmp/fedora-base-names.txt \
      /tmp/krisos-delta-names.txt \
      > /tmp/krisos-base-collisions.txt; \
    if [ -s /tmp/krisos-base-collisions.txt ]; then \
      echo 'KrisOS package delta collides with Fedora-owned base packages:' >&2; \
      cat /tmp/krisos-base-collisions.txt >&2; \
      echo 'Remove these names from build_files/base-packages.txt.' >&2; \
      exit 1; \
    fi; \
    : > /tmp/fedora-base-nevra.before; \
    while IFS= read -r pkg; do \
      rpm -q --qf '%{NAME}\t%{EPOCHNUM}:%{VERSION}-%{RELEASE}.%{ARCH}\n' "$pkg" \
        >> /tmp/fedora-base-nevra.before; \
    done < /tmp/fedora-base-names.txt; \
    LC_ALL=C sort -u -o \
      /tmp/fedora-base-nevra.before /tmp/fedora-base-nevra.before; \
    dnf_plugins_vra="$(rpm -q --qf '%{VERSION}-%{RELEASE}.%{ARCH}' libdnf5-cli)"; \
    sed -i "s/^dnf5-plugins$/dnf5-plugins-${dnf_plugins_vra}/" /tmp/krisos-delta-names.txt; \
    base_excludes="$(paste -sd, /tmp/fedora-base-names.txt)"; \
    xargs -r dnf5 -y \
      --setopt=install_weak_deps=False \
      --setopt="excludepkgs=${base_excludes}" \
      install < /tmp/krisos-delta-names.txt; \
    rpm -q glibc-langpack-en glibc-langpack-it langpacks-core-en langpacks-core-it; \
    if rpm -q glibc-all-langpacks >/dev/null 2>&1; then \
      if grep -Fxq glibc-all-langpacks /tmp/fedora-base-names.txt; then \
        echo 'glibc-all-langpacks is Fedora-base-owned; refusing image-side removal' >&2; \
        exit 1; \
      fi; \
      rpm -e glibc-all-langpacks; \
    fi; \
    assert_absent() { \
      if rpm -q "$1" >/dev/null 2>&1; then \
        echo "forbidden package installed: $1" >&2; \
        exit 1; \
      fi; \
    }; \
    for pkg in \
      glibc-all-langpacks \
      pipewire-jack-audio-connection-kit \
      pipewire-jack-audio-connection-kit-libs \
      sane-backends \
      sane-backends-libs \
      sane-airscan \
      libsane-airscan \
      gwenview \
      plasma-discover-notifier \
      plasma-discover-packagekit \
      PackageKit; \
    do \
      assert_absent "$pkg"; \
    done; \
    rpm -q \
      NetworkManager-wifi \
      wpa_supplicant \
      bluedevil \
      bluez \
      bluez-obexd \
      mt7xxx-firmware \
      amd-gpu-firmware \
      amd-ucode-firmware \
      mesa-dri-drivers \
      mesa-vulkan-drivers \
      libcanberra-backend-pulse \
      udisks2 \
      dolphin \
      konsole \
      kate \
      spectacle \
      ark \
      isoimagewriter \
      plasma-discover \
      plasma-discover-flatpak \
      cockpit \
      cockpit-system \
      cockpit-ws \
      okular \
      kcalc \
      kio-admin \
      kinfocenter \
      power-profiles-daemon \
      plasma-print-manager \
      cups \
      cups-filters \
      plasma-firewall \
      plasma-firewall-firewalld \
      firewalld \
      iproute \
      tar \
      bash-completion \
      ntfs-3g \
      ntfsprogs \
      os-prober \
      zram-generator \
      zram-generator-defaults \
      grubby; \
    rpm -q --whatprovides mesa-va-drivers; \
    test -e /usr/lib64/dri/radeonsi_drv_video.so; \
    test -f /usr/lib64/libcanberra-0.30/libcanberra-pulse.so; \
    test -f /usr/lib/firmware/rtl_nic/rtl8168h-2.fw.xz; \
    assert_absent linux-firmware; \
    if rpm -qa --qf '%{ARCH}\n' | grep -qx i686; then \
      echo 'i686 packages are not allowed in KrisOS' >&2; \
      exit 1; \
    fi; \
    dnf5 check --dependencies; \
    : > /tmp/fedora-base-nevra.after; \
    while IFS= read -r pkg; do \
      rpm -q --qf '%{NAME}\t%{EPOCHNUM}:%{VERSION}-%{RELEASE}.%{ARCH}\n' "$pkg" \
        >> /tmp/fedora-base-nevra.after; \
    done < /tmp/fedora-base-names.txt; \
    LC_ALL=C sort -u -o \
      /tmp/fedora-base-nevra.after /tmp/fedora-base-nevra.after; \
    diff -u /tmp/fedora-base-nevra.before /tmp/fedora-base-nevra.after; \
    dnf5 clean all; \
    rm -f \
      /tmp/base-packages.txt \
      /tmp/fedora-base-names.raw \
      /tmp/fedora-base-names.filtered \
      /tmp/fedora-base-names.txt \
      /tmp/krisos-delta-names.raw \
      /tmp/krisos-delta-names.txt \
      /tmp/krisos-base-collisions.txt \
      /tmp/fedora-base-nevra.before \
      /tmp/fedora-base-nevra.after

# Add Fedora bindings without replacing any image package.
RUN set -eux; \
    excludes="$(rpm -qa --qf '%{NAME}\n' | sort -u | paste -sd,)"; \
    rpm -qa --qf '%{NAME}\t%{EPOCHNUM}:%{VERSION}-%{RELEASE}.%{ARCH}\n' | sort > /tmp/rk-before; \
    dnf5 -y --setopt=install_weak_deps=False --setopt="excludepkgs=$excludes" install python3-libdnf5; \
    rpm -qa --qf '%{NAME}\t%{EPOCHNUM}:%{VERSION}-%{RELEASE}.%{ARCH}\n' | sort > /tmp/rk-after; \
    test -z "$(comm -23 /tmp/rk-before /tmp/rk-after)"; \
    python3 -c 'import libdnf5; assert hasattr(libdnf5.base.Base, "lock_system_repo")'; \
    dnf5 clean all; rm -f /tmp/rk-before /tmp/rk-after
COPY bin/rk /usr/bin/rk
RUN chmod 0755 /usr/bin/rk
COPY systemd/krisos-sync.service /usr/lib/systemd/system/krisos-sync.service
COPY systemd/krisos-sync.timer /usr/lib/systemd/system/krisos-sync.timer

# Persistent /usr overlay. Mount it in early real-root userspace rather than in
# initrd: OSTree has already exposed writable /var, while local-fs.target still
# holds normal services behind the overlay setup.
COPY systemd/krisos-overlay.sh /usr/libexec/krisos-overlay
COPY systemd/krisos-overlay.service /usr/lib/systemd/system/krisos-overlay.service
RUN chmod 0755 /usr/libexec/krisos-overlay

# Conservative hardening: only deltas from Fedora defaults that passed real
# Plasma/Wayland, networking, audio, rootless Podman and S3 suspend testing.
COPY build_files/55-krisos-hardening.conf /usr/lib/sysctl.d/55-krisos-hardening.conf

# Install the separately built krisCC component artifact late in the image so
# krisCC-only releases invalidate the smallest possible set of downstream layers.
# The workflow places the exact release RPM in the build context after verifying
# its SHA256SUMS. rpm (not dnf) is deliberate here: every runtime dependency must
# already be part of the declared image, so this step cannot resolve by replacing
# Fedora-owned RPMs.
COPY build_files/krisCC/krisCC.rpm /tmp/krisCC.rpm
COPY build_files/krisCC.lock /tmp/krisCC.lock
# krisCC is frozen as an image-owned component while application work is still
# being finished separately. The selected Fedora 45 RPM is integrity-pinned by
# SHA-256; --nosignature is scoped to this one local release artifact and does
# not weaken the global DNF/RPM signature policy.
RUN set -eux; \
    . /tmp/krisCC.lock; \
    printf '%s  %s\n' "$KRISCC_SHA256" /tmp/krisCC.rpm | sha256sum -c -; \
    rpm -Uvh --nosignature /tmp/krisCC.rpm; \
    rpm -q krisCC; \
    rpm -V krisCC; \
    rm -f /tmp/krisCC.rpm /tmp/krisCC.lock
COPY scripts/repair-home-labels.sh /usr/libexec/krisos/repair-home-labels
COPY build_files/krisCC-autostart.desktop /etc/xdg/autostart/krisCC-background.desktop

COPY build_files/99krisos-nss/ /usr/lib/dracut/modules.d/99krisos-nss/
COPY scripts/check-initramfs-accounts.sh /tmp/check-initramfs-accounts.sh

# Fedora 45 dracut 111-4 carries upstream dracut-ng #2490: the installed
# 70crypt generator uses top-level return statements, which systemd executes as
# a standalone generator and reports as exit status 2. Apply only the exact
# known-bad form; newer Fedora dracut builds that already contain the upstream
# exit-based fix pass through unchanged.
RUN set -eux; \
    generator=/usr/lib/dracut/modules.d/70crypt/crypt-generator.sh; \
    test -f "$generator"; \
    if grep -Fxq '[ -e /etc/crypttab ] || return 0' "$generator" && \
       grep -Fxq '[ -n "$GENERATOR_DIR" ] || return 1' "$generator"; then \
      sed -i \
        -e 's/^    return 0$/    exit 0/' \
        -e 's/^\[ -e \/etc\/crypttab \] || return 0$/[ -e \/etc\/crypttab ] || exit 0/' \
        -e 's/^\[ -n "\$GENERATOR_DIR" \] || return 1$/[ -n "\$GENERATOR_DIR" ] || exit 1/' \
        "$generator"; \
    fi; \
    grep -Fxq '    exit 0' "$generator"; \
    grep -Fxq '[ -e /etc/crypttab ] || exit 0' "$generator"; \
    grep -Fxq '[ -n "$GENERATOR_DIR" ] || exit 1' "$generator"; \
    ! grep -Fxq '[ -e /etc/crypttab ] || return 0' "$generator"; \
    ! grep -Fxq '[ -n "$GENERATOR_DIR" ] || return 1' "$generator"

# Fedora's canonical bootc initramfs must be regenerated after the KrisOS
# hardware firmware delta is installed. The pinned base initramfs predates the
# layered amd-ucode-firmware package; without this rebuild the deployed /boot
# copy can omit AuthenticAMD.bin even though the firmware RPM is installed.
RUN set -eux; \
    rpm -q iputils plasma-milou upower p11-kit-server; \
    test -f /usr/lib/firmware/amd-ucode/microcode_amd_fam19h.bin; \
    generated=0; \
    for kernel_dir in /usr/lib/modules/*; do \
      test -d "$kernel_dir" || continue; \
      test -f "$kernel_dir/modules.dep" || continue; \
      kver="${kernel_dir##*/}"; \
      dracut --force --no-hostonly --early-microcode --reproducible --zstd --add krisos-nss \
        "$kernel_dir/initramfs.img" "$kver"; \
      test -s "$kernel_dir/initramfs.img"; \
      lsinitrd "$kernel_dir/initramfs.img" | grep -F 'kernel/x86/microcode/AuthenticAMD.bin' >/dev/null; \
      bash /tmp/check-initramfs-accounts.sh "$kernel_dir/initramfs.img"; \
      lsinitrd -f /usr/lib/systemd/system-generators/dracut-crypt-generator \
        "$kernel_dir/initramfs.img" > /tmp/dracut-crypt-generator; \
      grep -Fxq '    exit 0' /tmp/dracut-crypt-generator; \
      grep -Fxq '[ -e /etc/crypttab ] || exit 0' /tmp/dracut-crypt-generator; \
      grep -Fxq '[ -n "$GENERATOR_DIR" ] || exit 1' /tmp/dracut-crypt-generator; \
      ! grep -Fxq '    return 0' /tmp/dracut-crypt-generator; \
      ! grep -Fxq '[ -e /etc/crypttab ] || return 0' /tmp/dracut-crypt-generator; \
      ! grep -Fxq '[ -n "$GENERATOR_DIR" ] || return 1' /tmp/dracut-crypt-generator; \
      generated=$((generated + 1)); \
    done; \
    test "$generated" -eq 1; \
    rm -f /tmp/check-initramfs-accounts.sh

# KrisOS stores persistent user homes under /var/home while /home is the bootc/
# OSTree compatibility link. Fedora SELinux homedir rules are generated from
# /etc/default/useradd when usepasswd=False, so set the correct default root and
# rebuild policy before any installed-system user is created by Anaconda.
RUN set -eux; \
    test -f /etc/default/useradd; \
    sed -ri 's|^HOME=.*$|HOME=/var/home|' /etc/default/useradd; \
    grep -Fxq 'HOME=/var/home' /etc/default/useradd; \
    semodule -B; \
    matchpathcon -n /var/home/kris | grep -q ':user_home_dir_t:'; \
    matchpathcon -n /var/home/kris/.config | grep -q ':config_home_t:'; \
    matchpathcon -n /var/home/kris/.local/share | grep -q ':data_home_t:'

# Snapshot every immutable package name owned by the final image: resolved Fedora
# base plus the KrisOS delta. RPM key pseudo-packages are deliberately not
# package-ownership policy; M1 handles repository/key trust separately.
RUN set -eux; \
    install -d -m 0755 /usr/share/krisos; \
    rpm -qa --qf '%{NAME}\n' \
      | sed -e '/^gpg-pubkey$/d' \
      | LC_ALL=C sort -u \
      > /usr/share/krisos/owned-packages.txt; \
    test -s /usr/share/krisos/owned-packages.txt; \
    rpm -qa --qf '%{NAME}\t%{EPOCHNUM}:%{VERSION}-%{RELEASE}.%{ARCH}\n' | sed '/^gpg-pubkey\t/d' | LC_ALL=C sort -u > /usr/share/krisos/owned-nevra.txt; \
    if grep -Fxq gpg-pubkey /usr/share/krisos/owned-packages.txt; then \
      echo 'gpg-pubkey must not appear in immutable ownership snapshot' >&2; \
      exit 1; \
    fi

# Factory state plus an explicit tmpfiles contract. Seed package intent and the
# initial NetworkManager radio policy only when missing; persistent user state
# must survive reboot and bootc image updates.
COPY build_files/tmpfiles-krisos.conf /usr/lib/tmpfiles.d/krisos.conf
RUN set -eux; \
    install -d -m 0755 /usr/share/factory/var/lib/krisos; \
    install -d -m 0755 /usr/share/factory/var/lib/NetworkManager; \
    : > /usr/share/factory/var/lib/krisos/packages.list
COPY build_files/NetworkManager.state /usr/share/factory/var/lib/NetworkManager/NetworkManager.state

RUN set -eux; \
    printf '%s\n' 'LANG=it_IT.UTF-8' > /etc/locale.conf; \
    test -f /etc/bluetooth/main.conf; \
    sed -i 's/^#AutoEnable=true$/AutoEnable=false/' /etc/bluetooth/main.conf; \
    grep -Fxq 'AutoEnable=false' /etc/bluetooth/main.conf; \
    test -f /etc/xdg/autostart/geoclue-demo-agent.desktop; \
    grep -Fxq 'Hidden=true' /etc/xdg/autostart/geoclue-demo-agent.desktop || printf '\nHidden=true\n' >> /etc/xdg/autostart/geoclue-demo-agent.desktop; \
    firewall-offline-cmd --zone=public --remove-service-from-zone=ssh; \
    firewall-offline-cmd --zone=public --remove-service-from-zone=mdns; \
    systemctl enable krisos-overlay.service; \
    systemctl enable krisos-sync.timer; \
    systemctl enable --force plasmalogin.service; \
    systemctl enable firewalld.service; \
    systemctl enable systemd-timesyncd.service; \
    systemctl disable systemd-homed.service; \
    systemctl disable avahi-daemon.service avahi-daemon.socket; \
    systemctl disable mdmonitor.service raid-check.timer; \
    systemctl disable flatpak-add-fedora-repos.service; \
    systemctl disable cockpit.socket; \
    systemctl mask bootc-fetch-apply-updates.timer dnf-makecache.timer dnf5-makecache.timer || true; \
    systemctl disable ufw.service || true; \
    systemctl set-default graphical.target

# Static image invariants. Runtime overlay persistence is intentionally left to
# the M1 VM smoke test; a green container build cannot prove it.
RUN set -eux; \
    assert_absent() { \
      if rpm -q "$1" >/dev/null 2>&1; then \
        echo "forbidden package installed: $1" >&2; \
        exit 1; \
      fi; \
    }; \
    assert_not_in_file() { \
      if grep -Fxq "$1" "$2"; then \
        echo "forbidden entry in $2: $1" >&2; \
        exit 1; \
      fi; \
    }; \
    assert_disabled() { \
      if systemctl is-enabled "$1" >/dev/null 2>&1; then \
        echo "unit must not be enabled: $1" >&2; \
        exit 1; \
      fi; \
    }; \
    test -x /usr/bin/bootc; \
    test -x /usr/bin/ostree; \
    test -x /usr/bin/dnf5; \
    test -x /usr/bin/efibootmgr; \
    test -x /usr/bin/grubby; \
    test -x /usr/bin/grub2-reboot; \
    test -x /usr/bin/krisCC; \
    rpm -q krisCC; \
    rpm -V krisCC; \
    grep -Fxq 'HOME=/var/home' /etc/default/useradd; \
    matchpathcon -n /var/home/kris | grep -q ':user_home_dir_t:'; \
    matchpathcon -n /var/home/kris/.config | grep -q ':config_home_t:'; \
    matchpathcon -n /var/home/kris/.local/share | grep -q ':data_home_t:'; \
    test -f /usr/lib/firmware/amd-ucode/microcode_amd_fam19h.bin; \
    kernel_count=0; \
    for kernel_dir in /usr/lib/modules/*; do \
      test -f "$kernel_dir/modules.dep" || continue; \
      test -s "$kernel_dir/initramfs.img"; \
      lsinitrd "$kernel_dir/initramfs.img" | grep -F 'kernel/x86/microcode/AuthenticAMD.bin' >/dev/null; \
      kernel_count=$((kernel_count + 1)); \
    done; \
    test "$kernel_count" -eq 1; \
    test -f /usr/share/applications/krisCC.desktop; \
    test -f /usr/share/metainfo/org.kriscc.KrisCC.metainfo.xml; \
    test -f /usr/share/polkit-1/actions/org.kriscc.controlcenter.policy; \
    test -f /etc/xdg/autostart/krisCC-background.desktop; \
    grep -Fxq 'Exec=/usr/bin/krisCC --background' /etc/xdg/autostart/krisCC-background.desktop; \
    test -x /usr/bin/dolphin; \
    test -x /usr/bin/konsole; \
    test -x /usr/bin/kate; \
    test -x /usr/bin/spectacle; \
    test -x /usr/bin/ark; \
    test -x /usr/bin/isoimagewriter; \
    test -x /usr/bin/plasma-discover; \
    rpm -q libcanberra-backend-pulse; \
    test -f /usr/lib64/libcanberra-0.30/libcanberra-pulse.so; \
    test -x /usr/libexec/cockpit-tls; \
    test -x /usr/bin/okular; \
    test -x /usr/bin/kcalc; \
    test -x /usr/bin/kinfocenter; \
    test -x /usr/bin/kfind; \
    test -x /usr/bin/qdirstat; \
    test -x /usr/bin/powerprofilesctl; \
    test -x /usr/bin/os-prober; \
    test -x /usr/bin/ntfsresize; \
    test -x /usr/libexec/krisos-overlay; \
    test -f /usr/lib/systemd/system/krisos-overlay.service; \
    test -f /usr/lib/systemd/system/krisos-sync.service; \
    test -f /usr/lib/systemd/system/krisos-sync.timer; \
    test -e /usr/lib/systemd/system/plasmalogin.service; \
    test -s /usr/share/krisos/owned-packages.txt; \
    grep -Fxq krisCC /usr/share/krisos/owned-packages.txt; \
    assert_not_in_file gpg-pubkey /usr/share/krisos/owned-packages.txt; \
    test -e /usr/share/factory/var/lib/krisos/packages.list; \
    test ! -s /usr/share/factory/var/lib/krisos/packages.list; \
    test -f /usr/share/factory/var/lib/NetworkManager/NetworkManager.state; \
    grep -Fxq 'WirelessEnabled=false' /usr/share/factory/var/lib/NetworkManager/NetworkManager.state; \
    test -f /usr/lib/tmpfiles.d/krisos.conf; \
    grep -Fxq 'd /var/lib/krisos 0755 root root -' \
      /usr/lib/tmpfiles.d/krisos.conf; \
    grep -Fxq 'C /var/lib/krisos/packages.list 0644 root root - /usr/share/factory/var/lib/krisos/packages.list' \
      /usr/lib/tmpfiles.d/krisos.conf; \
    grep -Fxq 'C /var/lib/NetworkManager/NetworkManager.state 0600 root root - /usr/share/factory/var/lib/NetworkManager/NetworkManager.state' \
      /usr/lib/tmpfiles.d/krisos.conf; \
    test -f /usr/lib/sysctl.d/55-krisos-hardening.conf; \
    grep -Fxq 'kernel.kptr_restrict = 2' /usr/lib/sysctl.d/55-krisos-hardening.conf; \
    grep -Fxq 'fs.protected_regular = 2' /usr/lib/sysctl.d/55-krisos-hardening.conf; \
    grep -Fxq 'fs.protected_fifos = 2' /usr/lib/sysctl.d/55-krisos-hardening.conf; \
    grep -Fxq 'fs.suid_dumpable = 0' /usr/lib/sysctl.d/55-krisos-hardening.conf; \
    grep -Fxq 'AutoEnable=false' /etc/bluetooth/main.conf; \
    grep -Fxq 'Hidden=true' /etc/xdg/autostart/geoclue-demo-agent.desktop; \
    test -f /etc/dnf/repos.override.d/90-krisos-privacy.repo; \
    grep -Fxq '[*]' /etc/dnf/repos.override.d/90-krisos-privacy.repo; \
    grep -Fxq 'countme=false' /etc/dnf/repos.override.d/90-krisos-privacy.repo; \
    test -f /etc/xdg/KDE/UserFeedback.conf; \
    grep -Fxq '[UserFeedback]' /etc/xdg/KDE/UserFeedback.conf; \
    grep -Fxq 'Enabled=false' /etc/xdg/KDE/UserFeedback.conf; \
    ! firewall-offline-cmd --zone=public --list-services | tr ' ' '\n' | grep -Eq '^(ssh|mdns)$'; \
    grep -Eq '^SELINUX=enforcing$' /etc/selinux/config; \
    grep -Fxq 'LANG=it_IT.UTF-8' /etc/locale.conf; \
    grep -Fxq 'excludepkgs=*.i686' /etc/dnf/libdnf5.conf.d/90-krisos.conf; \
    grep -Fxq 'multilib_policy=best' /etc/dnf/libdnf5.conf.d/90-krisos.conf; \
    grep -Fxq 'install_weak_deps=False' /etc/dnf/libdnf5.conf.d/90-krisos.conf; \
    rpm -q glibc-langpack-en glibc-langpack-it langpacks-core-en langpacks-core-it; \
    rpm -q xcb-util-cursor; \
    test -f /usr/lib/firmware/rtl_nic/rtl8168h-2.fw.xz; \
    test -d /usr/share/licenses/krisos-rtl8168-firmware; \
    grep -Eq '^linux-firmware[[:space:]]' /usr/share/krisos/firmware-provenance/rtl8168h-2-source-nevra.txt; \
    test -e /usr/lib64/qt6/plugins/platforms/libqxcb.so; \
    test -e /usr/lib64/qt6/plugins/plasma/kcms/systemsettings/kcm_firewall.so; \
    test -e /usr/lib64/qt6/plugins/kf6/plasma_firewall/firewalldbackend.so; \
    systemctl is-enabled krisos-overlay.service | grep -qx enabled; \
    systemctl is-enabled krisos-sync.timer | grep -qx enabled; \
    systemctl is-enabled plasmalogin.service | grep -qx enabled; \
    systemctl is-enabled firewalld.service | grep -qx enabled; \
    systemctl is-enabled systemd-timesyncd.service | grep -qx enabled; \
    assert_disabled systemd-homed.service; \
    assert_disabled avahi-daemon.service; \
    assert_disabled avahi-daemon.socket; \
    assert_disabled mdmonitor.service; \
    assert_disabled raid-check.timer; \
    assert_disabled flatpak-add-fedora-repos.service; \
    assert_disabled cockpit.socket; \
    assert_disabled bootc-fetch-apply-updates.timer; \
    assert_disabled dnf-makecache.timer; \
    assert_disabled dnf5-makecache.timer; \
    assert_disabled ufw.service; \
    test -z "$(ldd /usr/lib64/qt6/plugins/platforms/libqxcb.so | awk '/not found/{print}')"; \
    test -z "$(ldd /usr/libexec/plasma-login-greeter | awk '/not found/{print}')"; \
    assert_absent glibc-all-langpacks; \
    assert_absent linux-firmware; \
    assert_absent plasma-discover-notifier; \
    assert_absent plasma-discover-packagekit; \
    assert_absent PackageKit; \
    bootc container lint

# Final bootc filesystem hygiene. Runtime state is recreated by tmpfiles.
COPY build_files/60-krisos-runtime-state.conf /usr/lib/tmpfiles.d/60-krisos-runtime-state.conf

RUN set -eux; \
    find /run /tmp -mindepth 1 -maxdepth 1 -exec rm -rf -- {} + 2>/dev/null || true; \
    rm -rf \
      /var/cache/fwupd \
      /var/cache/libdnf5 \
      /var/cache/libX11 \
      /var/cache/swcatalog \
      /var/db/sudo \
      /var/lib/AccountsService \
      /var/lib/bluetooth \
      /var/lib/color \
      /var/lib/dnf/repos \
      /var/lib/flatpak \
      /var/lib/fwupd \
      /var/lib/geoclue \
      /var/lib/power-profiles-daemon \
      /var/lib/samba \
      /var/lib/udisks2 \
      /var/log/samba \
      /var/spool/cups; \
    rm -f \
      /var/lib/authselect/checksum \
      /var/lib/systemd/catalog/database \
      /var/lib/systemd/random-seed \
      /var/log/dnf5.log \
      /var/log/dnf5.log.* \
      /var/cache/ldconfig/aux-cache; \
    authselect check; \
    bootc container lint --fatal-warnings
