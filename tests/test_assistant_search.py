import json
import time

import httpx
import pytest
from sqlalchemy import update

from assistant_desk import DeskWorker
from assistant_search import quick_contact_answer, rank_contacts, rank_files, sheet_snippets
from ai_service import AIConfig, NeonAI, build_context
from workspace import Forbidden, WorkspaceError, users
from tests.test_assistant_desk import desk, submit


QUESTION = 'ابغاك تعطيني ايميلات ١-المراكز ٢-وايميلات مدرائها لكل من (الاسكان، السليمانية بعنيزة ، الضاحي الغربي )'


def contacts():
    result = [{'id':f'irrelevant_{i}','name':f'شخص آخر {i}','org':'جهة أخرى','projectId':'p_work','version':1} for i in range(40)]
    result += [
        {'id':'iskan','name':'مدير الإسكان','centerName':'الإسكان','city':'بريدة','org':'مركز صحي الإسكان ببريدة',
         'email':'iskan-manager@example.test','centerEmail':'iskan-center@example.test','version':2,'projectId':'p_work'},
        {'id':'sulaimaniya','name':'مدير السليمانية','centerName':'مركز صحي السليمانية','city':'عنيزة','org':'مركز صحي السليمانية بعنيزة',
         'email':'sulaimaniya-manager@example.test','centerEmail':'sulaimaniya-center@example.test','version':2,'projectId':'p_work'},
        {'id':'dahi','name':'مدير الضاحي','centerName':'الضاحي','city':'بريدة','org':'مركز صحي الضاحي',
         'email':'dahi-manager@example.test','centerEmail':'dahi-center@example.test','version':2,'projectId':'p_work'},
        {'id':'center_only','name':'مركز صحي الإسكان','org':'','email':'iskan-center@example.test',
         'centerEmail':'iskan-center@example.test','projectId':'p_work','version':1},
    ]
    return result


def seed_contacts(store,token):
    for record in contacts(): store.put(token,'stakeholders',record)


def test_same_screenshot_request_finds_late_contacts_and_keeps_alias_uncertain():
    answer, matched, warnings = quick_contact_answer(QUESTION,contacts())
    assert {r['id'] for r in matched}=={'iskan','sulaimaniya','dahi'}
    for center in ('iskan','sulaimaniya','dahi'):
        assert f'{center}-manager@example.test' in answer
        assert f'{center}-center@example.test' in answer
    assert 'غير متوفر' not in answer
    assert len(warnings)==1 and 'الضاحي الغربي' in warnings[0] and 'غير مطابق' in warnings[0]
    assert 'يحتاج تحقق' in answer


def test_directory_lookup_does_not_skip_write_or_drafting_requests():
    for question in ('اعطني ايميلات (الإسكان) واضف مهمة للمتابعة','اكتب رسالة لمدير الإسكان مع البريد',
                     'اعطني ايميل (الإسكان) واحفظه','عدل بريد المركز (الإسكان)'):
        assert quick_contact_answer(question,contacts()) is None


def test_same_center_name_in_two_cities_requires_disambiguation():
    first = contacts()[40] | {'id':'one','centerName':'الصفراء','city':'بريدة','org':'مركز صحي الصفراء'}
    second = first | {'id':'two','city':'المذنب','centerEmail':'different@example.test'}
    assert quick_contact_answer('اعطني ايميل (الصفراء)',[first,second]) is None
    answer, selected, warnings = quick_contact_answer('اعطني ايميل (الصفراء بالمذنب)',[first,second])
    assert [r['id'] for r in selected]==['two'] and not warnings
    assert 'different@example.test' in answer


def test_missing_fields_use_file_search_instead_of_a_false_unavailable_answer():
    c = contacts()[40] | {'centerEmail':''}
    assert quick_contact_answer('اعطني ايميلات المركز ومديره (الإسكان)',[c]) is None


def test_model_context_ranks_all_contacts_not_just_first_thirty(desk):
    store,token,_,repo=desk
    seed_contacts(store,token)
    store.put(token,'stakeholders',contacts()[40]|{'id':'other','projectId':'p_general','email':'OUTSIDE_SECRET'})
    submit(desk,question=QUESTION)
    data,refs,_,guards=repo.prepare(repo.claim())
    assert {'iskan','sulaimaniya','dahi'} <= {c['id'] for c in data['contacts']}
    assert 'OUTSIDE_SECRET' not in json.dumps(data)
    assert data['search_summary']['contacts_scanned']==44
    assert {'iskan','sulaimaniya','dahi'} <= set(guards['stakeholders'])
    assert all(c['source_ref'].startswith('C') for c in data['contacts'])
    assert any(s.get('contact_id')=='iskan' for s in refs)


def test_spreadsheet_lookup_keeps_late_matching_rows_and_column_headers(desk):
    store,token,_,repo=desk
    rows=[['المركز','اسم المدير','بريد المدير','بريد المركز']]
    rows += [['مكان آخر','اسم آخر','x'*150,'z'*150] for _ in range(1200)]
    rows += [['الإسكان','مدير الإسكان','manager@example.test','center@example.test']]
    record={'id':'directory','title':'مدراء_المراكز.xlsx','type':'sheet','projectId':'p_work',
            'sheets':[{'name':'دليل المراكز','rows':rows}]}
    store.put(token,'files',record)
    store.put(token,'files',{'id':'wrong','title':'الإسكان_نواقص_الأطباء.xlsx','type':'sheet','projectId':'p_work',
              'sheets':[{'name':'نواقص الأطباء','rows':[['المركز','النواقص'],['الإسكان','الفحص السريري']]}]})
    ranked=rank_files(store.read(token)[0]['files'],'ايميلات مدير الإسكان')
    assert ranked[0]['id']=='directory'
    state,_=store.read(token)
    data,refs,_=build_context(store,token,state,'p_work',['directory'],'ايميلات مدير الإسكان')
    source=next(s for s in data['sources'] if 'manager@example.test' in s['text'])
    assert 'بريد المدير' in source['text'] and 'center@example.test' in source['text']
    assert source['row']==1202 and source['sheet']=='دليل المراكز'
    assert any(s.get('row')==1202 for s in refs)


def test_read_tool_is_project_scoped_and_registers_edit_target_versions(desk):
    store,token,_,repo=desk
    seed_contacts(store,token)
    store.put(token,'stakeholders',contacts()[40]|{'id':'outside','projectId':'p_general','centerEmail':'OUTSIDE_SECRET'})
    submit(desk)
    job=repo.claim()
    _,refs,warnings,guards=repo.prepare(job)
    search=repo.searcher(job,refs,warnings,guards)
    result=search({'kind':'contacts','query':'الإسكان','limit':5})
    assert any(r['id']=='iskan' for r in result['results'])
    assert 'OUTSIDE_SECRET' not in json.dumps(result)
    assert guards['stakeholders']['iskan']==1
    with pytest.raises(WorkspaceError): search({'kind':'contacts','query':'الإسكان','project_id':'p_general'})


def test_read_tool_stops_immediately_when_request_owner_is_disabled(desk):
    store,token,_,repo=desk
    submit(desk)
    job=repo.claim()
    _,refs,warnings,guards=repo.prepare(job)
    search=repo.searcher(job,refs,warnings,guards)
    with store.engine.begin() as conn:
        conn.execute(update(users).where(users.c.id==job['owner']['id']).values(active=False))
    with pytest.raises(Forbidden): search({'kind':'contacts','query':'الإسكان'})


def test_requested_official_email_update_keeps_person_email_and_other_contacts(desk):
    store,token,_,repo=desk
    seed_contacts(store,token)
    submit(desk,question='حدث بريد مركز الإسكان الرسمي إلى official@example.test')
    job=repo.claim()
    _,refs,warnings,guards=repo.prepare(job)
    repo.searcher(job,refs,warnings,guards)({'kind':'contacts','query':'الإسكان'})
    repo.finish(job['id'],job['details']['lease'],'حدثت البريد الرسمي',[
        {'kind':'contact_update','target_id':'iskan','values':{'centerEmail':'official@example.test'}}
    ],{},refs,warnings,guards,'configured')
    records={c['id']:c for c in store.read(token)[0]['stakeholders']}
    assert records['iskan']['centerEmail']=='official@example.test'
    assert records['iskan']['email']=='iskan-manager@example.test'
    assert records['sulaimaniya']['centerEmail']=='sulaimaniya-center@example.test'


def test_direct_contact_requests_finish_even_when_gateway_is_unconfigured_or_cooling_down(desk):
    store,token,_,repo=desk
    seed_contacts(store,token)
    submit(desk,question=QUESTION)
    def never_call(config): raise AssertionError('Directory lookup must not spend inference credits')
    worker=DeskWorker(repo,None,client_factory=never_call)
    worker.not_before=time.time()+3600
    worker.kick()
    worker.close()
    job=repo.list_requests(token,'p_work')[0]
    assert job['status']=='complete' and job['model']=='workspace-directory'
    assert 'iskan-center@example.test' in job['answer']
    assert job['meta']['executed']==0 and job['meta']['usage']=={}


def test_assistant_resource_reload_uses_current_factories(monkeypatch):
    import assistant_ui
    class Stale:
        def __init__(self,*args,**kwargs): raise AssertionError('stale assistant resource')
    class CurrentDesk:
        def __init__(self,store): self.store=store
    class CurrentWorker:
        def __init__(self,desk,config,client_factory): self.desk,self.client=desk,client_factory
    class ReloadedDesk(CurrentDesk): pass
    for name in ('AssistantDesk','DeskWorker','NeonAI'): monkeypatch.setattr(assistant_ui,name,Stale)
    store=object()
    first=assistant_ui.resources('search-reload-current',store,None,CurrentDesk,CurrentWorker,object)
    assert isinstance(first[0],CurrentDesk) and first[1].client is object
    assert assistant_ui.resources('search-reload-current',store,None,CurrentDesk,CurrentWorker,object) is first
    reloaded=assistant_ui.resources('search-reload-next',store,None,ReloadedDesk,CurrentWorker,object)
    assert isinstance(reloaded[0],ReloadedDesk) and reloaded is not first


def test_gateway_can_search_then_answer_and_accumulates_usage():
    requests=[]
    def respond(request):
        payload=json.loads(request.content)
        requests.append(payload)
        if len(requests)==1:
            assert any(t['function']['name']=='search_project' for t in payload['tools'])
            return httpx.Response(200,json={'choices':[{'message':{'role':'assistant','content':None,'tool_calls':[
                {'id':'read_1','type':'function','function':{'name':'search_project','arguments':json.dumps({'kind':'contacts','query':'الإسكان'})}}
            ]},'finish_reason':'tool_calls'}],'usage':{'total_tokens':20}})
        assert payload['messages'][-1]['role']=='tool'
        assert 'center@example.test' in payload['messages'][-1]['content']
        return httpx.Response(200,json={'choices':[{'message':{'role':'assistant','content':'البريد center@example.test [C1]'},'finish_reason':'stop'}],'usage':{'total_tokens':10}})
    client=NeonAI(AIConfig('https://test.neon.tech','not-real','configured'),httpx.MockTransport(respond))
    result=client.answer('ما بريد المركز؟',{},[],search=lambda args:{'results':[{'centerEmail':'center@example.test','source_ref':'C1'}]})
    assert result==('البريد center@example.test [C1]',[],{'total_tokens':30})
    assert len(requests)==2


def test_model_read_tool_budget_is_bounded():
    calls=[]
    def respond(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200,json={'choices':[{'message':{'role':'assistant','content':None,'tool_calls':[
            {'id':'loop_'+str(len(calls)),'type':'function','function':{'name':'search_project','arguments':'{"kind":"contacts","query":"x"}'}}
        ]},'finish_reason':'tool_calls'}]})
    client=NeonAI(AIConfig('https://test.neon.tech','not-real','configured'),httpx.MockTransport(respond))
    with pytest.raises(WorkspaceError,match='بلغ البحث'):
        client.answer('بحث',{},[],search=lambda args:{'results':[]})
    assert len(calls)==4 and calls[-1]['tool_choice']=='none'
