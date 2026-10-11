"""Meaningful dashboard tests without network requests. Run python test_dashboard.py."""
import sys
import math
from datetime import date
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

sys.path.insert(0, str(Path(__file__).parent))
APP = str(Path(__file__).with_name('app.py'))

app = AppTest.from_file(APP).run(timeout=20)
assert not app.exception, app.exception
app.text_area[0].set_value('NVDA, AMD, MSFT, AAPL')
app.checkbox[0].set_value(True)
app.button[0].click().run(timeout=30)
assert not app.exception, app.exception
bundle = app.session_state['scan']
assert len(bundle['rows']) == 4
returns = [r['ranking_return_pct'] for r in bundle['rows']]
assert returns == sorted(returns, reverse=True)
assert app.warning and 'DEMO' in app.warning[0].value
assert len(app.get('vega_lite_chart')) == 1
next(w for w in app.selectbox if w.label == 'Inspect ticker').select('NVDA').run(timeout=20)
assert not app.exception, app.exception
assert app.session_state['scan']['rows'] == bundle['rows']

# Second strategy: both calls covered, 200-share stock baseline, capped gains.
next(w for w in app.selectbox if w.label == 'Strategy').select('Sell +15% / Sell +30% (200 shares)')
app.button[0].click().run(timeout=30)
assert not app.exception, app.exception
covered = app.session_state['scan']
assert len(covered['rows']) == 4
assert all(r['shares'] == 200 and r['call2_action'] == 'Sell' for r in covered['rows'])
assert all(math.isclose(r['call2_otm_pct'], 30) for r in covered['rows'])
for r in covered['rows']:
    cases = {s['stock_move_pct']:s for s in covered['scenarios'] if s['ticker'] == r['ticker']}
    assert math.isclose(cases[30]['strategy_profit'], cases[50]['strategy_profit'])
    assert math.isclose(cases[30]['strategy_profit'], r['max_profit'])
    assert math.isclose(cases[10]['stock_only_profit'], 200*r['stock_price']*.1)

from strategies import analyze_strategy, strategy_payoff, synthetic_strategy
args = SimpleNamespace(strategy='two_covered_calls',days=14,expiry_tolerance=4,
                       strike_tolerance=.03,commission=.65,rank_move=15)
snap = synthetic_strategy('TEST',date(2026,10,10),args,spot=100,first_bid=3)
r, _ = analyze_strategy('TEST',snap,args,date(2026,10,10))
# Bid 3 + bid .8 = $380; strike gains 100*$15 + 100*$30 = $4,500.
assert math.isclose(r['max_profit'],4878.70)
assert math.isclose(r['initial_net_outlay'],19621.30)
assert math.isclose(r['breakeven'],98.1065)
assert math.isclose(strategy_payoff(100,120,115,130,380,1.30,'two_covered_calls'),3878.70)
assert math.isclose(strategy_payoff(100,0,115,130,380,1.30,'two_covered_calls'),-r['max_loss'])
assert math.isclose(strategy_payoff(100,1000,115,130,380,1.30,'two_covered_calls'),r['max_profit'])
# Regression: original overlay formula unchanged across representative prices.
from options_scanner import payoff
for final in (0,80,100,115,118,120,150,1000):
    assert math.isclose(strategy_payoff(100,final,115,120,200,1.30,'call_overlay'),
                        payoff(100,final,115,120,2,1.30))

# Validation preserves the last completed scan instead of relabeling its inputs.
app.text_area[0].set_value('')
app.button[0].click().run(timeout=20)
assert app.error
assert app.session_state['scan']['rows'] == covered['rows']

# Provider failure renders a useful empty/error state, not an exception.
with patch('market_data.fetch_snapshot', side_effect=RuntimeError('Too Many Requests: rate limited')) as mocked:
    failed = AppTest.from_file(APP).run(timeout=20)
    assert mocked.call_count == 0, 'Startup must not fetch market data'
    failed.text_area[0].set_value('FAILONE, FAILTWO')
    failed.button[0].click().run(timeout=20)
    assert not failed.exception, failed.exception
    assert len(failed.session_state['scan']['errors']) == 2
    assert not failed.session_state['scan']['rows']
    assert 1 <= mocked.call_count <= 2
    assert failed.error
from market_data import fetch_snapshot
import subprocess
with patch('market_data.subprocess.run', side_effect=subprocess.TimeoutExpired('worker',12)) as request:
    try:
        fetch_snapshot('NVDA',14,4,'2026-10-11')
    except TimeoutError:
        pass
    else:
        raise AssertionError('Timeout was not surfaced')
    assert request.call_args.kwargs['timeout'] == 12

# Two live requests overlap; cached snapshots eliminate another fetch on a rescan.
import threading
barrier = threading.Barrier(2)
def mock_snapshot(symbol, days, tolerance, today_iso):
    barrier.wait(timeout=5)
    args = SimpleNamespace(strategy='call_overlay', days=days)
    return synthetic_strategy(symbol,date.fromisoformat(today_iso),args,spot=100,first_bid=3)
with patch('market_data.fetch_snapshot', side_effect=mock_snapshot) as request:
    parallel = AppTest.from_file(APP).run(timeout=20)
    parallel.text_area[0].set_value('PARONE, PARTWO')
    parallel.button[0].click().run(timeout=20)
    assert not parallel.exception, parallel.exception
    assert len(parallel.session_state['scan']['rows']) == 2
    assert request.call_count == 2
    parallel.button[0].click().run(timeout=20)
    assert not parallel.exception
    assert request.call_count == 2, 'Rescan should reuse cached snapshots'
print('PASS: both strategies, startup without requests, concurrency, cache reuse, timeout, rate-limit handling')
