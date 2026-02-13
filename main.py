import os
import requests
import asyncio
import signal
import sys
from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from threading import Thread
import uvicorn

def signal_handler(sig, frame):
    print("\nShutting down gracefully...")
    # Stop the bot polling (requires changes in the bot thread)
    # For a simple solution, just exit
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

STRAVA_CLIENT_ID = os.getenv("STRAVA_CLIENT_ID")
STRAVA_CLIENT_SECRET = os.getenv("STRAVA_CLIENT_SECRET")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher(bot)
app = FastAPI()

users = {}  # временное хранилище токенов

@dp.message_handler(commands=['login'])
async def login(message: types.Message):
    auth_url = (
        "https://www.strava.com/oauth/authorize"
        f"?client_id={STRAVA_CLIENT_ID}"
        "&response_type=code"
        "&redirect_uri=http://localhost:8000/callback"
        "&approval_prompt=force"
        "&scope=activity:read"
        f"&state={message.from_user.id}"
    )
    await message.answer(f"Авторизуйся:\n{auth_url}")

@app.get("/callback")
async def callback(request: Request):
    code = request.query_params.get("code")
    user_id = request.query_params.get("state")

    if not code or not user_id:
        return {"error": "Missing code or state"}

    # Exchange the code for an access token
    response = requests.post(
        "https://www.strava.com/oauth/token",
        data={
            "client_id": STRAVA_CLIENT_ID,
            "client_secret": STRAVA_CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code"
        }
    )

    # Check HTTP status
    if response.status_code != 200:
        # Log the error for debugging (visible in your console)
        print(f"Strava token error {response.status_code}: {response.text}")
        return {"error": "Failed to obtain token from Strava"}

    # Safely parse JSON
    try:
        token_data = response.json()
    except requests.exceptions.JSONDecodeError:
        print(f"Invalid JSON from Strava: {response.text}")
        return {"error": "Invalid response from Strava"}

    # Extract access token
    access_token = token_data.get("access_token")
    if not access_token:
        print(f"No access_token in response: {token_data}")
        return {"error": "No access token in Strava response"}

    # Store the token
    users[user_id] = access_token
    return {"status": "Авторизация успешна"}

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

@dp.message_handler(commands=['steps'])
async def steps(message: types.Message):
    user_id = str(message.from_user.id)

    if user_id not in users:
        await message.answer("Сначала выполни /login")
        return

    token = users[user_id]
    steps_count = get_today_steps(token)

    await message.answer(f"Сегодня примерно {steps_count} шагов")

def start_bot():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    executor.start_polling(dp, skip_updates=True)
    

if __name__ == "__main__":
    Thread(target=start_bot).start()
    uvicorn.run(app, host="0.0.0.0", port=8000)

