import os
import requests
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
import uvicorn

# --- Переменные окружения (должны быть заданы в Render) ---
STRAVA_CLIENT_ID = os.getenv("STRAVA_CLIENT_ID")
STRAVA_CLIENT_SECRET = os.getenv("STRAVA_CLIENT_SECRET")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

# --- Инициализация бота и диспетчера ---
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()
users = {}  # временное хранилище (заменить на БД в будущем)

# --- Команда /login ---
@dp.message(Command('login'))
async def login(message: types.Message):
    auth_url = (
        "https://www.strava.com/oauth/authorize"
        f"?client_id={STRAVA_CLIENT_ID}"
        "&response_type=code"
        "&redirect_uri=https://itmo-active.onrender.com/callback"  # ВАЖНО: ваш URL
        "&approval_prompt=force"
        "&scope=activity:read"
        f"&state={message.from_user.id}"
    )
    await message.answer(f"Авторизуйся:\n{auth_url}")

# --- Команда /steps ---
@dp.message(Command('steps'))
async def steps(message: types.Message):
    user_id = str(message.from_user.id)
    if user_id not in users:
        await message.answer("Сначала выполни /login")
        return
    token = users[user_id]
    steps_count = get_today_steps(token)
    await message.answer(f"Сегодня примерно {steps_count} шагов")

# --- OAuth callback (FastAPI) ---
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

# --- Функция для получения шагов из Strava (синхронная, лучше заменить на async/httpx) ---
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
            steps += int(distance / 0.75)  # грубая оценка
    return steps

# --- Lifespan: запускаем и останавливаем polling бота ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Запуск бота в фоне
    polling_task = asyncio.create_task(dp.start_polling(bot))
    print("Bot polling started")
    yield
    # Остановка при завершении приложения
    polling_task.cancel()
    try:
        await polling_task
    except asyncio.CancelledError:
        print("Bot polling stopped")

# --- Создаём приложение FastAPI с lifespan ---
app = FastAPI(lifespan=lifespan)

# --- Запуск (только для локальной отладки, на Render используется команда из Procfile) ---
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)