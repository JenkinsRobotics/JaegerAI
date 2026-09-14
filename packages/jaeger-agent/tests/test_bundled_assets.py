from hashlib import sha256

from jaeger_agent.core.assets import DEFAULT_SILERO_MODEL
from jaeger_agent.core.config import MultimodalConfig


def test_vad_asset_installs_with_the_exact_reference_bytes():
    assert DEFAULT_SILERO_MODEL.is_file()
    assert sha256(DEFAULT_SILERO_MODEL.read_bytes()).hexdigest() == (
        'b6875a49bacf6d57826a7e0a549d5a05d769ee34405cadcc9ff8b4442544b1f9')
    assert MultimodalConfig().silero_model_path == str(DEFAULT_SILERO_MODEL)
    assert 'MIT License' in DEFAULT_SILERO_MODEL.with_name('LICENSE.txt').read_text()


def test_default_vad_runs_without_a_home_directory_model():
    import numpy as np
    from jaeger_agent.core.policy import SileroVad
    vad = SileroVad()
    probability = vad.probability(np.zeros(480, dtype=np.float32))
    assert np.isfinite(probability) and 0 <= probability < vad.open_p
