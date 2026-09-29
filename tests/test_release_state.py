#!/usr/bin/python3
import json
import importlib.machinery
import importlib.util
from pathlib import Path
import unittest

_loader = importlib.machinery.SourceFileLoader('release_state', str(Path(__file__).with_name('release-state.py')))
_spec = importlib.util.spec_from_loader(_loader.name, _loader)
state = importlib.util.module_from_spec(_spec)
_loader.exec_module(state)


def deployment(ref):
    return {'image': {'image': {'image': ref}}}


class ReleaseState(unittest.TestCase):
    def test_only_booted_exact_reference_passes(self):
        state.check_image({'status': {'booted': deployment('expected')}}, 'expected')
        for booted in (None, {}, deployment('expected-extra'), deployment('old')):
            with self.subTest(booted=booted), self.assertRaises(ValueError):
                state.check_image({'status': {'booted': booted, 'staged': deployment('expected'), 'rollback': deployment('expected')}}, 'expected')


    def test_bootc_ostree_identity_is_independent_oracle(self):
        checksum = 'a' * 64
        document = {
            'status': {
                'booted': {
                    'ostree': {
                        'stateroot': 'default',
                        'checksum': checksum,
                        'deploySerial': 2,
                    }
                }
            }
        }
        state.check_deployment(document, f'default/{checksum}/2')
        for bad in (
            {},
            {'status': {'booted': {'ostree': None}}},
            {'status': {'booted': {'ostree': {'stateroot': 'default', 'checksum': 'short', 'deploySerial': 2}}}},
            {'status': {'booted': {'ostree': {'stateroot': 'default', 'checksum': checksum, 'deploySerial': '2'}}}},
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                state.check_deployment(bad, f'default/{checksum}/2')
        with self.assertRaises(ValueError):
            state.check_deployment(document, f'default/{checksum}/3')

    def test_rk_requires_complete_healthy_state(self):
        healthy_data = {
            'schema': 1,
            'overlay': 'ready',
            'mount': '42 overlay rw',
            'overlay_error': '',
            'pending_recovery': False,
            'needs_sync': False,
            'requests': ['tree'],
        }
        state.check_rk(json.dumps(healthy_data))

        invalid_values = [
            '',
            json.dumps({**healthy_data, 'schema': 2}),
            json.dumps({**healthy_data, 'overlay': 'degraded'}),
            json.dumps({**healthy_data, 'pending_recovery': True}),
            json.dumps({**healthy_data, 'needs_sync': True}),
            json.dumps({key: value for key, value in healthy_data.items() if key != 'requests'}),
        ]
        for invalid in invalid_values:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                state.check_rk(invalid)


if __name__ == '__main__':
    unittest.main()
