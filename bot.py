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

is_online = False
is_offended = False
offended_until = None

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

def check_if_offensive(text):
    """Проверка на обидные слова для режима ссоры"""
    offensive_words = [
        'дура', 'тупая', 'достала', 'заебала', 'отстань пж', 
        'надоела', 'бесишь', 'идиотка', 'глупая', 'stupid'
    ]
    return any(word in text.lower() for word in offensive_words)

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
        
        # НОВОЕ: Проверяем когда было последнее сообщение от тебя (ревность)
        is_jealous = False
        try:
            conn = psycopg2.connect(DATABASE_URL)
            cur = conn.cursor()
            cur.execute('''
                SELECT timestamp FROM messages 
                WHERE user_id = %s AND role = 'user' 
                ORDER BY timestamp DESC LIMIT 1
            ''', (BOYFRIEND_ID,))
            last_msg = cur.fetchone()
            cur.close()
            conn.close()
            
            if last_msg:
                hours_since = (datetime.now() - last_msg[0]).total_seconds() / 3600
                if hours_since > 6:
                    is_jealous = True
        except:
            pass
        
        # Генерим сообщение
        if is_jealous:
            prompts = [
                "напиши лёше что он куда-то пропал и ты беспокоишься",
                "спроси где он был, немного обиженно",
                "напиши что ты ждала его сообщения",
                "спроси с кем он общался всё это время, немного ревнуя"
            ]
        elif 8 <= hour < 11:
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
        else:
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
                    'temperature': 1.1
                }
            )
            text = response.json()['choices'][0]['message']['content']
            text = make_typos(text)
            
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
            print(f"Соня проявила инициативу ({daily_messages_sent}/3 за день): {text}")
            
        except Exception as e:
            print(f"Ошибка инициативы: {e}")

def make_typos(text):
    # Увеличиваем шанс опечатки до 40%
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

async def presence_manager():
    global is_online
    while True:
        online_time = random.randint(120, 600)
        offline_time = random.randint(900, 2700)
        
        try:
            await client(functions.account.UpdateStatusRequest(offline=False))
            is_online = True
            print(f"Соня онлайн на {online_time//60} мин")
            await asyncio.sleep(online_time)
            
            await client(functions.account.UpdateStatusRequest(offline=True))
            is_online = False
            print(f"Соня офлайн на {offline_time//60} мин")
            await asyncio.sleep(offline_time)
        except Exception as e:
            print(f"Ошибка статуса: {e}")
            await asyncio.sleep(60)

async def get_ai_response(message, user_id, user_name):
    is_boyfriend = (user_id == BOYFRIEND_ID)
    
    kld_time = datetime.now(pytz.timezone('Europe/Kaliningrad'))
    current_time_str = kld_time.strftime("%H:%M")
    
    # ЖЕСТКИЙ ПРOМПТ ДЛЯ ВОЗВРАТА СТИЛЯ
    SONYA_STYLE = (
        "Ты Соня, тебе 16. Твой стиль: ПОЛНЫЙ ИГНОР ЗАГЛАВНЫХ БУКВ И ТОЧЕК В КОНЦЕ. "
        "Пиши как реальная девчонка в телеге: коротко, сленгом, иногда с кучей лишних букв (нееет, блиннн). "
        "ЗАПРЕТ: Не используй время и цифры в ответах, если тебя об этом не спросили прямо. "
        "ЗАПРЕТ: Не ставь больше одного смайлика. "
        "Если Лёша бесит — отвечай дерзко. Если скучаешь — мило, но по-детски."
    )

    time_context = f"\n(Для справки: сейчас {current_time_str}, но не упоминай это просто так)."

    system_prompt = SONYA_STYLE if is_boyfriend else SYSTEM_PROMPT_OTHERS
    
    save_to_db(user_id, 'user', message)
    history = get_history_from_db(user_id, limit=40)
    
    try:
        response = requests.post(
            'https://api.groq.com/openai/v1/chat/completions',
            headers={'Authorization': f'Bearer {GROQ_API_KEY}'},
            json={
                'model': 'llama-3.3-70b-versatile',
                'messages': [{'role': 'system', 'content': system_prompt}] + history,
                'temperature': 1.0, # Больше рандома! 🚀
                'presence_penalty': 0.6 # Чтобы не повторялась
            }
        )
        data = response.json()
        result = data['choices'][0]['message']['content'].lower().replace('.', '') # Убираем точки
        save_to_db(user_id, 'assistant', result)
        return result
    except Exception as e:
        print(f"Ошибка: {e}")
        return "блин зависла"

@client.on(events.NewMessage(incoming=True))
async def handler(event):
    global is_online, is_offended, offended_until
    
    if event.is_group or event.is_channel: 
        return
    
    user_id = event.sender_id
    
    # НОВОЕ #20: Проверяем на обидные слова
    if user_id == BOYFRIEND_ID and check_if_offensive(event.text):
        is_offended = True
        offended_until = datetime.now() + timedelta(hours=random.randint(2, 6))
        print(f"Соня обиделась! До {offended_until.strftime('%H:%M')}")
    
    # НОВОЕ #20: Если обижена - отвечает сухо
    if is_offended and user_id == BOYFRIEND_ID:
    if datetime.now() < offended_until:
        cold_responses = ["отвали", "бесишь", "пфф", "ой всё", "мда"] # Более живые ответы
        await asyncio.sleep(random.randint(2, 10)) # Не заставляй себя ждать по 3 минуты!
        await event.respond(random.choice(cold_responses))
        return
        else:
            # Помирилась
            is_offended = False
            makeup_msg = random.choice([
                "ладно, не обижаюсь уже",
                "прости что молчала",
                "соскучилась"
            ])
            await asyncio.sleep(random.randint(10, 30))
            await event.respond(makeup_msg)
            print("Соня помирилась")
            return
    
    # НОВОЕ #4: Режим "занята" (школа)
    moscow_time = datetime.now(pytz.timezone('Europe/Kaliningrad'))
    hour = moscow_time.hour
    is_school_time = (9 <= hour < 15) and moscow_time.weekday() < 5
    
    if is_school_time and user_id == BOYFRIEND_ID and random.random() < 0.4:
        busy_responses = [
            "на уроке, потом отвечу",
            "щас контрольная",
            "не могу, на паре",
            "потом напишу ок?"
        ]
        await asyncio.sleep(random.randint(30, 120))
        await event.respond(random.choice(busy_responses))
        print("Соня на уроках")
        return
    
    if not is_online and random.random() < 0.1:
        print("Соня офлайн, проигнорила")
        return
    
    if is_online:
    await asyncio.sleep(random.randint(1, 5)) # Читает почти сразу
else:
    await asyncio.sleep(random.randint(10, 30)) # Заходит в сеть за полминуты
    await client(functions.account.UpdateStatusRequest(offline=False))
    is_online = True
        await asyncio.sleep(random.randint(10, 40))
    
    if random.random() < 0.3 and user_id == BOYFRIEND_ID:
        await maybe_react_to_message(event, event.text)
        await asyncio.sleep(random.uniform(2, 5))
    
    try: 
        await client.send_read_acknowledge(event.chat_id, max_id=event.id)
    except: 
        pass
    
    reply = await get_ai_response(event.text, user_id, "")
    
    messages_to_send = [reply]
    if len(reply) > 30 and random.random() < 0.3:
        parts = reply.split(' ', 1)
        if len(parts) > 1:
            messages_to_send = parts
    
    last_message_id = None
    for msg in messages_to_send:
        msg = make_typos(msg)
        
        # НОВОЕ #13: Улучшенная печать с паузами
        if random.random() < 0.15:
            async with client.action(event.chat_id, 'typing'):
                await asyncio.sleep(random.uniform(2, 4))
            await asyncio.sleep(random.uniform(1, 3))
        
        typing_time = max(2, min(len(msg) / random.uniform(2.5, 3.5), 10))
        
        if random.random() < 0.1 and len(msg) > 20:
            async with client.action(event.chat_id, 'typing'):
                await asyncio.sleep(typing_time / 2)
            await asyncio.sleep(random.uniform(1, 2))
            async with client.action(event.chat_id, 'typing'):
                await asyncio.sleep(typing_time / 2)
        else:
            async with client.action(event.chat_id, 'typing'):
                await asyncio.sleep(typing_time)
        
        sent_msg = await event.respond(msg)
        last_message_id = sent_msg.id
        await asyncio.sleep(random.uniform(1, 3))
    
    if last_message_id and user_id == BOYFRIEND_ID:
        asyncio.create_task(maybe_react_to_own_message(event.chat_id, last_message_id, reply))

async def maybe_react_to_message(event, message_text):
    if random.random() > 0.4:
        return
    
    text_lower = message_text.lower()
    
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
        reactions = ['👍', '❤️', '😊', '🙂']
    
    reaction = random.choice(reactions)
    
    try:
        await asyncio.sleep(random.uniform(1, 4))
        await client.send_reaction(event.chat_id, event.id, reaction)
        print(f"Соня поставила реакцию: {reaction}")
    except Exception as e:
        print(f"Ошибка реакции: {e}")

async def maybe_react_to_own_message(chat_id, message_id, her_message_text):
    if random.random() > 0.25:
        return
    
    await asyncio.sleep(random.uniform(2, 8))
    
    reactions = ['😅', '🙈', '😳', '🥰', '❤️']
    reaction = random.choice(reactions)
    
    try:
        await client.send_reaction(chat_id, message_id, reaction)
        print(f"Соня отреагировала на своё сообщение: {reaction}")
    except Exception as e:
        print(f"Ошибка своей реакции: {e}")

async def health_check(request): 
    return web.Response(text="Alive")

app = web.Application()
app.router.add_get('/', health_check)

last_checked_messages = {}

async def check_reactions_loop():
    global last_checked_messages
    
    while True:
        try:
            await asyncio.sleep(8)
            
            messages = await client.get_messages(BOYFRIEND_ID, limit=15)
            
            for msg in messages:
                if not msg.out:
                    continue
                
                if msg.reactions and msg.reactions.results:
                    has_your_reaction = any(r.chosen for r in msg.reactions.results)
                    
                    if has_your_reaction:
                        if msg.id not in last_checked_messages:
                            print(f"Обнаружена твоя реакция на сообщение {msg.id}")
                            last_checked_messages[msg.id] = True
                            asyncio.create_task(maybe_react_to_own_message(
                                BOYFRIEND_ID,
                                msg.id,
                                ""
                            ))
            
            if len(last_checked_messages) > 50:
                keys_to_remove = list(last_checked_messages.keys())[:-30]
                for k in keys_to_remove:
                    del last_checked_messages[k]
                
        except Exception as e:
            print(f"Ошибка проверки реакций: {e}")
            await asyncio.sleep(20)

async def main():
    init_db()
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', int(os.environ.get('PORT', 10000))).start()
    
    await client.start(phone)
    
    asyncio.create_task(presence_manager())
    asyncio.create_task(thoughts_loop())
    asyncio.create_task(check_reactions_loop())
    
    print("Соня ожила, думает о тебе и иногда ревнует... 💕😤")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())


