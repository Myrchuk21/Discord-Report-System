import discord
from discord.ext import commands
from dotenv import load_dotenv
import os
import json
import time  # Для работы с таймерами

# Загружаем переменные из .env файла
load_dotenv()

# Загружаем параметры из .env файла и проверяем их наличие
SUPPORT_ROLE_ID = os.getenv("SUPPORT_ROLE_ID")
if not SUPPORT_ROLE_ID:
    raise ValueError("SUPPORT_ROLE_ID не найден в .env файле.")
SUPPORT_ROLE_ID = int(SUPPORT_ROLE_ID)

REPORT_LOG_CHANNEL_ID = os.getenv("REPORT_LOG_CHANNEL_ID")
if not REPORT_LOG_CHANNEL_ID:
    raise ValueError("REPORT_LOG_CHANNEL_ID не найден в .env файле.")
REPORT_LOG_CHANNEL_ID = int(REPORT_LOG_CHANNEL_ID)

CLOSED_LOG_CHANNEL_ID = os.getenv("CLOSED_LOG_CHANNEL_ID")
if not CLOSED_LOG_CHANNEL_ID:
    raise ValueError("CLOSED_LOG_CHANNEL_ID не найден в .env файле.")
CLOSED_LOG_CHANNEL_ID = int(CLOSED_LOG_CHANNEL_ID)

REPORTS_FILE = "reports.json"

# Если файл с жалобами не существует или пустой, создаём его
if not os.path.exists(REPORTS_FILE):
    with open(REPORTS_FILE, "w") as f:
        json.dump([], f)

# Словарь для отслеживания времени последней жалобы каждого пользователя
user_last_report_time = {}

# Функция для получения всех жалоб
def get_all_reports():
    try:
        with open(REPORTS_FILE, "r") as f:
            content = f.read().strip()
            if not content:
                return []
            return json.loads(content)
    except json.JSONDecodeError:
        return []

# Инициализация переменной report_counter
def get_last_report_id():
    reports = get_all_reports()
    if reports:
        return max(report['report_id'] for report in reports)
    return 0

# Инициализируем переменную report_counter
report_counter = get_last_report_id()

# Функция для сохранения новой жалобы
def save_report(report):
    reports = get_all_reports()
    reports.append(report)
    with open(REPORTS_FILE, "w") as f:
        json.dump(reports, f)

# Инициализируем объект бота
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# Модальное окно отправки жалобы
class ReportModal(discord.ui.Modal, title="Отправить жалобу"):
    user_id = discord.ui.TextInput(label="ID пользователя", placeholder="Введите только цифры", required=True)
    reason = discord.ui.TextInput(label="Причина жалобы", placeholder="Опишите причину", style=discord.TextStyle.paragraph, required=True)

    async def on_submit(self, interaction: discord.Interaction):
        global report_counter

        # Проверка на антиспам (если прошло меньше 2 минут)
        user_id = str(interaction.user.id)
        current_time = time.time()
        if user_id in user_last_report_time:
            last_report_time = user_last_report_time[user_id]
            if current_time - last_report_time < 120:  # 120 секунд = 2 минуты
                await interaction.response.send_message("❌ Вы можете отправить жалобу только раз в 2 минуты.", ephemeral=True)
                return

        # Обновляем время последней жалобы
        user_last_report_time[user_id] = current_time

        # Проверка на правильность ID
        if not self.user_id.value.isdigit():
            await interaction.response.send_message("❌ ID должен содержать только цифры!", ephemeral=True)
            return

        report_counter += 1
        report_id = report_counter

        embed = discord.Embed(
            title=f"🚨 Новая жалоба #{report_id}",
            color=discord.Color.red()
        )
        embed.add_field(name="ID пользователя", value=self.user_id.value, inline=False)
        embed.add_field(name="Причина жалобы", value=self.reason.value, inline=False)
        embed.set_footer(text=f"Жалоба от {interaction.user}")

        # Сохраняем жалобу в файл
        report = {
            "report_id": report_id,
            "user_id": self.user_id.value,
            "reason": self.reason.value,
            "reported_by": str(interaction.user.id),
            "is_closed": False,  # Добавляем флаг, который будет указывать, закрыта ли жалоба
            "resolved_by": None,  # Поле для модератора, который решил жалобу
            "claimed_by": None  # Новое поле для отслеживания откликнувшегося модератора
        }
        save_report(report)

        await interaction.response.send_message("✅ Жалоба отправлена!", ephemeral=True)

        log_channel = bot.get_channel(REPORT_LOG_CHANNEL_ID)
        if log_channel:
            view = ReportActionView(report_id, self.user_id.value, self.reason.value)
            await log_channel.send(
                content=f"<@&{SUPPORT_ROLE_ID}>",
                embed=embed,
                view=view,
                allowed_mentions=discord.AllowedMentions(roles=True)
            )


# Кнопки под жалобой
class ReportActionView(discord.ui.View):
    def __init__(self, report_id, user_id, report_reason):
        super().__init__(timeout=None)
        self.report_id = report_id
        self.user_id = user_id
        self.report_reason = report_reason
        self.claimed_by = None

        # Проверяем, была ли жалоба уже закрыта
        self.is_closed = False
        reports = get_all_reports()
        for report in reports:
            if report["report_id"] == self.report_id:
                self.is_closed = report.get("is_closed", False)
                self.claimed_by = report.get("claimed_by", None)
                break

    @discord.ui.button(label="Откликнуться на жалобу", style=discord.ButtonStyle.primary)
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not any(role.id == SUPPORT_ROLE_ID for role in interaction.user.roles):
            await interaction.response.send_message("❌ У вас нет прав откликаться на жалобы.", ephemeral=True)
            return

        if self.claimed_by is None:
            self.claimed_by = interaction.user
            button.disabled = True

            # Обновляем жалобу с информацией о модераторе, который откликнулся
            reports = get_all_reports()
            for report in reports:
                if report["report_id"] == self.report_id:
                    report["claimed_by"] = str(interaction.user.id)  # Сохраняем ID откликнувшегося
                    break

            with open(REPORTS_FILE, "w") as f:
                json.dump(reports, f)

            embed = interaction.message.embeds[0]
            embed.add_field(name="Откликнулся модератор", value=interaction.user.mention, inline=False)

            await interaction.response.send_message(f"✅ {interaction.user.mention} откликнулся на жалобу #{self.report_id}.", ephemeral=True)
            await interaction.message.edit(embed=embed, view=self)
        else:
            await interaction.response.send_message("❗ Жалоба уже в работе другим модератором.", ephemeral=True)

    @discord.ui.button(label="Закрыть жалобу", style=discord.ButtonStyle.danger)
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.is_closed:
            await interaction.response.send_message("❌ Эта жалоба уже была закрыта.", ephemeral=True)
            return

        if interaction.user != self.claimed_by:
            await interaction.response.send_message("❌ Только модератор, откликнувшийся на жалобу, может её закрыть.", ephemeral=True)
            return

        # Обновляем статус закрытия жалобы
        await interaction.response.send_modal(CloseReportModal(
            report_id=self.report_id,
            closer=interaction.user,
            message=interaction.message,
            view=self,
            user_id=self.user_id,
            report_reason=self.report_reason
        ))


# Модальное окно для закрытия жалобы
class CloseReportModal(discord.ui.Modal, title="Причина закрытия жалобы"):
    reason = discord.ui.TextInput(label="Причина закрытия", placeholder="Напишите причину закрытия жалобы", style=discord.TextStyle.paragraph, required=True)

    def __init__(self, report_id, closer, message, view, user_id, report_reason):
        super().__init__()
        self.report_id = report_id
        self.closer = closer
        self.message = message
        self.view = view
        self.user_id = user_id
        self.report_reason = report_reason

    async def on_submit(self, interaction: discord.Interaction):
        reason = self.reason.value

        # Закрытие жалобы
        closed_embed = discord.Embed(
            title=f"Жалоба #{self.report_id} закрыта",
            description=f"**Причина закрытия**: {reason}\n**Закрыто**: {self.closer.mention}\n**Жалоба подана на**: {self.user_id}\n**Жалоба подана пользователем**: {self.closer.mention}",
            color=discord.Color.green()
        )
        closed_embed.set_footer(text=f"Закрыто модератором {self.closer}")

        # Обновляем файл с жалобами
        reports = get_all_reports()
        for report in reports:
            if report["report_id"] == self.report_id:
                report["is_closed"] = True
                report["resolved_by"] = str(self.closer.id)  # Добавляем ID модератора, который закрыл жалобу
                break

        with open(REPORTS_FILE, "w") as f:
            json.dump(reports, f)

        closed_log_channel = bot.get_channel(CLOSED_LOG_CHANNEL_ID)
        if closed_log_channel:
            await closed_log_channel.send(embed=closed_embed)

        # Обновляем сообщение с жалобой
        await self.message.edit(embed=closed_embed)
        await interaction.response.send_message("✅ Жалоба успешно закрыта!", ephemeral=True)

        # Отключаем кнопку "Закрыть жалобу"
        self.view.is_closed = True
        for button in self.view.children:
            if isinstance(button, discord.ui.Button) and button.label == "Закрыть жалобу":
                button.disabled = True
        await self.message.edit(view=self.view)


# Команды
@bot.tree.command(name="report", description="Отправить жалобу на пользователя")
async def report(interaction: discord.Interaction):
    await interaction.response.send_modal(ReportModal())


@bot.tree.command(name="list_reports", description="Список всех жалоб")
async def list_reports(interaction: discord.Interaction):
    # Проверяем, есть ли у пользователя нужная роль
    if not any(role.id == SUPPORT_ROLE_ID for role in interaction.user.roles):
        await interaction.response.send_message("❌ У вас нет прав для просмотра всех жалоб.", ephemeral=True)
        return

    reports = get_all_reports()
    if not reports:
        await interaction.response.send_message("❌ Нет открытых жалоб.", ephemeral=True)
        return

    embed = discord.Embed(
        title="📜 Список всех жалоб",
        color=discord.Color.blue()
    )

    for report in reports:
        closed_status = "Закрыта" if report.get("is_closed") else "Открыта"
        resolved_by = f"<@{report['resolved_by']}>" if report.get("resolved_by") else "Не решена"
        claimed_by = f"<@{report['claimed_by']}>" if report.get("claimed_by") else "Не откликнулся"
        embed.add_field(
            name=f"Жалоба #{report['report_id']}",
            value=f"ID пользователя: {report['user_id']}\nПричина: {report['reason']}\nСтатус: {closed_status}\nМодератор: {resolved_by}\nОткликнулся: {claimed_by}",
            inline=False
        )

    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.event
async def on_ready():
    print(f"✅ Бот запущен как {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"🔁 Синхронизированы {len(synced)} команд.")
    except Exception as e:
        print(f"❌ Ошибка синхронизации команд: {e}")
    
    # Устанавливаем статус стрима
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.streaming, name="Report System", url="https://www.twitch.tv/myrchuk21"))

bot.run(os.getenv("DISCORD_BOT_TOKEN"))