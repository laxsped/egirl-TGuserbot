from telethon import TelegramClient, events, functions
import requests
import asyncio
import random
import os
import base64
import psycopg2
from aiohttp import web
from datetime import datetime, timedelta
import pytz
from groq import Groq

# --- КОНФИГУРАЦИЯ ---
is_online = False
is_offended = False
offended_until = None

api_id = 33125954
api_hash = '42dd1070f641ea0060b39067c1e187e7'
phone = '+79118682172'
BOYFRIEND_ID = 5902478541
GROQ_API_KEY = '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'
DATABASE_URL = os.getenv('DATABASE_URL')
groq_client = Groq(api_key=GROQ_API_KEY)
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

# --- ПРОМПТЫ ---
SYSTEM_PROMPT_BOYFRIEND = """ты соня, девушка 16 лет. переписываешься со своим парнем лёшей. 
ВАЖНО: ты ДЕВУШКА! стиль: коротко, без заглавных, иногда дерзко/игриво, используешь эмодзи не часто. 
пиши как школьница: "ну ты и тормоз", "аххахах дурачок", "блинн скучаю". макс 1-2 предложения."""

SYSTEM_PROMPT_OTHERS = """ты соня, девушка 16 лет. пишет незнакомец. ты осторожная. 
стиль: коротко, без заглавных. если лезут — "отстань", "ты кто вообще"."""

# --- БАЗА ДАННЫХ (Postgres) ---
def init_db():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        # Добавил индекс, чтобы история грузилась мгновенно
        cur.execute('''    
            CREATE TABLE IF NOT EXISTS messages (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                role TEXT,
                content TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_user_id ON messages(user_id);
        ''')
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Ошибка БД init: {e}")

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

def get_history_from_db(user_id, limit=40):
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

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def check_if_offensive(text):
    if not text: return False
    offensive_words = [
        'дура', 'тупая', 'достала', 'заебала', 'отстань пж', 
        'надоела', 'бесишь', 'идиотка', 'глупая', 'stupid'
    ]
    return any(word in text.lower() for word in offensive_words)

def make_typos(text):
    if len(text) < 5 or random.random() > 0.4:
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

# --- VISION (Улучшенный промпт) ---
def get_vision_response(image_path, user_id):
    with open(image_path, "rb") as image_file:
        base64_image = base64.b64encode(image_file.read()).decode('utf-8')
    
    # Подтягиваем историю, чтобы она понимала, о чем вы говорили ДО фото
    history = get_history_from_db(user_id, limit=5)
    history_context = "\n".join([f"{m['role']}: {m['content']}" for m in history])

    try:
        completion = groq_client.chat.completions.create(
            model="meta-llama/llama-4-maverick-17b-128e-instruct",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text", 
                            "text": f"Ты Соня, тебе 16. Твой парень прислал фото. \n"
                                    f"Контекст последних сообщений: {history_context}\n"
                                    "1. Сначала напиши краткое описание фото для своей памяти в формате [MEMORY: ...].\n"
                                    "2. Затем ответь парню как реальная девушка (без заглавных, коротко, сленг, 1 эмодзи). "
                                    "НЕ описывай фото как ИИ, просто отреагируй на него эмоционально!"
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}
                        }
                    ]
                }
            ],
            temperature=0.5 # Снижаем, чтобы меньше врала про туман
        )
        return completion.choices[0].message.content
    except Exception as e:
        print(f"Ошибка Vision: {e}")
        return "блин картинка не грузится [MEMORY: ошибка]"

# --- AI RESPONSE (TEXT) ---
async def get_ai_response(message, user_id):
    is_boyfriend = (user_id == BOYFRIEND_ID)
    
    # Твой стиль Сони
    SONYA_STYLE = (
        "Ты Соня, тебе 16. Твой стиль: ПОЛНЫЙ ИГНОР ЗАГЛАВНЫХ БУКВ И ТОЧЕК В КОНЦЕ. "
        "Пиши как реальная девчонка в телеге: коротко, сленгом, иногда с кучей лишних букв. "
        "ЗАПРЕТ: Не используй время и цифры, не ставь больше одного смайлика. "
        "Если Лёша бесит — отвечай дерзко. Если скучаешь — мило."
    )
    
    system_prompt = SONYA_STYLE if is_boyfriend else SYSTEM_PROMPT_OTHERS
    
    save_to_db(user_id, 'user', message)
    history = get_history_from_db(user_id, limit=40)
    
    try:
        # Используем Maverick для обычного чата
        completion = groq_client.chat.completions.create(
            model="meta-llama/llama-4-maverick-17b-128e-instruct",
            messages=[{'role': 'system', 'content': system_prompt}] + history,
            temperature=1.0,
            presence_penalty=0.6
        )
        
        result = completion.choices[0].message.content.lower().replace('.', '').strip()
        save_to_db(user_id, 'assistant', result)
        return result
    except Exception as e:
        print(f"Ошибка AI (Maverick Text): {e}")
        return "блин зависла чето"

# --- BACKGROUND TASKS (Инициатива Сони) ---
async def thoughts_loop():
    daily_messages_sent = 0
    last_reset_day = datetime.now().day
    
    while True:
        await asyncio.sleep(random.randint(1800, 3600))
        
        current_day = datetime.now().day
        if current_day != last_reset_day:
            daily_messages_sent = 0
            last_reset_day = current_day
        
        if daily_messages_sent >= 3:
            continue
        
        moscow_time = datetime.now(pytz.timezone('Europe/Kaliningrad'))
        hour = moscow_time.hour
        
        if not (8 <= hour <= 23):
            continue
        
        if random.random() > 0.2:
            continue

        # Ревность (логика БД остается та же)
        is_jealous = False
        try:
            conn = psycopg2.connect(DATABASE_URL)
            cur = conn.cursor()
            cur.execute('SELECT timestamp FROM messages WHERE user_id = %s AND role = \'user\' ORDER BY timestamp DESC LIMIT 1', (BOYFRIEND_ID,))
            last_msg = cur.fetchone()
            cur.close()
            conn.close()
            if last_msg:
                hours_since = (datetime.now() - last_msg[0]).total_seconds() / 3600
                if hours_since > 6: is_jealous = True
        except: pass
        
        # Выбор промпта
        if is_jealous:
            prompts = ["напиши лёше что он куда-то пропал и ты беспокоишься", "спроси где он был, немного обиженно"]
        elif 8 <= hour < 11: prompts = ["напиши лёше доброе утро", "спроси как он спал"]
        elif 18 <= hour < 22: prompts = ["спроси чем он занят", "напиши что скучаешь"]
        else: prompts = ["спроси что он делает", "напиши что скучаешь"]
        
        prompt = random.choice(prompts)
        
        try:
            # Тут тоже Maverick!
            response = groq_client.chat.completions.create(
                model="meta-llama/llama-4-maverick-17b-128e-instruct",
                messages=[
                    {'role': 'system', 'content': SYSTEM_PROMPT_BOYFRIEND},
                    {'role': 'user', 'content': prompt}
                ],
                temperature=1.1
            )
            text = response.choices[0].message.content
            text = make_typos(text.lower().replace('.', ''))
            
            # Статус и отправка
            global is_online
            if not is_online:
                await client(functions.account.UpdateStatusRequest(offline=False))
                is_online = True
                await asyncio.sleep(random.randint(5, 15))
            
            async with client.action(BOYFRIEND_ID, 'typing'):
                await asyncio.sleep(random.randint(3, 7))
            
            await client.send_message(BOYFRIEND_ID, text)
            save_to_db(BOYFRIEND_ID, 'assistant', text)
            daily_messages_sent += 1
            print(f"Соня сама написала: {text}")
            
        except Exception as e:
            print(f"Ошибка инициативы: {e}")

async def presence_manager():
    global is_online
    while True:
        online_time = random.randint(120, 600)
        offline_time = random.randint(900, 2700)
        try:
            await client(functions.account.UpdateStatusRequest(offline=False))
            is_online = True
            await asyncio.sleep(online_time)
            await client(functions.account.UpdateStatusRequest(offline=True))
            is_online = False
            await asyncio.sleep(offline_time)
        except Exception as e:
            await asyncio.sleep(60)

async def check_reactions_loop():
    last_checked_messages = {}
    while True:
        try:
            await asyncio.sleep(10)
            messages = await client.get_messages(BOYFRIEND_ID, limit=10)
            for msg in messages:
                if not msg.out: continue
                if msg.reactions and msg.reactions.results:
                    has_your_reaction = any(r.chosen for r in msg.reactions.results)
                    if has_your_reaction and msg.id not in last_checked_messages:
                        last_checked_messages[msg.id] = True
                        asyncio.create_task(maybe_react_to_own_message(BOYFRIEND_ID, msg.id, ""))
            
            if len(last_checked_messages) > 50:
                last_checked_messages.clear()
        except Exception as e:
            print(f"Ошибка чек реакций: {e}")
            await asyncio.sleep(20)

async def maybe_react_to_own_message(chat_id, message_id, text):
    if random.random() > 0.25: return
    await asyncio.sleep(random.uniform(2, 8))
    reactions = ['😅', '🙈', '😳', '🥰', '❤️']
    try:
        await client.send_reaction(chat_id, message_id, random.choice(reactions))
    except: pass

async def maybe_react_to_message(event, message_text):
    if random.random() > 0.4: return
    text_lower = message_text.lower()
    if any(w in text_lower for w in ['люблю', 'милая', 'красивая']): reactions = ['❤️', '🥰', '😘']
    elif any(w in text_lower for w in ['ахах', 'лол', 'смеш']): reactions = ['😂', '🤣']
    elif any(w in text_lower for w in ['груст', 'плохо']): reactions = ['😢', '🥺']
    else: reactions = ['👍', '❤️', '😊']
    try:
        await asyncio.sleep(random.uniform(1, 4))
        await client.send_reaction(event.chat_id, event.id, random.choice(reactions))
    except: pass

# --- MAIN HANDLER ---
@client.on(events.NewMessage(incoming=True))
async def handler(event):
    global is_online, is_offended, offended_until
    if event.is_group or event.is_channel: return
    
    user_id = event.sender_id
    text = event.text if event.text else ""

    # === БЛОК ФОТО ===
    if event.photo:
        await client.send_read_acknowledge(event.chat_id, max_id=event.id)
        photo_path = await event.download_media()
        
        async with client.action(event.chat_id, 'typing'):
            # Вызываем зрение ОДИН раз
            raw_res = get_vision_response(photo_path, user_id)
            
            # Чистим ответ от технических тегов
            if "[MEMORY:" in raw_res:
                parts = raw_res.split("[MEMORY:", 1)
                reply_to_user = parts[0].strip()
                memory_content = parts[1].split("]", 1)[0].strip()
                save_to_db(user_id, 'assistant', f"[видела на фото: {memory_content}]")
            else:
                reply_to_user = raw_res
                save_to_db(user_id, 'assistant', f"[видела какое-то фото]")

            final_text = make_typos(reply_to_user.lower().replace('.', '').strip())
            
            if os.path.exists(photo_path):
                os.remove(photo_path)
            
            await asyncio.sleep(random.randint(3, 6))
            await event.respond(final_text)
        return
    # ==============================

    # Обида
    if user_id == BOYFRIEND_ID and check_if_offensive(text):
        is_offended = True
        offended_until = datetime.now() + timedelta(hours=random.randint(2, 6))
        print(f"Обиделась до {offended_until}")

    if is_offended and user_id == BOYFRIEND_ID:
        if datetime.now() < offended_until:
            await asyncio.sleep(random.randint(2, 8))
            await event.respond(random.choice(["отвали", "бесишь", "ой всё"]))
            return
        else:
            is_offended = False
            await event.respond("ладно, проехали")
            return

    # Школа
    kld_now = datetime.now(pytz.timezone('Europe/Kaliningrad'))
    if (9 <= kld_now.hour < 15) and kld_now.weekday() < 5 and user_id == BOYFRIEND_ID and random.random() < 0.3:
        await asyncio.sleep(random.randint(10, 30))
        await event.respond(random.choice(["на уроке", "щас контрольная", "потом"]))
        return

    # Онлайн статус
    if is_online: await asyncio.sleep(random.randint(1, 4))
    else:
        await asyncio.sleep(random.randint(10, 30))
        try: 
            await client(functions.account.UpdateStatusRequest(offline=False))
            is_online = True
        except: pass

    # Реакции
    if user_id == BOYFRIEND_ID:
        await maybe_react_to_message(event, text)
        try: await client.send_read_acknowledge(event.chat_id, max_id=event.id)
        except: pass

    # Ответ (текст)
    reply = await get_ai_response(text, user_id)
    
    # Отправка (возможно частями)
    messages_to_send = [reply]
    if len(reply) > 30 and random.random() < 0.3:
        parts = reply.split(' ', 1)
        if len(parts) > 1: messages_to_send = parts

    last_msg_id = None
    for msg in messages_to_send:
        msg = make_typos(msg)
        typing_sec = max(1.5, min(len(msg) / 4, 7))
        async with client.action(event.chat_id, 'typing'):
            await asyncio.sleep(typing_sec)
        sent = await event.respond(msg)
        last_msg_id = sent.id
        await asyncio.sleep(random.uniform(0.5, 1.5))
    
    if last_msg_id and user_id == BOYFRIEND_ID:
        asyncio.create_task(maybe_react_to_own_message(event.chat_id, last_msg_id, reply))

# --- ЗАПУСК ---
async def health_check(request): return web.Response(text="Alive")
app = web.Application()
app.router.add_get('/', health_check)

async def main():
    init_db()
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', int(os.environ.get('PORT', 10000))).start()
    await client.start(phone)
    
    asyncio.create_task(presence_manager())
    asyncio.create_task(thoughts_loop())
    asyncio.create_task(check_reactions_loop())
    
    print("Соня v3.0 (с глазами) запущена! 👀💕")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())

