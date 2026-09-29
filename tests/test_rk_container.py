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
print('PASS: real signed RPM install/remove, immutable identities and package intent')
