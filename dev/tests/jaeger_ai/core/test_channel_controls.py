"""Channel controls with local transport fixture; no SDK network/OS credentials."""
from types import SimpleNamespace
import pytest






def test_handler_gate_blocks_disconnect_during_work_and_new_admission_after_stop():
    from jaeger_ai.plugins._messaging import handler_admission,stop_handlers,resume_handlers
    bridge=SimpleNamespace()
    with handler_admission(bridge):
        with pytest.raises(RuntimeError,match='active'):stop_handlers(bridge)
    stop_handlers(bridge)
    with pytest.raises(RuntimeError,match='disconnecting'):
        with handler_admission(bridge):pytest.fail('new work admitted')
    resume_handlers(bridge)
    with handler_admission(bridge):pass




