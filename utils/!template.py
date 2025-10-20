from discord.ext import commands


class COGNAME(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # add your cog methods and commands here

async def setup(bot):
    await bot.add_cog(COGNAME(bot))