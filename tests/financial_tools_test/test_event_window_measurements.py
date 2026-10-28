"""Independent fixed-horizon arithmetic and isolation checks."""
from decimal import Decimal, Context, localcontext, getcontext, ROUND_HALF_EVEN, MIN_EMIN, MAX_EMAX
from fractions import Fraction
import pytest
from leonardo.financial_tools.event_window_measurements import measure_event_window


@pytest.mark.parametrize('direction', ('UP', 'DOWN'))
@pytest.mark.parametrize('n', (1, 2, 6, 1000))
def test_independent_fraction_oracle_all_eight(direction, n):
    future = [100, 102, 101, 99, 103, 104] if n <= 6 else [100 + (i % 13 - 6) for i in range(n)]
    future = future[:n]; high = [v+1 for v in future]; low = [v-1 for v in future]
    if direction == 'DOWN': future, high, low = [200-v for v in future], [200-v for v in low], [200-v for v in high]
    result = measure_event_window([100, *future], high=high, low=low, horizon_bars=n, direction=direction)
    d = 1 if direction == 'UP' else -1
    expected = dict(terminal_signed=Fraction(future[-1]-100), terminal_directional=Fraction(d*(future[-1]-100)),
        favorable_excursion=Fraction(max(0, max(d*(v-100) for v in (high if d==1 else low)))),
        adverse_excursion=Fraction(max(0, max(-d*(v-100) for v in (low if d==1 else high)))))
    assert len(result) == 8
    for field, points in expected.items():
        for unit, value in (('points', points), ('pct', points*100/Fraction(100))):
            assert result[field+'_'+unit] == dict(value=Decimal(value.numerator)/Decimal(value.denominator), reason='')


@pytest.mark.parametrize('p0,terminal', [('3','4'),('1e-500','2e-500'),('1e500','1.000000000000000000000000000000000000000000000000001e500'),
    ('1.000000000000000000000000000000000000000000000000009','2.000000000000000000000000000000000000000000000000001')])
def test_sequential_policy_and_ambient_context(p0, terminal):
    policy=Context(prec=50,rounding=ROUND_HALF_EVEN,Emin=MIN_EMIN,Emax=MAX_EMAX,traps=[])
    # Independent staged rounding: exact rational subtraction followed by each policy operation.
    difference=Fraction(Decimal(terminal))-Fraction(Decimal(p0))
    with localcontext(Context(prec=2000,Emin=MIN_EMIN,Emax=MAX_EMAX,traps=[])):
        exact=Decimal(difference.numerator)/Decimal(difference.denominator)
    points=policy.create_decimal(exact)
    pct=policy.divide(policy.multiply(points,Decimal(100)),Decimal(p0))
    with localcontext() as ambient:
        ambient.prec=3
        ambient.rounding='ROUND_FLOOR'
        for signal in ambient.traps: ambient.traps[signal]=True
        for signal in ambient.flags: ambient.flags[signal]=True
        before=(ambient.copy(),dict(ambient.flags),dict(ambient.traps))
        result=measure_event_window([Decimal(p0),Decimal(terminal)],horizon_bars=1,direction='UP')
        # Snapshot the API boundary before pytest/GUI assertion hooks run.
        after=(ambient.prec,ambient.rounding,dict(ambient.flags),dict(ambient.traps))
    assert result['terminal_signed_points']['value']==points
    assert result['terminal_signed_pct']['value']==pct
    assert after==(before[0].prec,before[0].rounding,before[1],before[2])


@pytest.mark.parametrize('n', (True, False, 0, -1, 1001, 1.0, '6', None))
def test_invalid_horizon(n):
    with pytest.raises((TypeError,ValueError)): measure_event_window([100,101],horizon_bars=n,direction='UP')


@pytest.mark.parametrize('role', ('close','high','low'))
@pytest.mark.parametrize('bad', ('text', iter([100]), {0:100}, [100,101,102]))
def test_container_and_overlong_rejected(role,bad):
    args=dict(close=[100,101],high=[102],low=[99],horizon_bars=1,direction='UP');args[role]=bad
    with pytest.raises((TypeError,ValueError)):measure_event_window(**args)


@pytest.mark.parametrize('cell,token', [(None,'unavailable'),(True,'invalid'),('100','invalid'),(float('nan'),'invalid'),
    (float('inf'),'invalid'),(Decimal('sNaN'),'invalid'),(object(),'invalid')])
@pytest.mark.parametrize('role', ('close','high','low'))
def test_missing_cell_reason_and_independent_sides(role,cell,token):
    args=dict(close=[100,101,102],high=[102,103],low=[99,100],horizon_bars=2,direction='UP')
    args[role][1 if role=='close' else 0]=cell
    result=measure_event_window(**args)
    affected=('terminal_signed','terminal_directional','favorable_excursion','adverse_excursion') if role=='close' else (('favorable_excursion',) if role=='high' else ('adverse_excursion',))
    for key, value in result.items():
        assert value['reason']==(f'{role}_value_{token}:1' if any(key.startswith(f) for f in affected) else '')


@pytest.mark.parametrize('role', ('close','high','low'))
@pytest.mark.parametrize('series,reason', [(None,'unavailable'),([], 'incomplete')])
def test_absent_and_short_series(role,series,reason):
    args=dict(close=[100,101],high=[102],low=[99],horizon_bars=1,direction='UP');args[role]=series
    result=measure_event_window(**args)
    field={'close':'terminal_signed','high':'favorable_excursion','low':'adverse_excursion'}[role]
    assert result[field+'_points']==dict(value=None,reason=role+'_series_'+reason)


@pytest.mark.parametrize('p0', (0,-100))
def test_nonpositive_reference_preserves_points(p0):
    result=measure_event_window([p0,p0+1],high=[p0+2],low=[p0-1],horizon_bars=1,direction='UP')
    assert all(v['reason']=='nonpositive_reference_for_percent' for k,v in result.items() if k.endswith('_pct'))
    assert all(v['reason']=='' and type(v['value']) is Decimal for k,v in result.items() if k.endswith('_points'))


def test_first_consistency_error_and_precedence():
    result=measure_event_window([100,101,102],high=[100,None],low=[102,None],horizon_bars=2,direction='UP')
    assert result['favorable_excursion_points']['reason']=='high_below_close:1'
    assert result['adverse_excursion_points']['reason']=='low_above_close:1'
    assert result['terminal_signed_points']['value']==2
    result=measure_event_window([0,None],high=[None],horizon_bars=1,direction='UP')
    assert all(v['reason']=='close_value_unavailable:1' for v in result.values())


def test_callback_cancellation_and_context_unchanged():
    class Cancelled(Exception): pass
    calls=[]
    def cancel():
        calls.append(1)
        if len(calls)==5:raise Cancelled('exact cancellation')
    before=getcontext().copy()
    with pytest.raises(Cancelled,match='exact cancellation'):
        measure_event_window([100]*1001,high=[101]*1000,low=[99]*1000,horizon_bars=1000,direction='UP',checkpoint=cancel)
    assert len(calls)==5 and getcontext().flags==before.flags and getcontext().traps==before.traps
    calls.clear()
    measure_event_window([100]*1001,high=[101]*1000,low=[99]*1000,horizon_bars=1000,direction='UP',checkpoint=lambda:calls.append(1))
    assert len(calls)>=49


@pytest.mark.parametrize('direction', ('up','RANGE',None,1))
def test_invalid_direction(direction):
    with pytest.raises(ValueError):measure_event_window([100,101],horizon_bars=1,direction=direction)


def test_nonfinite_derived_values_are_unavailable_without_ambient_flags():
    huge=Decimal((0,(9,),MAX_EMAX));negative=huge.copy_negate()
    before=getcontext().copy()
    result=measure_event_window([negative,huge],high=[huge],low=[negative],horizon_bars=1,direction='UP')
    assert result['terminal_signed_points']==dict(value=None,reason='nonfinite_derived_result')
    assert result['terminal_signed_pct']['reason']=='nonpositive_reference_for_percent'
    assert getcontext().flags==before.flags and getcontext().traps==before.traps


@pytest.mark.parametrize('where',('entry','return'))
def test_cancellation_at_api_boundaries_and_exact_retry(where):
    class Cancelled(Exception):pass
    args=dict(close=[100,101],high=[102],low=[99],horizon_bars=1,direction='UP');calls=[]
    expected=measure_event_window(**args,checkpoint=lambda:calls.append(1));total=len(calls);calls.clear()
    def check():
        calls.append(1)
        if len(calls)==(1 if where=='entry' else total):raise Cancelled()
    with pytest.raises(Cancelled):measure_event_window(**args,checkpoint=check)
    assert measure_event_window(**args)==expected


@pytest.mark.parametrize('p0,cn',((1e-300,2e-300),(1e300,1.0000000001e300)))
def test_finite_float_decimal_conversion(p0,cn):
    policy=Context(prec=50,rounding=ROUND_HALF_EVEN,Emin=MIN_EMIN,Emax=MAX_EMAX,traps=[])
    points=policy.subtract(Decimal(str(cn)),Decimal(str(p0)))
    expected=policy.divide(policy.multiply(points,Decimal(100)),Decimal(str(p0)))
    result=measure_event_window([p0,cn],horizon_bars=1,direction='UP')
    assert result['terminal_signed_points']['value']==points and result['terminal_signed_pct']['value']==expected
