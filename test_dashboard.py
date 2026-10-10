"""Meaningful dashboard tests without network requests. Run python test_dashboard.py."""
import sys
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

sys.path.insert(0, str(Path(__file__).parent))
APP = str(Path(__file__).with_name('app.py'))

app = AppTest.from_file(APP).run(timeout=20)
assert not app.exception, app.exception
app.checkbox[0].set_value(True)
app.button[0].click().run(timeout=30)
assert not app.exception, app.exception
bundle = app.session_state['scan']
assert len(bundle['rows']) == 4
returns = [r['ranking_return_pct'] for r in bundle['rows']]
assert returns == sorted(returns, reverse=True)
assert app.warning and 'DEMO' in app.warning[0].value
assert len(app.get('plotly_chart')) == 1
app.selectbox[-1].select('NVDA').run(timeout=20)
assert not app.exception, app.exception
assert app.session_state['scan']['rows'] == bundle['rows']

# Validation preserves the last completed scan instead of relabeling its inputs.
app.text_area[0].set_value('')
app.button[0].click().run(timeout=20)
assert app.error
assert app.session_state['scan']['rows'] == bundle['rows']

# Provider failure renders a useful empty/error state, not an exception.
with patch('options_scanner.fetch', side_effect=RuntimeError('Too Many Requests: rate limited')) as mocked:
    failed = AppTest.from_file(APP).run(timeout=20)
    failed.text_area[0].set_value('FAILONE, FAILTWO')
    failed.button[0].click().run(timeout=20)
    assert not failed.exception, failed.exception
    assert len(failed.session_state['scan']['errors']) == 2
    assert not failed.session_state['scan']['rows']
    assert mocked.call_count == 1
    assert failed.error
print('PASS: dashboard render, scan, ranking, detail selection, validation, rate-limit handling')
