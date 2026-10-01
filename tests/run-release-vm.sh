#!/usr/bin/bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
target="${KRISOS_E2E_TARGET:?Set KRISOS_E2E_TARGET, for example qa@192.0.2.10}"
expected_kriscc="${KRISOS_EXPECT_KRISCC:-}"
expected_image="${KRISOS_EXPECT_IMAGE:-}"
expected_admin_user="${KRISOS_EXPECT_ADMIN_USER:-}"
switch_image="${KRISOS_E2E_SWITCH_IMAGE:-}"
rk_package="${KRISOS_E2E_RK_PACKAGE:-tree}"
token="${KRISOS_E2E_TOKEN:-krisos-e2e-$(date +%s)-$$}"
remote_dir="/tmp/krisos-release-e2e"
ssh_opts=(-o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=8)

validate_simple() {
    local name="$1"
    local value="$2"
    local pattern="$3"
    if [[ -n "$value" && ! "$value" =~ $pattern ]]; then
        echo "Unsafe $name value: $value" >&2
        exit 2
    fi
}

validate_simple "KRISOS_EXPECT_ADMIN_USER" "$expected_admin_user" '^[A-Za-z_][A-Za-z0-9_.-]*[$]?$'
validate_simple "KRISOS_EXPECT_KRISCC" "$expected_kriscc" '^[A-Za-z0-9._+:-]+$'
validate_simple "KRISOS_EXPECT_IMAGE" "$expected_image" '^[A-Za-z0-9._/@:+-]+$'
validate_simple "KRISOS_E2E_SWITCH_IMAGE" "$switch_image" '^[A-Za-z0-9._/@:+-]+$'
validate_simple "KRISOS_E2E_RK_PACKAGE" "$rk_package" '^[A-Za-z0-9][A-Za-z0-9+_.-]{0,127}$'
validate_simple "KRISOS_E2E_TOKEN" "$token" '^[A-Za-z0-9._-]+$'

upload_checks() {
    tar -C "$repo_root/tests" -cf - boot-check.sh release-check.sh release-state.py |
        ssh "${ssh_opts[@]}" "$target"             "rm -rf '$remote_dir' && mkdir -p '$remote_dir' && tar -C '$remote_dir' -xf - && chmod 0755 '$remote_dir/'*.sh"
}

run_release_check() {
    local mode="$1"
    local image="${2-$expected_image}"
    local previous_deployment="${3-}"
    ssh "${ssh_opts[@]}" "$target" \
        "sudo env KRISOS_EXPECT_KRISCC='$expected_kriscc' KRISOS_EXPECT_IMAGE='$image' KRISOS_E2E_TOKEN='$token' KRISOS_EXPECT_ADMIN_USER='$expected_admin_user' KRISOS_E2E_PREVIOUS_DEPLOYMENT='$previous_deployment' '$remote_dir/release-check.sh' '$mode'"
}

wait_for_new_boot() {
    local old_boot_id="$1"
    local new_boot_id=""
    for _ in $(seq 1 60); do
        sleep 5
        new_boot_id="$(ssh "${ssh_opts[@]}" "$target" 'cat /proc/sys/kernel/random/boot_id' 2>/dev/null || true)"
        if [[ -n "$new_boot_id" && "$new_boot_id" != "$old_boot_id" ]]; then
            printf 'Observed new boot id: %s\n' "$new_boot_id"
            return 0
        fi
    done
    echo "VM did not return with a new boot id within 300 seconds." >&2
    return 1
}

reboot_and_wait() {
    local old_boot_id
    old_boot_id="$(ssh "${ssh_opts[@]}" "$target" 'cat /proc/sys/kernel/random/boot_id')"
    ssh "${ssh_opts[@]}" "$target" 'sudo systemctl reboot' || true
    wait_for_new_boot "$old_boot_id"
    upload_checks
}

wait_for_rk_recovery() {
    for _ in $(seq 1 120); do
        if ssh "${ssh_opts[@]}" "$target" \
                'test ! -e /var/lib/krisos/pending && test ! -e /var/lib/krisos/needs-sync' \
                >/dev/null 2>&1; then
            echo "RK recovery markers are clear"
            return 0
        fi
        sleep 5
    done
    echo "RK recovery did not clear pending/needs-sync within 600 seconds." >&2
    ssh "${ssh_opts[@]}" "$target" \
        'systemctl status --no-pager krisos-sync.timer krisos-sync.service || true; /usr/bin/rk status || true' >&2 || true
    return 1
}

assert_fixture_absent() {
    if ssh "${ssh_opts[@]}" "$target" "rpm -q '$rk_package' >/dev/null 2>&1 || grep -Fxq '$rk_package' /var/lib/krisos/packages.list 2>/dev/null"; then
        echo "RK VM fixture must be absent before the gate starts: $rk_package" >&2
        echo "Choose another signed Fedora package with KRISOS_E2E_RK_PACKAGE." >&2
        return 1
    fi
}

verify_rk_package_present() {
    ssh "${ssh_opts[@]}" "$target" \
        "rpm -q '$rk_package' >/dev/null && grep -Fxq '$rk_package' /var/lib/krisos/packages.list && sudo /usr/bin/rk status --json | python3 -m json.tool >/dev/null"
}

verify_rk_package_absent() {
    ssh "${ssh_opts[@]}" "$target" \
        "! rpm -q '$rk_package' >/dev/null 2>&1 && ! grep -Fxq '$rk_package' /var/lib/krisos/packages.list 2>/dev/null"
}

rk_add_fixture() {
    echo "Executing real rk add transaction for signed Fedora fixture: $rk_package"
    ssh "${ssh_opts[@]}" "$target" "sudo /usr/bin/rk add '$rk_package'"
    verify_rk_package_present
}

rk_remove_fixture() {
    echo "Executing real rk rm transaction for fixture: $rk_package"
    ssh "${ssh_opts[@]}" "$target" "sudo /usr/bin/rk rm '$rk_package'"
    verify_rk_package_absent
}

upload_checks
assert_fixture_absent

if [[ -n "$switch_image" ]]; then
    # Seed real package intent on the old deployment. The candidate must rebuild
    # its upper/rpmdb from this intent after bootc switch.
    rk_add_fixture

    echo "Preparing real upperdir sentinel before deployment switch"
    run_release_check check ""
    old_deployment="$(ssh "${ssh_opts[@]}" "$target" 'cat /var/lib/krisos/deployment')"
    [[ "$old_deployment" =~ ^[A-Za-z0-9._-]+/[0-9a-f]{64}/[0-9]+$ ]] || {
        echo "Unexpected current deployment identity: $old_deployment" >&2
        exit 1
    }
    run_release_check prepare-switch ""
    echo "Switching VM to immutable candidate: $switch_image"
    ssh "${ssh_opts[@]}" "$target" "sudo bootc switch '$switch_image'"
    reboot_and_wait
    wait_for_rk_recovery
    run_release_check verify-switch "$expected_image" "$old_deployment"
    verify_rk_package_present

    # Now exercise both mutation paths using the candidate's own rk binary.
    rk_remove_fixture
    rk_add_fixture

    echo "Rebuilding the persistent SELinux policy store after the deployment change"
    ssh "${ssh_opts[@]}" "$target" 'sudo semodule -B'
else
    echo "NOTE: KRISOS_E2E_SWITCH_IMAGE is unset; deployment-change resync is not exercised." >&2
    rk_add_fixture
fi

run_release_check check
run_release_check prepare-reboot
reboot_and_wait
run_release_check verify-reboot
verify_rk_package_present

# Removal must also survive a reboot; otherwise rpmdb/intent durability is not proven.
rk_remove_fixture
reboot_and_wait
run_release_check check
verify_rk_package_absent

echo "Exercising interrupted-transaction recovery on the current deployment"
run_release_check prepare-recovery
reboot_and_wait
wait_for_rk_recovery
run_release_check verify-recovery

echo "KrisOS VM release validation passed for $target (real rk add/rm fixture: $rk_package)"
