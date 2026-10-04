#!/usr/bin/python3
import importlib.machinery
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

_loader = importlib.machinery.SourceFileLoader('rk_recovery', str(Path(__file__).resolve().parents[1] / 'bin/rk'))
_spec = importlib.util.spec_from_loader(_loader.name, _loader)
rk = importlib.util.module_from_spec(_spec)
_loader.exec_module(rk)


class RecoveryIntent(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / 'packages.list').write_text('missing-app\nkeep-app\nbase\n')
        (self.root / 'needs-sync').touch()
        (self.root / 'owned').write_text('base\n')
        for patch in (mock.patch.object(rk, 'STATE', self.root), mock.patch.object(rk, 'OWNED', self.root / 'owned'), mock.patch.object(rk, 'guard'), mock.patch.object(rk, 'check_base'), mock.patch.object(rk, 'output', return_value='base\nkeep-app')):
            patch.start()
            self.addCleanup(patch.stop)

    def test_forget_unavailable_preserves_recovery_and_other_requests(self):
        rk.forget_requests({'missing-app'})
        self.assertEqual((self.root / 'packages.list').read_text(), 'base\nkeep-app\n')
        self.assertTrue((self.root / 'needs-sync').exists())
        self.assertFalse((self.root / 'pending').exists())
        self.assertEqual((self.root / 'packages.list').stat().st_mode & 0o777, 0o644)

    def test_installed_overlay_package_cannot_be_forgotten(self):
        with self.assertRaisesRegex(RuntimeError, 'installed overlay'):
            rk.forget_requests({'keep-app', 'missing-app'})
        self.assertIn('missing-app', (self.root / 'packages.list').read_text())

    def test_owned_request_can_be_forgotten_without_removing_owned_rpm(self):
        rk.forget_requests({'base'})
        self.assertNotIn('base', (self.root / 'packages.list').read_text())

    def test_forget_requires_recovery(self):
        (self.root / 'needs-sync').unlink()
        with self.assertRaisesRegex(RuntimeError, 'only available during recovery'):
            rk.forget_requests({'missing-app'})

    def test_unknown_request_leaves_intent_unchanged(self):
        before = (self.root / 'packages.list').read_bytes()
        with self.assertRaisesRegex(RuntimeError, 'saved package requests'):
            rk.forget_requests({'unknown'})
        self.assertEqual((self.root / 'packages.list').read_bytes(), before)

    def test_pending_or_degraded_guard_blocks_forget(self):
        rk.guard.side_effect = RuntimeError('Interrupted transaction requires reboot')
        with self.assertRaisesRegex(RuntimeError, 'requires reboot'):
            rk.forget_requests({'missing-app'})
        self.assertIn('missing-app', (self.root / 'packages.list').read_text())


    def test_refresh_rejects_needs_sync_without_writing_pending(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            (state / 'packages.list').write_text('keep-app\n')
            (state / 'needs-sync').touch()
            owned = state / 'owned'
            owned.write_text('base\n')
            with mock.patch.object(rk, 'STATE', state), mock.patch.object(rk, 'OWNED', owned), \
                    self.assertRaisesRegex(RuntimeError, 'recovery is already pending'):
                rk.refresh_overlay()
            self.assertTrue((state / 'needs-sync').exists())
            self.assertFalse((state / 'pending').exists())

    def test_refresh_rejects_pending_without_changing_recovery_state(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            (state / 'packages.list').write_text('keep-app\n')
            pending = state / 'pending'
            pending.write_text('existing recovery\n')
            owned = state / 'owned'
            owned.write_text('base\n')
            before = pending.read_bytes()
            with mock.patch.object(rk, 'STATE', state), mock.patch.object(rk, 'OWNED', owned), \
                    self.assertRaisesRegex(RuntimeError, 'A rebuild is pending; reboot'):
                rk.refresh_overlay()
            self.assertEqual(pending.read_bytes(), before)

    def test_missing_provisioning_has_actionable_error(self):
        (self.root / 'packages.list').unlink()
        with self.assertRaisesRegex(RuntimeError, 'systemd-tmpfiles'):
            rk.load_intent()


if __name__ == '__main__':
    unittest.main()
