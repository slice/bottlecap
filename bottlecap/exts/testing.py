from lifesaver.bot import Cog, command, Context


class Testing(Cog):
    @command()
    async def owo(self, ctx: Context):
        """owo"""
        await ctx.send('owo')


def setup(bot):
    bot.add_cog(Testing(bot))
