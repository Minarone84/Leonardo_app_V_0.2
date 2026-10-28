"""Revision-backed horizon sources, frozen evaluation and independent facts."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
from hashlib import sha256
from io import StringIO
import csv
import json
from types import SimpleNamespace

import pandas as pd
import pytest
from leonardo.analysis.service import AnalysisService
from leonardo.analysis.pattern_models import PreEventSpec, PatternRefinement
from leonardo.analysis.refinement_models import GranularPredicate as P, GranularGroup as G, GranularRefinement as D
from leonardo.analysis.pattern_refinement import (pin_patterns, evaluate_granular_patterns, evaluate_patterns,
    resolve_granular_population, search_granular_patterns, _gr04_capture_price_snapshot,
    _gr04_validate_price_snapshot, _gr04_market, _gr04_spacing, _gr04_window, _gr04_result_identity)
from leonardo.analysis.trend_start_patterns import _json, _hash
from leonardo.data_manager import ArtifactCollectionOutputV1
from leonardo.data_manager.creation_models import database_revision_from_dict, deterministic_hash, LoadedDatabaseRevision
from leonardo.recipes import PortableRecipeStore
from tests.analysis_test.test_analysis_service import make_database, request, reference
from tests.analysis_test.test_trend_start_catalogue import study_request
from tests.analysis_test.test_granular_evidence import make_case, quantity, spec
from tests.data_manager_test.test_utc_classification_lifecycle import utc_database
from tests.data_manager_test.test_creation_workflow import _leaf, _materialize


def horizon(field='terminal_directional', n=6, unit='pct', minimum=0, **kw):
    return P('horizon',field,unit,horizon_bars=n,minimum=minimum,**kw)


def priced_case(tmp_path, *, direction='UP', comparison='other_outcomes', clock=1900000000000, close_only=False, spoof=None, multiple=False, tolerance=0):
    from tests.data_manager_test.test_update_workflow import _domain,MARKET
    from tests.data_manager_test.test_artifact_materialization import _utc_recipe
    from leonardo.ohlcv.store import OHLCVStore,Candle
    import numpy as np
    domain,_,recipes,historical=_domain(tmp_path,initialize=False)
    pivots=[110,100,115,105,125,115,120,110,118,100,110,95,105,90,100,92,
            110,100,120,108,130,115,123,105,118,98,108,90,102,85,96,88,
            110,98,124,106,135,115,122,103,116,97,108,90,104,85,99,87]
    close=np.interp(np.arange((len(pivots)-1)*8+1),np.arange(len(pivots))*8,pivots)
    candles=[Candle(1700000000000+i*60000,float(v),float(v+.5),float(v-.5),float(v),1000.) for i,v in enumerate(close)]
    owned=OHLCVStore(historical);owned.write(MARKET,candles,source='gr04-disposable',persistence_status='committed')
    csvpath,sidepath=owned.csv_path(MARKET),owned.sidecar_path(MARKET)
    owned.publish_validation(MARKET,expected_csv_size=csvpath.stat().st_size,expected_csv_mtime_ns=csvpath.stat().st_mtime_ns,
        expected_csv_sha256=sha256(csvpath.read_bytes()).hexdigest(),expected_sidecar_size=sidepath.stat().st_size,
        expected_sidecar_mtime_ns=sidepath.stat().st_mtime_ns,expected_sidecar_sha256=sha256(sidepath.read_bytes()).hexdigest(),
        status='ok',row_count=len(candles),first_timestamp_ms=candles[0].ts_ms,last_timestamp_ms=candles[-1].ts_ms,
        warnings=(),issue_codes=(),error_count=0,warning_count=0,validator='gr04-disposable')
    pt=_leaf('peaks_troughs',{});recipes.save_recipe(pt)
    utc=_utc_recipe(pt,trend_window=5,roles=('trend_peak','trend_trough','range_peak','range_trough'))
    materialization=_materialize(domain,recipes,utc)
    collection=domain.create_artifact_collection(materialization,'Fixed-horizon UTC fixture')
    if close_only or spoof:
        from tests.data_manager_test.seed_fixtures import create_legacy_seed_v2
        seed=create_legacy_seed_v2(domain,MARKET,'Historical partial-price fixture',start_ms=candles[0].ts_ms,
            end_ms=candles[-1].ts_ms,columns=('open',) if spoof else ('close',))
    else:
        seed=domain.create_database_seed(MARKET,'Fixed-horizon database')
    manifest=domain.build_database_revision(seed.seed_id,collection.collection_id)
    recipe=_leaf('sma',{'period':3})
    materialized=_materialize(domain,PortableRecipeStore(tmp_path/'recipes'),recipe)
    selection=ArtifactCollectionOutputV1(materialized.root_logical_artifact_ids[0],recipe.output_names[0],spoof or 'signal')
    plan=domain.plan_database_content_edit(manifest.database_id,artifact_additions=(selection,))
    assert not plan.blocked
    manifest=domain.execute_database_content_edit(plan)
    if multiple:
        second=_leaf('sma',{'period':30});materialized=_materialize(domain,recipes,second)
        addition=ArtifactCollectionOutputV1(materialized.root_logical_artifact_ids[0],second.output_names[0],'slow_signal')
        plan=domain.plan_database_content_edit(manifest.database_id,artifact_additions=(addition,));assert not plan.blocked
        manifest=domain.execute_database_content_edit(plan)
    store=domain._creation.store;service=AnalysisService(store,clock_ms=lambda:clock)
    parent=service.run(request(manifest,*((spoof or 'signal','slow_signal') if multiple else (spoof or 'signal',)),minimum=2))
    cat=service.load_pattern_catalogue(parent);instance=cat.to_dict()['instances'][0]
    kind='T' if direction=='UP' else 'P';families=cat.families(instance['instance_id'],kind)
    assert families
    # Discovery starts with ordinary controls; the outcome comparison can then use legacy completed movement.
    from tests.analysis_test.test_trend_start_enrichment import movement
    req=replace(study_request(parent,cat,kind=kind,family=families[0]['family'],before=6,after=2,
        min_target=1,min_comparison=1,min_matches=1,pre_event=PreEventSpec(max_terms=2,tolerance=tolerance)),
        instance_id=instance['instance_id'],comparison=comparison,
        refinement=movement('completed') if comparison=='other_outcomes' else PatternRefinement())
    study=service.run_patterns(parent,req)
    assert not study.frame('patterns').empty
    ids=study.frame('patterns').pattern_id.tolist()
    if multiple:
        ids=[pid for pid in ids if len({t.column for t in study._data['patterns'][pid]['terms']})==2]
        assert ids
    frozen=service.pin_pattern_set(parent,cat,study,ids[:4])
    return SimpleNamespace(domain=domain,store=store,manifest=manifest,service=service,parent=parent,catalogue=cat,
        request=req,study=study,frozen=frozen,loaded=store.load_database_revision(manifest.database_id,manifest.revision_id))


@pytest.fixture(scope='module')
def prices(tmp_path_factory): return priced_case(tmp_path_factory.mktemp('fixed_horizon'))


@pytest.mark.parametrize('direction',('UP','DOWN'))
@pytest.mark.parametrize('comparison',('other_families','other_outcomes','non_start'))
def test_real_revision_unbinned_prices_and_independent_ledger(tmp_path,direction,comparison):
    case=priced_case(tmp_path,direction=direction,comparison=comparison)
    assert [c.request.source for c in case.parent.columns]==['signal']
    data=json.loads(case.frozen._root['_gr04_prices']);csvrows=list(csv.reader(StringIO(case.loaded.values_csv.decode())))
    assert data['manifest']==case.manifest.to_dict()
    assert data['reference']==dict(database_id=case.manifest.database_id,revision_id=case.manifest.revision_id,values_sha256=case.manifest.values_sha256)
    assert all(data['roles'][r]['raw_values']==[row[csvrows[0].index(r)] for row in csvrows[1:]] for r in ('close','high','low'))
    assert case.study._data['_gr04_prices'] is case.frozen._root['_gr04_prices']
    predicates=(horizon(n=6,minimum=-1000),horizon('favorable_excursion',12,minimum=0),horizon('adverse_excursion',6,minimum=0))
    definition=spec(*predicates);result=evaluate_granular_patterns(case.frozen,definition);report=result.population_report()
    checked=0
    for record in report['records']:
        if record['ordinary']:
            assert not record['scalar_ledger'] and 'horizon_windows' not in record
            continue
        for value in record['scalar_ledger']:
            if not value['known']:continue
            p=next(p for p in predicates if p.measurement_key==value['measurement_key']);s=record['anchor'];n=p.horizon_bars
            close=[Decimal(v) for v in data['roles']['close']['raw_values'][s:s+n+1]];p0=close[0]
            sign=1 if direction=='UP' else -1
            if p.field=='terminal_directional':points=sign*(close[-1]-p0)
            elif p.field=='favorable_excursion':
                side='high' if sign==1 else 'low';points=max(Decimal(0),max(sign*(Decimal(v)-p0) for v in data['roles'][side]['raw_values'][s+1:s+n+1]))
            else:
                side='low' if sign==1 else 'high';points=max(Decimal(0),max(-sign*(Decimal(v)-p0) for v in data['roles'][side]['raw_values'][s+1:s+n+1]))
            from decimal import Context,ROUND_HALF_EVEN,MIN_EMIN,MAX_EMAX
            policy=Context(prec=50,rounding=ROUND_HALF_EVEN,Emin=MIN_EMIN,Emax=MAX_EMAX,traps=[])
            expected=policy.divide(policy.multiply(points,Decimal(100)),p0)
            assert Decimal(value['value'])==expected
            window=next(w for w in record['horizon_windows'] if w['window_id']==value['source']['window_id'])
            assert window['start_row']==s and window['end_row']==s+n and window['required_end_ms']==1900000000000
            assert record['evidence_end_ms']>=window['required_end_ms'];checked+=1
    assert checked>0
    assert [p.pattern_id for p in case.frozen.patterns]==result.frame('patterns').pattern_id.tolist()


def test_model_identity_serialization_limits_and_inactive_rows():
    old=quantity();assert 'horizon_bars' not in old.to_dict()
    assert old.measurement_key==_hash(('gr03-measure-v1',{k:getattr(old,k) for k in ('domain','field','unit','basis','cohort','statistic','column','profile_id','offset')}))
    a=horizon();b=horizon(n=12);assert a.measurement_key!=b.measurement_key and a.predicate_key!=b.predicate_key
    definition=spec(old,a,b);assert definition.to_dict()['kind']=='gr04-filter-spec-v1' and D.from_dict(definition.to_dict())==definition
    assert D.from_dict(spec(old).to_dict())==spec(old)
    for kind in ('gr03-filter-spec-v1','other'):
        payload=definition.to_dict();payload['kind']=kind
        with pytest.raises(ValueError):D.from_dict(payload)
    payload=spec(old).to_dict();payload['kind']='gr04-filter-spec-v1'
    with pytest.raises(ValueError):D.from_dict(payload)
    assert spec(*(horizon(n=n) for n in range(1,9))).active_count==8
    with pytest.raises(ValueError,match='eight distinct'):spec(*(horizon(n=n) for n in range(1,10)))
    assert spec(*(horizon(n=n,enabled=n<9) for n in range(1,10))).active_count==8
    assert spec(*(horizon(n=n,minimum=None) for n in range(1,10))).active_count==0


@pytest.mark.parametrize('kwargs',({'horizon_bars':True},{'horizon_bars':0},{'horizon_bars':1001},{'basis':'completed'},
    {'column':'close'},{'allowed':('P01',)},{'unit':'native'},{'field':'signed_move'},{'minimum':True}))
def test_horizon_invalid_selectors(kwargs):
    values=dict(domain='horizon',field='terminal_directional',unit='pct',horizon_bars=6,minimum=0);values.update(kwargs)
    with pytest.raises((TypeError,ValueError)):P(**values)
    with pytest.raises(ValueError):replace(quantity(),horizon_bars=6)


def test_frozen_no_read_no_fit_no_mine_and_search_repin(prices,monkeypatch):
    case=prices;definition=spec(horizon(minimum=-1000));initial=evaluate_granular_patterns(case.frozen,definition)
    def prohibited(*a,**kw):pytest.fail('frozen operation attempted source IO, clock, fitting or Evaluate mining')
    monkeypatch.setattr(case.store,'load_database_revision',prohibited);monkeypatch.setattr(case.service,'_clock_ms',prohibited)
    import leonardo.analysis.service as service_module
    for name in ('fit_directional_binning','fit_dynamic_binning'):monkeypatch.setattr(service_module,name,prohibited)
    import leonardo.analysis.pre_event_patterns as patterns
    miner=patterns.mine;monkeypatch.setattr(patterns,'mine',prohibited)
    result=case.service.evaluate_pattern_set(case.frozen,definition)
    assert result.population_report()==initial.population_report()
    monkeypatch.setattr(patterns,'mine',miner)
    candidate=case.service.search_granular_patterns(case.frozen,case.parent,case.catalogue,definition,parent_id=result.evaluation_id)
    assert candidate._data['_gr04_prices'] is case.frozen._root['_gr04_prices']
    assert not candidate.frame('patterns').empty
    new=pin_patterns(case.parent,case.catalogue,candidate,candidate.frame('patterns').pattern_id.tolist()[:2])
    assert new._root['_gr04_prices'] is case.frozen._root['_gr04_prices']
    assert evaluate_granular_patterns(new,definition).population_report()['horizon_source']==result.population_report()['horizon_source']


@pytest.mark.parametrize('fault',('payload','binding','missing_binding','missing_payload','axis','clock','role','length','reference','market'))
def test_discovery_source_binding_rejects_tampering(prices,fault):
    case=prices;data=dict(case.study._data);payload=json.loads(data['_gr04_prices'])
    if fault=='payload':data['_gr04_prices']=b'{}'
    elif fault=='binding':data['_gr04_price_binding']='0'*64
    elif fault.startswith('missing_'):data.pop('_gr04_price_binding' if fault=='missing_binding' else '_gr04_prices')
    else:
        if fault=='axis':payload['timestamps'][1]=payload['timestamps'][0]
        elif fault=='clock':payload['acquired_at_ms']=False
        elif fault=='role':payload['roles']['close']['column']='signal'
        elif fault=='length':payload['roles']['close']['raw_values'].pop()
        elif fault=='reference':payload['reference']['values_sha256']='0'*64
        elif fault=='market':payload['market_id']['timeframe']='5m'
        data['_gr04_prices']=_json(payload).encode();data['_gr04_price_binding']=sha256(data['_gr04_prices']).hexdigest()
    with pytest.raises(ValueError,match='price_source_binding_mismatch'):
        pin_patterns(case.parent,case.catalogue,replace(case.study,_data=data),[case.frozen.patterns[0].pattern_id])
    duplicate=replace(case.study,_data=dict(case.study._data));assert pin_patterns(case.parent,case.catalogue,duplicate,[case.frozen.patterns[0].pattern_id])


def test_legacy_unstamped_and_inactive_horizon_do_not_decode(tmp_path,monkeypatch):
    frozen,*_=make_case(tmp_path)
    assert evaluate_patterns(frozen,PatternRefinement()).frame('patterns').shape[0]>0
    with pytest.raises(ValueError,match='price_source_missing'):evaluate_granular_patterns(frozen,spec(horizon()))
    import leonardo.analysis.pattern_refinement as module
    def prohibited(*a,**kw):pytest.fail('inactive horizon decoded price source')
    monkeypatch.setattr(module,'_gr04_source',prohibited)
    inactive=spec(horizon(enabled=False));result=evaluate_granular_patterns(frozen,inactive)
    assert 'horizon_source' not in json.loads(result.context)
    assert all('horizon_windows' not in r for r in result.population_report()['records'])


def captured_rows(tmp_path, *, columns=None):
    store,manifest,_=make_database(tmp_path,columns or {'signal':list(range(20))})
    loaded=store.load_database_revision(manifest.database_id,manifest.revision_id)
    rows=list(csv.reader(StringIO(loaded.values_csv.decode())))
    payload,binding=_gr04_capture_price_snapshot(loaded,rows,1900000000000)
    return loaded,payload,binding


@pytest.mark.parametrize('role',('close','high','low'))
def test_calculated_output_spoof_is_unavailable(tmp_path,role):
    loaded,payload,binding=captured_rows(tmp_path,columns={role:list(range(20))})
    model=_gr04_validate_price_snapshot(payload,binding,reference(loaded.manifest),_gr04_market(loaded.manifest.market_id),json.loads(payload)['timestamps'])
    assert model['roles'][role]['reason']=='calculated_output_not_canonical_price'


def test_close_only_capability(tmp_path):
    loaded,payload,binding=captured_rows(tmp_path)
    model=json.loads(payload)
    assert model['roles']['close']['status']=='available'
    assert all(model['roles'][r]['reason']=='canonical_price_column_missing' for r in ('high','low'))


@pytest.mark.parametrize('n,reason',[(6,''),(12,''),(1000,'horizon_tail_incomplete')])
def test_horizon_cache_and_tail(prices,monkeypatch,n,reason):
    import leonardo.financial_tools.event_window_measurements as module
    original=module.measure_event_window;calls=[]
    def count(*a,**kw):calls.append(kw['horizon_bars']);return original(*a,**kw)
    monkeypatch.setattr(module,'measure_event_window',count)
    definition=spec(horizon(n=n,minimum=-1000),horizon('terminal_signed',n,minimum=-1000),horizon('terminal_signed',n,unit='points',minimum=-1000))
    report=resolve_granular_population(prices.frozen,definition)
    windows=[w for r in report['records'] for w in r.get('horizon_windows',())]
    assert windows and len(calls)==sum(w['reason']=='' for w in windows)
    if reason:assert all(w['reason']==reason for w in windows)
    assert all(len(r['horizon_windows'])==1 for r in report['records'] if 'horizon_windows' in r)


def test_unavailable_any_is_not_complement_and_common_nonstart_rejected(prices,tmp_path):
    definition=spec(horizon(n=1000),quantity(basis='formation',minimum=-1000),operator='ANY')
    report=resolve_granular_population(prices.frozen,definition)
    measured=[r for r in report['records'] if r['scalar_ledger']]
    assert measured and all(r['cohort']=='excluded' and r['reason']=='unavailable_requested_evidence' for r in measured)
    ordinary=priced_case(tmp_path,comparison='non_start')
    with pytest.raises(ValueError,match='column-only'):resolve_granular_population(ordinary.frozen,D(common=(G(conditions=(horizon(),)),)))


@pytest.mark.parametrize('dates,timeframe,expected',[(('2024-01-01','2024-02-01','2024-03-01'),'1M',[0,0,0]),
    (('2024-01-31','2024-02-29','2024-03-29'),'1M',[0,0,1]),
    (('2024-01-31','2024-03-31','2024-05-31'),'2M',[0,0,0]),
    (('2024-01-31','2024-02-29','2024-03-31'),'1M',[0,0,0])])
def test_existing_calendar_authority(dates,timeframe,expected):
    axis=[int(pd.Timestamp(d,tz='UTC').timestamp()*1000) for d in dates]
    assert _gr04_spacing(axis,timeframe,lambda:None)==expected


def test_unrepresentable_calendar_step_is_unavailable():
    assert _gr04_spacing([2**63-2,2**63-1],'1M',lambda:None)==[0,1]


def test_spacing_gap_and_anchor_are_not_zero(prices):
    model=json.loads(prices.frozen._root['_gr04_prices']);axis=model['timestamps'];axis[8]+=1
    spacing=_gr04_spacing(axis,'1m',lambda:None)
    for anchor,reason in ((7,'horizon_timestamp_gap'),(None,'horizon_anchor_unavailable')):
        window,values=_gr04_window(model,'fixture','row',anchor,'UP',6,('close',),spacing,lambda:None)
        assert window['reason']==reason and values is None


def test_source_bound_identity_and_strict_threshold(prices):
    definition=spec(horizon(minimum=-1000));result=evaluate_granular_patterns(prices.frozen,definition)
    known=next(v for r in result.population_report()['records'] for v in r['scalar_ledger'] if v['known'])
    bound=Decimal(known['value']);inclusive=resolve_granular_population(prices.frozen,spec(horizon(minimum=bound)))
    exclusive=resolve_granular_population(prices.frozen,spec(horizon(minimum=bound,lower_inclusive=False)))
    assert inclusive!=exclusive
    old=_gr04_result_identity('evaluation',prices.frozen,D(),parent_id='p')
    assert old==_hash(('gr03-evaluation-v1',prices.frozen.set_id,'p',D().identity))
    assert result.evaluation_id==_gr04_result_identity('evaluation',prices.frozen,definition,parent_id=prices.frozen.source_discovery_id)


def publish_variant(case, frame):
    """Publish only a disposable successor through the owning store/model."""
    payload=case.manifest.to_dict(include_revision_id=False)
    values=frame.to_csv(index=False,lineterminator='\n').encode()
    payload.update(previous_revision_id=case.manifest.revision_id,values_sha256=sha256(values).hexdigest(),
        row_count=len(frame),first_timestamp_ms=int(frame.ts_ms.iloc[0]),last_timestamp_ms=int(frame.ts_ms.iloc[-1]))
    payload['revision_id']=deterministic_hash(payload);manifest=database_revision_from_dict(payload)
    case.store.publish_database_revision(case.store.load_database_definition(case.manifest.database_id),manifest,values,
        expected_head_revision_id=case.manifest.revision_id,utc_classification=case.loaded.utc_classification)
    return manifest


def test_store_successor_does_not_change_frozen_prices(tmp_path,monkeypatch):
    case=priced_case(tmp_path);definition=spec(horizon(minimum=-1000));before=evaluate_granular_patterns(case.frozen,definition)
    frame=pd.read_csv(StringIO(case.loaded.values_csv.decode()));frame['close']+=1
    successor=publish_variant(case,frame)
    assert successor.revision_id!=case.manifest.revision_id
    monkeypatch.setattr(case.store,'load_database_revision',lambda *a,**kw:pytest.fail('reader after pin'))
    after=evaluate_granular_patterns(case.frozen,definition)
    assert after.population_report()==before.population_report() and after.evaluation_id==before.evaluation_id


def test_actual_read_clock_and_snapshot_identity(prices):
    case=prices;service=AnalysisService(case.store,clock_ms=lambda:1900000000001)
    newer=service.run_patterns(case.parent,case.request)
    other=pin_patterns(case.parent,case.catalogue,newer,[p.pattern_id for p in case.frozen.patterns])
    assert other.set_id==case.frozen.set_id
    assert other._root['_gr04_price_binding']!=case.frozen._root['_gr04_price_binding']
    assert _gr04_result_identity('population',other,D())==_gr04_result_identity('population',case.frozen,D())
    definition=spec(horizon());assert _gr04_result_identity('population',other,definition)!=_gr04_result_identity('population',case.frozen,definition)
    model=json.loads(other._root['_gr04_prices'])
    assert model['acquired_at_ms']==1900000000001 and case.parent.snapshot_read_ms==1900000000000


def test_complete_horizon_open_episode_and_after_independence(prices):
    case=prices;instance=case.catalogue.instance(case.request.instance_id)
    opens=[e for e in instance['events'] if e['event_kind']=='T' and e['eligible']
           and any(w['episode']['status']=='open' for w in e['witnesses'])]
    # Inspect actual saved episodes; no fabricated completion/confirmation facts.
    if not opens:
        opens=[e for e in instance['events'] if e['eligible'] and any(w['episode']['status']=='open' for w in e['witnesses'])]
    assert opens
    event=opens[-1];direction=event['direction'] if 'direction' in event else ('UP' if event['event_kind']=='T' else 'DOWN')
    req=replace(case.request,event_kind=event['event_kind'],trend_direction=direction,family=event['family'],comparison='other_families',refinement=PatternRefinement())
    studies=[case.service.run_patterns(case.parent,replace(req,after=a)) for a in (0,20)]
    roots=[pin_patterns(case.parent,case.catalogue,s,s.frame('patterns').pattern_id.tolist()[:3]) for s in studies]
    reports=[resolve_granular_population(f,spec(horizon(n=1,minimum=-1000))) for f in roots]
    records=[next(r for r in report['records'] if r['row_id']==event['event_id']) for report in reports]
    assert all(r['scalar_ledger'][0]['known'] for r in records)
    assert records[0]['horizon_windows']==records[1]['horizon_windows']
    completed=resolve_granular_population(roots[0],spec(horizon(n=1,minimum=-1000),quantity(basis='completed')))
    record=next(r for r in completed['records'] if r['row_id']==event['event_id'])
    assert record['cohort']=='excluded' and record['reason']=='unavailable_requested_evidence'


def test_global_missing_role_and_still_supported_terminal(tmp_path):
    case=priced_case(tmp_path,close_only=True)
    assert resolve_granular_population(case.frozen,spec(horizon(minimum=-1000)))['summary']['target_total']>0
    with pytest.raises(ValueError,match='canonical_price_column_missing'):
        resolve_granular_population(case.frozen,spec(horizon('favorable_excursion')))
    assert evaluate_patterns(case.frozen,case.request.refinement)


def test_mandatory_snapshot_chronology_excludes_early_discovery(prices):
    case=prices;axis=json.loads(case.frozen._root['_gr04_prices'])['timestamps']
    req=replace(case.request,pre_event=replace(case.request.pre_event,chronological=True,split_ms=axis[-1]))
    discovery=case.service.run_patterns(case.parent,req)
    root=pin_patterns(case.parent,case.catalogue,discovery,discovery.frame('patterns').pattern_id.tolist()[:3])
    report=resolve_granular_population(root,spec(horizon(minimum=-1000)))
    samples=report['samples'];assert samples and all(s['partition']=='excluded' for s in samples)
    assert all(s['evidence_end_ms']>=1900000000000 for s in samples)
    # The current request forbids a split beyond its database end; do not move it to obtain discovery matches.
    with pytest.raises(ValueError):replace(req,pre_event=replace(req.pre_event,split_ms=1900000000001))


def test_literal_rule_count_oracle_and_complement(prices):
    root=prices.frozen
    baseline=resolve_granular_population(root,spec(horizon(minimum=-1000)))
    values=sorted(Decimal(v['value']) for r in baseline['records'] for v in r['scalar_ledger'] if v['known'])
    assert len(values)>=2 and values[0]<values[-1]
    threshold=(values[0]+values[-1])/2
    result=evaluate_granular_patterns(root,spec(horizon(minimum=threshold)));report=result.population_report()
    assert report['summary']['target_total']>0 and report['summary']['comparison_total']>0
    for rule in root.patterns:
        row=result.frame('patterns').set_index('pattern_id').loc[rule.pattern_id]
        for cohort,prefix in (('target',''),('comparison','comparison_')):
            count=assessable=0
            for record in report['records']:
                if record['cohort']!=cohort or record['partition']!='discovery':continue
                tokens=[root._root['columns'][t.column]['tokens'][record['anchor']+t.offset] for t in rule.terms]
                if any(v is None for v in tokens):continue
                assessable+=1;count+=all(v in t.allowed for t,v in zip(rule.terms,tokens))
            assert row[prefix+'matched']==count and row[prefix+'assessable']==assessable
    zero=evaluate_granular_patterns(root,spec(horizon(minimum=1000000)))
    assert zero.frame('patterns').matched.eq(0).all() and not zero.frame('patterns').support_eligible.any()
    assert any(not bool(o['matched']) for rule in root.patterns for o in result.pattern_matches(rule.pattern_id,'comparison').to_dict('records'))


def test_horizon_report_budget_and_cancellation(prices):
    import asyncio
    definition=spec(horizon(minimum=-1000));result=evaluate_granular_patterns(prices.frozen,definition)
    charge=json.loads(result.context)['retained_total_bytes']
    assert evaluate_granular_patterns(prices.frozen,definition,memory_limit_bytes=charge).evaluation_id==result.evaluation_id
    with pytest.raises(ValueError,match='limit'):evaluate_granular_patterns(prices.frozen,definition,memory_limit_bytes=charge-1)
    calls=[]
    def cancel():
        calls.append(1)
        if len(calls)==8:raise asyncio.CancelledError('horizon cancelled')
    with pytest.raises(asyncio.CancelledError):evaluate_granular_patterns(prices.frozen,definition,checkpoint=cancel)
    assert evaluate_granular_patterns(prices.frozen,definition).population_report()==result.population_report()


@pytest.mark.parametrize('operation',('evaluate','search'))
@pytest.mark.parametrize('action',('draft','checkpoint','source','close','cancel'))
def test_real_core_held_horizon_callbacks_cannot_publish(prices,monkeypatch,operation,action):
    from threading import Event
    from leonardo.core.core_runner import CoreRunner
    from leonardo.core.task_manager import TaskManager
    from leonardo.analysis.application import AnalysisApplicationService
    from tests.analysis_test.test_analysis_application import wait_until
    runner=CoreRunner(TaskManager());runner.start();app=AnalysisApplicationService(runner,prices.service);session=app.begin_session()
    results=[];done=Event();held=[]
    try:
        app.submit_pin_patterns(session,prices.parent,prices.catalogue,prices.study,[p.pattern_id for p in prices.frozen.patterns],
            result_callback=lambda r:(results.append(r),done.set()),callback_dispatcher=lambda cb:cb())
        assert done.wait(10) and results[0].status=='completed'
        state=app.refinement_snapshot(session);frozen=results[0].value;results.clear()
        submit=app.submit_evaluate_pinned if operation=='evaluate' else app.submit_refinement_search
        submit(session,state['set_id'],state['active_checkpoint_id'],state['generation'],spec(horizon(minimum=-1000)),
            result_callback=results.append,callback_dispatcher=held.append)
        wait_until(lambda:bool(held));assert app.is_busy(session)
        if action=='draft':app.invalidate_refinement_draft(session)
        elif action=='checkpoint':app.select_refinement_checkpoint(session,state['set_id'],state['active_checkpoint_id'])
        elif action=='source':app.clear_refinement_workspace(session)
        elif action=='close':app.end_session(session)
        else:app.cancel(session)
        for callback in tuple(held):callback();callback()
        assert not app.is_busy(session)
        if action=='close':assert results==[]
        else:
            assert len(results)==1 and results[0].status=='cancelled'
            state=app.refinement_snapshot(session)
            assert not state['workspace_present'] if action=='source' else state['evaluation_count']==0
    finally:app.end_session(session);runner.shutdown()


def test_cancel_entered_horizon_core_work(prices,monkeypatch):
    from threading import Event
    from leonardo.core.core_runner import CoreRunner
    from leonardo.core.task_manager import TaskManager
    from leonardo.analysis.application import AnalysisApplicationService
    runner=CoreRunner(TaskManager());runner.start();app=AnalysisApplicationService(runner,prices.service);session=app.begin_session()
    entered,release,done=Event(),Event(),Event();results=[]
    try:
        app.submit_pin_patterns(session,prices.parent,prices.catalogue,prices.study,[p.pattern_id for p in prices.frozen.patterns],
            result_callback=lambda r:(results.append(r),done.set()),callback_dispatcher=lambda cb:cb())
        assert done.wait(10) and results[0].status=='completed'
        state=app.refinement_snapshot(session);results.clear();done.clear()
        original=prices.service.evaluate_pattern_set
        def held(*a,checkpoint,**kw):
            entered.set();assert release.wait(10);checkpoint();return original(*a,checkpoint=checkpoint,**kw)
        monkeypatch.setattr(prices.service,'evaluate_pattern_set',held)
        app.submit_evaluate_pinned(session,state['set_id'],state['active_checkpoint_id'],state['generation'],spec(horizon()),
            result_callback=lambda r:(results.append(r),done.set()),callback_dispatcher=lambda cb:cb())
        assert entered.wait(5);assert app.cancel(session);release.set()
        assert done.wait(10) and results[0].status=='cancelled'
        assert app.refinement_snapshot(session)['evaluation_count']==0
    finally:release.set();app.end_session(session);runner.shutdown()


def test_horizon_history_limit_duplicate_reuse_and_accounting(prices):
    from leonardo.analysis.application import AnalysisApplicationService
    from tests.analysis_test.test_pattern_refinement_application import InlineRunner,execute
    app=AnalysisApplicationService(InlineRunner(),prices.service);session=app.begin_session()
    try:
        frozen=execute(lambda **cb:app.submit_pin_patterns(session,prices.parent,prices.catalogue,prices.study,
            [p.pattern_id for p in prices.frozen.patterns],**cb))
        first=None
        for n in range(20):
            state=app.refinement_snapshot(session)
            result=execute(lambda **cb:app.submit_evaluate_pinned(session,state['set_id'],state['active_checkpoint_id'],state['generation'],
                spec(horizon(n=6,minimum=n-1000)),**cb))
            if n==0:first=result
        state=app.refinement_snapshot(session);assert state['evaluation_count']==20
        with pytest.raises(ValueError,match='20 evaluation'):
            app.submit_evaluate_pinned(session,state['set_id'],state['active_checkpoint_id'],state['generation'],spec(horizon()),
                result_callback=lambda r:None,callback_dispatcher=lambda cb:cb())
        state=app.select_refinement_checkpoint(session,state['set_id'],frozen.source_discovery_id)
        duplicate=execute(lambda **cb:app.submit_evaluate_pinned(session,state['set_id'],state['active_checkpoint_id'],state['generation'],spec(horizon(minimum=-1000)),**cb))
        assert duplicate is first and app.refinement_snapshot(session)['evaluation_count']==20
        workspace=app._refinements[session]
        assert workspace.retained_total_bytes==workspace.retained_bytes+workspace.retained_population_bytes
    finally:app.end_session(session)


@pytest.mark.parametrize('role',('close','high','low'))
@pytest.mark.parametrize('version',('5.0','6.0'))
def test_owner_valid_v5_v6_output_names_are_not_prices(tmp_path,role,version):
    case=priced_case(tmp_path,spoof=role)
    loaded=case.loaded
    if version=='5.0':
        value=case.manifest.to_dict(include_revision_id=False);value.pop('utc_classification');value['schema_version']='5.0'
        value['previous_revision_id']=case.manifest.revision_id;value['revision_id']=deterministic_hash(value)
        manifest=database_revision_from_dict(value)
        case.store.publish_database_revision(case.store.load_database_definition(manifest.database_id),manifest,loaded.values_csv,
            expected_head_revision_id=case.manifest.revision_id)
        loaded=case.store.load_database_revision(manifest.database_id,manifest.revision_id)
    rows=list(csv.reader(StringIO(loaded.values_csv.decode())))
    payload,_=_gr04_capture_price_snapshot(loaded,rows,1900000000000)
    assert json.loads(payload)['roles'][role]['reason']=='calculated_output_not_canonical_price'


def test_v1_has_no_price_ownership_but_old_analysis_readable(tmp_path):
    case=priced_case(tmp_path);m=case.manifest.to_dict();member=m['members'][0]
    value={k:m[k] for k in ('database_id','display_name','description','seed_id','market_id','source_ohlcv','column_mapping',
        'first_timestamp_ms','last_timestamp_ms','row_count','column_count','values_sha256','created_at_utc','object_type')}
    value.update(schema_version='1.0',previous_revision_id=case.manifest.revision_id,
        collection_id=m['collection_sources'][0]['collection_id'],collection_revision_id=m['collection_sources'][0]['revision_id'],
        collection_manifest_hash='1'*64,artifact_version_keys=[{k:member[k] for k in ('logical_artifact_id','artifact_id')}],
        artifact_payload_hashes=[member['values_sha256']],portable_recipe_ids=[member['portable_recipe_id']])
    value['revision_id']=deterministic_hash(value);manifest=database_revision_from_dict(value)
    case.store.publish_database_revision(case.store.load_database_definition(manifest.database_id),manifest,case.loaded.values_csv,
        expected_head_revision_id=case.manifest.revision_id)
    service=AnalysisService(case.store,clock_ms=lambda:1900000000000)
    assert service.run(request(manifest,'signal')).columns[0].outcome=='completed'
    loaded=case.store.load_database_revision(manifest.database_id,manifest.revision_id)
    payload,_=_gr04_capture_price_snapshot(loaded,list(csv.reader(StringIO(loaded.values_csv.decode()))),1900000000000)
    assert all(v['reason']=='legacy_price_provenance_unavailable' for v in json.loads(payload)['roles'].values())


@pytest.mark.parametrize('tolerance',(0,1))
def test_multicolumn_rule_oracle_includes_nonassessable_observations(tmp_path,tolerance):
    case=priced_case(tmp_path,multiple=True,tolerance=tolerance);root=case.frozen
    result=evaluate_granular_patterns(root,spec(horizon(minimum=-1000)));report=result.population_report()
    checked=missing=0
    assert any(len({t.column for t in p.terms})==2 for p in root.patterns)
    if tolerance:assert any(len(t.allowed)>1 for p in root.patterns for t in p.terms)
    for rule in root.patterns:
        actual=result.frame('patterns').set_index('pattern_id').loc[rule.pattern_id]
        for cohort,prefix in (('target',''),('comparison','comparison_')):
            matched=assessable=exact=0
            for row in report['records']:
                if row['cohort']!=cohort or row['partition']!='discovery':continue
                values=[root._root['columns'][t.column]['tokens'][row['anchor']+t.offset] for t in rule.terms]
                if any(v is None for v in values):missing+=1;continue
                assessable+=1;matched+=all(v in t.allowed for t,v in zip(rule.terms,values));exact+=all(v == t.center for t,v in zip(rule.terms,values))
            assert actual[prefix+'matched']==matched and actual[prefix+'assessable']==assessable
            assert actual[prefix+'exact_matched']==exact and actual[prefix+'added_by_tolerance']==matched-exact
            checked+=1
    assert checked>0 and missing>0


def test_cancel_queued_horizon_core_work(prices,monkeypatch):
    from threading import Event
    from leonardo.core.core_runner import CoreRunner
    from leonardo.core.task_manager import TaskManager
    from leonardo.analysis.application import AnalysisApplicationService
    runner=CoreRunner(TaskManager(),max_worker_threads=1);runner.start()
    app=AnalysisApplicationService(runner,prices.service);session=app.begin_session()
    entered,release,done=Event(),Event(),Event();results=[];calls=[]
    try:
        app.submit_pin_patterns(session,prices.parent,prices.catalogue,prices.study,[p.pattern_id for p in prices.frozen.patterns],
            result_callback=lambda r:(results.append(r),done.set()),callback_dispatcher=lambda cb:cb())
        assert done.wait(10) and results[0].status=='completed'
        state=app.refinement_snapshot(session);results.clear();done.clear()
        def occupy(reporter):entered.set();assert release.wait(15)
        runner.submit_blocking_job(occupy,task_name='gr04-occupied');assert entered.wait(5)
        monkeypatch.setattr(prices.service,'evaluate_pattern_set',lambda *a,**kw:calls.append(True))
        app.submit_evaluate_pinned(session,state['set_id'],state['active_checkpoint_id'],state['generation'],spec(horizon()),
            result_callback=lambda r:(results.append(r),done.set()),callback_dispatcher=lambda cb:cb())
        assert app.cancel(session)
        assert done.wait(10) and results[0].status=='cancelled' and not calls
        assert app.refinement_snapshot(session)['evaluation_count']==0
    finally:release.set();app.end_session(session);runner.shutdown()


@pytest.mark.parametrize('search',(False,True))
@pytest.mark.parametrize('fault',('context_source','report_source','definition','parent'))
def test_horizon_publication_rejects_inconsistent_output(prices,search,fault):
    from leonardo.analysis.application import _gr03_validate_output
    case=prices;definition=spec(horizon(minimum=-1000));parent=case.frozen.source_discovery_id
    result=(search_granular_patterns(case.frozen,case.parent,case.catalogue,definition,parent_id=parent) if search
            else evaluate_granular_patterns(case.frozen,definition))
    _gr03_validate_output(result,case.frozen,definition,parent,search=search)
    data=deepcopy(result._data);context=json.loads(result.context)
    if fault=='context_source':context['horizon_source']['price_snapshot_id']='wrong'
    elif fault=='report_source':data['_gr03_population']['horizon_source']['price_snapshot_id']='wrong'
    elif fault=='definition':context['definition_id']='wrong'
    elif search:context['search_parent']['checkpoint_id']='wrong'
    else:context['parent_id']='wrong'
    altered=replace(result,_data=data,context=_json(context))
    with pytest.raises(ValueError):_gr03_validate_output(altered,case.frozen,definition,parent,search=search)
    if search:
        with pytest.raises(ValueError):pin_patterns(case.parent,case.catalogue,altered,altered.frame('patterns').pattern_id.tolist()[:2])


@pytest.mark.parametrize('cell,reason',(('', 'close_value_unavailable:1'),('bad','close_value_invalid:1')))
def test_owner_rejects_bad_canonical_cells_and_adapter_marks_unavailable(tmp_path,cell,reason):
    from leonardo.data_manager.creation_store import DataManagerCreationStoreError
    case=priced_case(tmp_path);base=resolve_granular_population(case.frozen,spec(horizon(minimum=-1000)))
    target=next(r for r in base['records'] if r['cohort']=='target');anchor=target['anchor']
    frame=pd.read_csv(StringIO(case.loaded.values_csv.decode()),dtype=str,keep_default_na=False)
    frame.loc[anchor+1,'close']=cell
    with pytest.raises(DataManagerCreationStoreError):publish_variant(case,frame)
    assert case.store.load_database_head(case.manifest.database_id).revision_id==case.manifest.revision_id
    # The owner refuses malformed base cells today. Test the adapter's defensive
    # missingness independently; this decoded specimen is never rebound or pinned.
    model=json.loads(case.frozen._root['_gr04_prices']);model['roles']['close']['raw_values'][anchor+1]=cell
    window,values=_gr04_window(model,'unbound-adapter-specimen','event',anchor,'UP',6,('close',),
        _gr04_spacing(model['timestamps'],'1m',lambda:None),lambda:None)
    assert not window['reason'] and values['terminal_directional_pct']==dict(value=None,reason=reason)


def test_horizon_crosses_saved_episode_endpoint_and_excludes_event_extremes(prices):
    case=prices;report=resolve_granular_population(case.frozen,spec(horizon(n=100,minimum=-1000)))
    events={e['event_id']:e for e in case.catalogue.instance(case.request.instance_id)['events']}
    crossings=[]
    for record in report['records']:
        if not record['scalar_ledger'] or not record['scalar_ledger'][0]['known']:continue
        for witness in events[record['row_id']]['witnesses']:
            episode=witness['episode']
            if episode['status']=='ended':
                endpoint=witness['metrics']['episode_metrics']['final_structural']['movement']['endpoint']['ts_ms']
                if record['horizon_windows'][0]['end_ts_ms']>endpoint:crossings.append((record,episode))
    assert crossings
    # Window inputs contain only S+1..S+N high/low values, never the event candle.
    model=json.loads(case.frozen._root['_gr04_prices']);anchor=crossings[0][0]['anchor']
    spacing=_gr04_spacing(model['timestamps'],'1m',lambda:None)
    original=_gr04_window(model,'fixture','event',anchor,'UP',6,('close','high','low'),spacing,lambda:None)
    model['roles']['high']['raw_values'][anchor]='1e100';model['roles']['low']['raw_values'][anchor]='-1e100'
    changed=_gr04_window(model,'fixture','event',anchor,'UP',6,('close','high','low'),spacing,lambda:None)
    assert original==changed
