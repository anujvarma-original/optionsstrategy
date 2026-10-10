"""Streamlit dashboard. Start with: streamlit run app.py"""
import io
import re
import zipfile
from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from options_scanner import fetch
from strategies import STRATEGIES, analyze_strategy, strategy_payoff, save_strategy_report, synthetic_strategy

st.set_page_config(page_title="Bullish Options Scanner", page_icon="📈", layout="wide")


@st.cache_data(ttl=600, max_entries=250, show_spinner=False)
def cached_snapshot(symbol, days, tolerance, today_iso):
    args = SimpleNamespace(days=days, expiry_tolerance=tolerance)
    return fetch(symbol, args, date.fromisoformat(today_iso))


def parse_symbols(text):
    clean = ' '.join(line.split('#')[0] for line in text.splitlines())
    return list(dict.fromkeys(s.upper() for s in re.split(r'[\s,;]+', clean.strip()) if s))


def downloadable_report(bundle):
    args = SimpleNamespace(**bundle['settings'])
    with TemporaryDirectory() as folder:
        save_strategy_report(Path(folder), bundle['rows'], bundle['scenarios'], bundle['errors'], args)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(Path(folder).iterdir()):
                archive.write(path, path.name)
        return buffer.getvalue()


st.title("Bullish Options Scanner")
st.markdown("**Compare a call overlay with two fully covered calls.**")
st.caption("Same expiration · 100 or 200 shares by strategy · conditional expiration payoffs")

with st.sidebar:
    st.header("Build your scan")
    with st.form('scan_form'):
        strategy_label = st.selectbox('Strategy', [v['label'] for v in STRATEGIES.values()])
        strategy = next(k for k, v in STRATEGIES.items() if v['label'] == strategy_label)
        raw = st.text_area('Tickers', value='NVDA, AMD, MSFT, AAPL', height=110,
                           help='Comma, space, or newline separated. Up to 25 symbols.')
        days = st.number_input('Target days to expiration', min_value=1, max_value=365, value=14)
        rank_move = st.slider('Stock move used for ranking (%)', -50, 100, 15, 1)
        rank_label = st.selectbox('Rank highest first by', ['Percentage return', 'Dollar profit per strategy position'])
        demo = st.checkbox('Demo mode — synthetic prices', value=False)
        with st.expander('Selection and fees'):
            expiry_tolerance = st.number_input('Expiration tolerance (calendar days)', 0, 14, 4)
            strike_tolerance = st.number_input('Maximum strike rounding (% of stock price)', 0.0, 10.0, 3.0, .5)
            commission = st.number_input('Entry fee per option contract ($)', 0.0, 100.0, .65, .05)
        submitted = st.form_submit_button('Scan tickers', type='primary', width='stretch')
    st.caption('Successful market snapshots are cached for 10 minutes. Scan results stay until you scan again.')
    st.caption('Yahoo can delay or rate-limit quotes. Demo mode never uses market data.')

if submitted:
    symbols = parse_symbols(raw)
    if not symbols or len(symbols) > 25:
        st.error('Enter between 1 and 25 tickers.')
    elif any(not re.fullmatch(r'[A-Z0-9.^=\-]{1,20}', s) for s in symbols):
        st.error('A ticker contains unsupported characters.')
    else:
        settings = dict(strategy=strategy, days=int(days), expiry_tolerance=int(expiry_tolerance),
                        strike_tolerance=float(strike_tolerance)/100,
                        commission=float(commission), rank_move=float(rank_move),
                        rank_by='return' if rank_label == 'Percentage return' else 'profit', demo=demo)
        args = SimpleNamespace(**settings)
        today = datetime.now(ZoneInfo('America/New_York')).date()
        rows, scenarios, errors = [], [], []
        bar = st.progress(0, text='Starting scan')
        for index, symbol in enumerate(symbols):
            bar.progress(index/len(symbols), text=f'Loading {symbol} ({index+1}/{len(symbols)})')
            try:
                snapshot = (synthetic_strategy(symbol, today, args, 100+index*25, 2+index*.5)
                            if demo else cached_snapshot(symbol, args.days, args.expiry_tolerance, today.isoformat()))
                row, cases = analyze_strategy(symbol, snapshot, args, today)
                rows.append(row)
                scenarios.extend(cases)
            except Exception as exc:
                message = f'{type(exc).__name__}: {exc}'
                errors.append(dict(ticker=symbol, error=message))
                if 'rate limit' in message.lower() or 'too many requests' in message.lower() or '429' in message:
                    for remaining in symbols[index+1:]:
                        errors.append(dict(ticker=remaining, error='Not requested: Yahoo rate limit; retry later.'))
                    break
        bar.progress(1.0, text='Scan complete')
        key = 'ranking_return_pct' if args.rank_by == 'return' else 'ranking_profit'
        rows.sort(key=lambda r: r[key], reverse=True)
        order = {r['ticker']: i for i, r in enumerate(rows)}
        scenarios.sort(key=lambda s: (order[s['ticker']], s['stock_move_pct']))
        st.session_state['scan'] = dict(rows=rows, scenarios=scenarios, errors=errors,
                                       settings=settings, scanned_at=datetime.now(ZoneInfo('America/Chicago')).isoformat())

if 'scan' not in st.session_state:
    st.info('Enter your ticker list and click Scan tickers. Enable Demo mode to preview the dashboard without market data.')
    st.markdown('''The original overlay uses 100 shares, sells at +15%, and buys at +20%; gains resume above the higher strike.
The two-call strategy uses 200 shares and sells one call at +15% and one at +30%.
Between those strikes only 100 shares retain upside; above the higher strike profit is capped.
Both calls are covered. Available strikes round upward; actual percentages appear in each ticker detail.''')
else:
    bundle = st.session_state['scan']
    rows, scenarios, errors = bundle['rows'], bundle['scenarios'], bundle['errors']
    settings = bundle['settings']
    spec = STRATEGIES[settings['strategy']]
    shares = spec['shares']
    st.subheader(spec['label'])
    if settings['demo']:
        st.warning('DEMO — all stock prices and premiums below are synthetic. These are not market quotes.')
    st.caption(f"Results from {bundle['scanned_at']} · Target {settings['days']} calendar days · "
               f"Ranking scenario {settings['rank_move']:+g}% · "
               f"Ranking by {'percentage return' if settings['rank_by'] == 'return' else 'dollar profit'}")
    if errors:
        with st.expander(f'Skipped or unavailable: {len(errors)} ticker(s)', expanded=not bool(rows)):
            st.dataframe(pd.DataFrame(errors), hide_index=True, width='stretch')
            st.caption('Zero bids, missing quotes, overlapping or distant strikes, and nonpositive executable credits are skipped. A +30% call two weeks out may have no bid.')
    if not rows:
        st.error('No usable positions found. Try fewer tickers later, or enable Demo mode to inspect the dashboard.')
    else:
        best = rows[0]
        cols = st.columns(4)
        cols[0].metric('Usable tickers', len(rows))
        cols[1].metric('Top ranked ticker', best['ticker'])
        cols[2].metric('Top ticker scenario profit', f"${best['ranking_profit']:,.2f}")
        cols[3].metric('Top ticker scenario return', f"{best['ranking_return_pct']:.2f}%")
        rankings, details, assumptions = st.tabs(['Ranked opportunities', 'Ticker payoff', 'Method and data'])
        with rankings:
            st.caption(f'Profits per {shares} shares. Scenario return = expiration profit ÷ initial net cash outlay. No probability weighting or annualization.')
            summary = pd.DataFrame(rows)[['ticker', 'stock_price', 'expiration', 'days_to_expiry',
                                         'call1_strike', 'call2_strike', 'net_premium_total',
                                         'initial_net_outlay', 'ranking_profit', 'ranking_return_pct', 'breakeven']]
            summary.columns = ['Ticker', 'Stock ($)', 'Expiration', 'Days', 'Sell strike ($)', f"{spec['action']} second strike ($)",
                               'Total premium ($)', 'Net outlay ($)', 'Scenario profit ($)', 'Scenario return (%)', 'Breakeven ($)']
            st.dataframe(summary, hide_index=True, width='stretch',
                         column_config={c: st.column_config.NumberColumn(c, format='%.2f') for c in summary.select_dtypes('number').columns if c != 'Days'})
            st.download_button('Download full report (ZIP)', downloadable_report(bundle),
                               file_name='options_scan_report.zip', mime='application/zip')
            st.download_button('Download rankings (CSV)', pd.DataFrame(rows).to_csv(index=False).encode(),
                               file_name='rankings.csv', mime='text/csv')
        with details:
            selected = st.selectbox('Inspect ticker', [r['ticker'] for r in rows])
            row = next(r for r in rows if r['ticker'] == selected)
            info = st.columns(3)
            info[0].metric('Sell call', f"${row['call1_strike']:.2f}", f"+{row['call1_otm_pct']:.2f}% above stock", delta_color='off')
            info[1].metric(f"{spec['action']} second call", f"${row['call2_strike']:.2f}", f"+{row['call2_otm_pct']:.2f}% above stock", delta_color='off')
            info[2].metric('Net premium received', f"${row['net_premium_total']:.2f}")
            st.caption(f"Expiration {row['expiration']} · {row['days_to_expiry']} days · Fees ${row['entry_fees']:.2f} · "
                       f"Maximum loss ${row['max_loss']:,.2f} (stock falls to zero)")
            x = [row['stock_price']*(.5+i*.005) for i in range(201)]
            # Include exact kinks so the chart does not smear strike boundaries.
            x = sorted(set(x+[row['call1_strike'], row['call2_strike']]))
            y = [strategy_payoff(row['stock_price'], p, row['call1_strike'], row['call2_strike'],
                                 row['net_premium_total'], row['entry_fees'], row['strategy']) for p in x]
            figure = go.Figure()
            figure.add_trace(go.Scatter(x=x, y=y, name='Stock + calls', line=dict(color='#2563eb', width=3)))
            figure.add_trace(go.Scatter(x=x, y=[shares*(p-row['stock_price']) for p in x],
                                       name='Stock alone', line=dict(color='#94a3b8', dash='dot')))
            figure.add_hline(y=0, line_color='#64748b')
            figure.add_vrect(x0=row['call1_strike'], x1=row['call2_strike'], fillcolor='#f59e0b', opacity=.10, line_width=0)
            figure.update_layout(xaxis_title='Stock price at expiration ($)', yaxis_title=f'Profit / loss per {shares} shares ($)',
                                 template='plotly_white', legend=dict(orientation='h'), margin=dict(t=30))
            st.plotly_chart(figure, width='stretch')
            cases = pd.DataFrame([s for s in scenarios if s['ticker'] == selected])
            display = cases.drop(columns=['ticker', 'expiration', 'strategy', 'shares'])
            st.dataframe(display, hide_index=True, width='stretch',
                         column_config={c: st.column_config.NumberColumn(c, format='%.2f') for c in display.columns})
            st.download_button('Download all scenarios (CSV)', pd.DataFrame(scenarios).to_csv(index=False).encode(),
                               file_name='scenarios.csv', mime='text/csv')
            st.caption(row['warnings'])
            if row['strategy'] == 'two_covered_calls':
                st.metric('Maximum expiration profit', f"${row['max_profit']:,.2f}")
                st.caption('Above the +30% strike, both 100-share blocks have their gains capped.')
        with assumptions:
            st.markdown('''**Selection:** expiration nearest the requested number of calendar days (later date on ties).
Both calls use that expiration. The overlay selects strikes at or above +15% and +20%; two covered calls use +15% and +30%.
Contracts exceeding the rounding tolerance are skipped, rather than silently substituted.

**Pricing:** the overlay uses sold call bid minus bought call ask; two covered calls receive both bids. Stock input is a reported regular-market price,
or daily close fallback, rather than an executable market-order fill. Cached quotes may be up to ten minutes old
in addition to provider delays. Option last-trade times are not bid/ask timestamps.

**Risk:** expiration payoffs assume all three legs remain intact. Early assignment can remove the shares;
the higher call does not prevent assignment. Below the stock purchase price, the net premium provides only
a small cushion. Verify corporate actions, contract deliverables, earnings, and dividends before trading.

**Costs:** two option entry commissions, no dividends, financing, taxes, stock commissions, or exit fees.
The overlay uses 100 shares, one sold call, and one bought call. Two covered calls require 200 shares and sell two calls. Returns use the initial net cash outlay,
not broker buying power. Rankings are conditional on the chosen stock move, not expected returns.''')
            metadata = pd.DataFrame(rows)[['ticker', 'stock_price_source', 'stock_timestamp', 'retrieved_utc',
                                           'call1_contract', 'call2_contract', 'call1_bid', 'call1_ask', 'call2_bid', 'call2_ask',
                                           'call1_last_trade', 'call2_last_trade', 'midpoint_premium_total', 'warnings']]
            st.dataframe(metadata, hide_index=True, width='stretch')

st.divider()
st.caption('Scenario analysis only. A positive ranking profit does not indicate that the stock will reach the assumed price.')
