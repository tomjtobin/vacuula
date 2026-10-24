"""Black-box regression tests against a complete built image; never use live data."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import time
import unittest

IMAGE = os.environ.get("VACUULA_TEST_IMAGE")
DOCKER = shlex.split(os.environ.get("VACUULA_TEST_DOCKER", "docker"))


def docker(*args, check=True, timeout=30):
    return subprocess.run(
        [*DOCKER, *args], text=True, capture_output=True, check=check, timeout=timeout
    )


@unittest.skipUnless(IMAGE, "Set VACUULA_TEST_IMAGE to a locally built candidate")
class UpgradeCompatibility(unittest.TestCase):
    def setUp(self):
        self.containers = []

    def tearDown(self):
        for container in self.containers:
            docker("rm", "-f", container, check=False)

    def start(self, overrides=None, options=None, command=()):
        env = {
            "HOST_IP": "127.0.0.1", "MDNS_ENABLED": "false",
            "GEN4_ENABLED": "false",
        }
        env.update(overrides or {})
        args = ["run", "-d", "--network", "none", "--read-only",
                "--tmpfs", "/server/data:rw,mode=700", "--tmpfs", "/tmp"]
        for name, value in env.items():
            args += ["-e", f"{name}={value}"]
        if options is not None:
            directory = tempfile.TemporaryDirectory()
            self.addCleanup(directory.cleanup)
            path = Path(directory.name) / "options.json"
            path.write_text(json.dumps(options))
            args += ["-v", f"{path}:/data/options.json:ro"]
        container = docker(*args, IMAGE, *command).stdout.strip()
        self.containers.append(container)
        return container

    def state(self, container):
        return json.loads(docker("inspect", container).stdout)[0]["State"]

    def logs(self, container):
        result = docker("logs", container)
        return result.stdout + result.stderr

    def ready(self, container):
        code = "import urllib.request; urllib.request.urlopen('http://127.0.0.1/api/server',timeout=1).read()"
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            if not self.state(container)["Running"]:
                self.fail(self.logs(container))
            if docker("exec", container, "python", "-c", code, check=False).returncode == 0:
                return
            time.sleep(0.2)
        self.fail("API did not become ready: " + self.logs(container))

    def endpoints(self, container, expected):
        code = '''
import hashlib, http.client, json, socket, ssl
from vacuula_server.constants import CERT
ctx = ssl.create_default_context(cafile=str(CERT))
ctx.check_hostname = False
fingerprints = []
for port in (335, 443, 444):
    expected = port in json.loads(__import__('sys').argv[1])
    if expected:
        conn = http.client.HTTPSConnection('127.0.0.1', port, context=ctx, timeout=2)
        conn.connect()
        fingerprints.append(hashlib.sha256(conn.sock.getpeercert(binary_form=True)).hexdigest())
        conn.request('GET', '/api/server')
        response = conn.getresponse()
        assert response.status == 200, (port, response.status)
        assert json.loads(response.read())['version']
        conn.close()
    else:
        try:
            connection = socket.create_connection(('127.0.0.1', port), timeout=1)
        except ConnectionRefusedError:
            pass
        else:
            connection.close()
            raise AssertionError(('unexpected listener', port))
assert len(set(fingerprints)) <= 1, fingerprints
'''
        result = docker("exec", container, "python", "-c", code, json.dumps(expected), check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_both_default_tls_endpoints_and_pid1_sigterm(self):
        container = self.start()
        self.ready(container)
        self.endpoints(container, [335, 443])
        # Default CMD must exec the server, rather than leave a shell at PID 1.
        result = docker("exec", container, "python", "-c",
                        "assert b'vacuula-server' in open('/proc/1/cmdline','rb').read()")
        self.assertEqual(result.returncode, 0)
        started = time.monotonic()
        docker("stop", "-t", "5", container)
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(self.state(container)["ExitCode"], 0, self.logs(container))
        self.assertIn("Server stopped", self.logs(container))

    def test_pid1_sigterm_without_robot_listeners(self):
        container = self.start({"GEN3_ENABLED": "false"})
        self.ready(container)
        docker("stop", "-t", "5", container)
        self.assertEqual(self.state(container)["ExitCode"], 0, self.logs(container))
        self.assertIn("Server stopped", self.logs(container))

    def test_pid1_sigterm_with_incomplete_tls_peers(self):
        container = self.start()
        self.ready(container)
        code = "import socket,time; from pathlib import Path; peers=[socket.create_connection(('127.0.0.1',p)) for p in (335,443)]; Path('/tmp/peers-ready').touch(); time.sleep(60)"
        docker("exec", "-d", container, "python", "-c", code)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if docker("exec", container, "test", "-f", "/tmp/peers-ready", check=False).returncode == 0:
                break
            time.sleep(0.1)
        else:
            self.fail("test peers did not connect")
        started = time.monotonic()
        docker("stop", "-t", "5", container)
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(self.state(container)["ExitCode"], 0, self.logs(container))
        self.assertIn("Server stopped", self.logs(container))

    def test_legacy_disabled(self):
        container = self.start({"GEN3_LEGACY_PORT": "0"})
        self.ready(container)
        self.endpoints(container, [335])

    def test_primary_443_is_not_bound_twice(self):
        container = self.start({"GEN3_PORT": "443"})
        self.ready(container)
        self.endpoints(container, [443])

    def test_configurable_legacy_port(self):
        container = self.start({"GEN3_LEGACY_PORT": "444"})
        self.ready(container)
        self.endpoints(container, [335, 444])

    def test_disabled_gen3_has_no_tls_listeners(self):
        container = self.start({"GEN3_ENABLED": "false"})
        self.ready(container)
        self.endpoints(container, [])

    def test_ha_options_and_environment_precedence(self):
        for overrides, expected in [({}, [335]), ({"GEN3_LEGACY_PORT": "443"}, [335, 443])]:
            with self.subTest(overrides=overrides):
                container = self.start(overrides, options={"GEN3_LEGACY_PORT": 0})
                self.ready(container)
                self.endpoints(container, expected)

    def test_configuration_conflicts_fail_before_serving(self):
        for overrides in [{"VACUULA_PORT": "443"}, {"GEN3_LEGACY_PORT": "99"},
                          {"GEN3_LEGACY_PORT": "1000"}, {"GEN3_LEGACY_PORT": "-1"},
                          {"GEN3_LEGACY_PORT": "invalid"}]:
            with self.subTest(overrides=overrides):
                container = self.start(overrides)
                result = docker("wait", container)
                self.assertNotEqual(int(result.stdout), 0)
                self.assertIn("GEN3_LEGACY_PORT", self.logs(container))

    def test_occupied_required_ports_fail_and_release_partial_bindings(self):
        code = '''
import os, socket, subprocess, sys
port = int(sys.argv[1])
blocker = socket.socket()
blocker.bind(('127.0.0.1', port))
blocker.listen()
p = subprocess.run(['vacuula-server'], capture_output=True, text=True, timeout=8)
assert p.returncode != 0, p.stderr
assert 'Cannot bind required Gen3 HTTPS listener' in p.stderr, p.stderr
assert str(port) in p.stderr, p.stderr
# The other Gen3 socket and management listener must not survive failed startup.
for free_port in ({335, 443, 80} - {port}):
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', free_port))
'''
        for port in (335, 443):
            with self.subTest(port=port):
                container = self.start(command=("sh", "-c", 'alembic upgrade head && exec "$@"',
                                                "--", "python", "-c", code, str(port)))
                self.assertEqual(int(docker("wait", container).stdout), 0, self.logs(container))

    def test_native_sigterm_and_sigint_exit_and_database_integrity(self):
        code = '''
import signal, sqlite3, subprocess, sys, time, urllib.request
p = subprocess.Popen(['vacuula-server'], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
try:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen('http://127.0.0.1/api/server', timeout=0.5).read()
            break
        except OSError:
            assert p.poll() is None, p.communicate()[1]
            time.sleep(0.1)
    else:
        raise AssertionError('native process did not start')
    p.send_signal(getattr(signal, sys.argv[1]))
    _, log = p.communicate(timeout=5)
    assert p.returncode == 0, log
    assert 'Server stopped' in log, log
    db = sqlite3.connect('/server/data/vacuula.db')
    assert db.execute('pragma integrity_check').fetchone()[0] == 'ok'
finally:
    if p.poll() is None:
        p.kill()
        p.wait()
'''
        for sig in ("SIGTERM", "SIGINT"):
            with self.subTest(signal=sig):
                container = self.start(command=("sh", "-c", 'alembic upgrade head && exec "$@"',
                                                "--", "python", "-c", code, sig))
                self.assertEqual(int(docker("wait", container).stdout), 0, self.logs(container))


if __name__ == "__main__":
    unittest.main()
