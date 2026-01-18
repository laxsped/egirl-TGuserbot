from telethon import TelegramClient, events, functions
import requests
import asyncio
import random
import os
import base64
import psycopg2
from aiohttp import web

# Твои данные
api_id = 33125954
api_hash = '42dd1070f641ea0060b39067c1e187e7'
phone = '+79118682172'
BOYFRIEND_ID = 5902478541
GROQ_API_KEY = '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'
DATABASE_URL = os.getenv('DATABASE_URL')

# Восстановление сессии
session_b64 = os.getenv('SESSION_DATA')
if session_b64:
    try:
        session_bytes = base64.b64decode(session_b64)
        with open('girlfriend_session.session', 'wb') as f:
            f.write(session_bytes)
        print("Сессия восстановлена!")
    except Exception as e:
        print(f"Ошибка сессии: {e}")

client = TelegramClient('girlfriend_session', api_id, api_hash)

# Промпты
SYSTEM_PROMPT_BOYFRIEND = """ты соня, девушка 16 лет. переписываешься со своим парнем лёшей. 
ВАЖНО: ты ДЕВУШКА! стиль: коротко, без заглавных, иногда дерзко/игриво. 
пиши как школьница: "ну ты и тормоз", "аххахах дурачок", "блинн скучаю". макс 1-2 предложения."""

SYSTEM_PROMPT_OTHERS = """ты соня, девушка 16 лет. пишет незнакомец. ты осторожная. 
стиль: коротко, без заглавных. если лезут — "отстань", "ты кто вообще"."""

# --- РАБОТА С БАЗОЙ ДАННЫХ (ПАМЯТЬ) ---
def init_db():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute('''    
        CREATE TABLE IF NOT EXISTS messages (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            role TEXT,
            content TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    cur.close()
    conn.close()

def save_to_db(user_id, role, content):
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute('INSERT INTO messages (user_id, role, content) VALUES (%s, %s, %s)', 
                    (user_id, role, content))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Ошибка записи в БД: {e}")

def get_history_from_db(user_id, limit=30):
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute('SELECT role, content FROM messages WHERE user_id = %s ORDER BY id DESC LIMIT %s', 
                    (user_id, limit))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [{'role': r, 'content': c} for r, c in reversed(rows)]
    except Exception as e:
        print(f"Ошибка чтения БД: {e}")
        return []

# --- ЛОГИКА ОПЕЧАТОК ---
def make_typos(text):
    if len(text) < 5 or random.random() > 0.25:
        return text
    text_list = list(text)
    t_type = random.randint(1, 3)
    if t_type == 1 and len(text_list) > 1:
        text_list.pop(random.randint(0, len(text_list)-1))
    elif t_type == 2:
        idx = random.randint(0, len(text_list)-2)
        text_list[idx], text_list[idx+1] = text_list[idx+1], text_list[idx]
    elif t_type == 3:
        idx = random.randint(0, len(text_list)-1)
        text_list.insert(idx, text_list[idx])
    return "".join(text_list)

async def presence_manager():
    while True:
        online_time = random.randint(120, 600)
        offline_time = random.randint(900, 2700)
        try:
            await client(functions.account.UpdateStatusRequest(offline=False))
            await asyncio.sleep(online_time)
            await client(functions.account.UpdateStatusRequest(offline=True))
            await asyncio.sleep(offline_time)
        except:
            await asyncio.sleep(60)

async def get_ai_response(message, user_id, user_name):
    is_boyfriend = (user_id == BOYFRIEND_ID)
    system_prompt = SYSTEM_PROMPT_BOYFRIEND if is_boyfriend else SYSTEM_PROMPT_OTHERS
    
    # Сохраняем входящее
    save_to_db(user_id, 'user', message)
    
    # Достаем историю
    history = get_history_from_db(user_id)
    
    try:
        response = requests.post(
            'https://api.groq.com/openai/v1/chat/completions',
            headers={'Authorization': f'Bearer {GROQ_API_KEY}'},
            json={
                'model': 'llama-3.3-70b-versatile',
                'messages': [{'role': 'system', 'content': system_prompt}] + history,
                'temperature': 0.9
            }
        )
        data = response.json()
        result = data['choices'][0]['message']['content']
        
        # Сохраняем ответ Сони
        save_to_db(user_id, 'assistant', result)
        return result
    except:
        return "сорян зависло"

@client.on(events.NewMessage(incoming=True))
async def handler(event):
    if event.is_group or event.is_channel: return
    user_id = event.sender_id
    
    # 1. Задержка "увидела уведомление"
    await asyncio.sleep(random.uniform(1, 3))
    
    # 2. Прочитано
    try: await client.send_read_acknowledge(event.chat_id, max_id=event.id)
    except: pass
    
    # 3. Ответ и опечатки
    reply = await get_ai_response(event.text, user_id, "")
    reply = make_typos(reply)
    
    # 4. Печатает...
    typing_time = max(2, min(len(reply) / random.uniform(2.5, 3.5), 15))
    async with client.action(event.chat_id, 'typing'):
        await asyncio.sleep(typing_time)
    
    await event.respond(reply)

# Web сервер для Render
async def health_check(request): return web.Response(text="Alive")
app = web.Application()
app.router.add_get('/', health_check)

async def main():
    init_db() # Запуск базы
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', int(os.environ.get('PORT', 10000))).start()
    
    await client.start(phone)
    asyncio.create_task(presence_manager())
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())

