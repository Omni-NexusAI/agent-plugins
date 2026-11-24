import copy
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('contract_under_test',Path(__file__).resolve().parents[1]/'helpers/contract.py')
contract=importlib.util.module_from_spec(spec);spec.loader.exec_module(contract)
MODEL='openrouter/verified-model'


class Model:
    provider='openrouter'
    model_name=MODEL
    def __init__(self,kwargs=None):self.kwargs=kwargs if kwargs is not None else {}
    def model_copy(self,update,deep):
        assert deep is False
        result=copy.copy(self)
        result.__dict__.update(update)
        return result


class ContractTests(unittest.TestCase):
    def test_blank_and_malformed_allowlist_is_inert(self):
        model=Model()
        for config in [{},{'models':[]},None,{'models':'bad'},{'models':[1]}]:
            self.assertIs(contract.prepare_model(model,config),model)

    def test_explicit_model_clone_preserves_shared_nested_kwargs(self):
        source={'temperature':0.4,'extra_body':{'provider':{'order':['existing'],'require_parameters':False},'other':{'keep':True}}}
        model=Model(source);before=copy.deepcopy(source)
        result=contract.prepare_model(model,{'models':[MODEL]})
        self.assertIsNot(result,model)
        self.assertEqual(model.kwargs,before)
        self.assertEqual(result.kwargs['temperature'],0.4)
        self.assertEqual(result.kwargs['extra_body']['provider']['order'],['existing'])
        self.assertTrue(result.kwargs['extra_body']['provider']['require_parameters'])
        self.assertEqual(result.kwargs['extra_body']['other'],{'keep':True})

    def test_unlisted_provider_model_or_transport_is_untouched(self):
        for key,value in [('provider','other'),('model_name','openrouter/unverified')]:
            model=Model();setattr(model,key,value)
            self.assertIs(contract.prepare_model(model,{'models':[MODEL]}),model)

    def test_current_native_chat_alias_is_supported_without_changing_it(self):
        model=Model({'a0_api_mode':'chat'})
        result=contract.prepare_model(model,{'models':[MODEL]})
        self.assertIsNot(result,model)
        self.assertEqual(result.kwargs['a0_api_mode'],'chat')
        self.assertEqual(model.kwargs,{'a0_api_mode':'chat'})
        for mode in ['responses','auto','unknown']:
            model=Model({'a0_api_mode':mode})
            self.assertIs(contract.prepare_model(model,{'models':[MODEL]}),model)

    def test_existing_format_even_explicit_none_is_preserved(self):
        for value in [None,{'type':'json_object'},{'type':'json_schema'}]:
            model=Model({'response_format':value})
            self.assertIs(contract.prepare_model(model,{'models':[MODEL]}),model)

    def test_existing_native_tool_contract_is_not_replaced(self):
        for kwargs in [{'tools':[{'type':'function'}]},{'tool_choice':'required'}]:
            model=Model(kwargs)
            self.assertIs(contract.prepare_model(model,{'models':[MODEL]}),model)

    def test_nested_provider_contracts_are_not_shadowed(self):
        for extra in [{'response_format':None},{'response_format':{'type':'json_object'}},
                      {'tools':[{'type':'function'}]},{'tool_choice':'required'},
                      {'text':{'format':{'type':'json_schema'}}}]:
            model=Model({'extra_body':extra});before=copy.deepcopy(model.kwargs)
            self.assertIs(contract.prepare_model(model,{'models':[MODEL]}),model)
            self.assertEqual(model.kwargs,before)
        model=Model({'text':{'format':{'type':'json_schema'}}})
        self.assertIs(contract.prepare_model(model,{'models':[MODEL]}),model)

    def test_unsupported_copy_or_provider_shape_is_inert(self):
        for kwargs in [{'extra_body':None},{'extra_body':{'provider':None}}]:
            model=Model(kwargs)
            self.assertIs(contract.prepare_model(model,{'models':[MODEL]}),model)
        model=Model();model.model_copy=None
        self.assertIs(contract.prepare_model(model,{'models':[MODEL]}),model)

    def test_envelope_does_not_force_tool_answer_or_completion(self):
        result=contract.prepare_model(Model(),{'models':[MODEL]})
        schema=result.kwargs['response_format']['json_schema']['schema']
        self.assertEqual(schema['properties']['tool_name'],{'type':'string'})
        self.assertEqual(schema['properties']['tool_args'],{'type':'object','additionalProperties':True})
        self.assertNotIn('const',schema['properties']['tool_name'])
        self.assertNotIn('text',schema['properties']['tool_args'])

    def test_concurrent_clones_and_schema_do_not_share_state(self):
        model=Model();a=contract.prepare_model(model,{'models':[MODEL]});b=contract.prepare_model(model,{'models':[MODEL]})
        a.kwargs['response_format']['json_schema']['schema']['required'].append('mutated')
        self.assertNotIn('mutated',b.kwargs['response_format']['json_schema']['schema']['required'])
        self.assertNotIn('mutated',contract.ENVELOPE['required'])
        self.assertEqual(model.kwargs,{})

    def test_supported_hook_changes_only_the_per_call_model(self):
        extension=types.ModuleType('helpers.extension');extension.Extension=object
        plugins=types.ModuleType('helpers.plugins');plugins.get_plugin_config=lambda *a:{'models':[MODEL]}
        modules={'helpers':types.ModuleType('helpers'),'helpers.extension':extension,'helpers.plugins':plugins,
                 'usr':types.ModuleType('usr'),'usr.plugins':types.ModuleType('usr.plugins'),
                 'usr.plugins.native_tool_output_contract':types.ModuleType('usr.plugins.native_tool_output_contract'),
                 'usr.plugins.native_tool_output_contract.helpers':types.ModuleType('usr.plugins.native_tool_output_contract.helpers'),
                 'usr.plugins.native_tool_output_contract.helpers.contract':contract}
        with patch.dict(sys.modules,modules):
            path=Path(__file__).resolve().parents[1]/'extensions/python/chat_model_call_before/_90_native_tool_envelope.py'
            hook_spec=importlib.util.spec_from_file_location('contract_hook_under_test',path)
            hook_module=importlib.util.module_from_spec(hook_spec);hook_spec.loader.exec_module(hook_module)
            hook=hook_module.NativeToolEnvelope();hook.agent=object()
            model=Model();messages=[{'role':'user','content':'unchanged'}];callback=object()
            call={'model':model,'messages':messages,'response_callback':callback,'background':False}
            hook.execute(call)
            self.assertIsNot(call['model'],model)
            self.assertIs(call['messages'],messages)
            self.assertIs(call['response_callback'],callback)
            self.assertEqual(model.kwargs,{})
            for key in ('a0_responses_function_tools','a0_chat_function_tools','tools'):
                native={'model':model,key:[{'type':'function'}]}
                hook.execute(native)
                self.assertIs(native['model'],model)


if __name__=='__main__':unittest.main()
