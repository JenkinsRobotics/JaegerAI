"""Local sampled camera context; raw images never leave this process."""
import threading
import time


class LocalVision:
    def __init__(self, camera_index, model_path, report):
        self.camera_index = camera_index
        self.model_path = model_path
        self.report = report
        self.stopped = threading.Event()
        self.thread = None
        self.observation = ""
        self.observed_at = 0.0
        self._lock = threading.Lock()

    def latest(self):
        with self._lock:
            age = time.monotonic() - self.observed_at
            return f"{age:.0f} seconds ago: {self.observation}" if self.observation and age < 30 else ""

    def wait_for_observation(self, timeout):
        deadline = time.monotonic() + timeout
        while not self.stopped.is_set() and time.monotonic() < deadline:
            if self.latest():
                return True
            self.stopped.wait(0.1)
        return False

    def start(self):
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def close(self):
        self.stopped.set()
        if self.thread:
            self.thread.join(timeout=30)
        with self._lock:
            self.observation = ""

    def _run(self):
        camera = None
        try:
            import cv2
            import torch
            from PIL import Image
            from transformers import AutoModelForCausalLM

            self.report(camera="loading local vision")
            model = AutoModelForCausalLM.from_pretrained(
                self.model_path, trust_remote_code=True, local_files_only=True,
                torch_dtype=torch.float32,
            )
            model.eval()
            if torch.backends.mps.is_available():
                model.to("mps")
            if self.stopped.is_set():
                return
            camera = cv2.VideoCapture(self.camera_index)
            if not camera.isOpened():
                raise RuntimeError("Camera could not be opened; check macOS camera permission")
            while not self.stopped.is_set():
                for _ in range(3):
                    camera.grab()
                ok, frame = camera.read()
                if not ok:
                    raise RuntimeError("Camera stopped delivering frames")
                captured_at = time.monotonic()
                image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                image.thumbnail((768, 768))
                with torch.inference_mode():
                    answer = model.query(image, "Describe only this camera view in priority order: "
                        "1. Visible people, positions and observable actions, without identity or emotion guesses. "
                        "2. Clearly visible immediate hazards or moving objects; do not invent hazards. "
                        "3. Important objects and left/center/right, foreground/background relationships. "
                        "4. Likely room type and activity, explicitly labelling guesses and uncertainty. "
                        "Do not claim measured distances, hidden objects, or a view behind the camera.")
                with self._lock:
                    self.observation = str(answer.get("answer", ""))[:1500]
                    self.observed_at = captured_at
                self.report(camera="live" if self.latest() else "slow", camera_updated=time.time())
                self.stopped.wait(2)
        except Exception as exc:
            self.report(camera="error", error=f"Local vision: {exc}")
        finally:
            if camera is not None:
                camera.release()
