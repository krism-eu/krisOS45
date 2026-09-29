#!/bin/bash
# Resolve immutable bootc accounts without pulling desktop NSS services into initrd.
check() { return 0; }
depends() { echo base; }
install() {
    inst_multiple getent
    inst_libdir_file 'libnss_altfiles.so.2'
    inst_simple /usr/lib/passwd
    inst_simple /usr/lib/group
    # Layered RPM scriptlets may have created identities in /etc rather than
    # /usr/lib. Include only accounts needed by initrd tmpfiles/udev rules.
    local name
    for name in root audio disk utmp clock tty kmem input video render tss; do
        if ! grep -q "^${name}:" "$initdir/etc/group"; then
            getent group "$name" >> "$initdir/etc/group" || return 1
        fi
    done
    if ! grep -q '^tss:' "$initdir/etc/passwd"; then
        getent passwd tss >> "$initdir/etc/passwd" || return 1
    fi
    # Override any desktop NSS configuration installed by another module.
    mkdir -p "$initdir/etc"
    printf 'passwd: files altfiles\ngroup: files altfiles\n' > "$initdir/etc/nsswitch.conf"
}
