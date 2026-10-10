"""Shared expiration-payoff engine for both fully covered dashboard strategies."""
import math
from datetime import date

from options_scanner import MOVES, expiration_for, html_table, valid_quote, write_csv

STRATEGIES = {
    'call_overlay': dict(label='Sell +15% / Buy +20%', shares=100, second=1.20, action='Buy'),
    'two_covered_calls': dict(label='Sell +15% / Sell +30% (200 shares)', shares=200, second=1.30, action='Sell'),
}


def selected_calls(calls, spot, second, tolerance):
    standard = [c for c in calls if c.get('contractSize') == 'REGULAR'
                and math.isfinite(float(c['strike']))]
    pair = []
    for factor in (1.15, second):
        target = spot * factor
        candidates = [c for c in standard if float(c['strike']) >= target-1e-8]
        if not candidates:
            raise ValueError(f'No standard strike at or above {target:.2f}')
        chosen = min(candidates, key=lambda c: float(c['strike']))
        if float(chosen['strike'])-target > tolerance*spot+1e-8:
            raise ValueError(f'Listed strike {chosen["strike"]} exceeds rounding tolerance')
        pair.append(chosen)
    if float(pair[1]['strike']) <= float(pair[0]['strike']):
        raise ValueError('Selected call strikes overlap')
    return pair


def strategy_payoff(spot, final, k1, k2, option_premium, fees, strategy):
    """option_premium is total dollar credit from the two 100-share contracts."""
    spec = STRATEGIES[strategy]
    second_sign = 1 if spec['action'] == 'Buy' else -1
    return (spec['shares']*(final-spot)-100*max(final-k1, 0)
            + second_sign*100*max(final-k2, 0)+option_premium-fees)


def analyze_strategy(symbol, snapshot, args, today):
    strategy = args.strategy
    spec = STRATEGIES[strategy]
    shares = spec['shares']
    spot = float(snapshot['spot'])
    if not math.isfinite(spot) or spot <= 0:
        raise ValueError('Invalid stock price')
    expiry = expiration_for(snapshot['expirations'], today, args.days, args.expiry_tolerance)
    c1, c2 = selected_calls(snapshot['calls'], spot, spec['second'], args.strike_tolerance)
    b1, a1 = valid_quote(c1)
    b2, a2 = valid_quote(c2)
    k1, k2 = float(c1['strike']), float(c2['strike'])
    premium = 100*(b1-a2 if spec['action'] == 'Buy' else b1+b2)
    if premium <= 0 or (strategy == 'call_overlay' and premium >= 100*(k2-k1)):
        raise ValueError('Nonpositive or implausible net bid/ask credit')
    fees = 2*args.commission
    capital = shares*spot-premium+fees
    if capital <= 0:
        raise ValueError('Implausible quotes: net outlay is nonpositive')
    pnl = lambda final: strategy_payoff(spot, final, k1, k2, premium, fees, strategy)
    notes = ['Bid/ask freshness unverified; check broker']
    for label, c, bid, ask in [('call 1', c1, b1, a1), ('call 2', c2, b2, a2)]:
        if (ask-bid)/((ask+bid)/2) > .50:
            notes.append(f'{label}: spread exceeds 50% of midpoint')
        oi = c.get('openInterest')
        if oi is None or not math.isfinite(float(oi)) or float(oi) < 10:
            notes.append(f'{label}: low/unknown open interest')
    midpoint = 100*((b1+a1)/2+((b2+a2)/2)*(1 if spec['action'] == 'Sell' else -1))
    rank_profit = pnl(spot*(1+args.rank_move/100))
    row = dict(ticker=symbol, strategy=strategy, strategy_label=spec['label'], shares=shares,
               stock_price=spot, expiration=expiry, days_to_expiry=(date.fromisoformat(expiry)-today).days,
               call1_action='Sell', call2_action=spec['action'], call1_strike=k1, call2_strike=k2,
               call1_otm_pct=100*(k1/spot-1), call2_otm_pct=100*(k2/spot-1),
               call1_contract=c1.get('contractSymbol',''), call2_contract=c2.get('contractSymbol',''),
               call1_bid=b1, call1_ask=a1, call2_bid=b2, call2_ask=a2,
               net_premium_total=premium, net_credit_per_share=premium/shares,
               midpoint_premium_total=midpoint, entry_fees=fees, initial_net_outlay=capital,
               breakeven=spot-(premium-fees)/shares, max_loss=capital,
               max_profit=pnl(k2) if strategy == 'two_covered_calls' else 'Unlimited',
               ranking_move_pct=args.rank_move, ranking_profit=rank_profit,
               ranking_return_pct=100*rank_profit/capital,
               stock_price_source=snapshot['source'], stock_timestamp=snapshot.get('stock_timestamp','unknown'),
               retrieved_utc=snapshot.get('retrieved_utc','SYNTHETIC'),
               call1_last_trade=str(c1.get('lastTradeDate','unknown')),
               call2_last_trade=str(c2.get('lastTradeDate','unknown')), warnings='; '.join(notes))
    cases = []
    for move in sorted(set(MOVES+(args.rank_move,))):
        final = spot*(1+move/100)
        profit = pnl(final)
        stock_profit = shares*(final-spot)
        cases.append(dict(ticker=symbol, strategy=strategy, shares=shares, expiration=expiry,
                          stock_move_pct=move, final_stock_price=final, strategy_profit=profit,
                          strategy_return_pct=100*profit/capital, stock_only_profit=stock_profit,
                          advantage_vs_stock=profit-stock_profit))
        row[f'profit_at_{move:+g}pct'] = profit
    return row, cases


def synthetic_strategy(symbol, today, args, spot=100, first_bid=3):
    spec = STRATEGIES[args.strategy]
    from datetime import timedelta
    return dict(spot=spot, expirations=[(today+timedelta(days=args.days)).isoformat()],
                source='SYNTHETIC DEMO, NOT MARKET DATA',
                calls=[dict(strike=spot*1.15,bid=first_bid,ask=first_bid+.2,
                            contractSymbol=f'{symbol}_DEMO_CALL1',contractSize='REGULAR',openInterest=100),
                       dict(strike=spot*spec['second'],bid=.8,ask=1,
                            contractSymbol=f'{symbol}_DEMO_CALL2',contractSize='REGULAR',openInterest=100)])


def save_strategy_report(directory, rows, scenarios, errors, args):
    directory.mkdir(parents=True,exist_ok=True)
    write_csv(directory/'rankings.csv', rows)
    write_csv(directory/'scenarios.csv', scenarios)
    write_csv(directory/'errors.csv', errors)
    spec = STRATEGIES[args.strategy]
    fields = ['ticker','shares','stock_price','expiration','call1_action','call1_strike',
              'call2_action','call2_strike','net_premium_total','initial_net_outlay','ranking_profit','ranking_return_pct']
    body = html_table(rows,fields)
    import html
    for row in rows:
        body += '<h2>'+html.escape(row['ticker'])+'</h2>'
        body += html_table([s for s in scenarios if s['ticker']==row['ticker']],
                           ['stock_move_pct','final_stock_price','strategy_profit','strategy_return_pct','stock_only_profit'])
    if errors:
        body += '<h2>Skipped tickers</h2>'+html_table(errors,['ticker','error'])
    demo = 'SYNTHETIC DEMO — ' if args.demo else ''
    report = f'''<!doctype html><html lang="en"><meta charset="utf-8"><title>Options scan</title>
<style>body{{font:15px system-ui;margin:32px}}table{{border-collapse:collapse}}td,th{{padding:10px;border:1px solid #dde3ed;text-align:right}}.scroll{{overflow:auto}}</style>
<h1>{demo}{spec['label']}</h1><p>Profits per {spec['shares']} shares. Ranking scenario {args.rank_move:+g}%.
Ranking by {args.rank_by}. Conditional expiration payoffs, not expected returns. Bid/ask estimates may be stale.
Two entry option fees; no taxes, financing, dividends or exit fees. Early assignment may alter exposure.</p>{body}</html>'''
    (directory/'report.html').write_text(report,encoding='utf-8')
