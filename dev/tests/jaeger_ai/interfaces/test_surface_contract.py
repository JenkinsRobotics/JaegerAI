def test_every_bridge_operation_has_an_explicit_swift_classification():
    from jaeger_ai.interfaces.bridge import BRIDGE_COMMANDS, BRIDGE_QUERIES
    from jaeger_ai.interfaces.surface_contract import (
        SWIFT_COMMAND_SUPPORT, SWIFT_QUERY_SUPPORT,
    )

    assert set(SWIFT_QUERY_SUPPORT) == set(BRIDGE_QUERIES)
    assert set(SWIFT_COMMAND_SUPPORT) == set(BRIDGE_COMMANDS)
    allowed = {"dedicated", "generic", "bridge_only"}
    assert set(SWIFT_QUERY_SUPPORT.values()) <= allowed
    assert set(SWIFT_COMMAND_SUPPORT.values()) <= allowed
