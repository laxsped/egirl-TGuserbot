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

# Константы
API_ID = int(os.getenv('API_ID', '0'))
API_HASH = os.getenv('API_HASH')
PHONE = os.getenv('PHONE')
BOYFRIEND_ID = int(os.getenv('BOYFRIEND_ID', '0'))
GROQ_API_KEY = os.getenv('GROQ_API_KEY')
DATABASE_URL = os.getenv('DATABASE_URL')
MODEL_NAME = "meta-llama/llama-4-maverick-17b-128e-instruct"

# --- ВОССТАНОВЛЕНИЕ СЕССИИ ---
session_b64 = os.getenv('SESSION_DATA')
if session_b64:
    try:
        session_bytes = base64.b64decode(session_b64)
        with open('girlfriend_session.session', 'wb') as f:
            f.write(session_bytes)
        print("✅ Сессия успешно восстановлена из ENV!")
    except Exception as e:
        print(f"❌ Ошибка восстановления сессии: {e}")

# Инициализация клиента и API
client = TelegramClient('girlfriend_session', API_ID, API_HASH)
groq_client = Groq(api_key=GROQ_API_KEY)

# Глобальные переменные
is_online = False
db_pool = None
message_buffers = {}
shutdown_event = asyncio.Event()

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
        
def run_db_query(query, params=None, fetch=False):
    """Безопасное выполнение запросов через пул"""
    conn = None
    try:
        if not db_pool: return [] if fetch else None
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
    """Получает контекст общения с ДРУГИМИ людьми"""
    rows = run_db_query(
        '''SELECT content FROM messages 
           WHERE user_id != %s AND role = 'user' 
           AND timestamp > NOW() - INTERVAL '12 hours' 
           ORDER BY RANDOM() LIMIT 2''',
        (exclude_user_id,), fetch=True
    )
    if not rows: return "Никто особо не писал."
    return "Кто-то писал: " + "; ".join([r[0] for r in rows])

# --- ЛОГИКА ИИ ---
def make_typos(text):
    if len(text) < 5 or random.random() > 0.6: return text
    if random.random() < 0.1:
        idx = random.randint(0, len(text)-1)
        return text[:idx] + text[idx+1:]
    return text.lower()

async def call_groq_with_retry(messages, temp=0.7, retries=3):
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
            logger.warning(f"Ошибка API (попытка {attempt+1}): {e}")
            await asyncio.sleep(1 + attempt)
    return "блин инет тупит"

# --- ПРОМПТЫ ---
SYSTEM_PROMPT_REAL_GF = """
ты соня, тебе 16. ты переписываешься со своим парнем лёшей.
твой характер: ироничная, живая, чуть вредная. ты не помощник, ты реальная девчонка.

правила стиля:
- только маленькие буквы, иногда КАПС (крик, эмоции). точки — только если ты реально обиделась или хочешь подчеркнуть драму.
- сленг используй ЕСТЕСТВЕННО и редко. не надо вставлять его в каждое предложение. 
- примеры того, как ты можешь говорить: "пон", "жиза", "гад блесс", "рил", "хз", "кринж", "бтв", "имхо", "рофл". (используй их по одному и только к месту).
- никаких "телячьих ласок", никакой лишней вежливости и тупых вопросов.
- пиши короткими сообщениями, как в тг.
- мат разрешен для эмоций, но не перегибай.

важно: 
- отвечай только на то, что пишет лёша. 
- НЕ ВСТАВЛЯЙ сленг просто так, если не знаешь что сказать.
- не выдумывай истории. спрашивай только по делу или если он пропал на полдня.

КОНТЕКСТ:
- если видишь [GOSSIP: ...], можешь поинтересоваться этой темой, но не копируй сам тег.
"""

SYSTEM_PROMPT_STRANGER = """
Твое имя Соня, тебе 16. Тебе пишет какой-то левый чел (не твой парень). 
ТВОЙ ВАЙБ: 
- Ты максимально холодная и закрытая. 
- Отвечаешь коротко (1-3 слова). 
- если замечаешь феминитивы (например, "я сделала", "я сказала", обязательно от лица собеседника) - становишься чуть мягче.
- используешь минимум смайликов, типа "😒", "😐", "🥱".
- Если начинают подкатывать — сразу кидай в игнор или отвечай "мда", "пон", "ясно".
- Ты не должна знакомиться (в романтическом плане). У тебя есть парень Лёша, и тебе на других лавеласов пофиг, только дружба.
- Если чел адекватный и спрашивает по делу (например, по учебе) — ответь сухо, но без агрессии.
- Если чел адекватный и хочет дружить — прояви интерес или дай нейтральный отказ.
"""

# --- ОБРАБОТКА СООБЩЕНИЙ (BATCHING) ---
async def process_user_buffer(user_id):
    if user_id not in message_buffers: return
    
    buffer_data = message_buffers.pop(user_id)
    messages_text = " ".join(buffer_data['messages'])
    
    logger.info(f"Обработка батча от {user_id}: {messages_text}")
    
    # Сохраняем как одно сообщение пользователя
    save_message(user_id, 'user', messages_text)
    
    is_boyfriend = (user_id == BOYFRIEND_ID)
    history = get_history(user_id)
    
    system_prompt = SYSTEM_PROMPT_REAL_GF
    if is_boyfriend:
        gossip = get_recent_gossip(user_id)
        system_prompt += f"\n[SYSTEM UPDATE: Тебе сегодня писали другие: '{gossip}'. Если Лёша спросит — можешь рассказать.]"
    else:
        stranger_history = history[-5:]
        system_prompt = SYSTEM_PROMPT_STRANGER
        
        if len(history) < 2:
            system_prompt += "\n[CONTEXT: Это твое первое сообщение этому человеку. Будь максимально подозрительной.]"
        elif len(history) > 10:
             system_prompt += "\n[CONTEXT: Этот чел слишком много пишет. Начни отвечать еще короче или затролль его, что он душный.]"

    # Запрос к ИИ
    response_text = await call_groq_with_retry(
        [{'role': 'system', 'content': system_prompt}] + history,
        temp=0.85 if is_boyfriend else 0.5
    )
    
    # Чистка ответа
    clean_text = response_text.replace('[MEMORY:', '').replace(']', '').strip()
    clean_text = clean_text.lower().replace('.', '')
    clean_text = clean_text.replace('gossip:', '').replace('[system update:', '')
    
    save_message(user_id, 'assistant', clean_text)
    
    # Разбиение на части
    parts = []
    if len(clean_text) > 40 and random.random() < 0.7:
        for sep in [', но ', ', а ', ' и ', '? ']:
            if sep in clean_text:
                p = clean_text.split(sep, 1)
                parts = [p[0], sep.strip() + ' ' + p[1]]
                break
        if not parts: parts = [clean_text]
    else:
        parts = [clean_text]

    # --- ОТПРАВКА С ИМИТАЦИЕЙ ЧЕЛОВЕКА ---
    await asyncio.sleep(random.uniform(1.5, 3.5))

    for i, part in enumerate(parts):
        async with client.action(user_id, 'typing'):
            part = make_typos(part)
            
            typing_time = len(part) * random.uniform(0.15, 0.22)
            typing_time = min(typing_time, 10.0)
            
            await asyncio.sleep(typing_time)
            await client.send_message(user_id, part)
            
        if i < len(parts) - 1:
            await asyncio.sleep(random.uniform(1.0, 2.5))

async def wait_and_process(user_id, delay):
    try:
        await asyncio.sleep(delay)
        await process_user_buffer(user_id)
    except asyncio.CancelledError:
        logger.debug(f"Timer для {user_id} отменён")
    except Exception as e:
        logger.error(f"Ошибка в wait_and_process: {e}")

# --- ГЛАВНЫЙ ХЕНДЛЕР ---
@client.on(events.NewMessage(incoming=True))
async def main_handler(event):
    if event.is_group or event.is_channel: return
    
    user_id = event.sender_id
    text = event.text or ""
    
    # === VISION ===
    if event.photo:
        await client.send_read_acknowledge(event.chat_id, max_id=event.id)
        photo_path = await event.download_media()
        history_context = "\n".join([f"{m['role']}: {m['content']}" for m in get_history(user_id, 5)])
        
        try:
            with open(photo_path, "rb") as f:
                b64_img = base64.b64encode(f.read()).decode('utf-8')
                
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
            if "[MEMORY:" in raw:
                mem = raw.split("[MEMORY:", 1)[1].split("]", 1)[0]
                reply = raw.split("]", 1)[1].strip()
                save_message(user_id, 'assistant', f"[видела фото: {mem}]")
            else:
                reply = raw
            await event.respond(make_typos(reply.lower()))
        except Exception as e:
            logger.error(f"Vision error: {e}")
            await event.respond("блин картинка не грузится(")
        finally:
            if os.path.exists(photo_path): 
                os.remove(photo_path)
        return

    # === BATCHING ===
    if user_id in message_buffers:
        old_timer = message_buffers[user_id].get('timer')
        if old_timer and not old_timer.done():
            old_timer.cancel()
        message_buffers[user_id]['messages'].append(text)
    else:
        message_buffers[user_id] = {'messages': [text]}
    
    await client.send_read_acknowledge(event.chat_id, max_id=event.id)
    
    message_buffers[user_id]['timer'] = asyncio.create_task(
        wait_and_process(user_id, 3.0)
    )

# --- ФОНОВЫЕ ЗАДАЧИ ---
async def life_cycle_loop():
    global is_online
    logger.info("Цикл жизни запущен")
    while not shutdown_event.is_set():
        try:
            now = datetime.now(pytz.timezone('Europe/Kaliningrad'))
            hour = now.hour
            
            # Онлайн
            if 8 <= hour < 23:
                if not is_online and random.random() < 0.3:
                    await client(functions.account.UpdateStatusRequest(offline=False))
                    is_online = True
                    await asyncio.sleep(random.randint(60, 300))
                elif is_online:
                    await client(functions.account.UpdateStatusRequest(offline=True))
                    is_online = False
            
            # Инициатива
            rows = run_db_query("SELECT timestamp, role FROM messages WHERE user_id = %s ORDER BY id DESC LIMIT 1", (BOYFRIEND_ID,), fetch=True)
            if rows:
                last_time, last_role = rows[0]
                hours_since = (datetime.now() - last_time).total_seconds() / 3600
                
                if hours_since > 5 and 10 <= hour <= 21 and random.random() < 0.4:
                    prompt = "Лёша молчит больше 5 часов. Напиши ему, узнай как дела." if last_role == 'assistant' else "Ты забыла ответить Лёше! Напиши."
                    resp = await call_groq_with_retry([{'role': 'system', 'content': SYSTEM_PROMPT_REAL_GF}, {'role': 'user', 'content': prompt}])
                    text = make_typos(resp.lower().replace('.', ''))
                    await client.send_message(BOYFRIEND_ID, text)
                    save_message(BOYFRIEND_ID, 'assistant', text)
            
            await asyncio.sleep(random.randint(600, 1200))
        except asyncio.CancelledError:
            logger.info("Life cycle loop отменён")
            break
        except Exception as e:
            logger.error(f"Error in lifecycle: {e}")
            await asyncio.sleep(60)

# --- ЗАПУСК ---
async def graceful_shutdown():
    logger.info("Начало корректного завершения...")
    shutdown_event.set()
    
    # Отменяем все активные таймеры
    for user_id, data in list(message_buffers.items()):
        timer = data.get('timer')
        if timer and not timer.done():
            timer.cancel()
    
    # Закрываем клиент
    if client.is_connected():
        await client.disconnect()
    
    # Закрываем пул БД
    if db_pool:
        db_pool.closeall()
    
    # Отменяем все оставшиеся задачи
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    for task in tasks:
        task.cancel()
    
    await asyncio.gather(*tasks, return_exceptions=True)
    logger.info("Завершение выполнено корректно")

async def start_bot():
    # 1. Инициализация БД
    init_db_pool()
    
    # 2. Запуск Телеграма
    await client.start(phone=PHONE)
    logger.info("Telegram клиент подключен")
    
    # 3. Запуск фоновых задач
    lifecycle_task = asyncio.create_task(life_cycle_loop())

    # 4. Запуск Веб-сервера
    app = web.Application()
    app.router.add_get('/', lambda r: web.Response(text="Sonya Alive"))
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get('PORT', 10000))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    
    logger.info(f"Health check запущен на порту {port}")
    logger.info("Соня v4.3 (Ultra Stable) запущена! 🚀")

    # 5. Ждём сигнала завершения
    try:
        await client.run_until_disconnected()
    finally:
        await graceful_shutdown()

def main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    def signal_handler(sig):
        logger.info(f"Получен сигнал {sig}")
        asyncio.create_task(graceful_shutdown())
    
    # Настройка обработки сигналов
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda s=sig: signal_handler(s))
        except NotImplementedError:
            pass

    try:
        loop.run_until_complete(start_bot())
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt получен")
    except Exception as e:
        logger.critical(f"Global crash: {e}", exc_info=True)
    finally:
        try:
            loop.run_until_complete(graceful_shutdown())
        except:
            pass
        loop.close()

if __name__ == '__main__':
    main()
