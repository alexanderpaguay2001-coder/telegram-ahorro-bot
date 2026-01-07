import os
import subprocess
from flask import Flask

app = Flask(__name__)

@app.get("/")
def home():
    return "OK", 200

# Arranca el bot una sola vez al iniciar el servicio
bot_process = None

def start_bot():
    global bot_process
    if bot_process is None or bot_process.poll() is not None:
        bot_process = subprocess.Popen(["python3", "bot.py"])

start_bot()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
