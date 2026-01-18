from telethon import TelegramClient, events
import requests
import asyncio
import random
import os
import base64

api_id = 33125954
api_hash = '42dd1070f641ea0060b39067c1e187e7'
phone = '+79118682172'
BOYFRIEND_ID = 5902478541

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
    
    print(f"Отправляю в ИИ от {user_name} ({user_id}): {message}")
    
    try:
        response = requests.post(
            'https://api.groq.com/openai/v1/chat/completions',
            headers={'Authorization': 'Bearer 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'},
            json={
                'model': 'llama-3.3-70b-versatile',
                'messages': [
                    {'role': 'system', 'content': system_prompt}
                ] + conversations[user_id],
                'temperature': 0.95
            }
        )
        data = response.json()
        
        if 'choices' in data:
            result = data['choices'][0]['message']['content']
            conversations[user_id].append({'role': 'assistant', 'content': result})
            print(f"ИИ ответил: {result}")
            return result
        else:
            print(f"Ошибка API: {data}")
            return "сорян зависло"
    except Exception as e:
        print(f"Ошибка: {e}")
        return "сорян зависло"

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
    
    print(f"Получено от {user_name} ({user_id}): {event.text}")
    
    # Небольшая задержка перед началом (думает)
    await asyncio.sleep(random.uniform(1, 3))
    
    # Получаем ответ от ИИ
    reply = await get_ai_response(event.text, user_id, user_name)
    
    # Считаем время печати в зависимости от длины
    # ~150-200 символов в минуту (обычная скорость печати подростка)
    chars_per_second = random.uniform(2.5, 3.5)  # 2.5-3.5 символа в секунду
    typing_time = len(reply) / chars_per_second
    
    # Минимум 2 сек, максимум 15 сек (чтобы не слишком долго)
    typing_time = max(2, min(typing_time, 15))
    
    print(f"Печатаю {len(reply)} символов, ~{typing_time:.1f} сек")
    
    # Показываем "печатает..." на рассчитанное время
    async with client.action(event.chat_id, 'typing'):
        await asyncio.sleep(typing_time)
    
    await event.respond(reply)
    print("Отправлено!")

print("Бот запущен!")
client.start(phone)
client.run_until_disconnected()