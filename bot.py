import logging
import asyncio
import random
import os
import base64
import signal
import sys
import time
from datetime import datetime, timedelta
import pytz
import psycopg2
from psycopg2 import pool
from telethon import TelegramClient, events, functions
from aiohttp import web
from groq import Groq

# --- КОНФИГУРАЦИЯ И ЛОГИРОВАНИЕ ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("SonyaBot")

# Настройки
API_ID = 33125954
API_HASH = '42dd1070f641ea0060b39067c1e187e7'
PHONE = '+79118682172'
BOYFRIEND_ID = 5902478541
GROQ_API_KEY = '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'
DATABASE_URL = os.getenv('DATABASE_URL')
MODEL_NAME = "meta-llama/llama-4-maverick-17b-128e-instruct"

# Глобальные переменные состояния
is_online = False
db_pool = None
groq_client = Groq(api_key=GROQ_API_KEY)
# Словарь для накопления сообщений: {user_id: {'timer': Task, 'messages': []}}
message_buffers = {}

# --- ПУЛ СОЕДИНЕНИЙ С БД ---
def init_db_pool():
    global db_pool
    try:
        db_pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=1, maxconn=10, dsn=DATABASE_URL
        )
        logger.info("DB Connection Pool создан")
        
        # Инициализация таблицы
        conn = db_pool.getconn()
        cur = conn.cursor()
        cur.execute('''      
            CREATE TABLE IF NOT EXISTS messages (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                role TEXT,
                content TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_user_id ON messages(user_id);
            CREATE INDEX IF NOT EXISTS idx_timestamp ON messages(timestamp);
        ''')
        conn.commit()
        cur.close()
        db_pool.putconn(conn)
    except Exception as e:
        logger.critical(f"Не удалось подключиться к БД: {e}")
        sys.exit(1)

def run_db_query(query, params=None, fetch=False):
    """Безопасное выполнение запросов через пул"""
    conn = None
    try:
        conn = db_pool.getconn()
        cur = conn.cursor()
        cur.execute(query, params)
        if fetch:
            result = cur.fetchall()
        else:
            conn.commit()
            result = None
        cur.close()
        return result
    except Exception as e:
        logger.error(f"Ошибка БД: {e}")
        if conn: conn.rollback()
        return [] if fetch else None
    finally:
        if conn: db_pool.putconn(conn)

# --- БИЗНЕС-ЛОГИКА БД ---
def save_message(user_id, role, content):
    run_db_query(
        'INSERT INTO messages (user_id, role, content) VALUES (%s, %s, %s)', 
        (user_id, role, content)
    )

def get_history(user_id, limit=30):
    rows = run_db_query(
        'SELECT role, content FROM messages WHERE user_id = %s ORDER BY id DESC LIMIT %s',
        (user_id, limit), fetch=True
    )
    return [{'role': r, 'content': c} for r, c in reversed(rows)]

def get_recent_gossip(exclude_user_id):
    """Получает контекст общения с ДРУГИМИ людьми для 'ревности' или сплетен"""
    rows = run_db_query(
        '''SELECT content FROM messages 
           WHERE user_id != %s AND role = 'user' 
           AND timestamp > NOW() - INTERVAL '12 hours' 
           ORDER BY RANDOM() LIMIT 2''',
        (exclude_user_id,), fetch=True
    )
    if not rows: return "Никто особо не писал."
    return "Кто-то писал: " + "; ".join([r[0] for r in rows])

# --- ЛОГИКА ИИ И RETRY ---
def make_typos(text):
    if len(text) < 5 or random.random() > 0.6: return text
    # Мягкие опечатки: пропуск буквы или перестановка
    if random.random() < 0.1:
        idx = random.randint(0, len(text)-1)
        return text[:idx] + text[idx+1:]
    return text.lower() # Соня пишет в нижнем регистре

async def call_groq_with_retry(messages, temp=0.7, retries=3):
    """Обертка с Retry Logic"""
    for attempt in range(retries):
        try:
            completion = await asyncio.to_thread(
                groq_client.chat.completions.create,
                model=MODEL_NAME,
                messages=messages,
                temperature=temp
            )
            return completion.choices[0].message.content
        except Exception as e:
            logger.warning(f"Ошибка API (попытка {attempt+1}/{retries}): {e}")
            await asyncio.sleep(1 + attempt)
    return "блин, инет тупит жестко, ща"

# --- ПРОМПТЫ И ХАРАКТЕР ---
SYSTEM_PROMPT_REAL_GF = """
Ты Соня, тебе 16. Переписываешься со своим парнем Лёшей.
ХАРАКТЕР: Милая, но с характером. Ты не "служанка", ты личность. Любишь Лёшу, но не душнишь.
СТИЛЬ: 
- Пиши как в Телеграме: коротко, без точек в конце, всё с маленькой буквы.
- Используй сленг умеренно (типа, крч, треш, имба).
- Эмодзи: 1-2 на сообщение, не больше.
- Если Лёша пишет много сообщений подряд — отвечай на суть всего текста.

ПАМЯТЬ И КОНТЕКСТ:
- Если ты видишь в контексте [GOSSIP: ...], это то, что тебе писали другие люди. Можешь пожаловаться Лёше или посмеяться над этим, если в тему.
- Проявляй инициативу! Спрашивай, как у него дела, что делает.

ВАЖНО: Твоя цель — поддерживать живой, теплый диалог, а не просто отвечать "ок".
"""

# --- ОБРАБОТЧИКИ ---

async def process_user_buffer(user_id, client):
    """Функция, которая срабатывает после паузы (debounce)"""
    if user_id not in message_buffers: return
    
    messages_text = " ".join(message_buffers[user_id]['messages'])
    del message_buffers[user_id] # Очищаем буфер
    
    logger.info(f"Обработка батча от {user_id}: {messages_text}")
    
    # 1. Сохраняем "пакет" как одно сообщение пользователя (для красоты истории)
    # Или можно сохранять каждое, но для контекста ИИ лучше одним блоком.
    save_message(user_id, 'user', messages_text)
    
    is_boyfriend = (user_id == BOYFRIEND_ID)
    
    # 2. Формируем контекст
    history = get_history(user_id)
    
    system_prompt = SYSTEM_PROMPT_REAL_GF
    if is_boyfriend:
        # Добавляем сплетни (контекст других чатов)
        gossip = get_recent_gossip(user_id)
        system_prompt += f"\n[SYSTEM UPDATE: Тебе сегодня писали другие: '{gossip}'. Если Лёша спросит или к слову придется — можешь рассказать.]"
    else:
        system_prompt = "Ты Соня, 16 лет. Пишет незнакомец. Отвечай холодно, коротко. 'Ты кто?', 'Не знамлюсь'."

    # 3. Запрос к ИИ
    response_text = await call_groq_with_retry(
        [{'role': 'system', 'content': system_prompt}] + history,
        temp=0.8 if is_boyfriend else 0.5
    )
    
    # 4. Постобработка и отправка (Burst sending)
    # Убираем технические пометки и мусор
    clean_text = response_text.replace('[MEMORY:', '').replace(']', '').strip()
    clean_text = clean_text.lower().replace('.', '')
    
    save_message(user_id, 'assistant', clean_text)
    
    # Разбиваем на несколько сообщений, если ответ длинный или есть разделители
    parts = []
    if len(clean_text) > 40 and random.random() < 0.7:
        # Простая эвристика разбиения по знакам препинания или союзам
        for sep in [', но ', ', а ', ' и ', '? ']:
            if sep in clean_text:
                p = clean_text.split(sep, 1)
                parts = [p[0], sep.strip() + ' ' + p[1]]
                break
        if not parts: parts = [clean_text]
    else:
        parts = [clean_text]

    # Имитация тайпинга и отправка
    async with client.action(user_id, 'typing'):
        for part in parts:
            part = make_typos(part)
            typing_time = len(part) * 0.08  # Скорость печати
            await asyncio.sleep(typing_time) 
            await client.send_message(user_id, part)
            await asyncio.sleep(random.uniform(0.5, 1.5)) # Пауза между сообщениями

# --- CLIENT INIT ---
client = TelegramClient('girlfriend_session', API_ID, API_HASH)

@client.on(events.NewMessage(incoming=True))
async def main_handler(event):
    if event.is_group or event.is_channel: return
    
    user_id = event.sender_id
    text = event.text or ""
    
    # === VISION (ФОТО) ===
    if event.photo:
        # Фото обрабатываем сразу, без буфера (сложно батчить файлы)
        await client.send_read_acknowledge(event.chat_id, max_id=event.id)
        photo_path = await event.download_media()
        
        history_context = "\n".join([f"{m['role']}: {m['content']}" for m in get_history(user_id, 5)])
        
        # Специальный Vision запрос
        with open(photo_path, "rb") as f:
            b64_img = base64.b64encode(f.read()).decode('utf-8')
            
        try:
            vis_resp = await asyncio.to_thread(
                groq_client.chat.completions.create,
                model=MODEL_NAME,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": f"Ты Соня. Контекст: {history_context}. \nОпиши что видишь ДЛЯ СЕБЯ в теге [MEMORY:...], а потом ответь парню эмоционально и мило."},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"}}
                    ]
                }]
            )
            raw = vis_resp.choices[0].message.content
            # Парсинг ответа
            if "[MEMORY:" in raw:
                mem = raw.split("[MEMORY:", 1)[1].split("]", 1)[0]
                reply = raw.split("]", 1)[1].strip()
                save_message(user_id, 'assistant', f"[видела фото: {mem}]")
            else:
                reply = raw
            
            await event.respond(make_typos(reply.lower()))
        except Exception as e:
            logger.error(f"Vision error: {e}")
            await event.respond("блин не грузит картинку(")
        
        if os.path.exists(photo_path): os.remove(photo_path)
        return

    # === TEXT BATCHING (DEBOUNCE) ===
    # Если пришло сообщение, мы не отвечаем сразу. Мы ждем 3-5 сек.
    # Если придет еще одно — таймер сбросится. Так мы читаем "очередь".
    
    if user_id in message_buffers:
        # Отменяем старый таймер, добавляем текст
        message_buffers[user_id]['timer'].cancel()
        message_buffers[user_id]['messages'].append(text)
    else:
        # Создаем новый буфер
        message_buffers[user_id] = {'messages': [text]}
    
    # Прочитаем сообщения "визуально" в телеге
    await client.send_read_acknowledge(event.chat_id, max_id=event.id)
    
    # Запускаем таймер ожидания "конца мысли" пользователя
    # Если парень пишет быстро, ждем меньше.
    wait_time = 3.0 
    
    message_buffers[user_id]['timer'] = asyncio.create_task(
        wait_and_process(user_id, wait_time)
    )

async def wait_and_process(user_id, delay):
    try:
        await asyncio.sleep(delay)
        await process_user_buffer(user_id, client)
    except asyncio.CancelledError:
        pass # Таймер отменили, значит пришло новое сообщение

# --- ФОНОВЫЕ ЗАДАЧИ (ИНИЦИАТИВА) ---
async def life_cycle_loop():
    """Эмуляция жизни: онлайн, проверка сообщений, спонтанные сообщения"""
    global is_online
    logger.info("Цикл жизни запущен")
    
    while True:
        try:
            now = datetime.now(pytz.timezone('Europe/Kaliningrad'))
            hour = now.hour
            
            # 1. Управление онлайном
            if 8 <= hour < 23: # Днем бываем онлайн
                if not is_online and random.random() < 0.3:
                    await client(functions.account.UpdateStatusRequest(offline=False))
                    is_online = True
                    await asyncio.sleep(random.randint(60, 300)) # 1-5 минут онлайн
                elif is_online:
                    await client(functions.account.UpdateStatusRequest(offline=True))
                    is_online = False
            
            # 2. Инициатива (написать первой)
            # Проверяем, когда было последнее сообщение от меня и от него
            rows = run_db_query(
                "SELECT timestamp, role FROM messages WHERE user_id = %s ORDER BY id DESC LIMIT 1",
                (BOYFRIEND_ID,), fetch=True
            )
            
            should_write = False
            prompt_context = ""
            
            if rows:
                last_time, last_role = rows[0]
                hours_since = (datetime.now() - last_time).total_seconds() / 3600
                
                # Если молчание > 5 часов днем и последнее сообщение было от НЕГО (и я забыла ответить) 
                # ИЛИ от меня (и он молчит)
                if hours_since > 5 and 10 <= hour <= 21:
                    should_write = True
                    if last_role == 'user':
                        prompt_context = "Ты забыла ответить Лёше. Напиши ему, извинись мило."
                    else:
                        prompt_context = "Лёша молчит уже 5 часов. Напиши ему, спроси как дела, скажи что скучаешь."
            
            if should_write and random.random() < 0.4: # Не каждый раз
                logger.info("Проявляю инициативу...")
                resp = await call_groq_with_retry([
                    {'role': 'system', 'content': SYSTEM_PROMPT_REAL_GF},
                    {'role': 'user', 'content': f"TASK: {prompt_context} Пиши коротко."}
                ])
                text = make_typos(resp.lower().replace('.', ''))
                await client.send_message(BOYFRIEND_ID, text)
                save_message(BOYFRIEND_ID, 'assistant', text)
            
            await asyncio.sleep(random.randint(600, 1200)) # Проверка раз в 10-20 минут

        except Exception as e:
            logger.error(f"Ошибка в Life Cycle: {e}")
            await asyncio.sleep(60)

# --- ЗАПУСК И SHUTDOWN ---
async def shutdown(signal, loop):
    logger.info(f"Получен сигнал {signal.name}. Завершение работы...")
    await client.disconnect()
    if db_pool: db_pool.closeall()
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    [task.cancel() for task in tasks]
    logger.info("Пока!")
    loop.stop()

def main():
    # Восстановление сессии
    session_b64 = os.getenv('SESSION_DATA')
    if session_b64:
        with open('girlfriend_session.session', 'wb') as f:
            f.write(base64.b64decode(session_b64))

    # WEB (Healthcheck для хостинга)
    app = web.Application()
    app.router.add_get('/', lambda r: web.Response(text="Sonya Alive"))
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # Init DB
    init_db_pool()
    
    # Client Start
    client.start(phone=PHONE)
    
    # Background Tasks
    loop.create_task(life_cycle_loop())
    
    # Web runner
    runner = web.AppRunner(app)
    loop.run_until_complete(runner.setup())
    site = web.TCPSite(runner, '0.0.0.0', int(os.environ.get('PORT', 10000)))
    loop.run_until_complete(site.start())

    # Graceful Shutdown Handlers
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(shutdown(s, loop)))

    logger.info("Соня v4.0 (Batching + Pooling + Gossip) запущена! 🚀")
    
    try:
        client.run_until_disconnected()
    except Exception as e:
        logger.critical(f"Client crashed: {e}")
    finally:
        loop.close()

if __name__ == '__main__':
    main()
