"""Bind the conformance suite to the second adapter.

Written AFTER the suite was committed at 466c731, and the suite was written
without reading nxb/adapters/claude_code.py. The wire format below comes from
contract/runtimes/claude_code.json `spawned_child`, which is published contract.

It passed 15/15 on its first run, and that is mostly information about the SUITE:
spawn, drain and the kill path live in one shared ProcessAdapter base while each
adapter is a thin subclass, so the shared properties were being tested twice
against one implementation. C14 and C15 were added afterwards to aim at the
surface that actually differs per adapter, and C14 immediately failed on BOTH.
"""
import unittest

import pytest
from nxb.adapters.claude_code import ClaudeCodeAdapter
from tests.adapter_conformance import AdapterConformance, AdapterFixture

#: Every property here spawns a child and waits on a real deadline, so this
#: module is part of the deliberate slow target. See pytest.ini.
pytestmark = pytest.mark.spawns_children



class ClaudeCodeFixture(AdapterFixture):
    def adapter(self, binary=None):
        return ClaudeCodeAdapter(binary=binary) if binary else ClaudeCodeAdapter()

    def start_line(self, thread_id):
        return '{"type":"system","subtype":"init","session_id":"%s"}' % thread_id

    def malformed_start_line(self):
        return '{"type":"system","subtype":"init"}'

    def noise_line(self):
        return '{"type":"system","subtype":"thinking_tokens"}'


class ClaudeCodeAdapterConformance(AdapterConformance, unittest.TestCase):
    fixture = ClaudeCodeFixture()


if __name__ == "__main__":
    unittest.main()
