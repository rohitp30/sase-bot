import asyncio
import re
from datetime import datetime, timedelta
from typing import Optional, List

import discord
from discord import app_commands
from discord.ext import commands, tasks

import pytz
from dateutil import parser as dateparser

from core import database
from core.database import Reminder
from core.logging_module import get_log

_log = get_log(__name__)

MAX_RELATIVE_SECONDS = 14 * 24 * 3600  # 14 days
MIN_SECONDS = 60                       # At least 1 minute
DISPATCH_INTERVAL = 30                 # Seconds between polling

# Fixed channel where reminders are posted
event_reminder_ch = 1376018418926485529

# Force using Eastern time zone for all absolute times / display
DEFAULT_TZ = "America/New_York"


# ------------- Helper Functions -------------

DURATION_PATTERN = re.compile(
    r"^(?:(?P<days>\d+)d)?(?:(?P<hours>\d+)h)?(?:(?P<minutes>\d+)m)?(?:(?P<seconds>\d+)s)?$",
    re.IGNORECASE,
)

REPEAT_KEYWORDS = {
    "hourly": 3600,
    "daily": 86400,
    "weekly": 7 * 86400,
}


def parse_duration(duration_str: str) -> Optional[int]:
    """Parse a relative duration like '1d2h30m15s' into total seconds."""
    duration_str = duration_str.strip().lower()
    if duration_str in REPEAT_KEYWORDS:
        return REPEAT_KEYWORDS[duration_str]

    m = DURATION_PATTERN.match(duration_str)
    if not m:
        return None

    days = int(m.group("days")) if m.group("days") else 0
    hours = int(m.group("hours")) if m.group("hours") else 0
    minutes = int(m.group("minutes")) if m.group("minutes") else 0
    seconds = int(m.group("seconds")) if m.group("seconds") else 0

    total = days * 86400 + hours * 3600 + minutes * 60 + seconds
    return total if total > 0 else None


def _input_has_date(dt_str: str) -> bool:
    """
    Heuristic to detect whether the user's input includes a date component.
    Returns True if the string likely contains a date (day/month/year or month name).
    """
    s = dt_str.strip().lower()
    # Year like 2025, numeric date like 11/10 or 11-10 or month names (jan, feb, etc.)
    if re.search(r"\b\d{4}\b", s):
        return True
    if re.search(r"\b\d{1,2}[\/\-]\d{1,2}\b", s):
        return True
    if re.search(r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)\b", s):
        return True
    return False


def parse_absolute_datetime(dt_str: str, tz_str: Optional[str]) -> Optional[datetime]:
    """
    Parse an absolute date/time string and attach the forced timezone (Eastern).
    Accepts 12-hour inputs with AM/PM (e.g. "2:30 PM", "Nov 10 2025 2:30pm").
    If the user provides only a time (no date), interpret it in DEFAULT_TZ and if that
    time for today already passed, schedule it for the next day.

    Returns UTC datetime.
    """
    try:
        s = dt_str.strip()
        if not s:
            return None

        # detect whether user provided a date component; if not, we'll treat input as time-only
        has_date = _input_has_date(s)

        # Use dateutil.parser to parse. If time-only, default date is today (UTC naive) —
        # we'll interpret that date as being in DEFAULT_TZ below.
        # Provide default to fill missing fields (use current UTC date/time as baseline)
        default_dt = datetime.utcnow()
        dt = dateparser.parse(s, default=default_dt)

        if not dt:
            return None

        # Force timezone to DEFAULT_TZ (America/New_York)
        try:
            tz = pytz.timezone(tz_str or DEFAULT_TZ)
        except Exception:
            return None

        if dt.tzinfo is None:
            # Interpret naive datetime as being in the forced timezone
            dt = tz.localize(dt)
        else:
            # Convert aware datetimes into the forced timezone first
            dt = dt.astimezone(tz)

        # If the user provided only a time (no date), and the parsed time (today in DEFAULT_TZ)
        # is in the past (or too close), move it to next day so user gets the next occurrence.
        now_utc = datetime.utcnow().replace(tzinfo=pytz.UTC)
        parsed_utc = dt.astimezone(pytz.UTC)
        if not has_date:
            # If parsed time (today) is <= now + MIN_SECONDS, schedule for next day
            if parsed_utc <= now_utc + timedelta(seconds=MIN_SECONDS):
                dt = dt + timedelta(days=1)
                parsed_utc = dt.astimezone(pytz.UTC)

        return parsed_utc
    except Exception:
        return None


def parse_repeat(repeat_str: Optional[str]) -> Optional[int]:
    """
    Parse recurrence string:
        - Keywords: daily, weekly, hourly
        - Pattern: '1d2h', '30m', '2h15m10s'
    Returns interval seconds or None.
    """
    if not repeat_str:
        return None
    repeat_str = repeat_str.strip().lower()
    if repeat_str in REPEAT_KEYWORDS:
        return REPEAT_KEYWORDS[repeat_str]
    return parse_duration(repeat_str)


def humanize_seconds(seconds: int) -> str:
    parts = []
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    if d:
        parts.append(f"{d}d")
    if h:
        parts.append(f"{h}h")
    if m:
        parts.append(f"{m}m")
    if s and not parts:
        # Only show seconds if under a minute or no other component
        parts.append(f"{s}s")
    return " ".join(parts) if parts else f"{seconds}s"


# ------------- Cog -------------

class ReminderCog(commands.Cog):
    """
    Reminder management cog with slash commands:
    /reminder create
    /reminder list
    /reminder cancel
    /reminder snooze
    /reminder help

    All stored times normalized to UTC. Timezone is forced to US/Eastern (America/New_York).
    """

    reminder_group = app_commands.Group(
        name="reminder",
        description="Reminder commands",
        guild_ids=[1376018416934322176],  # adjust or remove to register globally
    )

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.dispatch_loop.start()

    def cog_unload(self):
        self.dispatch_loop.cancel()

    # ---------- HELP COMMAND ----------
    @reminder_group.command(name="help", description="Show help for reminder commands.")
    async def help_cmd(self, interaction: discord.Interaction):
        """Sends an embed explaining how to use the reminder commands."""
        await interaction.response.defer(ephemeral=False)
        embed = discord.Embed(
            title="Reminder Command Help",
            color=discord.Color.blurple(),
            description=(
                "create one-off or recurring reminders. explicit times are interpreted as EST timezone "
                f"({DEFAULT_TZ}) and stored internally in UTC. Relative durations use the format `1d2h30m`.\n\n"
                "Examples and notes are below."
            ),
        )

        embed.add_field(
            name="Create (relative)",
            value=(
                "`/reminder create when:2h30m message:Stand up and stretch`\n"
                "-> Sets a reminder 2 hours 30 minutes from now."
            ),
            inline=False,
        )

        embed.add_field(
            name="Create (absolute, 12-hour supported)",
            value=(
                "`/reminder create when:\"Nov 12 2025 2:30 PM\" message:Meeting`\n"
                "-> Interprets `2:30 PM` in EST timezone on Nov 12 2025. "
                "If you only provide a time (e.g. `2:30 PM`), it's scheduled for the next occurrence of that time."
            ),
            inline=False,
        )

        embed.add_field(
            name="Recurring reminders",
            value=(
                "`/reminder create when:10m message:Hydrate repeat:daily`\n"
                "-> First triggers in 10 minutes, then repeats every day. You can use `hourly`, `daily`, `weekly` "
                "or `1d2h`, `30m` patterns for `repeat`.\n"
                "Use `repeat_count` to limit occurrences (omit for infinite)."
            ),
            inline=False,
        )

        embed.add_field(
            name="Manage reminders",
            value=(
                "`/reminder list` — show your active reminders\n"
                "`/reminder cancel <id>` — cancel a reminder\n"
                "`/reminder snooze <id> <duration>` — push the next trigger by a relative duration (e.g. `10m`)"
            ),
            inline=False,
        )

        embed.set_footer(
            text=(
                "Notes: Relative max is 14 days. Minimum delay is 1 minute. "
                "Times shown in embeds use Discord's timestamp shorthand and reflect UTC storage."
            )
        )

        await interaction.followup.send(embed=embed, ephemeral=True)

    # ---------- CREATE COMMAND ----------

    @reminder_group.command(name="create", description="Create a new reminder.")
    @app_commands.describe(
        when="Either relative (e.g. 2h30m) or absolute date/time (interpreted as US/Eastern, e.g. 2025-11-12 2:30 PM).",
        message="Reminder message to send when due.",
        repeat="Optional recurrence interval (e.g. daily, weekly, 2d3h).",
        repeat_count="Number of times to fire (omit for infinite recurrence).",
    )
    async def create(
        self,
        interaction: discord.Interaction,
        when: str,
        message: str,
        repeat: Optional[str] = None,
        repeat_count: Optional[int] = None,
    ):
        await interaction.response.defer(ephemeral=True)

        # Decide whether it's relative or absolute
        relative_seconds = parse_duration(when)
        due_utc: Optional[datetime] = None

        if relative_seconds:
            if relative_seconds > MAX_RELATIVE_SECONDS:
                return await interaction.followup.send(
                    f"Maximum relative time is {humanize_seconds(MAX_RELATIVE_SECONDS)}.", ephemeral=True
                )
            if relative_seconds < MIN_SECONDS:
                return await interaction.followup.send(
                    "Minimum relative time is 1 minute.", ephemeral=True
                )
            due_utc = datetime.utcnow() + timedelta(seconds=relative_seconds)
            used_mode = "relative"
        else:
            # Try absolute parse (force US/Eastern)
            due_utc = parse_absolute_datetime(when, DEFAULT_TZ)
            if not due_utc:
                return await interaction.followup.send(
                    "Failed to parse 'when'. Provide relative (e.g. 2h30m) or an absolute date/time (12-hour AM/PM supported).",
                    ephemeral=True,
                )
            if (due_utc - datetime.utcnow()).total_seconds() < MIN_SECONDS:
                return await interaction.followup.send(
                    "Absolute time must be at least 1 minute in the future.",
                    ephemeral=True,
                )
            if (due_utc - datetime.utcnow()).total_seconds() > MAX_RELATIVE_SECONDS and not repeat:
                return await interaction.followup.send(
                    f"Absolute one-off reminders limited to {humanize_seconds(MAX_RELATIVE_SECONDS)} ahead.",
                    ephemeral=True,
                )
            used_mode = "absolute"

        # Recurrence parsing
        interval_seconds = parse_repeat(repeat) if repeat else None
        is_recurring = interval_seconds is not None

        if is_recurring and interval_seconds < MIN_SECONDS:
            return await interaction.followup.send(
                "Recurrence interval must be >= 1 minute.",
                ephemeral=True,
            )

        if repeat_count is not None and repeat_count <= 0:
            return await interaction.followup.send(
                "repeat_count must be a positive integer.",
                ephemeral=True,
            )

        # Store reminder (timezone forced to DEFAULT_TZ)
        database.db.connect(reuse_if_open=True)
        reminder = Reminder.create(
            user_id=interaction.user.id,
            content=message,
            due_at=due_utc,
            timezone=DEFAULT_TZ,
            is_recurring=is_recurring,
            interval_seconds=interval_seconds,
            occurrences_left=repeat_count,
            active=True,
        )
        reminder.save()
        database.db.close()

        next_str = f"<t:{int(reminder.due_at.timestamp())}:R>"
        recur_str = ""
        if is_recurring:
            oc = "∞" if reminder.occurrences_left is None else str(reminder.occurrences_left)
            recur_str = f"\nRecurring every {humanize_seconds(interval_seconds)} (remaining: {oc})."

        embed = discord.Embed(
            title="Reminder Created",
            description=(
                f"Mode: {used_mode}\n"
                f"Message: {message}\n"
                f"Timezone: {DEFAULT_TZ}\n"
                f"Due: {next_str}{recur_str}"
            ),
            color=discord.Color.blurple(),
        )
        embed.add_field(name="Reminder ID", value=f"{str(reminder.id)} (use this ID to manage this reminder)")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ---------- LIST COMMAND ----------

    @reminder_group.command(name="list", description="List your active reminders.")
    async def list_reminders(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        database.db.connect(reuse_if_open=True)
        q = (
            Reminder.select()
            .where((Reminder.user_id == interaction.user.id) & (Reminder.active == True))
            .order_by(Reminder.due_at.asc())
        )
        rows: List[Reminder] = list(q)
        database.db.close()

        if not rows:
            return await interaction.followup.send("You have no active reminders.", ephemeral=True)

        lines = []
        for r in rows:
            mode = "R" if r.is_recurring else "1x"
            due_rel = f"<t:{int(r.due_at.timestamp())}:R>"
            tz_disp = r.timezone or DEFAULT_TZ
            occ = "∞" if (r.is_recurring and r.occurrences_left is None) else (
                str(r.occurrences_left) if r.is_recurring else "-"
            )
            lines.append(
                f"ID `{r.id}` | {mode} | Due {due_rel} | TZ {tz_disp} | Left: {occ}\n> {r.content}"
            )

        embed = discord.Embed(
            title="Your Reminders",
            description="\n".join(lines),
            color=discord.Color.gold(),
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ---------- CANCEL COMMAND ----------

    @reminder_group.command(name="cancel", description="Cancel a reminder by ID.")
    @app_commands.describe(reminder_id="The ID of the reminder to cancel.")
    async def cancel(self, interaction: discord.Interaction, reminder_id: int):
        await interaction.response.defer(ephemeral=True)
        database.db.connect(reuse_if_open=True)
        try:
            r: Reminder = Reminder.get(Reminder.id == reminder_id)
        except Exception:
            database.db.close()
            return await interaction.followup.send("Reminder not found.", ephemeral=True)

        if r.user_id != interaction.user.id:
            database.db.close()
            return await interaction.followup.send("You do not own that reminder.", ephemeral=True)

        r.active = False
        r.save()
        database.db.close()

        await interaction.followup.send(f"Reminder `{reminder_id}` canceled.", ephemeral=True)

    # ---------- SNOOZE COMMAND ----------

    @reminder_group.command(name="snooze", description="Snooze a reminder by ID with a relative duration.")
    @app_commands.describe(
        reminder_id="Reminder ID to snooze.",
        duration="Relative duration (e.g. 10m, 2h, 1d30m).",
    )
    async def snooze(self, interaction: discord.Interaction, reminder_id: int, duration: str):
        await interaction.response.defer(ephemeral=True)
        seconds = parse_duration(duration)
        if not seconds or seconds < MIN_SECONDS:
            return await interaction.followup.send("Invalid snooze duration (>=1m).", ephemeral=True)
        if seconds > MAX_RELATIVE_SECONDS:
            return await interaction.followup.send("Snooze exceeds maximum of 14 days.", ephemeral=True)

        database.db.connect(reuse_if_open=True)
        try:
            r: Reminder = Reminder.get(Reminder.id == reminder_id)
        except Exception:
            database.db.close()
            return await interaction.followup.send("Reminder not found.", ephemeral=True)

        if r.user_id != interaction.user.id:
            database.db.close()
            return await interaction.followup.send("You do not own that reminder.", ephemeral=True)

        # Adjust next due only
        r.due_at = datetime.utcnow() + timedelta(seconds=seconds)
        r.save()
        database.db.close()

        await interaction.followup.send(
            f"Reminder `{reminder_id}` snoozed until <t:{int(r.due_at.timestamp())}:R>.",
            ephemeral=True,
        )

    # ---------- INTERNAL DISPATCH LOOP ----------

    @tasks.loop(seconds=DISPATCH_INTERVAL)
    async def dispatch_loop(self):
        """
        Poll due reminders and dispatch them.
        - For one-off: mark inactive after sending.
        - For recurring: decrement occurrences_left if finite; reschedule next due.
        """
        now = datetime.utcnow()
        database.db.connect(reuse_if_open=True)

        due_query = (
            Reminder.select()
            .where(
                (Reminder.active == True)
                & (Reminder.due_at <= now)
            )
        )

        reminders_to_process: List[Reminder] = list(due_query)
        database.db.close()

        if not reminders_to_process:
            return

        for r in reminders_to_process:
            try:
                # Always post to the configured event channel
                send_target = self.bot.get_channel(event_reminder_ch)

                if send_target is None:
                    _log.warning(f"Reminder {r.id}: Unable to resolve target; skipping send.")
                else:
                    anchor = f"<@{r.user_id}>"
                    header = "⏰ Reminder" if not r.is_recurring else "🔁 Recurring Reminder"
                    embed = discord.Embed(
                        title=header,
                        description=r.content,
                        color=discord.Color.green(),
                    )
                    embed.set_footer(text=f"ID {r.id} • Timezone: {r.timezone or DEFAULT_TZ}")
                    # Attempt send
                    try:
                        await send_target.send(f"{anchor}", embed=embed)
                    except Exception as e:
                        _log.error(f"Failed sending reminder {r.id}: {e}")

                # Update DB state
                database.db.connect(reuse_if_open=True)
                r.last_sent_at = datetime.utcnow()
                if r.is_recurring:
                    # Handle occurrences
                    if r.occurrences_left is not None:
                        r.occurrences_left -= 1
                        if r.occurrences_left <= 0:
                            r.active = False
                            r.save()
                            database.db.close()
                            continue
                    # Reschedule by adding fixed interval (UTC)
                    r.due_at = r.due_at + timedelta(seconds=r.interval_seconds)
                    r.save()
                else:
                    r.active = False
                    r.save()
                database.db.close()

            except Exception as e:
                _log.exception(f"Unexpected error processing reminder {r.id}: {e}")

    @dispatch_loop.before_loop
    async def before_dispatch(self):
        await self.bot.wait_until_ready()
        _log.info("Reminder dispatch loop started.")


async def setup(bot: commands.Bot):
    await bot.add_cog(ReminderCog(bot))