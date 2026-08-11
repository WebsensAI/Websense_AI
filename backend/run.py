"""
run.py
Entry point. Run with: python run.py
Then open http://127.0.0.1:5000
"""
import os
from app.app import create_app
from app.config import Config

app = create_app()

if __name__ == "__main__":
    if not Config.GROQ_API_KEY:
        print("WARNING: GROQ_API_KEY is not set. AI analysis steps will fail.")
    if not Config.SMTP_EMAIL or not Config.SMTP_PASSWORD:
        print("NOTE: SMTP_EMAIL / SMTP_PASSWORD not set. Promo emails will be generated but not sent.")
    print(f"Starting server. Crawling up to {Config.MAX_PAGES} pages per request.")
    print("Open http://127.0.0.1:5000 in your browser.")
    app.run(debug=True, port=5000)
