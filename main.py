import matplotlib
matplotlib.use('Agg') # ЭТО ОБЯЗАТЕЛЬНО: позволяет рисовать графики без монитора

import ccxt.async_support as ccxt
import telebot
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import asyncio
import os
import threading
from flask import Flask
from telebot import types

# --- КОНФИГ ---
BOT_TOKEN = os.getenv('BOT_TOKEN') 
YOUR_CHAT_ID = int(os.getenv('YOUR_CHAT_ID', '0')) # '0' - это заглушка
symbols = ['BTC/USDT', 'ETH/USDT', 'BNB/USDT', 'SOL/USDT', 'XRP/USDT', 'ADA/USDT', 'DOGE/USDT', 'AVAX/USDT', 'DOT/USDT', 'TRX/USDT', 'LINK/USDT', 'NEAR/USDT']

binance = ccxt.binance({'options': {'defaultType': 'future'}})
bot = telebot.TeleBot(BOT_TOKEN)
last_signals = {symbol: None for symbol in symbols}

# --- БЛОК ЗАТЫЧКИ (HEALTH CHECK) ---
app = Flask(__name__)

@app.route('/')
def health_check():
    return "OK", 200

def run_flask():
    app.run(host='0.0.0.0', port=8000)

threading.Thread(target=run_flask, daemon=True).start()

# --- БЛОК КНОПКИ "ЖИВОЙ?" ---
@bot.message_handler(commands=['start'])
def start(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("Живой?"))
    bot.send_message(message.chat.id, "Бот запущен. Используй кнопку:", reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == "Живой?")
def check_status(message):
    bot.send_message(message.chat.id, "✅ Да, тружусь, всё хорошо!")

# --- МАТЕМАТИКА И ИНДИКАТОРЫ ---
def calculate_indicators(df):
    # RSI
    delta = df['c'].diff()
    gain = delta.where(delta > 0, 0).rolling(window=14).mean()
    loss = -delta.where(delta < 0, 0).rolling(window=14).mean()
    df['rsi'] = 100 - (100 / (1 + (gain / loss)))
    # ATR
    high_low = df['h'] - df['l']
    high_cp = np.abs(df['h'] - df['c'].shift())
    low_cp = np.abs(df['l'] - df['c'].shift())
    df['tr'] = pd.concat([high_low, high_cp, low_cp], axis=1).max(axis=1)
    df['atr'] = df['tr'].rolling(window=14).mean()
    # Z-Score Объема
    df['v_mean'] = df['v'].rolling(window=20).mean()
    df['v_std'] = df['v'].rolling(window=20).std()
    df['z_score'] = (df['v'] - df['v_mean']) / df['v_std']
    return df

def calculate_fibonacci(df):
    h, l = df['h'].max(), df['l'].min()
    diff = h - l
    return {'1.0': h, '0.618': h - diff * 0.382, '0.5': h - diff * 0.5, '0.382': h - diff * 0.618, '0': l}

# --- ВИЗУАЛИЗАЦИЯ ---
def create_chart(df, symbol, fibs, tp, sl):
    plt.figure(figsize=(10, 6))
    plt.plot(df.index, df['c'], color='#1f77b4', label='Цена')
    for lvl, val in fibs.items():
        plt.axhline(val, linestyle='--', alpha=0.3, color='orange')
    plt.axhline(tp, color='green', label='Take Profit', lw=1.5)
    plt.axhline(sl, color='red', label='Stop Loss', lw=1.5)
    plt.title(f"Сигнал: {symbol}")
    plt.legend()
    path = f"chart_{symbol.replace('/', '_')}.png"
    plt.savefig(path); plt.close()
    return path

# --- ОСНОВНАЯ ЛОГИКА ---
async def get_processed_df(symbol, tf):
    ohlcv = await binance.fetch_ohlcv(symbol, timeframe=tf, limit=100)
    df = pd.DataFrame(ohlcv, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
    return calculate_indicators(df)

async def check_market():
    print(f"\n--- СКАНИРОВАНИЕ {len(symbols)} МОНЕТ ---")
    for symbol in symbols:
        try:
            # 1. Мульти-таймфрейм
            df5m = await get_processed_df(symbol, '5m')
            df15m = await get_processed_df(symbol, '15m')
            df1h = await get_processed_df(symbol, '1h')

            curr = df15m.iloc[-1]
            fibs = calculate_fibonacci(df15m)
            
            # Фильтры
            trend_up = (df1h['c'].iloc[-1] > df1h['c'].iloc[-10]) # Тренд на 1ч
            vol_spike = (curr['z_score'] > 1.5) # Всплеск объема
            market_active = (curr['atr'] > df15m['atr'].mean() * 0.8) # Фильтр волатильности

            action = None
            if market_active and vol_spike:
                # BUY: Тренд 1ч вверх + RSI < 35 + отскок от Фибо 0.382
                if trend_up and curr['rsi'] < 45 and curr['c'] <= fibs['0.382']:
                    action = "BUY"
                # SELL: Тренд 1ч вниз + RSI > 55 + цена у Фибо 0.618
                elif not trend_up and curr['rsi'] > 55 and curr['c'] >= fibs['0.618']:
                    action = "SELL"

            print(f"[{symbol}] RSI:{curr['rsi']:.1f} Z:{curr['z_score']:.1f} ATR:{market_active} Sig:{action}")

            if action and action != last_signals[symbol]:
                last_signals[symbol] = action
                # ATR-based риск-менеджмент
                tp_dist = curr['atr'] * 3
                sl_dist = curr['atr'] * 1.5
                tp = curr['c'] + tp_dist if action == "BUY" else curr['c'] - tp_dist
                sl = curr['c'] - sl_dist if action == "BUY" else curr['c'] + sl_dist

                path = create_chart(df15m, symbol, fibs, tp, sl)
                # Создаем прямую ссылку на Binance Futures
                clean_symbol = symbol.replace('/', '')
                binance_link = f"https://www.binance.com/ru/futures/{clean_symbol}"

                path = create_chart(df15m, symbol, fibs, tp, sl)
                
                text = (
                    f"🎯 *ВХОД: {symbol}* ({action})\n"
                    f"━━━━━━━━━━━━━━\n"
                    f"💰 Цена: `{curr['c']}`\n"
                    f"📈 Z-Score Vol: `{curr['z_score']:.2f}`\n"
                    f"🟢 TP: `{tp:.4f}`\n"
                    f"🔴 SL: `{sl:.4f}`\n"
                    f"━━━━━━━━━━━━━━\n"
                    f"🔗 [ОТКРЫТЬ ГРАФИК BINANCE]({binance_link})")
                
                
                with open(path, 'rb') as photo:
                    bot.send_photo(YOUR_CHAT_ID, photo, caption=text, parse_mode="Markdown")
                os.remove(path)

        except Exception as e: print(f"Ошибка {symbol}: {e}")
        await asyncio.sleep(0.1)

async def main():
    while True:
        await check_market()
        await asyncio.sleep(20)

def run_scanner():
    asyncio.run(main())

if __name__ == "__main__":
    # Запускаем сканер в отдельном потоке, чтобы он не мешал кнопкам
    threading.Thread(target=run_scanner, daemon=True).start()
    
    # Запускаем прослушивание Telegram (обязательно в конце!)
    bot.infinity_polling()
