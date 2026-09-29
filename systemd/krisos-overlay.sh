#!/bin/bash
# krisos-overlay — early userspace persistent /usr overlay.
#
# Runs after ostree-remount.service and before local-fs.target. At this point
# the booted deployment is active, /var is writable, and normal services have
# not started yet. Any failure falls back to the immutable /usr and returns
# success so the machine remains bootable.

set -u

log() {
    echo "krisos-overlay: $*"
}

cmdline=""
IFS= read -r cmdline < /proc/cmdline || true

# Split whitespace once, without pathname expansion; retain the final token.
read -r -a cmdline_tokens <<< "$cmdline"
for tok in "${cmdline_tokens[@]}"; do
    if [ "$tok" = "krisos.overlay=off" ]; then
        log "disabled via karg — skipping"
        exit 0
    fi
done

deploy_path=""
for tok in "${cmdline_tokens[@]}"; do
    case "$tok" in
        ostree=*) deploy_path="${tok#ostree=}" ;;
    esac
done

if [ -z "$deploy_path" ]; then
    log "no ostree= parameter in cmdline — skipping"
    exit 0
fi

# /ostree/boot.BOOTVERSION/OSNAME/BOOTCSUM/TREEBOOTSERIAL
case "$deploy_path" in
    /ostree/boot.[01]/*/*/*) ;;
    *)
        log "unsupported ostree= path '$deploy_path' — skipping"
        exit 0
        ;;
esac

rest="${deploy_path#/ostree/}"
boot_generation="${rest%%/*}"
rest="${rest#*/}"
stateroot="${rest%%/*}"
rest="${rest#*/}"
bootcsum="${rest%%/*}"
treebootserial="${rest#*/}"

case "$boot_generation" in
    boot.0|boot.1) ;;
    *) log "invalid boot generation — skipping"; exit 0 ;;
esac
case "$stateroot" in
    ""|.|..|*[!A-Za-z0-9._-]*) log "invalid stateroot — skipping"; exit 0 ;;
esac
case "$bootcsum" in
    ""|*[!0-9a-f]*) log "invalid boot checksum — skipping"; exit 0 ;;
esac
case "$treebootserial" in
    ""|*[!0-9]*) log "invalid tree boot serial — skipping"; exit 0 ;;
esac
# The digit-only check above also excludes path separators.

# The ostree= boot checksum identifies boot artifacts, not the complete
# deployment tree. Two images can therefore share BOOTCSUM while /usr differs.
# libostree resolves the bootlink symlink and parses its target basename as
# CHECKSUM.DEPLOYSERIAL; mirror that here so any immutable tree change invalidates
# our disposable /usr cache.
deployment_target=""
if ! deployment_target="$(readlink -- "$deploy_path" 2>/dev/null)"; then
    log "cannot resolve OSTree bootlink '$deploy_path' — skipping"
    exit 0
fi
deployment_target="${deployment_target%/}"
deploy_basename="${deployment_target##*/}"
case "$deploy_basename" in
    *.*) ;;
    *) log "invalid OSTree deployment target '$deployment_target' — skipping"; exit 0 ;;
esac
commit="${deploy_basename%.*}"
deployserial="${deploy_basename##*.}"
case "$commit" in
    ""|*[!0-9a-f]*) log "invalid deployment checksum — skipping"; exit 0 ;;
esac
if [ "${#commit}" -ne 64 ]; then
    log "invalid deployment checksum length — skipping"
    exit 0
fi
case "$deployserial" in
    ""|*[!0-9]*) log "invalid deploy serial — skipping"; exit 0 ;;
esac

deployment_id="$stateroot/$commit/$deployserial"

state=/var/lib/krisos
upper="$state/upper"
work="$state/work"
saved="$state/deployment"
needs_sync="$state/needs-sync"
runtime=/run/krisos
overlay_ready="$runtime/overlay-mounted"

already_mounted=0
foreign_overlay=0
while read -r _source target fstype options _rest; do
    if [ "$target" != "/usr" ] || [ "$fstype" != "overlay" ]; then
        continue
    fi
    upper_ok=0
    work_ok=0
    case ",$options," in *",upperdir=$upper,"*) upper_ok=1 ;; esac
    case ",$options," in *",workdir=$work,"*) work_ok=1 ;; esac
    if [ "$upper_ok" -eq 1 ] && [ "$work_ok" -eq 1 ]; then
        already_mounted=1
    else
        foreign_overlay=1
    fi
    break
done < /proc/mounts

if [ "$already_mounted" -eq 1 ]; then
    # A valid KrisOS overlay may already exist if this oneshot is started again
    # manually in the same boot. Republish volatile readiness so conditional
    # recovery remains coherent instead of silently disabling krisos-sync.
    if [ ! -d "$runtime" ] && ! mkdir -p "$runtime"; then
        log "WARNING: KrisOS overlay already mounted, but runtime readiness directory cannot be created"
        exit 0
    fi
    if ! : > "$overlay_ready"; then
        log "WARNING: KrisOS overlay already mounted, but readiness marker cannot be published"
    fi
    log "KrisOS overlay already mounted"
    exit 0
fi
if [ "$foreign_overlay" -eq 1 ]; then
    log "WARNING: unexpected overlay is already mounted on /usr — leaving it untouched; KrisOS sync disabled"
    exit 0
fi
# needs-sync is persistent package-recovery intent. overlay-mounted is volatile
# proof that this boot actually reached a writable /usr overlay.

if ! mkdir -p "$state"; then
    log "WARNING: cannot create state directory — continuing on base /usr"
    exit 0
fi
if ! mkdir -p "$runtime"; then
    log "WARNING: cannot create runtime state — continuing on base /usr"
    exit 0
fi

wipe_cache() {
    reason="$1"
    log "$reason — wiping overlay cache"

    if ! rm -rf -- "$upper" "$work"; then
        log "WARNING: cache wipe failed — continuing on base /usr"
        return 1
    fi
    if ! mkdir -p "$upper" "$work"; then
        log "WARNING: cache recreation failed — continuing on base /usr"
        return 1
    fi
    return 0
}

saved_id=""
if [ -f "$saved" ]; then
    IFS= read -r saved_id < "$saved" || saved_id=""
fi

changed=0
pending_recovery=0
if [ -f "$state/pending" ]; then
    changed=1
    pending_recovery=1
    if ! wipe_cache "interrupted package transaction"; then
        exit 0
    fi
elif [ -z "$saved_id" ]; then
    changed=1
    if ! wipe_cache "deployment identity not initialized"; then
        exit 0
    fi
elif [ "$saved_id" != "$deployment_id" ]; then
    changed=1
    if ! wipe_cache "deployment changed"; then
        exit 0
    fi
elif [ ! -d "$upper" ] || [ ! -d "$work" ]; then
    # The saved deployment alone is not enough to prove the cache is intact.
    # If either OverlayFS directory vanished or became a non-directory, rebuild
    # both and reconcile persisted package intent exactly like a deployment change.
    changed=1
    if ! wipe_cache "overlay cache missing or invalid"; then
        exit 0
    fi
else
    : # same deployment and both cache directories are present
fi

if [ "$changed" -eq 1 ]; then
    # Recovery intent must become durable before an interrupted marker is
    # cleared and before a new deployment identity can ever be recorded.
    if ! : > "$needs_sync"; then
        log "WARNING: cannot create needs-sync marker — continuing on base /usr"
        exit 0
    fi
    if [ "$pending_recovery" -eq 1 ] && ! rm -f -- "$state/pending"; then
        log "WARNING: cannot clear pending transaction marker — continuing on base /usr"
        exit 0
    fi
    # Establish an ordering barrier: a power loss must not make the future
    # deployment identity durable while an old upper/work cache can reappear.
    if ! /usr/bin/sync -f "$state"; then
        log "WARNING: cannot persist overlay reset state — continuing on base /usr"
        exit 0
    fi
fi

# OverlayFS exposes the upper root inode as the merged /usr root. Copy the
# immutable /usr SELinux label onto that inode before mounting. Do not recurse:
# payload labels are created through their logical /usr paths.
if ! chcon --reference=/usr "$upper"; then
    log "WARNING: cannot label overlay root — continuing on base /usr (degraded)"
    exit 0
fi

log "mounting persistent overlay on /usr"
if ! mount -t overlay overlay \
        -o "lowerdir=/usr,upperdir=$upper,workdir=$work" \
        /usr; then
    log "WARNING: overlay mount failed — continuing on base /usr (degraded)"
    exit 0
fi

# From here on, avoid spawning helpers from the freshly overlaid /usr. Shell
# builtins are enough to publish readiness, record state and finish safely.
if ! : > "$overlay_ready"; then
    log "WARNING: overlay mounted, but readiness marker could not be created; automatic sync disabled for this boot"
fi
if ! printf '%s\n' "$deployment_id" > "$saved"; then
    log "WARNING: mounted, but deployment identity could not be persisted"
fi

log "mounted for $deployment_id"
exit 0
