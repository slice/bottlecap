import logging
import time

import asyncio
from typing import Union, List, Dict, Any, Optional

import aiohttp
import discord
from lifesaver.bot import Cog, command, Context, group
from lifesaver.bot.storage import AsyncJSONStorage
from dataclasses import dataclass

log = logging.getLogger(__name__)

PLAY_DESCRIPTION = """Mapped by {beatmap.creator}  ({stars:.1f}*, {beatmap.bpm} BPM)
{play.rank}  {play.score}  (x{play.maxcombo})

{play.count300}x300  {play.count100}x100  {play.count50}x50  {play.countmiss}xMiss
"""


@dataclass
class OsuPlay:
    user_id: str
    beatmap_id: str
    score: str
    maxcombo: str
    count50: str
    count100: str
    count300: str
    countmiss: str
    countkatu: str
    countgeki: str
    perfect: str
    enabled_mods: str
    date: str
    rank: str
    pp: str = '0'


@dataclass
class OsuBeatmap:
    beatmapset_id: str
    beatmap_id: str
    approved: str
    total_length: str
    hit_length: str
    version: str
    file_md5: str
    diff_size: str
    diff_overall: str
    diff_approach: str
    diff_drain: str
    mode: str
    approved_date: str
    last_update: str
    artist: str
    title: str
    creator: str
    bpm: str
    source: str
    tags: str
    genre_id: str
    language_id: str
    favourite_count: str
    playcount: str
    passcount: str
    max_combo: str
    difficultyrating: str


class Osu(Cog):
    wait_interval: int = 10

    def __init__(self, bot):
        super().__init__(bot)
        self.tracking = AsyncJSONStorage('osu.json', loop=bot.loop)
        self.track_task = bot.loop.create_task(self.poll())
        self.session = aiohttp.ClientSession(headers={
            'user-agent': 'bottlecap/0.0.0'
        })

    def __unload(self):
        self.session.close()
        self.track_task.cancel()

    def endpoint(self, url: str) -> str:
        return f'https://osu.ppy.sh/api{url}'

    async def get_recent_plays(self, user_id: Union[int, str], *, limit: int = 10) -> List[OsuPlay]:
        params = {'k': self.bot.cfg.osu_api_key, 'u': user_id, 'limit': limit}
        async with self.session.get(self.endpoint('/get_user_recent'), params=params) as resp:
            resp.raise_for_status()
            plays = await resp.json()
            return [OsuPlay(**play) for play in plays]

    async def get_top_plays(self, user_id: Union[int, str], *, limit: int = 10) -> List[OsuPlay]:
        params = {'k': self.bot.cfg.osu_api_key, 'u': user_id, 'limit': limit}
        async with self.session.get(self.endpoint('/get_user_best'), params=params) as resp:
            plays = await resp.json()
            return [OsuPlay(**play) for play in plays]

    async def get_beatmap(self, beatmap_id: str) -> OsuBeatmap:
        params = {'k': self.bot.cfg.osu_api_key, 'b': beatmap_id}
        async with self.session.get(self.endpoint('/get_beatmaps'), params=params) as resp:
            resp.raise_for_status()
            beatmaps = await resp.json()
            return OsuBeatmap(**beatmaps[0])

    async def alert_play(self, user_id: int, info: Dict[str, Any], play: OsuPlay):
        log.debug('Attempting to alert %d about recent play: %s.', user_id, play)
        last_tracked = info.get('last_tracked')

        if play.date == last_tracked:
            log.debug('Detected a stale play for %d (%s).', user_id, play.date)
            return

        await self.tracking.put(
            user_id,
            {**info, 'last_tracked': play.date}
        )

        if play.rank == 'F':
            log.debug('Detected failed play, not tracking.')
            return

        log.debug('Tracking this play. (%s)', play)

        beatmap = await self.get_beatmap(play.beatmap_id)
        stars = float(beatmap.difficultyrating)
        user = self.bot.get_user(user_id)

        embed = discord.Embed()
        embed.title = f'{beatmap.artist} - {beatmap.title} [{beatmap.version}]'
        embed.url = f'https://osu.ppy.sh/b/{play.beatmap_id}'
        embed.set_author(name=f"{info['osu_username']} ({user})", url=f'https://osu.ppy.sh/u/{play.user_id}')
        embed.description = PLAY_DESCRIPTION.format(play=play, player=user_id, beatmap=beatmap, stars=stars)

        top_plays = await self.get_top_plays(play.user_id)
        log.debug('Top plays for %d: %s', user_id, top_plays)
        as_top_play: Optional[OsuPlay] = discord.utils.get(top_plays, date=play.date)
        log.debug('Current play date: %s, detected top play: %s', play.date, as_top_play)

        channel = self.bot.get_channel(info['channel_id'])
        if not channel:
            log.warning('Cannot locate channel %d, not alerting.', info['channel_id'])
            return

        try:
            if as_top_play:
                log.debug('Using top play PP score (%s).', as_top_play.pp)
                content = f'<@{user_id}> **+{as_top_play.pp} PP'
            else:
                content = ''
            log.debug('Alerting %d in %d.', user_id, info['channel_id'])
            await channel.send(embed=embed, content=content)
        except discord.Forbidden:
            pass

    async def poll(self):
        while True:
            for user_id, info in self.tracking.all().items():
                user_id = int(user_id)
                plays = await self.get_recent_plays(info['osu_username'], limit=1)
                if not plays:
                    log.warning('Found NO plays for %s.', info['osu_username'])
                    continue
                await self.alert_play(user_id, info, plays[0])
            await asyncio.sleep(self.wait_interval)

    @group(invoke_without_command=True)
    async def track(self, ctx: Context, username):
        """tracks you on osu"""
        log.info('Now tracking %d (%s).', ctx.author.id, username)
        await self.tracking.put(ctx.author.id, {
            'channel_id': ctx.channel.id,
            'osu_username': username,
            'created_at': time.time(),
            'guild_id': ctx.guild.id
        })
        await ctx.send('okay, tracking you here')

    @track.command(hidden=True)
    async def reset(self, ctx: Context, who: discord.User = None):
        """resets your tracking status"""
        target = who or ctx.author
        record = self.tracking.get(target.id)

        if not record:
            return

        try:
            del record['last_tracked']
        except KeyError:
            return

        await self.tracking.put(target.id, record)
        await ctx.send(f"ok, reset {target}'s tracking state.")

    @command()
    async def untrack(self, ctx: Context):
        """untracks you on osu"""
        log.info('Untracking %d.', ctx.author.id)
        try:
            await self.tracking.delete(ctx.author.id)
        except KeyError:
            pass
        await ctx.ok()


def setup(bot):
    bot.add_cog(Osu(bot))
