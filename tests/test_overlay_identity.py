#!/usr/bin/python3
"""Verify overlay invalidation keys off the real OSTree deployment commit."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "systemd/krisos-overlay.sh"
BOOTCSUM = "b" * 64
OLD_COMMIT = "a" * 64
NEW_COMMIT = "c" * 64


class OverlayIdentity(unittest.TestCase):
    def prepare(self, saved_commit, target_commit, deployserial="0", chcon_status=0, mount_status=0, mounts_text="", pending=False, missing_upper=False, missing_work=False):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)

        ostree = root / "ostree"
        bootlink = ostree / "boot.0" / "default" / BOOTCSUM / "0"
        bootlink.parent.mkdir(parents=True)
        bootlink.symlink_to(f"../../../../deploy/default/deploy/{target_commit}.{deployserial}")

        cmdline = root / "cmdline"
        cmdline.write_text(f"quiet ostree={bootlink}\n")
        mounts = root / "mounts"

        state = root / "state"
        upper = state / "upper"
        work = state / "work"
        if not missing_upper:
            upper.mkdir(parents=True)
        if not missing_work:
            work.mkdir(parents=True)
        sentinel = upper / "sentinel"
        if upper.is_dir():
            sentinel.write_text("keep-or-wipe")
        mounts.write_text(mounts_text.format(upper=upper, work=work))
        (state / "deployment").write_text(f"default/{saved_commit}/0\n")
        if pending:
            (state / "pending").write_text("interrupted\n")
        runtime = root / "run" / "krisos"

        bindir = root / "bin"
        bindir.mkdir()
        for name, status in (("chcon", chcon_status), ("mount", mount_status)):
            stub = bindir / name
            stub.write_text(f"#!/bin/sh\nexit {status}\n")
            stub.chmod(0o755)

        hook = root / "hook.sh"
        text = SOURCE.read_text()
        text = text.replace("/proc/cmdline", str(cmdline))
        text = text.replace("/proc/mounts", str(mounts))
        text = text.replace("/ostree/", str(ostree) + "/")
        text = text.replace("state=/var/lib/krisos", f"state={state}")
        text = text.replace("runtime=/run/krisos", f"runtime={runtime}")
        hook.write_text(text)
        hook.chmod(0o755)

        env = dict(os.environ)
        env["PATH"] = f"{bindir}:/usr/bin:/bin"
        result = subprocess.run(
            ["/bin/bash", str(hook)], env=env, text=True, capture_output=True
        )
        return result, state, sentinel, runtime

    def test_same_boot_checksum_new_commit_wipes_cache(self):
        result, state, sentinel, runtime = self.prepare(OLD_COMMIT, NEW_COMMIT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("deployment changed — wiping overlay cache", result.stdout)
        self.assertFalse(sentinel.exists())
        self.assertTrue((state / "needs-sync").exists())
        self.assertTrue((runtime / "overlay-mounted").exists())
        self.assertEqual(
            (state / "deployment").read_text().strip(), f"default/{NEW_COMMIT}/0"
        )

    def test_same_deployment_preserves_cache(self):
        result, state, sentinel, runtime = self.prepare(NEW_COMMIT, NEW_COMMIT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("wiping overlay cache", result.stdout)
        self.assertTrue(sentinel.exists())
        self.assertFalse((state / "needs-sync").exists())
        self.assertTrue((runtime / "overlay-mounted").exists())
        self.assertEqual(
            (state / "deployment").read_text().strip(), f"default/{NEW_COMMIT}/0"
        )


    def test_same_deployment_missing_upper_rebuilds_cache_and_arms_sync(self):
        result, state, sentinel, runtime = self.prepare(NEW_COMMIT, NEW_COMMIT, missing_upper=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("overlay cache missing or invalid — wiping overlay cache", result.stdout)
        self.assertFalse(sentinel.exists())
        self.assertTrue((state / "upper").is_dir())
        self.assertTrue((state / "work").is_dir())
        self.assertTrue((state / "needs-sync").exists())
        self.assertTrue((runtime / "overlay-mounted").exists())

    def test_same_deployment_missing_work_rebuilds_cache_and_arms_sync(self):
        result, state, sentinel, runtime = self.prepare(NEW_COMMIT, NEW_COMMIT, missing_work=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("overlay cache missing or invalid — wiping overlay cache", result.stdout)
        self.assertFalse(sentinel.exists())
        self.assertTrue((state / "upper").is_dir())
        self.assertTrue((state / "work").is_dir())
        self.assertTrue((state / "needs-sync").exists())
        self.assertTrue((runtime / "overlay-mounted").exists())

    def test_existing_valid_krisos_overlay_republishes_readiness(self):
        mounts = "overlay /usr overlay rw,relatime,lowerdir=/usr,upperdir={upper},workdir={work} 0 0\n"
        result, state, sentinel, runtime = self.prepare(NEW_COMMIT, NEW_COMMIT, mounts_text=mounts)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("KrisOS overlay already mounted", result.stdout)
        self.assertTrue(sentinel.exists())
        self.assertTrue((runtime / "overlay-mounted").exists())

    def test_identity_uses_deploy_serial_from_bootlink_target(self):
        result, state, _, runtime = self.prepare(OLD_COMMIT, NEW_COMMIT, deployserial="7")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((runtime / "overlay-mounted").exists())
        self.assertEqual(
            (state / "deployment").read_text().strip(), f"default/{NEW_COMMIT}/7"
        )


    def test_pending_recovery_wipes_cache_and_clears_pending(self):
        result, state, sentinel, runtime = self.prepare(NEW_COMMIT, NEW_COMMIT, pending=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("interrupted package transaction — wiping overlay cache", result.stdout)
        self.assertFalse(sentinel.exists())
        self.assertFalse((state / "pending").exists())
        self.assertTrue((state / "needs-sync").exists())
        self.assertTrue((runtime / "overlay-mounted").exists())

    def test_foreign_usr_overlay_is_not_mistaken_for_krisos_overlay(self):
        foreign = "overlay /usr overlay rw,relatime,lowerdir=/usr,upperdir=/tmp/foreign-upper,workdir=/tmp/foreign-work 0 0\n"
        result, state, sentinel, runtime = self.prepare(NEW_COMMIT, NEW_COMMIT, mounts_text=foreign)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("unexpected overlay is already mounted on /usr", result.stdout)
        self.assertTrue(sentinel.exists())
        self.assertFalse(runtime.exists())

    def test_changed_deployment_has_persistence_barrier_before_mount(self):
        text = SOURCE.read_text()
        sync_index = text.index('/usr/bin/sync -f "$state"')
        mount_index = text.index('mount -t overlay overlay')
        identity_index = text.index("printf '%s\\n' \"$deployment_id\" > \"$saved\"")
        self.assertLess(sync_index, mount_index)
        self.assertLess(mount_index, identity_index)

    def test_chcon_failure_keeps_recovery_intent_but_not_ready_marker(self):
        result, state, _, runtime = self.prepare(OLD_COMMIT, NEW_COMMIT, chcon_status=1)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("cannot label overlay root", result.stdout)
        self.assertTrue((state / "needs-sync").exists())
        self.assertFalse((runtime / "overlay-mounted").exists())
        self.assertEqual((state / "deployment").read_text().strip(), f"default/{OLD_COMMIT}/0")

    def test_mount_failure_keeps_recovery_intent_but_not_ready_marker(self):
        result, state, _, runtime = self.prepare(OLD_COMMIT, NEW_COMMIT, mount_status=1)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("overlay mount failed", result.stdout)
        self.assertTrue((state / "needs-sync").exists())
        self.assertFalse((runtime / "overlay-mounted").exists())
        self.assertEqual((state / "deployment").read_text().strip(), f"default/{OLD_COMMIT}/0")


if __name__ == "__main__":
    unittest.main()
