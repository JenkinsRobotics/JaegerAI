"""Mark visible faces locally on the preview; leave model input unannotated."""
from pathlib import Path
import time


class PersonOverlay:
    def __init__(self):
        import cv2
        self.detector = cv2.FaceDetectorYN.create(
            str(Path.home() / ".cache/jaeger/models/yunet.onnx"), "", (640, 360), 0.85
        )
        self.boxes = []
        self.frame_size = (640, 360)
        self.next_detection = 0.0

    def primary_face_offset(self) -> tuple[float, float] | None:
        """Return normalized (dx, dy) in [-0.5, 0.5] of the largest visible face relative to frame center."""
        if not len(self.boxes):
            return None
        fw, fh = self.frame_size
        if fw <= 0 or fh <= 0:
            return None
        best = max(self.boxes, key=lambda b: int(b[2]) * int(b[3]))
        cx = (float(best[0]) + float(best[2]) * 0.5) / float(fw)
        cy = (float(best[1]) + float(best[3]) * 0.5) / float(fh)
        return (cx - 0.5, cy - 0.5)

    def render(self, jpeg: bytes) -> bytes:
        import cv2
        import numpy as np

        image = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            return jpeg
        self.frame_size = (int(image.shape[1]), int(image.shape[0]))
        if time.monotonic() >= self.next_detection:
            self.next_detection = time.monotonic() + 0.25
            self.detector.setInputSize((image.shape[1], image.shape[0]))
            _, faces = self.detector.detect(image)
            self.boxes = [] if faces is None else faces[:, :4].astype(int)
        for x, y, width, height in self.boxes:
            cv2.rectangle(image, (x, y), (x + width, y + height), (128, 235, 70), 2)
            cv2.putText(image, "Person", (x, max(16, y - 4)), cv2.FONT_HERSHEY_SIMPLEX,
                        0.5, (128, 235, 70), 1)
        if not len(self.boxes):
            return jpeg
        ok, encoded = cv2.imencode(".jpg", image)
        return encoded.tobytes() if ok else jpeg
