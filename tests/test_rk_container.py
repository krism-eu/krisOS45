#!/usr/bin/python3
"""Real Fedora DNF/RPM integration in a DISPOSABLE container, never on a host.

Only the VM-specific mount/SELinux guard is replaced. Solver, downloads,
signature checks, RPM tests, real install/remove and intent writes are exercised.
This test does not claim to test OverlayFS, reboot or deployment recovery.
"""
import importlib.machinery
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile

if os.environ.get('RK_DISPOSABLE_CONTAINER_TEST') != '1' or not Path('/run/.containerenv').exists():
    raise SystemExit('Run only through the disposable Podman CI test')
_loader = importlib.machinery.SourceFileLoader('rk', '/usr/bin/rk')
_spec = importlib.util.spec_from_loader(_loader.name, _loader)
rk = importlib.util.module_from_spec(_spec)
_loader.exec_module(rk)
if subprocess.run(['rpm', '-q', 'tree'], stdout=subprocess.DEVNULL).returncode == 0:
    raise SystemExit('Fixture tree must be absent in the image')
with tempfile.TemporaryDirectory() as directory:
    rk.STATE = Path(directory)
    (rk.STATE / 'packages.list').write_text('')
    fake_mount = (
        'fake overlay rw,relatime,lowerdir=/usr,'
        'upperdir=/tmp/fake-upper,workdir=/tmp/fake-work'
    )
    rk.mount_snapshot = lambda: fake_mount
    rk.guard = lambda: fake_mount
    rk.transact('add', {'tree'})
    subprocess.run(['/usr/bin/tree', '--version'], check=True)
    assert (rk.STATE / 'packages.list').read_text() == 'tree\n'
    assert oct((rk.STATE / 'packages.list').stat().st_mode & 0o777) == '0o644'
    assert not (rk.STATE / 'pending').exists()
    rk.refresh_overlay()
    assert (rk.STATE / 'pending').read_text() == 'Refresh requested: rebuild overlay after reboot\n'
    # The disposable container cannot reboot into the recovery hook; clear only
    # this test marker so the remaining real remove/sync checks can continue.
    (rk.STATE / 'pending').unlink()
    # Real libdnf5 no-op: an explicit add of the already-installed request must
    # not create pending or invoke a failing empty RPM transaction.
    rk.transact('add', {'tree'})
    assert (rk.STATE / 'packages.list').read_text() == 'tree\n'
    assert not (rk.STATE / 'pending').exists()
    rk.transact('rm', {'tree'})
    assert not Path('/usr/bin/tree').exists()
    assert (rk.STATE / 'packages.list').read_text() == ''
    rk.transact('sync', set())
    assert oct((rk.STATE / 'packages.list').stat().st_mode & 0o777) == '0o644'

    # Exercise rk plan's real unprivileged dry-run path. Use a fresh interpreter
    # via subprocess rather than os.fork(): the parent has already executed
    # libdnf5 transactions (internal threads, SWIG-held mutexes) and a fork
    # would only inherit the calling thread, risking an unrecoverable deadlock
    # in CI. HOME points at a writable scratch directory so the unprivileged
    # libdnf5 user cache does not attempt to write into /root.
    plan_state = Path(directory) / 'plan-user'
    plan_state.mkdir()
    (plan_state / 'packages.list').write_text('')
    plan_state_home = Path(directory) / 'plan-user-home'
    plan_state_home.mkdir()
    os.chmod(directory, 0o755)
    os.chmod(plan_state, 0o755)
    os.chmod(plan_state / 'packages.list', 0o644)
    os.chmod(plan_state_home, 0o777)
    plan_script = f"""
import importlib.machinery, importlib.util, sys
from pathlib import Path
_loader = importlib.machinery.SourceFileLoader('rk', '/usr/bin/rk')
_spec = importlib.util.spec_from_loader(_loader.name, _loader)
rk = importlib.util.module_from_spec(_spec)
_loader.exec_module(rk)
rk.STATE = Path({str(plan_state)!r})
rk.guard = lambda: {fake_mount!r}
sys.argv = ['/usr/bin/rk', 'plan', 'tree']
rk.main()
"""
    subprocess.run(
        ['python3', '-c', plan_script],
        user=65534,
        group=65534,
        extra_groups=[],
        env={**os.environ, 'HOME': str(plan_state_home)},
        check=True,
    )
print('PASS: real signed RPM install/remove/refresh, package intent and unprivileged plan')
