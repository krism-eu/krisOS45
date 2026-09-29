#!/usr/bin/bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mode="${1:-check}"
expected_kriscc="${KRISOS_EXPECT_KRISCC:-}"
expected_image="${KRISOS_EXPECT_IMAGE:-}"
token="${KRISOS_E2E_TOKEN:-}"
sentinel_dir="/usr/share/krisos-e2e"
sentinel_name=".krisos-release-e2e-${token}"
sentinel="$sentinel_dir/$sentinel_name"
upper_sentinel="/var/lib/krisos/upper/share/krisos-e2e/$sentinel_name"
previous_deployment="${KRISOS_E2E_PREVIOUS_DEPLOYMENT:-}"

fail=0

pass() {
    printf 'PASS: %s\n' "$1"
}

fail_check() {
    printf 'FAIL: %s\n' "$1" >&2
    fail=1
}

run_check() {
    local label="$1"
    shift
    if "$@"; then
        pass "$label"
    else
        fail_check "$label"
    fi
}

if [[ "$mode" != "check" && "$mode" != "prepare-reboot" && "$mode" != "verify-reboot" && "$mode" != "prepare-switch" && "$mode" != "verify-switch" && "$mode" != "prepare-recovery" && "$mode" != "verify-recovery" ]]; then
    echo "Usage: $0 [check|prepare-reboot|verify-reboot|prepare-switch|verify-switch|prepare-recovery|verify-recovery]" >&2
    exit 2
fi

if bash "$script_dir/boot-check.sh"; then
    pass "base boot checks"
else
    fail_check "base boot checks"
fi

status_file="$(mktemp)"
rk_file="$(mktemp)"
trap 'rm -f "$status_file" "$rk_file"' EXIT

if bootc status --format json --format-version 1 >"$status_file"; then
    pass "bootc status JSON"
else
    fail_check "bootc status JSON"
fi

if [[ -n "$expected_image" ]]; then
    if python3 "$script_dir/release-state.py" image "$status_file" "$expected_image"; then
        pass "expected image is the booted deployment"
    else
        fail_check "expected image is the booted deployment"
    fi
fi

run_check "SELinux enforcing" bash -c 'getenforce | grep -qx Enforcing'
run_check "kernel cmdline keeps SELinux enabled" bash -c '! grep -Eq "(^|[[:space:]])(selinux=0|enforcing=0)([[:space:]]|$)" /proc/cmdline'
run_check "hardening: kernel.kptr_restrict" bash -c 'test "$(sysctl -n kernel.kptr_restrict)" = 2'
run_check "hardening: fs.protected_regular" bash -c 'test "$(sysctl -n fs.protected_regular)" = 2'
run_check "hardening: fs.protected_fifos" bash -c 'test "$(sysctl -n fs.protected_fifos)" = 2'
run_check "hardening: fs.suid_dumpable" bash -c 'test "$(sysctl -n fs.suid_dumpable)" = 0'

run_check "krisCC installed" rpm -q krisCC
run_check "krisCC files verify" rpm -V --nomtime krisCC
run_check "krisCC executable" test -x /usr/bin/krisCC
run_check "krisCC owned by immutable image" grep -Fxq krisCC /usr/share/krisos/owned-packages.txt
run_check "ISO Image Writer installed" rpm -q isoimagewriter
run_check "ISO Image Writer executable" test -x /usr/bin/isoimagewriter
run_check "Gwenview removed from immutable image" bash -c '! rpm -q gwenview >/dev/null 2>&1'
run_check "Plasma Discover installed" rpm -q plasma-discover
run_check "Plasma Discover Flatpak backend installed" rpm -q plasma-discover-flatpak
run_check "Discover notifier omitted" bash -c '! rpm -q plasma-discover-notifier >/dev/null 2>&1'
run_check "Discover PackageKit backend omitted" bash -c '! rpm -q plasma-discover-packagekit >/dev/null 2>&1'
run_check "PackageKit omitted" bash -c '! rpm -q PackageKit >/dev/null 2>&1'
run_check "Cockpit installed" rpm -q cockpit
run_check "Cockpit socket disabled by default" bash -c 'systemctl is-enabled cockpit.socket 2>&1 | grep -qx disabled'
run_check "DNF weak dependencies disabled" grep -Fxq 'install_weak_deps=False' /etc/dnf/libdnf5.conf.d/90-krisos.conf

run_check "useradd default points to /var/home" grep -Fxq 'HOME=/var/home' /etc/default/useradd
run_check "SELinux /var/home user context" bash -c "matchpathcon -n /var/home/kris | grep -q ':user_home_dir_t:'"
run_check "SELinux config context below /var/home" bash -c "matchpathcon -n /var/home/kris/.config | grep -q ':config_home_t:'"
run_check "SELinux data context below /var/home" bash -c "matchpathcon -n /var/home/kris/.local/share | grep -q ':data_home_t:'"

kernel_image="/usr/lib/modules/$(uname -r)/initramfs.img"
run_check "canonical initramfs present" test -s "$kernel_image"
run_check "AMD early microcode embedded" bash -c "lsinitrd '$kernel_image' | grep -F 'kernel/x86/microcode/AuthenticAMD.bin' >/dev/null"

expected_admin_user="${KRISOS_EXPECT_ADMIN_USER:-}"
if [[ -n "$expected_admin_user" ]]; then
    run_check "expected admin user exists" getent passwd "$expected_admin_user"
    run_check "expected admin user is in wheel" bash -c "id -nG '$expected_admin_user' | tr ' ' '\n' | grep -qx wheel"
    admin_home="$(getent passwd "$expected_admin_user" | cut -d: -f6)"
    if [[ -n "$admin_home" ]]; then
        run_check "admin home resolves below /var/home" bash -c 'test "$(readlink -f -- "$1")" = "$2"' _ "$admin_home" "/var/home/$expected_admin_user"
        run_check "admin home SELinux label" bash -c "ls -Zd '/var/home/$expected_admin_user' | grep -q ':user_home_dir_t:'"
    fi
fi

actual_kriscc="$(rpm -q --qf '%{VERSION}-%{RELEASE}.%{ARCH}' krisCC 2>/dev/null || true)"
if [[ -n "$expected_kriscc" ]]; then
    if [[ "$actual_kriscc" == "$expected_kriscc" ]]; then
        pass "expected krisCC NEVRA"
    else
        printf 'Expected krisCC %s, found %s\n' "$expected_kriscc" "${actual_kriscc:-missing}" >&2
        fail_check "expected krisCC NEVRA"
    fi
fi

owned_nevra_line="$(rpm -q --qf '%{NAME}\t%{EPOCHNUM}:%{VERSION}-%{RELEASE}.%{ARCH}' krisCC 2>/dev/null || true)"
if [[ -n "$owned_nevra_line" ]] && grep -Fxq "$owned_nevra_line" /usr/share/krisos/owned-nevra.txt; then
    pass "krisCC NEVRA matches immutable ownership snapshot"
else
    fail_check "krisCC NEVRA matches immutable ownership snapshot"
fi

run_check "krisos-sync timer enabled" bash -c 'systemctl is-enabled krisos-sync.timer | grep -qx enabled'
run_check "krisos-sync timer active" bash -c 'systemctl is-active krisos-sync.timer | grep -qx active'

if /usr/bin/rk status --json >"$rk_file" 2>&1 && python3 "$script_dir/release-state.py" rk "$rk_file"; then
    pass "rk overlay ready and recovery complete"
else
    cat "$rk_file" >&2 || true
    fail_check "rk overlay ready and recovery complete"
fi

run_check "krisCC offscreen smoke" timeout 20s env     QT_QPA_PLATFORM=offscreen     QT_QUICK_BACKEND=software     QT_QUICK_CONTROLS_STYLE=Basic     KRISCC_SMOKE_TEST=1     /usr/bin/krisCC --background

require_sentinel_context() {
    if [[ $EUID -ne 0 ]]; then
        echo "$mode must run as root" >&2
        exit 2
    fi
    if [[ -z "$token" || ! "$token" =~ ^[A-Za-z0-9._-]+$ ]]; then
        echo "KRISOS_E2E_TOKEN must contain only A-Z, a-z, 0-9, dot, underscore or dash" >&2
        exit 2
    fi
}

prepare_overlay_sentinel() {
    require_sentinel_context
    install -d -m 0755 "$sentinel_dir"
    printf '%s\n' "$token" > "$sentinel"
    chmod 0644 "$sentinel"
    if [[ ! -f "$upper_sentinel" ]] || ! grep -Fxq "$token" "$upper_sentinel"; then
        echo "Sentinel did not materialize in KrisOS upperdir: $upper_sentinel" >&2
        exit 1
    fi
    sync -f "$sentinel"
    sync -f "$upper_sentinel"
    pass "sentinel materialized in the persistent KrisOS upperdir"
}

case "$mode" in
    prepare-reboot|prepare-switch)
        prepare_overlay_sentinel
        ;;
    prepare-recovery)
        prepare_overlay_sentinel
        printf '%s\n' 'Simulated interrupted transaction for disposable VM recovery gate' > /var/lib/krisos/pending
        chmod 0600 /var/lib/krisos/pending
        sync -f /var/lib/krisos/pending
        pass "pending recovery marker armed"
        ;;
    verify-reboot)
        require_sentinel_context
        if [[ -f "$sentinel" ]] && grep -Fxq "$token" "$sentinel" && \
                [[ -f "$upper_sentinel" ]] && grep -Fxq "$token" "$upper_sentinel"; then
            pass "KrisOS upperdir persisted across same-deployment reboot"
            # Remove through the mounted view; never mutate an active OverlayFS
            # upperdir directly. For an upper-only file this must unlink the
            # physical upper entry as well.
            rm -f "$sentinel"
            if [[ ! -e "$upper_sentinel" ]]; then
                pass "overlay sentinel cleanup removed the physical upper entry"
            else
                fail_check "overlay sentinel cleanup removed the physical upper entry"
            fi
            rmdir "$sentinel_dir" 2>/dev/null || true
        else
            fail_check "KrisOS upperdir persistence across same-deployment reboot"
        fi
        ;;
    verify-switch)
        require_sentinel_context
        if [[ -z "$previous_deployment" ]]; then
            echo "KRISOS_E2E_PREVIOUS_DEPLOYMENT is required for verify-switch" >&2
            exit 2
        fi
        current_deployment="$(cat /var/lib/krisos/deployment 2>/dev/null || true)"
        if [[ -n "$current_deployment" && "$current_deployment" != "$previous_deployment" ]]; then
            pass "deployment identity changed"
        else
            fail_check "deployment identity changed"
        fi
        if [[ ! -e "$sentinel" && ! -e "$upper_sentinel" ]]; then
            pass "old upperdir content was discarded on deployment change"
        else
            fail_check "old upperdir content was discarded on deployment change"
        fi
        ;;
    verify-recovery)
        require_sentinel_context
        if [[ -e /var/lib/krisos/pending || -e /var/lib/krisos/needs-sync ]]; then
            fail_check "interrupted transaction recovery markers cleared"
        else
            pass "interrupted transaction recovery markers cleared"
        fi
        if [[ ! -e "$sentinel" && ! -e "$upper_sentinel" ]]; then
            pass "interrupted transaction discarded the old upperdir"
        else
            fail_check "interrupted transaction discarded the old upperdir"
        fi
        ;;
esac

echo
if [[ "$fail" -eq 0 ]]; then
    echo "KRISOS RELEASE CHECKS PASSED"
else
    echo "KRISOS RELEASE CHECKS FAILED"
fi
exit "$fail"
