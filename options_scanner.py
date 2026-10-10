#!/usr/bin/env python3
"""Scan long stock + short +15% call + long +20% call, same expiration.

Python 3.10+. Install live-data dependency: python -m pip install -U yfinance
Run: python options_scanner.py NVDA AMD MSFT --days 14 --output results
Or:  python options_scanner.py --tickers-file tickers.txt
Test without dependencies/network: python options_scanner.py --self-test
Preview synthetic data: python options_scanner.py --demo --output demo_results

Ticker file: whitespace/comma-separated symbols; # comments allowed.
Default ranking: expiration profit / initial net cash outlay at a +15% move.
--rank-move changes that scenario; --rank-by profit ranks dollars per 100 shares.
This is scenario analysis, NOT expected return, a price forecast, or a trade order.

Expiration: closest available date to today + 14 calendar days, prefer later
date on ties; reject deviations over 4 days. Strikes: first listed at or above
1.15*spot and 1.20*spot; reject deviations exceeding 3% of spot. No substitution
of another contract just because the selected contract lacks a usable quote.
Standard 100-share USD equity contracts only; Yahoo REGULAR contractSize filter
is a screening aid, not authoritative verification of OCC deliverables.

Live data: Yahoo via yfinance, potentially delayed/stale. Uses last reported
regular-market price (chain underlying where available, daily close fallback).
Records retrieval time and stock timestamp if available. Yahoo option lastTradeDate
is NOT the bid/ask timestamp; freshness of bid/ask cannot be verified here.
Confirm stock price, quotes, earnings, dividends, and deliverables with broker.
Entry premium: sell bid minus buy ask; midpoint shown for comparison only.
Reject missing, zero, crossed or implausible bid/ask and nonpositive net credit.
No fill guarantee. Default entry commission $0.65 per option contract (2 legs).
No stock commission, financing, dividends, taxes, or closing/assignment fees.
Payoffs assume positions remain intact until expiry, despite possible early
assignment. Downside remains stock ownership risk less the small net credit.
"""

import argparse
import csv
import html
import math
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

MOVES = (-30, -20, -10, 0, 5, 10, 15, 20, 25, 30, 50)


def expiration_for(expirations, today, days=14, tolerance=4):
    target = today + timedelta(days=days)
    available = [date.fromisoformat(e) for e in expirations]
    available = [e for e in available if e > today]
    if not available:
        raise ValueError("No future option expirations")
    chosen = min(available, key=lambda e: (abs((e-target).days), -e.toordinal()))
    if abs((chosen-target).days) > tolerance:
        raise ValueError(f"Closest expiry {chosen} is outside +/-{tolerance} days of {target}")
    return chosen.isoformat()


def select_calls(calls, spot, tolerance=0.03):
    standard = [c for c in calls if c.get('contractSize') == 'REGULAR'
                and math.isfinite(float(c['strike']))]
    selected = []
    for factor in (1.15, 1.20):
        target = spot * factor
        eligible = [c for c in standard if float(c['strike']) >= target - 1e-8]
        if not eligible:
            raise ValueError(f"No standard strike at or above {target:.2f}")
        call = min(eligible, key=lambda c: float(c['strike']))
        if float(call['strike']) - target > tolerance * spot + 1e-8:
            raise ValueError(f"Listed strike {call['strike']} too far from target {target:.2f}")
        selected.append(call)
    if float(selected[1]['strike']) <= float(selected[0]['strike']):
        raise ValueError("Selected strikes overlap; no distinct +15%/+20% pair")
    return selected


def valid_quote(call):
    bid, ask = float(call.get('bid', math.nan)), float(call.get('ask', math.nan))
    if not all(math.isfinite(x) and x > 0 for x in (bid, ask)) or ask < bid:
        raise ValueError(f"Missing, zero or crossed bid/ask: {call.get('contractSymbol')}")
    return bid, ask


def payoff(spot, final, short_strike, long_strike, credit, fee=1.30):
    return 100 * (final - spot - max(final-short_strike, 0)
                  + max(final-long_strike, 0) + credit) - fee


def analyze(symbol, snapshot, args, today):
    spot = float(snapshot['spot'])
    if not math.isfinite(spot) or spot <= 0:
        raise ValueError("Invalid stock price")
    expiry = expiration_for(snapshot['expirations'], today, args.days, args.expiry_tolerance)
    short, long = select_calls(snapshot['calls'], spot, args.strike_tolerance)
    sb, sa = valid_quote(short)
    lb, la = valid_quote(long)
    ks, kl = float(short['strike']), float(long['strike'])
    credit = sb-la
    if not 0 < credit < kl-ks:
        raise ValueError("Bid/ask net credit must be positive and below strike gap")
    fee = 2 * args.commission
    capital = 100 * (spot-credit) + fee
    notes = ["Bid/ask freshness unverified; check broker"]
    for label, call, bid, ask in [('sell', short, sb, sa), ('buy', long, lb, la)]:
        if (ask-bid)/((ask+bid)/2) > 0.50:
            notes.append(f"{label}: bid/ask spread exceeds 50% of midpoint")
        oi = call.get('openInterest')
        if oi is None or not math.isfinite(float(oi)) or float(oi) < 10:
            notes.append(f"{label}: low/unknown open interest")
    rank_final = spot * (1 + args.rank_move/100)
    rank_profit = payoff(spot, rank_final, ks, kl, credit, fee)
    row = dict(ticker=symbol, stock_price=spot, stock_price_source=snapshot['source'],
               stock_timestamp=snapshot.get('stock_timestamp', 'unknown'),
               retrieved_utc=snapshot.get('retrieved_utc', 'SYNTHETIC'),
               expiration=expiry, days_to_expiry=(date.fromisoformat(expiry)-today).days,
               sell_contract=short.get('contractSymbol', ''), buy_contract=long.get('contractSymbol', ''),
               sell_strike=ks, buy_strike=kl,
               sell_otm_pct=100*(ks/spot-1), buy_otm_pct=100*(kl/spot-1),
               sell_bid=sb, sell_ask=sa, buy_bid=lb, buy_ask=la,
               sell_last_trade=str(short.get('lastTradeDate', 'unknown')),
               buy_last_trade=str(long.get('lastTradeDate', 'unknown')),
               net_credit_per_share=credit, midpoint_credit_per_share=(sb+sa-lb-la)/2,
               entry_fees=fee, initial_net_outlay=capital,
               breakeven=spot-credit+fee/100, max_loss=capital,
               plateau_profit=payoff(spot, ks, ks, kl, credit, fee),
               lag_vs_stock_above_buy_strike=100*(kl-ks-credit)+fee,
               ranking_move_pct=args.rank_move, ranking_profit=rank_profit,
               ranking_return_pct=100*rank_profit/capital, warnings='; '.join(notes))
    scenarios = []
    for move in sorted(set(MOVES + (args.rank_move,))):
        final = spot*(1+move/100)
        pnl = payoff(spot, final, ks, kl, credit, fee)
        stock_pnl = 100*(final-spot)
        scenarios.append(dict(ticker=symbol, expiration=expiry, stock_move_pct=move,
                              final_stock_price=final, strategy_profit=pnl,
                              strategy_return_pct=100*pnl/capital,
                              stock_only_profit=stock_pnl,
                              advantage_vs_stock=pnl-stock_pnl))
        row[f'profit_at_{move:+g}pct'] = pnl
    return row, scenarios


def fetch(symbol, args, today):
    import yfinance as yf
    ticker = yf.Ticker(symbol)
    expirations = ticker.options
    expiry = expiration_for(expirations, today, args.days, args.expiry_tolerance)
    chain = ticker.option_chain(expiry)
    underlying = getattr(chain, 'underlying', None) or {}
    currency = underlying.get('currency')
    if currency is None:
        currency = ticker.fast_info['currency']
    if currency != 'USD':
        raise ValueError(f"Only USD stocks supported; reported currency {currency}")
    spot = underlying.get('regularMarketPrice')
    timestamp = underlying.get('regularMarketTime')
    source = 'Yahoo regularMarketPrice (not executable stock ask)'
    stamp = datetime.fromtimestamp(timestamp, timezone.utc).isoformat() if timestamp else 'unknown'
    if spot is None or not math.isfinite(float(spot)) or float(spot) <= 0:
        history = ticker.history(period='5d', auto_adjust=False)
        closes = history['Close'].dropna()
        if closes.empty:
            raise ValueError("No stock price available")
        spot = float(closes.iloc[-1])
        stamp = str(closes.index[-1])
        source = 'Yahoo daily Close fallback (bar date, not tick time)'
    return dict(spot=spot, expirations=expirations, calls=chain.calls.to_dict('records'),
                source=source, stock_timestamp=stamp,
                retrieved_utc=datetime.now(timezone.utc).isoformat())


def synthetic(symbol, today, days, spot=100, credit=2):
    expiry = (today+timedelta(days=days)).isoformat()
    return dict(spot=spot, expirations=[expiry], source='SYNTHETIC DEMO, NOT MARKET DATA',
                calls=[dict(strike=spot*1.15, bid=credit+1, ask=credit+1.2,
                            contractSymbol=f'{symbol}_DEMO_SELL', contractSize='REGULAR', openInterest=100),
                       dict(strike=spot*1.20, bid=.8, ask=1,
                            contractSymbol=f'{symbol}_DEMO_BUY', contractSize='REGULAR', openInterest=100)])


def write_csv(path, rows):
    if not rows:
        path.write_text('', encoding='utf-8')
        return
    with path.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def html_table(rows, fields):
    def value(v):
        return f'{v:,.2f}' if isinstance(v, float) else str(v)
    head = ''.join(f'<th>{html.escape(f)}</th>' for f in fields)
    body = ''.join('<tr>'+''.join(f'<td>{html.escape(value(r[f]))}</td>' for f in fields)+'</tr>' for r in rows)
    return f'<div class="scroll"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def save_report(directory, rows, scenarios, errors, args):
    directory.mkdir(parents=True, exist_ok=True)
    write_csv(directory/'rankings.csv', rows)
    write_csv(directory/'scenarios.csv', scenarios)
    write_csv(directory/'errors.csv', errors)
    fields = ['ticker', 'stock_price', 'expiration', 'days_to_expiry', 'sell_strike',
              'buy_strike', 'net_credit_per_share', 'initial_net_outlay', 'ranking_profit',
              'ranking_return_pct', 'breakeven']
    body = html_table(rows, fields)
    for row in rows:
        body += f'<h2>{html.escape(row["ticker"])}</h2><p>{html.escape(row["warnings"])}</p>'
        body += html_table([s for s in scenarios if s['ticker'] == row['ticker']],
                           ['stock_move_pct', 'final_stock_price', 'strategy_profit',
                            'strategy_return_pct', 'stock_only_profit', 'advantage_vs_stock'])
    if errors:
        body += '<h2>Skipped tickers</h2>'+html_table(errors, ['ticker', 'error'])
    title = 'SYNTHETIC DEMO — ' if args.demo else ''
    report = f'''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Options strategy scanner</title>
<style>body{{font:15px system-ui;margin:32px;color:#142238;background:#f7f9fc}}h1{{font-size:26px}}
table{{border-collapse:collapse;background:white;width:100%}}td,th{{padding:10px;border-bottom:1px solid #dde3ed;text-align:right;white-space:nowrap}}
th{{background:#e6eefb}}.scroll{{overflow:auto;margin:16px 0}}p{{max-width:1000px;line-height:1.6}}</style>
<h1>{title}Stock + sell +15% call + buy +20% call</h1>
<p>Ranked by {args.rank_by} at a {args.rank_move:+g}% stock move at expiration. Dollar profits are per 100 shares.
Returns use initial net cash outlay. These are conditional payoffs, not expected profits or forecasts.
Selected expiration is closest to {args.days} calendar days out. Strikes round upward to available strikes.</p>
<p>Sell bid / buy ask; entry fees ${2*args.commission:.2f}. Quotes may be stale and fills are not guaranteed.
Stock input is a reported price, not a market-order fill. Early assignment may alter the position.
No dividends, taxes, financing, stock commissions, or exit fees. Substantial stock downside remains.</p>{body}</html>'''
    (directory/'report.html').write_text(report, encoding='utf-8')


def self_test():
    from tempfile import TemporaryDirectory
    today = date(2026, 10, 10)
    args = parse_args(['--demo'])
    snapshot = synthetic('TEST', today, 14)
    row, scenarios = analyze('TEST', snapshot, args, today)
    assert math.isclose(row['plateau_profit'], 1698.70)
    assert math.isclose(row['breakeven'], 98.013)
    assert math.isclose(row['lag_vs_stock_above_buy_strike'], 301.30)
    assert math.isclose(payoff(100, 0, 115, 120, 2), -9801.30)
    assert math.isclose(payoff(100, 130, 115, 120, 2), 2698.70)
    assert math.isclose(payoff(100, 118, 115, 120, 2), row['plateau_profit'])
    assert expiration_for(['2026-10-23', '2026-10-25'], today) == '2026-10-25'
    assert expiration_for(['2026-10-23'], today) == '2026-10-23'
    def rejects(fn):
        try:
            fn()
        except ValueError:
            return
        raise AssertionError('Invalid input accepted')
    rejects(lambda: expiration_for(['2026-11-20'], today))
    rejects(lambda: valid_quote(dict(bid=0, ask=1)))
    rejects(lambda: valid_quote(dict(bid=2, ask=1)))
    rejects(lambda: valid_quote(dict(bid=math.nan, ask=1)))
    rejects(lambda: select_calls([dict(strike=130, contractSize='REGULAR')], 100))
    rejects(lambda: select_calls([dict(strike=115, contractSize='MINI')], 100))
    rounded = [dict(strike=k, contractSize='REGULAR') for k in (115, 120, 125)]
    short, long = select_calls(rounded, 102)
    assert short['strike'] == 120 and long['strike'] == 125
    snapshot['calls'][0]['bid'] = .5
    rejects(lambda: analyze('TEST', snapshot, args, today))
    with TemporaryDirectory() as folder:
        save_report(Path(folder), [row], scenarios, [{'ticker': 'BAD', 'error': '<missing>'}], args)
        assert '&lt;missing&gt;' in (Path(folder)/'report.html').read_text()
        assert len(list(csv.DictReader((Path(folder)/'scenarios.csv').open()))) == len(scenarios)
    print('PASS: payoff, fees, expiry selection, strike rounding, quote validation, CSV/HTML output')


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('tickers', nargs='*', help='Space- or comma-separated Yahoo symbols')
    parser.add_argument('--tickers-file', type=Path)
    parser.add_argument('--days', type=int, default=14)
    parser.add_argument('--expiry-tolerance', type=int, default=4)
    parser.add_argument('--strike-tolerance', type=float, default=.03, help='Max rounding deviation / stock price')
    parser.add_argument('--rank-move', type=float, default=15, help='Assumed stock move in percent')
    parser.add_argument('--rank-by', choices=['return', 'profit'], default='return')
    parser.add_argument('--commission', type=float, default=.65, help='Entry fee per option contract')
    parser.add_argument('--output', type=Path, default=Path('options_results'))
    parser.add_argument('--demo', action='store_true')
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args(argv)
    if (args.days < 1 or args.expiry_tolerance < 0 or
            not math.isfinite(args.strike_tolerance) or args.strike_tolerance < 0 or
            not math.isfinite(args.commission) or args.commission < 0 or
            not math.isfinite(args.rank_move) or args.rank_move < -100):
        parser.error('Invalid days, tolerance, commission, or scenario move')
    return args


def main(argv=None):
    args = parse_args(argv)
    if args.self_test:
        self_test()
        return 0
    raw = ' '.join(args.tickers)
    if args.tickers_file:
        raw += ' '+ ' '.join(line.split('#')[0] for line in args.tickers_file.read_text().splitlines())
    symbols = list(dict.fromkeys(x.upper() for x in re.split(r'[\s,]+', raw.strip()) if x))
    if args.demo and not symbols:
        symbols = ['DEMO_A', 'DEMO_B', 'DEMO_C']
    if not symbols:
        print('Provide tickers, --tickers-file, or --demo. Use --help for examples.', file=sys.stderr)
        return 2
    if not args.demo:
        try:
            import yfinance  # noqa: F401
        except ImportError:
            print('Install dependency: python -m pip install -U yfinance', file=sys.stderr)
            return 2
    today = datetime.now(ZoneInfo('America/New_York')).date()
    rows, scenarios, errors = [], [], []
    print('SYNTHETIC DEMO — NOT MARKET DATA' if args.demo else 'Yahoo quotes: freshness/fills unverified')
    for index, symbol in enumerate(symbols):
        print(f'[{index+1}/{len(symbols)}] {symbol}', flush=True)
        try:
            snapshot = synthetic(symbol, today, args.days, 100+index*25, 1+index*.5) if args.demo else fetch(symbol, args, today)
            row, cases = analyze(symbol, snapshot, args, today)
            rows.append(row)
            scenarios.extend(cases)
        except Exception as exc:
            errors.append(dict(ticker=symbol, error=f'{type(exc).__name__}: {exc}'))
            print(f'  Skipped: {exc}', file=sys.stderr)
    key = 'ranking_return_pct' if args.rank_by == 'return' else 'ranking_profit'
    rows.sort(key=lambda r: r[key], reverse=True)
    order = {r['ticker']: i for i, r in enumerate(rows)}
    scenarios.sort(key=lambda s: (order[s['ticker']], s['stock_move_pct']))
    save_report(args.output, rows, scenarios, errors, args)
    print(f'\nRanking at {args.rank_move:+g}% move; profits per 100 shares:')
    print(f'{"Ticker":<12} {"Expiry":<12} {"Sell":>9} {"Buy":>9} {"Credit/sh":>10} {"Profit":>12} {"Return":>9}')
    for r in rows:
        print(f'{r["ticker"]:<12} {r["expiration"]:<12} {r["sell_strike"]:9.2f} {r["buy_strike"]:9.2f} '
              f'{r["net_credit_per_share"]:10.2f} {r["ranking_profit"]:12.2f} {r["ranking_return_pct"]:8.2f}%')
    print(f'\nSaved report.html, rankings.csv, scenarios.csv, errors.csv in {args.output.resolve()}')
    return 0 if rows else 1


if __name__ == '__main__':
    raise SystemExit(main())
