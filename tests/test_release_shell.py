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
        self.assertNotIn(r'status" \n        "python3', source)
        self.assertIn('check "deployment identity matches independent bootc status" "python3', source)

    def test_boot_check_normalizes_quoted_ostree_value(self):
        source = (ROOT / 'tests/boot-check.sh').read_text()
        self.assertIn('if [[ "$deploy_path" == \\"*\\" ]]; then', source)
        self.assertIn('deploy_path="${deploy_path#\\"}"', source)
        self.assertIn('deploy_path="${deploy_path%\\"}"', source)
        self.assertIn('[[ "$deploy_path" =~ ^/ostree/boot\\.[01]/', source)

    def test_release_check_accepts_verified_recovery_boot(self):
        source = (ROOT / 'tests/release-check.sh').read_text()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            check = root / 'release-check.sh'
            check.write_text(source)

            boot = root / 'boot-check.sh'
            boot.write_text('#!/bin/sh\nexit 2\n')
            boot.chmod(0o755)

            result = subprocess.run(
                ['/bin/bash', str(check), 'check'],
                capture_output=True,
                text=True,
            )

            self.assertEqual(
                result.returncode,
                0,
                result.stdout + result.stderr,
            )
            self.assertIn(
                'PASS: base recovery boot checks',
                result.stdout,
            )
            self.assertIn(
                'KRISOS RECOVERY BOOT CHECKS PASSED',
                result.stdout,
            )

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


    def test_promotion_ancestry_gate_blocks_rollback_unless_explicitly_allowed(self):
        block = self.workflow_run_block('.github/workflows/promote-m1.yml', 'Enforce promotion ancestry')
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            skopeo = directory / 'skopeo'
            skopeo.write_text('''#!/bin/sh
last=''
for arg in "$@"; do last="$arg"; done
case "$last" in
  *krisos45:m1)
    case "$LINEAGE_MODE" in
      missing) echo 'manifest unknown' >&2; exit 1 ;;
      network) echo 'connection refused' >&2; exit 1 ;;
    esac
    case " $* " in
      *' --format '*) printf '%s\n' "$CURRENT_REV" ;;
      *) printf '{}\n' ;;
    esac
    ;;
  *@sha256:*)
    case " $* " in
      *' --format '*) printf '%s\n' "$CANDIDATE_REV" ;;
      *) printf '{}\n' ;;
    esac
    ;;
  *) exit 2 ;;
esac
''')
            git = directory / 'git'
            git.write_text('''#!/bin/sh
case "$1" in
  cat-file) exit 0 ;;
  merge-base)
    case "$LINEAGE_MODE" in
      descendant) exit 0 ;;
      rollback) exit 1 ;;
      *) exit 2 ;;
    esac
    ;;
  *) exit 2 ;;
esac
''')
            skopeo.chmod(0o755)
            git.chmod(0o755)
            current = 'a' * 40
            candidate = 'b' * 40
            digest = 'sha256:' + 'c' * 64
            cases = (
                ('descendant', 'false', 0),
                ('rollback', 'false', 1),
                ('rollback', 'true', 0),
                ('missing', 'false', 0),
                ('network', 'false', 1),
            )
            for mode, allow, expected in cases:
                with self.subTest(mode=mode, allow=allow):
                    result = subprocess.run(
                        ['bash', '-c', block], cwd=directory,
                        env={**os.environ, 'PATH': str(directory) + ':' + os.environ['PATH'],
                             'RUNNER_TEMP': str(directory), 'HOME': str(directory),
                             'CANDIDATE_DIGEST': digest, 'ALLOW_ROLLBACK': allow,
                             'CURRENT_REV': current, 'CANDIDATE_REV': candidate,
                             'LINEAGE_MODE': mode},
                        capture_output=True, text=True,
                    )
                    self.assertEqual(result.returncode == 0, expected == 0, result.stderr)
                    if mode == 'rollback' and allow == 'false':
                        self.assertIn('Refusing rollback/non-descendant promotion', result.stderr)
                    if mode == 'missing':
                        self.assertIn('No existing m1 tag', result.stdout)
                    if mode == 'network':
                        self.assertIn('connection refused', result.stderr)

    def test_workflow_release_permissions_and_serialization_contract(self):
        publish = (ROOT / '.github/workflows/publish-candidate.yml').read_text()
        promote = (ROOT / '.github/workflows/promote-m1.yml').read_text()
        sync = (ROOT / '.github/workflows/sync-kriscc.yml').read_text()

        self.assertIn('group: publish-m1-candidate', publish)
        self.assertIn("if: github.ref == 'refs/heads/main'", publish)
        self.assertIn('packages: write', publish)
        self.assertIn('id-token: write', publish)
        self.assertNotIn('target="docker://ghcr.io/krism-eu/krisos45:m1"', publish)
        self.assertIn('Publish immutable candidate only', publish)

        self.assertIn('environment: stable-promotion', promote)
        self.assertIn('allow_rollback:', promote)
        self.assertIn('default: false', promote)
        self.assertIn('fetch-depth: 0', promote)
        self.assertIn('git merge-base --is-ancestor', promote)
        self.assertIn('org.opencontainers.image.revision', promote)
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
