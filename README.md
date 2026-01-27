🎀 Sonya UserBot v4.1
Advanced Telegram UserBot that transforms an account into a "virtual girlfriend" named Sonya. She isn't just a chatbot; she's designed to feel like a real person with a distinct personality, human-like typing patterns, and visual recognition. 💅

✨ Features
Personality-Driven: Sonya is ironic, lively, and a bit sassy. She speaks like a real 16-year-old (lowercase letters, slang, no "robotic" politeness).

Vision Capabilities: Can analyze photos and react to them emotionally thanks to the Llama-4 Maverick vision model. 📸

Human Emulation: * Simulates "typing" status based on message length.

Intentionally makes occasional typos.

Breaks long thoughts into multiple "bubbles" for a realistic chat flow.

Persistent Memory: Uses a PostgreSQL database to remember your conversation history.

Proactive Engagement: If her "boyfriend" is silent for more than 5 hours, she might take the initiative and text him first.

Stranger Defense: Cold and distant with strangers, but warms up if she detects friendly vibes or specific cues.

🚀 Quick Setup Guide
1. Repository Setup
Fork this repository to your own GitHub profile.

Ensure all files (especially main.py and requirements.txt) are present.

2. Code Configuration
In main.py, update the following fields with your own data:

BOYFRIEND_ID: Replace with your Telegram ID (get it from @userinfobot).

GROQ_API_KEY: Enter your API key from Groq Cloud.

3. Database & Hosting (Render.com)
Log in to Render.

Create a new PostgreSQL Database. Copy the Internal Database URL.

Create a new Web Service, connect your GitHub fork, and use the following Environment Variables:

DATABASE_URL: Your Postgres URL.

SESSION_DATA: Your Telethon session string encoded in base64.

PORT: 10000.

🛠 Tech Stack
Language: Python 3.x 🐍

TG Framework: Telethon (Userbot API)

LLM Engine: Groq API (Llama-3/4) 🧠

Database: PostgreSQL

Infrastructure: Render

⚠️ Disclaimer
This is a UserBot. Use it at your own risk. To avoid Telegram bans, do not use it for spamming and keep the human-like delays active.

🤝 Support
If Sonya starts getting too "real" or you find a bug, feel free to open an Issue! ✌️
