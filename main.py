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
DB_NAME = "guildwar_system_v11_ui.db"

ALERT_CHANNEL_ID_FIXED = 1444345312188698738
LOG_CHANNEL_ID = 1472149965299253457
HISTORY_CHANNEL_ID = 1472149894096621639

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
    try: c.execute("ALTER TABLE events ADD COLUMN team_limit INTEGER DEFAULT 0")
    except: pass
    c.execute('''CREATE TABLE IF NOT EXISTS registrations
                (event_id INTEGER, user_id INTEGER, username TEXT, team TEXT, role TEXT, time_text TEXT, weapons TEXT, joined_at DATETIME DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (event_id, user_id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS guild_members
                (user_id INTEGER PRIMARY KEY, username TEXT, role TEXT, weapons TEXT, joined_at DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    try: c.execute("ALTER TABLE guild_members ADD COLUMN weapons TEXT")
    except: pass
    c.execute('''CREATE TABLE IF NOT EXISTS bot_config
                (config_name TEXT PRIMARY KEY, guild_id INTEGER, channel_id INTEGER, message_id INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS leave_records
                (user_id INTEGER PRIMARY KEY, username TEXT, leave_type TEXT, date_text TEXT, expiry_date DATETIME, reason TEXT, posted_at DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    conn.close()

def create_event(title, date_str, time_str, teams_list, color):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    teams_str = ",".join([f"{t['name']}|{t['limit']}" for t in teams_list])
    c.execute("INSERT INTO events (title, date_str, time_str, teams, color, active, team_limit) VALUES (?, ?, ?, ?, ?, 1, 0)", (title, date_str, time_str, teams_str, color))
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
    c.execute('''INSERT OR REPLACE INTO registrations (event_id, user_id, username, team, role, time_text, weapons, joined_at) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)''', (event_id, user_id, username, team, role, time_text, weapons))
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
    c.execute("SELECT user_id, username, team, role, time_text, weapons FROM registrations WHERE event_id=? ORDER BY joined_at ASC", (event_id,))
    data = c.fetchall()
    conn.close()
    return data

def db_get_leaderboard():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''SELECT username, COUNT(*) as count FROM registrations GROUP BY user_id ORDER BY count DESC LIMIT 10''')
    data = c.fetchall()
    conn.close()
    return data

def set_bot_config(name, guild_id, channel_id, message_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''INSERT OR REPLACE INTO bot_config (config_name, guild_id, channel_id, message_id) VALUES (?, ?, ?, ?)''', (name, guild_id, channel_id, message_id))
    conn.commit()
    conn.close()

def get_bot_config(name):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT guild_id, channel_id, message_id FROM bot_config WHERE config_name=?", (name,))
    row = c.fetchone()
    conn.close()
    return row

def member_upsert(user_id, username, role, weapons):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''INSERT OR REPLACE INTO guild_members (user_id, username, role, weapons, joined_at) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)''', (user_id, username, role, weapons))
    conn.commit()
    conn.close()

def member_remove(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM guild_members WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def get_all_members():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT username, role, weapons FROM guild_members ORDER BY joined_at ASC")
    data = c.fetchall()
    conn.close()
    return data

def clear_all_members():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM guild_members")
    conn.commit()
    conn.close()

def leave_upsert(user_id, username, leave_type, date_text, expiry_date_str, reason):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''INSERT OR REPLACE INTO leave_records (user_id, username, leave_type, date_text, expiry_date, reason, posted_at) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)''', (user_id, username, leave_type, date_text, expiry_date_str, reason))
    conn.commit()
    conn.close()

def leave_remove(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM leave_records WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def get_all_leaves():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''SELECT l.user_id, l.username, l.leave_type, l.date_text, l.expiry_date, l.reason, m.role FROM leave_records l LEFT JOIN guild_members m ON l.user_id = m.user_id ORDER BY l.posted_at ASC''')
    data = c.fetchall()
    conn.close()
    return data

# ==========================================
# 🧠 HELPER FUNCTIONS
# ==========================================
async def refresh_leave_board(bot_client):
    link = get_bot_config('leave_board')
    if not link: return
    guild_id, ch_id, msg_id = link
    try:
        ch = bot_client.get_channel(ch_id)
        if ch:
            msg = await ch.fetch_message(msg_id)
            await msg.edit(embed=create_leave_board_embed())
    except: pass

async def refresh_all_active_wars(bot_client):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT event_id, channel_id, message_id FROM events WHERE active=1")
    active_events = c.fetchall()
    conn.close()
    for ev_id, ch_id, msg_id in active_events:
        try:
            ch = bot_client.get_channel(ch_id)
            if ch:
                msg = await ch.fetch_message(msg_id)
                await msg.edit(embed=create_dashboard_embed(ev_id))
        except: pass

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

class DashboardLinkView(discord.ui.View):
    def __init__(self, guild_id, channel_id, message_id):
        super().__init__(timeout=None)
        url = f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"
        self.add_item(discord.ui.Button(label="📍 ไปที่ห้องลงชื่อ", style=discord.ButtonStyle.link, url=url))

# ==========================================
# 📊 GENERATORS (Dashboard & Leave Board)
# ==========================================
def make_visual_bar(dps, tank, heal):
    total = dps + tank + heal
    limit = 10
    if total == 0: return "⚫" * limit
    if total <= limit:
        c_dps = dps
        c_tank = tank
        c_heal = heal
    else:
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
    
    ev_id, title, date_str, time_str, teams_str, color_val, _, _, active = event[:9]
    parsed_teams = []
    parsed_limits = {}
    for t_str in teams_str.split(","):
        if "|" in t_str:
            name, limit_str = t_str.split("|")
            parsed_teams.append(name)
            parsed_limits[name] = int(limit_str)
        else:
            parsed_teams.append(t_str)
            parsed_limits[t_str] = 0

    data = get_roster(event_id)
    event_users = {p[0] for p in data}

    stats = {t: {"DPS":0, "Tank":0, "Heal":0, "Total":0} for t in parsed_teams}
    roster = {t: {"Main": [], "Late": [], "Standby": []} for t in parsed_teams}
    absence_list = []
    pre_late_list = []
    
    for user_id, username, team, role, time_text, weapons in data:
        if team == "Absence":
            absence_list.append(f"❌ `{username}` : {role} [{time_text}]")
            continue
        if team not in stats: continue
        
        is_late = "Late" in time_text or "🐢" in time_text
        is_standby = "Standby" in time_text or "💤" in time_text
        is_main = not (is_late or is_standby)
        
        if is_main:
            stats[team]["Total"] += 1
            if role in stats[team]: stats[team][role] += 1
            
        emoji = "🛡️" if "Tank" in role else "⚔️" if "DPS" in role else "🌿"
        
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
            
            num = len(roster[team]["Main"]) + 1
            display = f"`> {num:02}.` `{bar}` | {emoji} **{username}**"
            roster[team]["Main"].append(display)
            
        elif is_late:
            roster[team]["Late"].append(f"🐢 **{username}** [Late]")
        elif is_standby:
            roster[team]["Standby"].append(f"💤zZ **{username}** [Standby]")

    active_leaves = get_all_leaves()
    for l_uid, l_uname, l_type, l_dtext, l_exp, l_reason, l_role in active_leaves:
        if l_uid not in event_users: 
            role_txt = f" ({l_role})" if l_role else ""
            if l_type == 'late':
                pre_late_list.append(f"🐢 `{l_uname}{role_txt}` : {l_dtext} - {l_reason}")
            else:
                absence_list.append(f"❌ `{l_uname}{role_txt}` : 🛏️ พักรบ [{l_dtext}] - {l_reason}")

    status_text = "🟢 OPEN REGISTRATION" if active else "🔒 LOCKED / ENDED"
    final_color = color_val if active else 0xff2e4c
    full_date_text = format_full_date(date_str)
    
    desc = f"```ansi\n\u001b[0;33m# ⏰ START: {time_str} น.\u001b[0m```\n📅 **Date:** {full_date_text}\n-------------------------"
    embed = discord.Embed(title=f"⚔️ {title}", description=desc, color=final_color)
    
    for t in parsed_teams:
        s = stats[t]
        visual_bar = make_visual_bar(s['DPS'], s['Tank'], s['Heal'])
        limit_val = parsed_limits[t]
        limit_txt = f"/{limit_val}" if limit_val > 0 else ""
        
        header_text = f"🔥 Total: {s['Total']}{limit_txt} (🛡️{s['Tank']} ⚔️{s['DPS']} 🌿{s['Heal']})\n{visual_bar}\n\n"
        val = header_text + "\n"
        
        if roster[t]["Main"]: val += "\n".join(roster[t]["Main"])
        else: val += "*... ว่าง ...*"
        if roster[t]["Late"]: val += "\n\n**🐢 มาสาย / Late Join**\n" + "\n".join(roster[t]["Late"])
        if roster[t]["Standby"]: val += "\n\n**💤 สำรอง / Standby**\n" + "\n".join(roster[t]["Standby"])
        val += "\n\u200b"
        embed.add_field(name=f"━━━━━━ TEAM {t.upper()} ━━━━━━", value=val, inline=False)
        
    if pre_late_list: 
        embed.add_field(name="⏳ แจ้งมาสายล่วงหน้า (รอกดลงชื่อ)", value="\n".join(pre_late_list), inline=False)
    if absence_list: 
        embed.add_field(name="🏳️ แจ้งลา (Absence & Leave Board)", value="\n".join(absence_list), inline=False)
        
    embed.set_footer(text=f"EVENT ID: #{event_id} | STATUS: {status_text} | Last Updated: {bangkok_now().strftime('%H:%M:%S')}")
    return embed

# 🔥 1. แก้ไขดีไซน์ตารางแจ้งลาให้โปร่งและสวยขึ้น (ลดความเบียด)
def create_leave_board_embed():
    leaves = get_all_leaves()
    short_term = []
    late_list = []
    hiatus = []
    for uid, uname, ltype, dtext, exp, reason, role in leaves:
        role_txt = f" ({role})" if role else ""
        
        # จัดฟอร์แมตใหม่ให้มีการเว้นบรรทัดและใส่ Blockquote สวยงาม
        if ltype == "hiatus": 
            hiatus.append(f"> 💤 **{uname}**{role_txt}\n> └ 📝 เหตุผล: {reason} `[{dtext}]`")
        elif ltype == "late": 
            late_list.append(f"> 🐢 **{uname}**{role_txt}\n> └ ⏰ {dtext} *(เหตุผล: {reason})*")
        else: 
            short_term.append(f"> ❌ **{uname}**{role_txt}\n> └ 📝 เหตุผล: {reason} `[{dtext}]`")
            
    embed = discord.Embed(title="📋 บอร์ดแจ้งลาหยุด / พักรบกิลด์ 天狗", description="แอดมินและหัวหน้าหน่วยสามารถเช็ครายชื่อผู้ที่ไม่อยู่ได้ที่นี่\n*(ระบบจะเคลียร์รายชื่อเมื่อหมดเวลาอัตโนมัติ และลิงก์ชื่อเข้าตารางวอให้ทันที)*\n━━━━━━━━━━━━━━━━━━━━━━", color=0x34495e)
    
    # เพิ่ม \n\n เพื่อให้มีช่องไฟระหว่างรายชื่อแต่ละคน และ \n\u200b เพื่อเว้นวรรคหมวดหมู่
    val_short = "\n\n".join(short_term) if short_term else "> *... ไม่มีผู้ลาระยะสั้น ...*"
    embed.add_field(name="📅 ลาระยะสั้น (Short-term)", value=val_short + "\n\u200b", inline=False)
    
    if late_list:
        embed.add_field(name="⏳ แจ้งมาสายล่วงหน้า (Late)", value="\n\n".join(late_list) + "\n\u200b", inline=False)
        
    val_hiatus = "\n\n".join(hiatus) if hiatus else "> *... ไม่มีผู้ลาพักยาว ...*"
    embed.add_field(name="🛌 ลาพักยาว (Hiatus)", value=val_hiatus + "\n\u200b", inline=False)
    
    embed.set_footer(text=f"อัปเดตอัตโนมัติล่าสุด: {bangkok_now().strftime('%d/%m/%Y %H:%M:%S')}")
    return embed

def create_member_board_embed():
    data = get_all_members()
    roster = {"DPS": [], "Tank": [], "Heal": []}
    emojis = {"DPS": "⚔️", "Tank": "🛡️", "Heal": "🌿"}
    for username, role, weapons in data:
        if role in roster:
            emoji = emojis.get(role, "👤")
            wp_text = f"`{weapons}`" if weapons and weapons != "-" else "`ยังไม่ระบุอาวุธ`"
            num = len(roster[role]) + 1
            roster[role].append(f"`> {num}.` {emoji} **{username}** - {wp_text}")
    embed = discord.Embed(title="👺 ทำเนียบจอมยุทธ์กิลด์ 天狗", description="ลงทะเบียนสายตำแหน่งและอาวุธหลักของคุณ", color=0x2ecc71)
    roles_info = [("DPS", "⚔️ สังกัดหน่วยโจมตี (DPS)", roster["DPS"]), ("Tank", "🛡️ สังกัดหน่วยป้องกัน (Tank)", roster["Tank"]), ("Heal", "🌿 สังกัดหน่วยสนับสนุน (Heal)", roster["Heal"])]
    for role_key, role_title, members_list in roles_info:
        val = "\n".join(members_list) if members_list else "*... ยังไม่มีจอมยุทธ์ในสังกัดนี้ ...*"
        embed.add_field(name=f"{role_title} ({len(members_list)} คน)", value=val, inline=False)
    embed.set_footer(text=f"อัปเดตล่าสุด: {bangkok_now().strftime('%d/%m/%Y %H:%M')}")
    return embed

# ==========================================
# 🛠️ SETUP SYSTEM (Guild War - ปรับปรุงระบบโควต้าทีม)
# ==========================================
def get_session(user_id):
    if user_id not in setup_sessions:
        setup_sessions[user_id] = {
            "title": "Guild War Roster", "date": "Today", "time": "19:30", 
            "teams": [{"name": "Team ATK", "limit": 0}, {"name": "Team Flex", "limit": 0}], 
            "color": 0x3498db
        }
    return setup_sessions[user_id]

def create_setup_embed(user_id):
    s = get_session(user_id)
    full_date_preview = format_full_date(s['date'])
    color_hex = hex(s['color']).replace("0x", "#").upper()
    
    embed = discord.Embed(title="🛠️ ตั้งค่าตารางวอ (Setup Mode)", description="ปรับแต่งข้อมูลก่อนประกาศจริง", color=s['color'])
    embed.add_field(name="📝 หัวข้อ", value=s["title"], inline=False)
    embed.add_field(name="📅 วันที่", value=full_date_preview, inline=True)
    embed.add_field(name="⏰ เวลา", value=s["time"], inline=True)
    
    teams_str = "\n".join([f"- {t['name']} (จำกัด: {t['limit']} คน)" if t['limit']>0 else f"- {t['name']} (ไม่จำกัด)" for t in s["teams"]])
    embed.add_field(name=f"🛡️ ทีมทั้งหมด ({len(s['teams'])})", value=f"```\n{teams_str}\n```", inline=False)
    embed.add_field(name="🎨 สีธีม", value=f"`{color_hex}`", inline=False)
    return embed

class ConfigModal(Modal, title='แก้ไขข้อมูล'):
    def __init__(self, mode):
        super().__init__()
        self.mode = mode
        if mode == 'title': self.inp = TextInput(label='หัวข้อ', placeholder='Guild War')
        elif mode == 'time': self.inp = TextInput(label='เวลา (HH:MM)', placeholder='19:30', max_length=5)
        elif mode == 'date_manual': self.inp = TextInput(label='วันที่ (DD/MM)', placeholder='15/02')
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
        await interaction.response.edit_message(embed=create_setup_embed(interaction.user.id), view=SetupView())

class AddTeamModal(Modal, title='เพิ่มทีมใหม่'):
    def __init__(self):
        super().__init__()
        self.team_name = TextInput(label='ชื่อทีม', placeholder='เช่น Team Def', max_length=20)
        self.add_item(self.team_name)
    async def on_submit(self, interaction: discord.Interaction):
        s = get_session(interaction.user.id)
        s['teams'].append({"name": self.team_name.value.strip(), "limit": 0})
        await interaction.response.edit_message(embed=create_setup_embed(interaction.user.id), view=SetupView())

# 🔥 2. แก้ไขระบบจำกัดคนให้แก้ไขทีเดียวทุกทีม
class MultiLimitModal(Modal, title='กำหนดโควต้าตัวจริง (ทุกทีม)'):
    def __init__(self, user_id):
        super().__init__()
        self.s = get_session(user_id)
        self.inputs = []
        # ดึงทีมทั้งหมดมาแสดงในหน้าต่างเดียว (Discord จำกัดสูงสุด 5 ช่อง)
        for t in self.s['teams'][:5]:
            inp = TextInput(
                label=f"โควต้า: {t['name']}", 
                placeholder='ใส่ตัวเลข (0 = ไม่จำกัด)', 
                default=str(t['limit']), 
                max_length=3,
                required=True
            )
            self.add_item(inp)
            self.inputs.append(inp)

    async def on_submit(self, interaction: discord.Interaction):
        for i, inp in enumerate(self.inputs):
            try: lim = int(inp.value)
            except: lim = 0
            self.s['teams'][i]['limit'] = lim
        await interaction.response.edit_message(embed=create_setup_embed(interaction.user.id), view=SetupView())

class DatePickerView(View):
    def __init__(self):
        super().__init__()
        options = [discord.SelectOption(label="✏️ กรอกเอง...", value="manual", emoji="📝")]
        now = bangkok_now()
        for i in range(0, 24):
            d = now + timedelta(days=i)
            label = f"{'วันนี้ ' if i==0 else 'พรุ่งนี้ ' if i==1 else ''}{d.strftime('%d/%m')} ({d.strftime('%a')})"
            options.append(discord.SelectOption(label=label, value=d.strftime("%d/%m"), emoji="📅"))
        sel = Select(placeholder="📅 เลือกวันที่...", min_values=1, max_values=1, options=options)
        sel.callback = self.callback
        self.add_item(sel)
    async def callback(self, interaction: discord.Interaction):
        val = self.children[0].values[0]
        if val == "manual": await interaction.response.send_modal(ConfigModal('date_manual'))
        else:
            get_session(interaction.user.id)['date'] = val
            await interaction.response.edit_message(embed=create_setup_embed(interaction.user.id), view=SetupView())

class ColorPickerView(View):
    def __init__(self):
        super().__init__()
        options = [
            discord.SelectOption(label="ฟ้า (Cyan)", value="cyan", emoji="🟦"),
            discord.SelectOption(label="แดง (Red)", value="red", emoji="🟥"),
            discord.SelectOption(label="เขียว (Green)", value="green", emoji="🟩"),
            discord.SelectOption(label="เหลือง (Yellow)", value="yellow", emoji="🟨"),
            discord.SelectOption(label="ม่วง (Purple)", value="purple", emoji="🟪"),
        ]
        sel = Select(placeholder="🎨 เลือกสีธีม...", options=options)
        sel.callback = self.callback
        self.add_item(sel)
    async def callback(self, interaction: discord.Interaction):
        colors = {"cyan": 0x3498db, "red": 0xe74c3c, "green": 0x2ecc71, "yellow": 0xf1c40f, "purple": 0x9b59b6}
        get_session(interaction.user.id)['color'] = colors.get(self.children[0].values[0], 0x3498db)
        await interaction.response.edit_message(embed=create_setup_embed(interaction.user.id), view=SetupView())

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
    
    @discord.ui.button(label="👥 เพิ่มทีม", style=discord.ButtonStyle.success, row=2)
    async def add_team(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(AddTeamModal())
        
    @discord.ui.button(label="⚙️ กำหนดโควต้า", style=discord.ButtonStyle.primary, row=2)
    async def set_limit(self, interaction: discord.Interaction, button: Button):
        s = get_session(interaction.user.id)
        if not s['teams']:
            return await interaction.response.send_message("❌ ยังไม่มีทีม กรุณาเพิ่มทีมก่อน", ephemeral=True)
        # กดปุ่มนี้แล้ว Modal เด้งขึ้นมาให้ปรับทุกทีมพร้อมกันเลย
        await interaction.response.send_modal(MultiLimitModal(interaction.user.id))
        
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
        try: await interaction.delete_original_response()
        except: pass

# ==========================================
# 📝 ALL-IN-ONE REGISTRATION UI
# ==========================================
class RegistrationView(discord.ui.View):
    def __init__(self, event_id, dashboard_msg, parsed_teams):
        super().__init__(timeout=None)
        self.event_id = event_id
        self.dashboard_msg = dashboard_msg
        
        self.sel_team = Select(placeholder="1️⃣ เลือกทีมที่ต้องการลง / ย้าย...", options=[discord.SelectOption(label=t) for t in parsed_teams], row=0)
        self.sel_role = Select(placeholder="2️⃣ เลือกตำแหน่งหลักของคุณ...", options=[
            discord.SelectOption(label="Tank", value="Tank", emoji="🛡️"),
            discord.SelectOption(label="Main DPS", value="DPS", emoji="⚔️"),
            discord.SelectOption(label="Healer", value="Heal", emoji="🌿"),
        ], row=1)
        
        status_opts = [discord.SelectOption(label="🔥 อยู่ยาว / Full Time", value="Full Time", emoji="🔥")]
        for i in range(1, 9): status_opts.append(discord.SelectOption(label=f"Round {i}", value=f"Round {i}", emoji="🔹"))
        status_opts.append(discord.SelectOption(label="🐢 ตามทีหลัง / Late Join", value="Late Join", emoji="🐢"))
        status_opts.append(discord.SelectOption(label="💤 สแตนด์บาย / Standby", value="Standby", emoji="💤"))
        self.sel_status = Select(placeholder="3️⃣ เลือกความพร้อม (กดเลือกได้หลายรอบ)...", min_values=1, max_values=len(status_opts), options=status_opts, row=2)
        
        weapon_opts = [
            discord.SelectOption(label="Nameless Sword", emoji="⚔️"), discord.SelectOption(label="Nameless Spear", emoji="🦯"),
            discord.SelectOption(label="Strategic Sword", emoji="🩸"), discord.SelectOption(label="Heavenquaker Spear", emoji="🩸"),
            discord.SelectOption(label="Thundercry Blade", emoji="⚡"), discord.SelectOption(label="Stormbreaker Spear", emoji="🛡️"),
            discord.SelectOption(label="Infernal Twinblades", emoji="⚔️"), discord.SelectOption(label="Mortal Rope Dart", emoji="🪢"),
            discord.SelectOption(label="Vernal Umbrella", emoji="☂️"), discord.SelectOption(label="Soulshade Umbrella", emoji="🌿"),
            discord.SelectOption(label="Inkwell Fan", emoji="🪭"), discord.SelectOption(label="Panacea Fan", emoji="🍃"),
            discord.SelectOption(label="Hengdao", emoji="🗡️"), discord.SelectOption(label="Gauntlets", emoji="🥊"),
            discord.SelectOption(label="Zui Meng You Chun", emoji="🌂"), discord.SelectOption(label="Su Zi Xing Yun", emoji="⛓️")
        ]
        self.sel_weapon = Select(placeholder="4️⃣ เลือกอาวุธคู่กาย (1 ถึง 2 ชิ้น)...", min_values=1, max_values=2, options=weapon_opts, row=3)
        
        self.sel_team.callback = self.dummy_callback
        self.sel_role.callback = self.dummy_callback
        self.sel_status.callback = self.dummy_callback
        self.sel_weapon.callback = self.dummy_callback
        
        self.add_item(self.sel_team)
        self.add_item(self.sel_role)
        self.add_item(self.sel_status)
        self.add_item(self.sel_weapon)
        
        btn_submit = Button(label="✅ บันทึกข้อมูลลงตาราง", style=discord.ButtonStyle.success, row=4)
        btn_submit.callback = self.submit
        self.add_item(btn_submit)

    async def dummy_callback(self, interaction: discord.Interaction):
        await interaction.response.defer()

    async def submit(self, interaction: discord.Interaction):
        if not self.sel_team.values or not self.sel_role.values or not self.sel_status.values or not self.sel_weapon.values:
            return await interaction.response.send_message("⚠️ **กรุณาเลือกข้อมูลให้ครบทั้ง 4 ช่องก่อนกดบันทึกครับ!**", ephemeral=True)
            
        team = self.sel_team.values[0]
        role = self.sel_role.values[0]
        status = ", ".join(self.sel_status.values)
        weapons = " + ".join(self.sel_weapon.values)
        
        ev = get_event(self.event_id)
        if not ev or ev[8] == 0: return await interaction.response.send_message("🔒 งานนี้ปิดลงชื่อแล้ว", ephemeral=True)
        
        limit = 0
        for t_str in ev[4].split(","):
            if "|" in t_str:
                n, l = t_str.split("|")
                if n == team: limit = int(l)
        
        final_status = status
        alert_msg = "✅ **บันทึกข้อมูลเรียบร้อยแล้ว! (ข้อมูลอัปเดตลงตารางแล้ว)**"
        
        if limit > 0 and "Late" not in final_status and "Standby" not in final_status:
            conn = sqlite3.connect(DB_NAME)
            c = conn.cursor()
            c.execute("SELECT user_id, time_text FROM registrations WHERE event_id=? AND team=?", (self.event_id, team))
            existing = c.fetchall()
            conn.close()
            main_count = sum(1 for uid, tt in existing if uid != interaction.user.id and "Late" not in tt and "Standby" not in tt)
            if main_count >= limit:
                final_status = "Standby"
                alert_msg = f"⚠️ **ทีม {team} โควต้าตัวจริงเต็มแล้ว ({limit} คน)!**\nระบบได้ย้ายคุณไปอยู่หมวด **สำรอง (Standby)** ให้อัตโนมัติ"

        reg_upsert(self.event_id, interaction.user.id, interaction.user.display_name, team, role, final_status, weapons)
        
        try: await self.dashboard_msg.edit(embed=create_dashboard_embed(self.event_id))
        except: pass
        
        await send_log(interaction.client, "Join/Edit", f"ลงชื่อ/อัปเดตทีม **{team}**\nตำแหน่ง: {role}\nสถานะ: {final_status}\nอาวุธ: {weapons}", interaction.user)
        await interaction.response.edit_message(content=alert_msg, view=None)

# ==========================================
# 🛑 CONFIRM LEAVE VIEW
# ==========================================
class ConfirmLeaveView(View):
    def __init__(self, event_id, dashboard_msg):
        super().__init__(timeout=60)
        self.event_id = event_id
        self.dashboard_msg = dashboard_msg

    @discord.ui.button(label="✅ ยืนยันลบชื่อ", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: Button):
        reg_remove(self.event_id, interaction.user.id)
        try: await self.dashboard_msg.edit(embed=create_dashboard_embed(self.event_id))
        except: pass
        await send_log(interaction.client, "Leave", f"ลบชื่อออกจาก Event #{self.event_id}", interaction.user)
        await interaction.response.edit_message(content="🗑️ **ลบชื่อของคุณออกจากตารางเรียบร้อยแล้ว!**", view=None)

    @discord.ui.button(label="❌ ยกเลิก", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: Button):
        await interaction.response.edit_message(content="❌ **ยกเลิกการลบชื่อ**", view=None)

# ==========================================
# 🎮 MAIN WAR VIEW
# ==========================================
class PersistentWarView(View):
    def __init__(self, event_id):
        super().__init__(timeout=None)
        self.event_id = event_id

        btn_reg = Button(label="📝 ลงชื่อ / แก้ไขข้อมูล", style=discord.ButtonStyle.success, row=0, custom_id=f"war_reg_{event_id}")
        btn_reg.callback = self.register
        self.add_item(btn_reg)

        btn_leave = Button(label="❌ ลบชื่อ", style=discord.ButtonStyle.danger, row=0, custom_id=f"war_leave_{event_id}")
        btn_leave.callback = self.leave
        self.add_item(btn_leave)

        btn_absence = Button(label="🏳️ แจ้งลา", style=discord.ButtonStyle.secondary, row=0, custom_id=f"war_abs_{event_id}")
        btn_absence.callback = self.absence
        self.add_item(btn_absence)

        btn_refresh = Button(label="🔄 รีเฟรช", style=discord.ButtonStyle.blurple, row=1, custom_id=f"war_ref_{event_id}")
        btn_refresh.callback = self.refresh
        self.add_item(btn_refresh)

        btn_weapons = Button(label="🔍 เช็คอาวุธ", style=discord.ButtonStyle.primary, row=1, custom_id=f"war_wp_{event_id}")
        btn_weapons.callback = self.check_weapons
        self.add_item(btn_weapons)

        btn_copy = Button(label="📋 Copy", style=discord.ButtonStyle.secondary, row=1, custom_id=f"war_copy_{event_id}")
        btn_copy.callback = self.copy
        self.add_item(btn_copy)

    async def register(self, interaction: discord.Interaction):
        ev = get_event(self.event_id)
        if not ev or ev[8] == 0: return await interaction.response.send_message("🔒 ปิดแล้ว", ephemeral=True)
        
        parsed_teams = [t_str.split("|")[0] if "|" in t_str else t_str for t_str in ev[4].split(",")]
        view = RegistrationView(self.event_id, interaction.message, parsed_teams)
        await interaction.response.send_message("👇 **กรุณาเลือกข้อมูลให้ครบทั้ง 4 ช่อง เพื่อลงชื่อหรือแก้ไข:**", view=view, ephemeral=True)

    async def leave(self, interaction: discord.Interaction):
        view = ConfirmLeaveView(self.event_id, interaction.message)
        await interaction.response.send_message("⚠️ **คุณแน่ใจหรือไม่ว่าต้องการลบชื่อออกจากการรบนี้?**", view=view, ephemeral=True)

    async def refresh(self, interaction: discord.Interaction):
        await interaction.response.edit_message(embed=create_dashboard_embed(self.event_id))

    async def check_weapons(self, interaction: discord.Interaction):
        data = get_roster(self.event_id)
        ev = get_event(self.event_id)
        if not ev: return
        parsed_teams = [t.split("|")[0] if "|" in t else t for t in ev[4].split(",")]
        
        embed = discord.Embed(title=f"🔍 ข้อมูลอาวุธ Event #{self.event_id}", color=0x2ecc71)
        found_any = False
        for t in parsed_teams:
            team_players = [p for p in data if p[2] == t]
            if not team_players: continue
            val = ""
            for p in team_players:
                username, _, role, _, weapons = p[1], p[2], p[3], p[4], p[5]
                if t == "Absence": continue
                emoji = "⚔️" if "DPS" in role else "🛡️" if "Tank" in role else "🌿"
                wp_text = weapons if weapons and weapons != "-" else "ยังไม่ระบุ"
                val += f"{emoji} **{username}** : `{wp_text}`\n"
            if val:
                found_any = True
                embed.add_field(name=f"━━━━━━ TEAM {t.upper()} ━━━━━━", value=val, inline=False)
        
        if not found_any: embed.description = "ยังไม่มีข้อมูลอาวุธ"
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def absence(self, interaction: discord.Interaction):
        await interaction.response.send_modal(AbsenceModal(self.event_id, interaction.message))

    async def copy(self, interaction: discord.Interaction):
        data = get_roster(self.event_id)
        ev = get_event(self.event_id)
        if not ev: return
        parsed_teams = [t.split("|")[0] if "|" in t else t for t in ev[4].split(",")]
        
        txt = f"```text\n📋 สรุปรายชื่อ Event #{self.event_id}\n=========================\n"
        for t in parsed_teams:
            team_players = [p for p in data if p[2] == t]
            if not team_players: continue
            txt += f"🛡️ {t.upper()}\n"
            main = [p for p in team_players if "Late" not in p[4] and "Standby" not in p[4]]
            late = [p for p in team_players if "Late" in p[4]]
            standby = [p for p in team_players if "Standby" in p[4]]
            for i, p in enumerate(main, 1): txt += f"{i}. {p[1]} ({p[3]}) - {p[4]} [{p[5]}]\n"
            if late:
                txt += "\n*🐢 สาย (Late):*\n"
                for p in late: txt += f"- {p[1]} ({p[3]}) [{p[5]}]\n"
            if standby:
                txt += "\n*💤 สำรอง (Standby):*\n"
                for p in standby: txt += f"- {p[1]} ({p[3]}) [{p[5]}]\n"
            txt += "-------------------------\n"
        txt += "```"
        await interaction.response.send_message(txt, ephemeral=True)

class AbsenceModal(Modal, title='แบบฟอร์มแจ้งลา (เฉพาะวอรอบนี้)'):
    def __init__(self, event_id, dashboard_msg):
        super().__init__()
        self.event_id = event_id
        self.dashboard_msg = dashboard_msg
    reason = TextInput(label='เหตุผล', required=True)
    async def on_submit(self, interaction: discord.Interaction):
        reg_upsert(self.event_id, interaction.user.id, interaction.user.display_name, "Absence", "-", self.reason.value, "-")
        try: await self.dashboard_msg.edit(embed=create_dashboard_embed(self.event_id))
        except: pass
        await send_log(interaction.client, "Absence", f"แจ้งลา Event #{self.event_id}\nเหตุผล: {self.reason.value}", interaction.user)
        await interaction.response.send_message("🏳️ บันทึกใบลาสำหรับวอรอบนี้เรียบร้อย", ephemeral=True)

# ==========================================
# 🛌 LEAVE BOARD SYSTEM
# ==========================================
class LeaveReasonModal(Modal, title='แบบฟอร์มแจ้งลา / แจ้งสาย'):
    def __init__(self, leave_type):
        super().__init__()
        self.leave_type = leave_type
        if leave_type == 'late':
            self.time_input = TextInput(label='คาดว่าจะมาถึงกี่โมง?', placeholder='เช่น 20.00 น.', required=True)
            self.reason = TextInput(label='เหตุผลที่มาสาย', placeholder='เช่น ขับรถอยู่, เลิกงานดึก...', required=True)
            self.add_item(self.time_input)
            self.add_item(self.reason)
        else:
            self.reason = TextInput(label='เหตุผลการลา', placeholder='เช่น ไปต่างจังหวัด, ติดสอบ...', required=True)
            self.add_item(self.reason)
            if leave_type == 'custom':
                self.date_input = TextInput(label='วันที่สิ้นสุดการลา (DD/MM)', placeholder='เช่น 15/04 (ถ้าไม่ระบุจะถือว่าพักยาว)', required=False)
                self.add_item(self.date_input)

    async def on_submit(self, interaction: discord.Interaction):
        now = bangkok_now()
        expiry_str = None
        date_text = "วันนี้"

        if self.leave_type == 'late':
            exp = now + timedelta(days=1)
            expiry_str = exp.strftime("%Y-%m-%d 23:59:59")
            date_text = f"มาถึงเวลา {self.time_input.value.strip()}"
        elif self.leave_type == '1_day':
            exp = now + timedelta(days=1)
            expiry_str = exp.strftime("%Y-%m-%d 23:59:59")
            date_text = "1 วัน"
        elif self.leave_type == '3_days':
            exp = now + timedelta(days=3)
            expiry_str = exp.strftime("%Y-%m-%d 23:59:59")
            date_text = "3 วัน"
        elif self.leave_type == '7_days':
            exp = now + timedelta(days=7)
            expiry_str = exp.strftime("%Y-%m-%d 23:59:59")
            date_text = "7 วัน"
        elif self.leave_type == 'custom':
            date_val = self.date_input.value.strip()
            if date_val:
                try:
                    dt_obj = datetime.strptime(date_val, "%d/%m")
                    target = dt_obj.replace(year=now.year)
                    if target.date() < now.date() and (now.month - target.month) > 6:
                        target = target.replace(year=now.year + 1)
                    exp = now.replace(year=target.year, month=target.month, day=target.day, hour=23, minute=59, second=59)
                    expiry_str = exp.strftime("%Y-%m-%d %H:%M:%S")
                    date_text = f"ถึง {date_val}"
                except:
                    self.leave_type = 'hiatus'
                    date_text = "พักยาว"
            else:
                self.leave_type = 'hiatus'
                date_text = "พักยาว"
        elif self.leave_type == 'hiatus':
            date_text = "พักยาวไม่มีกำหนด"

        leave_upsert(interaction.user.id, interaction.user.display_name, self.leave_type, date_text, expiry_str, self.reason.value)
        await refresh_leave_board(interaction.client)
        await refresh_all_active_wars(interaction.client) 
        await interaction.response.send_message(f"✅ **บันทึกข้อมูลลงบอร์ดถาวรสำเร็จ!** (สถานะ: {date_text})\n*(ระบบจะเชื่อมโยงชื่อไปยังตารางวอให้อัตโนมัติ)*", ephemeral=True)

class LeaveTypeSelect(Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="แจ้งมาสาย (Late)", value="late", emoji="🐢"),
            discord.SelectOption(label="ลาด่วน / 1 วัน", value="1_day", emoji="⏱️"),
            discord.SelectOption(label="ลา 3 วัน", value="3_days", emoji="🗓️"),
            discord.SelectOption(label="ลา 1 สัปดาห์", value="7_days", emoji="📅"),
            discord.SelectOption(label="ระบุวันกลับเอง...", value="custom", emoji="✏️"),
            discord.SelectOption(label="ลาพักยาว (ไม่มีกำหนดกลับ)", value="hiatus", emoji="🛌"),
        ]
        super().__init__(placeholder="เลือกประเภทการลา/แจ้งสายของคุณ...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(LeaveReasonModal(self.values[0]))

class LeaveBoardView(View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="📝 เขียนใบลา / แจ้งสาย", style=discord.ButtonStyle.primary, row=1, custom_id="lv_add")
    async def add_leave(self, interaction: discord.Interaction, button: Button):
        view = View(timeout=60).add_item(LeaveTypeSelect())
        await interaction.response.send_message("👇 **กรุณาเลือกประเภทการลา หรือแจ้งมาสาย:**", view=view, ephemeral=True)
    @discord.ui.button(label="❌ กลับมาแล้ว (ยกเลิกสถานะ)", style=discord.ButtonStyle.danger, row=1, custom_id="lv_rem")
    async def rem_leave(self, interaction: discord.Interaction, button: Button):
        leave_remove(interaction.user.id)
        await refresh_leave_board(interaction.client)
        await refresh_all_active_wars(interaction.client) 
        await interaction.response.send_message("🎉 **ยินดีต้อนรับกลับมา!** ลบชื่อออกจากบอร์ดแจ้งลาแล้ว", ephemeral=True)
    @discord.ui.button(label="🔄 รีเฟรชบอร์ด", style=discord.ButtonStyle.secondary, row=1, custom_id="lv_ref")
    async def ref_leave(self, interaction: discord.Interaction, button: Button):
        await interaction.response.edit_message(embed=create_leave_board_embed())

# ==========================================
# 🤖 BOT COMMANDS / MEMBER BOARD
# ==========================================
class MemberBoardView(View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="📝 ลงทะเบียน / แก้ไขตำแหน่ง", style=discord.ButtonStyle.success, row=1, custom_id="member_reg")
    async def register(self, interaction: discord.Interaction, button: Button):
        view = View(timeout=60).add_item(MemberRoleSelect(interaction.message))
        await interaction.response.send_message("👉 **กรุณาเลือกสายตำแหน่งหลักของคุณ:**", view=view, ephemeral=True)
    @discord.ui.button(label="🔄 รีเฟรช", style=discord.ButtonStyle.secondary, row=1, custom_id="member_ref")
    async def refresh(self, interaction: discord.Interaction, button: Button):
        await interaction.response.edit_message(embed=create_member_board_embed())
    @discord.ui.button(label="❌ ลบชื่อออก", style=discord.ButtonStyle.danger, row=1, custom_id="member_leave")
    async def leave(self, interaction: discord.Interaction, button: Button):
        member_remove(interaction.user.id)
        await interaction.response.edit_message(embed=create_member_board_embed())
        await interaction.followup.send("🗑️ ลบชื่อของคุณออกจากทำเนียบแล้ว", ephemeral=True)

# ==========================================
# 💻 BOT COMMANDS & EVENTS
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
    bot.add_view(MemberBoardView())
    bot.add_view(LeaveBoardView())
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

@bot.tree.command(name="setup_war", description="ตั้งค่าตารางวอ (แบบปุ่มกด)")
async def setup_war(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator: return
    get_session(interaction.user.id)
    await interaction.response.send_message(embed=create_setup_embed(interaction.user.id), view=SetupView(), ephemeral=True)

@bot.tree.command(name="setup_leave_board", description="สร้างบอร์ดแจ้งลาถาวร (Leave Board)")
async def setup_leave_board(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator: return
    embed = create_leave_board_embed()
    view = LeaveBoardView()
    await interaction.response.send_message("กำลังสร้างบอร์ดแจ้งลา...", ephemeral=True)
    msg = await interaction.channel.send(embed=embed, view=view)
    set_bot_config('leave_board', interaction.guild.id, msg.channel.id, msg.id)

@bot.tree.command(name="setup_member_board", description="สร้างตารางบอร์ดทำเนียบสมาชิกกิลด์")
async def setup_member_board(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator: return
    msg = await interaction.channel.send(embed=create_member_board_embed(), view=MemberBoardView())
    set_bot_config('member_board', interaction.guild.id, msg.channel.id, msg.id)
    await interaction.response.send_message("✅ สร้างตารางสำเร็จ", ephemeral=True)

@bot.tree.command(name="call_unregistered", description="ตามสมาชิกที่ยังไม่ได้ลงทะเบียนเข้าทำเนียบกิลด์")
async def call_unregistered(interaction: discord.Interaction, target_role: discord.Role = None):
    if not interaction.user.guild_permissions.administrator: return
    conn = sqlite3.connect(DB_NAME)
    reg_ids = {row[0] for row in conn.execute("SELECT user_id FROM guild_members")}
    conn.close()
    missing = []
    targets = target_role.members if target_role else interaction.guild.members
    for m in targets:
        if not m.bot and m.id not in reg_ids:
            missing.append(m.mention)
    if not missing:
        return await interaction.response.send_message("✅ ยอดเยี่ยม! สมาชิกทุกคนลงทะเบียนในทำเนียบครบแล้ว", ephemeral=True)
    header = f"📢 **กิล天狗 เปิดรับสมัคร จอมยุทธทั้งหลาย** 👺\n⚠️ พบสมาชิกที่ยังไม่ได้ลงทะเบียนเข้าทำเนียบกิลด์ **({len(missing)} คน)**:\n╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼\n"
    content = " ".join(missing)
    footer = f"\n╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼\n👇 **คลิกปุ่มด้านล่างเพื่อวาร์ปไปที่ตารางลงทะเบียนได้เลยครับ**"
    target_ch = interaction.channel
    link_data = get_bot_config('member_board')
    view = discord.ui.View()
    if link_data:
        url = f"https://discord.com/channels/{link_data[0]}/{link_data[1]}/{link_data[2]}"
        view.add_item(discord.ui.Button(label="📍 วาร์ปไปที่ตารางทำเนียบ", style=discord.ButtonStyle.link, url=url))
    try:
        if len(header + content + footer) > 2000:
            await target_ch.send(header + " (ส่วนที่ 1)", allowed_mentions=discord.AllowedMentions.none())
            await target_ch.send(content) 
            await target_ch.send(footer, view=view, allowed_mentions=discord.AllowedMentions.none())
        else:
            await target_ch.send(header + content + footer, view=view)
        await interaction.response.send_message("✅ ส่งประกาศตามคนลงทะเบียนทำเนียบกิลด์แล้ว", ephemeral=True)
    except Exception as e: pass

@bot.tree.command(name="reset_member_board", description="ล้างข้อมูลทำเนียบกิลด์ทั้งหมด (รีเซ็ตรายชื่อใหม่)")
async def reset_member_board(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator: return
    clear_all_members()
    await send_log(interaction.client, "Delete", "ล้างข้อมูลตารางทำเนียบสมาชิกกิลด์ทั้งหมด (Reset)", interaction.user)
    await interaction.response.send_message("🗑️ **ล้างรายชื่อในทำเนียบกิลด์ทั้งหมดเรียบร้อยแล้ว!**", ephemeral=True)

@bot.tree.command(name="check_missing", description="ตามคนขาด (ระบุ Event สำหรับตารางวอ)")
@app_commands.autocomplete(event_id=event_autocomplete)
async def check_missing(interaction: discord.Interaction, event_id: int, target_role: discord.Role = None):
    ev = get_event(event_id)
    if not ev: return await interaction.response.send_message("❌ ไม่พบ Event ID นี้", ephemeral=True)
    _, title, date_str, time_str, _, _, ch_id, msg_id, active = ev[:9]

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
        footer = f"\n╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼╼\n👇 **กดปุ่มด้านล่างเพื่อไปที่ห้องลงชื่อได้เลยครับ**"

        try:
            if len(header+content+footer) > 2000:
                await target_ch.send(header + " (ส่วนที่ 1)", allowed_mentions=discord.AllowedMentions.none())
                await target_ch.send(" ".join(missing), allowed_mentions=discord.AllowedMentions.none())
                await target_ch.send(footer, view=view, allowed_mentions=discord.AllowedMentions.none())
            else:
                await target_ch.send(header+content+footer, view=view, allowed_mentions=discord.AllowedMentions.none())
            await interaction.response.send_message(f"✅ ส่งประกาศตามคนขาด Event #{event_id} แล้ว", ephemeral=True)
        except Exception as e: pass

@bot.tree.command(name="close_war", description="จบงานและปิดตาราง (ระบุ Event)")
@app_commands.autocomplete(event_id=event_autocomplete)
async def close_war(interaction: discord.Interaction, event_id: int):
    if not interaction.user.guild_permissions.administrator: return
    ev = get_event(event_id)
    if not ev: return await interaction.response.send_message("❌ ไม่พบ Event ID นี้", ephemeral=True)

    close_event_db(event_id)
    
    detailed_history_embed = create_dashboard_embed(event_id)
    detailed_history_embed.title = f"📜 สรุปยอดวอ (Event #{event_id}) - จบงาน"
    detailed_history_embed.color = 0x2b2d31

    data = get_roster(event_id)
    total_players = len([p for p in data if p[2] != "Absence"])
    date_obj = parse_event_datetime(ev[2], ev[3])
    date_display = date_obj.strftime("%Y-%m-%d") if date_obj else ev[2]
    
    minimal_closed_embed = discord.Embed(color=0x2b2d31)
    minimal_closed_embed.description = (
        f"## 🔴 จบวอแล้ว: {ev[1]}\n\n"
        f"✅ **บันทึกข้อมูลเรียบร้อย**\n"
        f"📅 **วันที่:** {date_display}\n"
        f"👤 **จำนวนคน:** {total_players} คน\n\n"
        f"**System Closed.**"
    )

    try:
        ch = bot.get_channel(ev[6])
        if ch:
            msg = await ch.fetch_message(ev[7])
            await msg.edit(embed=minimal_closed_embed, view=None)
    except: pass
    
    if HISTORY_CHANNEL_ID:
        try:
            hist_ch = bot.get_channel(HISTORY_CHANNEL_ID)
            if hist_ch: await hist_ch.send(embed=detailed_history_embed)
        except: pass

    await send_log(interaction.client, "Close", f"ปิดงาน Event #{event_id} และส่งประวัติแล้ว", interaction.user)
    await interaction.response.send_message(f"🔴 ปิดงาน Event #{event_id} เรียบร้อย!", ephemeral=True)

@bot.tree.command(name="delete_event", description="ลบตารางและข้อมูลทั้งหมด (ระบุ Event)")
@app_commands.autocomplete(event_id=event_autocomplete)
async def delete_event(interaction: discord.Interaction, event_id: int):
    if not interaction.user.guild_permissions.administrator: return
    ev = get_event(event_id)
    if not ev: return
    delete_event_db(event_id)
    try:
        ch = bot.get_channel(ev[6])
        if ch:
            msg = await ch.fetch_message(ev[7])
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
    for ev in events:
        try:
            event_dt = parse_event_datetime(ev[2], ev[3])
            if not event_dt: continue
            diff = (event_dt - now).total_seconds()
            if 1740 < diff <= 1800:
                ch = bot.get_channel(ALERT_CHANNEL_ID_FIXED)
                if ch: await ch.send(f"📢 **แจ้งเตือน Event #{ev[0]}:** อีก 30 นาทีจะเริ่ม **{ev[1]}**! @everyone")
            elif 0 <= diff < 60:
                ch = bot.get_channel(ALERT_CHANNEL_ID_FIXED)
                if ch: await ch.send(f"⚔️ **ถึงเวลากิจกรรมแล้ว!** Event #{ev[0]}: **{ev[1]}** เริ่มแล้ว ลุยเลย! @everyone")
        except: pass

    c = conn.cursor()
    c.execute("SELECT user_id, expiry_date FROM leave_records WHERE expiry_date IS NOT NULL")
    leave_rows = c.fetchall()
    cleared = False
    for uid, exp_str in leave_rows:
        try:
            exp_dt = datetime.strptime(exp_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=pytz.timezone('Asia/Bangkok'))
            if now > exp_dt:
                c.execute("DELETE FROM leave_records WHERE user_id=?", (uid,))
                cleared = True
        except: pass
    if cleared:
        conn.commit()
        asyncio.create_task(refresh_leave_board(bot))
        asyncio.create_task(refresh_all_active_wars(bot))
    conn.close()

bot.run('Y')