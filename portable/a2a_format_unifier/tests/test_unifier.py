import copy
import asyncio
import json
import tempfile
import unittest
from datetime import timezone
from pathlib import Path

from a2a_format_unifier.helpers.formats import (
    FormatError, dialect_from_card, normalize_part, encode_part,
    normalize_result, encode_result, encode_message)
from a2a_format_unifier.helpers.client import Client, A2AError, converse_persisted, payload
from a2a_format_unifier.helpers.middleware import LegacyServerUnifier
from a2a_format_unifier.helpers.credentials import resolve_credential


def completed(ctx="same", text="reply", version="1.0"):
    base = {"kind": "task", "id": "t1", "contextId": ctx,
            "status": {"state": "completed", "message": {
                "kind": "message", "messageId": "m1", "role": "agent",
                "parts": [{"kind": "text", "text": text}]}},
            "artifacts": [{"artifactId": "a1", "parts": [{"kind": "text", "text": text}]}],
            "history": [], "metadata": {"kept": True}}
    return {"jsonrpc": "2.0", "id": "r1", "result": encode_result(base, version)}


class FormatTests(unittest.TestCase):
    def test_live_hermes_shape(self):
        # Recorded shape of the reply rejected by FastA2A's v0.3 validator.
        raw = {"id": "t", "contextId": "c", "status": {
            "state": "TASK_STATE_COMPLETED", "message": {
                "role": "ROLE_AGENT", "messageId": "m", "contextId": "c",
                "parts": [{"text": "ok", "mediaType": "text/plain"}]}},
            "artifacts": [{"parts": [{"text": "ok", "mediaType": "text/plain"}]}]}
        result = normalize_result(raw)
        self.assertEqual(result["kind"], "task")
        self.assertEqual(result["status"]["state"], "completed")
        self.assertEqual(result["status"]["message"]["role"], "agent")
        self.assertEqual(result["artifacts"][0]["parts"][0]["kind"], "text")
        self.assertNotIn("kind", raw)

    def test_v03_roundtrip_preserves_metadata_and_data(self):
        raw = payload(completed(version="0.3"))
        raw["artifacts"][0]["parts"].append({"kind": "data", "data": {"x": [1]}, "metadata": {"z": 2}})
        self.assertEqual(normalize_result(encode_result(raw, "1.0")), raw)

    def test_files_roundtrip(self):
        for field, value in (("uri", "https://example.test/a"), ("bytes", "YQ==")):
            old = {"kind": "file", "file": {field: value, "mimeType": "image/png", "name": "a.png"}, "metadata": {"x": 1}}
            self.assertEqual(normalize_part(encode_part(old, "1.0")), old)

    def test_unknown_or_ambiguous_formats_fail(self):
        for card in ({"protocolVersion": "2.0"}, {"supportedInterfaces": [{"protocolBinding": "GRPC", "protocolVersion": "1.0"}]}):
            with self.assertRaises(FormatError):
                dialect_from_card(card)
        with self.assertRaises(FormatError):
            normalize_part({"text": "x", "data": {}})

    def test_ids_and_roles(self):
        result = encode_message({"role": "agent", "message_id": "m", "context_id": "c", "parts": [{"kind": "text", "text": "hi"}]}, "1.0")
        self.assertEqual(result["contextId"], "c")
        self.assertEqual(result["messageId"], "m")
        self.assertEqual(result["role"], "ROLE_AGENT")
        self.assertNotIn("kind", result)

    def test_fast_a2a_profile_and_unrepresentable_parts(self):
        self.assertEqual(dialect_from_card({"protocolVersion": "0.2.5"}), "0.2.5")
        self.assertEqual(encode_part({"text": "x", "mediaType": "text/plain"}, "0.3"), {"kind": "text", "text": "x"})
        with self.assertRaises(FormatError):
            encode_part({"text": "x", "mediaType": "text/html"}, "0.3")
        with self.assertRaises(FormatError):
            normalize_result({"task": {"id": "x"}, "unknownExtension": {}})

    def test_timestamp_conversion(self):
        value = payload(completed(version="0.3"))
        value["status"]["timestamp"] = "2026-10-24T02:00:00-04:00"
        self.assertEqual(encode_result(value, "1.0")["task"]["status"]["timestamp"], "2026-10-24T06:00:00.000Z")


class ClientTests(unittest.TestCase):
    def transport(self, version="1.0", outputs=None):
        calls = []
        responses = iter(outputs or [completed(version=version)])
        def fake(method, url, body=None):
            calls.append((method, body))
            if method == "GET":
                return {"protocolVersion": version}
            return next(responses)
        return fake, calls

    def test_v1_and_v03_negotiate(self):
        for version, method, role in (("1.0", "SendMessage", "ROLE_USER"), ("0.3", "message/send", "user"), ("0.2.5", "message/send", "user")):
            transport, calls = self.transport(version)
            result = Client("http://peer.test", "secret", transport=transport).converse("hello", "prior", lambda c: None)
            request = calls[1][1]
            self.assertEqual(request["method"], method)
            self.assertEqual(request["params"]["message"]["role"], role)
            self.assertEqual(request["params"]["message"]["contextId"], "prior")
            self.assertEqual(request["params"]["configuration"]["acceptedOutputModes"], ["text/plain"])
            self.assertEqual(result["text"], "reply")

    def test_persist_across_new_clients_and_explicit_reset(self):
        with tempfile.TemporaryDirectory() as root:
            first, _ = self.transport(outputs=[completed(ctx="persisted")])
            converse_persisted(Client("http://peer.test", "x", transport=first), "one", root)
            second, calls = self.transport(outputs=[completed(ctx="persisted")])
            converse_persisted(Client("http://peer.test", "x", transport=second), "two", root)
            self.assertEqual(calls[1][1]["params"]["message"]["contextId"], "persisted")
            third, calls = self.transport()
            converse_persisted(Client("http://peer.test", "x", transport=third), "new", root, True)
            self.assertNotEqual(calls[1][1]["params"]["message"]["contextId"], "persisted")

    def test_error_does_not_resend(self):
        transport, calls = self.transport(outputs=[{"error": {"code": -1, "message": "secret"}}])
        with self.assertRaisesRegex(A2AError, "-1") as error:
            Client("http://peer.test", "x", transport=transport).converse("hi", "", lambda c: None)
        self.assertNotIn("secret", str(error.exception))
        self.assertEqual(sum(m == "POST" for m, _ in calls), 1)

    def test_failed_and_empty_are_not_success(self):
        for state, text in (("failed", "error"), ("completed", "")):
            response = completed(text=text)
            response["result"]["task"]["status"]["state"] = "TASK_STATE_" + state.upper()
            transport, _ = self.transport(outputs=[response])
            with self.assertRaises(A2AError):
                Client("http://peer.test", "x", transport=transport).converse("hi", "", lambda c: None)

    def test_poll_without_resend(self):
        pending = {"result": {"id": "t1", "contextId": "c", "status": {"state": "TASK_STATE_WORKING"}}}
        transport, calls = self.transport(outputs=[pending, completed(ctx="c")])
        result = Client("http://peer.test", "x", transport=transport).converse("hi", "", lambda c: None)
        self.assertEqual([b["method"] for m, b in calls if m == "POST"], ["SendMessage", "GetTask"])
        self.assertEqual(result["context_id"], "c")

    def test_corrupt_context_is_not_silently_reset(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "conversation.json").write_text("broken")
            transport, calls = self.transport()
            with self.assertRaisesRegex(A2AError, "invalid"):
                converse_persisted(Client("http://peer.test", "x", transport=transport), "hi", root)
            self.assertEqual(calls, [])

    def test_user_history_is_not_reply(self):
        response = completed(text="")
        response["result"]["task"]["history"] = [{"role": "ROLE_USER", "parts": [{"text": "echo"}]}]
        transport, _ = self.transport(outputs=[response])
        with self.assertRaisesRegex(A2AError, "no assistant text"):
            Client("http://peer.test", "x", transport=transport).converse("hi", "", lambda c: None)


class MiddlewareTests(unittest.IsolatedAsyncioTestCase):
    async def request(self, body=None, status=200, card=False, rejected=False, modern_card=True):
        seen = {}
        response = {"protocolVersion": "0.2.5", "url": "http://localhost:8000"} if card else completed(version="0.3")
        native_body = b'{"error":"unauthorized"}' if rejected else json.dumps(response).encode()

        async def app(scope, receive, send):
            seen["headers"] = scope.get("headers", [])
            seen["path"] = scope.get("path")
            if body is not None:
                seen["request"] = json.loads((await receive())["body"])
            await send({"type": "http.response.start", "status": status, "headers": [(b"content-type", b"application/json")]})
            await send({"type": "http.response.body", "body": native_body})

        scope = {"type": "http", "method": "GET" if card else "POST", "scheme": "http",
                 "path": ("/a2a/t-test/.well-known/agent-card.json" if modern_card else "/a2a/t-test/.well-known/agent.json") if card else "/a2a/t-test/",
                 "root_path": "/a2a", "headers": [(b"host", b"peer.test:18081"), (b"authorization", b"Bearer test")]}
        if body and body.get("method") in LegacyServerUnifier.METHODS:
            scope["headers"].append((b"a2a-version", b"1.0"))
        async def receive():
            return {"type": "http.request", "body": json.dumps(body).encode(), "more_body": False}
        sent = []
        async def send(event):
            sent.append(event)
        await LegacyServerUnifier(app)(scope, receive, send)
        return seen, sent[0], json.loads(sent[1]["body"])

    async def test_v1_request_and_response_auth_preserved(self):
        body = {"jsonrpc": "2.0", "id": 1, "method": "SendMessage", "params": {"message": {"role": "ROLE_USER", "messageId": "m", "parts": [{"text": "hi"}]}}}
        seen, start, result = await self.request(body)
        self.assertEqual(seen["request"]["method"], "message/send")
        self.assertEqual(seen["request"]["params"]["configuration"]["acceptedOutputModes"], ["text/plain"])
        self.assertEqual(seen["request"]["params"]["message"]["parts"][0]["kind"], "text")
        self.assertIn((b"authorization", b"Bearer test"), seen["headers"])
        self.assertEqual(result["result"]["task"]["status"]["state"], "TASK_STATE_COMPLETED")
        self.assertEqual(start["status"], 200)

    async def test_auth_failure_passes_through(self):
        body = {"method": "SendMessage", "params": {"message": {"role": "ROLE_USER", "parts": [{"text": "hi"}]}}}
        _, start, result = await self.request(body, 401, rejected=True)
        self.assertEqual(start["status"], 401)
        self.assertEqual(result, {"error": "unauthorized"})

    async def test_legacy_request_unchanged(self):
        body = {"method": "message/send", "params": {"message": {"kind": "message", "role": "user", "parts": [{"kind": "text", "text": "hi"}]}}}
        seen, _, result = await self.request(body)
        self.assertEqual(seen["request"], body)
        self.assertEqual(result, completed(version="0.3"))

    async def test_card_origin_preserves_path_without_duplicate_mount(self):
        seen, _, result = await self.request(card=True)
        self.assertEqual(seen["path"], "/a2a/t-test/.well-known/agent.json")
        self.assertEqual(result["url"], "http://peer.test:18081/a2a/t-test/")
        self.assertEqual(result["protocolVersion"], "0.2.5")

    async def test_native_card_is_completely_unchanged(self):
        seen, _, result = await self.request(card=True, modern_card=False)
        self.assertEqual(result, {"protocolVersion": "0.2.5", "url": "http://localhost:8000"})
        self.assertEqual(seen["path"], "/a2a/t-test/.well-known/agent.json")

    async def test_native_large_body_bypasses_unifier_size_limit(self):
        body = {"method": "message/send", "params": {"message": {"kind": "message", "role": "user", "parts": [{"kind": "text", "text": "x" * (LegacyServerUnifier.LIMIT + 1)}]}}}
        seen, start, _ = await self.request(body)
        self.assertEqual(start["status"], 200)
        self.assertEqual(seen["request"], body)

    def test_scope_opt_in_is_modern_only(self):
        native = {"type": "http", "method": "POST", "path": "/a2a/", "headers": []}
        self.assertFalse(LegacyServerUnifier.supports_scope(native))
        self.assertTrue(LegacyServerUnifier.supports_scope({**native, "headers": [(b"a2a-version", b"1.0")]}))
        self.assertFalse(LegacyServerUnifier.supports_scope({**native, "headers": [(b"a2a-version", b"0.3")]}))

    async def test_pending_native_task_polled_once_without_resending(self):
        methods = []
        async def app(scope, receive, send):
            request = json.loads((await receive())["body"])
            methods.append(request["method"])
            task = {"id": "t", "contextId": "c", "status": {"state": "submitted"}}
            if request["method"] == "tasks/get":
                task["status"] = {"state": "completed", "timestamp": "2026-10-24T06:00:00"}
                task["history"] = [{"kind": "message", "role": "agent", "messageId": "m", "parts": [{"kind": "text", "text": "answer"}]}]
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": json.dumps({"result": task}).encode()})
        async def receive():
            return {"type": "http.request", "body": json.dumps({"method": "SendMessage", "params": {"message": {"role": "ROLE_USER", "parts": [{"text": "hi"}]}}}).encode()}
        sent = []
        async def send(event):
            sent.append(event)
        await LegacyServerUnifier(app, poll_interval=0, legacy_timezone=timezone.utc)({"type": "http", "method": "POST", "path": "/a2a/t-test/", "headers": [(b"a2a-version", b"1.0")]}, receive, send)
        self.assertEqual(methods, ["message/send", "tasks/get"])
        task = json.loads(sent[1]["body"])["result"]["task"]
        self.assertEqual(task["status"]["message"]["parts"][0]["text"], "answer")
        self.assertEqual(task["status"]["timestamp"], "2026-10-24T06:00:00.000Z")


class CredentialTests(unittest.TestCase):
    def test_plugin_private_credential(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".private").mkdir()
            (root / ".private" / "peer.token").write_text("fixture-only-credential\n")
            self.assertEqual(resolve_credential({"token_file": ".private/peer.token"}, root), "fixture-only-credential")

    def test_shared_native_environment_is_reserved(self):
        with self.assertRaisesRegex(A2AError, "reserved"):
            resolve_credential({"token_env": "A2A_TOKEN"}, Path("."))

    def test_missing_conflicting_or_outside_credentials_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for entry in ({"token_file": "../outside"}, {"token_file": "/etc/passwd"},
                          {"token_file": ".private/no.token"},
                          {"token_file": ".private/x.token", "token_env": "DEDICATED_TEST"}):
                with self.assertRaises(A2AError):
                    resolve_credential(entry, root)

    def test_public_peer_has_no_credential(self):
        self.assertIsNone(resolve_credential({}, Path(".")))


if __name__ == "__main__":
    unittest.main()
