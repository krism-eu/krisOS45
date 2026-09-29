#!/usr/bin/python3
"""Exercise the real hook's early exits; no mount/state commands may run."""
from pathlib import Path
import subprocess
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'systemd/krisos-overlay.sh'


class Recovery(unittest.TestCase):
    def run_hook(self, cmdline):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'cmdline').write_text(cmdline)
            (root / 'ostree=unexpected').touch()
            hook = root / 'hook.sh'
            hook.write_text(SOURCE.read_text().replace('/proc/cmdline', str(root / 'cmdline')))
            result = subprocess.run(['/bin/bash', str(hook)], cwd=root,
                                    env={'PATH': '/nonexistent'}, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stderr, '')
            return result.stdout

    def test_off_before_any_state_access(self):
        self.assertIn('disabled via karg', self.run_hook('ostree=/ostree/boot.0/default/abc/0 krisos.overlay=off'))

    def test_off_with_whitespace(self):
        self.assertIn('disabled via karg', self.run_hook('\tkrisos.overlay=off  quiet\n'))

    def test_only_exact_token_disables(self):
        for token in ('krisos.overlay=offfoo', 'other=krisos.overlay=off'):
            self.assertIn('no ostree=', self.run_hook(token))

    def test_no_globbing(self):
        self.assertIn('no ostree=', self.run_hook('*'))

    def test_recovery_is_distinct_from_normal_success(self):
        for enforcement, code in (('Enforcing', 2), ('Permissive', 1)):
            with self.subTest(enforcement=enforcement), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / 'cmdline').write_text('ostree=/ostree/boot.0/default/abc/0 krisos.overlay=off\n')
                systemctl = '''
if [ "$1" = "is-enabled" ] && [ "$2" = "systemd-homed.service" ]; then
    exit 1
fi
if [ "$1" = "is-active" ] && [ "$2" = "systemd-homed.service" ]; then
    exit 3
fi
echo active
'''.strip()
                for name, body in (('findmnt', 'exit 1'), ('systemctl', systemctl), ('getenforce', 'echo ' + enforcement)):
                    file = root / name
                    file.write_text('#!/bin/sh\n' + body + '\n')
                    file.chmod(0o755)
                check = root / 'check.sh'
                check.write_text((SOURCE.parents[1] / 'tests/boot-check.sh').read_text().replace('/proc/cmdline', str(root / 'cmdline')))
                result = subprocess.run(['/bin/bash', str(check)], env={'PATH': str(root) + ':/usr/bin:/bin'}, capture_output=True, text=True)
                self.assertEqual(result.returncode, code, result.stdout + result.stderr)
                self.assertNotIn('ALL CHECKS PASSED', result.stdout)


if __name__ == '__main__':
    unittest.main()
