"""Tests for sekha.server: handle_request dispatcher + CLI `serve` subcommand.

Plan 05-02 Task 1 (TestHandleRequest + TestCli): in-process unit tests for
the pure dict-in/dict-out dispatcher and argparse wiring.

Plan 05-02 Task 2 (TestServerSubprocess): subprocess integration tests that
spawn real `python -m sekha.cli serve` processes over pipes and drive the
full JSON-RPC handshake. These catch the class of bugs that killed
MemPalace — stdout buffering, Content-Length drift, Windows CRLF
translation, stray prints from tool-handler imports — because those bugs
only surface under real process spin-up.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import threading
import unittest
from pathlib import Path

from sekha.jsonrpc import (
    ACCEPTED_PROTOCOL_VERSIONS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
)
from sekha.server import handle_request


class TestHandleRequest(unittest.TestCase):
    """Pure-function tests for sekha.server.handle_request."""

    # ------------------------------------------------------------------
    # 1. initialize echoes protocolVersion
    # ------------------------------------------------------------------
    def test_initialize_echoes_protocol_version(self):
        req = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        }
        resp = handle_request(req)
        self.assertIsNotNone(resp)
        self.assertEqual(resp["jsonrpc"], "2.0")
        self.assertEqual(resp["id"], 1)
        self.assertIn("result", resp)
        self.assertEqual(resp["result"]["protocolVersion"], "2025-03-26")
        self.assertEqual(resp["result"]["serverInfo"]["name"], "sekha")
        self.assertIn("version", resp["result"]["serverInfo"])
        self.assertEqual(resp["result"]["capabilities"], {"tools": {}})

    # ------------------------------------------------------------------
    # 2. initialize accepts all three protocol versions
    # ------------------------------------------------------------------
    def test_initialize_accepts_all_three_versions(self):
        for version in ACCEPTED_PROTOCOL_VERSIONS:
            with self.subTest(protocolVersion=version):
                req = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": version,
                        "capabilities": {},
                    },
                }
                resp = handle_request(req)
                self.assertEqual(resp["result"]["protocolVersion"], version)

    # ------------------------------------------------------------------
    # 3. initialize unknown version falls back without erroring
    # ------------------------------------------------------------------
    def test_initialize_unknown_version_falls_back(self):
        req = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "9999-01-01", "capabilities": {}},
        }
        resp = handle_request(req)
        self.assertIsNotNone(resp)
        # MUST have a result (not an error) and a protocolVersion field.
        self.assertIn("result", resp)
        self.assertNotIn("error", resp)
        self.assertIn("protocolVersion", resp["result"])
        # Must be a non-empty string.
        self.assertTrue(resp["result"]["protocolVersion"])

    # ------------------------------------------------------------------
    # 4. notifications/initialized returns None (no response)
    # ------------------------------------------------------------------
    def test_notifications_initialized_returns_none(self):
        req = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        resp = handle_request(req)
        self.assertIsNone(resp)

    # ------------------------------------------------------------------
    # 5. tools/list returns six sekha_*-prefixed tools
    # ------------------------------------------------------------------
    def test_tools_list_returns_six_tools(self):
        req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
        resp = handle_request(req)
        self.assertIsNotNone(resp)
        self.assertIn("result", resp)
        tools = resp["result"]["tools"]
        self.assertEqual(len(tools), 6)
        for t in tools:
            self.assertTrue(
                t["name"].startswith("sekha_"),
                f"tool name {t['name']} does not start with sekha_",
            )

    # ------------------------------------------------------------------
    # 6. tools/call sekha_status success — round-trips a handler result
    # ------------------------------------------------------------------
    def test_tools_call_sekha_status_success(self):
        import json as _json

        with tempfile.TemporaryDirectory(prefix="sekha-srv-test-") as td:
            home = Path(td)
            # Stage the five categories that sekha_status walks.
            for cat in ("sessions", "decisions", "preferences", "projects", "rules"):
                (home / cat).mkdir()
            saved_home = os.environ.get("SEKHA_HOME")
            os.environ["SEKHA_HOME"] = str(home)
            try:
                req = {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "sekha_status", "arguments": {}},
                }
                resp = handle_request(req)
            finally:
                if saved_home is None:
                    os.environ.pop("SEKHA_HOME", None)
                else:
                    os.environ["SEKHA_HOME"] = saved_home

            self.assertIsNotNone(resp)
            self.assertIn("result", resp)
            content = resp["result"]["content"]
            self.assertEqual(content[0]["type"], "text")
            status = _json.loads(content[0]["text"])
            for key in ("total", "by_category", "rules_count", "recent", "hook_errors"):
                self.assertIn(key, status)

    # ------------------------------------------------------------------
    # 7. tools/call unknown tool returns METHOD_NOT_FOUND (-32601)
    # ------------------------------------------------------------------
    def test_tools_call_unknown_tool_returns_method_not_found(self):
        req = {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "sekha_bogus", "arguments": {}},
        }
        resp = handle_request(req)
        self.assertIsNotNone(resp)
        self.assertIn("error", resp)
        self.assertEqual(resp["error"]["code"], METHOD_NOT_FOUND)

    # ------------------------------------------------------------------
    # 8. tools/call handler exception returns isError (NOT JSON-RPC error)
    # ------------------------------------------------------------------
    def test_tools_call_handler_exception_returns_is_error(self):
        from sekha import tools as _tools

        saved = _tools.HANDLERS["sekha_status"]
        def boom(**_kwargs):
            raise RuntimeError("boom")
        _tools.HANDLERS["sekha_status"] = boom
        try:
            req = {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {"name": "sekha_status", "arguments": {}},
            }
            resp = handle_request(req)
        finally:
            _tools.HANDLERS["sekha_status"] = saved

        self.assertIsNotNone(resp)
        self.assertIn("result", resp)
        self.assertTrue(resp["result"].get("isError"))
        self.assertIn("boom", resp["result"]["content"][0]["text"])

    # ------------------------------------------------------------------
    # 9. ping returns empty result
    # ------------------------------------------------------------------
    def test_ping_returns_empty_result(self):
        req = {"jsonrpc": "2.0", "id": 6, "method": "ping"}
        resp = handle_request(req)
        self.assertEqual(resp, {"jsonrpc": "2.0", "id": 6, "result": {}})

    # ------------------------------------------------------------------
    # 10. notifications/cancelled returns None and does not raise
    # ------------------------------------------------------------------
    def test_notifications_cancelled_returns_none(self):
        req = {
            "jsonrpc": "2.0",
            "method": "notifications/cancelled",
            "params": {"requestId": 3},
        }
        resp = handle_request(req)
        self.assertIsNone(resp)

    # ------------------------------------------------------------------
    # 11. unknown method returns METHOD_NOT_FOUND
    # ------------------------------------------------------------------
    def test_unknown_method_returns_method_not_found(self):
        req = {"jsonrpc": "2.0", "id": 7, "method": "prompts/list"}
        resp = handle_request(req)
        self.assertIsNotNone(resp)
        self.assertIn("error", resp)
        self.assertEqual(resp["error"]["code"], METHOD_NOT_FOUND)

    # ------------------------------------------------------------------
    # 12. missing method field returns INVALID_REQUEST (-32600)
    # ------------------------------------------------------------------
    def test_missing_method_field_returns_invalid_request(self):
        req = {"jsonrpc": "2.0", "id": 8}
        resp = handle_request(req)
        self.assertIsNotNone(resp)
        self.assertIn("error", resp)
        self.assertEqual(resp["error"]["code"], INVALID_REQUEST)

    # ------------------------------------------------------------------
    # 13. request id preserved for numeric, string, and null
    # ------------------------------------------------------------------
    def test_request_id_preserved_for_numeric_and_string(self):
        for rid in (1, "abc", None):
            with self.subTest(id=rid):
                req = {"jsonrpc": "2.0", "id": rid, "method": "ping"}
                resp = handle_request(req)
                self.assertEqual(resp["id"], rid)


class TestCli(unittest.TestCase):
    """Verify `sekha serve` subcommand is wired into the argparse tree."""

    def test_cli_serve_subcommand_registered(self):
        from sekha.cli import _build_parser
        parser = _build_parser()
        args = parser.parse_args(["serve"])
        self.assertEqual(args.command, "serve")


class TestServerSubprocess(unittest.TestCase):
    """Integration tests: spawn `python -m sekha.cli serve` over pipes.

    Every test stages a fresh SEKHA_HOME tempdir with the five memory
    categories pre-created so sekha_status and friends walk a complete
    filesystem layout. Pipes run in binary mode (bufsize=0, text=False)
    so the Windows msvcrt.setmode binary path in harden_stdio is
    actually exercised and the test encodes/decodes UTF-8 framing bytes
    explicitly.
    """

    # Generous read timeout to absorb Windows CI jitter; each test kills
    # the server on timeout via a threading.Timer so a hung readline
    # surfaces as an assertion failure instead of wedging CI.
    _READ_TIMEOUT = 8.0
    # Grace period after stdin.close() for the server to flush + exit.
    _SHUTDOWN_TIMEOUT = 5.0

    def setUp(self):
        self._td = tempfile.TemporaryDirectory(prefix="sekha-srv-sp-")
        self.home = Path(self._td.name)
        for cat in ("sessions", "decisions", "preferences", "projects", "rules"):
            (self.home / cat).mkdir()
        # Seed env for every spawn in this test — isolates from the user's
        # real ~/.sekha/. Copied rather than mutated so parallel test
        # invocations can't stomp each other's SEKHA_HOME.
        self._env = {**os.environ, "SEKHA_HOME": str(self.home)}
        self._procs: list[subprocess.Popen] = []

    def tearDown(self):
        for proc in self._procs:
            if proc.poll() is None:
                proc.kill()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
            # Close pipes to release OS handles (Windows is strict about this).
            for stream in (proc.stdin, proc.stdout, proc.stderr):
                if stream is not None:
                    try:
                        stream.close()
                    except OSError:
                        pass
        self._td.cleanup()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _spawn_server(self, argv: list[str] | None = None) -> subprocess.Popen:
        """Launch the real server as a subprocess over binary pipes.

        bufsize=0 + text=False is deliberate — we want to exercise the
        same harden_stdio codepath Claude Code hits (real file descriptors,
        binary mode on Windows) and control newline translation ourselves.
        """
        cmd = argv if argv is not None else [sys.executable, "-m", "sekha.cli", "serve"]
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self._env,
            bufsize=0,
        )
        self._procs.append(proc)
        return proc

    def _write(self, proc: subprocess.Popen, payload: dict) -> None:
        line = (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
        assert proc.stdin is not None
        proc.stdin.write(line)
        proc.stdin.flush()

    def _read_response(
        self, proc: subprocess.Popen, timeout: float | None = None
    ) -> dict:
        """Read one line from stdout, parsed as JSON. Kills proc on timeout."""
        assert proc.stdout is not None
        timeout = timeout if timeout is not None else self._READ_TIMEOUT
        timer = threading.Timer(timeout, proc.kill)
        timer.start()
        try:
            raw = proc.stdout.readline()
        finally:
            timer.cancel()
        if not raw:
            # Drain stderr for a readable failure message.
            stderr_bytes = b""
            try:
                assert proc.stderr is not None
                stderr_bytes = proc.stderr.read()
            except Exception:  # noqa: BLE001
                pass
            raise AssertionError(
                "server produced no response within "
                f"{timeout:.1f}s; stderr:\n"
                + stderr_bytes.decode("utf-8", errors="replace")
            )
        return json.loads(raw.decode("utf-8"))

    def _rpc(self, proc: subprocess.Popen, payload: dict) -> dict | None:
        """Write one request; read the response iff the request has an id."""
        self._write(proc, payload)
        if "id" not in payload:
            return None
        return self._read_response(proc)

    def _close_and_wait(self, proc: subprocess.Popen) -> int:
        """Close stdin, wait for clean shutdown, return exit code."""
        assert proc.stdin is not None
        proc.stdin.close()
        try:
            return proc.wait(timeout=self._SHUTDOWN_TIMEOUT)
        except subprocess.TimeoutExpired:
            proc.kill()
            self.fail(
                "server did not exit within "
                f"{self._SHUTDOWN_TIMEOUT}s of stdin close"
            )

    # ------------------------------------------------------------------
    # 15. Full happy-path handshake: initialize -> initialized -> tools/list
    #     -> tools/call sekha_status -> graceful shutdown
    # ------------------------------------------------------------------
    def test_full_handshake_plus_tools_list_plus_status(self):
        proc = self._spawn_server()

        init_resp = self._rpc(proc, {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        })
        self.assertEqual(init_resp["result"]["protocolVersion"], "2025-03-26")
        self.assertEqual(init_resp["result"]["serverInfo"]["name"], "sekha")

        # notifications/initialized — no response expected.
        self._rpc(proc, {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        })

        list_resp = self._rpc(proc, {
            "jsonrpc": "2.0", "id": 2, "method": "tools/list",
        })
        tools = list_resp["result"]["tools"]
        self.assertEqual(len(tools), 6)
        for t in tools:
            self.assertTrue(t["name"].startswith("sekha_"))

        status_resp = self._rpc(proc, {
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "sekha_status", "arguments": {}},
        })
        content = status_resp["result"]["content"]
        self.assertEqual(content[0]["type"], "text")
        status = json.loads(content[0]["text"])
        for key in ("total", "by_category", "rules_count", "recent", "hook_errors"):
            self.assertIn(key, status)

        exit_code = self._close_and_wait(proc)
        self.assertEqual(exit_code, 0)

    # ------------------------------------------------------------------
    # 16. Protocol-version echo-back across all three accepted versions
    # ------------------------------------------------------------------
    def test_handshake_with_all_three_protocol_versions(self):
        for version in ACCEPTED_PROTOCOL_VERSIONS:
            with self.subTest(protocolVersion=version):
                proc = self._spawn_server()
                resp = self._rpc(proc, {
                    "jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": version, "capabilities": {}},
                })
                self.assertEqual(resp["result"]["protocolVersion"], version)
                self._close_and_wait(proc)

    # ------------------------------------------------------------------
    # 17. ping round-trip under a real subprocess
    # ------------------------------------------------------------------
    def test_ping_round_trip(self):
        proc = self._spawn_server()
        resp = self._rpc(proc, {"jsonrpc": "2.0", "id": 1, "method": "ping"})
        self.assertEqual(resp, {"jsonrpc": "2.0", "id": 1, "result": {}})
        self._close_and_wait(proc)

    # ------------------------------------------------------------------
    # 18. Unknown method returns METHOD_NOT_FOUND; server still alive after
    # ------------------------------------------------------------------
    def test_unknown_method_returns_method_not_found(self):
        proc = self._spawn_server()
        err_resp = self._rpc(proc, {
            "jsonrpc": "2.0", "id": 1, "method": "prompts/list",
        })
        self.assertIn("error", err_resp)
        self.assertEqual(err_resp["error"]["code"], METHOD_NOT_FOUND)
        # Prove the server survived: a follow-up ping must reply.
        ping_resp = self._rpc(proc, {"jsonrpc": "2.0", "id": 2, "method": "ping"})
        self.assertEqual(ping_resp["result"], {})
        self._close_and_wait(proc)

    # ------------------------------------------------------------------
    # 19. Malformed JSON does not kill the server
    # ------------------------------------------------------------------
    def test_malformed_json_does_not_kill_server(self):
        proc = self._spawn_server()
        assert proc.stdin is not None
        proc.stdin.write(b"not-json\n")
        proc.stdin.flush()
        parse_err = self._read_response(proc)
        self.assertIn("error", parse_err)
        self.assertEqual(parse_err["error"]["code"], PARSE_ERROR)
        self.assertIsNone(parse_err["id"])  # id unrecoverable on parse error

        # Server must still handle subsequent requests.
        ping_resp = self._rpc(proc, {"jsonrpc": "2.0", "id": 1, "method": "ping"})
        self.assertEqual(ping_resp["result"], {})
        self._close_and_wait(proc)

    # ------------------------------------------------------------------
    # 20. Stray print() in a handler does NOT corrupt the protocol stream
    #     (the killer test — proves harden_stdio works under real process)
    # ------------------------------------------------------------------
    def test_stray_print_in_handler_does_not_corrupt_protocol_stream(self):
        # Shim: monkeypatch sekha.tools.HANDLERS["sekha_status"] to print
        # to stdout BEFORE returning the real status. Without harden_stdio,
        # that print would land on protocol stdout and corrupt the frame.
        shim = textwrap.dedent(
            """
            import sekha.tools as t
            _orig = t.sekha_status
            def noisy(**kwargs):
                print("OOPS pollution on stdout")  # would kill MemPalace
                return _orig(**kwargs)
            t.sekha_status = noisy
            t.HANDLERS["sekha_status"] = noisy
            from sekha.server import main
            raise SystemExit(main())
            """
        )
        proc = self._spawn_server([sys.executable, "-c", shim])

        # Handshake then call sekha_status.
        self._rpc(proc, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-03-26", "capabilities": {}},
        })
        self._rpc(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})

        resp = self._rpc(proc, {
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "sekha_status", "arguments": {}},
        })
        # Assertion 1: response parses as a well-formed JSON-RPC result —
        # NOT the "OOPS pollution" string. This proves stdout wasn't
        # corrupted by the handler's print.
        self.assertEqual(resp["jsonrpc"], "2.0")
        self.assertEqual(resp["id"], 2)
        self.assertIn("result", resp)
        status = json.loads(resp["result"]["content"][0]["text"])
        self.assertIn("total", status)

        # Follow-up ping must still round-trip cleanly — proving the
        # stream isn't desynced after the pollution attempt.
        ping_resp = self._rpc(proc, {"jsonrpc": "2.0", "id": 3, "method": "ping"})
        self.assertEqual(ping_resp["result"], {})

        # Close stdin, let the server shut down, then drain stderr.
        assert proc.stdin is not None
        proc.stdin.close()
        try:
            proc.wait(timeout=self._SHUTDOWN_TIMEOUT)
        except subprocess.TimeoutExpired:
            proc.kill()
            self.fail("shim server did not exit cleanly")
        assert proc.stderr is not None
        stderr_bytes = proc.stderr.read()
        # Assertion 2 (behavioral proof): the "OOPS" bytes DID get emitted —
        # they just landed on stderr, not stdout, thanks to harden_stdio.
        self.assertIn(
            b"OOPS",
            stderr_bytes,
            "stray print did not reach stderr; harden_stdio may have failed",
        )

    # ------------------------------------------------------------------
    # 21. notifications/cancelled mid-session does not crash the server
    # ------------------------------------------------------------------
    def test_notifications_cancelled_does_not_crash(self):
        proc = self._spawn_server()
        self._rpc(proc, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-03-26", "capabilities": {}},
        })
        # Cancellation notification — no response expected, must not crash.
        self._rpc(proc, {
            "jsonrpc": "2.0",
            "method": "notifications/cancelled",
            "params": {"requestId": 42},
        })
        # Ping proves server is alive.
        ping_resp = self._rpc(proc, {"jsonrpc": "2.0", "id": 2, "method": "ping"})
        self.assertEqual(ping_resp["result"], {})
        self._close_and_wait(proc)

    # ------------------------------------------------------------------
    # 22. Server exits cleanly on stdin close (EOF path)
    # ------------------------------------------------------------------
    def test_server_exits_cleanly_on_stdin_close(self):
        proc = self._spawn_server()
        self._rpc(proc, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-03-26", "capabilities": {}},
        })
        exit_code = self._close_and_wait(proc)
        self.assertEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()
