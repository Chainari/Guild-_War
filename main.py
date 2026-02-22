import os
import discord
import asyncio
from discord import app_commands
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

# 🔥 ใช้ DB ตัวเดิมได้เลย
DB_NAME = "guildwar_system_v9_weapons.db"

# 👇 กรุณาตรวจสอบ ID ห้องให้ถูกต้อง
ALERT_CHANNEL_ID_FIXED = 1444345312188698738
LOG_CHANNEL_ID = 1472149965299253457
HISTORY_CHANNEL_ID = 1472149894096621639

# 📦 SESSION STORAGE
setup_sessions = {}

# ==========================================
# 🗄️ DATABASE SYSTEM
# ==========================================
def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS events
                (event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                date_str TEXT,
                time_str TEXT,
                teams TEXT,
                color INTEGER DEFAULT 3447003,
                channel_id INTEGER,
                message_id INTEGER,
                active INTEGER DEFAULT 1)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS registrations
                (event_id INTEGER,
                user_id INTEGER,
                username TEXT,
                team TEXT,
                role TEXT,
                time_text TEXT,
                weapons TEXT,
                joined_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (event_id, user_id))''')
    conn.commit()
    conn.close()

def create_event(title, date_str, time_str, teams_list, color):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    teams_str = ",".join(teams_list)
    c.execute("INSERT INTO events (title, date_str, time_str, teams, color, active) VALUES (?, ?, ?, ?, ?, 1)",
            (title, date_str, time_str, teams_str, color))
    eid = c.lastrowid
    conn.commit()
    conn.close()

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

def delete_event_db(event_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM events WHERE event_id=?", (event_id,))
    c.execute("DELETE FROM registrations WHERE event_id=?", (event_id,))
    conn.commit()
    conn.close()

def reg_upsert(event_id, user_id, username, team, role, time_text, weapons):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''INSERT OR REPLACE INTO registrations
                (event_id, user_id, username, team, role, time_text, weapons, joined_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)''',
            (event_id, user_id, username, team, role, time_text, weapons))
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
    c.execute("SELECT username, team, role, time_text, weapons FROM registrations WHERE event_id=? ORDER BY joined_at ASC", (event_id,))
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
# 🧠 HELPER FUNCTIONS
# ==========================================
async def send_log(bot, action_type, description, user):
    if not LOG_CHANNEL_ID: return
    try:
        ch = bot.get_channel(LOG_CHANNEL_ID)
        if not ch: return
        color = 0x3498db
        icon = "📝"
        if action_type == "Create": color, icon = 0x2ecc71, "✅"
        elif action_type in ["Delete", "Leave"]: color, icon = 0xe74c3c, "🗑️"
        elif action_type == "Close": color, icon = 0xe67e22, "🔒"
        elif action_type == "Absence": color, icon = 0x95a5a6, "🏳️"
        elif action_type == "Join": color, icon = 0x3498db, "📝"

        embed = discord.Embed(title=f"{icon} บันทึกกิจกรรม: {action_type}", description=description, color=color)
        embed.set_author(name=user.display_name, icon_url=user.display_avatar.url)
        embed.set_footer(text=f"User ID: {user.id} | {bangkok_now().strftime('%d/%m/%Y %H:%M')}")
        if user.display_avatar: embed.set_thumbnail(url=user.display_avatar.url)
        await ch.send(embed=embed)
    except: pass

def parse_event_datetime(date_str, time_str):
    now = bangkok_now()
    try:
        t = datetime.strptime(time_str, "%H:%M").time()
        target_date = None
        d_str = date_str.lower().strip()
        if d_str in ["today", "วันนี้"]: target_date = now.date()
        elif d_str in ["tomorrow", "พรุ่งนี้"]: target_date = now.date() + timedelta(days=1)
        else:
            try:
                clean_date = d_str.split(" ")[0]
                dt_obj = datetime.strptime(clean_date, "%d/%m")
                target_date = dt_obj.replace(year=now.year).date()
                if target_date < now.date() and (now.month - target_date.month) > 6:
                    target_date = target_date.replace(year=now.year + 1)
            except: return None 
        if target_date:
            return now.replace(year=target_date.year, month=target_date.month, day=target_date.day, hour=t.hour, minute=t.minute, second=0)
    except: return None
    return None

def format_full_date(date_str):
    now = bangkok_now()
    try:
        target_date = None
        d_str = date_str.lower().strip()
        if d_str in ["today", "วันนี้"]: target_date = now.date()
        elif d_str in ["tomorrow", "พรุ่งนี้"]: target_date = now.date() + timedelta(days=1)
        else:
            clean_date = d_str.split(" ")[0]
            dt_obj = datetime.strptime(clean_date, "%d/%m")
            target_date = dt_obj.replace(year=now.year).date()
            if target_date < now.date() and (now.month - target_date.month) > 6:
                target_date = target_date.replace(year=now.year + 1)
        if target_date: return target_date.strftime("%A, %d %B %Y")
    except: pass
    return date_str

async def event_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[int]]:
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT event_id, title, date_str FROM events WHERE active=1") 
    events = c.fetchall()
    conn.close()
    choices = []
    for eid, title, dstr in events:
        display_name = f"#{eid} | {title} ({dstr})"
        if current.lower() in display_name.lower():
            choices.append(app_commands.Choice(name=display_name, value=eid))
    return choices[:25]

# ==========================================
# 📊 DASHBOARD GENERATOR
# ==========================================
def make_visual_bar(dps, tank, heal):
    total = dps + tank + heal
    limit = 10
    if total == 0: return "⚫" * limit
    
    # 🛠️ แก้บัค Total: ให้ 1 คน = 1 จุด หากจำนวนคนไม่เกิน Limit
    if total <= limit:
        c_dps = dps
        c_tank = tank
        c_heal = heal
    else:
        # ถ้าคนเกิน limit ค่อยคำนวณสัดส่วน %
        c_dps = int((dps / total) * limit)
        c_tank = int((tank / total) * limit)
        c_heal = limit - (c_dps + c_tank)
        
    bar = ("🔴" * c_dps) + ("🔵" * c_tank) + ("🟢" * c_heal)
    current_len = c_dps + c_tank + c_heal
    if current_len < limit: 
        bar += "⚫" * (limit - current_len)
    return f"`{bar}`"

def create_dashboard_embed(event_id):
    event = get_event(event_id)
    if not event: return discord.Embed(title="❌ Event Not Found")
    
    ev_id, title, date_str, time_str, teams_str, color_val, _, _, active = event
    teams = teams_str.split(",")
    data = get_roster(event_id)

    stats = {t: {"DPS":0, "Tank":0, "Heal":0, "Total":0} for t in teams}
    roster = {t: {"Main": [], "Late": [], "Standby": []} for t in teams}
    absence_list = []

    for username, team, role, time_text, weapons in data:
        if team == "Absence":
            absence_list.append(f"❌ `{username}` : {role} [{time_text}]")
            continue
            
        if team not in stats: continue
        
        is_main = "Late Join" not in time_text and "Standby" not in time_text
        
        if is_main:
            stats[team]["Total"] += 1
            if role in stats[team]: stats[team][role] += 1
            
        emoji = "⚔️" if "DPS" in role else "🛡️" if "Tank" in role else "🌿"
        
        # 🔥 ตัดชื่ออาวุธออก เพื่อให้ตารางคลีน (ย้ายไปดูในปุ่มแยก)
        
        if is_main:
            on, off = "🟢", "⚫"
            if "Full Time" in time_text: bar = f"{on*4} {on*4}"
            elif "Round" in time_text:
                rounds_visual = []
                for i in range(1, 9):
                    if f"Round {i}" in time_text: rounds_visual.append(on)
                    else: rounds_visual.append(off)
                bar = "".join(rounds_visual[:4]) + " " + "".join(rounds_visual[4:])
            else: bar = f"[{time_text}]"
            
            # 🔥 เรียงเลข + หลอด + ชื่อ (ไม่มีอาวุธต่อท้าย)
            num = len(roster[team]["Main"]) + 1
            display = f"> `{num}.` `{bar}` | {emoji} **{username}**"
            roster[team]["Main"].append(display)
            
        elif "Late" in time_text or "🐢" in time_text:
            roster[team]["Late"].append(f"> `🐢 Late Join` | {emoji} **{username}** ({role})")
        elif "Standby" in time_text or "💤" in time_text:
            roster[team]["Standby"].append(f"> `💤 Standby` | {emoji} **{username}** ({role})")

    status_text = "🟢 OPEN REGISTRATION" if active else "🔒 LOCKED / ENDED"
    final_color = color_val if active else 0xff2e4c
    full_date_text = format_full_date(date_str)
    
    desc = f"```ansi\n\u001b[0;33m# ⏰ START: {time_str} น.\u001b[0m```\n📅 **Date:** {full_date_text}\n━━━━━━━━━━━━━━━━━━━━━━"
    embed = discord.Embed(title=f"⚔️ {title}", description=desc, color=final_color)
    
    for t in teams:
        s = stats[t]
        visual_bar = make_visual_bar(s['DPS'], s['Tank'], s['Heal'])
        header_text = f"🔥 Total: {s['Total']} (🛡️{s['Tank']} ⚔️{s['DPS']} 🌿{s['Heal']})\n{visual_bar}\n"
        val = header_text + "\n"
        if roster[t]["Main"]: val += "\n".join(roster[t]["Main"])
        else: val += "*... ว่าง ...*"
        if roster[t]["Late"]: val += "\n\n**🐢 มาสาย / Late Join**\n" + "\n".join(roster[t]["Late"])
        if roster[t]["Standby"]: val += "\n\n**💤 สำรอง / Standby**\n" + "\n".join(roster[t]["Standby"])
        val += "\n\u200b"
        embed.add_field(name=f"▬▬▬▬ {t.upper()} ▬▬▬▬", value=val, inline=False)
        
    if absence_list: embed.add_field(name="🏳️ แจ้งลา (Absence)", value="\n".join(absence_list), inline=False)
    embed.set_footer(text=f"EVENT ID: #{event_id} | STATUS: {status_text} | Last Updated: {bangkok_now().strftime('%H:%M:%S')}")
    return embed

# ==========================================
# 🛠️ SETUP SYSTEM
# ==========================================
def get_session(user_id):
    if user_id not in setup_sessions:
        setup_sessions[user_id] = {"title": "Guild War Roster", "date": "Today", "time": "19:30", "teams": ["Team ATK", "Team Flex"], "color": 0x3498db}
    return setup_sessions[user_id]

def create_setup_embed(user_id):
    s = get_session(user_id)
    full_date_preview = format_full_date(s['date'])
    color_hex = hex(s['color']).replace("0x", "#").upper()
    
    embed = discord.Embed(title="🛠️ ตั้งค่าตารางวอ (Setup Mode)", description="ปรับแต่งข้อมูลก่อนประกาศจริง", color=s['color'])
    embed.add_field(name="📝 หัวข้อ", value=s["title"], inline=False)
    embed.add_field(name="📅 วันที่", value=full_date_preview, inline=True)
    embed.add_field(name="⏰ เวลา", value=s["time"], inline=True)
    teams_str = "\n".join([f"- {t}" for t in s["teams"]])
    embed.add_field(name=f"🛡️ ทีม ({len(s['teams'])})", value=f"```\n{teams_str}\n```", inline=False)
    embed.add_field(name="🎨 สีธีม", value=f"`{color_hex}`", inline=False)
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
        for i in range(0, 24):
            d = now + timedelta(days=i)
            day_name = d.strftime("%a")
            date_val = d.strftime("%d/%m")
            label = f"{date_val} ({day_name})"
            emoji = "📅"
            if i == 0: label = f"วันนี้ ({label})"
            if i == 1: label = f"พรุ่งนี้ ({label})"
            options.append(discord.SelectOption(label=label, value=date_val, emoji=emoji))
        super().__init__(placeholder="📅 เลือกวันที่ (ล่วงหน้า 3 สัปดาห์)...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "manual": await interaction.response.send_modal(ConfigModal('date_manual'))
        else:
            s = get_session(interaction.user.id)
            s['date'] = self.values[0]
            await interaction.response.edit_message(embed=create_setup_embed(interaction.user.id), view=SetupView())

class ColorSelect(Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="ฟ้า (Cyan)", value="cyan", emoji="🟦"),
            discord.SelectOption(label="แดง (Red)", value="red", emoji="🟥"),
            discord.SelectOption(label="เขียว (Green)", value="green", emoji="🟩"),
            discord.SelectOption(label="เหลือง (Yellow)", value="yellow", emoji="🟨"),
            discord.SelectOption(label="ม่วง (Purple)", value="purple", emoji="🟪"),
            discord.SelectOption(label="ชมพู (Pink)", value="pink", emoji="🌸"),
        ]
        super().__init__(placeholder="🎨 เลือกสีธีม...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        s = get_session(interaction.user.id)
        val = self.values[0]
        colors = {"cyan": 0x3498db, "red": 0xe74c3c, "green": 0x2ecc71, "yellow": 0xf1c40f, "purple": 0x9b59b6, "pink": 0xff9ff3}
        s['color'] = colors.get(val, 0x3498db)
        await interaction.response.edit_message(embed=create_setup_embed(interaction.user.id), view=SetupView())

class DatePickerView(View):
    def __init__(self):
        super().__init__()
        self.add_item(DateSelect())

class ColorPickerView(View):
    def __init__(self):
        super().__init__()
        self.add_item(ColorSelect())

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
    @discord.ui.button(label="🎨 เลือกสี", style=discord.ButtonStyle.secondary, row=1)
    async def edit_color(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message("เลือกสีธีม:", view=ColorPickerView(), ephemeral=True)
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
        await interaction.response.defer() 
        s = get_session(interaction.user.id)
        ev_id = create_event(s['title'], s['date'], s['time'], s['teams'], s['color'])
        embed = create_dashboard_embed(ev_id)
        view = PersistentWarView(ev_id)
        msg = await interaction.channel.send(embed=embed, view=view)
        update_event_msg(ev_id, msg.channel.id, msg.id)
        await send_log(interaction.client, "Create", f"สร้าง Event #{ev_id} ({s['title']})", interaction.user)
        del setup_sessions[interaction.user.id]
        await interaction.edit_original_response(content=f"✅ **ประกาศเรียบร้อย!**\n🆔 **Event ID: {ev_id}**", embed=None, view=None)
    @discord.ui.button(label="❌ ยกเลิก", style=discord.ButtonStyle.red, row=3)
    async def cancel(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer()
        try:
            await interaction.delete_original_response()
            if interaction.user.id in setup_sessions: del setup_sessions[interaction.user.id]
        except: pass

# ==========================================
# 📝 UI COMPONENTS
# ==========================================
class WeaponSelect(Select):
    def __init__(self, event_id, team, role, status_text, dashboard_msg):
        self.event_id = event_id
        self.team = team
        self.role = role
        self.status_text = status_text
        self.dashboard_msg = dashboard_msg
        
        # 🔥 อาวุธ 16 ชนิด
        options = [
            discord.SelectOption(label="Nameless Sword", description="ดาบไร้นาม", emoji="⚔️"),
            discord.SelectOption(label="Nameless Spear", description="หอกไร้นาม", emoji="🦯"),
            discord.SelectOption(label="Strategic Sword", description="ดาบเลือด", emoji="🩸"),
            discord.SelectOption(label="Heavenquaker Spear", description="หอกเลือด", emoji="🩸"),
            discord.SelectOption(label="Thundercry Blade", description="ดาบสายฟ้า", emoji="⚡"),
            discord.SelectOption(label="Stormbreaker Spear", description="หอกแทงค์", emoji="🛡️"),
            discord.SelectOption(label="Infernal Twinblades", description="ดาบคู่", emoji="⚔️"),
            discord.SelectOption(label="Mortal Rope Dart", description="มีดติดเชือก", emoji="🪢"),
            discord.SelectOption(label="Vernal Umbrella", description="ร่ม DPS", emoji="☂️"),
            discord.SelectOption(label="Soulshade Umbrella", description="ร่ม Heal", emoji="🌿"),
            discord.SelectOption(label="Inkwell Fan", description="พัด DPS", emoji="🪭"),
            discord.SelectOption(label="Panacea Fan", description="พัด Heal", emoji="🍃"),
            discord.SelectOption(label="Hengdao", description="ดาบถังเหิง", emoji="🗡️"),
            discord.SelectOption(label="Gauntlets", description="สนับมือ / หมัด", emoji="🥊"),
            discord.SelectOption(label="Zui Meng You Chun", description="ร่มสายใหม่", emoji="🌂"),
            discord.SelectOption(label="Su Zi Xing Yun", description="มีดติดเชือก (แซ่) สายใหม่", emoji="⛓️")
        ]
        # จำกัดการเลือก 1 ถึง 2 ชิ้น
        super().__init__(placeholder="⚔️ เลือกอาวุธ (1 ถึง 2 ชิ้น)...", min_values=1, max_values=2, options=options)

    async def callback(self, interaction: discord.Interaction):
        ev = get_event(self.event_id)
        if not ev or ev[8] == 0: return await interaction.response.send_message("🔒 ปิดแล้ว", ephemeral=True)
        
        weapons_str = " + ".join(self.values)
        reg_upsert(self.event_id, interaction.user.id, interaction.user.display_name, self.team, self.role, self.status_text, weapons_str)
        
        try: await self.dashboard_msg.edit(embed=create_dashboard_embed(self.event_id))
        except: pass
        
        await send_log(interaction.client, "Join", f"ลงชื่อทีม **{self.team}**\nตำแหน่ง: {self.role}\nสถานะ: {self.status_text}\nอาวุธ: {weapons_str}", interaction.user)
        await interaction.response.edit_message(content="✅ **ลงทะเบียนสำเร็จ!** (ปิดใน 5 วิ...)", view=None, delete_after=5.0)

class StatusSelect(Select):
    def __init__(self, event_id, team, role, dashboard_msg):
        self.event_id, self.team, self.role, self.dashboard_msg = event_id, team, role, dashboard_msg
        options = [discord.SelectOption(label="🔥 อยู่ยาว / Full Time", value="Full Time", emoji="🔥")]
        for i in range(1, 9): options.append(discord.SelectOption(label=f"Round {i}", value=f"Round {i}", emoji="🔹"))
        options.append(discord.SelectOption(label="🐢 ตามทีหลัง / Late Join", value="Late Join", emoji="🐢"))
        options.append(discord.SelectOption(label="💤 สแตนด์บาย / Standby", value="Standby", emoji="💤"))
        super().__init__(placeholder="เลือกความพร้อม...", min_values=1, max_values=len(options), options=options)

    async def callback(self, interaction: discord.Interaction):
        status_text = ", ".join(self.values)
        # เด้งไปหน้าเลือกอาวุธต่อ
        view = View().add_item(WeaponSelect(self.event_id, self.team, self.role, status_text, self.dashboard_msg))
        await interaction.response.edit_message(content=f"⚔️ **ระบุอาวุธที่ใช้ (เลือก 1-2 ชิ้น)**", view=view)

class TeamSelect(Select):
    def __init__(self, event_id, role, dashboard_msg):
        self.event_id, self.role_value, self.dashboard_msg = event_id, role, dashboard_msg
        ev = get_event(event_id)
        teams = ev[4].split(",") 
        options = [discord.SelectOption(label=t, value=t, emoji="🛡️") for t in teams]
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
        if not ev or ev[8] == 0: return await interaction.response.send_message("🔒 ปิดแล้ว", ephemeral=True)
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

    # 🔥 ปุ่มใหม่! เช็คอาวุธแยกต่างหาก
    @discord.ui.button(label="🔍 เช็คอาวุธ", style=discord.ButtonStyle.primary, row=2, custom_id="check_weapons")
    async def check_weapons(self, interaction: discord.Interaction, button: Button):
        data = get_roster(self.event_id)
        ev = get_event(self.event_id)
        if not ev: return
        teams = ev[4].split(",")
        
        embed = discord.Embed(title=f"🔍 ข้อมูลอาวุธ Event #{self.event_id}", color=0x2ecc71)
        
        found_any = False
        for t in teams:
            team_players = [p for p in data if p[1] == t]
            if not team_players: continue
            
            val = ""
            for p in team_players:
                username, _, role, _, weapons = p
                # ไม่แสดงคนแจ้งลา
                if t == "Absence": continue

                emoji = "⚔️" if "DPS" in role else "🛡️" if "Tank" in role else "🌿"
                wp_text = weapons if weapons and weapons != "-" else "ยังไม่ระบุ"
                val += f"{emoji} **{username}** : `{wp_text}`\n"
            
            if val:
                found_any = True
                embed.add_field(name=f"▬▬▬▬ {t.upper()} ▬▬▬▬", value=val, inline=False)
        
        if not found_any:
            embed.description = "ยังไม่มีข้อมูลการลงชื่อ หรือ อาวุธ"

        # ส่งข้อความแบบ ephemeral (เห็นแค่คนกด)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="🏳️ แจ้งลา", style=discord.ButtonStyle.gray, row=2, custom_id="absence")
    async def absence(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(AbsenceModal(self.event_id, interaction.message))

    @discord.ui.button(label="❌ ลบชื่อ", style=discord.ButtonStyle.red, row=2, custom_id="leave")
    async def leave(self, interaction: discord.Interaction, button: Button):
        reg_remove(self.event_id, interaction.user.id)
        await interaction.response.edit_message(embed=create_dashboard_embed(self.event_id))
        await send_log(interaction.client, "Leave", f"ลบชื่อออกจาก Event #{self.event_id}", interaction.user)
        await interaction.followup.send("🗑️ ลบชื่อเรียบร้อย", ephemeral=True)

    @discord.ui.button(label="📋 Copy", style=discord.ButtonStyle.secondary, row=2, custom_id="copy")
    async def copy(self, interaction: discord.Interaction, button: Button):
        data = get_roster(self.event_id)
        ev = get_event(self.event_id)
        if not ev: return
        teams = ev[4].split(",")
        
        txt = f"```text\n📋 สรุปรายชื่อ Event #{self.event_id}\n"
        txt += "=========================\n"
        
        for t in teams:
            team_players = [p for p in data if p[1] == t]
            if not team_players: continue
            
            txt += f"🛡️ {t.upper()}\n"
            main = [p for p in team_players if "Late" not in p[3] and "Standby" not in p[3]]
            late = [p for p in team_players if "Late" in p[3]]
            standby = [p for p in team_players if "Standby" in p[3]]
            
            for i, p in enumerate(main, 1):
                txt += f"{i}. {p[0]} ({p[2]}) - {p[3]} [{p[4]}]\n"
            
            if late:
                txt += "\n*🐢 สาย (Late):*\n"
                for p in late: txt += f"- {p[0]} ({p[2]}) [{p[4]}]\n"
                
            if standby:
                txt += "\n*💤 สำรอง (Standby):*\n"
                for p in standby: txt += f"- {p[0]} ({p[2]}) [{p[4]}]\n"
                
            txt += "-------------------------\n"
            
        txt += "```"
        await interaction.response.send_message(txt, ephemeral=True)

class AbsenceModal(Modal, title='แบบฟอร์มแจ้งลา'):
    def __init__(self, event_id, dashboard_msg):
        super().__init__()
        self.event_id, self.dashboard_msg = event_id, dashboard_msg
    reason = TextInput(label='เหตุผล', required=True)
    async def on_submit(self, interaction: discord.Interaction):
        reg_upsert(self.event_id, interaction.user.id, interaction.user.display_name, "Absence", "-", self.reason.value, "-")
        try: await self.dashboard_msg.edit(embed=create_dashboard_embed(self.event_id))
        except: pass
        await send_log(interaction.client, "Absence", f"แจ้งลา Event #{self.event_id}\nเหตุผล: {self.reason.value}", interaction.user)
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

@bot.command()
async def sync(ctx):
    if ctx.author.guild_permissions.administrator:
        synced = await bot.tree.sync()
        await ctx.send(f"✅ Synced {len(synced)} commands เรียบร้อย!")
    else:
        await ctx.send("❌ คุณต้องเป็นแอดมิน")

@bot.tree.command(name="setup_war", description="ตั้งค่าตารางวอ (แบบปุ่มกด)")
async def setup_war(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator: return
    get_session(interaction.user.id) 
    await interaction.response.send_message(embed=create_setup_embed(interaction.user.id), view=SetupView(), ephemeral=True)

@bot.tree.command(name="check_missing", description="ตามคนขาด (ระบุ Event)")
@app_commands.autocomplete(event_id=event_autocomplete)
async def check_missing(interaction: discord.Interaction, event_id: int, target_role: discord.Role = None):
    ev = get_event(event_id)
    if not ev: return await interaction.response.send_message("❌ ไม่พบ Event ID นี้", ephemeral=True)
    _, title, date_str, time_str, _, _, ch_id, msg_id, active = ev 

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
        full_date_text = format_full_date(date_str)
        header = f"⚔️ **MISSING ROSTER: {title}** ⚔️\n"
        header += f"📅 **Date:** {full_date_text} | ⏰ **Time:** {time_str}\n"
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

@bot.tree.command(name="close_war", description="จบงานและปิดตาราง (ระบุ Event)")
@app_commands.autocomplete(event_id=event_autocomplete)
async def close_war(interaction: discord.Interaction, event_id: int):
    # เปลี่ยนสถานะใน DB เป็น 0 (LOCKED)
    close_event_db(event_id)
    ev = get_event(event_id)
    
    # 🔥 ลบตารางเดิมทิ้งตามคำขอ
    if ev:
        try:
            ch = bot.get_channel(ev[6])
            msg = await ch.fetch_message(ev[7])
            await msg.delete() # ลบข้อความ Dashboard 
        except: pass
    
    # ส่งตารางสรุปแบบล็อคไปห้อง History
    if HISTORY_CHANNEL_ID:
        try:
            hist_ch = bot.get_channel(HISTORY_CHANNEL_ID)
            if hist_ch:
                embed = create_dashboard_embed(event_id)
                embed.title = f"📜 สรุปยอดวอ (Event #{event_id}) - จบงาน"
                await hist_ch.send(embed=embed)
        except Exception as e:
            print(f"❌ History Send Fail: {e}")

    await send_log(interaction.client, "Close", f"ปิดงาน Event #{event_id} และลบตารางแล้ว", interaction.user)
    await interaction.response.send_message(f"🔴 ปิดงาน Event #{event_id} และลบตารางออกจากห้องเรียบร้อย", ephemeral=True)

@bot.tree.command(name="delete_event", description="ลบตารางและข้อมูลทั้งหมด (ระบุ Event)")
@app_commands.autocomplete(event_id=event_autocomplete)
async def delete_event(interaction: discord.Interaction, event_id: int):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้คำสั่งนี้", ephemeral=True)

    ev = get_event(event_id)
    if not ev:
        return await interaction.response.send_message(f"❌ ไม่พบ Event ID: {event_id}", ephemeral=True)

    _, title, _, _, _, _, ch_id, msg_id, _ = ev
    delete_event_db(event_id) 

    try:
        ch = bot.get_channel(ch_id)
        if ch:
            msg = await ch.fetch_message(msg_id)
            await msg.delete() 
    except: pass

    await send_log(interaction.client, "Delete", f"ลบ Event #{event_id} ถาวร", interaction.user)
    await interaction.response.send_message(f"🗑️ **ลบข้อมูล Event #{event_id} เรียบร้อยแล้ว!**", ephemeral=True)

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
        ev_id, title, date_str, time_str, _, _, _, _, _ = ev
        try:
            event_dt = parse_event_datetime(date_str, time_str)
            if not event_dt: continue

            diff = (event_dt - now).total_seconds()
            
            # 🛠️ เวลาแจ้งเตือน 30 นาที (1740-1800 วินาที)
            if 1740 < diff <= 1800:
                ch = bot.get_channel(ALERT_CHANNEL_ID_FIXED)
                if ch: await ch.send(f"📢 **แจ้งเตือน Event #{ev_id}:** อีก 30 นาทีจะเริ่ม **{title}**! @everyone")
        except: pass

bot.run('Y')