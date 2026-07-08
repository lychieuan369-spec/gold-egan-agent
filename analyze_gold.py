#!/usr/bin/env python3
"""
Gold Price Prediction Agent — analyze_gold.py
Uses yfinance GC=F (Gold Futures CME) with RSI(14), EMA(9) on RSI, WMA(45) on RSI.
Supports --mode json (clean JSON only) and --mode text (human-readable).
"""

import argparse
import io
import json
import sys
import time
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# Force UTF-8 output on Windows (avoids UnicodeEncodeError on emoji in console)
if not isinstance(sys.stdout, io.TextIOWrapper) or sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if not isinstance(sys.stderr, io.TextIOWrapper) or sys.stderr.encoding.lower() != "utf-8":
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


def fetch_gold_data(timeframe: str, n_candles: int = 200) -> pd.DataFrame:
    """
    Fetch gold OHLCV data from yfinance (GC=F).
    timeframe: '1h' or '4h'
    For 4h, fetches 1h data and resamples.
    """
    try:
        import yfinance as yf
    except ImportError:
        raise ImportError("yfinance is required: pip install yfinance")

    ticker = "GC=F"

    def _download_with_retry(period, interval, label, retries=3, delays=(3, 6)):
        last_err = None
        for attempt in range(retries):
            try:
                df = yf.download(ticker, period=period, interval=interval,
                                 progress=False, auto_adjust=True)
                if df is not None and not df.empty:
                    return df
                last_err = f"No {label} data returned from yfinance for GC=F"
            except Exception as e:
                last_err = f"yfinance download failed ({label}): {e}"
            if attempt < retries - 1:
                time.sleep(delays[min(attempt, len(delays) - 1)])
        raise RuntimeError(last_err)

    if timeframe == "1h":
        # yfinance 1h data, up to 60d
        period = "60d"
        interval = "1h"
        df = _download_with_retry(period, interval, "1h")

        df = _normalize_columns(df)
        df = df.dropna(subset=["close"])
        if len(df) < 50:
            raise RuntimeError(f"Insufficient 1h candles: {len(df)}")
        return df.tail(n_candles)

    elif timeframe == "4h":
        # Fetch 1h over 120d, then resample to 4h
        period = "120d"
        interval = "1h"
        df = _download_with_retry(period, interval, "1h (4h resample)")

        df = _normalize_columns(df)
        df = df.dropna(subset=["close"])

        # Resample to 4h OHLCV
        df_4h = df.resample("4h").agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
        ).dropna(subset=["close"])

        if len(df_4h) < 50:
            raise RuntimeError(f"Insufficient 4h candles after resample: {len(df_4h)}")
        return df_4h.tail(n_candles)

    else:
        raise ValueError(f"Unsupported timeframe: {timeframe}. Use '1h' or '4h'.")


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize column names to lowercase. Handles MultiIndex from yfinance."""
    if isinstance(df.columns, pd.MultiIndex):
        # yfinance sometimes returns MultiIndex (col, ticker)
        df.columns = [col[0].lower() if isinstance(col, tuple) else col.lower()
                      for col in df.columns]
    else:
        df.columns = [c.lower() for c in df.columns]

    # Rename standard yfinance columns if needed
    rename_map = {"adj close": "close"}
    df = df.rename(columns=rename_map)
    return df


def calculate_rsi(closes: np.ndarray, period: int = 14) -> np.ndarray:
    """
    Wilder's RSI calculation.
    Returns array of same length as input (NaN for initial values).
    """
    closes = np.array(closes, dtype=float)
    n = len(closes)
    rsi = np.full(n, np.nan)

    if n < period + 1:
        return rsi

    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    # Initial averages (simple mean for seed)
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])

    # First RSI value at index `period`
    if avg_loss == 0:
        rsi[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        rsi[period] = 100.0 - (100.0 / (1.0 + rs))

    # Wilder smoothing for remaining values
    for i in range(period + 1, n):
        avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
        if avg_loss == 0:
            rsi[i] = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi[i] = 100.0 - (100.0 / (1.0 + rs))

    return rsi


def calculate_ema(data: np.ndarray, period: int) -> np.ndarray:
    """
    Exponential Moving Average.
    Returns array of same length; NaN for insufficient data.
    """
    data = np.array(data, dtype=float)
    n = len(data)
    ema = np.full(n, np.nan)

    # Find first valid (non-NaN) index
    valid_idx = np.where(~np.isnan(data))[0]
    if len(valid_idx) < period:
        return ema

    start = valid_idx[period - 1]
    # Seed with simple mean of first `period` valid values
    seed_values = data[valid_idx[:period]]
    ema[start] = np.mean(seed_values)

    k = 2.0 / (period + 1)
    for i in range(start + 1, n):
        if np.isnan(data[i]):
            ema[i] = np.nan
        else:
            ema[i] = data[i] * k + ema[i - 1] * (1.0 - k)

    return ema


def calculate_wma(data: np.ndarray, period: int) -> np.ndarray:
    """
    Weighted Moving Average (linearly weighted).
    Returns array of same length; NaN for insufficient data.
    """
    data = np.array(data, dtype=float)
    n = len(data)
    wma = np.full(n, np.nan)
    weights = np.arange(1, period + 1, dtype=float)
    weight_sum = weights.sum()

    for i in range(period - 1, n):
        window = data[i - period + 1: i + 1]
        if np.any(np.isnan(window)):
            continue
        wma[i] = np.dot(window, weights) / weight_sum

    return wma


def detect_signal(df: pd.DataFrame) -> dict:
    """
    Calculates RSI(14), EMA(9) on RSI, WMA(45) on RSI.
    Returns signal dict with: signal, strength, conditions, price, rsi, ema_rsi, wma_rsi, sl, tp1, tp2.
    """
    closes = df["close"].values.astype(float)
    current_price = float(closes[-1])

    rsi_arr = calculate_rsi(closes, period=14)
    ema_rsi_arr = calculate_ema(rsi_arr, period=9)
    wma_rsi_arr = calculate_wma(rsi_arr, period=45)

    # Latest valid values
    current_rsi = _last_valid(rsi_arr)
    current_ema_rsi = _last_valid(ema_rsi_arr)
    current_wma_rsi = _last_valid(wma_rsi_arr)

    if any(v is None for v in [current_rsi, current_ema_rsi, current_wma_rsi]):
        return {
            "signal": "NEUTRAL",
            "strength": 0,
            "conditions": ["Insufficient data for indicators"],
            "price": current_price,
            "rsi": current_rsi,
            "ema_rsi": current_ema_rsi,
            "wma_rsi": current_wma_rsi,
            "sl": None,
            "tp1": None,
            "tp2": None,
        }

    # Signal logic
    conditions_met = []
    buy_score = 0
    sell_score = 0

    # RSI oversold/overbought
    if current_rsi <= 25:
        conditions_met.append(f"RSI oversold ({current_rsi:.1f} ≤ 25)")
        buy_score += 2
    elif current_rsi >= 75:
        conditions_met.append(f"RSI overbought ({current_rsi:.1f} ≥ 75)")
        sell_score += 2
    elif current_rsi <= 35:
        conditions_met.append(f"RSI low ({current_rsi:.1f} ≤ 35)")
        buy_score += 1
    elif current_rsi >= 65:
        conditions_met.append(f"RSI high ({current_rsi:.1f} ≥ 65)")
        sell_score += 1

    # EMA(9) on RSI vs WMA(45) on RSI crossover/position
    if current_ema_rsi > current_wma_rsi:
        conditions_met.append(
            f"EMA(9) RSI above WMA(45) RSI ({current_ema_rsi:.1f} > {current_wma_rsi:.1f})"
        )
        buy_score += 1
    else:
        conditions_met.append(
            f"EMA(9) RSI below WMA(45) RSI ({current_ema_rsi:.1f} < {current_wma_rsi:.1f})"
        )
        sell_score += 1

    # RSI trending up (last 3 values)
    rsi_valid = rsi_arr[~np.isnan(rsi_arr)]
    if len(rsi_valid) >= 3:
        if rsi_valid[-1] > rsi_valid[-2] > rsi_valid[-3]:
            conditions_met.append("RSI trending up (3 consecutive rises)")
            buy_score += 1
        elif rsi_valid[-1] < rsi_valid[-2] < rsi_valid[-3]:
            conditions_met.append("RSI trending down (3 consecutive falls)")
            sell_score += 1

    # Determine signal
    if buy_score >= 3:
        signal = "BUY"
        strength = min(buy_score, 5)
        sl = round(current_price * (1 - 0.015), 2)
        tp1 = round(current_price * (1 + 0.015), 2)
        tp2 = round(current_price * (1 + 0.030), 2)
    elif sell_score >= 3:
        signal = "SELL"
        strength = min(sell_score, 5)
        sl = round(current_price * (1 + 0.015), 2)
        tp1 = round(current_price * (1 - 0.015), 2)
        tp2 = round(current_price * (1 - 0.030), 2)
    else:
        signal = "NEUTRAL"
        strength = 0
        sl = None
        tp1 = None
        tp2 = None

    return {
        "signal": signal,
        "strength": strength,
        "conditions": conditions_met,
        "price": round(current_price, 2),
        "rsi": round(current_rsi, 2),
        "ema_rsi": round(current_ema_rsi, 2),
        "wma_rsi": round(current_wma_rsi, 2),
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
    }


def _last_valid(arr: np.ndarray):
    """Return last non-NaN value or None."""
    valid = arr[~np.isnan(arr)]
    return float(valid[-1]) if len(valid) > 0 else None


def format_price(price) -> str:
    """Format price as USD/oz string."""
    if price is None:
        return "N/A"
    return f"${price:,.2f}"


def main():
    parser = argparse.ArgumentParser(description="Gold price signal analyzer")
    parser.add_argument(
        "--mode",
        choices=["json", "text"],
        default="text",
        help="Output mode: json (clean JSON) or text (human-readable)",
    )
    parser.add_argument(
        "--timeframe",
        choices=["1h", "4h"],
        default="1h",
        help="Timeframe to analyze",
    )
    args = parser.parse_args()

    try:
        df = fetch_gold_data(args.timeframe)
        result = detect_signal(df)
        result["timeframe"] = args.timeframe
        result["candles"] = len(df)
    except Exception as e:
        error_result = {
            "signal": "ERROR",
            "error": str(e),
            "timeframe": args.timeframe,
        }
        if args.mode == "json":
            print(json.dumps(error_result))
        else:
            print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    if args.mode == "json":
        print(json.dumps(result))
        return

    # Human-readable text output
    tf = args.timeframe.upper()
    sig = result["signal"]
    sig_emoji = {"BUY": "🟢", "SELL": "🔴", "NEUTRAL": "⚪"}.get(sig, "⚪")

    print(f"\n{'='*50}")
    print(f"  🥇 GOLD (GC=F) — {tf} Analysis")
    print(f"{'='*50}")
    print(f"  Signal     : {sig_emoji} {sig}  (strength {result['strength']}/5)")
    print(f"  Price      : {format_price(result['price'])} /oz")
    print(f"  RSI(14)    : {result['rsi']:.2f}")
    print(f"  EMA(9)RSI  : {result['ema_rsi']:.2f}")
    print(f"  WMA(45)RSI : {result['wma_rsi']:.2f}")
    print(f"  Candles    : {result['candles']}")
    print()
    print("  Conditions:")
    for c in result["conditions"]:
        print(f"    • {c}")
    if sig != "NEUTRAL":
        print()
        print("  Risk Management:")
        print(f"    Stop Loss : {format_price(result['sl'])}")
        print(f"    TP1       : {format_price(result['tp1'])}")
        print(f"    TP2       : {format_price(result['tp2'])}")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    main()
