"""Shared, bounded transport policy. Never replay an ambiguously executed turn."""
import os
import math
import threading
import time
import urllib.error
import subprocess


class ClassifiedError(RuntimeError):
    """An adapter-owned outcome category, distinct from response prose."""
    def __init__(self, category, message):
        super().__init__(message)
        self.error_category = category


def timeout_setting(name, default=300.0):
    raw = os.environ.get(name, "").strip()
    value = float(raw) if raw else default
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a finite positive number of seconds")
    return value


def failure_category(exc):
    if isinstance(exc, ClassifiedError):
        return exc.error_category
    if isinstance(exc, subprocess.TimeoutExpired):
        return "timeout"
    if isinstance(exc, urllib.error.HTTPError):
        return f"http_{exc.code}"
    if isinstance(exc, urllib.error.URLError):
        return failure_category(exc.reason)
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, ConnectionRefusedError):
        return "connection_refused"
    return "transport_error"


class CircuitOpen(ConnectionError):
    pass


class CircuitBreaker:
    """Briefly fail fast after repeated transport errors, then allow a probe."""
    def __init__(self, threshold=3, cooldown=30.0):
        self.threshold, self.cooldown = threshold, cooldown
        self.failures = 0
        self.until = 0.0
        self.lock = threading.Lock()

    def check(self):
        with self.lock:
            if time.monotonic() < self.until:
                raise CircuitOpen("upstream circuit open after repeated transport errors; retry shortly")

    def success(self):
        with self.lock:
            self.failures, self.until = 0, 0.0

    def failure(self):
        with self.lock:
            self.failures += 1
            if self.failures >= self.threshold:
                self.until = time.monotonic() + self.cooldown
