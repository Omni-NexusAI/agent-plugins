"""Offline native-runtime regression checks; never installs or calls a provider."""
import asyncio, copy, importlib, inspect, json, os, pathlib, sys, types, unittest
from unittest.mock import patch
from contextlib import contextmanager

HERE=pathlib.Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parents[1])); sys.path.insert(0,'/a0')
import initial_greeting_guard
sys.modules['usr.plugins.initial_greeting_guard']=initial_greeting_guard
from initial_greeting_guard.helpers import seed
sys.modules['usr.plugins.initial_greeting_guard.helpers.seed']=seed
from agent import Agent, UserMessage, LoopData
from helpers import extension, history, files
from helpers.llm_result import LLMResult, metadata_from_llm_result
from langchain_core.messages import SystemMessage
import models

Mark=importlib.import_module('initial_greeting_guard.extensions.python._functions.agent.Agent.hist_add_message.end._10_mark_initial_seed').MarkInitialSeed
Filter=importlib.import_module('initial_greeting_guard.extensions.python.message_loop_prompts_after._98_omit_initial_seed').OmitInitialSeed
Initial=importlib.import_module('extensions.python.agent_init._10_initial_message').InitialMessage

class Log:
 def __init__(self):self.logs=[]
 def log(self,**kwargs):self.logs.append(types.SimpleNamespace(**kwargs)); return self.logs[-1]
 def set_progress(self,*args,**kwargs):pass

@contextmanager
def native_fixture():
 def dispatch(point,agent=None,**kwargs):
  if point=='_functions/agent/Agent/hist_add_message/end':Mark(agent=agent).execute(**kwargs)
 def create(number=0):
  a=object.__new__(Agent); a.number=number;a.agent_name=f'A{number}';a.data={};a.config=types.SimpleNamespace(profile='agent0')
  a.context=types.SimpleNamespace(log=Log(),last_message=None);a.history=history.History(a);a.last_user_message=None
  a.read_prompt=lambda file,**kwargs: files.remove_code_fences(pathlib.Path('/a0/prompts',file).read_text()).strip()
  a.parse_prompt=lambda file,**kwargs: {'user_message':kwargs['message']} if file=='fw.user_message.md' else kwargs['message']
  a.loop_data=LoopData()
  return a
 with patch.object(extension,'call_extensions_sync',dispatch), patch.object(history.History,'_get_max_embeds',lambda self:0):
  yield create

def initialized(make):
 a=make(); Initial(agent=a).execute(); return a

def add_task(a,text='Compute 17*23 and report TASK_MARKER'):
 return a.hist_add_user_message(UserMessage(message=text))

def filtered(a):
 loop=LoopData();loop.history_output=a.history.output(); Filter(agent=a).execute(loop_data=loop);return loop.history_output

def test_real_native_initializer_marks_only_its_pair(make):
 a=initialized(make); records=a.history.all_messages()
 assert len(records)==2 and all(seed.KEY in r.metadata for r in records)
 assert len(a.context.log.logs)==1 and a.context.log.logs[0].id==records[1].id
 assert 'Hello' in a.context.log.logs[0].content
 actual=add_task(a); assert seed.KEY not in actual.metadata

def test_model_filter_preserves_persisted_history_and_ui(make):
 a=initialized(make);task=add_task(a)
 a.hist_add_ai_response('{"tool_name":"code_execution_tool","tool_args":{"runtime":"terminal","code":"print(17*23)"}}')
 a.hist_add_tool_result('code_execution_tool','391')
 before=a.history.serialize(); logs=copy.deepcopy(a.context.log.logs)
 records=filtered(a)
 assert [x['sequence'] for x in records]==[3,4,5]
 assert records[0]['id']==task.id
 assert before==a.history.serialize() and logs==a.context.log.logs
 llm=models.LiteLLMChatWrapper(model='diagnostic',provider='openrouter')
 wire=llm._convert_messages([SystemMessage(content='Synthetic offline test'),*history.output_langchain(records)])
 assert [x['role'] for x in wire]==['system','user','assistant','user']
 assert 'TASK_MARKER' in wire[1]['content'] and '391' in wire[-1]['content']

def test_genuine_user_hello_survives(make):
 a=initialized(make);actual=add_task(a,'Hello!');a.hist_add_ai_response('A genuine answer')
 records=filtered(a)
 assert records[0]['id']==actual.id and records[0]['content']=={'user_message':'Hello!'}
 assert records[1]['content']=='A genuine answer'

def test_later_greeting_and_tools_survive(make):
 a=initialized(make);add_task(a);a.hist_add_ai_response('Hello later');a.hist_add_tool_result('test','Hello!')
 assert [x['content'] for x in filtered(a)][-2:]==['Hello later',{'tool_name':'test','tool_result':'Hello!'}]

def test_unmarked_lookalike_never_filtered_or_retroactively_tagged(make):
 a=make();a.hist_add_user_message(UserMessage(message='Hello!'))
 a.hist_add_ai_response(a.read_prompt('fw.initial_message.md'),llm_result=LLMResult.non_llm())
 add_task(a);records=a.history.output()
 assert all(seed.KEY not in x['metadata'] for x in records)
 assert seed.model_history(records) is records

def test_native_seed_only_no_real_task_remains(make):
 a=initialized(make);records=a.history.output();assert seed.model_history(records) is records

MUTATIONS=[
 lambda r:r[0]['metadata'].pop(seed.KEY),
 lambda r:r[1]['metadata'].pop(seed.KEY),
 lambda r:r[0]['metadata'][seed.KEY].update(origin='unknown'),
 lambda r:r[0]['metadata'][seed.KEY].update(source_sha256='unsupported'),
 lambda r:r[1]['metadata'][seed.KEY].update(user_id='other'),
 lambda r:r[0].update(id='changed'),
 lambda r:r[1].update(sequence=7),
 lambda r:r[0].update(ai=True),
 lambda r:r[0].update(content={'user_message':'Real edited request'}),
 lambda r:r[1].update(content='Real edited assistant reply'),
 lambda r:r[2].update(content={'tool_name':'test','tool_result':'receipt'}),
 lambda r:r[2].update(ai=True),
]
def test_ambiguous_modified_or_unsupported_records_fail_closed(make,mutation):
 a=initialized(make);add_task(a);records=copy.deepcopy(a.history.output());mutation(records)
 assert seed.model_history(records) is records

def test_contexts_and_subordinates_are_isolated(make):
 a=initialized(make);b=initialized(make);add_task(a,'A task');add_task(b,'B task')
 assert filtered(a)[0]['content']=={'user_message':'A task'}
 assert filtered(b)[0]['content']=={'user_message':'B task'}
 assert a.history.all_messages()[0].metadata[seed.KEY]['user_id']!=b.history.all_messages()[0].metadata[seed.KEY]['user_id']
 sub=make(1);Initial(agent=sub).execute();assert all(seed.KEY not in m.metadata for m in sub.history.all_messages())

def test_restored_marker_filters_without_rewriting(make):
 a=initialized(make);add_task(a);b=make();history.History.from_dict(json.loads(a.history.serialize()),b.history)
 before=b.history.serialize();assert len(filtered(b))==1;assert b.history.serialize()==before

def test_unsupported_initializer_source_is_never_marked(make):
 seed._trusted_source.cache_clear()
 with patch.object(seed,'SUPPORTED_INITIALIZERS',frozenset()):
  a=initialized(make);assert all(seed.KEY not in m.metadata for m in a.history.all_messages())
 seed._trusted_source.cache_clear()

def test_disabled_hooks_leave_native_history_unchanged(make):
 with patch.object(extension,'call_extensions_sync',lambda *args,**kwargs:None):
  a=initialized(make);add_task(a)
 assert all(seed.KEY not in m.metadata for m in a.history.all_messages())
 assert len(a.history.output())==3

def test_native_prepare_prompt_filters_before_native_message_grouping(make):
 a=initialized(make);add_task(a,'Real user task');before=a.history.serialize();a.loop_data=LoopData()
 async def system(_loop):return ['Synthetic system instructions']
 async def dispatch(point,agent=None,**kwargs):
  if point=='message_loop_prompts_after':Filter(agent=agent).execute(**kwargs)
 a.get_system_prompt=system
 a.read_prompt=lambda file,**kwargs: '[EXTRAS] '+kwargs['extras'] if file=='agent.context.extras.md' else '[PROTOCOL] '+kwargs['protocol']
 with patch.object(extension,'call_extensions_async',dispatch):
  prompt=asyncio.run(Agent.prepare_prompt.__wrapped__(a,a.loop_data))
 assert [m.type for m in prompt]==['system','human']
 assert 'Real user task' in str(prompt[1].content) and 'Hello!' not in str(prompt[1].content)
 assert a.history.serialize()==before

def test_old_actual_chats_are_unchanged_without_provenance():
 for cid in filter(None,os.environ.get('A0_AUDIT_CHAT_IDS','').split(',')):
  p=pathlib.Path('/a0/usr/chats',cid,'chat.json');original=p.read_bytes();d=json.loads(original)
  def walk(v):
   if isinstance(v,dict):
    if v.get('_cls')=='Message':yield v
    else:
     for x in v.values():yield from walk(x)
   elif isinstance(v,list):
    for x in v:yield from walk(x)
  records=list(walk(json.loads(d['agents'][0]['history'])))
  assert seed.model_history(records) is records and p.read_bytes()==original

def test_v215_native_seed_metadata_is_preserved(make):
 a=initialized(make); records=a.history.all_messages()
 assert records[0].metadata['initial_seed'] is True
 assert all(seed.KEY in record.metadata for record in records)

def test_unexpected_native_seed_metadata_prevents_marking(make):
 original=Agent.hist_add_user_message
 def add_with_extra(agent,*args,**kwargs):
  message=original(agent,*args,**kwargs);message.metadata['unreviewed']=True;return message
 with patch.object(Agent,'hist_add_user_message',add_with_extra):a=initialized(make)
 assert all(seed.KEY not in record.metadata for record in a.history.all_messages())

def test_change_hook_refreshes_only_own_namespace():
 cls=importlib.import_module('initial_greeting_guard.extensions.python._functions.helpers.plugins.after_plugin_change.end._91_initial_greeting_guard').RefreshGreetingProvenance
 hook=cls(agent=None)
 with patch('helpers.modules.purge_namespace') as purge:
  hook.execute({'args':(['another_plugin'],)})
  hook.execute({'exception':RuntimeError('fixture')})
  purge.assert_not_called()
  hook.execute({'args':(['initial_greeting_guard'],)})
  purge.assert_called_once_with('usr.plugins.initial_greeting_guard')


class NativeRegression(unittest.TestCase):
 pass

def bind_test(function,mutation=None):
 def run(self):
  with native_fixture() as make:
   kwargs={'make':make} if 'make' in inspect.signature(function).parameters else {}
   if mutation is not None:kwargs['mutation']=mutation
   function(**kwargs)
 return run

for name,function in list(globals().items()):
 if name.startswith('test_') and callable(function):
  if 'mutation' in inspect.signature(function).parameters:
   for index,mutation in enumerate(MUTATIONS):
    setattr(NativeRegression,name+f'_{index:02}',bind_test(function,mutation))
  else:setattr(NativeRegression,name,bind_test(function))

if __name__=='__main__':unittest.main(verbosity=2)
