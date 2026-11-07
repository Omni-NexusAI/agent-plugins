import copy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from a2a_format_unifier.helpers.fallback import adapt_rejected_reply
from a2a_format_unifier.helpers.formats import FormatError
from a2a_format_unifier.helpers.native_client import configured_endpoint
from a2a_format_unifier.helpers import native_client

try:
    import httpx
    import pydantic
    AgentConnection = native_client._native_connection_class()
    from fasta2a.client import UnexpectedResponseError
    from a2a_format_unifier.helpers import native_client
    NATIVE_AVAILABLE = True
except ImportError:
    NATIVE_AVAILABLE = False


def result_v1():
    return {"task": {"id": "fixture-task", "contextId": "fixture-context", "status": {
        "state": "TASK_STATE_COMPLETED", "message": {"role": "ROLE_AGENT", "messageId": "reply",
        "parts": [{"text": "fixture reply"}]}}, "history": []}}


class ScopeTests(unittest.TestCase):
    def test_legacy_layout_is_preferred(self):
        native = object()
        with patch.object(native_client, 'import_module', return_value=SimpleNamespace(AgentConnection=native)) as load:
            self.assertIs(native_client._native_connection_class(), native)
        load.assert_called_once_with('helpers.fasta2a_client')

    def test_v215_layout_only_after_missing_legacy_module(self):
        native = object()
        missing = ModuleNotFoundError(name='helpers.fasta2a_client')
        with patch.object(native_client, 'import_module', side_effect=[missing, SimpleNamespace(AgentConnection=native)]) as load:
            self.assertIs(native_client._native_connection_class(), native)
        self.assertEqual([c.args[0] for c in load.call_args_list], ['helpers.fasta2a_client', 'plugins._a2a_chat.helpers.fasta2a_client'])

    def test_missing_nested_dependency_is_not_masked(self):
        failure = ModuleNotFoundError(name='httpx')
        with patch.object(native_client, 'import_module', side_effect=failure) as load:
            with self.assertRaises(ModuleNotFoundError) as caught:
                native_client._native_connection_class()
        self.assertIs(caught.exception, failure)
        self.assertEqual(load.call_count, 1)

    def test_exact_endpoint_only_no_name_or_default_selection(self):
        config = {"endpoints": [{"url": "http://hermes.test:9900/", "framework": "hermes"}]}
        self.assertIsNone(configured_endpoint(config, "http://laptop.test:5027/a2a"))
        self.assertIsNone(configured_endpoint(config, "http://hermes.test:9900/other-agent"))
        self.assertIsNotNone(configured_endpoint(config, "http://hermes.test:9900"))
        self.assertIsNone(configured_endpoint({}, "http://laptop.test:5027/a2a"))

    def test_native_agent_zero_is_not_converted(self):
        with self.assertRaisesRegex(FormatError, "Native Agent Zero"):
            adapt_rejected_reply({"result": result_v1()}, {"name": "LaptopA0", "provider": {"organization": "Agent Zero"}, "protocolVersion": "1.0"}, lambda x: x)


@unittest.skipUnless(NATIVE_AVAILABLE, "requires installed Agent Zero/FastA2A")
class NativeTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_init = AgentConnection.__init__
        cls.original_card = AgentConnection.get_agent_card
        native_client.install()

    @classmethod
    def tearDownClass(cls):
        AgentConnection.__init__ = cls.original_init
        AgentConnection.get_agent_card = cls.original_card

    async def exercise(self, *, native=False, malformed=False, disabled=False, status=200, unknown=False, config=None, modern_card_only=False):
        calls = []
        card = {"name": "LaptopA0" if native else "Cross-framework fixture",
                "provider": {"organization": "Agent Zero" if native else "Other Framework"},
                "protocolVersion": "9.0" if unknown else ("0.2.5" if native else "1.0")}
        body = result_v1()
        if native and not malformed:
            body = {"kind": "task", "id": "fixture-task", "contextId": "fixture-context",
                    "status": {"state": "completed"}, "history": [{"kind": "message", "role": "agent", "messageId": "reply", "parts": [{"kind": "text", "text": "fixture reply"}]}]}

        async def respond(request):
            calls.append((request.method, str(request.url), request.content))
            if request.method == "GET":
                if modern_card_only and request.url.path.endswith("agent.json"):
                    return httpx.Response(404, json={})
                return httpx.Response(200, json=card)
            data = json.loads(request.content)
            return httpx.Response(status, json={"jsonrpc": "2.0", "id": data.get("id"), "result": copy.deepcopy(body)})

        self.calls = calls
        with patch('helpers.plugins.get_enabled_plugins', return_value=[] if disabled else ['a2a_format_unifier']), \
             patch('helpers.plugins.get_plugin_config', return_value=config or {"endpoints": []}):
            connection = AgentConnection('http://selected.test/a2a')
            previous = connection._http_client
            replacement = httpx.AsyncClient(base_url=previous.base_url, transport=httpx.MockTransport(respond), headers=previous.headers, event_hooks=previous.event_hooks)
            await previous.aclose()
            connection._http_client = replacement
            native_object = getattr(connection._a2a_client, 'native', connection._a2a_client)
            native_object.http_client = replacement
            try:
                await connection.get_agent_card()
                sent = await connection.send_message('fixture request')
                final = await connection.get_task(sent['result']['id'])
                return sent, final
            finally:
                await connection.close()

    async def test_cross_framework_native_parse_failure_adapts_without_resend(self):
        sent, final = await self.exercise()
        self.assertEqual(sent['result']['context_id'], 'fixture-context')
        self.assertEqual(final['result']['status']['state'], 'completed')
        methods = [json.loads(body)['method'] for method, _, body in self.calls if method == 'POST']
        self.assertEqual(methods, ['message/send', 'tasks/get'])
        self.assertTrue(all(url.startswith('http://selected.test/a2a') for _, url, _ in self.calls))

    async def test_compatible_native_agent_uses_native_parser_only(self):
        with patch.object(native_client, 'adapt_rejected_reply', side_effect=AssertionError('fallback must not run')):
            sent, _ = await self.exercise(native=True)
        self.assertEqual(sent['result']['status']['state'], 'completed')

    async def test_malformed_agent_zero_is_not_adapted(self):
        with self.assertRaises(pydantic.ValidationError):
            await self.exercise(native=True, malformed=True)
        self.assertEqual(sum(method == 'POST' for method, _, _ in self.calls), 1)

    async def test_disabled_plugin_retains_original_validation(self):
        with self.assertRaises(pydantic.ValidationError):
            await self.exercise(disabled=True)
        self.assertEqual(sum(method == 'POST' for method, _, _ in self.calls), 1)

    async def test_auth_failure_never_triggers_format_fallback(self):
        with patch.object(native_client, 'adapt_rejected_reply', side_effect=AssertionError('auth must not trigger fallback')):
            with self.assertRaises(UnexpectedResponseError):
                await self.exercise(status=401)
        self.assertEqual(sum(method == 'POST' for method, _, _ in self.calls), 1)

    async def test_unknown_format_fails_without_resending(self):
        with self.assertRaises(FormatError):
            await self.exercise(unknown=True)
        self.assertEqual(sum(method == 'POST' for method, _, _ in self.calls), 1)

    async def test_explicit_card_identity_mismatch_stops_before_message(self):
        config = {'endpoints': [{'url': 'http://selected.test/a2a', 'framework': 'other', 'expected_agent_name': 'Different agent'}]}
        with self.assertRaisesRegex(RuntimeError, 'identity'):
            await self.exercise(config=config)
        self.assertFalse(any(method == 'POST' for method, _, _ in self.calls))

    async def test_modern_card_alias_read_only_same_endpoint(self):
        await self.exercise(modern_card_only=True)
        self.assertTrue(any(url.endswith('/a2a/.well-known/agent-card.json') for _, url, _ in self.calls))
        self.assertEqual(sum(method == 'POST' for method, _, _ in self.calls), 2)


@unittest.skipUnless(NATIVE_AVAILABLE, "requires installed Agent Zero/FastA2A")
class LifecycleTests(unittest.TestCase):
    def test_change_extension_refreshes_only_its_namespace(self):
        from a2a_format_unifier.extensions.python._functions.helpers.plugins.after_plugin_change.end._90_a2a_unifier import ActivateA2AUnifier
        from usr.plugins.a2a_format_unifier.helpers import bindings as live_bindings
        hook = ActivateA2AUnifier(agent=None)
        with patch('helpers.modules.purge_namespace') as purge, patch.object(live_bindings, 'after_plugin_change') as activate:
            hook.execute({'args': (['another_plugin'],)})
            hook.execute({'args': (['a2a_format_unifier'],), 'exception': RuntimeError('fixture')})
            purge.assert_not_called()
            activate.assert_not_called()
            hook.execute({'args': (['a2a_format_unifier'],)})
            purge.assert_called_once_with('usr.plugins.a2a_format_unifier')
            activate.assert_called_once()

    def test_disabled_activation_does_not_install_either_binding(self):
        from a2a_format_unifier.helpers import bindings, server
        with patch('helpers.plugins.get_enabled_plugins', return_value=[]), \
             patch.object(native_client, 'install') as client, patch.object(server, 'install') as inbound:
            self.assertEqual(bindings.install_enabled(), {'enabled': False, 'server': False, 'client': False})
        client.assert_not_called()
        inbound.assert_not_called()

    def test_unrelated_or_failed_change_does_not_activate(self):
        from a2a_format_unifier.helpers import bindings
        with patch.object(bindings, 'install_enabled') as install:
            bindings.after_plugin_change({'args': (['another_plugin'],), 'kwargs': {}, 'exception': None})
            bindings.after_plugin_change({'args': (['a2a_format_unifier'],), 'exception': RuntimeError('failed')})
        install.assert_not_called()

    def test_own_toggle_and_full_refresh_use_enabled_installation(self):
        from a2a_format_unifier.helpers import bindings
        with patch.object(bindings, 'install_enabled', return_value='installed') as install:
            self.assertEqual(bindings.after_plugin_change({'kwargs': {'plugin_names': ['a2a_format_unifier']}}), 'installed')
            self.assertEqual(bindings.after_plugin_change({'args': (None,)}), 'installed')
        self.assertEqual(install.call_count, 2)

    def test_real_binding_installation_is_idempotent_and_restorable(self):
        from a2a_format_unifier.helpers import bindings, server
        from helpers.fasta2a_server import DynamicA2AProxy
        original_init, original_card, original_server = AgentConnection.__init__, AgentConnection.get_agent_card, DynamicA2AProxy.__call__
        try:
            with patch('helpers.plugins.get_enabled_plugins', return_value=['a2a_format_unifier']):
                first = bindings.install_enabled()
                second = bindings.install_enabled()
            self.assertEqual(first, {'enabled': True, 'server': True, 'client': True})
            self.assertEqual(second, {'enabled': True, 'server': False, 'client': False})
            self.assertIs(AgentConnection.__init__._a2a_original, original_init)
            self.assertIs(DynamicA2AProxy.__call__._a2a_original, original_server)
        finally:
            AgentConnection.__init__, AgentConnection.get_agent_card, DynamicA2AProxy.__call__ = original_init, original_card, original_server

    def test_unsupported_binding_does_not_disable_other_direction(self):
        from a2a_format_unifier.helpers import bindings, server
        with patch('helpers.plugins.get_enabled_plugins', return_value=['a2a_format_unifier']), \
             patch.object(server, 'install', side_effect=RuntimeError('unsupported')), \
             patch.object(native_client, 'install', return_value=True):
            result = bindings.install_enabled()
        self.assertEqual(result, {'enabled': True, 'server': False, 'client': True})


if __name__ == '__main__':
    unittest.main()
