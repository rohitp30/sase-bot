# cogs/captcha_sase.py
import io
import random
import string
import asyncio
import discord
from discord import app_commands
from discord.ext import commands
from captcha.image import ImageCaptcha

# ---------------- CONFIG ----------------
ROLE_ID = 1429659690949939271  # replace with your Verified role ID
CAPTCHA_LENGTH = 6
CAPTCHA_TTL = 300  # seconds
# ----------------------------------------


def generate_captcha():
    """Generate a CAPTCHA using the captcha module."""
    captcha_gen = ImageCaptcha(width=280, height=90)
    text = ''.join(random.choices(string.ascii_uppercase + string.digits, k=CAPTCHA_LENGTH))
    image_data = captcha_gen.generate(text)
    image_bytes = io.BytesIO(image_data.read())
    image_bytes.seek(0)
    return text, image_bytes


class CaptchaModal(discord.ui.Modal, title="Enter CAPTCHA Code"):
    def __init__(self, cog: "CaptchaSASE", user_id: int):
        super().__init__(timeout=180)
        self.cog = cog
        self.user_id = user_id

        self.code_input = discord.ui.TextInput(
            label="CAPTCHA Code",
            placeholder="Type the letters/numbers shown",
            min_length=1,
            max_length=10
        )
        self.add_item(self.code_input)

    async def on_submit(self, interaction: discord.Interaction):
        code_entered = self.code_input.value.strip().upper()

        async with self.cog.lock:
            expected = self.cog.active_captchas.get(self.user_id)

        if not expected:
            await interaction.response.send_message("⚠️ you don’t have an active CAPTCHA go get a new one.", ephemeral=True)
            return

        if expected["expires"] < asyncio.get_event_loop().time():
            await interaction.response.send_message("⌛ your CAPTCHA expired buddy. go click the button again to get a new one.", ephemeral=True)
            async with self.cog.lock:
                self.cog.active_captchas.pop(self.user_id, None)
            return

        if code_entered == expected["code"]:
            async with self.cog.lock:
                self.cog.active_captchas.pop(self.user_id, None)

            role = interaction.guild.get_role(ROLE_ID)
            if not role:
                await interaction.response.send_message("idk how i got here but theres no verified role to give u sorry. contact an admin", ephemeral=True)
                return

            try:
                await interaction.user.add_roles(role, reason="Passed CAPTCHA verification")
            except discord.Forbidden:
                await interaction.response.send_message("I lack perms to assign that role sorry lol.", ephemeral=True)
                return

            await interaction.response.send_message("**✅ verified**\n> congrats you verified! at least we know you aint a bot now", ephemeral=True)
        else:
            await interaction.response.send_message("**❌ invalid**\n> so you a bot. if ur actually real try again", ephemeral=True)


class VerifyView(discord.ui.View):
    def __init__(self, cog: "CaptchaSASE", user_id: int):
        super().__init__(timeout=180)
        self.cog = cog
        self.user_id = user_id

    @discord.ui.button(label="Enter Code", style=discord.ButtonStyle.primary)
    async def enter_code(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("how'd you even get here, this aint urs :/", ephemeral=True)
            return
        await interaction.response.send_modal(CaptchaModal(self.cog, self.user_id))


class StartVerificationView(discord.ui.View):
    def __init__(self, cog: "CaptchaSASE"):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Start Verification", style=discord.ButtonStyle.success, custom_id="captcha:start")
    async def start_verification(self, interaction: discord.Interaction, button: discord.ui.Button):
        code, image_bytes = generate_captcha()
        async with self.cog.lock:
            self.cog.active_captchas[interaction.user.id] = {
                "code": code,
                "expires": asyncio.get_event_loop().time() + CAPTCHA_TTL
            }

        file = discord.File(image_bytes, filename="captcha.png")
        caption = f"🧩 CAPTCHA generated! you got {CAPTCHA_TTL // 60} minutes to solve it"
        view = VerifyView(self.cog, interaction.user.id)
        await interaction.response.send_message(content=caption, file=file, view=view, ephemeral=True)


class CaptchaSASE(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_captchas = {}
        self.lock = asyncio.Lock()

    async def cog_load(self):
        self.bot.add_view(StartVerificationView(self))

    @app_commands.command(name="post_captcha", description="Post the CAPTCHA verification message.")
    @app_commands.guilds(1223473430410690630)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def post_captcha(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Server Verification",
            description="hey click **Start Verification** to solve a puzzle 🤓",
            color=discord.Color.blurple()
        )
        view = StartVerificationView(self)
        await interaction.response.send_message(embed=embed, view=view)


async def setup(bot):
    await bot.add_cog(CaptchaSASE(bot))