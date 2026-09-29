#!/usr/bin/python3
"""Execute the shell paths that previously lost home/admin arguments."""
from pathlib import Path
import os
import re
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ReleaseShell(unittest.TestCase):
    def test_home_check_passes_the_actual_home_to_readlink(self):
        line = next(line for line in (ROOT / 'tests/release-check.sh').read_text().splitlines() if 'run_check "admin home resolves below /var/home"' in line)
        with tempfile.TemporaryDirectory() as directory:
            stub = Path(directory) / 'readlink'
            stub.write_text('#!/bin/sh\n[ "$1" = -f ] || exit 1\n[ "$2" = -- ] || exit 1\n[ "$3" = /home/qa ] || exit 1\nprintf "%s\\n" /var/home/qa\n')
            stub.chmod(0o755)
            script = 'run_check() { shift; "$@"; }\nadmin_home=/home/qa\nexpected_admin_user=qa\n' + line
            result = subprocess.run(['bash', '-c', script], env={**os.environ, 'PATH': directory + ':' + os.environ['PATH']}, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_vm_harness_transmits_admin_user(self):
        source = (ROOT / 'tests/run-release-vm.sh').read_text()
        function = re.search(r'run_release_check\(\) \{.*?\n\}', source, re.S).group()
        script = '''ssh() { printf '%s\\n' "$@"; }
ssh_opts=()
target=qa@example
expected_kriscc=version
expected_image=image
expected_admin_user=desktop
token=token
remote_dir=/tmp/qa
''' + function + '\nrun_release_check check\n'
        result = subprocess.run(['bash', '-c', script], capture_output=True, text=True, check=True)
        self.assertIn("KRISOS_EXPECT_ADMIN_USER='desktop'", result.stdout)
        self.assertIn("KRISOS_E2E_PREVIOUS_DEPLOYMENT=''", result.stdout)


    def test_boot_check_deployment_crosscheck_has_no_literal_backslash_n_command(self):
        source = (ROOT / 'tests/boot-check.sh').read_text()
        self.assertNotIn('status" \n        "python3', source)
        self.assertIn('check "deployment identity matches independent bootc status" "python3', source)

    def test_overlay_sentinel_targets_real_upperdir(self):
        source = (ROOT / 'tests/release-check.sh').read_text()
        self.assertIn('sentinel_dir="/usr/share/krisos-e2e"', source)
        self.assertIn('/var/lib/krisos/upper/share/krisos-e2e/', source)
        self.assertNotIn('/usr/local/share/.krisos-release-e2e', source)
        self.assertIn('sync -f "$upper_sentinel"', source)

    def test_vm_harness_tests_switch_before_same_deployment_reboot(self):
        source = (ROOT / 'tests/run-release-vm.sh').read_text()
        prepare = source.index('run_release_check prepare-switch')
        switch = source.index('sudo bootc switch')
        verify = source.index('run_release_check verify-switch')
        same_reboot = source.index('run_release_check prepare-reboot')
        recovery = source.index('run_release_check prepare-recovery')
        self.assertLess(prepare, switch)
        self.assertLess(switch, verify)
        self.assertLess(verify, same_reboot)
        self.assertLess(same_reboot, recovery)


    @staticmethod
    def workflow_run_block(workflow, step_name):
        lines = (ROOT / workflow).read_text().splitlines()
        marker = f'      - name: {step_name}'
        start = lines.index(marker)
        run = next(i for i in range(start + 1, len(lines)) if lines[i] == '        run: |')
        body = []
        for line in lines[run + 1:]:
            if line.startswith('      - name: '):
                break
            if line.startswith('          '):
                body.append(line[10:])
            elif not line:
                body.append('')
            else:
                break
        return '\n'.join(body) + '\n'

    def test_containerignore_does_not_hide_containerfile_copy_sources(self):
        ignored = {
            line.strip().rstrip('/')
            for line in (ROOT / '.containerignore').read_text().splitlines()
            if line.strip() and not line.lstrip().startswith('#') and '*' not in line
        }
        for line in (ROOT / 'Containerfile').read_text().splitlines():
            stripped = line.strip()
            if not (stripped.startswith('COPY ') or stripped.startswith('ADD ')):
                continue
            tokens = shlex.split(stripped)
            if any(token.startswith('--from=') for token in tokens[1:]):
                continue
            positional = [token for token in tokens[1:] if not token.startswith('--')]
            for source in positional[:-1]:
                top = source.lstrip('./').split('/', 1)[0]
                self.assertNotIn(top, ignored, f'{line!r} uses an ignored build-context source')

    def test_package_drift_falls_back_to_anonymous_after_login_failure(self):
        block = self.workflow_run_block('.github/workflows/build-m1.yml', 'Capture exact package provenance and drift')
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            bindir = directory / 'bin'
            bindir.mkdir()
            sudo = bindir / 'sudo'
            sudo.write_text('''#!/bin/sh
if [ "$1" = podman ]; then shift; fi
case "$1" in
  run)
    case "$*" in
      *localhost/krisos45:m1*firmware-provenance*) printf 'linux-firmware\t0:20260901-1.fc45.noarch\n' ;;
      *localhost/krisos45:m1*owned-nevra*) printf 'base\t0:2.0-1.fc45.x86_64\n' ;;
      *ghcr.io/krism-eu/krisos45:m1*owned-nevra*) printf 'base\t0:1.0-1.fc45.x86_64\n' ;;
      *) exit 2 ;;
    esac
    ;;
  pull) exit 0 ;;
  *) exit 2 ;;
esac
''')
            sudo.chmod(0o755)
            skopeo = bindir / 'skopeo'
            skopeo.write_text('''#!/bin/sh
case "$1" in
  login) exit 1 ;;
  inspect) printf 'sha256:%064d\n' 1 ;;
  *) exit 2 ;;
esac
''')
            skopeo.chmod(0o755)
            result = subprocess.run(
                ['bash', '-c', block],
                cwd=directory,
                env={
                    **os.environ,
                    'PATH': str(bindir) + ':' + os.environ['PATH'],
                    'GHCR_USER': 'qa',
                    'GHCR_TOKEN': 'token-for-test',
                    'RUNNER_TEMP': str(directory),
                },
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('authenticated GHCR access unavailable; trying anonymous access', result.stdout)
            self.assertTrue((directory / 'previous-m1.digest').is_file())
            self.assertIn('-base', (directory / 'package-drift.txt').read_text())
            self.assertFalse(any(directory.glob('krisos-ghcr-auth.*')))

    def test_workflow_release_permissions_and_serialization_contract(self):
        build = (ROOT / '.github/workflows/build-m1.yml').read_text()
        sync = (ROOT / '.github/workflows/sync-kriscc.yml').read_text()
        promote = (ROOT / '.github/workflows/promote-m1.yml').read_text()
        self.assertIn('group: build-m1-${{ github.ref }}', build)
        self.assertIn("expected = 'group: build-m1-$' + '{{ github.ref }}'", build)
        self.assertNotIn("grep -Fq 'group: build-m1-${{ github.ref }}'", build)
        self.assertIn('packages: write', build)
        self.assertIn('pull-requests: write', sync)
        self.assertNotIn('gh workflow run', sync)
        self.assertIn('group: promote-m1', promote)
        self.assertIn('actions: read', promote)
        self.assertNotIn('deployments: read', promote)
        self.assertIn('Require protected stable-promotion environment', promote)
        self.assertIn('required_reviewers', promote)


if __name__ == '__main__':
    unittest.main()
