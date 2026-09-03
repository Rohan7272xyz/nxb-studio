"""NEXUS Bridge, H1 only.

Scope is deliberately one hop: a dispatcher hands the broker an envelope and
gets back a receipt, a refusal, or an honest "I do not know". H2 (spawn),
H3 (report), H4 (deliver), the canary and provenance are NOT here. See
docs/SPEC-RECEIPTS-LIVENESS.md.
"""

from nxb.contract import CONTRACT, validate, ContractError
from nxb.dispatch import Broker
from nxb.ledger import Ledger
from nxb.runtimes import register, RegistrationRefused

__all__ = [
    "CONTRACT", "validate", "ContractError",
    "Broker", "Ledger", "register", "RegistrationRefused",
]
