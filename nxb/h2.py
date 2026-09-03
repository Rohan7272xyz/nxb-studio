"""H2: broker to runtime spawn.

Built, not specified. Every refusal here earned its place by firing during
nxb-010, and two of them are corrections to refusals that existed on paper.
"""

import json
import os
import uuid

from nxb.contract import ContractError
from nxb.receipt import utc_now

H2_CONTRACT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "contract", "h2.json",
)

with open(H2_CONTRACT_PATH, encoding="utf-8") as _h:
    H2_CONTRACT = json.load(_h)

_TYPES = {"str": str, "int": int, "float": float, "list": list, "dict": dict}


def h2_validate(schema_name, payload):
    schema = H2_CONTRACT["schemas"][schema_name]
    for name in schema.get("forbidden_fields", []):
        if name in payload:
            raise ContractError(f"{schema_name} must not carry {name!r}")
    for name, rule in schema["fields"].items():
        if rule.get("required") and name not in payload:
            raise ContractError(f"{schema_name} missing required {name!r}")
        if name not in payload:
            continue
        value, expected = payload[name], rule["type"]
        ok = isinstance(value, _TYPES[expected]) and not isinstance(value, bool)
        if expected == "float" and isinstance(value, int):
            ok = True
        if not ok:
            raise ContractError(f"{schema_name}.{name} must be {expected}")
        if rule.get("non_empty") and not str(value).strip():
            raise ContractError(f"{schema_name}.{name} must not be empty")
        if rule.get("enum") and value not in rule["enum"]:
            raise ContractError(f"{schema_name}.{name} not in {rule['enum']}")
    return payload


class SpawnHop:
    def __init__(self, ledger, adapter, *, observer="nxb-broker"):
        self.ledger = ledger
        self.adapter = adapter
        self.observer = observer
        self.last_handle = None

    def spawn(self, parent_receipt_id, *, work_dir, prompt, run_dir,
              start_timeout, hold_stdin_open=False, schema_path=None):
        """Spawn for an ACCEPTED H1 receipt. Returns an h2_return, never raises."""
        state = self.ledger.receipt_state(parent_receipt_id)
        if state is None:
            return self._ret("REFUSED", parent_receipt_id, reason="parent_unknown",
                             spawn_status="DID_NOT_START")
        if state != "ACCEPTED":
            # A REFUSED H1 dispatch must not become work. The old system had no
            # equivalent: a directive that failed validation simply vanished.
            return self._ret("REFUSED", parent_receipt_id,
                             reason=f"parent_not_accepted: {state}",
                             spawn_status="DID_NOT_START")
        prior = self.ledger.spawn_for(parent_receipt_id)
        if prior is not None:
            # RT-2. Control reaches here ONLY BECAUSE A SPAWN ROW EXISTS, so
            # this is the one branch where the broker holds direct evidence a
            # child ran, and it used to be the branch that reported it did not.
            # The work was never lost, only unreachable: the row carries the
            # runtime_ref and the runtime's own locator resolves it.
            #
            # `spawn_status` stays DID_NOT_START and IS KNOWN TO BE WRONG. The
            # honest value is "it started and I cannot tell you the outcome",
            # which is a new vocabulary term, and vocabulary is embargoed until
            # the blind arm reports. Exposing the ref is the half that can be
            # fixed now without pre-empting that decision.
            ref = prior["runtime_ref"]
            extra = {}
            if ref:
                extra["runtime_ref"] = ref
                try:
                    found = self.adapter.evidence_for(ref)
                except Exception:                              # noqa: BLE001
                    found = None
                if found:
                    extra["evidence_path"] = found
            return self._ret("REFUSED", parent_receipt_id, reason="already_spawned",
                             spawn_status="DID_NOT_START", **extra)

        try:
            result = self.adapter.spawn(
                work_dir=work_dir, prompt=prompt, run_dir=run_dir,
                start_timeout=start_timeout, hold_stdin_open=hold_stdin_open,
                schema_path=schema_path,
            )
        except Exception as exc:                       # noqa: BLE001
            # H1's dispatch() never raises and H2 must not either. An adapter
            # is third-party-shaped code by design, so the hop assumes nothing
            # about its manners. [nxb-011]
            self.ledger.record_spawn(
                parent_receipt_id, receipt=None,
                runtime_id=self.adapter.runtime_id, runtime_ref=None,
                state="REFUSED", reason="adapter_raised", now=utc_now(),
            )
            return self._ret("REFUSED", parent_receipt_id,
                             reason=f"adapter_raised: {type(exc).__name__}",
                             spawn_status="DID_NOT_START")

        if not result["started"]:
            # F-16b: the exit code here is 0 for a child we SIGINTed. We key on
            # the START SIGNAL, never on the exit code, or a killed spawn reads
            # as a success.
            self.ledger.record_spawn(
                parent_receipt_id, receipt=None,
                runtime_id=self.adapter.runtime_id, runtime_ref=None,
                state="REFUSED", reason=result["reason"], now=utc_now(),
            )
            return self._ret("REFUSED", parent_receipt_id,
                             reason=result["reason"], spawn_status="DID_NOT_START")

        receipt = {
            "receipt_id": "h2-" + uuid.uuid4().hex,
            "hop": "H2",
            "parent_receipt_id": parent_receipt_id,
            "observed_at": utc_now(),
            "observer": self.observer,
            "runtime_id": self.adapter.runtime_id,
            "runtime_ref": result["thread_id"],
            "pinned_model": self.adapter.model,
        }
        h2_validate("h2_receipt", receipt)
        self.ledger.record_spawn(
            parent_receipt_id, receipt=receipt,
            runtime_id=self.adapter.runtime_id,
            runtime_ref=result["thread_id"], state="STARTED", reason=None,
            now=utc_now(),
        )
        self.last_handle = result   # the live child, for a drain the caller owns
        return self._ret("STARTED", parent_receipt_id, receipt=receipt)

    @staticmethod
    def _ret(state, parent, *, receipt=None, reason=None, spawn_status=None,
             **extra):
        out = {"state": state, "parent_receipt_id": parent}
        out.update({k: v for k, v in extra.items() if v is not None})
        if receipt is not None:
            out["receipt"] = receipt
        if reason is not None:
            out["reason"] = reason
        if spawn_status is not None:
            out["spawn_status"] = spawn_status
        h2_validate("h2_return", out)
        return out
