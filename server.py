import os
import threading
from flask import Flask

import bot  # tu archivo bot.py

app = Flask(__name__)

@app.get("/")
def home():
    return "OK", 200

def run_bot():
    bot.main()

if __name__ == "__main__":
    t = threading.Thread(target=run_bot, daemon=True)
    t.start()

    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
