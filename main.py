import os
import discord
from discord.ext import commands, tasks
from discord.ui import Button, View, Select, Modal, TextInput
import sqlite3
import pytz
from datetime import datetime, timedelta

# ==========================================
# 🕒 TIMEZONE HELPER
# ==========================================
def bangkok_now():
    return datetime.now(pytz.timezone('Asia/Bangkok'))

# ==========================================
# ⚙️ CONFIGURATION
# ==========================================
DB_NAME = "guildwar_ultimate_v3.db"

# 👇👇👇 ใส่เลขห้องเหมือนเดิมครับ 👇👇👇
LOG_CHANNEL_ID = 1471767919112486912
HISTORY_CHANNEL_ID = 1472117530721128679
# 👆👆👆 --------------------------- 👆👆👆

# ค่าเริ่มต้น
war_config = {
    "title": "Guild War Roster",
    "date": "Today",
    "match_time": "20:00",    # เวลาแข่งจริง
    "deadline_time": "19:30", # เวลาปิดรับลงชื่อ
    "teams": ["Team Red", "Team Blue"],
    "ALERT_CHANNEL_ID": None
}

is_roster_locked = False

# ==========================================
# 🗄️ DATABASE SYSTEM
# ==========================================
def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS registrations
                (user_id INTEGER PRIMARY KEY,
                username TEXT,
                team TEXT,
                role TEXT,
                time_text TEXT)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS history
                (id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT,
                user_id INTEGER,
                username TEXT,
                status TEXT)''')
    conn.commit()
    conn.close()

def db_upsert(user_id, username, team, role, time_text):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO registrations VALUES (?, ?, ?, ?, ?)",
            (user_id, username, team, role, time_text))
    conn.commit()
    conn.close()

def db_remove(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM registrations WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def db_get_user(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT team, role, time_text FROM registrations WHERE user_id=?", (user_id,))
    data = c.fetchone()
    conn.close()
    return data

def db_get_all():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT username, team, role, time_text FROM registrations")
    data = c.fetchall()
    conn.close()
    return data

def db_clear():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM registrations")
    conn.commit()
    conn.close()

def db_save_history(date_str):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT user_id, username, team FROM registrations")
    rows = c.fetchall()
    count = 0
    for uid, name, team in rows:
        status = "Absence" if team == "Absence" else "Joined"
        c.execute("INSERT INTO history (date, user_id, username, status) VALUES (?, ?, ?, ?)",
                (date_str, uid, name, status))
        count += 1
    conn.commit()
    conn.close()
    return count

async def send_log(interaction: discord.Interaction, action_name: str, details: str, color: discord.Color):
    if LOG_CHANNEL_ID == 0: return
    channel = interaction.client.get_channel(LOG_CHANNEL_ID)
    if channel:
        embed = discord.Embed(title=f"📝 Log: {action_name}", color=color, timestamp=bangkok_now())
        embed.add_field(name="User", value=f"{interaction.user.display_name}", inline=True)
        embed.add_field(name="Details", value=details, inline=False)
        await channel.send(embed=embed)

# ==========================================
# 🛠️ ADMIN CONFIG SYSTEM (POPUP)
# ==========================================
class MasterConfigModal(Modal, title='ตั้งค่ารายละเอียด War'):
    def __init__(self):
        super().__init__()
        
        # 1. หัวข้อ
        self.title_input = TextInput(
            label='1. หัวข้อ (Title)',
            default=war_config["title"],
            required=True
        )
        # 2. วันที่
        self.date_input = TextInput(
            label='2. วันที่ (DD/MM หรือ Today)',
            default=war_config["date"],
            required=True
        )
        # 3. เวลาแข่ง
        self.match_time_input = TextInput(
            label='3. เวลาเริ่มแข่ง (HH:MM)',
            default=war_config["match_time"],
            placeholder="20:00",
            required=True,
            max_length=5
        )
        # 4. เวลาปิดรับ (Deadline)
        self.deadline_input = TextInput(
            label='4. เวลาปิดรับลงชื่อ (HH:MM)',
            default=war_config["deadline_time"],
            placeholder="19:30",
            required=True,
            max_length=5
        )

        self.add_item(self.title_input)
        self.add_item(self.date_input)
        self.add_item(self.match_time_input)
        self.add_item(self.deadline_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            # เช็ครูปแบบเวลา
            datetime.strptime(self.match_time_input.value, "%H:%M")
            datetime.strptime(self.deadline_input.value, "%H:%M")
            
            # บันทึกค่า
            war_config["title"] = self.title_input.value
            war_config["date"] = self.date_input.value
            war_config["match_time"] = self.match_time_input.value
            war_config["deadline_time"] = self.deadline_input.value

            await send_log(interaction, "⚙️ แก้ไข Config", 
                        f"Title: {war_config['title']}\nTime: {war_config['match_time']}\nDeadline: {war_config['deadline_time']}", 
                        discord.Color.blue())
            
            # อัปเดตหน้า Setup
            await interaction.response.edit_message(content=None, embed=create_setup_embed(), view=SetupView())
        
        except ValueError:
            await interaction.response.send_message("❌ รูปแบบเวลาผิด (ต้องใช้ HH:MM เช่น 20:00)", ephemeral=True, delete_after=5.0)

# ==========================================
# 🛡️ USER REGISTRATION (POPUP)
# ==========================================
class OneStopRegistrationView(View):
    def __init__(self, default_team=None, default_role=None, default_status=None, dashboard_msg=None):
        super().__init__(timeout=180)
        self.dashboard_msg = dashboard_msg
        self.selected_team = default_team
        self.selected_role = default_role
        self.selected_status = default_status

        # เลือกทีม
        team_options = [discord.SelectOption(label=t, value=t, default=(t==default_team)) for t in war_config["teams"]]
        self.team_select = Select(placeholder="1️⃣ เลือกทีม...", options=team_options, row=0)
        self.team_select.callback = self.on_team_change
        self.add_item(self.team_select)

        # เลือกตำแหน่ง
        role_options = [
            discord.SelectOption(label="Main DPS", value="DPS", emoji="⚔️", default=("DPS"==default_role)),
            discord.SelectOption(label="Tank", value="Tank", emoji="🛡️", default=("Tank"==default_role)),
            discord.SelectOption(label="Healer", value="Heal", emoji="🌿", default=("Heal"==default_role))
        ]
        self.role_select = Select(placeholder="2️⃣ เลือกตำแหน่ง...", options=role_options, row=1)
        self.role_select.callback = self.on_role_change
        self.add_item(self.role_select)

        # เลือกเวลา
        status_options = [
            discord.SelectOption(label="อยู่ยาว (Full Time)", value="Full Time", emoji="🔥"),
            discord.SelectOption(label="ขอ 1 รอบ (1 Round)", value="1 Round", emoji="☝️"),
            discord.SelectOption(label="ไปสาย (Late)", value="Late Join", emoji="🐢"),
            discord.SelectOption(label="สำรอง (Standby)", value="Standby", emoji="💤"),
            discord.SelectOption(label="อื่นๆ (ระบุเอง)", value="Other", emoji="✏️")
        ]
        # Pre-select logic
        found = False
        for opt in status_options:
            if opt.value == default_status:
                opt.default = True; found = True
        if not found and default_status: # ถ้าเป็นค่า Custom ให้เลือก Other ไว้ก่อน
            status_options[-1].default = True

        self.status_select = Select(placeholder="3️⃣ ความพร้อม/เวลา...", options=status_options, row=2)
        self.status_select.callback = self.on_status_change
        self.add_item(self.status_select)

    async def on_team_change(self, interaction: discord.Interaction):
        self.selected_team = self.team_select.values[0]
        await interaction.response.defer()

    async def on_role_change(self, interaction: discord.Interaction):
        self.selected_role = self.role_select.values[0]
        await interaction.response.defer()

    async def on_status_change(self, interaction: discord.Interaction):
        val = self.status_select.values[0]
        if val == "Other":
            await interaction.response.send_modal(CustomStatusModal(self))
        else:
            self.selected_status = val
            await interaction.response.defer()

    @discord.ui.button(label="💾 ยืนยัน (Confirm)", style=discord.ButtonStyle.green, row=3)
    async def confirm_btn(self, interaction: discord.Interaction, button: Button):
        if not self.selected_team or not self.selected_role or not self.selected_status:
            await interaction.response.send_message("❌ เลือกให้ครบ 3 ช่องก่อนครับ", ephemeral=True); return

        db_upsert(interaction.user.id, interaction.user.display_name, self.selected_team, self.selected_role, self.selected_status)
        await send_log(interaction, "✅ ลงทะเบียน", f"{self.selected_team} | {self.selected_role}", discord.Color.green())
        
        if self.dashboard_msg:
            try: await self.dashboard_msg.edit(embed=create_dashboard_embed())
            except: pass

        await interaction.response.edit_message(content=f"✅ **บันทึกสำเร็จ!**\n🛡️ {self.selected_team} | ⚔️ {self.selected_role}", view=None, embed=None)

class CustomStatusModal(Modal, title='ระบุเวลา'):
    def __init__(self, parent_view):
        super().__init__()
        self.parent_view = parent_view
        self.custom_input = TextInput(label="รายละเอียด", placeholder="เช่น เข้า 20:30", required=True)
        self.add_item(self.custom_input)
    async def on_submit(self, interaction: discord.Interaction):
        self.parent_view.selected_status = self.custom_input.value
        await interaction.response.defer()

# ==========================================
# 🛠️ SETUP & MAIN VIEW
# ==========================================
class AddTeamModal(Modal, title='เพิ่มทีมใหม่'):
    team_name = TextInput(label='ชื่อทีม', placeholder='เช่น Team Charlie', required=True)
    async def on_submit(self, interaction: discord.Interaction):
        if self.team_name.value not in war_config["teams"]:
            war_config["teams"].append(self.team_name.value)
            await interaction.response.edit_message(embed=create_setup_embed(), view=SetupView())
        else: await interaction.response.send_message("❌ ทีมซ้ำ", ephemeral=True)

class RemoveTeamModal(Modal, title='ลบทีมล่าสุด'):
    confirm = TextInput(label='พิมพ์ CONFIRM', placeholder='CONFIRM', required=True)
    async def on_submit(self, interaction: discord.Interaction):
        if self.confirm.value == "CONFIRM" and len(war_config["teams"]) > 1:
            war_config["teams"].pop()
            await interaction.response.edit_message(embed=create_setup_embed(), view=SetupView())
        else: await interaction.response.send_message("❌ ผิดพลาด", ephemeral=True)

class SetupView(View):
    def __init__(self):
        super().__init__(timeout=None)
    
    # 👇👇 ปุ่มนี้คือที่คุณต้องการครับ 👇👇
    @discord.ui.button(label="📅 เลือกวัน / เวลา / หัวข้อ", style=discord.ButtonStyle.primary, row=1)
    async def edit_config(self, interaction: discord.Interaction, button: Button):
        # พอกดปุ๊บ เด้ง Popup ทันที
        await interaction.response.send_modal(MasterConfigModal())

    @discord.ui.button(label="➕ เพิ่มทีม", style=discord.ButtonStyle.secondary, row=1)
    async def add_team(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(AddTeamModal())

    @discord.ui.button(label="➖ ลบทีม", style=discord.ButtonStyle.secondary, row=1)
    async def remove_team(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(RemoveTeamModal())

    @discord.ui.button(label="🗑️ Reset รายชื่อ", style=discord.ButtonStyle.danger, row=2)
    async def clear_roster(self, interaction: discord.Interaction, button: Button):
        db_clear()
        await interaction.response.send_message("✅ ล้างรายชื่อเรียบร้อย", ephemeral=True)

    @discord.ui.button(label="✅ ยืนยันและประกาศ", style=discord.ButtonStyle.green, row=2)
    async def confirm(self, interaction: discord.Interaction, button: Button):
        war_config["ALERT_CHANNEL_ID"] = interaction.channel_id
        embed = create_dashboard_embed()
        view = MainWarView()
        await interaction.channel.send(embed=embed, view=view)
        await interaction.response.edit_message(content="✅ **ประกาศเรียบร้อย!**", embed=None, view=None, delete_after=5.0)

def create_setup_embed():
    embed = discord.Embed(title="🛠️ ตั้งค่าระบบ War", color=0x3498db)
    embed.add_field(name="1. หัวข้อ", value=war_config["title"], inline=False)
    embed.add_field(name="2. วันที่", value=war_config["date"], inline=True)
    embed.add_field(name="3. เวลาแข่ง", value=f"{war_config['match_time']} น.", inline=True)
    embed.add_field(name="4. ปิดรับ (Deadline)", value=f"{war_config['deadline_time']} น.", inline=True) # แสดง Deadline ชัดเจน
    embed.add_field(name="🛡️ ทีม", value=", ".join(war_config["teams"]), inline=False)
    return embed

# ==========================================
# 🎮 MAIN DASHBOARD
# ==========================================
class MainWarView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="📝 ลงทะเบียน / แก้ไข", style=discord.ButtonStyle.primary, row=0, emoji="✍️")
    async def register_edit(self, interaction: discord.Interaction, button: Button):
        if is_roster_locked:
            await interaction.response.send_message("⛔ **ปิดรับลงชื่อแล้วครับ** (เลยเวลา Deadline)", ephemeral=True); return
        
        user_data = db_get_user(interaction.user.id)
        d_team, d_role, d_status = user_data if user_data else (None, None, None)
        
        await interaction.response.send_message("👇 **กรอกข้อมูล**", view=OneStopRegistrationView(d_team, d_role, d_status, interaction.message), ephemeral=True)

    @discord.ui.button(label="🏳️ แจ้งลา", style=discord.ButtonStyle.secondary, row=0)
    async def absence(self, interaction: discord.Interaction, button: Button):
        if is_roster_locked:
            await interaction.response.send_message("⛔ ปิดระบบแล้ว", ephemeral=True); return
        await interaction.response.send_modal(AbsenceModal(interaction.message))

    @discord.ui.button(label="❌ ลบชื่อ", style=discord.ButtonStyle.red, row=0)
    async def leave(self, interaction: discord.Interaction, button: Button):
        db_remove(interaction.user.id)
        await interaction.message.edit(embed=create_dashboard_embed())
        await interaction.response.send_message("🗑️ ลบชื่อแล้ว", ephemeral=True, delete_after=3)

    @discord.ui.button(label="🔄 Refresh", style=discord.ButtonStyle.gray, row=1)
    async def refresh(self, interaction: discord.Interaction, button: Button):
        await interaction.response.edit_message(embed=create_dashboard_embed(), view=self)

    @discord.ui.button(label="📋 Copy", style=discord.ButtonStyle.gray, row=1)
    async def copy_text(self, interaction: discord.Interaction, button: Button):
        text = generate_copy_text()
        await interaction.response.send_message(f"```{text}```", ephemeral=True)

    @discord.ui.button(label="🔐 Lock/Unlock", style=discord.ButtonStyle.danger, row=2)
    async def toggle_lock(self, interaction: discord.Interaction, button: Button):
        if not interaction.user.guild_permissions.administrator: return
        global is_roster_locked
        is_roster_locked = not is_roster_locked
        await interaction.message.edit(embed=create_dashboard_embed())
        await interaction.response.send_message(f"Status: {'LOCKED' if is_roster_locked else 'OPEN'}", ephemeral=True, delete_after=3)

    @discord.ui.button(label="💾 Save History", style=discord.ButtonStyle.success, row=2)
    async def save_history(self, interaction: discord.Interaction, button: Button):
        if not interaction.user.guild_permissions.administrator: return
        count = db_save_history(war_config["date"])
        if HISTORY_CHANNEL_ID:
            ch = interaction.client.get_channel(HISTORY_CHANNEL_ID)
            if ch: await ch.send(embed=create_dashboard_embed(is_history=True))
        db_clear()
        await interaction.message.edit(embed=create_dashboard_embed())
        await interaction.response.send_message(f"✅ บันทึกประวัติ {count} คน", ephemeral=True)

class AbsenceModal(Modal, title='แจ้งลา'):
    def __init__(self, dashboard_msg):
        super().__init__()
        self.dashboard_msg = dashboard_msg
    reason = TextInput(label='สาเหตุ', required=True)
    async def on_submit(self, interaction: discord.Interaction):
        db_upsert(interaction.user.id, interaction.user.display_name, "Absence", self.reason.value, "-")
        await self.dashboard_msg.edit(embed=create_dashboard_embed())
        await interaction.response.send_message("✅ แจ้งลาแล้ว", ephemeral=True)

def generate_copy_text():
    data = db_get_all()
    text = f"⚔️ {war_config['title']} ({war_config['match_time']} น.)\n"
    team_map = {name: [] for name in war_config["teams"]}
    for user, team, role, time in data:
        if team in team_map: team_map[team].append(f"- {user} ({role})")
    for t in team_map:
        text += f"\n🛡️ {t}\n" + ("\n".join(team_map[t]) if team_map[t] else "-")
    return text

def create_dashboard_embed(is_history=False):
    data = db_get_all()
    stats = {name: {"DPS":0, "Tank":0, "Heal":0, "Total":0} for name in war_config["teams"]}
    roster = {name: [] for name in war_config["teams"]}
    absent = []

    for user, team, role, time in data:
        if team == "Absence": absent.append(f"❌ {user}: {role}")
        elif team in stats:
            stats[team]["Total"] += 1
            if role in stats[team]: stats[team][role] += 1
            icon = "⚔️" if "DPS" in role else "🛡️" if "Tank" in role else "🌿"
            roster[team].append(f"> {icon} **{user}** [{time}]")

    color = 0xff2e4c if is_roster_locked else 0x00f7ff
    status_text = "🔒 SYSTEM LOCKED" if is_roster_locked else f"🟢 OPEN (Punt: {war_config['deadline_time']})"
    title = f"📜 History: {war_config['title']}" if is_history else war_config['title']
    desc = f"📅 **{war_config['date']}**\n⚔️ แข่ง: **{war_config['match_time']}** | ⛔ ปิดรับ: **{war_config['deadline_time']}**"
    
    embed = discord.Embed(title=title, description=desc, color=color)
    for team in war_config["teams"]:
        s = stats[team]
        head = f"🔥 Total: {s['Total']} (⚔️{s['DPS']} 🛡️{s['Tank']} 🌿{s['Heal']})"
        embed.add_field(name=f"🛡️ {team.upper()} | {head}", value="\n".join(roster[team]) if roster[team] else "*...*", inline=False)
    if absent: embed.add_field(name=f"🏳️ ลา ({len(absent)})", value="\n".join(absent), inline=False)
    
    if not is_history: embed.set_footer(text=f"STATUS: {status_text} | Updated: {bangkok_now().strftime('%H:%M')}")
    return embed

# ==========================================
# 🤖 BOT RUN
# ==========================================
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@tasks.loop(minutes=1)
async def auto_lock_task():
    global is_roster_locked
    if is_roster_locked: return
    now = bangkok_now().strftime("%H:%M")
    if now == war_config["deadline_time"]: # เช็ค Deadline แทนเวลาเริ่ม
        is_roster_locked = True
        print(f"⏰ Locked at {now}")

@bot.event
async def on_ready():
    init_db()
    print(f'✅ Ready: {bot.user}')
    await bot.tree.sync()
    auto_lock_task.start()

@bot.tree.command(name="setup_war_v3", description="เริ่มระบบ Setup แบบ Modal")
async def setup_war(interaction: discord.Interaction):
    await interaction.response.send_message(embed=create_setup_embed(), view=SetupView(), ephemeral=True)

bot.run('Y')