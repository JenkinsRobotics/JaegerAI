import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from jaeger_ai import hermes_worker


class HermesDelegateWorkerTests(unittest.TestCase):
    def test_hermes_delegate_uses_oneshot_stdio_without_webui(self):
        calls = []

        def fake_run(argv, **kwargs):
            calls.append((argv, kwargs))
            return SimpleNamespace(returncode=0, stdout="worker answer\n", stderr="")

        with (
            patch.object(hermes_worker.shutil, "which", return_value="/opt/bin/hermes"),
            patch.object(hermes_worker.subprocess, "run", side_effect=fake_run),
        ):
            result = hermes_worker.run("inspect the module", depth=0)

        self.assertTrue(result["delegated"])
        self.assertEqual(result["worker"], "hermes")
        self.assertEqual(result["transport"], "oneshot_stdio")
        self.assertEqual(result["answer"], "worker answer")
        self.assertEqual(
            calls[0][0],
            ["/opt/bin/hermes", "--oneshot", "inspect the module"],
        )
        self.assertTrue(all("port" not in str(arg).lower() for arg in calls[0][0]))
        self.assertTrue(all("session" not in str(arg).lower() for arg in calls[0][0]))

    def test_hermes_delegate_is_opt_in(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(hermes_worker.enabled())
        with patch.dict(os.environ, {"JAEGER_DELEGATE_WORKER": "hermes"}, clear=True):
            self.assertTrue(hermes_worker.enabled())


if __name__ == "__main__":
    unittest.main()
