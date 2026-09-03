import threading
import os
from flask import Flask
from bot import run_bot

app = Flask(__name__)

@app.route('/')
def home():
    return "MintGlow bot is running!"

@app.route('/health')
def health():
    return "OK", 200

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    # Запускаем Flask в отдельном потоке (чтобы освободить основной)
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.start()
    # Запускаем бота в основном потоке (чтобы сигналы работали)
    run_bot()
