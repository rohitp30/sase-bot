import os
from datetime import datetime

from dotenv import load_dotenv
from flask import Flask
from peewee import (
    AutoField,
    BigIntegerField,
    BooleanField,
    DateTimeField,
    IntegerField,
    Model,
    MySQLDatabase,
    SqliteDatabase,
    TextField,
)

from core.logging_module import get_log

load_dotenv()
_log = get_log(__name__)

"""
Change to a SqliteDatabase if you don't have any MySQL Credentials.
If you do switch, comment/remove the MySQLDatabase variable and uncomment/remove the # from the SqliteDatabase instance. 
"""

if os.getenv("DATABASE_IP") is None:
    db = SqliteDatabase("data.db")
    _log.info("No Database IP found in .env file, using SQLite!")

elif os.getenv("DATABASE_IP") is not None:
    try:
        db = MySQLDatabase(
            os.getenv("DATABASE_COLLECTION"),
            user=os.getenv("DATABASE_USERNAME"),
            password=os.getenv("DATABASE_PASSWORD"),
            host=os.getenv("DATABASE_IP"),
            port=int(os.getenv("DATABASE_PORT")),
        )
        _log.info("Successfully connected to the MySQL Database")
    except Exception as e:
        _log.warning(
            f"Unable to connect to the MySQL Database:\n    > {e}\n\nSwitching to SQLite..."
        )
        db = SqliteDatabase("data.db")


def iter_table(model_dict: dict):
    """Iterates through a dictionary of tables, confirming they exist and creating them if necessary."""
    for key in model_dict:
        if not db.table_exists(key):
            db.connect(reuse_if_open=True)
            db.create_tables([model_dict[key]])
            db.close()
        else:
            db.connect(reuse_if_open=True)
            for column in model_dict[key]._meta.sorted_fields:
                if not db.column_exists(key, column.name):
                    db.create_column(key, column.name)
            db.close()


"""
DATABASE FILES

This file represents every database table and the model they follow. 
When fetching information from the tables, consult the typehints for possible methods!
"""


class BaseModel(Model):
    """Base Model class used for creating new tables."""

    class Meta:
        database = db


class Administrators(BaseModel):
    """
    Administrators:
    List of users who are whitelisted on the bot.

    `id`: AutoField()
    Database Entry

    `discordID`: BigIntegerField()
    Discord ID

    `TierLevel`: IntegerField()
    TIER LEVEL

    1 - Basic Mod
    2 - Moderator
    3 - Administrator
    4 - Owner
    """

    id = AutoField()
    discordID = BigIntegerField(unique=True)
    TierLevel = IntegerField(default=1)


class AdminLogging(BaseModel):
    """
    # AdminLogging:
    Local logs for high privileged commands.

    `id`: AutoField()
    Database Entry

    `discordID`: BigIntegerField()
    Discord ID

    `action`: TextField()
    Command Name

    `content`: TextField()
    `*args` passed in

    `datetime`: DateTimeField()
    DateTime Object when the command was executed.
    """

    id = AutoField()
    discordID = BigIntegerField()
    action = TextField()
    content = TextField(default="N/A")
    datetime = DateTimeField(default=datetime.now())


class Blacklist(BaseModel):
    """
    # Blacklist:
    List of users who are blacklisted on the bot.

    `id`: AutoField()
    Database Entry

    `discordID`: BigIntegerField()
    Discord ID
    """

    id = AutoField()
    discordID = BigIntegerField(unique=True)


class BaseQueue(BaseModel):
    """
    #BaseQueue
    Not used but a boilerplate for any basic events you may need.

    `id`: AutoField()
    Database Entry

    `queue_id`: BigIntegerField()
    Type of queue.
    """

    id = AutoField()
    queue_id = BigIntegerField()


class CommandAnalytics(BaseModel):
    """
    #CommandAnalytics
    Analytics for commands.

    `id`: AutoField()
    Database Entry ID

    `command`: TextField()
    The command that was used.

    `user`: IntegerField()
    The user that used the command.

    `date`: DateTimeField()
    The date when the command was used.

    `command_type`: TextField()
    The type of command that was used.

    `guild_id`: BigIntegerField()
    The guild ID of the guild that the command was used in.
    """

    id = AutoField()
    command = TextField()
    date = DateTimeField()
    command_type = TextField()
    guild_id = BigIntegerField()
    user = BigIntegerField()


class CheckInformation(BaseModel):
    """
    # CheckInformation:
    Information about the bot's checks.

    `id`: AutoField()
    Database Entry

    `maintenance_mode`: BooleanField()
    Ultimate Check; If this is enabled no one except Permit 4+ users are allowed to use the bot.
    '>>> **NOTE:** This attribute must always have a bypass to prevent lockouts, otherwise this check will ALWAYS return False.

    `no_guild`: BooleanField()
    If commands executed outside of guilds (DMs) are allowed.

    `else_situation`: BooleanField()
    Other situations will be defaulted to/as ...

    `persistent_change`: BooleanField()
    If the bot has added its persistent buttons/views.
    """

    id = AutoField()
    maintenance_mode = BooleanField()
    no_guild = BooleanField()
    else_situation = BooleanField()
    persistent_change = BooleanField()


app = Flask(__name__)


@app.before_request
def _db_connect():
    """
    This hook ensures that a connection is opened to handle any queries
    generated by the request.
    """
    db.connect()


@app.teardown_request
def _db_close(exc):
    """
    This hook ensures that the connection is closed when we've finished
    processing the request.
    """
    if not db.is_closed():
        db.close()


tables = {
    "Administrators": Administrators,
    "AdminLogging": AdminLogging,
    "Blacklist": Blacklist,
    "BaseQueue": BaseQueue,
    "CommandAnalytics": CommandAnalytics,
    "CheckInformation": CheckInformation,
}

"""
This function automatically adds tables to the database if they do not exist,
however it does take a significant amount of time to run so the env variable 'ITER_TABLES' should be 'False'
in development. 
"""
if os.getenv("ITER_TABLES") == "True":
    iter_table(tables)