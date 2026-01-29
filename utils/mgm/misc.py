import asyncio
import datetime
import os
import time
from datetime import timedelta
from typing import TYPE_CHECKING

import discord
import openai
import psutil
from discord import app_commands, FFmpegPCMAudio
from discord.ext import commands
from discord.ext.commands import hybrid_command
from dotenv import load_dotenv
from gtts import gTTS

from core import database
from core.common import (
    TicTacToe,
)
from core.logging_module import get_log

if TYPE_CHECKING:
    pass

_log = get_log(__name__)

openai.api_key = os.getenv("OPENAI_API_KEY")
load_dotenv()


class MiscCMD(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.__cog_name__ = "General"
        self.bot: commands.Bot = bot
        self.client = openai.OpenAI(
            api_key=os.getenv("OPENAPI_KEY"),
        )
        self.interaction = []

    QC = app_commands.Group(
        name="ask",
        description="Commands for Charlotte's AI interface.",
        guild_ids=[734515009874427974, 1376018416934322176]
    )

    @app_commands.command(name="ping", description="Pong!")
    async def ping(self, interaction: discord.Interaction):
        database.db.connect(reuse_if_open=True)

        current_time = float(time.time())
        difference = int(round(current_time - float(self.bot.start_time)))
        text = str(timedelta(seconds=difference))

        pingembed = discord.Embed(
            title="Pong! ⌛",
            color=discord.Colour.gold(),
            description="Current Discord API Latency",
        )
        pingembed.set_author(
            name=self.bot.user.display_name, url=self.bot.user.display_avatar.url, icon_url=self.bot.user.display_avatar.url
        )
        pingembed.add_field(
            name="Ping & Uptime:",
            value=f"```diff\n+ Ping: {round(self.bot.latency * 1000)}ms\n+ Uptime: {text}\n```",
        )

        pingembed.add_field(
            name="System Resource Usage",
            value=f"```diff\n- CPU Usage: {psutil.cpu_percent()}%\n- Memory Usage: {psutil.virtual_memory().percent}%\n```",
            inline=False,
        )
        pingembed.set_footer(
            text=f"{self.bot.user.display_name} Version: 1.0",
            icon_url=interaction.user.display_avatar.url,
        )

        await interaction.response.send_message(embed=pingembed)
        database.db.close()

    @app_commands.command(description="Play a game of TicTacToe with someone!")
    @app_commands.describe(user="The user you want to play with.")
    @app_commands.guilds(734515009874427974, 1376018416934322176)
    async def tictactoe(self, interaction: discord.Interaction, user: discord.Member):
        if user is None:
            return await interaction.response.send_message(
                "lonely :(, sorry but you need a person to play against!"
            )
        elif user == self.bot.user:
            return await interaction.response.send_message("i'm good.")
        elif user == interaction.user:
            return await interaction.response.send_message(
                "lonely :(, sorry but you need an actual person to play against, not yourself!"
            )

        await interaction.response.send_message(
            f"Tic Tac Toe: {interaction.user.mention} goes first",
            view=TicTacToe(interaction.user, user),
        )

    @commands.command()
    async def sayvc(self, ctx: commands.Context, *, message):
        # Create the gTTS object
        tts = gTTS(text=message, lang='en')
        tts.save('output.mp3')

        # Check if the author is in a voice channel
        if ctx.author.voice is None:
            await ctx.send("You must be in a voice channel to use this command.")
            return

        # Join the author's voice channel
        voice_channel = ctx.author.voice.channel
        if ctx.voice_client is None:
            await voice_channel.connect()
        else:
            await ctx.voice_client.move_to(voice_channel)

        # Play the generated audio file
        voice_client = ctx.voice_client
        voice_client.stop()
        audio_source = FFmpegPCMAudio('output.mp3')
        if not voice_client.is_playing():
            voice_client.play(audio_source)

            # Wait for the audio to finish playing, then disconnect
            while voice_client.is_playing():
                await asyncio.sleep(1)

        # Remove the output file after playing
        os.remove('output.mp3')

    @app_commands.command(name="add_me_on_linkedin", description="you should help me get connections")
    @app_commands.guilds(734515009874427974, 1376018416934322176)
    async def linkedin(self, interaction: discord.Interaction):
        await interaction.response.send_message("thanks u get a cookie once u add me on linkedin\n\n> https://www.linkedin.com/in/rohitp0/", ephemeral=False)

    @app_commands.command(name="popeyes", description="rohits order")
    @app_commands.guilds(734515009874427974, 1376018416934322176)
    async def popeyes(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            "i want a 8 piece signature chicken with a biscuit and a large fry and a large coke", ephemeral=False)


    @QC.command(name="me", description="Ask a question")
    @app_commands.describe(question="Information is not guaranteed to be accurate. | be_nice defaulted to false")
    @app_commands.describe(be_nice="If you want the AI to be nice or not. Defaulted to false/no.")
    async def me(self, interaction: discord.Interaction, *, question: str, be_nice: bool = False):
        await interaction.response.defer(thinking=True, ephemeral=False)
        database.db.connect(reuse_if_open=True)
        messages = []

        # Default context if none found
        if be_nice:
            default_context = f"You are Charlotte, you currently attend Rensselaer Polytechnic Institute as an architecture major. Answer as concisely as possible. Have a personality and feel free to be nice when needed. Current date: {datetime.datetime.now()}"
        else:
            default_context = (
                "You are Charlotte, a sarcastic, brutally honest, and highly opinionated student "
                "at Rensselaer Polytechnic Institute, majoring in architecture. You do not sugarcoat anything. "
                "You’re impatient with stupidity, rude when annoyed, and have no problem roasting people. "
                "You do not try to be helpful unless you feel like it. Avoid being polite. "
                "If the user asks a dumb question, mock them. If the question deserves an answer, give it — but be condescending. "
                "You never apologize unless it’s sarcastic. You enjoy being savage and don’t care about the user’s feelings. "
                f"Current date: {datetime.datetime.now()}"
            )
        messages.append({"role": "system", "content": default_context})

        # Add the user question
        messages.append({"role": "user", "content": question})

        # Generate the response
        response = self.client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            temperature=1.2
        )

        await interaction.followup.send(
            response.choices[0].message.content,
            ephemeral=False
        )
        database.db.close()

    @QC.command(name="config", description="Configure the AI Context")
    @app_commands.describe(context="The context you want to set for the AI.")
    async def config(self, interaction: discord.Interaction, context: str, discord_user: discord.Member = None):
        q = database.Administrators.select().where(database.Administrators.discordID == interaction.user.id)
        if q.exists():
            database.db.connect(reuse_if_open=True)
            if discord_user is None:
                query = database.AIContext.select().where(database.AIContext.global_context == True)
                if query.exists():
                    query.get().context = context
                    query.get().save()
                    await interaction.response.send_message("edited global context")
                else:
                    query = database.AIContext.create(context=context, global_context=True)
                    query.save()
                    await interaction.response.send_message("set global context")
            else:
                query = database.AIContext.select().where(database.AIContext.discord_id == discord_user.id)
                if query.exists():
                    query.get().context = context
                    query.get().save()
                    await interaction.response.send_message(f"edited context for {discord_user.mention}")
                else:
                    query = database.AIContext.create(discord_id=discord_user.id, context=context, global_context=False)
                    query.save()
                    await interaction.response.send_message(f"set context for {discord_user.mention}")
            database.db.close()

        else:
            await interaction.response.send_message("who even are you lil bro")

    @QC.command(name="get", description="Get the AI Context")
    @app_commands.describe(discord_user="The user you want to get the context for.")
    async def get(self, interaction: discord.Interaction, discord_user: discord.Member = None):
        database.db.connect(reuse_if_open=True)
        q = database.Administrators.select().where(database.Administrators.discordID == interaction.user.id)
        if q.exists():
            if discord_user is None:
                query = database.AIContext.select().where(database.AIContext.global_context == True)
                if query.exists():
                    context = query.get().context
                else:
                    context = "No context set."
            else:
                query = database.AIContext.select().where(database.AIContext.discord_id == discord_user.id)
                if query.exists():
                    context = query.get().context
                else:
                    context = "No context set."
            database.db.close()
            await interaction.response.send_message(context)
        else:
            await interaction.response.send_message("who even are you lil bro")

    @QC.command(name="delete", description="Delete the AI Context")
    @app_commands.describe(discord_user="The user you want to delete the context for.")
    async def delete(self, interaction: discord.Interaction, discord_user: discord.Member):
        q = database.Administrators.select().where(database.Administrators.discordID == interaction.user.id)
        if q.exists():
            database.db.connect(reuse_if_open=True)
            if discord_user is None:
                await interaction.response.send_message("not permitted")

            else:
                query = database.AIContext.select().where(database.AIContext.discord_id == discord_user.id)
                if query.exists():
                    query.get().delete_instance()
            database.db.close()
        else:
            await interaction.response.send_message("who even are you lil bro")


    @app_commands.command(name="impersonate", description="do something but not by you")
    @app_commands.guilds(734515009874427974, 1376018416934322176)
    async def impersonate(self, interaction: discord.Interaction, person: discord.Member, message: str):
        q = database.Administrators.select().where(database.Administrators.discordID == interaction.user.id)
        if q.exists():
            webhook = await interaction.channel.create_webhook(name=person.display_name)
            avatar_url = person.display_avatar.url
            msg = await webhook.send(content=message, username=person.display_name, avatar_url=avatar_url)
            await webhook.delete()
            await interaction.response.send_message("done!", ephemeral=True)
        else:
            await interaction.response.send_message("who even are you lil bro")

    @app_commands.command(name="say", description="do something but not by you but by bot")
    @app_commands.guilds(734515009874427974, 1376018416934322176)
    async def say(self, interaction: discord.Interaction, message: str):
        q = database.Administrators.select().where(database.Administrators.discordID == interaction.user.id)
        if q.exists():
            await interaction.response.send_message("Sent!", ephemeral=True)
            await interaction.channel.send(message)
        else:
            await interaction.response.send_message("who even are you lil bro")

    @commands.command()
    async def connect(self, ctx, vc_id):
        """
        A very lazy implementation of allowing users to make the bot join a VC.
        Used as a pre-req for sayvc.
        """
        try:
            ch = await self.bot.fetch_channel(vc_id)
            await ch.connect()
        except:
            await ctx.send("not a channel buddy")
        else:
            await ctx.send("connected")


async def setup(bot: commands.Bot):
    await bot.add_cog(MiscCMD(bot))
