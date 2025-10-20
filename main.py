"""
Copyright (C) SpaceTurtle0 - All Rights Reserved
 * Permission is granted to use this application as a boilerplate.
 * Written by Space. December 2022
"""

__author__ = "rohit"
__author_email__ = "hello@hello.com"
__project__ = "SASE Bot"

import faulthandler
import logging
import os
import time
from datetime import datetime

import discord
from alive_progress import alive_bar
from discord import app_commands
from discord.ext import commands
from discord_sentry_reporting import use_sentry
from dotenv import load_dotenv
from pygit2 import Repository, GIT_DESCRIBE_TAGS
from sentry_sdk.integrations.flask import FlaskIntegration
from sentry_sdk.integrations.logging import LoggingIntegration

from core import database
from core.common import get_extensions
from core.logging_module import get_log
from core.special_methods import (
    before_invoke_,
    initialize_database,
    main_mode_check_,
    on_command_error_,
    on_ready_,
    on_command_,
)

load_dotenv()
faulthandler.enable()

logger = logging.getLogger("discord")
logger.setLevel(logging.INFO)

_log = get_log(__name__)
_log.info("Starting up...")


class SASEBotSlashTree(app_commands.CommandTree):
    def __init__(self, bot):
        super().__init__(bot)
        self.bot = bot

    async def interaction_check(self, interaction: discord.Interaction, /) -> bool:
        blacklisted_users = [p.discordID for p in database.Blacklist]
        if interaction.user.id in blacklisted_users:
            await interaction.response.send_message(
                "You have been blacklisted from using commands!", ephemeral=True
            )
            return False
        return True

    async def on_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ):
        # await on_app_command_error_(self.bot, interaction, error)
        pass


class SASEBot(commands.Bot):
    """
    Generates a SASEBot Instance.
    """

    def __init__(self, uptime: time.time):
        super().__init__(
            command_prefix=commands.when_mentioned_or(os.getenv("PREFIX")),
            intents=discord.Intents.all(),
            case_insensitive=True,
            tree_cls=SASEBotSlashTree,
            activity=discord.Activity(
                type=discord.ActivityType.watching, name="u"
            ),
        )
        self.help_command = None
        self.before_invoke(self.analytics_before_invoke)
        self.add_check(self.check)
        self._start_time = uptime

    async def on_ready(self):
        await on_ready_(self)

    async def on_command_error(self, ctx: commands.Context, error: Exception):
        await on_command_error_(self, ctx, error)

    async def on_command(self, ctx: commands.Context):
        await on_command_(self, ctx)

    async def analytics_before_invoke(self, ctx: commands.Context):
        await before_invoke_(ctx)

    async def check(self, ctx: commands.Context):
        return await main_mode_check_(ctx)

    async def setup_hook(self) -> None:
        with alive_bar(
            len(get_extensions()),
            ctrl_c=False,
            bar="bubbles",
            title="Initializing Cogs:",
        ) as bar:

            for ext in get_extensions():
                try:
                    await bot.load_extension(ext)
                except commands.ExtensionAlreadyLoaded:
                    await bot.unload_extension(ext)
                    await bot.load_extension(ext)
                except commands.ExtensionNotFound:
                    raise commands.ExtensionNotFound(ext)
                bar()

    async def is_owner(self, user: discord.User):
        admin_ids = []
        query = database.Administrators.select().where(
            database.Administrators.TierLevel >= 3
        )
        for admin in query:
            admin_ids.append(admin.discordID)

        if user.id in admin_ids:
            return True

        return await super().is_owner(user)

    @property
    def version(self):
        """
        Returns the current version of the bot.
        """
        repo = Repository(".")
        current_commit = repo.head
        current_branch = repo.head.shorthand

        version = ...  # type: str
        if current_branch == "HEAD":
            current_tag = repo.describe(committish=current_commit, describe_strategy=GIT_DESCRIBE_TAGS)
            version = f"{current_tag} (stable)"
        else:
            version = "development"
        version += f" | {str(current_commit.target)[:7]}"

        return version

    @property
    def author(self):
        """
        Returns the author of the bot.
        """
        return __author__

    @property
    def author_email(self):
        """
        Returns the author email of the bot.
        """
        return __author_email__

    @property
    def start_time(self):
        """
        Returns the time the bot was started.
        """
        return self._start_time


bot = SASEBot(time.time())


@bot.event
async def on_interaction(interaction: discord.Interaction):
    if interaction.type == discord.InteractionType.application_command:
        database.CommandAnalytics.create(
            command=interaction.command.name,
            guild_id=interaction.guild.id,
            user=interaction.user.id,
            date=datetime.now(),
            command_type="slash",
        ).save()


if os.getenv("DSN_SENTRY") is not None:
    sentry_logging = LoggingIntegration(
        level=logging.INFO,  # Capture info and above as breadcrumbs
        event_level=logging.ERROR,  # Send errors as events
    )

    # Traceback tracking, DO NOT MODIFY THIS
    use_sentry(
        bot,
        dsn=os.getenv("DSN_SENTRY"),
        traces_sample_rate=1.0,
        integrations=[FlaskIntegration(), sentry_logging],
    )


initialize_database(bot)

if __name__ == "__main__":
    bot.run(os.getenv("TOKEN"))
