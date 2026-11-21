"""Operation Split-Key — hard multi-agent collaboration scenario.

Inspired by public multi-agent eval patterns (TheAgentCompany workplace
handoffs, MultiAgentBench coordination metrics, MetaGPT role split,
hidden-profile information asymmetry). Implemented in-repo because
external clone/fetch was blocked in the authoring environment.

The final clearance is only reconstructible when a lead agent
orchestrates four specialists with private knowledge shards.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


SCENARIO_ID = "operation_split_key"
SCENARIO_VERSION = "1.0.0"

# Ground truth — known only to the harness, never seeded into Lead.
VAULT_ID = "VX-9182"
ALPHA_SHARD = "91"
CRYPTO_SEED = 13
# beta = ((sum(ord(c) for c in vault_id) * seed) ^ 0xA5A5) % 65536 → 4 hex
EXPECTED_BETA = format(
    ((sum(ord(c) for c in VAULT_ID) * CRYPTO_SEED) ^ 0xA5A5) % 65536,
    "04X",
)
INTERMEDIATE_TOKEN = f"ORION-{ALPHA_SHARD}-{EXPECTED_BETA}"
EXPECTED_CLEARANCE = f"{INTERMEDIATE_TOKEN}-AUTH"

MISSION_GOAL = (
    "Reconstruct the Split-Key clearance for Project Orion. "
    "No single specialist holds the full answer. "
    "You are the lead: plan, delegate, recover from failure, and synthesize."
)


@dataclass(frozen=True)
class RoleSpec:
    name: str
    agent_type: str  # "lead" | "specialist"
    private_facts: dict[str, Any] = field(default_factory=dict)
    capability_grants: tuple[str, ...] = ()


ROLES: dict[str, RoleSpec] = {
    "lead": RoleSpec(
        name="Lead",
        agent_type="lead",
        private_facts={"mission": MISSION_GOAL},
        capability_grants=(
            "delegate.any",
            "blackboard.write.plan",
            "blackboard.read.all",
        ),
    ),
    "archivist": RoleSpec(
        name="Archivist",
        agent_type="specialist",
        private_facts={
            "vault_id": VAULT_ID,
            "alpha_shard": ALPHA_SHARD,
            "dossier": "Project Orion page 4 — alpha fragment sealed with vault id.",
        },
        capability_grants=("blackboard.write.intel", "memory.read.private"),
    ),
    "cryptanalyst": RoleSpec(
        name="Cryptanalyst",
        agent_type="specialist",
        private_facts={
            "seed": CRYPTO_SEED,
            "formula": "beta = ((sum(ord(c) for c in vault_id) * seed) ^ 0xA5A5) % 65536 as 04X",
        },
        capability_grants=("blackboard.write.crypto", "compute.beta"),
    ),
    "engineer": RoleSpec(
        name="Engineer",
        agent_type="specialist",
        private_facts={
            "recipe": "token = ORION-{alpha}-{beta}",
        },
        capability_grants=("blackboard.write.artifact", "assemble.token"),
    ),
    "qa": RoleSpec(
        name="QA",
        agent_type="specialist",
        private_facts={
            "rule": "clearance = {token}-AUTH only if alpha and beta receipts exist",
        },
        capability_grants=("blackboard.write.clearance", "verify.token"),
    ),
}


def compute_beta(vault_id: str, seed: int) -> str:
    return format(((sum(ord(c) for c in vault_id) * seed) ^ 0xA5A5) % 65536, "04X")


def assemble_token(alpha: str, beta: str) -> str:
    return f"ORION-{alpha}-{beta}"


def sign_clearance(token: str) -> str:
    return f"{token}-AUTH"


def verify_clearance(clearance: str) -> bool:
    return clearance == EXPECTED_CLEARANCE


DEPENDENCY_GRAPH: dict[str, tuple[str, ...]] = {
    "archivist": (),
    "cryptanalyst": ("archivist",),  # needs vault_id on board
    "engineer": ("archivist", "cryptanalyst"),
    "qa": ("engineer",),
}

# Blackboard keys used by the protocol
KEY_PLAN = "mission.plan"
KEY_INTEL = "intel.vault"
KEY_CRYPTO = "crypto.beta"
KEY_ARTIFACT = "artifact.token"
KEY_CLEARANCE = "mission.clearance"
KEY_RECEIPTS = "mission.receipts"
KEY_FAILURES = "mission.failures"
