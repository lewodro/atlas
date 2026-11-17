from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import main


class MainWebPromptTest(unittest.TestCase):
    def test_yes_answers_open_web_gui(self) -> None:
        for answer in ("y", "Y", "yes", " YES "):
            with self.subTest(answer=answer):
                self.assertTrue(main.wants_web_gui(answer))
        self.assertFalse(main.wants_web_gui("no"))
        self.assertFalse(main.wants_web_gui(""))

    @patch("main.subprocess.run")
    def test_launcher_uses_current_python_and_managed_server(self, run) -> None:
        run.return_value.returncode = 0
        self.assertEqual(main.launch_web_gui(), 0)

        command = run.call_args.args[0]
        self.assertEqual(command[0], sys.executable)
        self.assertEqual(Path(command[1]).name, "server.py")
        self.assertEqual(command[2:], ["--open"])


if __name__ == "__main__":
    unittest.main()
