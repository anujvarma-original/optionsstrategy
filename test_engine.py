"""Network-free checks: python test_engine.py (no third-party dependencies)."""
import json
import math
import subprocess
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from market_data import FETCH_TIMEOUT, fetch_snapshot
from options_scanner import payoff
from strategies import analyze_strategy, strategy_payoff, synthetic_strategy

for strategy in ('call_overlay', 'two_covered_calls'):
    args = SimpleNamespace(strategy=strategy, days=14, expiry_tolerance=4,
                           strike_tolerance=.03, commission=.65, rank_move=15)
    snapshot = synthetic_strategy('TEST', date(2026,10,11), args, spot=100, first_bid=3)
    row, cases = analyze_strategy('TEST', snapshot, args, date(2026,10,11))
    assert math.isclose(row['max_loss'], row['initial_net_outlay'])
    if strategy == 'call_overlay':
        for final in (0,80,100,115,118,120,150,1000):
            assert math.isclose(strategy_payoff(100,final,115,120,200,1.3,strategy),
                                payoff(100,final,115,120,2,1.3))
    else:
        assert row['shares'] == 200
        assert math.isclose(row['max_profit'],4878.70)
        assert math.isclose(strategy_payoff(100,1000,115,130,380,1.3,strategy), row['max_profit'])

with patch('market_data.subprocess.run', side_effect=subprocess.TimeoutExpired('worker',FETCH_TIMEOUT)) as mocked:
    try:
        fetch_snapshot('TEST',14,4,'2026-10-11')
    except TimeoutError:
        pass
    else:
        raise AssertionError('Missing hard timeout')
    assert mocked.call_args.kwargs['timeout'] == FETCH_TIMEOUT
    assert mocked.call_args.kwargs['check'] is False

with patch('market_data.subprocess.run', return_value=SimpleNamespace(returncode=0, stdout=json.dumps({'snapshot':snapshot}))):
    assert fetch_snapshot('TEST',14,4,'2026-10-11') == snapshot
with patch('market_data.subprocess.run', return_value=SimpleNamespace(returncode=0, stdout=json.dumps({'error':'Rate limited'}))):
    try:
        fetch_snapshot('TEST',14,4,'2026-10-11')
    except RuntimeError as exc:
        assert 'Rate limited' in str(exc)
    else:
        raise AssertionError('Missing provider error')
print('PASS: both strategy payoffs, coverage, capped gains, worker timeout, response parsing, provider errors')
