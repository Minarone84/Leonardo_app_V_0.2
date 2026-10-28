"""REC-02 lossless inspection storage and exact accounting regressions."""
from copy import deepcopy
from dataclasses import replace
import json
import pytest
from leonardo.analysis import combination_explanations as ce
from leonardo.analysis.refinement_models import CombinationInspection, InspectionOptions
from leonardo.analysis.pattern_models import PatternStudy, PatternRefinement
from leonardo.analysis.pattern_refinement import pin_patterns, evaluate_patterns
from tests.analysis_test.test_family_scope_refinement import multi_case

@pytest.fixture(scope="module")
def compact_case(tmp_path_factory):
    parent, catalogue, axis, request, study, _ = multi_case(tmp_path_factory.mktemp("compact"))
    frozen = pin_patterns(parent, catalogue, study, (study.frame("patterns").pattern_id.iloc[0],))
    first = evaluate_patterns(frozen, PatternRefinement())
    second = evaluate_patterns(frozen, PatternRefinement(), parent=first)
    return frozen, study, first, second

def build(case, view="child", **kw):
    frozen, study, first, second = case
    current, parent = {"source": (study, None), "child": (first, None), "grandchild": (second, first)}[view]
    return ce.inspect_combination(frozen, study, current, parent,
                                 frozen.patterns[0].pattern_id, InspectionOptions(), **kw)

def test_construction_does_not_materialize_per_anchor_windows(compact_case, monkeypatch):
    from leonardo.analysis.refinement_models import PatternEvaluation
    calls = []
    for cls in (PatternStudy, PatternEvaluation):
        original = cls.event_window
        def watch(self, event_id, original=original):
            calls.append(event_id)
            return original(self, event_id)
        monkeypatch.setattr(cls, "event_window", watch)
    report = build(compact_case)
    assert calls == [], "construction must store detached inputs and references, not eager windows"
    payload = json.loads(report.payload)
    assert payload["window_store"]["schema"] == "gr06-inspection-window-store-v1"
    assert payload["window_store"]["sources"]

@pytest.mark.parametrize("view", ("source", "child", "grandchild"))
def test_every_public_record_window_matches_unchanged_authority(compact_case, view):
    report = build(compact_case, view)
    data = json.loads(report.payload)
    assert set(data) == {"header", "tables", "records", "links", "window_store"}
    frozen, study, first, second = compact_case
    sources = {"source": study, "current": study if view == "source" else first if view == "child" else second}
    if view != "source":
        sources["parent"] = study if view == "child" else first
    for side, rows in data["records"].items():
        for row_id, stored in rows.items():
            actual = report.record(side, row_id)
            assert actual["event_window"] == ce._canonical(sources[side].event_window(row_id))
            assert {k:v for k,v in actual.items() if k != "event_window"} == {k:v for k,v in stored.items() if k != "event_window"}
    assert report.retained_bytes == len(report.payload.encode("utf-8"))

def test_exact_boundary_and_genuine_too_small_allowance(compact_case):
    report = build(compact_case)
    assert build(compact_case, memory_limit_bytes=report.retained_bytes).payload == report.payload
    with pytest.raises(ValueError, match="report_budget_exceeded"):
        build(compact_case, memory_limit_bytes=report.retained_bytes-1)
    with pytest.raises(ValueError, match="report_budget_exceeded"):
        build(compact_case, memory_limit_bytes=100)

@pytest.mark.parametrize("fault", ("schema", "digest", "dangling", "descriptor_type"))
def test_compact_structural_corruption_is_rejected(compact_case, fault):
    report = build(compact_case)
    content = json.loads(report.payload)
    store = content["window_store"]
    row = next(iter(content["records"]["source"].values()))
    if fault == "schema": store["schema"] = "unknown"
    elif fault == "digest":
        key = next(iter(store["sources"]));store["sources"][key] += " "
    elif fault == "dangling":row["event_window"]["source_key"] = "0"*64
    else:row["event_window"]["anchor_ts_ms"] = True
    with pytest.raises((ValueError, TypeError)):
        CombinationInspection(json.dumps(content))

def test_legacy_format_and_report_identity_preserved():
    from leonardo.analysis.refinement_models import _granular_hash
    raw = {"header": {}, "tables": {}, "records": {}, "links": {}}
    report = CombinationInspection(json.dumps(raw))
    assert report.report_id == _granular_hash(("gr06-inspection-v1", report.payload))
    assert report.header == {}


def tiny_window_input(n=8, *, pre=True):
    from types import SimpleNamespace
    import pandas as pd
    import numpy as np
    from decimal import Decimal
    stamps = list(range(1000, 1000+n*100, 100))
    values = [None, float('nan'), 'nan', float('inf'), 'inf', True, Decimal('1.2300'), {'quote': ['é\\\"', -2]}]
    values[-1]['nonfinite']=[float('nan'),'nan',float('inf'),'inf',float('-inf'),'-inf']
    frame = pd.DataFrame({'ts_ms': stamps, 'raw_value': [values[i%8] for i in range(n)],
                          'label': ['P01']*n, 'status': ['ok']*n}, dtype=object)
    data = dict(timestamps=stamps, positions={t:i for i,t in enumerate(stamps)},
                coverage=[True]*(n-1)+[False], breaks=np.array([0]+[1]*(n-1)),
                columns={'Δ':dict(profile_id='profile',measurement='value',frame=frame)})
    return SimpleNamespace(_data=data, request=SimpleNamespace(before=2,after=2,
        pre_event=SimpleNamespace(offsets=(-3,-2,-1)) if pre else None))

def tiny_report(source, view='study', account=None, anchor=None):
    account = account or ce._InspectionAccounting(134217728,lambda:None)
    content=account.mapping(dict(header={},tables={},records={},links={},
        window_store=dict(schema='gr06-inspection-window-store-v1',sources={})))
    key=ce._inspection_window_source(source,content['window_store'],account)
    anchor=source._data['timestamps'][0] if anchor is None else anchor
    event_id='control:'+str(anchor)
    content['records']['source']={event_id:dict(anchor_ts_ms=anchor,
        event_window=dict(source_key=key,event_id=event_id,anchor_ts_ms=anchor,view_kind=view))}
    return account.finish(content),event_id

@pytest.mark.parametrize('anchor_index',(0,5,7))
@pytest.mark.parametrize('pre',(False,True))
@pytest.mark.parametrize('view',('study','evaluation'))
def test_nested_nonfinite_strings_gaps_outside_history_and_detachment(pre,view,anchor_index,monkeypatch):
    from leonardo.analysis import trend_start_patterns as windows
    from leonardo.analysis.refinement_models import _table
    source=tiny_window_input(pre=pre)
    report,key=tiny_report(source,view,anchor=source._data['timestamps'][anchor_index])
    original=windows.event_window(source._data,source.request,key)
    expected=ce._canonical(_table(original) if view=='evaluation' else original)
    calls=[];authority=windows.event_window
    def counted(*a,**kw):
        calls.append(a[2]);return authority(*a,**kw)
    monkeypatch.setattr(windows,'event_window',counted)
    first=report.record('source',key)
    assert first['event_window']==expected and calls==[key]
    snapshot=json.loads(next(iter(json.loads(report.payload)['window_store']['sources'].values())))
    cells=snapshot['columns'][0]['frame_rows']
    import math
    assert math.isnan(cells[1][1]) and cells[2][1]=='nan'
    assert math.isinf(cells[3][1]) and cells[4][1]=='inf'
    source._data['columns']['Δ']['frame'].iat[0,1]='changed'
    source._data['timestamps'][0]=-1;source._data['coverage'].clear()
    first['event_window']['rows'].clear();report.header.clear()
    assert report.record('source',key)['event_window']==expected

@pytest.mark.parametrize('change',('none','cell','request','columns','profile','measurement','coverage','breaks','positions'))
def test_snapshot_interning_requires_every_window_input(change):
    a=tiny_window_input();b=deepcopy(a)
    if change=='cell':b._data['columns']['Δ']['frame'].iat[1,1]='nan'
    elif change=='request':b.request.before+=1
    elif change=='columns':b._data['columns']['other']=b._data['columns'].pop('Δ')
    elif change=='profile':b._data['columns']['Δ']['profile_id']='different'
    elif change=='measurement':b._data['columns']['Δ']['measurement']='different'
    elif change=='coverage':b._data['coverage'][0]=False
    elif change=='breaks':b._data['breaks'][0]=1
    elif change=='positions':b._data['positions']=dict(reversed(list(b._data['positions'].items())))
    account=ce._InspectionAccounting(134217728,lambda:None)
    store=account.mapping(dict(schema='gr06-inspection-window-store-v1',sources={}))
    one=ce._inspection_window_source(a,store,account);two=ce._inspection_window_source(b,store,account)
    assert (one==two)==(change=='none')
    assert account.stats['snapshots']==(1 if change=='none' else 2)

def test_accounting_insert_replace_attach_unicode_and_independent_oracle():
    account=ce._InspectionAccounting(134217728,lambda:None)
    root=account.mapping({'é':'"\\\n','replace':{'old':[1,2]}})
    child=account.array([{'a':float('nan')},'🦉'])
    oracle=lambda value:len(ce._json(ce._canonical(value)).encode('utf-8'))
    assert account.total==oracle(root)+oracle(child)
    root['child']=child
    assert account.total==oracle(root)
    child.append({'growing':[1,2,3]})
    root['replace']['old'].append('later')
    assert account.total==oracle(root)
    root['replace']={'new':'less'}
    assert account.total==oracle(root) and account.roots=={id(root)}
    # An equal-sized replacement must not temporarily charge both values.
    account.limit=account.total
    root['replace']={'new':'less'}
    assert account.total==oracle(root)

def test_snapshot_rejects_unsupported_cells_and_real_compact_oversize():
    source=tiny_window_input()
    source._data['columns']['Δ']['frame'].iat[0,1]=object()
    with pytest.raises(TypeError,match='unsupported'):
        tiny_report(source)
    source=tiny_window_input()
    source._data['columns']['Δ']['frame'].iat[0,1]='x'*32768
    with pytest.raises(ValueError,match='report_budget_exceeded'):
        tiny_report(source,account=ce._InspectionAccounting(16384,lambda:None))

def test_new_storage_work_scales_by_grid_and_descriptors_without_prefix_rescans(record_property):
    results=[]
    for n in (32,64,128):
        source=tiny_window_input(n);account=ce._InspectionAccounting(134217728,lambda:None)
        content=account.mapping(dict(header={},tables={},records={},links={},
            window_store=dict(schema='gr06-inspection-window-store-v1',sources={})))
        key=ce._inspection_window_source(source,content['window_store'],account)
        records=account.mapping()
        for stamp in source._data['timestamps']:
            event='control:'+str(stamp)
            records[event]=dict(anchor_ts_ms=stamp,event_window=dict(source_key=key,event_id=event,
                                anchor_ts_ms=stamp,view_kind='study'))
        content['records']['source']=records
        report=account.finish(content)
        results.append((n,dict(account.stats),report.retained_bytes))
        assert account.stats['copied_cells']==n*4 and account.stats['prefix_rescans']==0
        assert account.stats['snapshots']==1
    for left,right in zip(results,results[1:]):
        assert right[1]['scalars']<=2*left[1]['scalars']
        assert right[2]<=2*left[2]+1024
    record_property('storage_scaling_receipt',json.dumps(results))

@pytest.mark.parametrize('fault',('snapshot_keys','row_width','request','descriptor_anchor','descriptor_id','digest_tamper'))
def test_compact_validation_is_self_contained_without_expansion(fault,monkeypatch):
    from hashlib import sha256
    from leonardo.analysis import trend_start_patterns
    report,row_id=tiny_report(tiny_window_input())
    content=json.loads(report.payload);row=content['records']['source'][row_id];store=content['window_store']['sources']
    oldkey=next(iter(store));snapshot=json.loads(store[oldkey])
    if fault=='snapshot_keys':snapshot['extra']=1
    elif fault=='row_width':snapshot['columns'][0]['frame_rows'][0].append(3)
    elif fault=='request':snapshot['request']['before']=True
    elif fault=='descriptor_anchor':row['event_window']['anchor_ts_ms']+=1
    elif fault=='descriptor_id':row['event_window']['event_id']='control:alien'
    else:
        object.__setattr__(report,'payload',report.payload+' ')
        with pytest.raises(ValueError,match='digest'):report.validate()
        return
    value=ce._json(snapshot);key=sha256(value.encode('utf-8')).hexdigest()
    store.clear();store[key]=value;row['event_window']['source_key']=key
    monkeypatch.setattr(trend_start_patterns,'event_window',lambda *a,**k:pytest.fail('eager validation expansion'))
    with pytest.raises(ValueError):CombinationInspection(ce._json(content)).validate()

@pytest.fixture(scope='module')
def representative_case(tmp_path_factory):
    """Canonical disposable 2400-bar sine -> artifacts -> UTC5/3 database."""
    from hashlib import sha256
    from types import SimpleNamespace
    import numpy as np
    from leonardo.ohlcv.store import OHLCVStore,Candle
    from leonardo.data_manager import ArtifactCollectionOutputV1
    from leonardo.analysis.service import AnalysisService
    from leonardo.analysis.models import AnalysisRequest,ColumnRequest
    from leonardo.analysis.pattern_models import PatternRequest,PreEventSpec
    from leonardo.analysis.refinement_models import GranularRefinement,GranularGroup,GranularPredicate
    from leonardo.analysis.pattern_refinement import evaluate_granular_patterns
    from leonardo.financial_tools import DirectionalBinningPolicy
    from tests.data_manager_test.test_update_workflow import _domain,MARKET
    from tests.data_manager_test.test_creation_workflow import _leaf,_materialize
    from tests.data_manager_test.test_artifact_materialization import _utc_recipe
    path=tmp_path_factory.mktemp('representative')
    domain,_,recipes,historical=_domain(path,initialize=False)
    i=np.arange(2400);close=100+8*np.sin(i/5)+12*np.sin(i/45)
    candles=[Candle(1700000040000+int(j)*60000,float(v),float(v+1),float(v-1),float(v),100.) for j,v in enumerate(close)]
    owned=OHLCVStore(historical);owned.write(MARKET,candles,source='REC02 deterministic sine',persistence_status='committed')
    csv,side=owned.csv_path(MARKET),owned.sidecar_path(MARKET)
    owned.publish_validation(MARKET,expected_csv_size=csv.stat().st_size,expected_csv_mtime_ns=csv.stat().st_mtime_ns,
        expected_csv_sha256=sha256(csv.read_bytes()).hexdigest(),expected_sidecar_size=side.stat().st_size,
        expected_sidecar_mtime_ns=side.stat().st_mtime_ns,expected_sidecar_sha256=sha256(side.read_bytes()).hexdigest(),
        status='ok',row_count=2400,first_timestamp_ms=candles[0].ts_ms,last_timestamp_ms=candles[-1].ts_ms,
        warnings=(),issue_codes=(),error_count=0,warning_count=0,validator='REC02 canonical specimen')
    peaks=_leaf('peaks_troughs',{});recipes.save_recipe(peaks)
    utc=_utc_recipe(peaks,trend_window=5,range_window=3,roles=('trend_peak','trend_trough','range_peak','range_trough'))
    materialized=_materialize(domain,recipes,utc)
    sma=_leaf('sma',{'period':3});sma_result=_materialize(domain,recipes,sma)
    seed=domain.create_database_seed(MARKET,'REC02 synthetic')
    base=domain.execute_seed_only_database_creation(domain.plan_seed_only_database_creation(seed.seed_id,'REC02'))
    additions=(ArtifactCollectionOutputV1(materialized.root_logical_artifact_ids[0],'uptrend','utc_uptrend'),
               ArtifactCollectionOutputV1(sma_result.root_logical_artifact_ids[0],sma.output_names[0],'sma3'))
    plan=domain.plan_database_content_edit(base.database_id,artifact_additions=additions);assert not plan.blocked
    manifest=domain.execute_database_content_edit(plan)
    service=AnalysisService(domain._creation.store)
    entry=next(e for e in service.catalog().entries if e.reference.database_id==manifest.database_id)
    binning=service.run(AnalysisRequest(entry.reference,tuple(ColumnRequest(n,'directional_intensity',
        DirectionalBinningPolicy(10,10,2)) for n in ('close','sma3'))))
    catalogue=service.load_pattern_catalogue(binning);instance=catalogue.to_dict()['instances'][0]['instance_id']
    request=PatternRequest(entry.reference,catalogue.run_key,instance,'T','UP',('close','sma3'),
        entry.first_timestamp_ms,entry.last_timestamp_ms,family='UP/TPTP/0,2,1,3',before=20,after=20,
        comparison='non_start',min_target=1,min_comparison=1,min_matches=1,
        pre_event=PreEventSpec(history=3,lead=1,max_terms=2,tolerance=0,chronological=True))
    study=service.run_patterns(binning,request)
    ids=[pid for pid,row in study._data['patterns'].items() if
         {(t.column,t.offset,tuple(t.allowed)) for t in row['terms']}=={('close',-2,('P01',)),('sma3',-3,('P01',))}]
    assert len(ids)==1
    frozen=pin_patterns(binning,catalogue,study,tuple(ids))
    definition=GranularRefinement(common=(GranularGroup('ALL',(GranularPredicate('column','raw_value','native',
        column='close',profile_id=study._data['columns']['close']['profile_id'],offset=-3,maximum=100),)),))
    current=evaluate_granular_patterns(frozen,definition)
    return SimpleNamespace(frozen=frozen,study=study,current=current,pattern_id=ids[0])

def test_representative_canonical_case_completes_without_eager_windows(representative_case,monkeypatch,record_property):
    from time import perf_counter
    from leonardo.analysis.refinement_models import PatternEvaluation
    p=representative_case
    fields=('matched','assessable','comparison_matched','comparison_assessable')
    parent=p.study.frame('patterns').set_index('pattern_id').loc[p.pattern_id]
    child=p.current.frame('patterns').iloc[0]
    assert tuple(int(parent[k]) for k in fields)==(6,7,0,0)
    assert tuple(int(child[k]) for k in fields)==(0,0,0,0)
    calls=[];originals={cls:cls.event_window for cls in (PatternStudy,PatternEvaluation)}
    for cls,authority in originals.items():
        def watch(self,row_id,authority=authority):calls.append(row_id);return authority(self,row_id)
        monkeypatch.setattr(cls,'event_window',watch)
    started=perf_counter()
    report=ce.inspect_combination(p.frozen,p.study,p.current,None,p.pattern_id,InspectionOptions())
    elapsed=perf_counter()-started
    assert calls==[] and report.retained_bytes<=134217728
    content=json.loads(report.payload)
    assert len(content['window_store']['sources'])==1
    for side,result in (('source',p.study),('current',p.current),('parent',p.study)):
        assert len(content['records'][side])>1800
        # All stored identities and each ledger page remain present; detailed
        # every-window streaming parity is also run on the authenticated fixture.
        expected=sorted(content['records'][side],key=lambda key:(content['records'][side][key]['anchor_ts_ms'],
                         content['records'][side][key]['ordinary'],key))
        seen=[]
        for offset in range(0,len(expected),50):
            page=report.ledger({'side':side},offset=offset)
            seen+=page.row_id.tolist()
            assert page.attrs['support_set_total']==len(expected)
        assert seen==expected
        for key in (expected[0],expected[len(expected)//2],expected[-1]):
            assert report.record(side,key)['event_window']==ce._canonical(originals[type(result)](result,key))
    for link in content['links'].values():assert set(link['row_ids'])<=set(content['records'][link['side']])
    record_property('representative_receipt',json.dumps(dict(rows=2400,elapsed_seconds=elapsed,
        retained_bytes=report.retained_bytes,side_rows={k:len(v) for k,v in content['records'].items()},eager_windows=0)))

def test_signed_zero_is_not_merged_and_compact_domain_cannot_be_legacy():
    from leonardo.analysis.refinement_models import _granular_hash
    a=tiny_window_input();b=deepcopy(a)
    a._data['columns']['Δ']['frame'].iat[0,1]=-0.0
    b._data['columns']['Δ']['frame'].iat[0,1]=0.0
    account=ce._InspectionAccounting(134217728,lambda:None)
    store=account.mapping(dict(schema='gr06-inspection-window-store-v1',sources={}))
    assert ce._inspection_window_source(a,store,account)!=ce._inspection_window_source(b,store,account)
    report,_=tiny_report(a)
    assert report.report_id==_granular_hash(('gr06-inspection-v2',report.payload))
    object.__setattr__(report,'report_id',_granular_hash(('gr06-inspection-v1',report.payload)))
    with pytest.raises(ValueError,match='digest'):report.validate()

def test_inspection_has_no_growing_prefix_budget_passes(compact_case,monkeypatch):
    passes=[];original=ce._inspection_encode
    def encode(value,checkpoint):
        if isinstance(value,dict) and 'window_store' in value:
            passes.append({k:len(v) for k,v in value['records'].items()})
        return original(value,checkpoint)
    monkeypatch.setattr(ce,'_inspection_encode',encode)
    import sys
    from leonardo.analysis.pattern_refinement import resolve_inspection_measurements
    old_budget=ce._budget;protected_calls=[]
    def budget(value,limit):
        caller=sys._getframe(1).f_code
        assert caller is resolve_inspection_measurements.__code__, 'growing inspection prefix scan'
        protected_calls.append(caller.co_name)
        return old_budget(value,limit)
    monkeypatch.setattr(ce,'_budget',budget)
    report=build(compact_case)
    final={k:len(v) for k,v in json.loads(report.payload)['records'].items()}
    assert passes==[final,final]  # One reconciliation plus one model validation.
    assert protected_calls  # The separate measurement authority remains active.
    assert CombinationInspection.__slots__==('payload','report_id')

def test_nullable_profile_metadata_remains_lossless():
    from leonardo.analysis.trend_start_patterns import event_window
    source=tiny_window_input()
    source._data['columns']['Δ']['profile_id']=None
    report,key=tiny_report(source)
    assert report.record('source',key)['event_window']==ce._canonical(event_window(source._data,source.request,key))

def test_matching_digest_with_unequal_snapshot_bytes_is_an_error(monkeypatch):
    import hashlib
    from types import SimpleNamespace
    a=tiny_window_input();b=deepcopy(a)
    b._data['columns']['Δ']['frame'].iat[0,1]='different'
    monkeypatch.setattr(hashlib,'sha256',lambda value:SimpleNamespace(hexdigest=lambda:'0'*64))
    account=ce._InspectionAccounting(134217728,lambda:None)
    store=account.mapping(dict(schema='gr06-inspection-window-store-v1',sources={}))
    ce._inspection_window_source(a,store,account)
    with pytest.raises(ValueError,match='digest collision'):
        ce._inspection_window_source(b,store,account)

def test_fresh_digest_does_not_rebind_view_and_legacy_rejection_stays_deferred(compact_case):
    content=json.loads(build(compact_case).payload)
    key=next(iter(content['records']['current']))
    content['records']['current'][key]['event_window']['view_kind']='study'
    changed=CombinationInspection(ce._json(content))
    with pytest.raises(ValueError,match='view binding'):changed.validate()
    content=json.loads(build(compact_case).payload)
    content['header']['checkpoint_id']='alien'
    # Header/row membership is still constructible for publication rejection.
    content['records']['current'][key]['row_id']='alien'
    assert isinstance(CombinationInspection(ce._json(content)),CombinationInspection)

@pytest.mark.parametrize('field',('profile_id','measurement','request'))
def test_rehashed_snapshot_must_keep_captured_provenance(compact_case,field):
    from hashlib import sha256
    content=json.loads(build(compact_case).payload)
    sources=content['window_store']['sources'];old=next(iter(sources));snapshot=json.loads(sources[old])
    if field=='request':snapshot['request']['after']+=1
    else:snapshot['columns'][0][field]='alien'
    encoded=ce._json(snapshot);key=sha256(encoded.encode('utf-8')).hexdigest()
    sources[key]=encoded;del sources[old]
    for rows in content['records'].values():
        for row in rows.values():
            if row['event_window']['source_key']==old:row['event_window']['source_key']=key
    report=CombinationInspection(ce._json(content))
    with pytest.raises(ValueError,match='binding'):report.validate()

def test_sequence_copy_yields_at_bounded_scalar_intervals():
    visited=[];checkpoints=[]
    def values():
        for i in range(1025):
            visited.append(i);yield i
    actual=ce._inspection_sequence(values(),lambda:checkpoints.append(len(visited)))
    assert actual==list(range(1025)) and checkpoints==[0,256,512,768,1024,1025]

def test_nested_key_copy_is_bounded_and_unknown_objects_are_rejected():
    calls=[];value={str(i):i for i in range(300)}
    assert ce._inspection_raw(value,lambda:calls.append(True))==value and len(calls)==2
    source=tiny_window_input()
    source._data['columns']['Δ']['frame'].iat[0,1]={object():1}
    with pytest.raises(TypeError,match='unsupported inspection snapshot key'):tiny_report(source)
