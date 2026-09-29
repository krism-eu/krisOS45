#!/usr/bin/python3
"""Policy tests: reject unsafe solved transactions before any RPM changes."""
from contextlib import redirect_stdout
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

_loader = importlib.machinery.SourceFileLoader('rk', str(Path(__file__).resolve().parents[1] / 'bin/rk'))
_spec = importlib.util.spec_from_loader(_loader.name, _loader)
rk = importlib.util.module_from_spec(_spec)
_loader.exec_module(rk)


def guard_output(*args):
    if args[:2] == (rk.FINDMNT, '-rn'):
        return '42 overlay rw,relatime,upperdir=/var/lib/krisos/upper,workdir=/var/lib/krisos/work'
    if args == (rk.GETENFORCE,):
        return 'Enforcing'
    if args == (rk.LS, '-Zd', '/usr'):
        return 'system_u:object_r:usr_t:s0 /usr'
    if args == (rk.RPM, '--eval', '%{_dbpath}'):
        return '/usr/lib/sysimage/rpm'
    raise AssertionError(f'unexpected command: {args!r}')


class FakeRepoConfig:
    def __init__(self, enabled):
        self.enabled = enabled
        self.pkg_gpgcheck = False


class FakeRepo:
    def __init__(self, enabled):
        self.config = FakeRepoConfig(enabled)

    def get_config(self):
        return self.config


class Policy(unittest.TestCase):
    def test_repo_hardening_preserves_admin_enabled_state(self):
        for enabled in (True, False):
            with self.subTest(enabled=enabled):
                repo = FakeRepo(enabled)
                rk.harden_repo(repo)
                self.assertEqual(repo.config.enabled, enabled)
                self.assertTrue(repo.config.pkg_gpgcheck)

    def test_plan_lock_missing_falls_back_read_only(self):
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(rk, 'STATE', Path(directory)):
            self.assertIsNone(rk.acquire_plan_lock())

    def test_plan_lock_uses_readonly_shared_nonblocking_lock(self):
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(rk, 'STATE', Path(directory)):
            path = Path(directory) / 'lock'
            path.write_text('')
            real_open = os.open
            calls = []
            def tracked_open(file, flags, *args):
                calls.append((Path(file), flags))
                return real_open(file, flags, *args)
            with mock.patch.object(rk.os, 'open', side_effect=tracked_open):
                fd = rk.acquire_plan_lock()
                try:
                    self.assertEqual(calls[0], (path, os.O_RDONLY))
                finally:
                    os.close(fd)

    def test_plan_lock_busy_has_clear_error(self):
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(rk, 'STATE', Path(directory)), \
                mock.patch.object(rk.fcntl, 'flock', side_effect=BlockingIOError):
            (Path(directory) / 'lock').write_text('')
            with self.assertRaisesRegex(RuntimeError, 'Another rk transaction is in progress'):
                rk.acquire_plan_lock()

    def test_all_base_actions_rejected(self):
        for action in ('Install', 'Remove', 'Upgrade', 'Downgrade', 'Reinstall', 'Replaced'):
            with self.subTest(action=action), self.assertRaises(RuntimeError):
                rk.validate_plan([('glibc', 'x86_64', action)], {'glibc'}, {'glibc'})

    def test_indirect_removal_rejected(self):
        with self.assertRaises(RuntimeError):
            rk.validate_plan([('another-app', 'x86_64', 'Remove')], set(), {'tree'})

    def test_multilib_dependency_rejected(self):
        with self.assertRaises(RuntimeError):
            rk.validate_plan([('dependency', 'i686', 'Install')], set(), set())

    def test_additive_and_explicit_remove(self):
        rk.validate_plan([('tree', 'x86_64', 'Install'), ('data', 'noarch', 'Install')], {'glibc'}, set())
        rk.validate_plan([('tree', 'x86_64', 'Remove')], {'glibc'}, {'tree'})


    def test_check_base_reports_expected_and_observed_nevra(self):
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(rk, 'IDENTITIES', Path(directory) / 'owned-nevra.txt'), \
                mock.patch.object(rk, 'output', return_value='base\t0:2.0-1.fc45.x86_64'):
            rk.IDENTITIES.write_text('base\t0:1.0-1.fc45.x86_64\n')
            with self.assertRaisesRegex(RuntimeError, 'expected but missing/changed:.*1.0.*observed replacement/change:.*2.0'):
                rk.check_base({'base'})

    def test_no_cli_escape_hatches(self):
        for name in ('--disableexcludes=all', '/tmp/a.rpm', 'https://example/a.rpm', 'a.i686', 'a*', '@group', 'a' * 129):
            with self.subTest(name=name), self.assertRaises(RuntimeError):
                rk.names([name])
        self.assertEqual(rk.names(['a' * 128]), {'a' * 128})

    def test_owned_names_are_not_revalidated_as_cli_input(self):
        self.assertEqual(rk.owned_names(['ordinary', 'future.x86_64']), {'ordinary', 'future.x86_64'})
        with self.assertRaises(RuntimeError):
            rk.owned_names(['bad name'])

    @staticmethod
    def rpm_manifest_output(entries):
        def fake_check_output(*args, **kwargs):
            command = args[0] if len(args) == 1 and isinstance(args[0], (tuple, list)) else args
            command = tuple(command)
            if command[:2] != (rk.RPM, '-qp'):
                raise AssertionError(f'unexpected command: {command!r}')
            if command[2] in ('--scripts', '--triggers', '--filetriggers'):
                return ''
            if command[2] == '--qf':
                # Include a final newline exactly like rpm. Empty FILELINKTOS and
                # FILECAPS therefore leave two meaningful trailing TAB fields.
                return ''.join(
                    f'{name}\t{mode}\t{target}\t{caps}\n'
                    for name, mode, target, caps in entries
                )
            raise AssertionError(f'unexpected rpm query: {command!r}')
        return fake_check_output

    def test_fedora45_vendor_repo_and_trust_paths_are_protected(self):
        for filename in (
            '/usr/share/dnf5/repos.d/overlay.repo',
            '/usr/share/dnf5/libdnf.conf.d/overlay.conf',
            '/usr/share/dnf5/repos.override.d/overlay.repo',
            '/usr/share/pki/rpm-gpg/RPM-GPG-KEY-overlay',
            '/usr/lib/rpm/macros.d/macros.overlay',
        ):
            with self.subTest(filename=filename), \
                    mock.patch.object(rk.subprocess, 'check_output', side_effect=self.rpm_manifest_output([(filename, '100644', '', '')])), \
                    self.assertRaisesRegex(RuntimeError, 'protected or persistent state'):
                rk.validate_payload('/tmp/overlay.rpm')

    def test_manifest_preserves_empty_final_link_and_caps_fields(self):
        entries = [('/usr/share/example/final.txt', '100644', '', '')]
        with mock.patch.object(
                rk.subprocess, 'check_output',
                side_effect=self.rpm_manifest_output(entries)), \
                mock.patch.object(rk.os.path, 'lexists', return_value=False):
            rk.validate_payload('/tmp/overlay.rpm')

    def test_persistent_effect_namespaces_are_protected(self):
        for filename in (
            '/usr/lib/sysusers.d/overlay.conf',
            '/usr/lib/tmpfiles.d/overlay.conf',
            '/usr/lib/udev/rules.d/99-overlay.rules',
            '/usr/lib/systemd/system/overlay.service',
            '/usr/lib/systemd/system-generators/overlay-generator',
            '/usr/lib/systemd/system-preset/90-overlay.preset',
            '/usr/lib/systemd/user-preset/90-overlay.preset',
            '/usr/lib/systemd/network/10-overlay.network',
            '/usr/lib/systemd/resolved.conf.d/90-overlay.conf',
            '/usr/lib/systemd/journald.conf.d/90-overlay.conf',
            '/usr/lib/firewalld/services/overlay.xml',
            '/usr/lib/selinux/overlay.pp',
            '/usr/share/selinux/packages/overlay.pp',
            '/usr/lib/pam.d/overlay',
            '/usr/share/polkit-1/actions/org.example.overlay.policy',
            '/usr/lib/sysctl.d/99-overlay.conf',
            '/usr/lib/NetworkManager/conf.d/overlay.conf',
            '/usr/lib/dracut/modules.d/99overlay/module-setup.sh',
        ):
            with self.subTest(filename=filename), \
                    mock.patch.object(rk.subprocess, 'check_output', side_effect=self.rpm_manifest_output([(filename, '100644', '', '')])), \
                    self.assertRaisesRegex(RuntimeError, 'protected or persistent state'):
                rk.validate_payload('/tmp/overlay.rpm')

    def test_incoming_symlink_cannot_escape_usr(self):
        entries = [
            ('/usr/share/evil', '120777', '../../../etc', ''),
            ('/usr/share/evil/payload', '100644', '', ''),
        ]
        with mock.patch.object(rk.subprocess, 'check_output', side_effect=self.rpm_manifest_output(entries)), \
                self.assertRaisesRegex(RuntimeError, 'resolves outside /usr'):
            rk.validate_payload('/tmp/overlay.rpm')

    def test_incoming_symlink_cannot_alias_protected_namespace(self):
        entries = [
            ('/usr/share/evil', '120777', '/usr/share/dnf5', ''),
            ('/usr/share/evil/payload.repo', '100644', '', ''),
        ]
        with mock.patch.object(rk.subprocess, 'check_output', side_effect=self.rpm_manifest_output(entries)), \
                self.assertRaisesRegex(RuntimeError, 'protected or persistent state'):
            rk.validate_payload('/tmp/overlay.rpm')

    def test_safe_internal_symlink_is_allowed(self):
        entries = [
            ('/usr/share/example', '040755', '', ''),
            ('/usr/share/example/data', '040755', '', ''),
            ('/usr/share/example/current', '120777', 'data', ''),
            ('/usr/share/example/current/file.txt', '100644', '', ''),
        ]
        with mock.patch.object(rk.subprocess, 'check_output', side_effect=self.rpm_manifest_output(entries)), \
                mock.patch.object(rk.os.path, 'lexists', return_value=False):
            rk.validate_payload('/tmp/overlay.rpm')


    def test_special_setid_and_capability_payloads_are_rejected(self):
        cases = (
            ('/usr/share/example/device', '020666', '', '', 'Special files'),
            ('/usr/share/example/fifo', '010644', '', '', 'Special files'),
            ('/usr/bin/example-setuid', '104755', '', '', 'setuid/setgid'),
            ('/usr/bin/example-setgid', '102755', '', '', 'setuid/setgid'),
            ('/usr/bin/example-cap', '100755', '', 'cap_net_raw=ep', 'File capabilities'),
        )
        for filename, mode, target, caps, error in cases:
            with self.subTest(filename=filename), \
                    mock.patch.object(rk.subprocess, 'check_output', side_effect=self.rpm_manifest_output([(filename, mode, target, caps)])), \
                    self.assertRaisesRegex(RuntimeError, error):
                rk.validate_payload('/tmp/overlay.rpm')

    def test_intent_atomic_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'packages.list'
            rk.atomic(path, 'tree\n', mode=0o644)
            rk.atomic(path, 'tree\nunzip\n', mode=0o644)
            self.assertEqual(path.read_text(), 'tree\nunzip\n')
            self.assertEqual(oct(path.stat().st_mode & 0o777), '0o644')
            self.assertEqual(sorted(p.name for p in path.parent.iterdir()), ['packages.list'])

    def test_atomic_default_mode_remains_private(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'pending'
            rk.atomic(path, 'recover\n')
            self.assertEqual(oct(path.stat().st_mode & 0o777), '0o600')

    def test_guard_does_not_reconstruct_deployment_from_bootcsum(self):
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(rk, 'STATE', Path(directory)), \
                mock.patch.object(rk, 'output', side_effect=guard_output):
            (Path(directory) / 'deployment').write_text('default/' + 'a' * 64 + '/0\n')
            mount = rk.guard()
            self.assertTrue(mount.startswith('42 overlay '))

    def test_guard_blocks_pending_transaction_recovery(self):
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(rk, 'STATE', Path(directory)), \
                mock.patch.object(rk, 'output', side_effect=guard_output):
            (Path(directory) / 'pending').write_text('recover\n')
            with self.assertRaisesRegex(RuntimeError, 'Interrupted transaction requires reboot'):
                rk.guard()

    def test_status_remains_readable_during_pending_recovery(self):
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(rk, 'STATE', Path(directory)), \
                mock.patch.object(rk, 'output', side_effect=guard_output):
            state = Path(directory)
            (state / 'pending').write_text('recover\n')
            (state / 'needs-sync').write_text('')
            (state / 'packages.list').write_text('tree\n')
            stream = io.StringIO()
            with redirect_stdout(stream):
                rk.show_status()
            text = stream.getvalue()
            self.assertIn('Overlay: ready', text)
            self.assertIn('Pending recovery: True', text)
            self.assertIn('Needs sync: True', text)
            self.assertIn('tree', text)

            json_stream = io.StringIO()
            with redirect_stdout(json_stream):
                rk.show_status(json_output=True)
            payload = json.loads(json_stream.getvalue())
            self.assertEqual(payload['schema'], 1)
            self.assertEqual(payload['overlay'], 'ready')
            self.assertTrue(payload['pending_recovery'])
            self.assertTrue(payload['needs_sync'])
            self.assertEqual(payload['requests'], ['tree'])

    def test_status_ignores_blank_package_lines(self):
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(rk, 'STATE', Path(directory)), \
                mock.patch.object(rk, 'output', side_effect=guard_output):
            state = Path(directory)
            (state / 'packages.list').write_text('tree\n\n   \nnano\n')
            payload = rk.status_payload()
            self.assertEqual(payload['requests'], ['nano', 'tree'])
            self.assertEqual(rk.load_intent(), {'nano', 'tree'})

    def test_status_rejects_corrupted_package_intent(self):
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(rk, 'STATE', Path(directory)), \
                mock.patch.object(rk, 'output', side_effect=guard_output):
            state = Path(directory)
            (state / 'packages.list').write_text('tree\nbad name\n')
            with self.assertRaisesRegex(RuntimeError, 'Use an exact package name'):
                rk.status_payload()


if __name__ == '__main__':
    unittest.main()