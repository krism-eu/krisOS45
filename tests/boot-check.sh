#!/bin/bash
# Post-boot smoke test for KrisOS M1. Run on the booted system.
set -u

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fail=0
recovery=0
cmdline=""
deploy_path=""
IFS= read -r cmdline < /proc/cmdline || true
read -r -a tokens <<< "$cmdline"
for token in "${tokens[@]}"; do
    [ "$token" != "krisos.overlay=off" ] || recovery=1
    case "$token" in
        ostree=*) deploy_path="${token#ostree=}" ;;
    esac
done

# /proc/cmdline può conservare una coppia bilanciata di virgolette
# attorno al valore ostree=. Normalizza come krisos-overlay.
if [[ "$deploy_path" == \"*\" ]]; then
    deploy_path="${deploy_path#\"}"
    deploy_path="${deploy_path%\"}"
fi

ostree_contract=0
if [[ "$deploy_path" =~ ^/ostree/boot\.[01]/[^/[:space:]]+/[0-9a-f]+/[0-9]+$ ]]; then
    ostree_contract=1
fi

check() {
    if eval "$2"; then
        echo "PASS: $1"
    else
        echo "FAIL: $1"
        fail=1
    fi
}

check "OSTree backend contract"  "grep -Eq '(^|[[:space:]])ostree=/ostree/boot\.[01]/[^/[:space:]]+/[0-9a-f]+/[0-9]+([[:space:]]|$)' /proc/cmdline"
check "systemd-homed disabled"    "! systemctl is-enabled systemd-homed.service >/dev/null 2>&1"
check "systemd-homed inactive"    "! systemctl is-active systemd-homed.service >/dev/null 2>&1"
if [ "$recovery" -eq 1 ]; then
    check "recovery: /usr overlay absent" "command -v findmnt >/dev/null && ! findmnt -rn -M /usr -o FSTYPE | grep -qx overlay"
    check "SELinux enforcing" "getenforce | grep -qx Enforcing"
    check "login manager active" "systemctl is-active plasmalogin.service | grep -qx active"
    if [ "$fail" -ne 0 ]; then
        echo "RECOVERY CHECKS FAILED"
        exit 1
    fi
    echo "RECOVERY BOOT VERIFIED: overlay intentionally disabled; normal overlay checks skipped"
    exit 2
fi

expected_deployment=""
if [ -n "$deploy_path" ]; then
    target="$(readlink -- "$deploy_path" 2>/dev/null || true)"
    target="${target%/}"
    basename="${target##*/}"
    rest="${deploy_path#/ostree/}"
    rest="${rest#*/}"
    stateroot="${rest%%/*}"
    commit="${basename%.*}"
    deployserial="${basename##*.}"
    if [[ "$commit" =~ ^[0-9a-f]{64}$ ]] && [[ "$deployserial" =~ ^[0-9]+$ ]]; then
        expected_deployment="$stateroot/$commit/$deployserial"
    fi
fi

check "/usr dedicated overlay"    "test \"$(findmnt -T /usr -n -o TARGET)\" = /usr && test \"$(findmnt -T /usr -n -o FSTYPE)\" = overlay"
check "overlay service active"    "systemctl is-active krisos-overlay.service | grep -qx active"
check "deployment recorded"       "test -s /var/lib/krisos/deployment"
check "deployment identity matches OSTree bootlink" "test -n \"$expected_deployment\" && grep -Fxq \"$expected_deployment\" /var/lib/krisos/deployment"
status_file="$(mktemp)"
if bootc status --format json --format-version 1 > "$status_file" 2>/dev/null; then
    check "deployment identity matches independent bootc status" "python3 '$script_dir/release-state.py' deployment '$status_file' '$expected_deployment'"
else
    echo "FAIL: bootc status JSON for deployment cross-check"
    fail=1
fi
rm -f "$status_file"
check "overlay upper present"     "test -d /var/lib/krisos/upper"
check "overlay work present"      "test -d /var/lib/krisos/work"
check "package intent seed"       "test -e /var/lib/krisos/packages.list"
check "SELinux enforcing"         "getenforce | grep -qx Enforcing"
check "overlay root labeled usr_t" "ls -Zd /usr | grep -q 'object_r:usr_t:'"
check "login manager active"      "systemctl is-active plasmalogin.service | grep -qx active"

echo
if [ "$fail" -eq 0 ]; then
    echo "ALL CHECKS PASSED"
else
    echo "SOME CHECKS FAILED"
fi
exit "$fail"
