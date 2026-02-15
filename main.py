import os
import discord
import asyncio
from discord.ext import commands, tasks
from discord.ui import Button, View, Select, Modal, TextInput
import sqlite3
import pytz
from datetime import datetime, timedelta

# ==========================================
# 🕒 TIMEZONE & CONFIG
# ==========================================
def bangkok_now():
    return datetime.now(pytz.timezone('Asia/Bangkok'))

# เปลี่ยนชื่อ DB เพื่อเริ่มระบบใหม่ (รองรับชื่อทีมแยกแต่ละงาน)
DB_NAME = "guildwar_final.db" 

# 👇 กรุณาตรวจสอบ ID ห้องให้ถูกต้อง 👇
ALERT_CHANNEL_ID_FIXED = 1444345312188698738 
LOG_CHANNEL_ID = 1472149965299253457
HISTORY_CHANNEL_ID = 1472149894096621639  # ✅ ระบบส่งประวัติหลังจบวอ

# 📦 SESSION STORAGE (เก็บข้อมูลระหว่างตั้งค่า แยกรายคน)
setup_sessions = {} 

# ==========================================
# 🗄️ DATABASE SYSTEM
# ==========================================
def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    # ตาราง Events (เพิ่ม column teams เพื่อเก็บรายชื่อทีมเฉพาะของงานนั้น)
    c.execute('''CREATE TABLE IF NOT EXISTS events
                (event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                date_str TEXT,
                time_str TEXT,
                teams TEXT,
                channel_id INTEGER,
                message_id INTEGER,
                active INTEGER DEFAULT 1)''')
    
    # ตาราง Registrations
    c.execute('''CREATE TABLE IF NOT EXISTS registrations
                (event_id INTEGER,
                user_id INTEGER,
                username TEXT,
                team TEXT,
                role TEXT,
                time_text TEXT,
                PRIMARY KEY (event_id, user_id))''')
    conn.commit()
    conn.close()

# --- DB FUNCTIONS ---
def create_event(title, date_str, time_str, teams_list):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    teams_str = ",".join(teams_list) 
    c.execute("INSERT INTO events (title, date_str, time_str, teams, active) VALUES (?, ?, ?, ?, 1)", 
            (title, date_str, time_str, teams_str))
    eid = c.lastrowid
    conn.commit()
    conn.close()
    return eid

def update_event_msg(event_id, ch_id, msg_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE events SET channel_id=?, message_id=? WHERE event_id=?", (ch_id, msg_id, event_id))
    conn.commit()
    conn.close()

def get_event(event_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT * FROM events WHERE event_id=?", (event_id,))
    row = c.fetchone()
    conn.close()
    return row

def close_event_db(event_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE events SET active=0 WHERE event_id=?", (event_id,))
    conn.commit()
    conn.close()

def reg_upsert(event_id, user_id, username, team, role, time_text):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO registrations VALUES (?, ?, ?, ?, ?, ?)",
            (event_id, user_id, username, team, role, time_text))
    conn.commit()
    conn.close()

def reg_remove(event_id, user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM registrations WHERE event_id=? AND user_id=?", (event_id, user_id))
    conn.commit()
    conn.close()

def get_roster(event_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT username, team, role, time_text FROM registrations WHERE event_id=?", (event_id,))
    data = c.fetchall()
    conn.close()
    return data

def db_get_leaderboard():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''SELECT username, COUNT(*) as count
                FROM registrations
                GROUP BY user_id
                ORDER BY count DESC
                LIMIT 10''')
    data = c.fetchall()
    conn.close()
    return data

# ==========================================
# 🛠️ INTERACTIVE SETUP SYSTEM
# ==========================================
def get_session(user_id):
    if user_id not in setup_sessions:
        setup_sessions[user_id] = {
            "title": "Guild War Roster",
            "date": "Today",
            "time": "19:30",
            "teams": ["Team ATK", "Team Flex"]
        }
    return setup_sessions[user_id]

def create_setup_embed(user_id):
    s = get_session(user_id)
    embed = discord.Embed(title="🛠️ ตั้งค่าตารางวอ (Setup Mode)", description="ปรับแต่งข้อมูลก่อนประกาศจริง", color=0x3498db)
    embed.add_field(name="📝 หัวข้อ", value=s["title"], inline=False)
    embed.add_field(name="📅 วันที่", value=s["date"], inline=True)
    embed.add_field(name="⏰ เวลา", value=s["time"], inline=True)
    
    teams_str = "\n".join([f"- {t}" for t in s["teams"]])
    embed.add_field(name=f"🛡️ ทีม ({len(s['teams'])})", value=f"```\n{teams_str}\n```", inline=False)
    return embed

class ConfigModal(Modal, title='แก้ไขข้อมูล'):
    def __init__(self, mode):
        super().__init__()
        self.mode = mode
        if mode == 'title': self.inp = TextInput(label='หัวข้อ', placeholder='Guild War')
        elif mode == 'time': self.inp = TextInput(label='เวลา (HH:MM)', placeholder='19:30', max_length=5)
        elif mode == 'date_manual': self.inp = TextInput(label='วันที่ (DD/MM)', placeholder='15/02')
        elif mode == 'add_team': self.inp = TextInput(label='ชื่อทีมใหม่', placeholder='Team Roaming')
        self.add_item(self.inp)

    async def on_submit(self, interaction: discord.Interaction):
        s = get_session(interaction.user.id)
        val = self.inp.value
        
        if self.mode == 'time':
            try: datetime.strptime(val, "%H:%M")
            except: return await interaction.response.send_message("❌ รูปแบบเวลาผิด", ephemeral=True)
            s['time'] = val
        elif self.mode == 'title': s['title'] = val
        elif self.mode == 'date_manual': s['date'] = val
        elif self.mode == 'add_team':
            if val not in s['teams']: s['teams'].append(val)
        
        await interaction.response.edit_message(embed=create_setup_embed(interaction.user.id), view=SetupView())

class DateSelect(Select):
    def __init__(self):
        options = [discord.SelectOption(label="✏️ กรอกเอง...", value="manual", emoji="📝")]
        now = bangkok_now()
        options.append(discord.SelectOption(label=f"วันนี้ ({now.strftime('%d/%m')})", value="Today", emoji="🟢"))
        for i in range(1, 4):
            d = now + timedelta(days=i)
            options.append(discord.SelectOption(label=f"{d.strftime('%d/%m')}", value=d.strftime('%d/%m'), emoji="🗓️"))
        super().__init__(placeholder="📅 เลือกวันที่...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "manual":
            await interaction.response.send_modal(ConfigModal('date_manual'))
        else:
            s = get_session(interaction.user.id)
            s['date'] = self.values[0]
            await interaction.response.edit_message(embed=create_setup_embed(interaction.user.id), view=SetupView())

class DatePickerView(View):
    def __init__(self):
        super().__init__()
        self.add_item(DateSelect())

class SetupView(View):
    def __init__(self): super().__init__(timeout=None)

    @discord.ui.button(label="📝 แก้ชื่อ", style=discord.ButtonStyle.secondary, row=1)
    async def edit_info(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(ConfigModal('title'))

    @discord.ui.button(label="⏰ แก้เวลา", style=discord.ButtonStyle.secondary, row=1)
    async def edit_time(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(ConfigModal('time'))

    @discord.ui.button(label="📅 เลือกวัน", style=discord.ButtonStyle.primary, row=1)
    async def edit_date(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message("เลือกวันที่:", view=DatePickerView(), ephemeral=True)

    @discord.ui.button(label="➕ เพิ่มทีม", style=discord.ButtonStyle.success, row=2)
    async def add_team(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(ConfigModal('add_team'))

    @discord.ui.button(label="➖ ลบทีมล่าสุด", style=discord.ButtonStyle.danger, row=2)
    async def remove_team(self, interaction: discord.Interaction, button: Button):
        s = get_session(interaction.user.id)
        if len(s['teams']) > 1: s['teams'].pop()
        await interaction.response.edit_message(embed=create_setup_embed(interaction.user.id), view=self)

    @discord.ui.button(label="✅ ยืนยันและประกาศ", style=discord.ButtonStyle.green, row=3)
    async def confirm(self, interaction: discord.Interaction, button: Button):
        s = get_session(interaction.user.id)
        
        # 1. บันทึกลง DB
        ev_id = create_event(s['title'], s['date'], s['time'], s['teams'])
        
        # 2. สร้าง Dashboard
        embed = create_dashboard_embed(ev_id)
        view = PersistentWarView(ev_id)
        msg = await interaction.channel.send(embed=embed, view=view)
        
        # 3. อัปเดต Location
        update_event_msg(ev_id, msg.channel.id, msg.id)
        
        # 4. ลบ Session และแจ้ง ID
        del setup_sessions[interaction.user.id]
        
        # 🔥 แจ้ง Event ID ตัวใหญ่ๆ
        await interaction.response.edit_message(content=f"✅ **ประกาศเรียบร้อย!**\n🆔 **Event ID: {ev_id}**\n(ใช้เลขนี้สำหรับ /check_missing)", embed=None, view=None, delete_after=20)

# ==========================================
# 📊 DASHBOARD GENERATOR
# ==========================================
def create_dashboard_embed(event_id):
    event = get_event(event_id)
    if not event: return discord.Embed(title="❌ Event Not Found")
    
    ev_id, title, date_str, time_str, teams_str, _, _, active = event
    teams = teams_str.split(",") # ดึงทีมจาก DB ของงานนั้นๆ
    
    data = get_roster(event_id)
    role_priority = {"Tank": 1, "DPS": 2, "Heal": 3}
    data.sort(key=lambda x: (role_priority.get(x[2], 99), x[0]))

    stats = {t: {"DPS":0, "Tank":0, "Heal":0, "Total":0} for t in teams}
    roster = {t: {"Main": [], "Late": [], "Standby": []} for t in teams}
    absence_list = []

    for username, team, role, time_text in data:
        if team == "Absence":
            absence_list.append(f"❌ `{username}` : {role}")
        elif team in stats:
            stats[team]["Total"] += 1
            if role in stats[team]: stats[team][role] += 1
            emoji = "⚔️" if "DPS" in role else "🛡️" if "Tank" in role else "🌿"
            
            on, off = "🟢", "⚫"
            if "Full Time" in time_text: bar = f"{on*4} {on*4}"
            else: bar = f"[{time_text}]"
            display = f"> `{bar}` | {emoji} **{username}**"
            
            # Logic แยกประเภท
            if "Standby" in time_text: roster[team]["Standby"].append(f"💤 {username} [Standby]")
            elif "Late" in time_text or "🐢" in time_text: roster[team]["Late"].append(f"> `🐢 Late Join` | {emoji} **{username}**")
            else: roster[team]["Main"].append(display)

    status_text = "🟢 OPEN REGISTRATION" if active else "🔒 LOCKED / ENDED"
    color = 0x00f7ff if active else 0xff2e4c
    
    # ⏰ ตัวหนังสือใหญ่
    desc = f"```ansi\n\u001b[0;33m# ⏰ START: {time_str} น.\u001b[0m```\n📅 **Date:** {date_str}"
    
    embed = discord.Embed(title=f"⚔️ {title}", description=desc, color=color)
    
    for t in teams:
        s = stats[t]
        val = f"🔥 Total: {s['Total']} (🛡️{s['Tank']} ⚔️{s['DPS']} 🌿{s['Heal']})\n"
        if roster[t]["Main"]: val += "\n".join(roster[t]["Main"])
        else: val += "*... ว่าง ...*"
        if roster[t]["Late"]: val += "\n\n**🐢 มาสาย / Late Join**\n" + "\n".join(roster[t]["Late"])
        if roster[t]["Standby"]: val += "\n\n**💤 สำรอง / Standby**\n" + "\n".join(roster[t]["Standby"])
        embed.add_field(name=f"▬▬▬▬ {t.upper()} ▬▬▬▬", value=val, inline=False)
        
    if absence_list: embed.add_field(name="🏳️ แจ้งลา (Absence)", value="\n".join(absence_list), inline=False)
    
    # 🆔 Footer ID
    embed.set_footer(text=f"EVENT ID: #{event_id} | STATUS: {status_text} | Last Updated: {bangkok_now().strftime('%H:%M:%S')}")
    return embed

# ==========================================
# 📝 UI COMPONENTS
# ==========================================
class StatusSelect(Select):
    def __init__(self, event_id, team, role, dashboard_msg):
        self.event_id = event_id
        self.team, self.role, self.dashboard_msg = team, role, dashboard_msg
        options = [discord.SelectOption(label="🔥 อยู่ยาว / Full Time", value="Full Time", emoji="🔥")]
        for i in range(1, 9): options.append(discord.SelectOption(label=f"Round {i}", value=f"Round {i}", emoji="🔹"))
        options.append(discord.SelectOption(label="🐢 ตามทีหลัง / Late Join", value="Late Join", emoji="🐢"))
        options.append(discord.SelectOption(label="💤 สแตนด์บาย / Standby", value="Standby", emoji="💤"))
        super().__init__(placeholder="เลือกความพร้อม...", min_values=1, max_values=len(options), options=options)

    async def callback(self, interaction: discord.Interaction):
        ev = get_event(self.event_id)
        if not ev or ev[7] == 0: return await interaction.response.send_message("🔒 ปิดแล้ว", ephemeral=True)
        
        reg_upsert(self.event_id, interaction.user.id, interaction.user.display_name, self.team, self.role, ", ".join(self.values))
        try: await self.dashboard_msg.edit(embed=create_dashboard_embed(self.event_id))
        except: pass
        
        # ✨ Auto-Dismiss
        await interaction.response.edit_message(content="✅ **ลงทะเบียนสำเร็จ!** (ปิดใน 5 วิ...)", view=None, delete_after=5.0)

class CustomStatusModal(Modal, title='ระบุสถานะของคุณ'):
    def __init__(self, event_id, team, role, dashboard_msg):
        super().__init__()
        self.event_id = event_id
        self.team = team
        self.role = role
        self.dashboard_msg = dashboard_msg
    status_input = TextInput(label='สถานะ', placeholder='เช่น เข้า 20.00', required=True)
    async def on_submit(self, interaction: discord.Interaction):
        reg_upsert(self.event_id, interaction.user.id, interaction.user.display_name, self.team, self.role, self.status_input.value)
        try: await self.dashboard_msg.edit(embed=create_dashboard_embed(self.event_id))
        except: pass
        await interaction.response.edit_message(content="✅ **สำเร็จ!**", view=None, delete_after=5.0)

class TeamSelect(Select):
    def __init__(self, event_id, role, dashboard_msg):
        self.event_id = event_id
        self.role_value = role
        self.dashboard_msg = dashboard_msg
        
        ev = get_event(event_id)
        teams = ev[4].split(",") 
        options = []
        for t in teams: options.append(discord.SelectOption(label=t, value=t, emoji="🛡️"))
        super().__init__(placeholder="เลือกทีม...", min_values=1, max_values=1, options=options)
    
    async def callback(self, interaction: discord.Interaction):
        view = View().add_item(StatusSelect(self.event_id, self.values[0], self.role_value, self.dashboard_msg))
        await interaction.response.edit_message(content=f"⏳ ระบุความพร้อม **{self.values[0]}**:", view=view)

class RoleSelect(Select):
    def __init__(self, event_id):
        self.event_id = event_id
        super().__init__(placeholder="เลือกตำแหน่งของคุณ...", options=[
            discord.SelectOption(label="Tank", value="Tank", emoji="🛡️"),
            discord.SelectOption(label="Main DPS", value="DPS", emoji="⚔️"),
            discord.SelectOption(label="Healer", value="Heal", emoji="🌿"),
        ])
    async def callback(self, interaction: discord.Interaction):
        ev = get_event(self.event_id)
        if not ev or ev[7] == 0: return await interaction.response.send_message("🔒 ปิดแล้ว", ephemeral=True)
        view = View(timeout=60).add_item(TeamSelect(self.event_id, self.values[0], interaction.message))
        await interaction.response.send_message("👉 **กรุณาเลือกทีม:**", view=view, ephemeral=True)

class PersistentWarView(View):
    def __init__(self, event_id):
        super().__init__(timeout=None)
        self.event_id = event_id
        self.add_item(RoleSelect(event_id))
    
    @discord.ui.button(label="🔄 รีเฟรช", style=discord.ButtonStyle.blurple, row=2, custom_id="refresh")
    async def refresh(self, interaction: discord.Interaction, button: Button):
        await interaction.response.edit_message(embed=create_dashboard_embed(self.event_id))

    @discord.ui.button(label="🏳️ แจ้งลา", style=discord.ButtonStyle.gray, row=2, custom_id="absence")
    async def absence(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(AbsenceModal(self.event_id, interaction.message))

    @discord.ui.button(label="❌ ลบชื่อ", style=discord.ButtonStyle.red, row=2, custom_id="leave")
    async def leave(self, interaction: discord.Interaction, button: Button):
        reg_remove(self.event_id, interaction.user.id)
        await interaction.response.edit_message(embed=create_dashboard_embed(self.event_id))
        await interaction.followup.send("🗑️ ลบชื่อเรียบร้อย", ephemeral=True)

    @discord.ui.button(label="📋 Copy", style=discord.ButtonStyle.secondary, row=2, custom_id="copy")
    async def copy(self, interaction: discord.Interaction, button: Button):
        data = get_roster(self.event_id)
        txt = f"Event #{self.event_id}\n" + "\n".join([f"{u} ({r})" for u,_,r,_ in data])
        await interaction.response.send_message(f"```{txt}```", ephemeral=True)

class AbsenceModal(Modal, title='แบบฟอร์มแจ้งลา'):
    def __init__(self, event_id, dashboard_msg):
        super().__init__()
        self.event_id = event_id
        self.dashboard_msg = dashboard_msg
    reason = TextInput(label='เหตุผล', required=True)
    async def on_submit(self, interaction: discord.Interaction):
        reg_upsert(self.event_id, interaction.user.id, interaction.user.display_name, "Absence", self.reason.value, "-")
        try: await self.dashboard_msg.edit(embed=create_dashboard_embed(self.event_id))
        except: pass
        await interaction.response.send_message("🏳️ บันทึกแล้ว", ephemeral=True, delete_after=5.0)

# ==========================================
# 🔘 DASHBOARD LINK
# ==========================================
class DashboardLinkView(discord.ui.View):
    def __init__(self, guild_id, channel_id, message_id):
        super().__init__(timeout=None)
        url = f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"
        self.add_item(discord.ui.Button(label="📍 ไปที่ห้องลงชื่อ (Dashboard)", style=discord.ButtonStyle.link, url=url))

# ==========================================
# 🤖 BOT COMMANDS
# ==========================================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    init_db()
    await bot.tree.sync()
    if not auto_reminder.is_running(): auto_reminder.start()
    conn = sqlite3.connect(DB_NAME)
    rows = conn.execute("SELECT event_id FROM events WHERE active=1").fetchall()
    conn.close()
    for (ev_id,) in rows:
        bot.add_view(PersistentWarView(ev_id))
    print(f'✅ Bot Online: {bot.user}')

@bot.tree.command(name="setup_war", description="ตั้งค่าตารางวอ (แบบปุ่มกด)")
async def setup_war(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator: return
    get_session(interaction.user.id) # Init session
    await interaction.response.send_message(embed=create_setup_embed(interaction.user.id), view=SetupView(), ephemeral=True)

@bot.tree.command(name="check_missing", description="ตามคนขาด (ระบุ Event ID)")
async def check_missing(interaction: discord.Interaction, event_id: int, target_role: discord.Role = None):
    ev = get_event(event_id)
    if not ev: return await interaction.response.send_message("❌ ไม่พบ Event ID นี้", ephemeral=True)
    _, title, date_str, time_str, _, ch_id, msg_id, active = ev 

    conn = sqlite3.connect(DB_NAME)
    reg_ids = {row[0] for row in conn.execute("SELECT user_id FROM registrations WHERE event_id=?", (event_id,))}
    conn.close()

    missing = []
    targets = target_role.members if target_role else interaction.guild.members
    for m in targets:
        if not m.bot and m.id not in reg_ids: missing.append(m.mention)

    target_ch = bot.get_channel(ALERT_CHANNEL_ID_FIXED) or interaction.channel
    
    if not missing:
        await interaction.response.send_message("✅ ครบแล้ว!", ephemeral=True)
    else:
        view = DashboardLinkView(interaction.guild.id, ch_id, msg_id)
        
        # 📢 ประกาศพร้อมรายละเอียด
        header = f"⚔️ **MISSING ROSTER: {title}** ⚔️\n"
        header += f"📅 **Date:** {date_str} | ⏰ **Time:** {time_str}\n"
        header += f"🆔 **Event ID:** #{event_id}\n"
        header += f"⚠️ สมาชิกที่ยังไม่ลงชื่อ **({len(missing)} คน)**:\n"
        header += f"╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼\n"
        content = " ".join(missing)
        footer = f"\n╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼\n👇 **กดปุ่มด้านล่างเพื่อไปที่ห้องลงชื่อ (Dashboard) ได้เลยครับ**"

        try:
            if len(header+content+footer) > 2000:
                await target_ch.send(header + " (ส่วนที่ 1)", allowed_mentions=discord.AllowedMentions.none())
                await target_ch.send(" ".join(missing), allowed_mentions=discord.AllowedMentions.none())
                await target_ch.send(footer, view=view, allowed_mentions=discord.AllowedMentions.none())
            else:
                await target_ch.send(header+content+footer, view=view, allowed_mentions=discord.AllowedMentions.none())
            await interaction.response.send_message(f"✅ ส่งประกาศตามคนขาด Event #{event_id} แล้ว", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"Error: {e}", ephemeral=True)

@bot.tree.command(name="close_war", description="จบงานและปิดตาราง (ระบุ Event ID)")
async def close_war(interaction: discord.Interaction, event_id: int):
    close_event_db(event_id)
    ev = get_event(event_id)
    if ev:
        try:
            ch = bot.get_channel(ev[5])
            msg = await ch.fetch_message(ev[6])
            await msg.edit(embed=create_dashboard_embed(event_id))
        except: pass
    
    # ✅ ส่ง History (Restore)
    if HISTORY_CHANNEL_ID:
        try:
            hist_ch = bot.get_channel(HISTORY_CHANNEL_ID)
            if hist_ch:
                embed = create_dashboard_embed(event_id)
                embed.title = f"📜 สรุปยอดวอ (Event #{event_id}) - จบงาน"
                await hist_ch.send(embed=embed)
        except: pass

    await interaction.response.send_message(f"🔴 ปิดงาน Event #{event_id} เรียบร้อย", ephemeral=True)

@bot.tree.command(name="leaderboard", description="ดูอันดับการเข้าวอ")
async def leaderboard(interaction: discord.Interaction):
    data = db_get_leaderboard()
    if not data: return await interaction.response.send_message("❌ ยังไม่มีข้อมูล", ephemeral=True)
    embed = discord.Embed(title="🏆 Guild War Leaderboard", color=discord.Color.gold())
    desc = ""
    for i, (name, count) in enumerate(data):
        medal = "🥇" if i==0 else "🥈" if i==1 else "🥉" if i==2 else f"#{i+1}"
        desc += f"{medal} **{name}** : {count} ครั้ง\n"
    embed.description = desc
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="shutdown", description="ปิดบอท")
async def shutdown(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator: return
    await interaction.response.send_message("👋 Bye", ephemeral=True)
    await bot.close()

# --- TASKS ---
@tasks.loop(minutes=1)
async def auto_reminder():
    now = bangkok_now()
    conn = sqlite3.connect(DB_NAME)
    events = conn.execute("SELECT * FROM events WHERE active=1").fetchall()
    conn.close()

    for ev in events:
        ev_id, title, _, time_str, _, _, _, _ = ev
        try:
            target_time = datetime.strptime(time_str, "%H:%M")
            target_dt = now.replace(hour=target_time.hour, minute=target_time.minute, second=0)
            diff = (target_dt - now).total_seconds()
            
            if 840 < diff <= 900:
                ch = bot.get_channel(ALERT_CHANNEL_ID_FIXED)
                if ch: await ch.send(f"📢 **แจ้งเตือน Event #{ev_id}:** อีก 15 นาทีจะเริ่ม **{title}**! @everyone")
        except: pass

bot.run('YOUR_TOKEN_HERE')