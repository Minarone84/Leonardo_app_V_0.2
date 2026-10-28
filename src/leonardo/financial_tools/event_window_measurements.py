"""Pure stored event-close outcomes under an isolated Decimal policy."""
from decimal import (Decimal as _Decimal, Context as _Context, localcontext as _localcontext,
                     ROUND_HALF_EVEN as _HALF_EVEN, MIN_EMIN as _MIN_EMIN, MAX_EMAX as _MAX_EMAX)


def _gr04_scan(series, role, length, checkpoint, closes=None):
    if series is None:
        return None, role + '_series_unavailable'
    if len(series) < length:
        return None, role + '_series_incomplete'
    values = []
    for index, cell in enumerate(series):
        if checkpoint is not None and index % 64 == 0:
            checkpoint()
        offset = index + (role != 'close')
        if cell is None:
            return None, f'{role}_value_unavailable:{offset}'
        if type(cell) not in (int, float, _Decimal):
            return None, f'{role}_value_invalid:{offset}'
        value = _Decimal(str(cell)) if type(cell) is float else _Decimal(cell)
        if not value.is_finite():
            return None, f'{role}_value_invalid:{offset}'
        if role == 'high' and value < closes[index + 1]:
            return None, f'high_below_close:{offset}'
        if role == 'low' and value > closes[index + 1]:
            return None, f'low_above_close:{offset}'
        values.append(value)
    return values, ''


def measure_event_window(close, *, high=None, low=None, horizon_bars: int,
                         direction: str, checkpoint=None) -> dict:
    """Measure N subsequent bars; close includes the reference, high/low do not.

    Missing evidence is reported independently per scalar. Configuration errors
    and cancellation propagate; caller Decimal flags, traps and precision survive.
    """
    if checkpoint is not None:
        checkpoint()
    if type(horizon_bars) is not int or not 1 <= horizon_bars <= 1000:
        raise ValueError('horizon_bars must be an integer from 1 through 1000')
    if direction not in ('UP', 'DOWN'):
        raise ValueError('direction must be UP or DOWN')
    for role, series, length in (('close', close, horizon_bars + 1),
                                 ('high', high, horizon_bars), ('low', low, horizon_bars)):
        if series is not None:
            if not isinstance(series, (list, tuple)):
                raise TypeError(f'{role} must be a list, tuple or None')
            if len(series) > length:
                raise ValueError(f'{role} exceeds the requested horizon')
    policy = _Context(prec=50, rounding=_HALF_EVEN, Emin=_MIN_EMIN, Emax=_MAX_EMAX,
                      capitals=1, clamp=0, flags=[], traps=[])
    result = {}
    with _localcontext(policy):
        closes, close_reason = _gr04_scan(close, 'close', horizon_bars + 1, checkpoint)
        sides = {}
        if not close_reason:
            for role, series in (('high', high), ('low', low)):
                sides[role] = _gr04_scan(series, role, horizon_bars, checkpoint, closes)
        for field in ('terminal_signed', 'terminal_directional', 'favorable_excursion', 'adverse_excursion'):
            reason, points = close_reason, None
            if not reason:
                if field == 'terminal_signed' or field == 'terminal_directional' and direction == 'UP':
                    points = closes[-1] - closes[0]
                elif field == 'terminal_directional':
                    points = closes[0] - closes[-1]
                else:
                    upper = (field == 'favorable_excursion') == (direction == 'UP')
                    values, reason = sides['high' if upper else 'low']
                    if not reason:
                        points = max(_Decimal(0), max(values) - closes[0] if upper else closes[0] - min(values))
            for unit in ('points', 'pct'):
                scalar_reason, value = reason, None
                if not scalar_reason:
                    if unit == 'pct' and closes[0] <= 0:
                        scalar_reason = 'nonpositive_reference_for_percent'
                    else:
                        value = points if unit == 'points' else points * 100 / closes[0]
                        if not value.is_finite():
                            value, scalar_reason = None, 'nonfinite_derived_result'
                result[field + '_' + unit] = dict(value=value, reason=scalar_reason)
    if checkpoint is not None:
        checkpoint()
    return result
