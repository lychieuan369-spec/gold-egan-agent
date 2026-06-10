#!/usr/bin/env python3
"""
Gold Price Prediction Agent — telegram_alert_gold.py
Entry point for GitHub Actions. Checks 4h + 1h signals and sends Telegram alert
if either timeframe produces a non-NEUTRAL signal.
Reads BOT_TOKEN and CHAT_ID from environment variables.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone


def get_signal(timeframe: str) -> dict:
    """Run analyze_gold.py and return parsed JSON result."""
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "analyze_gold.py")
    try:
        result = subprocess.run(
            [sys.executable, script, "--mode", "json", "--timeframe", timeframe],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            return {
                "signal": "ERROR",
                "error": stderr or "analyze_gold.py returned non-zero exit",
                "timeframe": timeframe,
            }
        output = result.stdout.strip()
        if not output:
            return {"signal": "ERROR", "error": "Empty output", "timeframe": timeframe}
        return json.loads(output)
    except subprocess.TimeoutExpired:
        return {"signal": "ERROR", "error": "Timeout (120s)", "timeframe": timeframe}
    except json.JSONDecodeError as e:
        return {"signal": "ERROR", "error": f"JSON parse error: {e}", "timeframe": timeframe}
    except Exception as e:
        return {"signal": "ERROR", "error": str(e), "timeframe": timeframe}


def fmt_price(price) -> str:
    """Format as USD/oz string."""
    if price is None:
        return "N/A"
    return f"${price:,.2f}"


def strength_bar(strength: int) -> str:
    """Visual strength indicator."""
    filled = min(max(strength, 0), 5)
    return "▓" * filled + "░" * (5 - filled)


def build_message(sig_4h: dict, sig_1h: dict) -> str:
    """Build HTML-formatted Telegram message."""
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    signal_emoji = {
        "BUY": "🟢",
        "SELL": "🔴",
        "NEUTRAL": "⚪",
        "ERROR": "⛔",
    }

    def render_signal_block(sig: dict) -> str:
        tf = sig.get("timeframe", "?").upper()
        s = sig.get("signal", "ERROR")
        emoji = signal_emoji.get(s, "⚪")

        if s == "ERROR":
            return (
                f"<b>[{tf}]</b> {emoji} <b>ERROR</b>\n"
                f"<code>{sig.get('error', 'Unknown error')[:200]}</code>"
            )

        lines = [
            f"<b>[{tf}]</b> {emoji} <b>{s}</b>  "
            f"<code>{strength_bar(sig.get('strength', 0))}</code> {sig.get('strength', 0)}/5",
            f"  💰 Price  : <b>{fmt_price(sig.get('price'))}</b> /oz",
            f"  📊 RSI    : <code>{sig.get('rsi', 'N/A')}</code>",
            f"  📈 EMA(9) : <code>{sig.get('ema_rsi', 'N/A')}</code>",
            f"  📉 WMA(45): <code>{sig.get('wma_rsi', 'N/A')}</code>",
        ]

        conditions = sig.get("conditions", [])
        if conditions:
            lines.append("  <i>Conditions:</i>")
            for c in conditions:
                lines.append(f"    ✓ {c}")

        if s != "NEUTRAL" and sig.get("sl") is not None:
            lines.append(f"  🛡 SL  : <b>{fmt_price(sig.get('sl'))}</b>")
            lines.append(f"  🎯 TP1 : <b>{fmt_price(sig.get('tp1'))}</b>  (+1.5%)")
            lines.append(f"  🎯 TP2 : <b>{fmt_price(sig.get('tp2'))}</b>  (+3.0%)")

        return "\n".join(lines)

    # Determine overall alert level
    signals = [sig_4h.get("signal"), sig_1h.get("signal")]
    if "BUY" in signals and "SELL" not in signals:
        alert_header = "🥇 <b>GOLD ALERT — BUY SIGNAL DETECTED</b> 🥇"
    elif "SELL" in signals and "BUY" not in signals:
        alert_header = "🥇 <b>GOLD ALERT — SELL SIGNAL DETECTED</b> 🥇"
    elif "BUY" in signals and "SELL" in signals:
        alert_header = "🥇 <b>GOLD ALERT — MIXED SIGNALS (caution)</b> 🥇"
    else:
        alert_header = "🥇 <b>GOLD ALERT — SIGNAL UPDATE</b> 🥇"

    msg_parts = [
        alert_header,
        f"<i>{now_utc}</i>",
        "",
        render_signal_block(sig_4h),
        "",
        "─────────────────────────",
        "",
        render_signal_block(sig_1h),
        "",
        "─────────────────────────",
        "<i>Data: CME Gold Futures (GC=F) via yfinance</i>",
        "<i>SL ±1.5% | TP1 ±1.5% | TP2 ±3.0%</i>",
        "<i>⚠️ For informational purposes only. Not financial advice.</i>",
    ]

    return "\n".join(msg_parts)


def send_telegram(bot_token: str, chat_id: str, message: str) -> bool:
    """Send HTML-formatted message via Telegram Bot API."""
    import urllib.request
    import urllib.parse
    import urllib.error

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = json.dumps({
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            if body.get("ok"):
                print(f"[OK] Telegram message sent (message_id={body['result']['message_id']})")
                return True
            else:
                print(f"[ERROR] Telegram API error: {body}", file=sys.stderr)
                return False
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"[ERROR] HTTP {e.code}: {body}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"[ERROR] send_telegram failed: {e}", file=sys.stderr)
        return False


def main():
    bot_token = os.environ.get("BOT_TOKEN", "8639655584:AAGKmEwGKEufCYwItf3v4c7G_P5acacAwQA").strip()
    chat_id = os.environ.get("CHAT_ID", "8842938928").strip()

    print("[INFO] Fetching 4h signal...")
    sig_4h = get_signal("4h")
    print(f"[INFO] 4h signal: {sig_4h.get('signal')} | RSI={sig_4h.get('rsi')}")

    print("[INFO] Fetching 1h signal...")
    sig_1h = get_signal("1h")
    print(f"[INFO] 1h signal: {sig_1h.get('signal')} | RSI={sig_1h.get('rsi')}")

    # Only send alert if at least one timeframe has a non-NEUTRAL, non-ERROR signal
    actionable_signals = {sig_4h.get("signal"), sig_1h.get("signal")} - {"NEUTRAL", "ERROR", None}

    if not actionable_signals:
        print("[INFO] Both timeframes NEUTRAL — no alert sent.")
        return

    print(f"[INFO] Actionable signals detected: {actionable_signals} — sending Telegram alert...")
    message = build_message(sig_4h, sig_1h)
    send_telegram(bot_token, chat_id, message)

    # Futures LONG/SHORT — only on STRONG signal (strength >= 4)
    for sig, tf_label in [(sig_4h, "4H"), (sig_1h, "1H")]:
        strength = sig.get("strength", 0)
        signal = sig.get("signal")
        price = sig.get("price", 0)
        if signal == "BUY" and strength >= 4:
            atr = price * 0.015
            sl = round(price - 1.5 * atr, 2)
            tp = round(price + 3.0 * atr, 2)
            text = (
                f"🟢 <b>LONG GOLD/USD [{tf_label}]</b>\n"
                f"Entry: <b>${price:,.2f}</b>\n"
                f"SL: ${sl:,.2f} (-1.5×ATR)\n"
                f"TP: ${tp:,.2f} (+3×ATR)\n"
                f"RR: 1:2 | Strength: {strength}/5"
            )
            send_telegram(bot_token, chat_id, text)
            print(f"[INFO] Futures LONG alert sent [{tf_label}]")
        elif signal == "SELL" and strength >= 4:
            atr = price * 0.015
            sl = round(price + 1.5 * atr, 2)
            tp = round(price - 3.0 * atr, 2)
            text = (
                f"🔴 <b>SHORT GOLD/USD [{tf_label}]</b>\n"
                f"Entry: <b>${price:,.2f}</b>\n"
                f"SL: ${sl:,.2f} (+1.5×ATR)\n"
                f"TP: ${tp:,.2f} (-3×ATR)\n"
                f"RR: 1:2 | Strength: {strength}/5"
            )
            send_telegram(bot_token, chat_id, text)
            print(f"[INFO] Futures SHORT alert sent [{tf_label}]")

    sys.exit(0)


if __name__ == "__main__":
    main()
