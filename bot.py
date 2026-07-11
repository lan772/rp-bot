import discord
from discord.ext import commands
import sqlite3
import os

# ============ НАСТРОЙКА ============
TOKEN = os.getenv("DISCORD_TOKEN")
PREFIX = "!"

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=PREFIX, intents=intents)

# ID роли, которой разрешено редактировать анкеты (ГМ/Админ). Впиши сюда свой ID роли.
GM_ROLE_ID = None  # например: 123456789012345678

DB_PATH = "characters.db"
SLOT_COUNT = 6

# Финальный список статов (ключ команды -> отображаемое название)
STATS = {
    "прочность": "Прочность",
    "сила": "Сила",
    "скорость": "Скорость",
    "реакция": "Реакция",
    "стойкость": "Стойкость",
    "регенерация": "Регенерация",
    "контроль_маны": "Контроль маны",
    "энергия": "Мана/Энергия",
}

# Единицы измерения для точных значений (для красивого отображения)
STAT_UNITS = {
    "прочность": "кг (выдерживаемая нагрузка)",
    "сила": "кг (сила удара/подъёма)",
    "скорость": "км/ч",
    "реакция": "мс",
    "стойкость": "очков",
    "регенерация": "% в пост",
    "контроль_маны": "% эффективности",
    "энергия": "%",
}

# ============ БАЗА ДАННЫХ ============
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS characters (
            user_id INTEGER,
            slot INTEGER,
            name TEXT DEFAULT 'Имя не указано',
            race TEXT DEFAULT 'Не указана',
            fight_style TEXT DEFAULT 'Не указан',
            level TEXT DEFAULT 'Новичок',
            height TEXT DEFAULT 'Не указан',
            weight TEXT DEFAULT 'Не указан',
            age TEXT DEFAULT 'Не указан',
            info TEXT DEFAULT '—',
            organization TEXT DEFAULT 'Не указана',
            builds TEXT DEFAULT '—',
            balance INTEGER DEFAULT 0,
            cleared_zones INTEGER DEFAULT 0,
            прочность INTEGER DEFAULT 0,
            сила INTEGER DEFAULT 0,
            скорость INTEGER DEFAULT 0,
            реакция INTEGER DEFAULT 0,
            стойкость INTEGER DEFAULT 0,
            регенерация INTEGER DEFAULT 0,
            контроль_маны INTEGER DEFAULT 0,
            энергия INTEGER DEFAULT 100,
            traits TEXT DEFAULT '',
            artifacts TEXT DEFAULT '',
            achievements TEXT DEFAULT '',
            image_url TEXT DEFAULT '',
            PRIMARY KEY (user_id, slot)
        )
    """)
    conn.commit()
    # Миграция: добавляем новые колонки, если база уже существовала без них
    new_columns = [
        ("race", "'Не указана'"),
        ("fight_style", "'Не указан'"),
        ("height", "'Не указан'"),
        ("weight", "'Не указан'"),
        ("age", "'Не указан'"),
        ("info", "'—'"),
        ("organization", "'Не указана'"),
        ("builds", "'—'"),
    ]
    for col, default in new_columns:
        try:
            c.execute(f"ALTER TABLE characters ADD COLUMN {col} TEXT DEFAULT {default}")
            conn.commit()
        except sqlite3.OperationalError:
            pass  # колонка уже существует
    # Числовые колонки мигрируем отдельно (другой тип)
    for col, default in [("balance", "0"), ("cleared_zones", "0")]:
        try:
            c.execute(f"ALTER TABLE characters ADD COLUMN {col} INTEGER DEFAULT {default}")
            conn.commit()
        except sqlite3.OperationalError:
            pass
    conn.close()

# Явный порядок колонок — не зависит от того, в каком физическом порядке
# SQLite хранит их в таблице (важно из-за ALTER TABLE при миграциях)
COLUMN_ORDER = [
    "user_id", "slot", "name", "race", "fight_style", "level",
    "height", "weight", "age", "info", "organization", "builds", "balance", "cleared_zones",
    "прочность", "сила", "скорость", "реакция", "стойкость", "регенерация",
    "контроль_маны", "энергия", "traits", "artifacts", "achievements", "image_url"
]
COLUMNS_SQL = ", ".join(COLUMN_ORDER)

def get_char(user_id, slot):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(f"SELECT {COLUMNS_SQL} FROM characters WHERE user_id=? AND slot=?", (user_id, slot))
    row = c.fetchone()
    if row is None:
        c.execute("INSERT INTO characters (user_id, slot) VALUES (?, ?)", (user_id, slot))
        conn.commit()
        c.execute(f"SELECT {COLUMNS_SQL} FROM characters WHERE user_id=? AND slot=?", (user_id, slot))
        row = c.fetchone()
    conn.close()
    return row

def update_stat(user_id, slot, stat, delta):
    get_char(user_id, slot)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(f"UPDATE characters SET {stat} = {stat} + ? WHERE user_id=? AND slot=?", (delta, user_id, slot))
    conn.commit()
    conn.close()

def update_list_field(user_id, slot, field, value, add=True):
    get_char(user_id, slot)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(f"SELECT {field} FROM characters WHERE user_id=? AND slot=?", (user_id, slot))
    current = c.fetchone()[0]
    items = [i for i in current.split(";") if i] if current else []
    if add:
        items.append(value)
    else:
        items = [i for i in items if i.lower() != value.lower()]
    new_value = ";".join(items)
    c.execute(f"UPDATE characters SET {field}=? WHERE user_id=? AND slot=?", (new_value, user_id, slot))
    conn.commit()
    conn.close()

def set_field(user_id, slot, field, value):
    get_char(user_id, slot)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(f"UPDATE characters SET {field}=? WHERE user_id=? AND slot=?", (value, user_id, slot))
    conn.commit()
    conn.close()

def valid_slot(slot):
    return 1 <= slot <= SLOT_COUNT

# ============ ПРОВЕРКА ПРАВ ============
def is_gm(ctx):
    if GM_ROLE_ID is None:
        return ctx.author.guild_permissions.administrator
    return any(role.id == GM_ROLE_ID for role in ctx.author.roles)

# ============ ПРОСМОТР АНКЕТЫ ============
@bot.command(name="информация")
async def info(ctx, slot: int = 1, member: discord.Member = None):
    member = member or ctx.author
    if not valid_slot(slot):
        await ctx.send(f"⚠️ Слот должен быть от 1 до {SLOT_COUNT}")
        return

    row = get_char(member.id, slot)
    (_, _, name, race, fight_style, level, height, weight, age, info_text,
     organization, builds, balance, cleared_zones,
     prochnost, sila, skorost, reakciya,
     stoikost, regen, kontrol, energiya, traits, artifacts, achievements, image_url) = row

    embed = discord.Embed(title=f"📋 [Слот {slot}] {name}", color=discord.Color.dark_red())
    embed.set_thumbnail(url=member.display_avatar.url)
    if image_url:
        embed.set_image(url=image_url)

    embed.add_field(name="🧬 Раса", value=race, inline=True)
    embed.add_field(name="⚔️ Стиль боя", value=fight_style, inline=True)
    embed.add_field(name="🎖 Уровень авантюриста", value=str(level), inline=False)
    embed.add_field(
        name="📏 Внешность",
        value=(
            f"Рост: {height}\n"
            f"Вес: {weight}\n"
            f"Возраст: {age}"
        ),
        inline=False
    )
    embed.add_field(name="📖 Информация", value=info_text, inline=False)
    embed.add_field(name="🏛 Организация", value=organization, inline=True)
    embed.add_field(name="🧩 Сборка", value=builds, inline=False)
    embed.add_field(name="💰 Баланс", value=f"{balance} монет", inline=True)
    embed.add_field(name="🗺 Зачищено Аномальных Зон", value=str(cleared_zones), inline=True)
    embed.add_field(
        name="📊 Статы",
        value=(
            f"Прочность: {prochnost} кг\n"
            f"Сила: {sila} кг\n"
            f"Скорость: {skorost} км/ч\n"
            f"Реакция: {reakciya} мс\n"
            f"Стойкость: {stoikost} очк.\n"
            f"Регенерация: {regen}%/пост\n"
            f"Контроль маны: {kontrol}%\n"
            f"Мана/Энергия: {energiya}%"
        ),
        inline=False
    )
    embed.add_field(name="✨ Трейты", value=traits.replace(";", "\n") or "—", inline=False)
    embed.add_field(name="🗡 Артефакты", value=artifacts.replace(";", "\n") or "—", inline=False)
    embed.add_field(name="🏆 Достижения", value=achievements.replace(";", "\n") or "—", inline=False)

    await ctx.send(embed=embed)

@bot.command(name="слоты")
async def list_slots(ctx, member: discord.Member = None):
    member = member or ctx.author
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    lines = []
    for slot in range(1, SLOT_COUNT + 1):
        c.execute("SELECT name FROM characters WHERE user_id=? AND slot=?", (member.id, slot))
        row = c.fetchone()
        name = row[0] if row else "Пустой слот"
        lines.append(f"**Слот {slot}:** {name}")
    conn.close()
    embed = discord.Embed(
        title=f"📁 Слоты персонажей — {member.display_name}",
        description="\n".join(lines),
        color=discord.Color.yellow()
    )
    await ctx.send(embed=embed)

# ============ РЕДАКТИРОВАНИЕ (только ГМ) ============
@bot.command(name="стат")
async def set_stat(ctx, member: discord.Member, slot: int, stat: str, *, value: str):
    """Устанавливает точное значение стата напрямую (не прибавляет, а заменяет)"""
    if not is_gm(ctx):
        await ctx.send("⛔ У вас нет прав на это действие.")
        return
    if not valid_slot(slot):
        await ctx.send(f"⚠️ Слот должен быть от 1 до {SLOT_COUNT}")
        return
    stat = stat.lower()
    if stat not in STATS:
        await ctx.send(f"⚠️ Неизвестный стат. Доступные: {', '.join(STATS.keys())}")
        return
    set_field(member.id, slot, stat, value)
    unit = STAT_UNITS.get(stat, "")
    await ctx.send(f"✅ {STATS[stat]} у {member.display_name} (слот {slot}) установлен(а) на: {value} {unit}")

@bot.command(name="добавить_трейт")
async def add_trait(ctx, member: discord.Member, slot: int, *, trait_name: str):
    if not is_gm(ctx):
        await ctx.send("⛔ У вас нет прав на это действие.")
        return
    if not valid_slot(slot):
        await ctx.send(f"⚠️ Слот должен быть от 1 до {SLOT_COUNT}")
        return
    update_list_field(member.id, slot, "traits", trait_name, add=True)
    await ctx.send(f"✅ Трейт «{trait_name}» добавлен для {member.display_name} (слот {slot})")

@bot.command(name="убрать_трейт")
async def remove_trait(ctx, member: discord.Member, slot: int, *, trait_name: str):
    if not is_gm(ctx):
        await ctx.send("⛔ У вас нет прав на это действие.")
        return
    if not valid_slot(slot):
        await ctx.send(f"⚠️ Слот должен быть от 1 до {SLOT_COUNT}")
        return
    update_list_field(member.id, slot, "traits", trait_name, add=False)
    await ctx.send(f"✅ Трейт «{trait_name}» убран у {member.display_name} (слот {slot})")

@bot.command(name="добавить_артефакт")
async def add_artifact(ctx, member: discord.Member, slot: int, *, item_name: str):
    if not is_gm(ctx):
        await ctx.send("⛔ У вас нет прав на это действие.")
        return
    if not valid_slot(slot):
        await ctx.send(f"⚠️ Слот должен быть от 1 до {SLOT_COUNT}")
        return
    update_list_field(member.id, slot, "artifacts", item_name, add=True)
    await ctx.send(f"✅ Артефакт «{item_name}» добавлен для {member.display_name} (слот {slot})")

@bot.command(name="убрать_артефакт")
async def remove_artifact(ctx, member: discord.Member, slot: int, *, item_name: str):
    if not is_gm(ctx):
        await ctx.send("⛔ У вас нет прав на это действие.")
        return
    if not valid_slot(slot):
        await ctx.send(f"⚠️ Слот должен быть от 1 до {SLOT_COUNT}")
        return
    update_list_field(member.id, slot, "artifacts", item_name, add=False)
    await ctx.send(f"✅ Артефакт «{item_name}» убран у {member.display_name} (слот {slot})")

@bot.command(name="достижение")
async def add_achievement(ctx, member: discord.Member, slot: int, *, ach_name: str):
    if not is_gm(ctx):
        await ctx.send("⛔ У вас нет прав на это действие.")
        return
    if not valid_slot(slot):
        await ctx.send(f"⚠️ Слот должен быть от 1 до {SLOT_COUNT}")
        return
    update_list_field(member.id, slot, "achievements", ach_name, add=True)
    await ctx.send(f"🏆 Достижение «{ach_name}» добавлено для {member.display_name} (слот {slot})")

@bot.command(name="убрать_достижение")
async def remove_achievement(ctx, member: discord.Member, slot: int, *, ach_name: str):
    if not is_gm(ctx):
        await ctx.send("⛔ У вас нет прав на это действие.")
        return
    if not valid_slot(slot):
        await ctx.send(f"⚠️ Слот должен быть от 1 до {SLOT_COUNT}")
        return
    update_list_field(member.id, slot, "achievements", ach_name, add=False)
    await ctx.send(f"✅ Достижение «{ach_name}» убрано у {member.display_name} (слот {slot})")

@bot.command(name="уровень")
async def set_level(ctx, member: discord.Member, slot: int, *, value: str):
    if not is_gm(ctx):
        await ctx.send("⛔ У вас нет прав на это действие.")
        return
    if not valid_slot(slot):
        await ctx.send(f"⚠️ Слот должен быть от 1 до {SLOT_COUNT}")
        return
    set_field(member.id, slot, "level", value)
    await ctx.send(f"✅ Уровень авантюриста {member.display_name} (слот {slot}) установлен на: {value}")

@bot.command(name="имя")
async def set_name(ctx, member: discord.Member, slot: int, *, char_name: str):
    if not is_gm(ctx):
        await ctx.send("⛔ У вас нет прав на это действие.")
        return
    if not valid_slot(slot):
        await ctx.send(f"⚠️ Слот должен быть от 1 до {SLOT_COUNT}")
        return
    set_field(member.id, slot, "name", char_name)
    await ctx.send(f"✅ Имя персонажа (слот {slot}) установлено: {char_name}")

@bot.command(name="раса")
async def set_race(ctx, member: discord.Member, slot: int, *, race_name: str):
    if not is_gm(ctx):
        await ctx.send("⛔ У вас нет прав на это действие.")
        return
    if not valid_slot(slot):
        await ctx.send(f"⚠️ Слот должен быть от 1 до {SLOT_COUNT}")
        return
    set_field(member.id, slot, "race", race_name)
    await ctx.send(f"✅ Раса персонажа (слот {slot}) установлена: {race_name}")

@bot.command(name="стиль_боя")
async def set_fight_style(ctx, member: discord.Member, slot: int, *, style_name: str):
    if not is_gm(ctx):
        await ctx.send("⛔ У вас нет прав на это действие.")
        return
    if not valid_slot(slot):
        await ctx.send(f"⚠️ Слот должен быть от 1 до {SLOT_COUNT}")
        return
    set_field(member.id, slot, "fight_style", style_name)
    await ctx.send(f"✅ Стиль боя персонажа (слот {slot}) установлен: {style_name}")

@bot.command(name="убрать_стиль_боя")
async def remove_fight_style(ctx, member: discord.Member, slot: int):
    if not is_gm(ctx):
        await ctx.send("⛔ У вас нет прав на это действие.")
        return
    if not valid_slot(slot):
        await ctx.send(f"⚠️ Слот должен быть от 1 до {SLOT_COUNT}")
        return
    set_field(member.id, slot, "fight_style", "Не указан")
    await ctx.send(f"✅ Стиль боя персонажа (слот {slot}) сброшен")

@bot.command(name="рост")
async def set_height(ctx, member: discord.Member, slot: int, *, value: str):
    if not is_gm(ctx):
        await ctx.send("⛔ У вас нет прав на это действие.")
        return
    if not valid_slot(slot):
        await ctx.send(f"⚠️ Слот должен быть от 1 до {SLOT_COUNT}")
        return
    set_field(member.id, slot, "height", value)
    await ctx.send(f"✅ Рост персонажа (слот {slot}) установлен: {value}")

@bot.command(name="вес")
async def set_weight(ctx, member: discord.Member, slot: int, *, value: str):
    if not is_gm(ctx):
        await ctx.send("⛔ У вас нет прав на это действие.")
        return
    if not valid_slot(slot):
        await ctx.send(f"⚠️ Слот должен быть от 1 до {SLOT_COUNT}")
        return
    set_field(member.id, slot, "weight", value)
    await ctx.send(f"✅ Вес персонажа (слот {slot}) установлен: {value}")

@bot.command(name="возраст")
async def set_age(ctx, member: discord.Member, slot: int, *, value: str):
    if not is_gm(ctx):
        await ctx.send("⛔ У вас нет прав на это действие.")
        return
    if not valid_slot(slot):
        await ctx.send(f"⚠️ Слот должен быть от 1 до {SLOT_COUNT}")
        return
    set_field(member.id, slot, "age", value)
    await ctx.send(f"✅ Возраст персонажа (слот {slot}) установлен: {value}")

@bot.command(name="описание")
async def set_info(ctx, member: discord.Member, slot: int, *, value: str):
    if not is_gm(ctx):
        await ctx.send("⛔ У вас нет прав на это действие.")
        return
    if not valid_slot(slot):
        await ctx.send(f"⚠️ Слот должен быть от 1 до {SLOT_COUNT}")
        return
    set_field(member.id, slot, "info", value)
    await ctx.send(f"✅ Информация персонажа (слот {slot}) обновлена")

@bot.command(name="организация")
async def set_organization(ctx, member: discord.Member, slot: int, *, value: str):
    if not is_gm(ctx):
        await ctx.send("⛔ У вас нет прав на это действие.")
        return
    if not valid_slot(slot):
        await ctx.send(f"⚠️ Слот должен быть от 1 до {SLOT_COUNT}")
        return
    set_field(member.id, slot, "organization", value)
    await ctx.send(f"✅ Организация персонажа (слот {slot}) установлена: {value}")

@bot.command(name="убрать_организацию")
async def remove_organization(ctx, member: discord.Member, slot: int):
    if not is_gm(ctx):
        await ctx.send("⛔ У вас нет прав на это действие.")
        return
    if not valid_slot(slot):
        await ctx.send(f"⚠️ Слот должен быть от 1 до {SLOT_COUNT}")
        return
    set_field(member.id, slot, "organization", "Не указана")
    await ctx.send(f"✅ Организация персонажа (слот {slot}) сброшена")

@bot.command(name="сборка")
async def set_build(ctx, member: discord.Member, slot: int, *, value: str):
    if not is_gm(ctx):
        await ctx.send("⛔ У вас нет прав на это действие.")
        return
    if not valid_slot(slot):
        await ctx.send(f"⚠️ Слот должен быть от 1 до {SLOT_COUNT}")
        return
    set_field(member.id, slot, "builds", value)
    await ctx.send(f"✅ Сборка персонажа (слот {slot}) обновлена")

@bot.command(name="убрать_сборку")
async def remove_build(ctx, member: discord.Member, slot: int):
    if not is_gm(ctx):
        await ctx.send("⛔ У вас нет прав на это действие.")
        return
    if not valid_slot(slot):
        await ctx.send(f"⚠️ Слот должен быть от 1 до {SLOT_COUNT}")
        return
    set_field(member.id, slot, "builds", "—")
    await ctx.send(f"✅ Сборка персонажа (слот {slot}) сброшена")

@bot.command(name="добавить_баланс")
async def add_balance(ctx, member: discord.Member, slot: int, amount: int):
    if not is_gm(ctx):
        await ctx.send("⛔ У вас нет прав на это действие.")
        return
    if not valid_slot(slot):
        await ctx.send(f"⚠️ Слот должен быть от 1 до {SLOT_COUNT}")
        return
    update_stat(member.id, slot, "balance", amount)
    await ctx.send(f"✅ Баланс {member.display_name} (слот {slot}) увеличен на {amount}")

@bot.command(name="убрать_баланс")
async def remove_balance(ctx, member: discord.Member, slot: int, amount: int):
    if not is_gm(ctx):
        await ctx.send("⛔ У вас нет прав на это действие.")
        return
    if not valid_slot(slot):
        await ctx.send(f"⚠️ Слот должен быть от 1 до {SLOT_COUNT}")
        return
    update_stat(member.id, slot, "balance", -amount)
    await ctx.send(f"✅ Баланс {member.display_name} (слот {slot}) уменьшен на {amount}")

@bot.command(name="добавить_зоны")
async def add_cleared_zones(ctx, member: discord.Member, slot: int, amount: int):
    if not is_gm(ctx):
        await ctx.send("⛔ У вас нет прав на это действие.")
        return
    if not valid_slot(slot):
        await ctx.send(f"⚠️ Слот должен быть от 1 до {SLOT_COUNT}")
        return
    update_stat(member.id, slot, "cleared_zones", amount)
    await ctx.send(f"✅ Зачищенные зоны {member.display_name} (слот {slot}) увеличены на {amount}")

@bot.command(name="убрать_зоны")
async def remove_cleared_zones(ctx, member: discord.Member, slot: int, amount: int):
    if not is_gm(ctx):
        await ctx.send("⛔ У вас нет прав на это действие.")
        return
    if not valid_slot(slot):
        await ctx.send(f"⚠️ Слот должен быть от 1 до {SLOT_COUNT}")
        return
    update_stat(member.id, slot, "cleared_zones", -amount)
    await ctx.send(f"✅ Зачищенные зоны {member.display_name} (слот {slot}) уменьшены на {amount}")

@bot.command(name="фото")
async def set_photo(ctx, member: discord.Member, slot: int):
    """Использование: прикрепи изображение к сообщению вместе с командой !фото @игрок слот"""
    if not is_gm(ctx):
        await ctx.send("⛔ У вас нет прав на это действие.")
        return
    if not valid_slot(slot):
        await ctx.send(f"⚠️ Слот должен быть от 1 до {SLOT_COUNT}")
        return
    if not ctx.message.attachments:
        await ctx.send("⚠️ Прикрепи изображение к сообщению вместе с этой командой.")
        return
    image_url = ctx.message.attachments[0].url
    set_field(member.id, slot, "image_url", image_url)
    await ctx.send(f"✅ Фото для {member.display_name} (слот {slot}) обновлено")

@bot.command(name="помощь")
async def show_help(ctx):
    embed = discord.Embed(
        title="📖 Список команд",
        color=discord.Color.dark_red()
    )

    embed.add_field(
        name="👀 Просмотр (доступно всем)",
        value=(
            "`!информация` — твой слот 1\n"
            "`!информация 3` — твой слот 3\n"
            "`!информация 3 @игрок` — слот 3 другого игрока\n"
            "`!слоты` — список всех 6 слотов (свои)\n"
            "`!слоты @игрок` — слоты другого игрока\n"
            "`!помощь` — это сообщение"
        ),
        inline=False
    )

    embed.add_field(
        name="📊 Статы (только ГМ)",
        value=(
            "`!стат @игрок 1 [стат] [значение]` — установить точное значение\n"
            f"Доступные статы: {', '.join(STATS.keys())}"
        ),
        inline=False
    )

    embed.add_field(
        name="📋 Анкета персонажа (только ГМ)",
        value=(
            "`!имя @игрок 1 [имя]`\n"
            "`!раса @игрок 1 [раса]`\n"
            "`!стиль_боя @игрок 1 [стиль]` / `!убрать_стиль_боя @игрок 1`\n"
            "`!уровень @игрок 1 [уровень]`\n"
            "`!рост @игрок 1 [рост]`\n"
            "`!вес @игрок 1 [вес]`\n"
            "`!возраст @игрок 1 [возраст]`\n"
            "`!описание @игрок 1 [текст]`\n"
            "`!организация @игрок 1 [название]` / `!убрать_организацию @игрок 1`\n"
            "`!сборка @игрок 1 [текст]` / `!убрать_сборку @игрок 1`\n"
            "`!фото @игрок 1` (+ прикреплённое изображение)"
        ),
        inline=False
    )

    embed.add_field(
        name="✨ Трейты и артефакты (только ГМ)",
        value=(
            "`!добавить_трейт @игрок 1 [название]` / `!убрать_трейт @игрок 1 [название]`\n"
            "`!добавить_артефакт @игрок 1 [название]` / `!убрать_артефакт @игрок 1 [название]`"
        ),
        inline=False
    )

    embed.add_field(
        name="🏆 Достижения, баланс, зоны (только ГМ)",
        value=(
            "`!достижение @игрок 1 [название]` / `!убрать_достижение @игрок 1 [название]`\n"
            "`!добавить_баланс @игрок 1 [сумма]` / `!убрать_баланс @игрок 1 [сумма]`\n"
            "`!добавить_зоны @игрок 1 [кол-во]` / `!убрать_зоны @игрок 1 [кол-во]`"
        ),
        inline=False
    )

    await ctx.send(embed=embed)

# ============ ЗАПУСК ============
@bot.event
async def on_ready():
    print(f"Бот запущен как {bot.user}")

init_db()
bot.run(TOKEN)
