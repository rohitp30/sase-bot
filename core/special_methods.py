from __future__ import annotations

import collections
import os
import subprocess
import traceback
from datetime import datetime
from difflib import get_close_matches
from pathlib import Path
from typing import TYPE_CHECKING

import discord
import sentry_sdk
from discord.ext import commands

from core import database
from core.common import (
    ConsoleColors,
    Colors,
)
from core.logging_module import get_log

if TYPE_CHECKING:
    # change this if you change the class name
    from main import BOTNAME as BotObject

_log = get_log(__name__)


async def before_invoke_(ctx: commands.Context):
    q = database.CommandAnalytics.create(
        command=ctx.command.name,
        user=ctx.author.id,
        date=datetime.now(),
        command_type="regular",
        guild_id=ctx.guild.id if ctx.guild is not None else 0,
    ).save()

    sentry_sdk.set_user(None)
    sentry_sdk.set_user({"id": ctx.author.id, "username": ctx.author.name})
    sentry_sdk.set_tag("username", f"{ctx.author.name}#{ctx.author.discriminator}")
    if ctx.command is None:
        sentry_sdk.set_context(
            "user",
            {
                "name": ctx.author.name if ctx.author is not None else "None",
                "id": ctx.author.id if ctx.author is not None else "None",
                "command": ctx.command if ctx.command is not None else "None",
                "guild": ctx.guild.name if ctx.guild is not None else "None",
                "guild_id": ctx.guild.id if ctx.guild is not None else "None",
                "channel": getattr(ctx.channel, "name", "DM" if isinstance(ctx.channel, discord.DMChannel) else "None"),
                "channel_id": ctx.channel.id if ctx.channel is not None else "None",
            },
        )
    else:
        sentry_sdk.set_context(
            "user",
            {
                "name": ctx.author.name,
                "id": ctx.author.id if ctx.author is not None else "None",
                "command": "Unknown",
                "guild": ctx.guild.name if ctx.guild is not None else "None",
                "guild_id": ctx.guild.id if ctx.guild is not None else "None",
                "channel": getattr(ctx.channel, "name", "DM" if isinstance(ctx.channel, discord.DMChannel) else "None"),
                "channel_id": ctx.channel.id if ctx.channel is not None else "None",
            },
        )


async def on_ready_(bot: BotObject):
    now = datetime.now()
    query: database.CheckInformation = (
        database.CheckInformation.select()
        .where(database.CheckInformation.id == 1)
        .get()
    )

    if not query.persistent_change:
        # bot.add_view(ViewClass(bot))

        query.persistent_change = True
        query.save()

    if not os.getenv("USEREAL"):
        IP = os.getenv("DATABASE_IP")
        database_field = f"{ConsoleColors.OKGREEN}Selected Database: External ({IP}){ConsoleColors.ENDC}"
    else:
        database_field = (
            f"{ConsoleColors.FAIL}Selected Database: localhost{ConsoleColors.ENDC}\n{ConsoleColors.WARNING}WARNING: Not "
            f"recommended to use SQLite.{ConsoleColors.ENDC} "
        )

    try:
        p = subprocess.run(
            "git describe --always",
            shell=True,
            text=True,
            capture_output=True,
            check=True,
        )
        output = p.stdout
    except subprocess.CalledProcessError:
        output = "ERROR"

    # chat_exporter.init_exporter(bot)

    print(
        f"""
            {bot.user.name} is ready!

            Bot Account: {bot.user.name} | {bot.user.id}
            {ConsoleColors.OKCYAN}Discord API Wrapper Version: {discord.__version__}{ConsoleColors.ENDC}
            {ConsoleColors.WARNING}StudyBot Version: {output}{ConsoleColors.ENDC}
            {database_field}

            {ConsoleColors.OKCYAN}Current Time: {now}{ConsoleColors.ENDC}
            {ConsoleColors.OKGREEN}Cogs, libraries, and views have successfully been initialized.{ConsoleColors.ENDC}
            ==================================================
            {ConsoleColors.WARNING}Statistics{ConsoleColors.ENDC}

            Guilds: {len(bot.guilds)}
            Members: {len(bot.users)}
            """
    )


async def on_command_error_(bot: BotObject, ctx: commands.Context, error: Exception):
    tb = error.__traceback__
    etype = type(error)
    exception = traceback.format_exception(etype, error, tb, chain=True)
    exception_msg = ""
    for line in exception:
        exception_msg += line

    error = getattr(error, "original", error)
    if ctx.command is not None:
        if ctx.command.name == "rule":
            return "No Rule..."

    if isinstance(error, (commands.CheckFailure, commands.CheckAnyFailure)):
        return

    if hasattr(ctx.command, "on_error"):
        return

    elif isinstance(error, (commands.CommandNotFound, commands.errors.CommandNotFound)):
        cmd = ctx.invoked_with
        cmds = [cmd.name for cmd in bot.commands]
        matches = get_close_matches(cmd, cmds)
        if len(matches) > 0:
            return await ctx.send(
                f'Command "{cmd}" not found, maybe you meant "{matches[0]}"?'
            )
        else:
            """return await ctx.send(
                f'Command "{cmd}" not found, use the help command to know what commands are available. '
                f"Some commands have moved over to slash commands, please check "
                f"url"
                f"for more updates! "
            )"""
            return await ctx.message.add_reaction("❌")

    elif isinstance(
        error, (commands.MissingRequiredArgument, commands.TooManyArguments)
    ):
        signature = f"{ctx.prefix}{ctx.command.qualified_name} {ctx.command.signature}"

        em = discord.Embed(
            title="Missing/Extra Required Arguments Passed In!",
            description="You have missed one or several arguments in this command"
            "\n\nUsage:"
            f"\n`{signature}`",
            color=Colors.red,
        )
        em.set_thumbnail(url=bot.user.avatar.url)
        em.set_footer(
            text="Consult the Help Command if you are having trouble or call over a Bot Manager!"
        )
        return await ctx.send(embed=em)

    elif isinstance(
        error,
        (
            commands.MissingAnyRole,
            commands.MissingRole,
            commands.MissingPermissions,
            commands.errors.MissingAnyRole,
            commands.errors.MissingRole,
            commands.errors.MissingPermissions,
        ),
    ):
        em = discord.Embed(
            title="Invalid Permissions!",
            description="You do not have the associated role in order to successfully invoke this command! "
            "Contact an administrator/developer if you believe this is invalid.",
            color=Colors.red,
        )
        em.set_thumbnail(url=bot.user.avatar.url)
        em.set_footer(
            text="Consult the Help Command if you are having trouble or call over a Bot Manager!"
        )
        await ctx.send(embed=em)
        return

    elif isinstance(
        error,
        (commands.BadArgument, commands.BadLiteralArgument, commands.BadUnionArgument),
    ):
        signature = f"{ctx.prefix}{ctx.command.qualified_name} {ctx.command.signature}"

        em = discord.Embed(
            title="Bad Argument!",
            description=f"Unable to parse arguments, check what arguments you provided."
            f"\n\nUsage:\n`{signature}`",
            color=Colors.red,
        )
        em.set_thumbnail(url=bot.user.avatar.url)
        em.set_footer(
            text="Consult the Help Command if you are having trouble or call over a Bot Manager!"
        )
        return await ctx.send(embed=em)

    elif isinstance(
        error, (commands.CommandOnCooldown, commands.errors.CommandOnCooldown)
    ):
        m, s = divmod(error.retry_after, 60)
        h, m = divmod(m, 60)

        msg = "This command cannot be used again for {} minutes and {} seconds".format(
            round(m), round(s)
        )

        embed = discord.Embed(
            title="Command On Cooldown", description=msg, color=discord.Color.red()
        )
        return await ctx.send(embed=embed)

    else:
        error_file = Path("error.txt")
        error_file.touch()
        with error_file.open("w") as f:
            f.write(exception_msg)
        embed = discord.Embed(
            title="Error Detected!",
            description="Seems like I've ran into an unexpected error!",
            color=Colors.red,
        )
        embed.add_field(
            name="Error Message",
            value=f"Check the console for more information.",
        )
        embed.set_thumbnail(url=bot.user.avatar.url)
        embed.set_footer(text=f"Error: {str(error)}")
        await ctx.send(embed=embed)
    raise error


async def on_command_(bot: BotObject, ctx: commands.Context):
    return
    # if you want to enforce slash commands only, uncomment the return statement above
    if ctx.command.name in ["sync", "ping", "kill", "jsk", "py"]:
        return

    await ctx.reply(
        f":x: This command usage is deprecated. Use the equivalent slash command by using `/{ctx.command.name}` instead."
    )


async def main_mode_check_(ctx: commands.Context) -> bool:
    """MT = discord.utils.get(ctx.guild.roles, name="Moderator")
    VP = discord.utils.get(ctx.guild.roles, name="VP")
    CO = discord.utils.get(ctx.guild.roles, name="CO")
    SS = discord.utils.get(ctx.guild.roles, name="Secret Service")"""
    CI_query: database.CheckInformation = database.CheckInformation.select().where(database.CheckInformation.id == 1).get()

    blacklisted_users = []
    db_blacklist: collections.Iterable = database.Blacklist
    for p in db_blacklist:
        blacklisted_users.append(p.discordID)

    admins = []
    query = database.Administrators.select().where(
        database.Administrators.TierLevel == 4
    )
    for admin in query:
        admins.append(admin.discordID)

    # Permit 4 Check
    if ctx.author.id in admins:
        return True

    # Maintenance Check
    elif CI_query.maintenance_mode:
        embed = discord.Embed(
            title="Master Maintenance ENABLED",
            description=f"❌ The bot is currently unavailable as it is under maintenance, check back later!",
            color=discord.Colour.gold(),
        )
        embed.set_footer(
            text="Message the bot owner for more information!"
        )
        await ctx.send(embed=embed)

        return False

    # Blacklist Check
    elif ctx.author.id in blacklisted_users:
        return False

    # DM Check
    elif ctx.guild is None:
        return CI_query.no_guild

    # Else...
    else:
        return CI_query.else_situation


def initialize_database(bot):
    """
    Initializes the database, and creates the needed table data if they don't exist.
    """
    database.db.connect(reuse_if_open=True)
    CIQ = database.CheckInformation.select().where(database.CheckInformation.id == 1)

    if not CIQ.exists():
        database.CheckInformation.create(
            maintenance_mode=False,
            no_guild=False,
            else_situation=True,
            persistent_change=False,
        )
        _log.info("Created CheckInformation Entry.")

    if len(database.Administrators) == 0:
        for person in bot.owner_ids:
            database.Administrators.create(discordID=person, TierLevel=4)
            _log.info("Created Administrator Entry.")

    query: database.CheckInformation = (
        database.CheckInformation.select()
        .where(database.CheckInformation.id == 1)
        .get()
    )
    query.persistent_change = False
    query.save()
    database.db.close()



