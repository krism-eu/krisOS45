#!/usr/bin/python3
"""Regression tests for release and build shell paths."""
from pathlib import Path
import os
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
        block = self.workflow_run_block('.github/workflows/publish-candidate.yml', 'Capture exact package provenance and drift')
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            bindir = directory / 'bin'
            bindir.mkdir()
            podman = bindir / 'podman'
            podman.write_text('''#!/bin/sh
case "$1" in
  run)
    case "$*" in
      *localhost/krisos45:candidate*firmware-provenance*) printf 'linux-firmware\t0:20260901-1.fc45.noarch\n' ;;
      *localhost/krisos45:candidate*owned-nevra*) printf 'base\t0:2.0-1.fc45.x86_64\n' ;;
      *ghcr.io/krism-eu/krisos45:m1*owned-nevra*) printf 'base\t0:1.0-1.fc45.x86_64\n' ;;
      *) exit 2 ;;
    esac
    ;;
  pull) exit 0 ;;
  *) exit 2 ;;
esac
''')
            podman.chmod(0o755)
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

    def test_adoption_pr_policy_fallback_keeps_other_errors_fatal(self):
        block = self.workflow_run_block('.github/workflows/sync-kriscc.yml', 'Open reviewed component adoption PR')
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            git = directory / 'git'
            git.write_text('''#!/bin/sh
case "$1" in
  rev-parse) printf '%s\\n' "$BASE_SHA" ;;
  diff) exit 1 ;;
  *) exit 0 ;;
esac
''')
            gh = directory / 'gh'
            gh.write_text('''#!/bin/sh
case "$PR_TEST_MODE" in
  success) printf '%s\\n' 'https://github.com/example/krisos/pull/1' ;;
  policy) echo 'GraphQL: GitHub Actions is not permitted to create or approve pull requests (createPullRequest)' >&2; exit 1 ;;
  network) echo 'connection refused' >&2; exit 1 ;;
esac
''')
            git.chmod(0o755)
            gh.chmod(0o755)
            for mode in ('success', 'policy', 'network'):
                with self.subTest(mode=mode):
                    summary = directory / f'{mode}.md'
                    result = subprocess.run(
                        ['bash', '-c', block], cwd=directory,
                        env={**os.environ, 'PATH': str(directory) + ':' + os.environ['PATH'],
                             'BASE_SHA': 'a' * 40, 'KRISCC_TAG': 'v0.8.2', 'GITHUB_RUN_ID': '123',
                             'GITHUB_REPOSITORY': 'example/krisos', 'GITHUB_STEP_SUMMARY': str(summary),
                             'PR_TEST_MODE': mode},
                        capture_output=True, text=True,
                    )
                    if mode == 'network':
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn('connection refused', result.stderr)
                    else:
                        self.assertEqual(result.returncode, 0, result.stderr)
                        output = summary.read_text()
                        if mode == 'policy':
                            self.assertIn('main has not changed', output)
                            self.assertIn('/compare/main...automation/kriscc-0.8.2-123?expand=1', output)
                            self.assertNotIn('Opened adoption PR', output)
                        else:
                            self.assertIn('Opened adoption PR: https://github.com/example/krisos/pull/1', output)

    def test_workflow_release_permissions_and_serialization_contract(self):
        build = (ROOT / '.github/workflows/build-m1.yml').read_text()
        publish = (ROOT / '.github/workflows/publish-candidate.yml').read_text()
        promote = (ROOT / '.github/workflows/promote-m1.yml').read_text()
        sync = (ROOT / '.github/workflows/sync-kriscc.yml').read_text()

        self.assertIn('permissions:\n  contents: read', build)
        self.assertIn('group: validate-m1-${{ github.ref }}', build)
        self.assertNotIn('packages: write', build)
        self.assertNotIn('id-token: write', build)
        self.assertIn('pull_request:', build)

        self.assertIn('group: publish-m1-candidate', publish)
        self.assertIn("if: github.ref == 'refs/heads/main'", publish)
        self.assertIn('packages: write', publish)
        self.assertIn('id-token: write', publish)
        self.assertNotIn('target="docker://ghcr.io/krism-eu/krisos45:m1"', publish)
        self.assertIn('Publish immutable candidate only', publish)

        self.assertIn('environment: stable-promotion', promote)
        self.assertIn('cosign verify', promote)
        self.assertIn('target="docker://ghcr.io/krism-eu/krisos45:m1"', promote)
        self.assertLess(promote.index('cosign verify'), promote.index('target="docker://ghcr.io/krism-eu/krisos45:m1"'))

        self.assertIn('pull-requests: write', sync)
        self.assertIn('resolved_base="$(./scripts/resolve-base.sh)"', sync)
        self.assertIn('--build-arg "BASE_IMAGE=$resolved_base"', sync)
        self.assertIn('sudo apt-get install -y podman skopeo', sync)
        self.assertNotIn('gh workflow run', sync)

if __name__ == '__main__':
    unittest.main()
