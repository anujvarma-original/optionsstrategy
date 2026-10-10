# Bullish Options Scanner — Streamlit dashboard

Choose either strategy with the same expiration nearest 14 calendar days away:

| Strategy | Stock position | Call 1 | Call 2 |
| --- | --- | --- | --- |
| Original call overlay | 100 shares | Sell at or above +15% | Buy at or above +20% |
| Two covered calls | 200 shares | Sell at or above +15% | Sell at or above +30% |

Two short calls require 200 shares to be fully covered. With only 100 shares,
the second short call would be uncovered and could create unlimited upside risk.
Both calls use the same expiration, not successive dates. These are two alternative
positions; selecting one does not add two calls to the original overlay.

## Deploy on Streamlit Community Cloud

1. Extract this package and upload its contents to a GitHub repository. Keep
   `app.py`, `strategies.py`, `options_scanner.py`, and `requirements.txt` together at the repository root.
   Include `.streamlit/config.toml` for the theme.
2. Open https://share.streamlit.io and choose **Create app**.
3. Select your GitHub repository, branch, and entrypoint **app.py**.
4. In advanced settings select Python **3.12**, then deploy.

No API key or secrets are required for Yahoo data. Deployment requires your own
GitHub and Streamlit accounts. The delivered package is ready to deploy; it is
not already hosted. Review the app's sharing settings when deploying.

Official deployment reference:
https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy

## Run locally

```bash
python -m pip install -r requirements.txt
streamlit run app.py
```

Enter comma-, space-, or newline-separated tickers and click **Scan tickers**.
Enable **Demo mode** for synthetic data without Yahoo requests. No simulated
quotes are substituted silently when live data fails.

## Dashboard

- Up to 25 symbols per scan; target expiry defaults to 14 calendar days.
- First listed strikes at or above +15% and +20% for the original overlay;
  +15% and +30% for two covered calls. Actual percentages shown.
- Bid for each sold call, ask for the bought call, two entry commissions.
- Default ranking by percentage return at a +15% stock move; change the
  ranking scenario or rank by dollar profit per strategy position. The overlay
  uses 100 shares, while the two-call position uses 200; use percentage return
  when comparing results with different capital requirements.
- Sorted ranking table, ticker-specific payoff chart versus shares alone,
  scenario table, quote metadata, and CSV/ZIP downloads.
- Successful market data cached for 10 minutes; rerunning chart selections
  does not refetch quotes. Displayed scan settings remain tied to that scan.
- Invalid quotes and unusable contracts appear under skipped tickers.
- Scan stops requesting more symbols after a Yahoo rate-limit response.

## Original overlay calculation

For purchase price S0, expiration price ST, short strike K1, long strike K2,
net premium per share C, and total entry fees F:

`profit = 100 * (ST - S0 - max(ST-K1, 0) + max(ST-K2, 0) + C) - F`

`initial net outlay = 100 * (S0-C) + F`

`scenario return = profit / initial net outlay`

Gains pause between K1 and K2. Above K2 they resume, but lag stock alone by
`100 * (K2-K1-C) + F`. Downside breakeven is `S0-C+F/100`.

## Two covered calls calculation

For 200 shares, one short call at K1 (+15%), one at K2 (+30%), total dollar
premium P = `100 * (call1 bid + call2 bid)`, and total entry fees F:

`profit = 200*(ST-S0) - 100*max(ST-K1,0) - 100*max(ST-K2,0) + P - F`

`initial net outlay = 200*S0 - P + F`

`breakeven = S0 - (P-F)/200`

`maximum profit = 100*(K1-S0) + 100*(K2-S0) + P - F`

Below K1, gains accrue on 200 shares; between K1 and K2, gains accrue on
100 shares; at or above K2 profit is capped. Maximum loss is the initial net
outlay if the stock falls to zero. The net_credit_per_share output is the total
premium divided by the actual share count (200 here). Both calls must have
usable positive bids: a +30% call two weeks out may have no bid and be skipped.

## Data limitations

These are conditional expiration profits, not probability-weighted expected
profits, price predictions, annualized yields, or order recommendations.
Stock input is a reported regular-market price or daily close, not an actual
market fill. Yahoo bid/ask freshness cannot be verified; lastTradeDate refers
to the last transaction, not the quote time. Cache age is additional to provider
delay. Quotes may be rate-limited or unavailable, particularly far out of the
money with two weeks remaining. No live-data availability guarantee on shared
cloud hosting. A broker or licensed options provider is the next upgrade if
reliable live quotes are required.

Only USD standard contracts marked REGULAR are screened; confirm authoritative
OCC deliverables with your broker. Payoffs assume all legs remain intact until
expiration; early assignment may change exposure. Purchased calls do not prevent
short-call assignment. Substantial stock downside remains. No taxes, dividends,
financing, stock commissions, or closing/assignment fees are included.

## Verification

```bash
python options_scanner.py --self-test
python test_dashboard.py
```

Dashboard tests cover both strategies, stock coverage, capped payoff, fees,
CSV/report rendering, and validation using Streamlit AppTest and mocked data. Live Yahoo
retrieval in the original environment returned a rate-limit response; the live
data route has not been verified end to end. Test in your own environment before
relying on results.
