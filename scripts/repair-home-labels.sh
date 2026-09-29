#!/usr/bin/env bash
# Preview or repair the four persistent paths confirmed by the boot audit.
set -euo pipefail
apply=false
if [[ ${1:-} == --apply ]]; then apply=true; shift; fi
[[ $# == 1 ]] || { echo "Usage: $0 [--apply] USER" >&2; exit 2; }
[[ $EUID == 0 ]] || { echo 'Run as root to inspect/repair SELinux labels.' >&2; exit 1; }
user=$1
record="$(getent passwd "$user")"
IFS=: read -r name _ uid _ _ user_home _ <<< "$record"
[[ $name == "$user" && $uid != 0 ]] || { echo 'Expected a non-root user.' >&2; exit 1; }
resolved="$(realpath -e -- "$user_home")"
[[ $resolved == /var/home/* && ${resolved#/var/home/} != */* ]] || {
    echo 'Home must resolve to a direct child of /var/home.' >&2; exit 1;
}
args=(-v)
$apply || args+=(-n)
for path in "$resolved" "$resolved/.config" "$resolved/.local" "$resolved/.local/share"; do
    [[ -d $path && ! -L $path ]] || continue
    [[ $(realpath -e -- "$path") == "$path" ]] || continue
    restorecon "${args[@]}" -- "$path"
done
