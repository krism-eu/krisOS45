#!/usr/bin/python3
"""Policy tests: reject unsafe solved transactions before any RPM changes."""
from contextlib import redirect_stderr, redirect_stdout
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import types
import sys
import unittest
from unittest import mock

_loader = importlib.machinery.SourceFileLoader('rk', str(Path(__file__).resolve().parents[1] / 'bin/rk'))
_spec = importlib.util.spec_from_loader(_loader.name, _loader)
rk = importlib.util.module_from_spec(_spec)
_loader.exec_module(rk)

_REAL_FSTAT = os.fstat


def root_owned_fstat(fd):
    """Return the real mode/type while simulating the production root:root owner.

    Source-level unit tests must also run from an unprivileged developer shell;
    ownership itself is covered separately by an explicit negative test.
    """
    info = _REAL_FSTAT(fd)
    return types.SimpleNamespace(st_mode=info.st_mode, st_uid=0, st_gid=0)


def unprivileged_owned_fstat(fd):
    info = _REAL_FSTAT(fd)
    return types.SimpleNamespace(st_mode=info.st_mode, st_uid=1000, st_gid=1000)


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


def fake_libdnf5_for_refresh(available=True, repo_error=None):
    class Config:
        pass

    class Sack:
        def create_repos_from_system_configuration(self):
            pass

        def load_repos(self):
            if repo_error is not None:
                raise RuntimeError(repo_error)

    class Base:
        def __init__(self):
            self.config = Config()
            self.sack = Sack()
            self.unlocked = False

        def load_config(self):
            pass

        def get_config(self):
            return self.config

        def setup(self):
            pass

        def lock_system_repo(self):
            return True

        def unlock_system_repo(self):
            self.unlocked = True

        def get_repo_sack(self):
            return self.sack

    class Package:
        def __init__(self, name='tree', arch='x86_64'):
            self.name = name
            self.arch = arch

        def get_arch(self):
            return self.arch

    class PackageQuery:
        def __init__(self, base):
            self.name = None

        def filter_available(self):
            pass

        def filter_name(self, name):
            self.name = name

        def __iter__(self):
            return iter([Package(self.name or 'tree')] if available else [])

    # Deliberately no Goal implementation: refresh must only inspect repository
    # availability, never solve an upgrade against the current overlay state.
    return types.SimpleNamespace(
        base=types.SimpleNamespace(Base=Base),
        repo=types.SimpleNamespace(RepoQuery=lambda base: []),
        rpm=types.SimpleNamespace(PackageQuery=PackageQuery),
    )


class Policy(unittest.TestCase):
    def test_entrypoint_catches_non_runtime_libdnf_style_exception(self):
        class NonLibdnfStyleException(Exception):
            pass

        stream = io.StringIO()
        with mock.patch.object(rk, 'main', side_effect=NonLibdnfStyleException('repository offline')), \
                redirect_stderr(stream):
            self.assertEqual(rk.entrypoint(), 1)
        self.assertEqual(stream.getvalue(), 'rk: NonLibdnfStyleException repository offline\n')

    def test_entrypoint_flattens_multiline_libdnf_style_exception(self):
        class NonLibdnfStyleException(Exception):
            pass

        stream = io.StringIO()
        with mock.patch.object(rk, 'main', side_effect=NonLibdnfStyleException('line1\nline2')), \
                redirect_stderr(stream):
            self.assertEqual(rk.entrypoint(), 1)
        self.assertEqual(stream.getvalue(), 'rk: NonLibdnfStyleException line1 line2\n')

    def test_entrypoint_preserves_specific_runtime_error_format(self):
        stream = io.StringIO()
        with mock.patch.object(rk, 'main', side_effect=RuntimeError('blocked\nreason')), \
                redirect_stderr(stream):
            self.assertEqual(rk.entrypoint(), 1)
        self.assertEqual(stream.getvalue(), 'rk: blocked reason\n')

    def test_entrypoint_does_not_swallow_system_exit(self):
        with mock.patch.object(rk, 'main', side_effect=SystemExit(2)), \
                self.assertRaises(SystemExit) as raised:
            rk.entrypoint()
        self.assertEqual(raised.exception.code, 2)

    def test_repo_hardening_preserves_admin_enabled_state(self):
        for enabled in (True, False):
            with self.subTest(enabled=enabled):
                repo = FakeRepo(enabled)
                rk.harden_repo(repo)
                self.assertEqual(repo.config.enabled, enabled)
                self.assertTrue(repo.config.pkg_gpgcheck)

    def test_transaction_lock_requires_root_only_regular_file(self):
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(rk, 'STATE', Path(directory)):
            path = Path(directory) / 'lock'
            path.write_text('')
            # Keep the real test file openable by an unprivileged developer.
            # Simulate the production root:root metadata, including each mode,
            # through fstat so the test reaches rk's policy check instead of
            # failing early in os.open() on 0400/0200.
            path.chmod(0o600)
            for mode in (0o644, 0o400, 0o200, 0o660):
                with self.subTest(mode=oct(mode)), \
                        mock.patch.object(
                            rk.os,
                            'fstat',
                            return_value=types.SimpleNamespace(
                                st_mode=0o100000 | mode, st_uid=0, st_gid=0
                            ),
                        ):
                    with self.assertRaisesRegex(RuntimeError, 'root:root mode 0600'):
                        rk.open_transaction_lock()
            with mock.patch.object(
                    rk.os,
                    'fstat',
                    return_value=types.SimpleNamespace(
                        st_mode=0o100600, st_uid=0, st_gid=0
                    ),
            ):
                fd = rk.open_transaction_lock()
            try:
                self.assertTrue(fd >= 0)
            finally:
                os.close(fd)

    def test_transaction_lock_rejects_non_root_owner(self):
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(rk, 'STATE', Path(directory)), \
                mock.patch.object(rk.os, 'fstat', side_effect=unprivileged_owned_fstat):
            path = Path(directory) / 'lock'
            path.write_text('')
            path.chmod(0o600)
            with self.assertRaisesRegex(RuntimeError, 'root:root mode 0600'):
                rk.open_transaction_lock()

    def test_transaction_lock_missing_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(rk, 'STATE', Path(directory)):
            with self.assertRaisesRegex(RuntimeError, 'transaction lock is not initialized'):
                rk.open_transaction_lock()

    def test_transaction_lock_does_not_follow_symlink(self):
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(rk, 'STATE', Path(directory)):
            root = Path(directory)
            target = root / 'target'
            target.write_text('')
            target.chmod(0o600)
            (root / 'lock').symlink_to(target)
            with self.assertRaises(OSError):
                rk.open_transaction_lock()

    def test_transaction_lock_busy_has_clear_error(self):
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(rk, 'STATE', Path(directory)), \
                mock.patch.object(rk.os, 'fstat', side_effect=root_owned_fstat):
            path = Path(directory) / 'lock'
            path.write_text('')
            path.chmod(0o600)
            fd = rk.open_transaction_lock()
            try:
                with mock.patch.object(rk.fcntl, 'flock', side_effect=BlockingIOError), \
                        self.assertRaisesRegex(RuntimeError, 'Another rk transaction is in progress'):
                    rk.acquire_transaction_lock(fd)
            finally:
                os.close(fd)

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


    def test_refresh_cli_is_root_only(self):
        with mock.patch.object(sys, 'argv', ['/usr/bin/rk', 'refresh']), \
                mock.patch.object(rk.os, 'geteuid', return_value=1000), \
                mock.patch.object(rk, 'refresh_overlay') as refresh, \
                self.assertRaisesRegex(RuntimeError, 'Run with sudo'):
            rk.main()
        refresh.assert_not_called()

    def test_refresh_cli_runs_under_transaction_lock(self):
        with mock.patch.object(sys, 'argv', ['/usr/bin/rk', 'refresh']), \
                mock.patch.object(rk.os, 'geteuid', return_value=0), \
                mock.patch.object(rk, 'open_transaction_lock', return_value=123) as open_lock, \
                mock.patch.object(rk, 'acquire_transaction_lock') as acquire, \
                mock.patch.object(rk, 'guard'), \
                mock.patch.object(rk, 'load_intent'), \
                mock.patch.object(rk, 'refresh_overlay') as refresh, \
                mock.patch.object(rk.os, 'close') as close:
            rk.main()
        open_lock.assert_called_once_with()
        acquire.assert_called_once_with(123)
        refresh.assert_called_once_with()
        close.assert_called_once_with(123)

    def test_refresh_unavailable_request_does_not_write_pending(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            (state / 'packages.list').write_text('tree\n')
            owned = state / 'owned'
            owned.write_text('base\n')
            module = fake_libdnf5_for_refresh(available=False)
            with mock.patch.object(rk, 'STATE', state), \
                    mock.patch.object(rk, 'OWNED', owned), \
                    mock.patch.object(rk, 'guard', return_value='mount'), \
                    mock.patch.object(rk, 'check_base'), \
                    mock.patch.object(rk, 'output', return_value='tree'), \
                    mock.patch.dict(sys.modules, {'libdnf5': module}), \
                    self.assertRaisesRegex(RuntimeError, 'unavailable in enabled repositories'):
                rk.refresh_overlay()
            self.assertFalse((state / 'pending').exists())

    def test_refresh_repository_load_failure_does_not_write_pending(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            (state / 'packages.list').write_text('tree\n')
            owned = state / 'owned'
            owned.write_text('base\n')
            module = fake_libdnf5_for_refresh(repo_error='repository offline')
            with mock.patch.object(rk, 'STATE', state), \
                    mock.patch.object(rk, 'OWNED', owned), \
                    mock.patch.object(rk, 'guard', return_value='mount'), \
                    mock.patch.object(rk, 'check_base'), \
                    mock.patch.object(rk, 'output', return_value='tree'), \
                    mock.patch.dict(sys.modules, {'libdnf5': module}), \
                    self.assertRaisesRegex(RuntimeError, 'repository offline'):
                rk.refresh_overlay()
            self.assertFalse((state / 'pending').exists())

    def test_refresh_drops_requests_now_owned_by_base(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            (state / 'packages.list').write_text('tree\nnowbase\n')
            owned = state / 'owned'
            owned.write_text('base\nnowbase\n')
            module = fake_libdnf5_for_refresh()
            stream = io.StringIO()
            with mock.patch.object(rk, 'STATE', state), \
                    mock.patch.object(rk, 'OWNED', owned), \
                    mock.patch.object(rk, 'guard', return_value='mount'), \
                    mock.patch.object(rk, 'check_base'), \
                    mock.patch.object(rk, 'output', return_value='tree'), \
                    mock.patch.dict(sys.modules, {'libdnf5': module}), \
                    redirect_stdout(stream):
                rk.refresh_overlay()
            self.assertEqual((state / 'packages.list').read_text(), 'tree\n')
            self.assertEqual((state / 'pending').read_text(),
                             'Refresh requested: rebuild overlay after reboot\n')
            self.assertIn('Dropped requests now provided by the base image: nowbase',
                          stream.getvalue())

    def test_refresh_when_all_requests_are_owned_does_not_arm_pending(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            (state / 'packages.list').write_text('nowbase\n')
            owned = state / 'owned'
            owned.write_text('nowbase\n')
            stream = io.StringIO()
            with mock.patch.object(rk, 'STATE', state), \
                    mock.patch.object(rk, 'OWNED', owned), \
                    mock.patch.object(rk, 'guard', return_value='mount'), \
                    mock.patch.object(rk, 'check_base') as check_base, \
                    redirect_stdout(stream):
                rk.refresh_overlay()
            self.assertEqual((state / 'packages.list').read_text(), '')
            self.assertFalse((state / 'pending').exists())
            self.assertIn('nothing to refresh', stream.getvalue())
            check_base.assert_called_once_with({'nowbase'})

    def test_refresh_empty_intent_has_neutral_message(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            (state / 'packages.list').write_text('')
            owned = state / 'owned'
            owned.write_text('base\n')
            stream = io.StringIO()
            with mock.patch.object(rk, 'STATE', state), \
                    mock.patch.object(rk, 'OWNED', owned), \
                    mock.patch.object(rk, 'guard', return_value='mount'), \
                    mock.patch.object(rk, 'check_base'), \
                    redirect_stdout(stream):
                rk.refresh_overlay()
            self.assertFalse((state / 'pending').exists())
            self.assertIn('No saved package requests; nothing to refresh.', stream.getvalue())
            self.assertNotIn('provided by the base image', stream.getvalue())

    def test_refresh_owned_drop_persists_if_repository_check_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            (state / 'packages.list').write_text('tree\nnowbase\n')
            owned = state / 'owned'
            owned.write_text('base\nnowbase\n')
            module = fake_libdnf5_for_refresh(available=False)
            with mock.patch.object(rk, 'STATE', state), \
                    mock.patch.object(rk, 'OWNED', owned), \
                    mock.patch.object(rk, 'guard', return_value='mount'), \
                    mock.patch.object(rk, 'check_base'), \
                    mock.patch.object(rk, 'output', return_value='tree'), \
                    mock.patch.dict(sys.modules, {'libdnf5': module}), \
                    self.assertRaisesRegex(RuntimeError, 'unavailable in enabled repositories'):
                rk.refresh_overlay()
            self.assertEqual((state / 'packages.list').read_text(), 'tree\n')
            self.assertFalse((state / 'pending').exists())

    def test_refresh_success_writes_private_pending_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            (state / 'packages.list').write_text('tree\n')
            owned = state / 'owned'
            owned.write_text('base\n')
            module = fake_libdnf5_for_refresh()
            stream = io.StringIO()
            with mock.patch.object(rk, 'STATE', state), \
                    mock.patch.object(rk, 'OWNED', owned), \
                    mock.patch.object(rk, 'guard', return_value='mount'), \
                    mock.patch.object(rk, 'check_base'), \
                    mock.patch.object(rk, 'output', return_value='tree'), \
                    mock.patch.dict(sys.modules, {'libdnf5': module}), \
                    redirect_stdout(stream):
                rk.refresh_overlay()
            pending = state / 'pending'
            self.assertEqual(pending.read_text(), 'Refresh requested: rebuild overlay after reboot\n')
            self.assertEqual(pending.stat().st_mode & 0o777, 0o600)
            self.assertIn('Refresh armed. Reboot', stream.getvalue())

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
                rows = []
                for entry in entries:
                    if len(entry) == 4:
                        name, mode, target, caps = entry
                        owner = group = 'root'
                    elif len(entry) == 6:
                        name, mode, owner, group, target, caps = entry
                    else:
                        raise AssertionError(f'unexpected manifest fixture: {entry!r}')
                    rows.append(f'{name}\t{mode}\t{owner}\t{group}\t{target}\t{caps}\n')
                return ''.join(rows)
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
            '/usr/lib/firmware/example/device.bin',
            '/usr/lib/grub/x86_64-efi/example.mod',
            '/usr/lib/bootupd/example',
            '/usr/libexec/krisos/example-helper',
            '/usr/share/dbus-1/system.d/org.example.conf',
            '/usr/share/dbus-1/system-services/org.example.service',
            '/usr/share/factory/var/lib/krisos/packages.list',
            '/usr/lib/environment.d/90-example.conf',
            '/usr/lib/binfmt.d/example.conf',
            '/usr/etc/example.conf',
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

    def test_cross_package_symlink_graph_cannot_reach_protected_namespace(self):
        package_a = [
            ('/usr/share/bridge', Path('/usr/share/bridge'), False, True, 'target', 0o120777, 'root', 'root', '/tmp/a.rpm'),
        ]
        package_b = [
            ('/usr/share/target', Path('/usr/share/target'), False, True, '/usr/lib/security', 0o120777, 'root', 'root', '/tmp/b.rpm'),
            ('/usr/share/bridge/payload.so', Path('/usr/share/bridge/payload.so'), False, False, '', 0o100644, 'root', 'root', '/tmp/b.rpm'),
        ]
        with mock.patch.object(
                rk, '_read_payload_manifest',
                side_effect=[(package_a, {'/usr/share/bridge': 'target'}),
                             (package_b, {'/usr/share/target': '/usr/lib/security'})]), \
                self.assertRaisesRegex(RuntimeError, 'protected or persistent state'):
            rk.validate_payloads(['/tmp/a.rpm', '/tmp/b.rpm'])

    def test_nested_incoming_symlinks_are_rejected(self):
        entries = [
            ('/usr/share/app', '120777', '/usr/bin', ''),
            ('/usr/share/app/hooks', '120777', '../lib/security', ''),
            ('/usr/share/app/hooks/evil.so', '100644', '', ''),
        ]
        with mock.patch.object(rk.subprocess, 'check_output', side_effect=self.rpm_manifest_output(entries)), \
                self.assertRaisesRegex(RuntimeError, 'Nested incoming symlinks are not supported'):
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

    def test_incoming_symlink_chain_cannot_escape_usr(self):
        entries = [
            ('/usr/share/a', '120777', 'b', ''),
            ('/usr/share/b', '120777', 'c', ''),
            ('/usr/share/c', '120777', '../../../etc', ''),
            ('/usr/share/a/payload', '100644', '', ''),
        ]
        with mock.patch.object(rk.subprocess, 'check_output', side_effect=self.rpm_manifest_output(entries)), \
                self.assertRaisesRegex(RuntimeError, 'resolves outside /usr'):
            rk.validate_payload('/tmp/overlay.rpm')

    def test_incoming_symlink_cycle_is_rejected(self):
        entries = [
            ('/usr/share/a', '120777', 'b', ''),
            ('/usr/share/b', '120777', 'a', ''),
        ]
        with mock.patch.object(rk.subprocess, 'check_output', side_effect=self.rpm_manifest_output(entries)), \
                self.assertRaisesRegex(RuntimeError, 'symlink cycle'):
            rk.validate_payload('/tmp/overlay.rpm')

    def test_non_root_owned_payload_is_rejected(self):
        entries = [('/usr/share/example/file.txt', '100644', 'daemon', 'root', '', '')]
        with mock.patch.object(rk.subprocess, 'check_output', side_effect=self.rpm_manifest_output(entries)), \
                self.assertRaisesRegex(RuntimeError, 'Non-root RPM ownership'):
            rk.validate_payload('/tmp/overlay.rpm')

    def test_group_or_world_writable_payload_is_rejected(self):
        for mode in ('100664', '100666', '040775', '040777'):
            with self.subTest(mode=mode), \
                    mock.patch.object(rk.subprocess, 'check_output', side_effect=self.rpm_manifest_output([('/usr/share/example/path', mode, '', '')])), \
                    self.assertRaisesRegex(RuntimeError, 'Group/world-writable'):
                rk.validate_payload('/tmp/overlay.rpm')

    def test_existing_directory_requires_exact_root_metadata(self):
        entries = [('/usr/share', '040755', '', '')]
        fake_info = type('S', (), {'st_uid': 0, 'st_gid': 0, 'st_mode': 0o40700})()
        with mock.patch.object(rk.subprocess, 'check_output', side_effect=self.rpm_manifest_output(entries)), \
                mock.patch.object(rk.os.path, 'lexists', return_value=True), \
                mock.patch.object(Path, 'is_dir', return_value=True), \
                mock.patch.object(Path, 'is_symlink', return_value=False), \
                mock.patch.object(Path, 'stat', return_value=fake_info), \
                self.assertRaisesRegex(RuntimeError, 'metadata does not match'):
            rk.validate_payload('/tmp/overlay.rpm')

    def test_usrmerge_sbin_directory_symlink_is_allowed_with_exact_metadata(self):
        entries = [('/usr/sbin', '040755', '', '')]
        fake_info = type('S', (), {'st_uid': 0, 'st_gid': 0, 'st_mode': 0o40755})()
        with mock.patch.object(rk.subprocess, 'check_output', side_effect=self.rpm_manifest_output(entries)), \
                mock.patch.object(rk.os.path, 'lexists', return_value=True), \
                mock.patch.object(Path, 'is_dir', return_value=True), \
                mock.patch.object(Path, 'is_symlink', return_value=True), \
                mock.patch.object(Path, 'stat', return_value=fake_info), \
                mock.patch.object(rk, '_is_allowed_usrmerge_directory_symlink', return_value=True):
            rk.validate_payload('/tmp/overlay.rpm')

    def test_usrmerge_sbin_alias_still_requires_exact_target_metadata(self):
        entries = [('/usr/sbin', '040755', '', '')]
        fake_info = type('S', (), {'st_uid': 0, 'st_gid': 0, 'st_mode': 0o40700})()
        with mock.patch.object(rk.subprocess, 'check_output', side_effect=self.rpm_manifest_output(entries)), \
                mock.patch.object(rk.os.path, 'lexists', return_value=True), \
                mock.patch.object(Path, 'is_dir', return_value=True), \
                mock.patch.object(Path, 'is_symlink', return_value=True), \
                mock.patch.object(Path, 'stat', return_value=fake_info), \
                mock.patch.object(rk, '_is_allowed_usrmerge_directory_symlink', return_value=True), \
                self.assertRaisesRegex(RuntimeError, 'metadata does not match'):
            rk.validate_payload('/tmp/overlay.rpm')

    def test_non_allowlisted_existing_directory_symlink_is_rejected(self):
        entries = [('/usr/share/example', '040755', '', '')]
        with mock.patch.object(rk.subprocess, 'check_output', side_effect=self.rpm_manifest_output(entries)), \
                mock.patch.object(rk.os.path, 'lexists', return_value=True), \
                mock.patch.object(Path, 'is_dir', return_value=True), \
                mock.patch.object(Path, 'is_symlink', return_value=True), \
                self.assertRaisesRegex(RuntimeError, 'would overwrite an existing path'):
            rk.validate_payload('/tmp/overlay.rpm')

    def test_usrmerge_allowlist_requires_exact_link_destination(self):
        file = mock.Mock()
        file.is_symlink.return_value = True
        file.resolve.return_value = Path('/usr/bin')
        with mock.patch.object(rk.os, 'readlink', return_value='bin'):
            self.assertTrue(rk._is_allowed_usrmerge_directory_symlink('/usr/sbin', file))
        with mock.patch.object(rk.os, 'readlink', return_value='../bin'):
            self.assertFalse(rk._is_allowed_usrmerge_directory_symlink('/usr/sbin', file))
        with mock.patch.object(rk.os, 'readlink', return_value='bin'):
            self.assertFalse(rk._is_allowed_usrmerge_directory_symlink('/usr/libexec', file))

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

    def test_identical_root_owned_existing_symlink_is_allowed(self):
        entries = [('/usr/share/example/current', '120777', 'data', '')]
        fake_lstat = types.SimpleNamespace(st_uid=0, st_gid=0, st_mode=0o120777)
        with mock.patch.object(rk.subprocess, 'check_output', side_effect=self.rpm_manifest_output(entries)), \
                mock.patch.object(rk.os.path, 'lexists', return_value=True), \
                mock.patch.object(Path, 'is_symlink', return_value=True), \
                mock.patch.object(Path, 'lstat', return_value=fake_lstat), \
                mock.patch.object(rk.os, 'readlink', return_value='data'):
            rk.validate_payload('/tmp/overlay.rpm')

    def test_identical_existing_symlink_cannot_reach_protected_namespace(self):
        entries = [('/usr/share/example/current', '120777', '/usr/lib/security', '')]
        fake_lstat = types.SimpleNamespace(st_uid=0, st_gid=0, st_mode=0o120777)
        with mock.patch.object(rk.subprocess, 'check_output', side_effect=self.rpm_manifest_output(entries)), \
                mock.patch.object(rk.os.path, 'lexists', return_value=True), \
                mock.patch.object(Path, 'is_symlink', return_value=True), \
                mock.patch.object(Path, 'lstat', return_value=fake_lstat), \
                mock.patch.object(rk.os, 'readlink', return_value='/usr/lib/security'), \
                self.assertRaisesRegex(RuntimeError, 'protected or persistent state'):
            rk.validate_payload('/tmp/overlay.rpm')

    def test_existing_symlink_with_different_target_is_rejected(self):
        entries = [('/usr/share/example/current', '120777', 'data', '')]
        fake_lstat = types.SimpleNamespace(st_uid=0, st_gid=0, st_mode=0o120777)
        with mock.patch.object(rk.subprocess, 'check_output', side_effect=self.rpm_manifest_output(entries)), \
                mock.patch.object(rk.os.path, 'lexists', return_value=True), \
                mock.patch.object(Path, 'is_symlink', return_value=True), \
                mock.patch.object(Path, 'lstat', return_value=fake_lstat), \
                mock.patch.object(rk.os, 'readlink', return_value='other'), \
                self.assertRaisesRegex(RuntimeError, 'overwrite an existing path'):
            rk.validate_payload('/tmp/overlay.rpm')

    def test_identical_existing_symlink_must_be_root_owned(self):
        entries = [('/usr/share/example/current', '120777', 'data', '')]
        fake_lstat = types.SimpleNamespace(st_uid=1000, st_gid=1000, st_mode=0o120777)
        with mock.patch.object(rk.subprocess, 'check_output', side_effect=self.rpm_manifest_output(entries)), \
                mock.patch.object(rk.os.path, 'lexists', return_value=True), \
                mock.patch.object(Path, 'is_symlink', return_value=True), \
                mock.patch.object(Path, 'lstat', return_value=fake_lstat), \
                mock.patch.object(rk.os, 'readlink', return_value='data'), \
                self.assertRaisesRegex(RuntimeError, 'overwrite an existing path'):
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
            with self.assertRaisesRegex(RuntimeError, 'A rebuild is pending; reboot'):
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

    def test_status_reports_corrupted_package_intent_as_json_safe_degraded_state(self):
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(rk, 'STATE', Path(directory)), \
                mock.patch.object(rk, 'output', side_effect=guard_output):
            state = Path(directory)
            (state / 'packages.list').write_text('tree\nbad name\n')
            payload = rk.status_payload()
            self.assertEqual(payload['overlay'], 'degraded')
            self.assertEqual(payload['requests'], [])
            self.assertIn('Use an exact package name', payload['state_error'])
            stream = io.StringIO()
            with redirect_stdout(stream):
                rk.show_status(json_output=True)
            decoded = json.loads(stream.getvalue())
            self.assertEqual(decoded['schema'], 1)
            self.assertTrue(decoded['state_error'])

    def test_status_reports_non_utf8_package_intent_without_crashing(self):
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(rk, 'STATE', Path(directory)), \
                mock.patch.object(rk, 'output', side_effect=guard_output):
            state = Path(directory)
            (state / 'packages.list').write_bytes(b'tree\n\xff\n')
            payload = rk.status_payload()
            self.assertEqual(payload['overlay'], 'degraded')
            self.assertTrue(payload['state_error'])


if __name__ == '__main__':
    unittest.main()
