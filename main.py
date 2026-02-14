import os
import discord
from discord.ext import commands, tasks
from discord.ui import Button, View, Select, Modal, TextInput
import sqlite3
import pytz
from datetime import datetime, timedelta

# ==========================================
# ⚙️ CONFIGURATION
# ==========================================
# 👇 ใส่ Token และ Channel ID ของคุณที่นี่ 👇
LOG_CHANNEL_ID = 1471767919112486912
HISTORY_CHANNEL_ID = 1472117530721128679
# 👆 ---------------------------------- 👆

DB_NAME = "guildwar_final.db"
timezone = pytz.timezone('Asia/Bangkok')

# ค่าเริ่มต้น
war_config = {
    "title": "Guild War Roster",
    "date": "Today",
    "time": "19:30",
    "deadline": "19:00",
    "teams": ["Team ATK", "Team Flex"],
    "alert_channel": None
}
is_locked = False

def get_time():
    return datetime.now(timezone)

# ==========================================
# 🗄️ DATABASE
# ==========================================
def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS registration (
        user_id INTEGER PRIMARY KEY, username TEXT, team TEXT, role TEXT, status TEXT
    )''')
    conn.commit()
    conn.close()

def db_upsert(user_id, username, team, role, status):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO registration VALUES (?,?,?,?,?)", (user_id, username, team, role, status))
    conn.commit()
    conn.close()

def db_delete(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM registration WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def db_get_all():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT username, team, role, status FROM registration")
    data = c.fetchall()
    conn.close()
    return data

def db_clear():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM registration")
    conn.commit()
    conn.close()

# ==========================================
# 🛠️ SETUP SYSTEM (ระบบตั้งค่าแบบปุ่มกด)
# ==========================================

# 1. Popup กรอกเวลา (เด้งหลังเลือกวัน)
class ConfigModal(Modal, title="รายละเอียดเวลา"):
    def __init__(self, date_selected, main_msg):
        super().__init__()
        self.date_selected = date_selected
        self.main_msg = main_msg

        self.title_inp = TextInput(label="หัวข้อ", default=war_config["title"], required=True)
        self.add_item(self.title_inp)
        
        self.time_inp = TextInput(label="เวลาเริ่ม (HH:MM)", default=war_config["time"], placeholder="19:30", max_length=5, required=True)
        self.add_item(self.time_inp)
        
        self.dead_inp = TextInput(label="ปิดรับ (Deadline)", default=war_config["deadline"], placeholder="19:00", max_length=5, required=True)
        self.add_item(self.dead_inp)

    async def on_submit(self, interaction: discord.Interaction):
        war_config["date"] = self.date_selected
        war_config["title"] = self.title_inp.value
        war_config["time"] = self.time_inp.value
        war_config["deadline"] = self.dead_inp.value
        
        await self.main_msg.edit(embed=create_setup_embed())
        await interaction.response.send_message("✅ บันทึกเวลาเรียบร้อย", ephemeral=True, delete_after=3)

# 2. Dropdown เลือกวัน
class DateSelect(Select):
    def __init__(self, main_msg):
        self.main_msg = main_msg
        options = []
        now = get_time()
        options.append(discord.SelectOption(label=f"วันนี้ ({now.strftime('%d/%m')})", value="Today", emoji="🟢"))
        tmr = now + timedelta(days=1)
        options.append(discord.SelectOption(label=f"พรุ่งนี้ ({tmr.strftime('%d/%m')})", value="Tomorrow", emoji="🟡"))
        for i in range(2, 6):
            d = now + timedelta(days=i)
            options.append(discord.SelectOption(label=f"{d.strftime('%A')} {d.strftime('%d/%m')}", value=d.strftime("%d/%m"), emoji="🗓️"))
        options.append(discord.SelectOption(label="ระบุเอง...", value="Manual", emoji="📝"))
        super().__init__(placeholder="📅 เลือกวันที่จัด War...", min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(ConfigModal(self.values[0], self.main_msg))

class DatePickerView(View):
    def __init__(self, main_msg):
        super().__init__()
        self.add_item(DateSelect(main_msg))

# 3. Popup เพิ่มทีม
class AddTeamModal(Modal, title="เพิ่มทีม"):
    def __init__(self, main_msg):
        super().__init__()
        self.main_msg = main_msg
    name = TextInput(label="ชื่อทีม", placeholder="Team Name", required=True)
    async def on_submit(self, interaction: discord.Interaction):
        if self.name.value not in war_config["teams"]:
            war_config["teams"].append(self.name.value)
            await self.main_msg.edit(embed=create_setup_embed())
            await interaction.response.send_message(f"✅ เพิ่ม {self.name.value} แล้ว", ephemeral=True)

class RemoveTeamView(View):
    def __init__(self, main_msg):
        super().__init__()
        opts = [discord.SelectOption(label=t, value=t) for t in war_config["teams"]]
        self.add_item(Select(placeholder="ลบทีม...", options=opts if opts else [discord.SelectOption(label="ไม่มี", value="none")], custom_id="del_team"))
    
    async def interaction_check(self, interaction: discord.Interaction):
        # จัดการ event ของ select ใน view นี้ด้วยวิธี manual check
        val = interaction.data['values'][0]
        if val in war_config["teams"]:
            war_config["teams"].remove(val)
            await self.main_msg.edit(embed=create_setup_embed())
            await interaction.response.send_message(f"🗑️ ลบ {val} แล้ว", ephemeral=True)
        return False

# 4. ปุ่ม Control Panel หลัก
class SetupControlView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="📅 เลือกวัน / เวลา / หัวข้อ", style=discord.ButtonStyle.primary, row=1)
    async def config_btn(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message("👇 **เลือกวันที่:**", view=DatePickerView(interaction.message), ephemeral=True)

    @discord.ui.button(label="➕ เพิ่มทีม", style=discord.ButtonStyle.secondary, row=1)
    async def add_team_btn(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(AddTeamModal(interaction.message))

    @discord.ui.button(label="➖ ลบทีม", style=discord.ButtonStyle.secondary, row=1)
    async def remove_team_btn(self, interaction: discord.Interaction, button: Button):
        if not war_config["teams"]: return await interaction.response.send_message("❌ ไม่มีทีม", ephemeral=True)
        await interaction.response.send_message("👇 **เลือกทีมที่จะลบ:**", view=RemoveTeamView(interaction.message), ephemeral=True)

    @discord.ui.button(label="🗑️ Reset รายชื่อ", style=discord.ButtonStyle.danger, row=2)
    async def reset_btn(self, interaction: discord.Interaction, button: Button):
        db_clear()
        await interaction.response.send_message("✅ ล้างรายชื่อเรียบร้อย", ephemeral=True)

    @discord.ui.button(label="✅ ยืนยันและประกาศ", style=discord.ButtonStyle.success, row=2)
    async def confirm_btn(self, interaction: discord.Interaction, button: Button):
        war_config["alert_channel"] = interaction.channel_id
        await interaction.response.send_message("📢 **กำลังประกาศ...**", ephemeral=True, delete_after=2)
        embed = create_dashboard_embed() # เรียกใช้ฟังก์ชันเดิมที่หน้าตาสวยๆ
        view = MainWarView()
        msg = await interaction.channel.send(embed=embed, view=view)
        try: await msg.create_thread(name=f"💬 {war_config['title']}", auto_archive_duration=1440)
        except: pass

def create_setup_embed():
    embed = discord.Embed(title="⚙️ ตั้งค่า Guild War", description="กดปุ่มด้านล่างเพื่อตั้งค่า", color=0x2b2d31)
    embed.add_field(name="📌 Title", value=war_config['title'], inline=True)
    embed.add_field(name="📅 Date", value=war_config['date'], inline=True)
    embed.add_field(name="⏰ Time", value=f"{war_config['time']} (ปิด {war_config['deadline']})", inline=True)
    team_str = ", ".join(war_config['teams']) if war_config['teams'] else "-"
    embed.add_field(name="🛡️ Teams", value=f"```\n{team_str}\n```", inline=False)
    return embed

# ==========================================
# 📊 DASHBOARD (หน้าตาเดิม เป๊ะ 100%)
# ==========================================

def create_dashboard_embed():
    # 1. คำนวณเวลาเพื่อทำ Timestamp สวยๆ
    try:
        now_th = get_time()
        war_time_obj = datetime.strptime(war_config['time'], "%H:%M")
        date_input = war_config.get('date', 'Today').lower().strip()
        
        target_date = now_th.date()
        if date_input in ['tomorrow', 'พรุ่งนี้']: 
            target_date = now_th.date() + timedelta(days=1)
        elif date_input not in ['today', 'วันนี้']:
            # พยายามแปลงวันที่ manual เช่น 14/02
            try:
                clean_date = date_input.split(' ')[-1] # เผื่อมีชื่อวันติดมา
                parsed_date = datetime.strptime(clean_date, "%d/%m")
                target_date = parsed_date.replace(year=now_th.year).date()
                if target_date < now_th.date(): target_date = target_date.replace(year=now_th.year + 1)
            except: pass
            
        target_dt = timezone.localize(datetime.combine(target_date, war_time_obj.time()))
        ts = int(target_dt.timestamp())
        date_pretty = target_dt.strftime("%A, %d/%m")
        # ตรงนี้คือ Time Display แบบเดิมที่มีนับถอยหลัง
        time_display = f"📅 **{date_pretty}**\n<t:{ts}:F> • <t:{ts}:R>"
    except:
        time_display = f"📅 {war_config['date']} @ {war_config['time']}"

    # 2. ดึงข้อมูล
    data = db_get_all()
    stats = {t: {'DPS':0, 'Tank':0, 'Heal':0, 'List':[]} for t in war_config['teams']}
    absence = []

    for name, team, role, status in data:
        if team == "Absence":
            absence.append(name)
        elif team in stats:
            stats[team][role] += 1
            # ไอคอนสถานะ
            s_icon = "💤" if status == "Standby" else "🐢" if status == "Late" else ""
            # ไอคอนอาชีพ
            r_icon = "⚔️" if role=="DPS" else "🛡️" if role=="Tank" else "🌿"
            stats[team]['List'].append(f"> {r_icon} {name} {s_icon}")

    # 3. สร้าง Embed (สี Cyan, หัวเหลือง)
    status_text = "🔴 LOCKED" if is_locked else "🟢 OPEN REGISTRATION"
    color = 0xff0000 if is_locked else 0x00f7ff  # Cyan เหมือนเดิม
    
    embed = discord.Embed(
        title=war_config['title'],
        description=f"```ansi\n\u001b[0;33m⏰ START: {war_config['time']} น.\u001b[0m```\n{time_display}", # สีเหลืองเหมือนเดิม
        color=color
    )

    for t, s in stats.items():
        total = sum([s['DPS'], s['Tank'], s['Heal']])
        # สร้างหลอดเลือดสีดำ/สี เหมือนเดิม
        bar = "⚫" * 10
        if total > 0:
            d = int((s['DPS']/total)*10)
            ta = int((s['Tank']/total)*10)
            h = 10 - d - ta
            # ป้องกันเกิน 10
            if d+ta+h > 10: h = 10 - d - ta
            bar = ("🟥"*d) + ("🟦"*ta) + ("🟩"*h)
            if len(bar) < 10: bar += "⚫" * (10 - len(bar))
            
        header = f"▬▬▬▬ {t.upper()} ▬▬▬▬\n🔥 **Total: {total}** (⚔️ {s['DPS']} 🛡️ {s['Tank']} 🌿 {s['Heal']})\n`{bar}`"
        body = "\n".join(s['List']) if s['List'] else "\n... ว่าง ..."
        embed.add_field(name=header, value=body + "\n", inline=False)
        
    if absence:
        embed.add_field(name=f"🏳️ ลา ({len(absence)})", value=", ".join(absence), inline=False)

    embed.set_footer(text=f"STATUS: {status_text} | Last Updated: {get_time().strftime('%H:%M:%S')}")
    return embed

# ==========================================
# 🎮 INTERACTION VIEW (ปุ่มลงชื่อ)
# ==========================================
class RegisterView(View):
    def __init__(self, main_msg):
        super().__init__(timeout=120)
        self.main_msg = main_msg
        
        self.add_item(Select(placeholder="1. เลือกทีม", options=[discord.SelectOption(label=t, value=t) for t in war_config["teams"]], custom_id="team"))
        self.add_item(Select(placeholder="2. เลือกอาชีพ", options=[
            discord.SelectOption(label="DPS", value="DPS", emoji="⚔️"),
            discord.SelectOption(label="Tank", value="Tank", emoji="🛡️"),
            discord.SelectOption(label="Healer", value="Heal", emoji="🌿")
        ], custom_id="role"))
        self.add_item(Select(placeholder="3. สถานะ", options=[
            discord.SelectOption(label="Full Time", value="Main", emoji="🔥"),
            discord.SelectOption(label="Standby", value="Standby", emoji="💤"),
            discord.SelectOption(label="Late", value="Late", emoji="🐢")
        ], custom_id="status"))

    @discord.ui.button(label="บันทึก", style=discord.ButtonStyle.success, row=3)
    async def submit(self, interaction: discord.Interaction, button: Button):
        vals = {c.custom_id: c.values for c in self.children if isinstance(c, Select)}
        if not all(vals.values()): return await interaction.response.send_message("❌ กรุณาเลือกให้ครบ", ephemeral=True)
        if is_locked: return await interaction.response.send_message("⛔ ปิดรับแล้ว", ephemeral=True)

        db_upsert(interaction.user.id, interaction.user.display_name, vals["team"][0], vals["role"][0], vals["status"][0])
        try: await self.main_msg.edit(embed=create_dashboard_embed())
        except: pass
        await interaction.response.send_message("✅ ลงชื่อสำเร็จ", ephemeral=True, delete_after=3)

class AbsenceModal(Modal, title="แจ้งลา"):
    def __init__(self, main_msg):
        super().__init__()
        self.main_msg = main_msg
    reason = TextInput(label="เหตุผล", required=True)
    async def on_submit(self, interaction: discord.Interaction):
        db_upsert(interaction.user.id, interaction.user.display_name, "Absence", "-", self.reason.value)
        try: await self.main_msg.edit(embed=create_dashboard_embed())
        except: pass
        await interaction.response.send_message("✅ แจ้งลาเรียบร้อย", ephemeral=True, delete_after=3)

class MainWarView(View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(label="ลงชื่อ / แก้ไข", style=discord.ButtonStyle.primary, emoji="✍️")
    async def reg(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message(view=RegisterView(interaction.message), ephemeral=True)

    @discord.ui.button(label="แจ้งลา", style=discord.ButtonStyle.secondary, emoji="🏳️")
    async def abs(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(AbsenceModal(interaction.message))

    @discord.ui.button(label="ถอนตัว", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def leave(self, interaction: discord.Interaction, button: Button):
        db_delete(interaction.user.id)
        await interaction.message.edit(embed=create_dashboard_embed())
        await interaction.response.send_message("🗑️ ลบชื่อแล้ว", ephemeral=True, delete_after=3)

# ==========================================
# 🚀 RUN BOT
# ==========================================
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.tree.command(name="setup_war")
async def setup_war(interaction: discord.Interaction):
    # เรียกหน้า Setup ที่มีปุ่มกดเหมือนรีโมท
    await interaction.response.send_message(embed=create_setup_embed(), view=SetupControlView(), ephemeral=True)

@bot.event
async def on_ready():
    init_db()
    print(f"✅ Online as {bot.user}")
    await bot.tree.sync()

bot.run('Y')