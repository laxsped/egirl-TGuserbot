🎀 Sonya UserBot v4.1
Advanced Telegram UserBot that transforms an account into a "virtual girlfriend" named Sonya. This bot isn't just a script; it's a digital personality with human-like behavior, emotions, and memory.

⚠️ Important: Choosing an Account
You have two options for running this bot:

Second Account (Recommended): Register a separate Telegram account for Sonya. This is the safest and most fun way to interact with her as a "separate person."

Main Account: You can run the script on your primary account, but it will act on your behalf. Either way, the setup process is the same.

☁️ No Local Installation Required!
You don't need to download anything to your PC or install Python. The project includes a requirements.txt file, which means Render.com will automatically handle all libraries and dependencies in the cloud for you.

🚀 Quick Setup Guide
1. Preparation
Fork this repository to your GitHub profile.

Get your API_ID and API_HASH from my.telegram.org.

Get your GROQ_API_KEY from Groq Cloud.

Find your own Telegram ID using @userinfobot (this will be the BOYFRIEND_ID).

2. Deploying to Render.com
Create a Database: On Render, create a new PostgreSQL database. Copy the Internal Database URL.

Create a Web Service: Create a new Web Service and connect it to your forked GitHub repo.

Set Environment Variables: In the "Environment" tab of your service, add the following keys:
Key,Value
API_ID,Your Telegram API ID
API_HASH,Your Telegram API Hash
PHONE,Phone number of Sonya's account (with +)
BOYFRIEND_ID,Your personal Telegram ID
GROQ_API_KEY,Your Groq API Key
DATABASE_URL,The URL from your Postgres database
MODEL_NAME,meta-llama/llama-4-maverick-17b-128e-instruct

3. First Launch
Once you hit Deploy, Render will install everything automatically.

Note: On the very first run, you might need to check the Render logs to enter the Telegram confirmation code if you haven't provided a SESSION_DATA string.

✨ Why Sonya is special
Human-like typing: She makes typos, uses slang, and breaks long texts into multiple messages.

Smart Vision: Send her a photo, and she'll actually "see" and comment on it. 📸

Auto-Mode: She stays online during the day and can even text you first if she misses you.

Zero Maintenance: Since it's hosted on Render, she stays online 24/7 without your PC being on.

🤝 Need Help?
If something isn't working or you have a cool idea for Sonya's personality, open an Issue! ✌️
