"""The always-on Studio service is explicit, user-scoped, and restartable."""

import os
import pathlib
import plistlib
import sys
import tempfile
import types
import unittest

from nxb import studio_service as service


class LaunchAgentDeclaration(unittest.TestCase):
    def _fixture(self, tmp):
        home = os.path.join(tmp, "home")
        repo = os.path.join(tmp, "repo")
        ledger = os.path.join(home, ".nxb", "ledger.db")
        os.makedirs(os.path.join(repo, "nxb"))
        os.makedirs(os.path.dirname(ledger))
        pathlib.Path(repo, "nxb", "__main__.py").write_text("")
        pathlib.Path(ledger).write_text("")
        return home, repo, ledger

    def test_it_runs_at_login_and_is_kept_alive_without_a_shell(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, repo, ledger = self._fixture(tmp)
            doc = service.launch_agent(
                ledger, repo, python=sys.executable, home=home)
        self.assertIs(doc["RunAtLoad"], True)
        self.assertIs(doc["KeepAlive"], True)
        self.assertEqual(doc["WorkingDirectory"], repo)
        self.assertEqual(doc["ProgramArguments"][:3],
                         [sys.executable, "-m", "nxb"])
        self.assertIn("--no-open", doc["ProgramArguments"])
        self.assertNotIn("studio.token", " ".join(doc["ProgramArguments"]))
        self.assertEqual(doc["EnvironmentVariables"]["NXB_STUDIO_MANAGED"],
                         "1")
        self.assertEqual(doc["EnvironmentVariables"]["PYTHONPATH"], repo)

    def test_install_writes_and_bootstraps_the_user_agent(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, repo, ledger = self._fixture(tmp)
            calls, loaded = [], {"value": False}
            real_launchctl = service._launchctl
            real_loaded = service._is_loaded
            real_listener = service._listener
            real_wait = service._wait_for
            real_which = service.shutil.which

            def launchctl(*args):
                calls.append(args)
                if args[0] == "bootstrap":
                    loaded["value"] = True
                stdout = "\tpid = 4242\n" if args[0] == "print" else ""
                return types.SimpleNamespace(returncode=0, stdout=stdout,
                                             stderr="")

            service._launchctl = launchctl
            service._is_loaded = lambda: False
            service._listener = lambda port: loaded["value"]
            service._wait_for = lambda port, wanted, deadline=10: True
            service.shutil.which = lambda name: (
                "/usr/bin/launchctl" if name == "launchctl"
                else real_which(name))
            try:
                result = service.install(
                    ledger, repo, python=sys.executable, home=home)
            finally:
                service._launchctl = real_launchctl
                service._is_loaded = real_loaded
                service._listener = real_listener
                service._wait_for = real_wait
                service.shutil.which = real_which

            plist = service.service_paths(home)["plist"]
            with open(plist, "rb") as handle:
                document = plistlib.load(handle)
        self.assertEqual(result["state"], "RUNNING")
        self.assertTrue(document["KeepAlive"])
        self.assertTrue(any(c[0] == "bootstrap" for c in calls))
        self.assertTrue(any(c[:2] == ("kickstart", "-k") for c in calls))

    def test_an_unrelated_listener_is_not_killed_or_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, repo, ledger = self._fixture(tmp)
            real_loaded = service._is_loaded
            real_listener = service._listener
            real_which = service.shutil.which
            service._is_loaded = lambda: False
            service._listener = lambda port: True
            service.shutil.which = lambda name: (
                "/usr/bin/launchctl" if name == "launchctl"
                else real_which(name))
            try:
                with self.assertRaises(service.StudioServiceError) as caught:
                    service.install(
                        ledger, repo, python=sys.executable, home=home)
            finally:
                service._is_loaded = real_loaded
                service._listener = real_listener
                service.shutil.which = real_which
        self.assertIn("outside the Studio service", str(caught.exception))


class ManagedStudioSurface(unittest.TestCase):
    def test_the_page_names_the_managed_service(self):
        page = pathlib.Path(service.__file__).with_name("studio.html").read_text()
        self.assertIn("always-on service · connected", page)

    def test_managed_logs_do_not_print_the_bearer_token(self):
        source = pathlib.Path(service.__file__).with_name("studio.py").read_text()
        self.assertIn("token omitted from the service log", source)
        self.assertIn("handing restart to launchd", source)


if __name__ == "__main__":
    unittest.main()
