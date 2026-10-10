# Bullish Options Scanner — Streamlit dashboard

Buy 100 shares, sell one call at or above +15%, and buy one call at or above +20%,
with the same expiration nearest 14 calendar days away.

## Deploy on Streamlit Community Cloud

1. Extract this package and upload its contents to a GitHub repository. Keep
   `app.py`, `options_scanner.py`, and `requirements.txt` together at the repository root.
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
- First listed strikes at or above +15% and +20%; actual percentages shown.
- Bid for sold call, ask for bought call, two entry commissions.
- Default ranking by percentage return at a +15% stock move; change the
  ranking scenario or rank by dollar profit per 100 shares.
- Sorted ranking table, ticker-specific payoff chart versus shares alone,
  scenario table, quote metadata, and CSV/ZIP downloads.
- Successful market data cached for 10 minutes; rerunning chart selections
  does not refetch quotes. Displayed scan settings remain tied to that scan.
- Invalid quotes and unusable contracts appear under skipped tickers.
- Scan stops requesting more symbols after a Yahoo rate-limit response.

## Calculation

For purchase price S0, expiration price ST, short strike K1, long strike K2,
net premium per share C, and total entry fees F:

`profit = 100 * (ST - S0 - max(ST-K1, 0) + max(ST-K2, 0) + C) - F`

`initial net outlay = 100 * (S0-C) + F`

`scenario return = profit / initial net outlay`

Gains pause between K1 and K2. Above K2 they resume, but lag stock alone by
`100 * (K2-K1-C) + F`. Downside breakeven is `S0-C+F/100`.

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

Dashboard tests use Streamlit AppTest and synthetic or mocked data. Live Yahoo
retrieval in the original environment returned a rate-limit response; the live
data route has not been verified end to end. Test in your own environment before
relying on results.
