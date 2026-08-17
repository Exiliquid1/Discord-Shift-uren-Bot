import sqlite3
import datetime
import discord
from discord.ext import commands, tasks

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="/", intents=intents)

# ⚠️ VUL HIER JOUW KANAAL ID IN
DASHBOARD_CHANNEL_ID = 1538900577000362154  
DASHBOARD_MESSAGE_ID = None

# --- DATABASE SETUP ---
conn = sqlite3.connect("rooster_week.db")
cursor = conn.cursor()
cursor.execute('''
    CREATE TABLE IF NOT EXISTS week_rooster (
        user_id INTEGER,
        username TEXT,
        dag_index INTEGER,
        van_tijd TEXT,
        tot_tijd TEXT,
        is_vrij INTEGER,
        PRIMARY KEY (user_id, dag_index)
    )
''')
conn.commit()

DAGEN = ["Maandag", "Dinsdag", "Woensdag", "Donderdag", "Vrijdag", "Zaterdag", "Zondag"]

# --- MODAL VOOR SPECIFIEKE DAG ---
class DagInvoerModal(discord.ui.Modal):
    def __init__(self, dag_index: int):
        self.dag_index = dag_index
        super().__init__(title=f"Werktijden voor {DAGEN[dag_index]}")

        self.van_input = discord.ui.TextInput(
            label="Begintijd (HH:MM) - Typ 'vrij' als vrij",
            placeholder="08:00",
            default="08:00",
            min_length=4,
            max_length=5
        )
        self.tot_input = discord.ui.TextInput(
            label="Eindtijd (HH:MM)",
            placeholder="16:30",
            default="16:30",
            required=False,
            min_length=4,
            max_length=5
        )
        self.add_item(self.van_input)
        self.add_item(self.tot_input)

    async def on_submit(self, interaction: discord.Interaction):
        user = interaction.user
        van = self.van_input.value.strip().lower()
        tot = self.tot_input.value.strip() if self.tot_input.value else "00:00"

        if van == "vrij":
            cursor.execute('''
                INSERT OR REPLACE INTO week_rooster (user_id, username, dag_index, van_tijd, tot_tijd, is_vrij)
                VALUES (?, ?, ?, '00:00', '00:00', 1)
            ''', (user.id, user.display_name, self.dag_index))
        else:
            cursor.execute('''
                INSERT OR REPLACE INTO week_rooster (user_id, username, dag_index, van_tijd, tot_tijd, is_vrij)
                VALUES (?, ?, ?, ?, ?, 0)
            ''', (user.id, user.display_name, self.dag_index, van, tot))

        conn.commit()
        await interaction.response.send_message(
            f" Opslag geslaagd voor **{DAGEN[self.dag_index]}**!", 
            ephemeral=True
        )
        await update_dashboard()

# --- SELECTIE MENU VOOR DAGEN ---
class DagSelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.select(
        placeholder=" Kies de dag die je wil invullen/aanpassen...",
        custom_id="select_dag_menu",
        options=[
            discord.SelectOption(label=dag, value=str(i)) for i, dag in enumerate(DAGEN)
        ]
    )
    async def select_callback(self, interaction: discord.Interaction, select: discord.ui.Select):
        dag_idx = int(select.values[0])
        await interaction.response.send_modal(DagInvoerModal(dag_idx))

# --- LIVE DASHBOARD GENERATIE ---
def genereer_dashboard_embed():
    nu = datetime.datetime.now()
    huidige_tijd = nu.strftime("%H:%M")
    vandaag_index = nu.weekday()
    vandaag_naam = DAGEN[vandaag_index]

    cursor.execute('SELECT username, dag_index, van_tijd, tot_tijd, is_vrij FROM week_rooster')
    rows = cursor.fetchall()

    vrij_om_te_gamen = []
    aan_het_werk = []
    gebruikers_rooster = {}

    for username, dag_idx, van, tot, is_vrij in rows:
        if username not in gebruikers_rooster:
            gebruikers_rooster[username] = ["-"] * 7
        
        if is_vrij:
            gebruikers_rooster[username][dag_idx] = "Vrij"
        else:
            gebruikers_rooster[username][dag_idx] = f"{van}-{tot}"

        if dag_idx == vandaag_index:
            if is_vrij:
                vrij_om_te_gamen.append(f"🟢 **{username}** (Vrij vandaag)")
            else:
                if van <= huidige_tijd <= tot:
                    aan_het_werk.append(f"🔴 **{username}** (Werkt tot {tot})")
                elif huidige_tijd > tot:
                    vrij_om_te_gamen.append(f"🟢 **{username}** (Klaar met werken om {tot})")
                else:
                    vrij_om_te_gamen.append(f"🟡 **{username}** (Begint om {van})")

    embed = discord.Embed(
        title="🎮 LIVE GAMING & WEEKROOSTER DASHBOARD",
        description=f" Vandaag is **{vandaag_naam}** | Tijd: **{huidige_tijd}**\n\n"
                    f"*Selecteer hieronder een dag om je uren voor deze week in te voeren.*",
        color=discord.Color.blue()
    )

    if vrij_om_te_gamen:
        embed.add_field(name="✅ Nu Beschikbaar om te gamen", value="\n".join(vrij_om_te_gamen), inline=False)
    else:
        embed.add_field(name="✅ Nu Beschikbaar om te gamen", value="*Niemand opgegeven*", inline=False)

    if aan_het_werk:
        embed.add_field(name="⏳ Aan het werk", value="\n".join(aan_het_werk), inline=False)
    else:
        embed.add_field(name="⏳ Aan het werk", value="*Niemand aan het werk*", inline=False)

    if gebruikers_rooster:
        rooster_tekst = ""
        for user, dagen in gebruikers_rooster.items():
            rooster_tekst += f"**{user}**:\n"
            for i, d in enumerate(DAGEN):
                if dagen[i] != "-":
                    rooster_tekst += f"• *{d[:2]}*: {dagen[i]} "
            rooster_tekst += "\n"
        embed.add_field(name=" Weekrooster Overzicht", value=rooster_tekst, inline=False)

    return embed

async def update_dashboard():
    global DASHBOARD_MESSAGE_ID
    channel = bot.get_channel(DASHBOARD_CHANNEL_ID)
    if not channel:
        return

    embed = genereer_dashboard_embed()

    if DASHBOARD_MESSAGE_ID:
        try:
            msg = await channel.fetch_message(DASHBOARD_MESSAGE_ID)
            await msg.edit(embed=embed, view=DagSelectView())
            return
        except discord.NotFound:
            pass

    msg = await channel.send(embed=embed, view=DagSelectView())
    DASHBOARD_MESSAGE_ID = msg.id

# --- AUTOMATISCHE REFRESH LOOP (ELKE MINUUT) ---
@tasks.loop(minutes=1)
async def auto_refresh_dashboard():
    nu = datetime.datetime.now()
    huidige_tijd = nu.strftime("%H:%M")
    dag_van_week = nu.weekday() # 6 = Zondag

    # 1. ZONDAG HERINNERING OM 19:00
    if dag_van_week == 6 and huidige_tijd == "19:00":
        channel = bot.get_channel(DASHBOARD_CHANNEL_ID)
        if channel:
            await channel.send("🔔 **Herinnering!** Vergeet niet je werktijden voor de komende week in te voeren via het dashboard hierboven! @everyone")

    # 2. ZONDAG NACHT RESET OM 23:59
    if dag_van_week == 6 and huidige_tijd == "23:59":
        cursor.execute('DELETE FROM week_rooster')
        conn.commit()
        print("Het weekrooster is automatisch gereset voor de nieuwe week!")

    await update_dashboard()

@bot.event
async def on_ready():
    print(f'Bot is succesvol ingelogd als {bot.user}')
    bot.add_view(DagSelectView())
    auto_refresh_dashboard.start()

# ⚠️ VUL HIER JOUW BOT TOKEN IN
bot.run("MTUzODg5Njg4NzUzMTE4NDIyOQ.GMxFA9.N2ZsJ4FhvrW7rTtKHszty2yJYXg9IlwCUy-aJs")