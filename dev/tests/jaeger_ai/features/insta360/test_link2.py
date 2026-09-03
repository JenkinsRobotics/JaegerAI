from __future__ import annotations

from jaeger_ai.features.insta360.constants import PAN_MAX, TILT_MIN
from jaeger_ai.features.insta360.link2 import Insta360Link2


class _Gimbal:
    position = (0, 0)

    def write_pan_tilt(self, *, pan: int, tilt: int) -> None:
        self.position = (pan, tilt)

    def read_pan_tilt(self) -> tuple[int, int]:
        return self.position


def test_aim_clamps_to_hardware_limits() -> None:
    camera = object.__new__(Insta360Link2)
    camera._gimbal = _Gimbal()
    result = camera.aim(PAN_MAX + 1, TILT_MIN - 1)
    assert (result.pan, result.tilt) == (PAN_MAX, TILT_MIN)
