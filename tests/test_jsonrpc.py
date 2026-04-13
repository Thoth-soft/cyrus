"""Tests for sekha.jsonrpc: error codes, parse, emit, emit_error, harden_stdio.

RED stage for Plan 05-01 Task 1. Covers the protocol layer's stdio hygiene
primitives that killed MemPalace when they were wrong. Every test uses
io.StringIO / io.BytesIO so no real stdout is touched.
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import unittest
from unittest import mock

from sekha.jsonrpc import (
    ACCEPTED_PROTOCOL_VERSIONS,
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    JsonRpcError,
    emit,
    emit_error,
    harden_stdio,
    parse,
)


class TestJsonrpc(unittest.TestCase):
    # ------------------------------------------------------------------
    # 1. Error code constants
    # ------------------------------------------------------------------
    def test_error_code_constants(self):
        self.assertEqual(PARSE_ERROR, -32700)
        self.assertEqual(INVALID_REQUEST, -32600)
        self.assertEqual(METHOD_NOT_FOUND, -32601)
        self.assertEqual(INVALID_PARAMS, -32602)
        self.assertEqual(INTERNAL_ERROR, -32603)

    # ------------------------------------------------------------------
    # 2. parse() accepts valid JSON-RPC line + trailing whitespace
    # ------------------------------------------------------------------
    def test_parse_valid_json(self):
        line = '{"jsonrpc":"2.0","id":1,"method":"ping"}\n'
        result = parse(line)
        self.assertIsInstance(result, dict)
        self.assertEqual(result["jsonrpc"], "2.0")
        self.assertEqual(result["id"], 1)
        self.assertEqual(result["method"], "ping")

    def test_parse_tolerates_trailing_whitespace(self):
        line = '   {"a": 1}   \r\n'
        self.assertEqual(parse(line), {"a": 1})

    # ------------------------------------------------------------------
    # 3. parse() on malformed input raises with .code == PARSE_ERROR
    # ------------------------------------------------------------------
    def test_parse_malformed_raises_parse_error(self):
        with self.assertRaises(ValueError) as ctx:
            parse("not json")
        self.assertTrue(isinstance(ctx.exception, JsonRpcError))
        self.assertEqual(ctx.exception.code, PARSE_ERROR)

    # ------------------------------------------------------------------
    # 4. emit() writes one line + flushes
    # ------------------------------------------------------------------
    def test_emit_writes_single_line_and_flushes(self):
        stream = io.StringIO()
        payload = {"jsonrpc": "2.0", "id": 1, "result": {}}
        emit(stream, payload)
        written = stream.getvalue()
        self.assertEqual(written, '{"jsonrpc":"2.0","id":1,"result":{}}\n')

    def test_emit_flush_invoked(self):
        # Use a stream subclass that records flush() calls
        class FlushTracker(io.StringIO):
            flushed = 0

            def flush(self):  # noqa: D401
                self.flushed += 1
                super().flush()

        stream = FlushTracker()
        emit(stream, {"ok": True})
        self.assertGreaterEqual(stream.flushed, 1)

    # ------------------------------------------------------------------
    # 5. emit_error() shape
    # ------------------------------------------------------------------
    def test_emit_error_shape(self):
        stream = io.StringIO()
        emit_error(stream, request_id=7, code=-32601, message="Method not found")
        line = stream.getvalue()
        self.assertTrue(line.endswith("\n"))
        parsed = json.loads(line.rstrip("\n"))
        self.assertEqual(parsed, {
            "jsonrpc": "2.0",
            "id": 7,
            "error": {"code": -32601, "message": "Method not found"},
        })

    def test_emit_error_id_none_serializes_null(self):
        stream = io.StringIO()
        emit_error(stream, request_id=None, code=PARSE_ERROR, message="bad")
        line = stream.getvalue()
        parsed = json.loads(line.rstrip("\n"))
        self.assertIsNone(parsed["id"])

    # ------------------------------------------------------------------
    # 6. emit() never embeds a literal \n inside the serialized JSON
    # ------------------------------------------------------------------
    def test_emit_no_embedded_newlines(self):
        stream = io.StringIO()
        emit(stream, {"msg": "hello\nworld"})
        output = stream.getvalue()
        # Exactly one newline byte: the framing delimiter. json.dumps escapes
        # embedded \n as the 2-char sequence \\n inside the string.
        self.assertEqual(output.count("\n"), 1)
        self.assertTrue(output.endswith("\n"))
        self.assertIn("hello\\nworld", output)

    # ------------------------------------------------------------------
    # 7. harden_stdio() returns a protected write handle
    # ------------------------------------------------------------------
    def test_harden_stdio_returns_protected_handle(self):
        real_stdout = sys.stdout
        real_stderr = sys.stderr
        try:
            # Install in-memory buffer-backed streams so harden_stdio has a
            # .buffer to grab. TextIOWrapper requires a BufferedIOBase.
            fake_stdout_buf = io.BytesIO()
            fake_stdout = io.TextIOWrapper(fake_stdout_buf, encoding="utf-8",
                                           write_through=True)
            fake_stderr_buf = io.BytesIO()
            fake_stderr = io.TextIOWrapper(fake_stderr_buf, encoding="utf-8",
                                           write_through=True)
            sys.stdout = fake_stdout
            sys.stderr = fake_stderr

            protected = harden_stdio()

            self.assertTrue(hasattr(protected, "write"))
            self.assertTrue(hasattr(protected, "flush"))
            # After the call, sys.stdout is the stderr stream (swap happened).
            self.assertIs(sys.stdout, fake_stderr)
            # protected is a distinct stream from sys.stderr
            self.assertIsNot(protected, fake_stderr)
        finally:
            sys.stdout = real_stdout
            sys.stderr = real_stderr

    # ------------------------------------------------------------------
    # 8. After harden_stdio, stray print() goes to stderr (captured)
    # ------------------------------------------------------------------
    def test_harden_stdio_survives_stray_print(self):
        real_stdout = sys.stdout
        real_stderr = sys.stderr
        try:
            fake_stdout_buf = io.BytesIO()
            fake_stdout = io.TextIOWrapper(fake_stdout_buf, encoding="utf-8",
                                           write_through=True)
            fake_stderr_buf = io.BytesIO()
            fake_stderr = io.TextIOWrapper(fake_stderr_buf, encoding="utf-8",
                                           write_through=True)
            sys.stdout = fake_stdout
            sys.stderr = fake_stderr

            protected = harden_stdio()
            # A stray print() must NOT land on the protected handle.
            print("OOPS from some import")

            # Flush both sides so BytesIO sees the writes
            fake_stderr.flush()
            protected.flush()
            fake_stdout.flush()

            self.assertIn(b"OOPS", fake_stderr_buf.getvalue())
            # Protected handle (the one the server uses for protocol output)
            # received nothing from the stray print.
            self.assertNotIn(b"OOPS", fake_stdout_buf.getvalue())
        finally:
            sys.stdout = real_stdout
            sys.stderr = real_stderr

    # ------------------------------------------------------------------
    # 9. Protected handle uses utf-8 encoding (non-Windows explicit check)
    # ------------------------------------------------------------------
    @unittest.skipIf(sys.platform == "win32",
                     "Windows branch wraps in binary mode; encoding check is skipped.")
    def test_harden_stdio_utf8_on_non_windows(self):
        real_stdout = sys.stdout
        real_stderr = sys.stderr
        try:
            fake_stdout_buf = io.BytesIO()
            fake_stdout = io.TextIOWrapper(fake_stdout_buf, encoding="utf-8",
                                           write_through=True)
            fake_stderr_buf = io.BytesIO()
            fake_stderr = io.TextIOWrapper(fake_stderr_buf, encoding="utf-8",
                                           write_through=True)
            sys.stdout = fake_stdout
            sys.stderr = fake_stderr

            protected = harden_stdio()
            self.assertEqual(protected.encoding.lower().replace("-", ""), "utf8")
        finally:
            sys.stdout = real_stdout
            sys.stderr = real_stderr

    # ------------------------------------------------------------------
    # 10. parse() rejects JSON-RPC batch arrays with INVALID_REQUEST
    # ------------------------------------------------------------------
    def test_parse_rejects_json_rpc_batch_array(self):
        with self.assertRaises(JsonRpcError) as ctx:
            parse("[{}]")
        self.assertEqual(ctx.exception.code, INVALID_REQUEST)

    def test_parse_rejects_non_object_payload(self):
        with self.assertRaises(JsonRpcError) as ctx:
            parse('"just a string"')
        self.assertEqual(ctx.exception.code, INVALID_REQUEST)

    # ------------------------------------------------------------------
    # Extra: ACCEPTED_PROTOCOL_VERSIONS contains the three pinned versions
    # ------------------------------------------------------------------
    def test_accepted_protocol_versions_contents(self):
        self.assertIn("2025-11-25", ACCEPTED_PROTOCOL_VERSIONS)
        self.assertIn("2025-03-26", ACCEPTED_PROTOCOL_VERSIONS)
        self.assertIn("2024-11-05", ACCEPTED_PROTOCOL_VERSIONS)


if __name__ == "__main__":
    unittest.main()
