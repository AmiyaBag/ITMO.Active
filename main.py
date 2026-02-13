import os
import requests
import asyncio
import signal
import sys
import threading
from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
import uvicorn

# --- Обработчик сигнала для graceful shutdown (упрощённый) ---
def signal_handler(sig, frame):
    print("\nShutting down gracefully...")
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

# --- Переменные окружения ---
STRAVA_CLIENT_ID = os.getenv("STRAVA_CLIENT_ID")
STRAVA_CLIENT_SECRET = os.getenv("STRAVA_CLIENT_SECRET")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

# --- Инициализация бота и диспетчера (aiogram v3) ---
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()                # <-- ИСПРАВЛЕНО
app = FastAPI()

# Хранилище токенов (в памяти, не подходит для продакшена)
users = {}

# --- Команда /login ---
@dp.message(Command('login'))
async def login(message: types.Message):
    auth_url = (
        "https://www.strava.com/oauth/authorize"
        f"?client_id={STRAVA_CLIENT_ID}"
        "&response_type=code"
        "&redirect_uri=https://itmo-active.onrender.com"   # ЗАМЕНИТЬ на Render URL при деплое
        "&approval_prompt=force"
        "&scope=activity:read"
        f"&state={message.from_user.id}"
    )
    await message.answer(f"Авторизуйся:\n{auth_url}")

# --- Команда /steps (aiogram v3) ---
@dp.message(Command('steps'))    # <-- ИСПРАВЛЕНО
async def steps(message: types.Message):
    user_id = str(message.from_user.id)
    if user_id not in users:
        await message.answer("Сначала выполни /login")
        return
    token = users[user_id]
    steps_count = get_today_steps(token)
    await message.answer(f"Сегодня примерно {steps_count} шагов")

# --- OAuth callback ---
@app.get("/callback")
async def callback(request: Request):
    code = request.query_params.get("code")
    user_id = request.query_params.get("state")

    if not code or not user_id:
        return {"error": "Missing code or state"}

    response = requests.post(
        "https://www.strava.com/oauth/token",
        data={
            "client_id": STRAVA_CLIENT_ID,
            "client_secret": STRAVA_CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code"
        }
    )

    if response.status_code != 200:
        print(f"Strava token error {response.status_code}: {response.text}")
        return {"error": "Failed to obtain token from Strava"}

    try:
        token_data = response.json()
    except requests.exceptions.JSONDecodeError:
        print(f"Invalid JSON from Strava: {response.text}")
        return {"error": "Invalid response from Strava"}

    access_token = token_data.get("access_token")
    if not access_token:
        print(f"No access_token in response: {token_data}")
        return {"error": "No access token in Strava response"}

    users[user_id] = access_token
    return {"status": "Авторизация успешна"}

# --- Получение шагов из Strava (синхронно, лучше заменить на async) ---
def get_today_steps(token):
    headers = {"Authorization": f"Bearer {token}"}
    activities = requests.get(
        "https://www.strava.com/api/v3/athlete/activities",
        headers=headers
    ).json()

    steps = 0
    for act in activities:
        if act["type"] in ["Run", "Walk"]:
            distance = act["distance"]
            steps += int(distance / 0.75)
    return steps

# --- Запуск бота в отдельном потоке ---
def start_bot():
    asyncio.run(dp.start_polling(bot))   # <-- ИСПРАВЛЕНО (dp, а не bot напрямую)

bot_thread = threading.Thread(target=start_bot, daemon=True)
bot_thread.start()

# --- Запуск FastAPI ---
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)