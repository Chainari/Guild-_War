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
DB_NAME = "guildwar_ultimate.db"

# 👇👇👇 เลขห้องที่คุณตั้งค่าไว้ (ตรวจสอบอีกครั้งว่าถูกต้อง) 👇👇👇
LOG_CHANNEL_ID = 1472149965299253457         # ห้อง Log
HISTORY_CHANNEL_ID = 1472149894096621639    # ห้อง History
ALERT_CHANNEL_ID_FIXED = 1444345312188698738 # ห้องแจ้งเตือน/ตามคน
# 👆👆👆 ----------------------- 👆👆👆

war_config = {
    "title": "Guild War Roster",
    "date": "Today",
    "time": "19:30",
    "teams": ["Team ATK", "Team Flex"],
    "ALERT_CHANNEL_ID": ALERT_CHANNEL_ID_FIXED,
    "DASHBOARD_CHANNEL_ID": None,
    "DASHBOARD_MSG_ID": None,
    "reminded": False
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

def db_get_leaderboard():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''SELECT username, COUNT(*) as count
                FROM history
                WHERE status = 'Joined'
                GROUP BY user_id
                ORDER BY count DESC
                LIMIT 10''')
    data = c.fetchall()
    conn.close()
    return data

# ==========================================
# 📝 AUDIT LOGS
# ==========================================
async def send_log(interaction: discord.Interaction, action_name: str, details: str, color: discord.Color):
    if LOG_CHANNEL_ID == 0: return
    try:
        channel = await interaction.client.fetch_channel(LOG_CHANNEL_ID)
        if channel:
            embed = discord.Embed(title=f"📝 บันทึกกิจกรรม: {action_name}", color=color, timestamp=bangkok_now())
            embed.add_field(name="User", value=f"{interaction.user.display_name} ({interaction.user.name})", inline=True)
            embed.add_field(name="Details", value=details, inline=False)
            if interaction.user.avatar:
                embed.set_thumbnail(url=interaction.user.avatar.url)
            await channel.send(embed=embed)
    except: pass

# ==========================================
# 🗓️ SETUP & CONFIG UI
# ==========================================
class ConfigModal(Modal, title='ตั้งค่า War'):
    def __init__(self, selected_date, needs_date_input=False):
        super().__init__()
        self.selected_date = selected_date
        
        self.title_input = TextInput(label='หัวข้อ (Title)', default=war_config["title"], required=True)
        self.add_item(self.title_input)
        
        if needs_date_input:
            self.date_input = TextInput(label='วันที่ (DD/MM)', placeholder="เช่น 25/12", required=True)
            self.add_item(self.date_input)
        else:
            self.date_input = None

        self.time_input = TextInput(label='เวลาเริ่ม (HH:MM)', default=war_config["time"], placeholder="Ex. 19:30", required=True, max_length=5)
        self.add_item(self.time_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            datetime.strptime(self.time_input.value, "%H:%M")
            war_config["title"] = self.title_input.value
            war_config["time"] = self.time_input.value
            if self.date_input:
                war_config["date"] = self.date_input.value.strip()
            else:
                war_config["date"] = self.selected_date
            
            war_config["reminded"] = False
            await send_log(interaction, "⚙️ แก้ไข Config", f"Title: {war_config['title']}\nTime: {war_config['time']}", discord.Color.blue())
            await interaction.response.edit_message(content=None, embed=create_setup_embed(), view=SetupView())
        except ValueError:
            await interaction.response.send_message("❌ รูปแบบเวลาผิด (ใช้ HH:MM)", ephemeral=True, delete_after=5.0)

class DateSelect(Select):
    def __init__(self):
        options = []
        now = bangkok_now()
        options.append(discord.SelectOption(label="✏️ กรอกวันที่เอง...", value="manual", emoji="📝", description="พิมพ์วันที่เอง เช่น 25/12"))
        options.append(discord.SelectOption(label=f"วันนี้ ({now.strftime('%d/%m')})", value="Today", emoji="🟢"))
        tmr = now + timedelta(days=1)
        options.append(discord.SelectOption(label=f"พรุ่งนี้ ({tmr.strftime('%d/%m')})", value="Tomorrow", emoji="🟡"))
        for i in range(2, 14):
            d = now + timedelta(days=i)
            day_name = d.strftime("%A")
            date_str = d.strftime("%d/%m")
            options.append(discord.SelectOption(label=f"{day_name} ที่ {date_str}", value=date_str, emoji="🗓️"))
        super().__init__(placeholder="📅 เลือกวันที่จัด War...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        selected = self.values[0]
        if selected == "manual":
            await interaction.response.send_modal(ConfigModal(selected, needs_date_input=True))
        else:
            await interaction.response.send_modal(ConfigModal(selected, needs_date_input=False))

class DatePickerView(View):
    def __init__(self):
        super().__init__(timeout=60)
        self.add_item(DateSelect())

class AddTeamModal(Modal, title='เพิ่มทีมใหม่'):
    team_name = TextInput(label='ชื่อทีมใหม่', placeholder='เช่น Team Roaming', required=True)
    async def on_submit(self, interaction: discord.Interaction):
        new_team = self.team_name.value
        if new_team not in war_config["teams"]:
            war_config["teams"].append(new_team)
            await interaction.response.edit_message(embed=create_setup_embed(), view=SetupView())
        else:
            await interaction.response.send_message("❌ ชื่อทีมซ้ำ", ephemeral=True, delete_after=3.0)

class RemoveTeamModal(Modal, title='ลบทีมล่าสุด'):
    confirm = TextInput(label='พิมพ์ CONFIRM', placeholder='CONFIRM', required=True)
    async def on_submit(self, interaction: discord.Interaction):
        if self.confirm.value == "CONFIRM":
            if len(war_config["teams"]) > 1:
                war_config["teams"].pop()
                await interaction.response.edit_message(embed=create_setup_embed(), view=SetupView())
            else: await interaction.response.send_message("❌ ต้องเหลืออย่างน้อย 1 ทีม", ephemeral=True, delete_after=3.0)
        else: await interaction.response.send_message("❌ ยืนยันไม่ถูกต้อง", ephemeral=True, delete_after=3.0)

class SetupView(View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(label="📅 เลือกวัน/เวลา", style=discord.ButtonStyle.primary, row=1)
    async def edit_config(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message("👇 **เลือกวันที่:**", view=DatePickerView(), ephemeral=True)

    @discord.ui.button(label="➕ เพิ่มทีม", style=discord.ButtonStyle.secondary, row=2)
    async def add_team(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(AddTeamModal())

    @discord.ui.button(label="➖ ลบทีม", style=discord.ButtonStyle.secondary, row=2)
    async def remove_team(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(RemoveTeamModal())

    @discord.ui.button(label="🗑️ Reset รายชื่อ", style=discord.ButtonStyle.danger, row=3)
    async def clear_roster(self, interaction: discord.Interaction, button: Button):
        db_clear()
        await interaction.response.send_message("✅ **ล้างรายชื่อเรียบร้อย!**", ephemeral=True)

    @discord.ui.button(label="✅ ยืนยันและประกาศ", style=discord.ButtonStyle.green, row=3)
    async def confirm(self, interaction: discord.Interaction, button: Button):
        war_config["ALERT_CHANNEL_ID"] = ALERT_CHANNEL_ID_FIXED
        war_config["reminded"] = False
        
        embed = create_dashboard_embed()
        view = MainWarView()
        await send_log(interaction, "📢 ประกาศ War", f"Teams: {len(war_config['teams'])}", discord.Color.gold())
        msg = await interaction.channel.send(embed=embed, view=view)
        
        war_config["DASHBOARD_CHANNEL_ID"] = msg.channel.id
        war_config["DASHBOARD_MSG_ID"] = msg.id

        try: await msg.create_thread(name=f"💬 ห้องคุยงาน - {war_config['title']}", auto_archive_duration=1440)
        except: pass
        
        alert_room_text = f"<#{war_config['ALERT_CHANNEL_ID']}>" if war_config['ALERT_CHANNEL_ID'] else "ห้องนี้"
        await interaction.response.edit_message(content=f"✅ **ประกาศแล้ว!** (แจ้งเตือนจะส่งไปที่ {alert_room_text})", embed=None, view=None, delete_after=10.0)

def create_setup_embed():
    embed = discord.Embed(title="🛠️ ตั้งค่าระบบ (Setup)", description="ปรับแต่งข้อมูลก่อนประกาศ", color=0x3498db)
    embed.add_field(name="📅 หัวข้อ", value=war_config["title"], inline=False)
    embed.add_field(name="⏰ เวลา", value=f"{war_config['date']} @ {war_config['time']} น.", inline=True)
    
    alert_text = f"<#{ALERT_CHANNEL_ID_FIXED}>" if ALERT_CHANNEL_ID_FIXED else "⚠️ ยังไม่ใส่ ID ห้องในโค้ด"
    embed.add_field(name="📢 ห้องแจ้งเตือน (Fixed)", value=alert_text, inline=True)
    
    team_list = "\n".join([f"- {t}" for t in war_config["teams"]])
    embed.add_field(name=f"🛡️ ทีม ({len(war_config['teams'])})", value=f"```\n{team_list}\n```", inline=False)
    return embed

# ==========================================
# 📝 REGISTRATION UI
# ==========================================
class AbsenceModal(Modal, title='แบบฟอร์มแจ้งลา'):
    def __init__(self, dashboard_msg):
        super().__init__()
        self.dashboard_msg = dashboard_msg 
    reason = TextInput(label='เหตุผลที่ลา', placeholder='เช่น ติดงาน, ป่วย', required=True)
    async def on_submit(self, interaction: discord.Interaction):
        if is_roster_locked:
            await interaction.response.send_message("⛔ **ระบบปิดรับรายชื่อแล้ว**", ephemeral=True, delete_after=5.0)
            return
        db_upsert(interaction.user.id, interaction.user.display_name, "Absence", self.reason.value, "-")
        await send_log(interaction, "🏳️ แจ้งลา", f"Reason: {self.reason.value}", discord.Color.orange())
        if self.dashboard_msg:
            try: await self.dashboard_msg.edit(embed=create_dashboard_embed())
            except: pass
        await interaction.response.send_message(f"🏳️ บันทึกการลาเรียบร้อย", ephemeral=True, delete_after=5.0)

class CustomStatusModal(Modal, title='ระบุสถานะของคุณ'):
    def __init__(self, team, role, dashboard_msg):
        super().__init__()
        self.team = team
        self.role = role
        self.dashboard_msg = dashboard_msg
        
    status_input = TextInput(label='สถานะ / ช่วงเวลา', placeholder='เช่น เข้าหลัง 20.00 น.', required=True, max_length=20)

    async def on_submit(self, interaction: discord.Interaction):
        status = self.status_input.value
        db_upsert(interaction.user.id, interaction.user.display_name, self.team, self.role, status)
        await send_log(interaction, "✅ ลงชื่อ (Custom)", f"Team: {self.team}\nRole: {self.role}\nStatus: {status}", discord.Color.green())
        
        if self.dashboard_msg:
            try: await self.dashboard_msg.edit(embed=create_dashboard_embed())
            except: pass
        await interaction.response.send_message(f"✅ ลงทะเบียนสำเร็จ!", ephemeral=True, delete_after=5.0)

class StatusSelect(Select):
    def __init__(self, team, role, dashboard_msg):
        self.team = team
        self.role = role
        self.dashboard_msg = dashboard_msg
        
        options = [discord.SelectOption(label="🔥 อยู่ยาว / Full Time", description="จัดเต็มทุกรอบ", value="Full Time", emoji="🔥")]
        emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣"]
        for i in range(8):
            round_num = i + 1
            options.append(discord.SelectOption(label=f"Round {round_num}", description=f"ลงเล่นรอบที่ {round_num}", value=f"Round {round_num}", emoji=emojis[i]))
        options.extend([
            discord.SelectOption(label="🐢 ตามไปทีหลัง / Late Join", description="มาไม่ทันเวลาเริ่ม แต่จะตามไป", value="Late Join", emoji="🐢"),
            discord.SelectOption(label="💤 สแตนด์บาย / Standby", description="ตัวสำรอง", value="Standby", emoji="💤"),
            discord.SelectOption(label="✏️ อื่นๆ (Other)", description="พิมพ์บอกช่วงเวลาเอง...", value="Other", emoji="✏️")
        ])
        super().__init__(placeholder="เลือกสถานะ (เลือกได้หลายข้อ)...", min_values=1, max_values=len(options), options=options)

    async def callback(self, interaction: discord.Interaction):
        if is_roster_locked:
            await interaction.response.send_message("⛔ **ระบบปิดรับรายชื่อแล้ว**", ephemeral=True, delete_after=5.0)
            return
        if "Other" in self.values:
            await interaction.response.send_modal(CustomStatusModal(self.team, self.role, self.dashboard_msg))
            return
        selected_text = ", ".join(self.values)
        db_upsert(interaction.user.id, interaction.user.display_name, self.team, self.role, selected_text)
        await send_log(interaction, "✅ ลงชื่อ", f"Team: {self.team}\nRole: {self.role}\nStatus: {selected_text}", discord.Color.green())
        if self.dashboard_msg:
            try: await self.dashboard_msg.edit(embed=create_dashboard_embed())
            except: pass
        await interaction.response.send_message(f"✅ ลงทะเบียนสำเร็จ!", ephemeral=True, delete_after=5.0)

class StatusSelectView(View):
    def __init__(self, team, role, dashboard_msg):
        super().__init__()
        self.add_item(StatusSelect(team, role, dashboard_msg))

class TeamSelect(Select):
    def __init__(self, role, dashboard_msg):
        self.role_value = role
        self.dashboard_msg = dashboard_msg
        options = []
        for team_name in war_config["teams"]:
            options.append(discord.SelectOption(label=team_name, value=team_name, emoji="🛡️"))
        super().__init__(placeholder="เลือกทีมที่จะลง...", min_values=1, max_values=1, options=options)
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_message(f"⏳ ระบุความพร้อม **{self.values[0]}**:", view=StatusSelectView(self.values[0], self.role_value, self.dashboard_msg), ephemeral=True)

class TeamSelectView(View):
    def __init__(self, role, dashboard_msg):
        super().__init__()
        self.add_item(TeamSelect(role, dashboard_msg))

class RoleSelect(Select):
    def __init__(self):
        super().__init__(placeholder="เลือกตำแหน่งของคุณ...", min_values=1, max_values=1, options=[
            discord.SelectOption(label="Main DPS", value="DPS", emoji="⚔️"),
            discord.SelectOption(label="Tank", value="Tank", emoji="🛡️"),
            discord.SelectOption(label="Healer", value="Heal", emoji="🌿"),
        ])
    async def callback(self, interaction: discord.Interaction):
        if is_roster_locked:
            await interaction.response.send_message("⛔ **ระบบปิดรับรายชื่อแล้ว**", ephemeral=True, delete_after=5.0)
            return
        await interaction.response.send_message("👉 กรุณาเลือกทีม:", view=TeamSelectView(self.values[0], interaction.message), ephemeral=True)

class MainWarView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(RoleSelect())

    @discord.ui.button(label="🔄 รีเฟรช", style=discord.ButtonStyle.blurple, row=2)
    async def refresh(self, interaction: discord.Interaction, button: Button):
        await interaction.response.edit_message(embed=create_dashboard_embed(), view=self)

    @discord.ui.button(label="🏳️ แจ้งลา", style=discord.ButtonStyle.gray, row=2)
    async def absence(self, interaction: discord.Interaction, button: Button):
        if is_roster_locked:
            await interaction.response.send_message("⛔ **ระบบปิด**", ephemeral=True, delete_after=5.0)
            return
        await interaction.response.send_modal(AbsenceModal(interaction.message))

    @discord.ui.button(label="❌ ลบชื่อ", style=discord.ButtonStyle.red, row=2)
    async def leave(self, interaction: discord.Interaction, button: Button):
        db_remove(interaction.user.id)
        await send_log(interaction, "🗑️ ลบชื่อ", "User removed themselves.", discord.Color.red())
        await interaction.message.edit(embed=create_dashboard_embed())
        await interaction.response.send_message("🗑️ ลบรายชื่อเรียบร้อย", ephemeral=True, delete_after=5.0)

    @discord.ui.button(label="📋 Copy", style=discord.ButtonStyle.secondary, row=2)
    async def copy_text(self, interaction: discord.Interaction, button: Button):
        data = db_get_all()
        role_priority = {"Tank": 1, "DPS": 2, "Heal": 3}
        data.sort(key=lambda x: (role_priority.get(x[2], 99), x[0])) 
        text = f"⚔️ **{war_config['title']}**\n📅 {war_config['date']} ⏰ {war_config['time']}\n\n"
        team_map = {name: [] for name in war_config["teams"]}
        absence_list = []
        for username, team, role, time in data:
            if team == "Absence": absence_list.append(f"- {username} ({role})")
            elif team in team_map: team_map[team].append(f"- {username} ({role}) [{time}]")
        for team_name in war_config["teams"]:
            text += f"🛡️ **{team_name}**\n" + ("\n".join(team_map[team_name]) if team_map[team_name] else "- ว่าง -") + "\n\n"
        text += "🏳️ **แจ้งลา**\n" + ("\n".join(absence_list) if absence_list else "- ไม่มี -")
        await interaction.response.send_message(f"```{text}```", ephemeral=True)

# ==========================================
# 📊 DASHBOARD GENERATOR
# ==========================================
def create_dashboard_embed():
    data = db_get_all()
    role_priority = {"Tank": 1, "DPS": 2, "Heal": 3}
    data.sort(key=lambda x: (role_priority.get(x[2], 99), x[0]))

    stats = {name: {"DPS":0, "Tank":0, "Heal":0, "Total":0} for name in war_config["teams"]}
    stats["Absence"] = 0
    roster = {name: {"Main": [], "Standby": []} for name in war_config["teams"]}
    roster["Absence"] = []
    
    for username, team, role, time_text in data:
        if team == "Absence":
            stats["Absence"] += 1
            roster["Absence"].append(f"❌ `{username}` : {role}")
        elif team in stats:
            stats[team]["Total"] += 1
            if role in stats[team]: stats[team][role] += 1
            role_emoji = "⚔️" if "DPS" in role else "🛡️" if "Tank" in role else "🌿"
            
            on_icon = "🟢"
            off_icon = "⚫"
            if "Full Time" in time_text: status_display = f"{on_icon*4} {on_icon*4}" 
            elif "Round" in time_text:
                bar = [on_icon if f"Round {i}" in time_text else off_icon for i in range(1, 9)]
                status_display = "".join(bar[:4]) + " " + "".join(bar[4:])
            else: status_display = f"[{time_text}]" 

            if "Late Join" in time_text and "Round" in time_text: status_display += " 🐢"
            display_str = f"> `{status_display}` | {role_emoji} **{username}**"
            
            if "Standby" in time_text: roster[team]["Standby"].append(f"💤 {username} [Standby]")
            else: roster[team]["Main"].append(display_str)

    try:
        tz = pytz.timezone('Asia/Bangkok')
        now_th = datetime.now(tz)
        war_time_obj = datetime.strptime(war_config['time'], "%H:%M")
        date_input = war_config.get('date', 'Today').lower().strip()
        target_date = now_th.date()
        if date_input in ['tomorrow', 'พรุ่งนี้']: target_date = now_th.date() + timedelta(days=1)
        elif date_input not in ['today', 'วันนี้']:
            try:
                parsed_date = datetime.strptime(date_input.replace('-', '/'), "%d/%m")
                target_date = parsed_date.replace(year=now_th.year).date()
                if target_date < now_th.date() and (now_th.month == 12 and target_date.month == 1):
                    target_date = target_date.replace(year=now_th.year + 1)
            except: pass
        target_dt = tz.localize(datetime.combine(target_date, war_time_obj.time()))
        ts = int(target_dt.timestamp())
        time_display = f"📅 **{target_dt.strftime('%A, %d/%m')}**\n<t:{ts}:F> • <t:{ts}:R>"
    except: time_display = f"{war_config['date']} - {war_config['time']}"

    lock_text = "🔒 SYSTEM LOCKED" if is_roster_locked else "🟢 OPEN REGISTRATION"
    color = 0xff2e4c if is_roster_locked else 0x00f7ff
    embed = discord.Embed(title=f"{war_config['title']}", description=f"```ansi\n\u001b[0;33m⏰ START: {war_config['time']} น.\u001b[0m```\n{time_display}", color=color)

    def make_visual_bar(stat_dict):
        dps, tank, heal = stat_dict['DPS'], stat_dict['Tank'], stat_dict['Heal']
        total = dps + tank + heal
        header = f"🔥 **Total: {total}** (⚔️ `{dps}` 🛡️ `{tank}` 🌿 `{heal}`)"
        if total == 0: bar = "⚫" * 10
        else:
            limit = 10
            c_dps = int((dps / total) * limit) if total > 0 else 0
            c_tank = int((tank / total) * limit) if total > 0 else 0
            c_heal = limit - (c_dps + c_tank)
            bar = ("🔴" * c_dps) + ("🔵" * c_tank) + ("🟢" * c_heal)
            if len(bar) < limit: bar += "⚫" * (limit - len(bar))
        return f"{header}\n`{bar}`"

    for team_name in war_config["teams"]:
        field_value = make_visual_bar(stats[team_name]) + "\n"
        if roster[team_name]["Main"]: field_value += "\n" + "\n".join(roster[team_name]["Main"])
        else: field_value += "\n*... ว่าง ...*"
        if roster[team_name]["Standby"]: field_value += "\n\n**— 💤 สำรอง / Standby —**\n" + "\n".join(roster[team_name]["Standby"])
        embed.add_field(name=f"▬▬▬▬ {team_name.upper()} ▬▬▬▬", value=field_value, inline=False)

    if stats['Absence'] > 0:
        embed.add_field(name="▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬", value=f"🏳️ **Absence List ({stats['Absence']})**", inline=False)
        embed.add_field(name="\u200b", value="\n".join(roster["Absence"]), inline=False)
        
    embed.set_footer(text=f"STATUS: {lock_text} | Last Updated: {bangkok_now().strftime('%H:%M:%S')}")
    return embed

# ==========================================
# 🤖 BOT COMMANDS & SYSTEM
# ==========================================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True # 🔥🔥 สำคัญมาก! เปิดตาบอทให้มองเห็นสมาชิก 🔥🔥
bot = commands.Bot(command_prefix="!", intents=intents)

async def update_dashboard():
    if war_config["DASHBOARD_CHANNEL_ID"] and war_config["DASHBOARD_MSG_ID"]:
        try:
            channel = bot.get_channel(war_config["DASHBOARD_CHANNEL_ID"]) or await bot.fetch_channel(war_config["DASHBOARD_CHANNEL_ID"])
            msg = await channel.fetch_message(war_config["DASHBOARD_MSG_ID"])
            await msg.edit(embed=create_dashboard_embed())
        except: pass

@tasks.loop(minutes=1)
async def auto_lock_task():
    global is_roster_locked
    now = bangkok_now()
    current_time_str = now.strftime("%H:%M")
    
    if not is_roster_locked and current_time_str == war_config["time"]:
        is_roster_locked = True
        await update_dashboard()
        print(f"⏰ Auto-locked roster at {current_time_str}")

    try:
        if war_config["ALERT_CHANNEL_ID"] and not war_config.get("reminded", False):
            target_time = datetime.strptime(war_config["time"], "%H:%M")
            target_dt = now.replace(hour=target_time.hour, minute=target_time.minute, second=0, microsecond=0)
            if target_dt < now and (now.hour > 20 and target_dt.hour < 5): target_dt += timedelta(days=1)
            
            diff = (target_dt - now).total_seconds()
            if 0 < diff <= 900: # 15 นาที
                channel = bot.get_channel(war_config["ALERT_CHANNEL_ID"]) or await bot.fetch_channel(war_config["ALERT_CHANNEL_ID"])
                if channel:
                    await channel.send(f"📢 **แจ้งเตือน:** อีก 15 นาทีจะเริ่มวอแล้ว! @everyone เตรียมตัวเข้าดิสได้เลย!")
                    war_config["reminded"] = True
    except Exception as e: print(f"Reminder Error: {e}")

@bot.event
async def on_ready():
    init_db()
    print(f'✅ Bot Online: {bot.user}')
    await bot.tree.sync()
    if not auto_lock_task.is_running():
        auto_lock_task.start()

# --- COMMANDS SECTION ---

@bot.tree.command(name="setup_war", description="[Admin] ตั้งค่าและเริ่มประกาศ")
async def setup_war(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("⛔ เฉพาะ Admin", ephemeral=True)
    await interaction.response.send_message(embed=create_setup_embed(), view=SetupView(), ephemeral=True)

@bot.tree.command(name="lock", description="[Admin] ล็อค/ปลดล็อค ตาราง")
async def lock_war(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("⛔ เฉพาะ Admin", ephemeral=True)
    global is_roster_locked
    is_roster_locked = not is_roster_locked
    await update_dashboard()
    status = "🔒 ล็อคแล้ว" if is_roster_locked else "🟢 ปลดล็อคแล้ว"
    await interaction.response.send_message(f"✅ {status}", ephemeral=True)

@bot.tree.command(name="close_war", description="[Admin] จบวอ บันทึก และปิดตาราง")
async def close_war(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("⛔ เฉพาะ Admin", ephemeral=True)
    
    await interaction.response.defer(ephemeral=True)
    today = bangkok_now().strftime('%Y-%m-%d')
    count = db_save_history(today)
    
    if HISTORY_CHANNEL_ID:
        try:
            h_channel = await interaction.client.fetch_channel(HISTORY_CHANNEL_ID)
            embed = create_dashboard_embed()
            embed.title = f"📜 สรุปยอดวอ วันที่ {today}"
            embed.color = discord.Color.greyple()
            embed.description = f"จบวอเรียบร้อย สมาชิกเข้าร่วม: {count} คน"
            await h_channel.send(embed=embed)
        except Exception as e: await interaction.followup.send(f"⚠️ ส่ง History ไม่ได้: {e}", ephemeral=True)

    if war_config["DASHBOARD_CHANNEL_ID"] and war_config["DASHBOARD_MSG_ID"]:
        try:
            channel = bot.get_channel(war_config["DASHBOARD_CHANNEL_ID"]) or await bot.fetch_channel(war_config["DASHBOARD_CHANNEL_ID"])
            msg = await channel.fetch_message(war_config["DASHBOARD_MSG_ID"])
            embed = msg.embeds[0]
            embed.title = f"🔴 จบวอแล้ว: {war_config['title']}"
            embed.color = 0x2f3136
            embed.clear_fields()
            embed.description = f"✅ **บันทึกข้อมูลเรียบร้อย**\n📅 วันที่: {today}\n👥 จำนวนคน: {count} คน"
            embed.set_footer(text="System Closed.")
            await msg.edit(embed=embed, view=None)
        except: pass

    db_clear()
    await send_log(interaction, "💾 จบวอ", f"บันทึก {count} คน และปิดงาน", discord.Color.green())
    await interaction.followup.send(f"✅ **ปิดจบคอร์สเรียบร้อย!**", ephemeral=True)

@bot.tree.command(name="check_missing", description="[Admin] เช็คคนขาด (เลือกยศ หรือ ไม่เลือกเพื่อเช็คทั้งเซิร์ฟ)")
async def check_missing(interaction: discord.Interaction, target_role: discord.Role = None):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT user_id FROM registrations")
    registered_ids = {row[0] for row in c.fetchall()}
    conn.close()
    
    missing = []
    check_scope = ""

    if target_role:
        check_scope = f"ยศ {target_role.mention}"
        for member in target_role.members:
            if not member.bot and member.id not in registered_ids:
                missing.append(member.mention)
    else:
        check_scope = "ทุกคนในเซิร์ฟเวอร์"
        for member in interaction.guild.members:
            if not member.bot and member.id not in registered_ids:
                missing.append(member.mention)
    
    target_channel = interaction.channel
    if war_config["ALERT_CHANNEL_ID"]:
        try: target_channel = bot.get_channel(war_config["ALERT_CHANNEL_ID"]) or await bot.fetch_channel(war_config["ALERT_CHANNEL_ID"])
        except: pass
    
    if not missing:
        await interaction.response.send_message(f"✅ {check_scope} ลงชื่อครบทุกคนแล้ว!", ephemeral=True)
    else:
        if len(missing) > 50:
            await interaction.response.send_message(f"⚠️ คนขาดเยอะมาก ({len(missing)} คน) เดี๋ยวส่งรายชื่อเข้าห้องแจ้งเตือน...", ephemeral=True)
            text_list = "\n".join([m.replace("<@", "").replace(">", "") for m in missing]) 
            await target_channel.send(f"📢 **รายชื่อคนขาด ({check_scope}):**\n(จำนวน {len(missing)} คน)\n```\n{text_list}\n```")
        else:
            msg_text = f"📢 **ตามคน ({check_scope}):** ยังไม่ลงชื่อ ({len(missing)} คน)\n{', '.join(missing)}"
            await target_channel.send(msg_text)
            await interaction.response.send_message(f"✅ ส่งรายชื่อคนขาดไปที่ {target_channel.mention} แล้ว", ephemeral=True)

@bot.tree.command(name="leaderboard", description="ดูอันดับการเข้าวอ")
async def leaderboard(interaction: discord.Interaction):
    data = db_get_leaderboard()
    if not data:
        await interaction.response.send_message("❌ ยังไม่มีประวัติการบันทึก", ephemeral=True)
        return
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

bot.run('T')