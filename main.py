import os
import requests
import asyncio
import json
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
import uvicorn

# --- Переменные окружения ---
STRAVA_CLIENT_ID = os.getenv("STRAVA_CLIENT_ID")
STRAVA_CLIENT_SECRET = os.getenv("STRAVA_CLIENT_SECRET")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
STRAVA_VERIFY_TOKEN = os.getenv("STRAVA_VERIFY_TOKEN", "supersecret")  # придумайте свой

# --- Инициализация бота и диспетчера ---
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()
users = {}  # временное хранилище

# --- Lifespan: запуск polling ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Сброс вебхука и очистка ожидающих обновлений
    await bot.delete_webhook(drop_pending_updates=True)
    polling_task = asyncio.create_task(dp.start_polling(bot))
    print("Bot polling started")
    yield
    polling_task.cancel()
    try:
        await polling_task
    except asyncio.CancelledError:
        print("Bot polling stopped")

# --- FastAPI приложение ---
app = FastAPI(lifespan=lifespan)

# --- Команды бота ---
@dp.message(Command('login'))
async def login(message: types.Message):
    auth_url = (
        "https://www.strava.com/oauth/authorize"
        f"?client_id={STRAVA_CLIENT_ID}"
        "&response_type=code"
        "&redirect_uri=https://itmo-active.onrender.com/callback"
        "&approval_prompt=force"
        "&scope=activity:read"
        f"&state={message.from_user.id}"
    )
    await message.answer(f"Авторизуйся:\n{auth_url}")

@dp.message(Command('steps'))
async def steps(message: types.Message):
    user_id = str(message.from_user.id)
    if user_id not in users:
        await message.answer("Сначала выполни /login")
        return
    token = users[user_id]
    steps_count = get_today_steps(token)
    await message.answer(f"Сегодня примерно {steps_count} шагов")

# --- Эндпоинты FastAPI ---
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
            "grant_type": "authorization_code",
            "redirect_uri": "https://itmo-active.onrender.com/callback"
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

@app.get("/webhook")
async def webhook_get(request: Request):
    """Подтверждение вебхука Strava (GET)"""
    mode = request.query_params.get("hub.mode")
    challenge = request.query_params.get("hub.challenge")
    verify_token = request.query_params.get("hub.verify_token")

    if mode and verify_token == STRAVA_VERIFY_TOKEN:
        # Возвращаем challenge как требуется Strava
        return {"hub.challenge": challenge}
    else:
        return Response(status_code=403)

@app.post("/webhook")
async def webhook_post(request: Request):
    """Получение уведомлений от Strava (POST)"""
    body = await request.json()
    print("Получен вебхук от Strava:", json.dumps(body, indent=2))
    # TODO: обработать событие (например, обновить кэш активности)
    return Response(status_code=200)

# --- Вспомогательная функция ---
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

# --- Локальный запуск (для Render не используется) ---
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)