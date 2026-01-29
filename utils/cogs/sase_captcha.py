# cogs/captcha_sase.py
import io
import random
import string
import asyncio
import discord
from discord import app_commands
from discord.ext import commands
from multicolorcaptcha import CaptchaGenerator
from PIL import Image

# ---------------- CONFIG ----------------
ROLE_ID = 1455301776873095356  # replace with your Verified role ID
CAPTCHA_LENGTH = 6
CAPTCHA_TTL = 300  # seconds
# ----------------------------------------

# Captcha image size number (2 -> 640x360, 1 -> smaller)
CAPTCHA_SIZE_NUM = 1  # good balance for Discord embeds

# Create generator once (global or module-level)
captcha_generator = CaptchaGenerator(CAPTCHA_SIZE_NUM)

def generate_captcha():
    """
    Generate a multicolor CAPTCHA using multicolorcaptcha.
    Returns (answer_text, image_bytes)
    """
    captcha = captcha_generator.gen_math_captcha_image(difficult_level=4, multicolor=True)

    # Get information of math captcha
    math_image = captcha.image
    math_equation_string = captcha.equation_str
    math_equation_result = captcha.equation_result

    # Save the images to files
    math_image.save("captcha.png", "png")
    return math_equation_result, math_image


class CaptchaModal(discord.ui.Modal, title="Enter CAPTCHA Code"):
    def __init__(self, cog: "CaptchaSASE", user_id: int):
        super().__init__(timeout=180)
        self.cog = cog
        self.user_id = user_id

        self.code_input = discord.ui.TextInput(
            label="CAPTCHA Code",
            placeholder="Enter the math result here",
            min_length=1,
            max_length=5,
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
                await interaction.user.remove_roles(role, reason="Passed CAPTCHA verification")
            except discord.Forbidden:
                await interaction.response.send_message("I lack perms to assign that role sorry lol.", ephemeral=True)
                return

            await interaction.response.send_message("**✅ verified**\n> congrats you've been verified!", ephemeral=True)
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
        code, image = generate_captcha()
        async with self.cog.lock:
            self.cog.active_captchas[interaction.user.id] = {
                "code": code,
                "expires": asyncio.get_event_loop().time() + CAPTCHA_TTL
            }

        file = discord.File("captcha.png", filename="captcha.png")
        caption = f"🧩 CAPTCHA generated! you got {CAPTCHA_TTL // 60} minutes to solve the math puzzle shown in the image below. click **Enter Code** to record your answer."
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
    @app_commands.guilds(1223473430410690630, 734515009874427974)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def post_captcha(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Server Verification",
            description="hey there, click **Start Verification** to solve a puzzle to gain access to the rest of the server!",
            color=discord.Color.blurple()
        )
        view = StartVerificationView(self)
        await interaction.response.send_message(embed=embed, view=view)

    # New: assign "unverified" role when a member joins
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        print("Member joined, assigning unverified role if applicable.")
        if (
            not member.bot
            and member.guild is not None
            and member.guild.id == 734515009874427974
        ):
            role = discord.utils.find(lambda r: r.name.lower() == "unverified", member.guild.roles)
            if role is None:
                return
            try:
                await member.add_roles(role, reason="Assigned unverified on join")
            except Exception as e:
                print("failed to assign")
                print(e)
                return


async def setup(bot):
    await bot.add_cog(CaptchaSASE(bot))