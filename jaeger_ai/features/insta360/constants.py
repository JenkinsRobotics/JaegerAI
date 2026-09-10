"""Constants and hardware mappings for Insta360 Link and Link 2."""

from __future__ import annotations

# USB Vendor IDs and Product IDs
INSTA360_VID = 0x2E1A  # 11802

# Models
LINK1_PID = 0x4003      # 16387 - Original Insta360 Link
LINK2_PID = 0x4C04      # 19460 - Insta360 Link 2

SUPPORTED_DEVICES = {
    (INSTA360_VID, LINK2_PID): "Insta360 Link 2",
    (INSTA360_VID, LINK1_PID): "Insta360 Link",
}

# UVC Control Selectors & Extension Unit IDs
UNIT_PROCESSING = 2
UNIT_CAMERA_TERMINAL = 1
UNIT_XU1 = 9            # Extension Unit 1 (Proprietary gimbal & state registers)

# Extension Unit 1 Selectors
SEL_DEVICE_INFO = 0x01
SEL_SYSTEM_STATUS = 0x02
SEL_DEVICE_SN = 0x03
SEL_PAN_TILT = 0x1A     # 8 bytes: int32 tilt, int32 pan (little-endian)
SEL_FUNC_ENABLE = 0x1B  # 2 bytes bitmask: tracking, gestures, etc.

# Gimbal Range Limits (micro-degrees / internal units)
PAN_MIN = -540000
PAN_MAX = 540000
TILT_MIN = -360000
TILT_MAX = 360000

# Device Names as reported by macOS AVFoundation
CAMERA_DEVICE_NAME = "Insta360 Link 2"
AUDIO_DEVICE_NAME = "Insta360 Link 2"
VIRTUAL_CAMERA_NAME = "Insta360 Virtual Camera"
