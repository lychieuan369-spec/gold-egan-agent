# Gold Price Prediction Agent

Automated gold price signal bot using RSI(14), EMA(9), and WMA(45) on RSI.
Checks CME Gold Futures (GC=F) on 4h and 1h timeframes every hour and sends
a Telegram alert when a BUY or SELL signal is detected.

## What it does

1. Fetches GC=F (Gold Futures) data via `yfinance`
2. Resamples 1h candles to 4h using pandas OHLCV aggregation
3. Calculates RSI(14) with Wilder's smoothing method
4. Calculates EMA(9) on RSI and WMA(45) on RSI
5. Detects BUY/SELL/NEUTRAL based on oversold/overbought thresholds and crossovers
6. Sends HTML-formatted Telegram message if either timeframe is non-NEUTRAL

## Signal Logic

| Condition | Points |
|-----------|--------|
| RSI ≤ 25 (oversold) | +2 BUY |
| RSI ≥ 75 (overbought) | +2 SELL |
| RSI ≤ 35 | +1 BUY |
| RSI ≥ 65 | +1 SELL |
| EMA(9) RSI > WMA(45) RSI | +1 BUY |
| EMA(9) RSI < WMA(45) RSI | +1 SELL |
| RSI trending up (3 bars) | +1 BUY |
| RSI trending down (3 bars) | +1 SELL |

Score ≥ 3 triggers BUY or SELL signal.

## Risk Management

- Stop Loss: ±1.5%
- Take Profit 1: ±1.5%
- Take Profit 2: ±3.0%

## Setup

### 1. GitHub Secrets

In your repository → Settings → Secrets → Actions, add:

| Secret | Value |
|--------|-------|
| `BOT_TOKEN` | Your Telegram bot token (from @BotFather) |
| `CHAT_ID` | Your Telegram chat/channel ID |

### 2. Enable GitHub Actions

The workflow runs automatically every hour via cron.
Use "Run workflow" in the Actions tab to trigger manually.

## Run Locally

```bash
# Install dependencies
pip install -r requirements.txt

# Text output (human-readable)
python analyze_gold.py --timeframe 4h --mode text
python analyze_gold.py --timeframe 1h --mode text

# JSON output (for scripting)
python analyze_gold.py --timeframe 4h --mode json

# Full alert (requires BOT_TOKEN and CHAT_ID in env)
BOT_TOKEN=xxx CHAT_ID=yyy python telegram_alert_gold.py
```

## File Structure

```
gold_egan_agent/
├── analyze_gold.py          # Core analysis: fetch, indicators, signal detection
├── telegram_alert_gold.py   # Entry point: checks signals, sends alert
├── requirements.txt
├── README.md
└── .github/
    └── workflows/
        └── gold-alert.yml   # GitHub Actions hourly cron
```

## Data Source

- **Ticker:** `GC=F` — COMEX Gold Futures (CME Group)
- **Provider:** yfinance (Yahoo Finance)
- **1h candles:** up to 60 days history
- **4h candles:** resampled from 1h (up to 120 days)

> **Disclaimer:** For informational and educational purposes only. Not financial advice.
