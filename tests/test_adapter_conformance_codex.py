"""Bind the conformance suite to the one adapter that exists today.

Adding an adapter means adding a fixture like this one and nothing else. The
properties live in tests/adapter_conformance.py and are not restated here.
"""

import unittest

import pytest

#: Every property here spawns a child and waits on a real deadline, so this
#: module is part of the deliberate slow target. See pytest.ini.
pytestmark = pytest.mark.spawns_children


from nxb.adapters.codex import CodexAdapter
from tests.adapter_conformance import AdapterConformance, AdapterFixture


class CodexFixture(AdapterFixture):
    """Codex's wire format. Three strings, declared by whoever knows the runtime."""

    def adapter(self, binary=None):
        return CodexAdapter(binary=binary) if binary else CodexAdapter()

    def start_line(self, thread_id):
        return '{"type":"thread.started","thread_id":"%s"}' % thread_id

    def malformed_start_line(self):
        return '{"type":"thread.started"}'

    def noise_line(self):
        return '{"type":"turn.started"}'


class CodexAdapterConformance(AdapterConformance, unittest.TestCase):
    fixture = CodexFixture()


if __name__ == "__main__":
    unittest.main()
