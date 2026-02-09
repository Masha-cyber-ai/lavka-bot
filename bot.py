import os
import logging
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters

# Load environment variables
load_dotenv()

# Logging setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
import json
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ConversationHandler, CallbackQueryHandler
from groq import Groq

# States for ConversationHandler
CALORIES = range(1)

# In-memory storage for user goals
user_goals = {}

async def fill_cart_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_goals:
        await update.message.reply_text("Сначала задайте цели командой /set_goals")
        return

    # Logic to find items (same as recommend)
    goals = user_goals[user_id]
    current_products = load_products()
    sorted_products = sorted(current_products, key=lambda x: x['protein'], reverse=True)
    
    items_to_add = []
    count = 0
    for p in sorted_products:
        weight = p.get('weight_g', 100)
        p_cal = int(p['calories'] * weight / 100)
        if p_cal <= goals['calories']:
            # Add specific name for search
            # We remove "(Из Лавки)" etc to make search strictly by name if needed, 
            # but usually full name is better if unique.
            # Let's use full name but ensure products.json names are good.
            items_to_add.append(p['name'])
            count += 1
            if count >= 3: break # Add top 3 items
            
    if not items_to_add:
        await update.message.reply_text("Корзина пуста. Сначала получите рекомендации которые вам подходят.")
        return

    await update.message.reply_text(
        f"Начинаю сборку корзины для: {', '.join(items_to_add)}...\n"
        "Открываю браузер..."
    )
    
    try:
        # Pass items as separate arguments
        cmd = [sys.executable, 'cart_filler.py'] + items_to_add
        subprocess.Popen(cmd) 
    except Exception as e:
        await update.message.reply_text(f"Ошибка при запуске скрипта: {e}")

def load_products():
    try:
        with open('products.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return []

products = load_products()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [['/set_goals'], ['/recommend']]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await context.bot.send_message(
        chat_id=update.effective_chat.id, 
        text="Привет! Я помогу тебе подобрать еду под твои КБЖУ.\n\n"
             "Я работаю по системе: **40% белки, 40% углеводы, 20% жиры**.\n"
             "1. Введи свой калораж: /set_goals\n"
             "2. Получи рекомендации: /recommend",
        reply_markup=reply_markup
    )

async def set_goals_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Введите вашу дневную норму **калорий** (числом, например 1500):",
        parse_mode='Markdown'
    )
    return CALORIES

async def set_calories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        calories = int(update.message.text)
        
        # Calculation: 40% Protein, 40% Carbs, 20% Fat
        # Protein (4 kcal/g), Carbs (4 kcal/g), Fat (9 kcal/g)
        protein = int((calories * 0.40) / 4)
        carbs = int((calories * 0.40) / 4)
        fat = int((calories * 0.20) / 9)
        
        user_id = update.effective_user.id
        user_goals[user_id] = {
            'calories': calories,
            'protein': protein,
            'fat': fat,
            'carbs': carbs
        }
        
        keyboard = [['/recommend', '/fill_cart']]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            f"Принято! Твоя дневная цель ({calories} ккал) разбита так:\n"
            f"🥩 Белки (40%): {protein} г\n"
            f"🥦 Углеводы (40%): {carbs} г\n"
            f"🥑 Жиры (20%): {fat} г\n\n"
            f"Теперь жми /recommend, чтобы найти еду.",
            reply_markup=reply_markup
        )
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("Пожалуйста, введите целое число.")
        return CALORIES

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Настройка отменена.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

import random

async def recommend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show mode selection buttons"""
    user_id = update.effective_user.id
    if user_id not in user_goals:
        await update.message.reply_text("Сначала задайте калораж командой /set_goals")
        return
    
    keyboard = [
        [
            InlineKeyboardButton("⚡ Быстрые рекомендации", callback_data='mode_fast'),
            InlineKeyboardButton("🤖 AI-рекомендации", callback_data='mode_ai')
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "Выберите режим рекомендаций:\\n\\n"
        "⚡ **Быстрые** — мгновенный результат\\n"
        "🤖 **AI** — умный подбор с объяснениями (2-3 сек)",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def recommend_fast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fast recommendations without AI"""
    # Handle both callback and direct call
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        send_func = query.message.reply_text
    else:
        user_id = update.effective_user.id
        send_func = update.message.reply_text
        
    if user_id not in user_goals:
        await send_func("Сначала задайте калораж командой /set_goals")
        return

    goals = user_goals[user_id]
    current_products = load_products()
    
    options = {}
    globally_used = set() # Track items used across all options to prevent repeats
    
    for i in range(1, 4):
        combo = []
        current_cal = 0
        
        # Helper to find item by category that hasn't been used yet
        def get_random_by_cat(cats, used_set):
            # Try to find unused products first
            candidates = [p for p in current_products 
                          if p.get('category') in cats 
                          and p['name'] not in used_set 
                          and p not in combo]
            
            # If no unused, fallback to any valid (to ensure we fill the cart)
            if not candidates:
                 candidates = [p for p in current_products 
                              if p.get('category') in cats 
                              and p not in combo]
            
            if candidates: return random.choice(candidates)
            return None

        # 1. Main Course
        main = get_random_by_cat(['main', 'frozen', 'breakfast'], globally_used)
        if main:
            weight = main.get('weight_g', 100)
            cal = int(main['calories'] * weight / 100)
            if current_cal + cal <= goals['calories']:
                combo.append(main)
                globally_used.add(main['name'])
                current_cal += cal
        
        # 2. Side/Soup/Salad
        side = get_random_by_cat(['soup', 'salad', 'vegetable', 'breakfast'], globally_used)
        if side:
            weight = side.get('weight_g', 100)
            cal = int(side['calories'] * weight / 100)
            if current_cal + cal <= goals['calories']:
                combo.append(side)
                globally_used.add(side['name'])
                current_cal += cal
                
        # 3. Fill remaining
        remaining = [p for p in current_products if p not in combo and p['name'] not in globally_used]
        if not remaining: remaining = [p for p in current_products if p not in combo] # fallback
        random.shuffle(remaining)
        
        for p in remaining:
            weight = p.get('weight_g', 100)
            cal = int(p['calories'] * weight / 100)
            if current_cal + cal <= goals['calories'] * 1.15:
                combo.append(p)
                globally_used.add(p['name'])
                current_cal += cal
        
        options[f'option_{i}'] = combo

    # Beautify Response
    response = f"🎯 **Ваша цель:** {goals['calories']} ккал (Б ~{goals['protein']}г)\n"
    response += "Ниже — 3 варианта вкусного и разнообразного меню:\n\n"
    
    for key, items in options.items():
        opt_num = key.split('_')[1]
        total_cal = sum([int(p['calories'] * p.get('weight_g',100)/100) for p in items])
        total_prot = sum([int(p['protein'] * p.get('weight_g',100)/100) for p in items])
        
        header_emoji = ["🔥", "🥗", "🍲"][int(opt_num)-1]
        
        response += f"═══════════════════\n"
        response += f"{header_emoji} **ВАРИАНТ {opt_num}** ({total_cal} ккал)\n"
        
        for p in items:
            w = p.get('weight_g', 100)
            cal = int(p['calories'] * w / 100)
            prot = int(p['protein'] * w / 100)
            fat = int(p['fat'] * w / 100)
            carb = int(p['carbs'] * w / 100)
            
            cat = p.get('category', 'other')
            icon = "🍽"
            if cat == 'soup': icon = "🍜"
            elif cat == 'salad': icon = "🥗"
            elif cat == 'frozen': icon = "🥟"
            elif cat == 'snack': icon = "🍫"
            elif cat == 'fruit': icon = "🍌"
            elif cat == 'breakfast': icon = "🥞"
            
            response += (
                f"{icon} [{p['name']}]({p['link']})\n"
                f"   └ {w}г | {cal}ккал | Б:{prot} Ж:{fat} У:{carb}\n"
            )
        response += "\n"

    keyboard = [['/set_goals'], ['/recommend']]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    await send_func(response, parse_mode='Markdown', disable_web_page_preview=True, reply_markup=reply_markup)


async def ai_recommend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """AI-powered recommendations using Groq"""
    # Handle both callback and direct call
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        send_func = query.message.reply_text
    else:
        user_id = update.effective_user.id
        send_func = update.message.reply_text
        
    if user_id not in user_goals:
        await send_func("Сначала задайте калораж командой /set_goals")
        return

    goals = user_goals[user_id]
    current_products = load_products()
    
    # Prepare products data for AI
    products_text = ""
    for p in current_products:
        w = p.get('weight_g', 100)
        cal = int(p['calories'] * w / 100)
        prot = int(p['protein'] * w / 100)
        fat = int(p['fat'] * w / 100)
        carb = int(p['carbs'] * w / 100)
        products_text += f"- {p['name']} ({p.get('category', 'other')}): {cal}ккал, Б{prot} Ж{fat} У{carb}\n"
    
    # Initialize Groq client
    try:
        groq_client = Groq(api_key=os.getenv('GROQ_API_KEY'))
        
        await send_func("🤖 AI думает над вашим меню... (это займет пару секунд)")
        
        # Create AI prompt
        prompt = f"""Ты — диетолог-консультант. Пользователь хочет получить рекомендации по питанию.

Его цель: {goals['calories']} ккал в день (Белки: {goals['protein']}г, Жиры: {goals['fat']}г, Углеводы: {goals['carbs']}г)

Доступные продукты из Яндекс Лавки:
{products_text}

ЗАДАЧА:
1. Создай ТРИ разных варианта дневного меню из этих продуктов
2. Каждый вариант должен быть сбалансированным и вкусным
3. Старайся попасть в целевые калории (допустимо ±10%)
4. Объясни, почему ты выбрал именно эти комбинации

ФОРМАТ ОТВЕТА:
🔥 ВАРИАНТ 1 (название стиля, например "Белковый день")
- Продукт 1
- Продукт 2
💡 Почему: краткое объяснение

🥗 ВАРИАНТ 2 (название)
- Продукт 1
- Продукт 2
💡 Почему: краткое объяснение

🍲 ВАРИАНТ 3 (название)
- Продукт 1
- Продукт 2
💡 Почему: краткое объяснение

Будь кратким и дружелюбным!"""

        # Call Groq API
        chat_completion = groq_client.chat.completions.create(
            messages=[
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            model="llama-3.3-70b-versatile",
            temperature=0.7,
            max_tokens=2000,
        )
        
        ai_response = chat_completion.choices[0].message.content
        
        # Add header and footer
        final_response = f"🎯 **Ваша цель:** {goals['calories']} ккал\n\n{ai_response}\n\n_Совет от AI. Для быстрых рекомендаций используйте /recommend_"
        
        keyboard = [['/recommend'], ['/set_goals']]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await send_func(final_response, parse_mode='Markdown', disable_web_page_preview=True, reply_markup=reply_markup)
        
    except Exception as e:
        await send_func(f"❌ Ошибка AI: {str(e)}\n\nПопробуйте обычные рекомендации: /recommend")


async def handle_mode_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline button clicks for mode selection"""
    query = update.callback_query
    
    if query.data == 'mode_fast':
        await recommend_fast(update, context)
    elif query.data == 'mode_ai':
        await ai_recommend(update, context)


if __name__ == '__main__':
    TOKEN = os.getenv('TELEGRAM_TOKEN')
    if not TOKEN:
        print("ОШИБКА: Токен не найден! Пожалуйста, добавьте TELEGRAM_TOKEN в файл .env")
        exit(1)
        
    application = ApplicationBuilder().token(TOKEN).build()
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('set_goals', set_goals_start)],
        states={
            CALORIES: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_calories)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('recommend', recommend))
    application.add_handler(CallbackQueryHandler(handle_mode_selection))
    
    print("Бот запущен...")
    application.run_polling()
