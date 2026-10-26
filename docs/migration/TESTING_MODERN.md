# Modern Testing Architecture (v0.13.0)

**Date:** 2026-10-24
**Impact:** Contributors and developers

## Summary

JaegerAI's testing architecture has been modernized based on **2024-2026 AI
engineering research**. The old 10-tier system is replaced with a focused
**4-tier architecture** that minimizes test count while maximizing confidence.

## The 4 Tiers

```
dev/tests/
├── contracts/     # Tool/API schema validation (fast, deterministic)
├── properties/    # Property-based testing with Hypothesis
├── trajectories/  # Scripted LLM end-to-end paths
└── acceptance/    # Live Gateway/WebUI tests
```

### Tier 1: Contract Tests (`--contracts`)

**Purpose:** Validate that tools, APIs, and protocols conform to their schemas.

**Speed:** < 10 seconds

**What it tests:**
- Tool input/output schemas (Pydantic models)
- Gateway REST API contracts
- MCP/A2A protocol contracts
- Bridge NDJSON message formats

**Example:**
```python
# dev/tests/contracts/test_tool_schemas.py
import pytest
from jaeger_ai.contract.schemas import ToolCall, ToolResult

def test_write_file_contract():
    # Valid call
    call = ToolCall(name="write_file", arguments={"path": "test.txt", "content": "hello"})
    assert call.name == "write_file"
    
    # Invalid call (missing required field)
    with pytest.raises(ValidationError):
        ToolCall(name="write_file", arguments={"path": "test.txt"})  # missing content
```

### Tier 2: Property Tests (`--properties`)

**Purpose:** Test invariants that should always hold, using auto-generated inputs.

**Speed:** < 30 seconds

**What it tests:**
- Memory operations are idempotent
- State transitions are valid
- Effect ledger prevents double-execution
- Session state is consistent

**Example:**
```python
# dev/tests/properties/test_memory_properties.py
from hypothesis import given, strategies as st

def test_add_fact_is_idempotent(memory_store):
    """Adding the same fact twice doesn't create duplicates."""
    memory_store.add_fact("user.name", "Alice")
    memory_store.add_fact("user.name", "Alice")
    facts = memory_store.list_facts("user.name")
    assert len(facts) == 1

@given(st.text(min_size=1), st.text())
def test_fact_roundtrip(key, value, memory_store):
    """Any fact added can be retrieved with the same value."""
    memory_store.add_fact(key, value)
    assert memory_store.get_fact(key) == value
```

### Tier 3: Trajectory Tests (`--trajectories`)

**Purpose:** Test full agent execution paths with scripted LLM responses.

**Speed:** < 60 seconds

**What it tests:**
- Single-turn task completion
- Multi-turn conversations
- Tool chaining (multiple tools in sequence)
- Error recovery paths

**Example:**
```python
# dev/tests/trajectories/test_single_turn.py
from dev.tests.helpers.blueprint_runtime import BlueprintRuntime

def test_file_write_trajectory():
    """Agent writes a file correctly."""
    rt = BlueprintRuntime()
    rt.when_tool("write_file", result={"ok": True})
    
    result = rt.run_turn("Create a file called test.txt with content 'hello'")
    
    # Verify trajectory, not just final output
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "write_file"
    assert result.tool_calls[0].args["path"] == "test.txt"
    assert result.tool_calls[0].args["content"] == "hello"
    assert result.status == "completed"
```

### Tier 4: Acceptance Tests (`--acceptance`)

**Purpose:** Test the full system with real components (Gateway, WebUI, etc.).

**Speed:** Variable (requires running services)

**What it tests:**
- End-to-end Gateway lifecycle
- WebUI → Gateway → Runtime flow
- Bridge protocol end-to-end
- Scheduler execution
- Multi-client scenarios

**Example:**
```python
# dev/tests/acceptance/test_gateway_e2e.py
import pytest
import requests

@pytest.fixture
def gateway():
    """Requires running Gateway on :33418."""
    resp = requests.get("http://127.0.0.1:33418/health")
    assert resp.status_code == 200
    return "http://127.0.0.1:33418"

def test_send_message(gateway):
    """Send a message and receive a response."""
    # Create session
    resp = requests.post(f"{gateway}/v1/sessions", json={"name": "test"})
    session_id = resp.json()["id"]
    
    # Send message
    resp = requests.post(
        f"{gateway}/v1/sessions/{session_id}/turns",
        json={"message": "Hello"}
    )
    assert resp.status_code == 200
    assert "response" in resp.json()
```

## Running Tests

```bash
# Fast feedback loop (contracts + properties + trajectories)
dev/scripts/run_tests.sh
# or explicitly:
dev/scripts/run_tests.sh --contracts
dev/scripts/run_tests.sh --properties
dev/scripts/run_tests.sh --trajectories

# Full suite including acceptance (requires Gateway running)
dev/scripts/run_tests.sh --all

# Single tier
dev/scripts/run_tests.sh --contracts -k test_write_file
```

## Key Principles (from 2024-2026 Research)

1. **Layer Isolation** — Test deterministic infrastructure (routing, state,
   permissions) separately from LLM calls. Use scripted responses for LLM.

2. **Trajectory Evaluation** — Score the agent's decision process, not just
   the final output. A correct answer via wrong path is still wrong.

3. **Contract Testing** — Define schemas upfront. Validate inputs/outputs at
   every boundary.

4. **Property-Based Testing** — Test invariants (idempotency, consistency)
   rather than specific examples. Auto-generate edge cases.

5. **Deterministic Mock Boundaries** — Replace LLM with scripted responses
   for infrastructure tests. Eliminates flakiness.

## Migration from Old 10-Tier System

| Old Tier | New Tier | Notes |
|----------|----------|-------|
| `--smoke` | `--contracts` | Basic validation |
| `--unit` | `--contracts` + `--properties` | Split by purpose |
| `--integration` | `--trajectories` | End-to-end paths |
| `--production-path` | `--trajectories` | Scripted LLM paths |
| `--acceptance` | `--acceptance` | Unchanged |
| `--security` | `--contracts` + specific tests | Security contracts |
| `--fault-injection` | `--trajectories` | Error paths |
| `--external-eval` | Separate harness | Not in default suite |
| `--soak` | Manual/CI only | Long-running tests |
| `--full` | `--all` | Everything |

## Writing New Tests

### Contract Test
```python
# dev/tests/contracts/test_my_tool.py
from jaeger_ai.contract.schemas import validate_tool_call

def test_my_tool_accepts_valid_input():
    validate_tool_call("my_tool", {"required_field": "value"})

def test_my_tool_rejects_invalid_input():
    with pytest.raises(ValidationError):
        validate_tool_call("my_tool", {"wrong_field": "value"})
```

### Property Test
```python
# dev/tests/properties/test_my_state.py
from hypothesis import given, strategies as st

@given(st.text(), st.integers())
def test_my_state_invariant(key, value):
    state = MyState()
    state.set(key, value)
    assert state.get(key) == value  # Invariant: set then get returns same
```

### Trajectory Test
```python
# dev/tests/trajectories/test_my_flow.py
from dev.tests.helpers.blueprint_runtime import BlueprintRuntime

def test_my_flow():
    rt = BlueprintRuntime()
    rt.when_user_says("do something")
    rt.when_tool("my_tool", result={"success": True})
    
    result = rt.run_turn("do something")
    assert result.status == "completed"
    assert result.tool_calls[0].name == "my_tool"
```

## CI Integration

```yaml
# .github/workflows/ci.yml
jobs:
  contracts:
    runs-on: ubuntu-latest
    steps:
      - run: dev/scripts/run_tests.sh --contracts
  
  properties:
    runs-on: ubuntu-latest
    steps:
      - run: dev/scripts/run_tests.sh --properties
  
  trajectories:
    runs-on: ubuntu-latest
    steps:
      - run: dev/scripts/run_tests.sh --trajectories
  
  acceptance:
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'  # Only on main
    steps:
      - run: jaeger gateway daemon &
      - run: dev/scripts/run_tests.sh --acceptance
```

## Questions?

See [README.md](README.md) for the migration guide index.
