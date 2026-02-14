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

# 👇👇👇 ใส่เลขห้องตรงนี้ครับ 👇👇👇
LOG_CHANNEL_ID = 1472149965299253457    # ห้อง Log (แอดมินดู)
HISTORY_CHANNEL_ID = 1472149894096621639 # ห้อง History (เก็บประวัติย้อนหลัง)
# 👆👆👆 ------------------- 👆👆👆

war_config = {
    "title": "Guild War Roster",
    "date": "Today",
    "time": "19:30",
    "teams": ["Team ATK", "Team Flex"],
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
# 🗓️ DATE PICKER SYSTEM
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

            await send_log(interaction, "⚙️ แก้ไข Config", f"Title: {war_config['title']}\nDate: {war_config['date']}\nTime: {war_config['time']}", discord.Color.blue())
            await interaction.response.edit_message(content=None, embed=create_setup_embed(), view=SetupView())
        except ValueError:
            await interaction.response.send_message("❌ รูปแบบเวลาผิด (ใช้ HH:MM)", ephemeral=True, delete_after=5.0)

class DateSelect(Select):
    def __init__(self):
        options = []
        now = bangkok_now()
        options.append(discord.SelectOption(label="✏️ กรอกวันที่เอง...", value="manual", emoji="📝", description="พิมพ์วันที่เอง เช่น 25/12"))
        options.append(discord.SelectOption(label=f"วันนี้ ({now.strftime('%d/%m')})", value="Today", emoji="🟢", description="เซ็ตเป็นวันปัจจุบัน"))
        tmr = now + timedelta(days=1)
        options.append(discord.SelectOption(label=f"พรุ่งนี้ ({tmr.strftime('%d/%m')})", value="Tomorrow", emoji="🟡", description="เซ็ตเป็นวันพรุ่งนี้"))
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

# ==========================================
# 🛠️ SETUP MENUS
# ==========================================
class AddTeamModal(Modal, title='เพิ่มทีมใหม่'):
    team_name = TextInput(label='ชื่อทีมใหม่', placeholder='เช่น Team Roaming', required=True)
    async def on_submit(self, interaction: discord.Interaction):
        new_team = self.team_name.value
        if new_team not in war_config["teams"]:
            war_config["teams"].append(new_team)
            await send_log(interaction, "➕ เพิ่มทีม", f"เพิ่มทีม: {new_team}", discord.Color.green())
            await interaction.response.edit_message(embed=create_setup_embed(), view=SetupView())
        else:
            await interaction.response.send_message("❌ ชื่อทีมซ้ำ", ephemeral=True, delete_after=3.0)

class RemoveTeamModal(Modal, title='ลบทีมล่าสุด'):
    confirm = TextInput(label='พิมพ์ CONFIRM', placeholder='CONFIRM', required=True)
    async def on_submit(self, interaction: discord.Interaction):
        if self.confirm.value == "CONFIRM":
            if len(war_config["teams"]) > 1:
                removed = war_config["teams"].pop()
                await send_log(interaction, "➖ ลบทีม", f"ลบทีม: {removed}", discord.Color.red())
                await interaction.response.edit_message(embed=create_setup_embed(), view=SetupView())
            else: await interaction.response.send_message("❌ ต้องเหลืออย่างน้อย 1 ทีม", ephemeral=True, delete_after=3.0)
        else: await interaction.response.send_message("❌ ยืนยันไม่ถูกต้อง", ephemeral=True, delete_after=3.0)

class SetupView(View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(label="📅 เลือกวัน/เวลา/หัวข้อ", style=discord.ButtonStyle.primary, row=1)
    async def edit_config(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message("👇 **กรุณาเลือกวันที่ต้องการจัด War:**", view=DatePickerView(), ephemeral=True)

    @discord.ui.button(label="➕ เพิ่มทีม", style=discord.ButtonStyle.secondary, row=1)
    async def add_team(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(AddTeamModal())

    @discord.ui.button(label="➖ ลบทีมล่าสุด", style=discord.ButtonStyle.secondary, row=1)
    async def remove_team(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(RemoveTeamModal())

    @discord.ui.button(label="🗑️ ล้างรายชื่อเก่า (Reset)", style=discord.ButtonStyle.danger, row=2)
    async def clear_roster(self, interaction: discord.Interaction, button: Button):
        db_clear()
        await send_log(interaction, "🗑️ ล้างรายชื่อ (Manual Reset)", "Admin กดล้างรายชื่อก่อนเริ่มวอ", discord.Color.red())
        await interaction.response.send_message("✅ **ล้างรายชื่อเก่าเรียบร้อย!** พร้อมสำหรับการเริ่มประกาศใหม่", ephemeral=True)

    @discord.ui.button(label="✅ ยืนยันและประกาศ", style=discord.ButtonStyle.green, row=2)
    async def confirm(self, interaction: discord.Interaction, button: Button):
        war_config["ALERT_CHANNEL_ID"] = interaction.channel_id
        embed = create_dashboard_embed()
        view = MainWarView()
        await send_log(interaction, "📢 ประกาศ War", f"Teams: {len(war_config['teams'])}", discord.Color.gold())
        msg = await interaction.channel.send(embed=embed, view=view)
        try: await msg.create_thread(name=f"💬 ห้องคุยงาน - {war_config['title']}", auto_archive_duration=1440)
        except: pass
        await interaction.response.edit_message(content="✅ **ประกาศเรียบร้อย!**", embed=None, view=None, delete_after=5.0)

def create_setup_embed():
    embed = discord.Embed(title="🛠️ ตั้งค่าระบบ (Dynamic Config)", description="ปรับแต่งข้อมูลก่อนประกาศ", color=0x3498db)
    embed.add_field(name="📅 หัวข้อ", value=war_config["title"], inline=False)
    embed.add_field(name="🗓️ วันที่", value=war_config["date"], inline=True)
    embed.add_field(name="⏰ เวลา", value=f"{war_config['time']} น.", inline=True)
    team_list = "\n".join([f"{i+1}. {t}" for i, t in enumerate(war_config["teams"])])
    embed.add_field(name=f"🛡️ ทีมทั้งหมด ({len(war_config['teams'])})", value=f"```\n{team_list}\n```", inline=False)
    embed.set_footer(text="💡 อย่าลืมกด 'ล้างรายชื่อเก่า' หากต้องการเริ่มนับจำนวนคนใหม่")
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

# [NEW] Modal สำหรับกรอกสถานะเอง (Custom Input)
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
        await interaction.response.send_message(f"✅ ลงทะเบียนสำเร็จ! **{self.team}** ({status})", ephemeral=True, delete_after=5.0)

class StatusSelect(Select):
    def __init__(self, team, role, dashboard_msg):
        self.team = team
        self.role = role
        self.dashboard_msg = dashboard_msg
        
        options = [
            discord.SelectOption(label="🔥 อยู่ยาว / Full Time", description="จัดเต็มทุกรอบ", value="Full Time", emoji="🔥"),
        ]
        
        emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣"]
        for i in range(8):
            round_num = i + 1
            options.append(discord.SelectOption(label=f"Round {round_num}", description=f"ลงเล่นรอบที่ {round_num}", value=f"Round {round_num}", emoji=emojis[i]))
            
        options.extend([
            discord.SelectOption(label="🐢 ตามไปทีหลัง / Late Join", description="มาไม่ทันเวลาเริ่ม แต่จะตามไป", value="Late Join", emoji="🐢"),
            discord.SelectOption(label="💤 สแตนด์บาย / Standby", description="ตัวสำรอง ถ้าคนขาดค่อยเรียก", value="Standby", emoji="💤"),
            discord.SelectOption(label="✏️ อื่นๆ / ระบุเอง (Other)", description="พิมพ์บอกช่วงเวลาเอง...", value="Other", emoji="✏️")
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
            
        await interaction.response.send_message(f"✅ ลงทะเบียนสำเร็จ! **{self.team}** ({selected_text})", ephemeral=True, delete_after=5.0)

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
        await interaction.response.send_message(
            f"⏳ กรุณาระบุความพร้อมสำหรับ **{self.values[0]}**:",
            view=StatusSelectView(self.values[0], self.role_value, self.dashboard_msg),
            ephemeral=True
        )

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
        # [SORT] เรียงลำดับข้อมูลก่อน Copy ด้วย (Tank -> DPS -> Heal)
        role_priority = {"Tank": 1, "DPS": 2, "Heal": 3}
        data.sort(key=lambda x: (role_priority.get(x[2], 99), x[0])) 

        text = f"⚔️ **{war_config['title']}**\n📅 {war_config['date']} ⏰ {war_config['time']}\n\n"
        team_map = {name: [] for name in war_config["teams"]}
        absence_list = []
        for username, team, role, time in data:
            if team == "Absence": absence_list.append(f"- {username} ({role})")
            elif team in team_map: 
                team_map[team].append(f"- {username} ({role}) [{time}]")
        for team_name in war_config["teams"]:
            text += f"🛡️ **{team_name}**\n" + ("\n".join(team_map[team_name]) if team_map[team_name] else "- ว่าง -") + "\n\n"
        text += "🏳️ **แจ้งลา**\n" + ("\n".join(absence_list) if absence_list else "- ไม่มี -")
        await interaction.response.send_message(f"```{text}```", ephemeral=True)

    @discord.ui.button(label="🔒 Lock", style=discord.ButtonStyle.danger, row=3)
    async def toggle_lock(self, interaction: discord.Interaction, button: Button):
        if not interaction.user.guild_permissions.administrator: return
        global is_roster_locked
        is_roster_locked = not is_roster_locked
        await interaction.message.edit(embed=create_dashboard_embed())
        await interaction.response.send_message(f"✅ Status: {'LOCKED' if is_roster_locked else 'OPEN'}", ephemeral=True, delete_after=3.0)

    @discord.ui.button(label="💾 จบวอ/บันทึก", style=discord.ButtonStyle.success, row=3)
    async def save_history(self, interaction: discord.Interaction, button: Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("⛔ Admin Only", ephemeral=True)
            return
            
        await interaction.response.defer(ephemeral=True) 

        today = bangkok_now().strftime('%Y-%m-%d')
        count = db_save_history(today)
        
        if HISTORY_CHANNEL_ID:
            try:
                history_channel = await interaction.client.fetch_channel(HISTORY_CHANNEL_ID)
                embed = create_dashboard_embed()
                embed.title = f"📜 สรุปยอดวอ วันที่ {today}"
                embed.color = discord.Color.greyple()
                embed.description = f"จบวอเรียบร้อย สมาชิกเข้าร่วม: {count} คน"
                embed.set_footer(text=f"Saved by {interaction.user.display_name} • {bangkok_now().strftime('%H:%M:%S')}")
                await history_channel.send(embed=embed)
            except Exception as e:
                print(f"❌ Error sending history: {e}")
                await interaction.followup.send(f"⚠️ บันทึกข้อมูลแล้ว แต่ส่งเข้าห้อง History ไม่ได้ (เช็คเลขห้อง/ยศบอท): {e}", ephemeral=True)
        
        try:
            embed = interaction.message.embeds[0]
            embed.title = f"🔴 จบวอแล้ว: {war_config['title']}"
            embed.color = 0x2f3136 # สีเทาเข้ม
            embed.clear_fields() 
            embed.description = f"✅ **บันทึกข้อมูลเรียบร้อย**\n📅 วันที่: {today}\n👥 จำนวนคน: {count} คน"
            embed.set_footer(text="System Closed.")
            await interaction.message.edit(embed=embed, view=None)
        except:
            pass 
        
        db_clear()
        
        await send_log(interaction, "💾 บันทึกประวัติ", f"บันทึกข้อมูล {count} คน และปิดประกาศ", discord.Color.green())
        await interaction.followup.send(f"✅ **ปิดจบคอร์สเรียบร้อย!**\n(ส่งสรุปไปห้อง <#{HISTORY_CHANNEL_ID}> แล้ว)", ephemeral=True)

# ==========================================
# 📊 DASHBOARD
# ==========================================
def create_dashboard_embed():
    data = db_get_all()
    
    # [SORT PRIORITY] Tank -> DPS -> Heal -> Name
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
            
            # --- START NEW LOGIC: หลอดพลังในกรอบ Code Block ---
            status_display = ""
            
            on_icon = "🟢"
            off_icon = "⚫"
            
            if "Full Time" in time_text:
                status_display = f"{on_icon*4} {on_icon*4}" 
            elif "Round" in time_text:
                bar = []
                for i in range(1, 9): 
                    if f"Round {i}" in time_text:
                        bar.append(on_icon)
                    else:
                        bar.append(off_icon)
                status_display = "".join(bar[:4]) + " " + "".join(bar[4:])
            else:
                status_display = f"[{time_text}]" # เอา backticks ออกก่อนเดี๋ยวใส่รวมกัน

            if "Late Join" in time_text and "Round" in time_text:
                status_display += " 🐢"
            
            # [FIXED] ใส่ Backticks ครอบหลอดพลัง (`...`) เพื่อให้มีพื้นหลังสีดำเล็กๆ ตามรูป
            display_str = f"> `{status_display}` | {role_emoji} **{username}**"
            # --- END NEW LOGIC ---
            
            if "Standby" in time_text:
                roster[team]["Standby"].append(f"💤 {username} [Standby]")
            else:
                roster[team]["Main"].append(display_str)

    try:
        tz = pytz.timezone('Asia/Bangkok')
        now_th = datetime.now(tz)
        war_time_obj = datetime.strptime(war_config['time'], "%H:%M")
        
        date_input = war_config.get('date', 'Today').lower().strip()
        target_date = now_th.date()

        if date_input in ['tomorrow', 'พรุ่งนี้']:
            target_date = now_th.date() + timedelta(days=1)
        elif date_input not in ['today', 'วันนี้']:
            clean_date = date_input.replace('-', '/')
            try:
                parsed_date = datetime.strptime(clean_date, "%d/%m")
                target_date = parsed_date.replace(year=now_th.year).date()
                if target_date < now_th.date() and (now_th.month == 12 and target_date.month == 1):
                    target_date = target_date.replace(year=now_th.year + 1)
            except:
                pass

        target_dt = tz.localize(datetime.combine(target_date, war_time_obj.time()))
        ts = int(target_dt.timestamp())
        
        date_pretty = target_dt.strftime("%A, %d/%m")
        time_display = f"📅 **{date_pretty}**\n<t:{ts}:F> • <t:{ts}:R>"
    except Exception as e:
        time_display = f"{war_config['date']} - {war_config['time']}"

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
        
        if roster[team_name]["Main"]:
            field_value += "\n" + "\n".join(roster[team_name]["Main"])
        else:
            field_value += "\n*... ว่าง ...*"
            
        if roster[team_name]["Standby"]:
            field_value += "\n\n**— 💤 สำรอง / Standby —**\n" + "\n".join(roster[team_name]["Standby"])
            
        embed.add_field(name=f"▬▬▬▬ {team_name.upper()} ▬▬▬▬", value=field_value, inline=False)

    if stats['Absence'] > 0:
        embed.add_field(name="▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬", value=f"🏳️ **Absence List ({stats['Absence']})**", inline=False)
        embed.add_field(name="\u200b", value="\n".join(roster["Absence"]), inline=False)
        
    embed.set_footer(text=f"STATUS: {lock_text} | Last Updated: {bangkok_now().strftime('%H:%M:%S')}")
    return embed

# ==========================================
# 🤖 BOT COMMANDS
# ==========================================
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@tasks.loop(minutes=1)
async def auto_lock_task():
    global is_roster_locked
    if is_roster_locked: return

    now = bangkok_now().strftime("%H:%M")
    if now == war_config["time"]:
        is_roster_locked = True
        print(f"⏰ Auto-locked roster at {now}")

@bot.event
async def on_ready():
    init_db()
    print(f'✅ Bot Online: {bot.user}')
    await bot.tree.sync()
    if not auto_lock_task.is_running():
        auto_lock_task.start()

@bot.tree.command(name="setup_war", description="ตั้งค่าและเริ่มประกาศ")
async def setup_war(interaction: discord.Interaction):
    await interaction.response.send_message(embed=create_setup_embed(), view=SetupView(), ephemeral=True)

@bot.tree.command(name="move_all", description="ย้ายสมาชิก")
async def move_all(interaction: discord.Interaction, source: discord.VoiceChannel, target: discord.VoiceChannel):
    if not interaction.guild.me.guild_permissions.move_members:
        await interaction.response.send_message("⛔ บอทไม่มียศ", ephemeral=True)
        return
    for member in source.members:
        try: await member.move_to(target)
        except: pass
    await interaction.response.send_message(f"✅ ย้ายสำเร็จ", ephemeral=True)

@bot.tree.command(name="check_missing", description="เช็คคนขาด")
async def check_missing(interaction: discord.Interaction, target_role: discord.Role):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT user_id FROM registrations")
    ids = {row[0] for row in c.fetchall()}
    conn.close()
    missing = [m.mention for m in target_role.members if m.id not in ids and not m.bot]
    if not missing: await interaction.response.send_message("✅ ครบ!", ephemeral=True)
    else: await interaction.response.send_message(f"📢 **ขาด:** {', '.join(missing)}", ephemeral=True)

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

bot.run('Y')