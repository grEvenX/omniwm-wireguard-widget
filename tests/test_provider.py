"""Offline integration tests. These never invoke real VPN commands."""
import importlib.util
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
UUID = "BC61A04B-C99B-4C3D-8892-3FA1EBAC9973"
FAKE = r'''
import json, os, sys
from pathlib import Path
p = Path(os.environ["VPN_TEST_STATE"])
s = json.loads(p.read_text())
args = sys.argv[1:]
with open(str(p)+".log", "a") as f: f.write(json.dumps(args)+"\n")
if args == ["--nc", "list"]:
    uid = "BC61A04B-C99B-4C3D-8892-3FA1EBAC9973"
    bundle = s.get("bundle", "com.wireguard.macos")
    name = s.get("name", "Myworkout Wireguard Client")
    line = f'* (Disconnected) {uid} VPN ({bundle}) "{name}" [VPN:{bundle}]'
    if not s.get("missing"): print(line)
    if s.get("duplicate"): print(line.replace(uid, "11111111-1111-1111-1111-111111111111"))
elif args[1] == "status":
    print(s.get("status", "Disconnected"))
    print("Extended Status <dictionary> { Status : 0 }")
elif args[1] in ("start", "stop"):
    if s.get("fail"):
        print("SCNetworkConnectionStart failed: permission denied")
        sys.exit(1)
    if not s.get("stall"):
        s["status"] = "Connected" if args[1] == "start" else "Disconnected"
        p.write_text(json.dumps(s))
else: sys.exit(2)
'''


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.state = self.base / "state.json"
        self.write_state(status="Disconnected")
        self.fake = self.base / "scutil"
        self.fake.write_text(f"#!{sys.executable}\n" + FAKE)
        self.fake.chmod(0o755)
        self.process = None

    def write_state(self, **data):
        self.state.write_text(json.dumps(data, ensure_ascii=False))

    def start(self, tunnel=UUID):
        env = dict(os.environ, VPN_TEST_STATE=str(self.state),
                   OMNIWM_PROVIDER_OPTIONS=json.dumps({"tunnel": tunnel, "pollSeconds": 1}))
        code = 'require $ARGV[0]; main::run(scutil => $ARGV[1]);'
        self.process = subprocess.Popen(["/usr/bin/perl", "-e", code,
            str(ROOT / "wireguard/provider.pl"), str(self.fake)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        self.addCleanup(self.stop)
        return self.read()

    def stop(self):
        if self.process:
            self.process.stdin.close()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
            self.process.stdout.close()
            self.process.stderr.close()
            self.process = None

    def read(self, timeout=4):
        if not select.select([self.process.stdout], [], [], timeout)[0]:
            self.fail("Provider response timed out")
        # Unbuffered byte reads avoid select()/BufferedReader disagreement when
        # the provider publishes state and a result in one batch.
        line = b""
        while not line.endswith(b"\n"):
            byte = os.read(self.process.stdout.fileno(), 1)
            if not byte:
                self.fail("Provider exited: " + self.process.stderr.read().decode())
            line += byte
        return json.loads(line)

    def action(self, name="toggle", request="r1"):
        self.process.stdin.write((json.dumps(["action", request, name, {}]) + "\n").encode())
        self.process.stdin.flush()
        frames = []
        while True:
            frame = self.read()
            frames.append(frame)
            if frame[0] == "result":
                return frame, frames

    def mutations(self):
        return [args for args in map(json.loads, Path(str(self.state) + ".log").read_text().splitlines())
                if args[1] in ("start", "stop")]

    def test_connect_then_disconnect_exact_service(self):
        self.assertEqual(self.start()[2]["status"], "disconnected")
        result, frames = self.action()
        self.assertTrue(result[2])
        self.assertEqual(result[3]["status"], "connected")
        self.assertTrue(any(f[:2] == ["state", "vpn"] for f in frames))
        result, _ = self.action(request="r2")
        self.assertTrue(result[2])
        self.assertEqual(result[3]["status"], "disconnected")
        self.assertEqual(self.mutations(), [["--nc", "start", UUID], ["--nc", "stop", UUID]])

    def test_actual_state_rechecked_before_toggle(self):
        self.start()
        self.write_state(status="Connected")
        result, _ = self.action()
        self.assertTrue(result[2])
        self.assertEqual(self.mutations(), [["--nc", "stop", UUID]])

    def test_cannot_target_another_vpn_provider(self):
        self.write_state(bundle="com.ui.uid.standard-desktop")
        self.assertIn("not found", self.start()[2]["error"])
        self.assertFalse(self.action()[0][2])
        self.assertEqual(self.mutations(), [])

    def test_missing_tunnel_never_mutated(self):
        self.write_state(missing=True)
        self.assertIn("not found", self.start()[2]["error"])
        self.assertFalse(self.action()[0][2])
        self.assertEqual(self.mutations(), [])

    def test_ambiguous_name_never_mutated(self):
        self.write_state(duplicate=True)
        self.assertIn("More than one", self.start("Myworkout Wireguard Client")[2]["error"])
        self.assertFalse(self.action()[0][2])
        self.assertEqual(self.mutations(), [])

    def test_unicode_name(self):
        self.write_state(name="Stjørdal VPN")
        self.assertEqual(self.start("Stjørdal VPN")[2]["tunnel"], "Stjørdal VPN")
        self.assertTrue(self.action()[0][2])

    def test_busy_transition_does_not_toggle_again(self):
        self.write_state(stall=True)
        self.start()
        first, _ = self.action()
        self.assertTrue(first[2])
        self.assertTrue(first[3]["busy"])
        self.assertFalse(self.action(request="r2")[0][2])
        self.assertEqual(len(self.mutations()), 1)

    def test_native_connecting_state_blocks_toggle(self):
        self.write_state(status="Connecting")
        self.assertEqual(self.start()[2]["status"], "connecting")
        self.assertFalse(self.action()[0][2])
        self.assertEqual(self.mutations(), [])

    def test_failed_command_and_recovery(self):
        self.write_state(fail=True)
        self.start()
        result, frames = self.action()
        self.assertFalse(result[2])
        self.assertIn("permission denied", result[3])
        self.assertTrue(any(f[0] == "state" and "error" in f[2] for f in frames))
        self.write_state(status="Disconnected")
        self.assertTrue(self.action("refresh")[0][2])
        self.assertTrue(self.action()[0][2])

    def test_periodic_status_follows_external_changes(self):
        self.start()
        self.write_state(status="Connected")
        self.assertEqual(self.read()[2]["status"], "connected")
        self.assertEqual(self.mutations(), [])

    def test_multiple_frames_in_single_write(self):
        self.start()
        self.process.stdin.write(b'["action","a","refresh",{}]\n["action","b","refresh",{}]\n')
        self.process.stdin.flush()
        self.assertEqual(self.read()[1], "a")
        self.assertEqual(self.read()[1], "b")


class ConfigurationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("wireguard_install", ROOT / "install.py")
        cls.installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.installer)

    def test_preserves_other_settings_and_components(self):
        import tomllib
        original = '''# Keep my comment
[profiles.default]
trailing = ["clock", "wifi"]
theme = "wallpaper"
[profiles.default.island]
displays = "notch"
[[profiles.default.island.components]]
id = "music"
widget = "media"
[weather]
city = "Stjørdal"
'''
        updated = self.installer.configure(original, UUID, {})
        data = tomllib.loads(updated)
        p = data["profiles"]["default"]
        self.assertEqual(p["trailing"], ["clock", "wireguard", "wifi"])
        self.assertEqual(p["theme"], "wallpaper")
        self.assertEqual(p["island"]["displays"], "notch")
        self.assertEqual(p["island"]["components"][0]["id"], "music")
        self.assertEqual(data["weather"]["city"], "Stjørdal")
        self.assertIn("# Keep my comment", updated)
        self.assertEqual(updated, self.installer.configure(updated, UUID, {}))

    def test_custom_root_is_preserved_by_refusal(self):
        with self.assertRaisesRegex(ValueError, "refusing to replace"):
            self.installer.configure('[profiles.default.island]\nroot="custom"\n', UUID, {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
