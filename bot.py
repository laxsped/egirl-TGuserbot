from telethon import TelegramClient, events, functions
import requests
import asyncio
import random
import os
import base64
import psycopg2
from aiohttp import web
from datetime import datetime
import pytz

is_online = False
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

async def thoughts_loop():
    daily_messages_sent = 0  # Счётчик сообщений за день
    last_reset_day = datetime.now().day
    
    while True:
        await asyncio.sleep(random.randint(1800, 3600))  # 30-60 мин
        
        # Сбрасываем счётчик в новый день
        current_day = datetime.now().day
        if current_day != last_reset_day:
            daily_messages_sent = 0
            last_reset_day = current_day
        
        # Максимум 3 сообщения от неё первой в день
        if daily_messages_sent >= 3:
            continue
        
        # Проверяем время (МСК)
        moscow_time = datetime.now(pytz.timezone('Europe/Kaliningrad'))
        hour = moscow_time.hour
        
        # Пишет только с 8:00 до 23:00
        if not (8 <= hour <= 23):
            continue
        
        # Шанс 20% написать
        if random.random() > 0.2:
            continue
        
        # Проверяем когда было последнее сообщение
        history = get_history_from_db(BOYFRIEND_ID, limit=1)
        # Если история пустая или последнее сообщение давно
        
        # Генерим сообщение в зависимости от времени
        if 8 <= hour < 11:
            prompts = [
                "напиши лёше доброе утро",
                "спроси как он спал",
                "пожелай хорошего дня"
            ]
        elif 11 <= hour < 15:
            prompts = [
                "спроси что он делает",
                "напиши что скучаешь",
                "спроси пойдёт ли гулять"
            ]
        elif 15 <= hour < 18:
            prompts = [
                "напиши что вышла из школы наконец",
                "спроси как у него дела",
                "пожалуйся на учителей шутливо"
            ]
        elif 18 <= hour < 22:
            prompts = [
                "спроси чем он занят",
                "напиши что скучаешь",
                "предложи погулять завтра"
            ]
        else:  # 22-23
            prompts = [
                "напиши что собираешься спать",
                "пожелай спокойной ночи",
                "спроси не спит ли он ещё"
            ]
        
        prompt = random.choice(prompts)
        
        try:
            response = requests.post(
                'https://api.groq.com/openai/v1/chat/completions',
                headers={'Authorization': f'Bearer {GROQ_API_KEY}'},
                json={
                    'model': 'llama-3.3-70b-versatile',
                    'messages': [
                        {'role': 'system', 'content': SYSTEM_PROMPT_BOYFRIEND},
                        {'role': 'user', 'content': prompt}
                    ],
                    'temperature': 0.9
                }
            )
            text = response.json()['choices'][0]['message']['content']
            text = make_typos(text)
            
            # Заходим в онлайн если офлайн
            global is_online
            if not is_online:
                await client(functions.account.UpdateStatusRequest(offline=False))
                is_online = True
                await asyncio.sleep(random.randint(5, 15))
            
            # Печатаем и отправляем
            async with client.action(BOYFRIEND_ID, 'typing'):
                await asyncio.sleep(random.randint(3, 7))
            
            await client.send_message(BOYFRIEND_ID, text)
            save_to_db(BOYFRIEND_ID, 'assistant', text)
            daily_messages_sent += 1
            print(f"Соня проявила инициативу ({daily_messages_sent}/3 за день): {text}")
            
        except Exception as e:
            print(f"Ошибка инициативы: {e}")
            
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
    global is_online
    while True:
        # Онлайн 2-10 минут
        online_time = random.randint(120, 600)
        # Офлайн 15-45 минут
        offline_time = random.randint(900, 2700)
        
        try:
            # Ставим онлайн
            await client(functions.account.UpdateStatusRequest(offline=False))
            is_online = True
            print(f"Соня онлайн на {online_time//60} мин")
            await asyncio.sleep(online_time)
            
            # Ставим офлайн
            await client(functions.account.UpdateStatusRequest(offline=True))
            is_online = False
            print(f"Соня офлайн на {offline_time//60} мин")
            await asyncio.sleep(offline_time)
        except Exception as e:
            print(f"Ошибка статуса: {e}")
            await asyncio.sleep(60)


async def get_ai_response(message, user_id, user_name):
    is_boyfriend = (user_id == BOYFRIEND_ID)
    
    # Определяем время (МСК)
    moscow_time = datetime.now(pytz.timezone('Europe/Kaliningrad'))
    current_time_str = moscow_time.strftime("%H:%M")
    current_day = moscow_time.strftime("%A") # День недели на английском (можно перевести)

    # Добавляем ПРЯМОЙ КОНТЕКСТ в системный промпт
    time_context = f"\n\nТЕКУЩИЙ КОНТЕКСТ: Сейчас {current_time_str}, день недели - {current_day}. " \
                   f"Учитывай время суток в ответах (ночь, утро, день)."

    system_prompt = SYSTEM_PROMPT_BOYFRIEND + time_context if is_boyfriend else SYSTEM_PROMPT_OTHERS
    
    save_to_db(user_id, 'user', message)
    history = get_history_from_db(user_id, limit=40)
    
    try:
        response = requests.post(
            'https://api.groq.com/openai/v1/chat/completions',
            headers={'Authorization': f'Bearer {GROQ_API_KEY}'},
            json={
                'model': 'llama-3.3-70b-versatile',
                'messages': [{'role': 'system', 'content': system_prompt}] + history,
                'temperature': 0.8
            }
        )
        data = response.json()
        result = data['choices'][0]['message']['content']
        save_to_db(user_id, 'assistant', result)
        return result
    except Exception as e:
        print(f"Ошибка: {e}")
        return "сорян зависло"

@client.on(events.NewMessage(incoming=True))
async def handler(event):
    global is_online
    
    if event.is_group or event.is_channel: 
        return
    
    user_id = event.sender_id
    
    # 1. Шанс на игнор только если ОФЛАЙН
    if not is_online and random.random() < 0.1:
        print("Соня офлайн, проигнорила")
        return
    
    # 2. Задержка зависит от статуса
    if is_online:
        await asyncio.sleep(random.randint(5, 30))
    else:
        await asyncio.sleep(random.randint(300, 7200))
        await client(functions.account.UpdateStatusRequest(offline=False))
        is_online = True
        await asyncio.sleep(random.randint(10, 40))
    
    # 3. НОВОЕ: Иногда сначала ставит реакцию, потом отвечает
    if random.random() < 0.3 and user_id == BOYFRIEND_ID:
        await maybe_react_to_message(event, event.text)
        await asyncio.sleep(random.uniform(2, 5))  # Потом думает что ответить
    
    # 4. Прочитываем
    try: 
        await client.send_read_acknowledge(event.chat_id, max_id=event.id)
    except: 
        pass
    
    # 5. Генерим ответ
    reply = await get_ai_response(event.text, user_id, "")
    
    # 6. Double messaging
    messages_to_send = [reply]
    if len(reply) > 30 and random.random() < 0.3:
        parts = reply.split(' ', 1)
        if len(parts) > 1:
            messages_to_send = parts
    
    last_message_id = None
    for msg in messages_to_send:
        msg = make_typos(msg)
        typing_time = max(2, min(len(msg) / random.uniform(2.5, 3.5), 10))
        
        async with client.action(event.chat_id, 'typing'):
            await asyncio.sleep(typing_time)
        
        sent_msg = await event.respond(msg)
        last_message_id = sent_msg.id
        await asyncio.sleep(random.uniform(1, 3))
    
    # 7. НОВОЕ: Иногда реагирует на своё последнее сообщение
    if last_message_id and user_id == BOYFRIEND_ID:
        asyncio.create_task(maybe_react_to_own_message(event.chat_id, last_message_id, reply))

# --- ЛОГИКА РЕАКЦИЙ ---
async def maybe_react_to_message(event, message_text):
    """Соня иногда ставит реакции на твои сообщения"""
    
    # Шанс 40% поставить реакцию
    if random.random() > 0.4:
        return
    
    # Определяем реакцию по содержанию сообщения
    text_lower = message_text.lower()
    
    # Эмоциональные ключевые слова
    if any(word in text_lower for word in ['люблю', 'любишь', 'милая', 'красивая', 'скучаю']):
        reactions = ['❤️', '🥰', '😘', '💕']
    elif any(word in text_lower for word in ['ахах', 'хаха', 'лол', 'смешно', 'дурак', 'дурачок']):
        reactions = ['😂', '🤣', '😄']
    elif any(word in text_lower for word in ['грустно', 'плохо', 'устал', 'болею']):
        reactions = ['😢', '🥺', '😭']
    elif any(word in text_lower for word in ['пойдем', 'погуляем', 'встретимся', 'увидимся']):
        reactions = ['🥰', '😊', '🤗']
    elif any(word in text_lower for word in ['фото', 'селфи', 'выглядишь']):
        reactions = ['😍', '🔥', '😳']
    else:
        # Обычные нейтральные реакции
        reactions = ['👍', '❤️', '😊', '🙂']
    
    # Выбираем случайную реакцию
    reaction = random.choice(reactions)
    
    try:
        await asyncio.sleep(random.uniform(1, 4))  # Небольшая задержка
        await client.send_reaction(event.chat_id, event.id, reaction)
        print(f"Соня поставила реакцию: {reaction}")
    except Exception as e:
        print(f"Ошибка реакции: {e}")

async def maybe_react_to_own_message(chat_id, message_id, her_message_text):
    """Соня иногда реагирует на СВОИ сообщения после твоей реакции"""
    
    # Шанс 25% отреагировать на своё сообщение
    if random.random() > 0.25:
        return
    
    # Ждём 2-8 секунд (будто увидела что ты отреагировал)
    await asyncio.sleep(random.uniform(2, 8))
    
    # Реагирует на своё сообщение
    reactions = ['😅', '🙈', '😳', '🥰', '❤️']
    reaction = random.choice(reactions)
    
    try:
        await client.send_reaction(chat_id, message_id, reaction)
        print(f"Соня отреагировала на своё сообщение: {reaction}")
    except Exception as e:
        print(f"Ошибка своей реакции: {e}")
        
# Web сервер для Render
async def health_check(request): 
    return web.Response(text="Alive")

app = web.Application()
app.router.add_get('/', health_check)

# --- ОБРАБОТЧИК РЕАКЦИЙ НА ЕЁ СООБЩЕНИЯ ---
@client.on(events.MessageReactions)
async def on_reaction_update(event):
    """Ловим когда ты ставишь реакцию на её сообщение"""
    try:
        # Проверяем что это диалог с тобой
        if event.peer_id.user_id == BOYFRIEND_ID:
            # Соня видит что ты отреагировал и может отреагировать сама на своё сообщение
            asyncio.create_task(maybe_react_to_own_message(
                event.peer_id.user_id,
                event.msg_id,
                ""
            ))
    except Exception as e:
        print(f"Ошибка обработки реакции: {e}")

async def main():
    init_db()
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', int(os.environ.get('PORT', 10000))).start()
    
    await client.start(phone)
    
    # Запускаем все фоновые процессы
    asyncio.create_task(presence_manager())
    asyncio.create_task(thoughts_loop())
    
    print("Соня ожила и думает о тебе...")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
