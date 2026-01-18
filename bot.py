from telethon import TelegramClient, events, functions
import requests
import asyncio
import random
import os
import base64
from aiohttp import web

# Твои данные
api_id = 33125954
api_hash = '42dd1070f641ea0060b39067c1e187e7'
phone = '+79118682172'
BOYFRIEND_ID = 5902478541
GROQ_API_KEY = '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'

# Восстанавливаем session из переменной окружения
session_b64 = os.getenv('SESSION_DATA')
if session_b64:
    print("Восстанавливаю сессию из переменной окружения...")
    try:
        session_bytes = base64.b64decode(session_b64)
        with open('girlfriend_session.session', 'wb') as f:
            f.write(session_bytes)
        print("Сессия восстановлена!")
    except Exception as e:
        print(f"Ошибка при восстановлении сессии: {e}")

client = TelegramClient('girlfriend_session', api_id, api_hash)

SYSTEM_PROMPT_BOYFRIEND = """ты соня, девушка 16 лет. переписываешься со своим парнем лёшей. 

ВАЖНО: ты ДЕВУШКА, не парень! если спросят про пол/гендер - отвечай естественно типа "ты чё, я девочка", "а как по мне видно что девушка", "лёш ты совсем?"

стиль: коротко, без заглавных, иногда дерзко/игриво. пиши как обычная школьница в переписке:
- "ну ты и тормоз"
- "аххахах дурачок" 
- "блинн скучаю"
- "когда увидимся"
- "ты чё такой"
- "дурашка"

макс 1-2 предложения. эмодзи редко. просто и по-живому, не объясняй кто ты."""

SYSTEM_PROMPT_OTHERS = """ты соня, девушка 16 лет. пишет незнакомый человек. ты осторожная но не тупая, можешь нормально общаться если человек адекватный. 

стиль: коротко, без заглавных, немного настороженно но по-человечески. НЕ зацикливайся на одних фразах!

если спрашивают познакомиться:
- "ну давай, только сначала представься"
- "а ты кто такой"
- "откуда ты вообще"

если продолжают общаться нормально:
- "ну ок"
- "может быть"
- "хз пока"
- "а чё ты хотел"

если ведут себя странно:
- "ты чё какой то странный"
- "отстань"
- "не хочу общаться"

отвечай по ситуации, не повторяйся. будь настороженной но адекватной. макс 1-2 предложения."""

conversations = {}

# Функция для имитации онлайна/оффлайна
async def presence_manager():
    while True:
        online_time = random.randint(120, 600)
        offline_time = random.randint(900, 2700)
        try:
            await client(functions.account.UpdateStatusRequest(offline=False))
            print(f"--- Соня зашла в онлайн на {online_time//60} мин ---")
            await asyncio.sleep(online_time)
            await client(functions.account.UpdateStatusRequest(offline=True))
            print(f"--- Соня вышла из сети на {offline_time//60} мин ---")
            await asyncio.sleep(offline_time)
        except Exception as e:
            print(f"Ошибка в статусе: {e}")
            await asyncio.sleep(60)

async def get_ai_response(message, user_id, user_name):
    is_boyfriend = (user_id == BOYFRIEND_ID)
    system_prompt = SYSTEM_PROMPT_BOYFRIEND if is_boyfriend else SYSTEM_PROMPT_OTHERS
    if user_id not in conversations:
        conversations[user_id] = []
    
    if not is_boyfriend and user_name:
        context_message = f"[пишет {user_name}]: {message}"
    else:
        context_message = message
    
    conversations[user_id].append({'role': 'user', 'content': context_message})
    if len(conversations[user_id]) > 10:
        conversations[user_id] = conversations[user_id][-10:]
    
    try:
        response = requests.post(
            'https://api.groq.com/openai/v1/chat/completions',
            headers={'Authorization': f'Bearer {GROQ_API_KEY}'},
            json={
                'model': 'llama-3.3-70b-versatile',
                'messages': [{'role': 'system', 'content': system_prompt}] + conversations[user_id],
                'temperature': 0.95
            }
        )
        data = response.json()
        if 'choices' in data:
            result = data['choices'][0]['message']['content']
            conversations[user_id].append({'role': 'assistant', 'content': result})
            return result
        return "сорян зависло"
    except Exception:
        return "сорян зависло"

# Логика опечаток
def make_typos(text):
    if len(text) < 5 or random.random() > 0.25: # Опечатка в 25% случаев
        return text
    
    text_list = list(text)
    typo_type = random.randint(1, 3)
    
    if typo_type == 1: # Пропуск буквы
        idx = random.randint(0, len(text_list) - 1)
        text_list.pop(idx)
    elif typo_type == 2: # Перестановка соседних букв
        idx = random.randint(0, len(text_list) - 2)
        text_list[idx], text_list[idx+1] = text_list[idx+1], text_list[idx]
    elif typo_type == 3: # Повтор буквы
        idx = random.randint(0, len(text_list) - 1)
        text_list.insert(idx, text_list[idx])
        
    return "".join(text_list)

@client.on(events.NewMessage(incoming=True))
async def handler(event):
    if event.is_group or event.is_channel:
        return
    
    user_id = event.sender_id
    try:
        sender = await event.get_sender()
        user_name = sender.first_name or "аноним"
    except:
        user_name = "аноним"
    
    # 1. Задержка перед просмотром
    await asyncio.sleep(random.uniform(1, 3))
    
    # 2. Читаем сообщение
    try:
        await client.send_read_acknowledge(event.chat_id, max_id=event.id)
    except:
        pass
    
    # 3. Генерим ответ
    reply = await get_ai_response(event.text, user_id, user_name)
    
    # 4. Добавляем опечатку
    reply = make_typos(reply)
    
    # 5. Имитируем набор текста
    chars_per_second = random.uniform(2.5, 3.5)
    typing_time = max(2, min(len(reply) / chars_per_second, 15))
    
    async with client.action(event.chat_id, 'typing'):
        await asyncio.sleep(typing_time)
    
    await event.respond(reply)

# Web сервер
async def health_check(request):
    return web.Response(text="Bot is alive!")

app = web.Application()
app.router.add_get('/', health_check)
app.router.add_get('/health', health_check)

async def start_web_server():
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', int(os.environ.get('PORT', 10000)))
    await site.start()

async def main():
    await start_web_server()
    await client.start(phone)
    asyncio.create_task(presence_manager())
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
