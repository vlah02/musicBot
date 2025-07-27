import discord
from discord.ext import commands
import os
import asyncio
import yt_dlp
import lyricsgenius
from dotenv import load_dotenv
import urllib.parse
import urllib.request
import re
import datetime
import random

def make_progress_bar(elapsed: float, total: float, length: int = 20) -> str:
    """Return a text bar like '████░░░░░ 01:23/03:45'"""
    filled = int(elapsed / total * length)
    empty = length - filled
    bar = "█" * filled + "░" * empty

    def fmt(sec: float) -> str:
        m, s = divmod(int(sec), 60)
        return f"{m:02}:{s:02}"

    return f"{bar} {fmt(elapsed)}/{fmt(total)}"

def run_bot():
    load_dotenv()
    DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
    GENIUS_TOKEN  = os.getenv("GENIUS_TOKEN")
    ROLE_NAME     = "DJ"
    RESTRICTED_UID= 123456789012345678

    intents = discord.Intents.default()
    intents.message_content = True
    intents.voice_states    = True
    client = commands.Bot(command_prefix="!", intents=intents)

    queues           = {}  # guild_id -> list[song]
    voice_clients    = {}  # guild_id -> VoiceClient
    current_song     = {}  # guild_id -> song
    song_start_times = {}  # guild_id -> datetime
    loop_status      = {}  # guild_id -> bool
    last_np_message  = {}  # guild_id -> message_id

    youtube_base_url    = "https://www.youtube.com/"
    youtube_results_url = youtube_base_url + "results?"
    youtube_watch_url   = youtube_base_url + "watch?v="

    yt_dl_opts = {
        "format": "bestaudio/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
    }
    ytdl   = yt_dlp.YoutubeDL(yt_dl_opts)
    genius = lyricsgenius.Genius(GENIUS_TOKEN)

    ffmpeg_opts = {
        "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
        "options"       : '-vn -filter:a "volume=0.25"',
    }

    @client.event
    async def on_ready():
        print(f"{client.user} is now jamming")

    @client.event
    async def on_voice_state_update(member, before, after):
        if member == client.user and before.channel and not after.channel:
            gid = before.channel.guild.id
            vc = voice_clients.pop(gid, None)
            if vc:
                vc.stop()
            current_song.pop(gid, None)
            song_start_times.pop(gid, None)

    @client.event
    async def on_command_error(ctx, error):
        if isinstance(error, commands.MissingRole):
            await ctx.send(embed=discord.Embed(
                title="Access Denied",
                description="🚫 You need the **DJ** role to use that command.",
                color=discord.Color.red()
            ))
        else:
            raise error

    @client.event
    async def on_reaction_add(reaction: discord.Reaction, user: discord.User):
        if user.bot:
            return

        msg = reaction.message
        if msg.author != client.user or not msg.embeds:
            return
        embed = msg.embeds[0]
        if embed.title != "Now Playing" or reaction.emoji not in ("⏸️","▶️","➡️"):
            return

        gid = msg.guild.id
        vc  = voice_clients.get(gid)
        if not vc:
            try:
                await msg.remove_reaction(reaction.emoji, user)
            except (discord.Forbidden, discord.NotFound):
                pass
            return

        if reaction.emoji == "⏸️":
            vc.pause()
            await msg.channel.send("⏸️ Paused playback.")
        elif reaction.emoji == "▶️":
            vc.resume()
            await msg.channel.send("▶️ Resumed playback.")
        else:  # ➡️ skip
            vc.stop()
            await msg.channel.send("➡️ Skipped current song.")
            # delete this old embed so it can't be used again
            try:
                await msg.delete()
            except (discord.Forbidden, discord.NotFound):
                pass
            return  # stop here so we don't try to remove reactions on deleted message

        # if pause/play, clear the reaction
        try:
            await msg.remove_reaction(reaction.emoji, user)
        except (discord.Forbidden, discord.NotFound):
            pass

    async def play_song(ctx, song):
        try:
            data = await asyncio.get_event_loop().run_in_executor(
                None, lambda: ytdl.extract_info(song["url"], download=False)
            )
        except Exception:
            return await ctx.send(embed=discord.Embed(
                title="Error",
                description="There was an error extracting video information.",
                color=discord.Color.red()
            ))

        player = discord.FFmpegOpusAudio(data["url"], **ffmpeg_opts)

        def after_play(err):
            vc = voice_clients.get(ctx.guild.id)
            if not vc or not vc.is_connected():
                return
            next_coro = (
                play_song(ctx, song)
                if loop_status.get(ctx.guild.id)
                else handle_queue(ctx)
            )
            asyncio.run_coroutine_threadsafe(next_coro, client.loop)

        voice_clients[ctx.guild.id].play(player, after=after_play)
        current_song[ctx.guild.id]     = song
        song_start_times[ctx.guild.id] = datetime.datetime.now()

        # before posting, delete previous NP embed if any
        prev = last_np_message.get(ctx.guild.id)
        if prev:
            try:
                old = await ctx.fetch_message(prev)
                await old.delete()
            except:
                pass

        embed = discord.Embed(title="Now Playing", color=discord.Color.green())
        embed.add_field(name="Title", value=f"[{song['title']}]({song['url']})", inline=False)
        embed.add_field(name="Duration", value=str(datetime.timedelta(seconds=song["duration"])), inline=False)
        embed.add_field(name="Requested by", value=song["user"], inline=False)
        embed.set_thumbnail(url=song["thumbnail"])
        msg = await ctx.send(embed=embed)
        for emoji in ("⏸️","▶️","➡️"):
            await msg.add_reaction(emoji)
        last_np_message[ctx.guild.id] = msg.id

    async def handle_queue(ctx):
        q = queues.get(ctx.guild.id)
        if q:
            next_song = q.pop(0)
            await play_song(ctx, next_song)
        else:
            await disconnect_bot(ctx)

    async def disconnect_bot(ctx):
        vc = voice_clients.pop(ctx.guild.id, None)
        if vc:
            await vc.disconnect()
        await ctx.send(embed=discord.Embed(
            title="Disconnected",
            description="Queue is empty. Bot disconnected.",
            color=discord.Color.red()
        ))

    @client.before_invoke
    async def pre_command_cleanup_and_check(ctx):
        try:
            await ctx.message.delete()
        except:
            pass

        if ctx.author.id == RESTRICTED_UID:
            await ctx.send(embed=discord.Embed(
                title="Access Denied",
                description="You are restricted from using this command.",
                color=discord.Color.red()
            ))
            raise commands.CheckFailure()

    @client.command(name="play", aliases=["p"])
    @commands.has_role(ROLE_NAME)
    async def play(ctx, *, link=None, user=None):
        queues.setdefault(ctx.guild.id, [])
        if not link:
            q = queues[ctx.guild.id]
            if q:
                vc = voice_clients.get(ctx.guild.id)
                if vc and vc.is_connected() and not vc.is_playing():
                    song = q.pop(0)
                    return await play_song(ctx, song)
                vc = await ctx.author.voice.channel.connect()
                voice_clients[ctx.guild.id] = vc
                song = q.pop(0)
                return await play_song(ctx, song)
            return await ctx.send(embed=discord.Embed(
                title="Queue", description="Queue is empty.", color=discord.Color.red()
            ))
        if "youtube.com" not in link:
            query = urllib.parse.urlencode({"search_query": link})
            html  = urllib.request.urlopen(youtube_results_url + query).read().decode()
            m     = re.search(r"/watch\?v=(.{11})", html)
            if m:
                link = youtube_watch_url + m.group(1)
        try:
            data = await asyncio.get_event_loop().run_in_executor(
                None, lambda: ytdl.extract_info(link, download=False)
            )
        except Exception:
            return await ctx.send(embed=discord.Embed(
                title="Error", description="Error extracting video info.", color=discord.Color.red()
            ))
        song = {
            "title": data["title"],
            "url": link,
            "duration": data["duration"],
            "thumbnail": data["thumbnail"],
            "user": user or ctx.author.display_name,
        }
        vc = voice_clients.get(ctx.guild.id)
        if vc and vc.is_connected():
            if vc.is_playing():
                queues[ctx.guild.id].append(song)
                return await ctx.send(embed=discord.Embed(
                    title="Added to Queue",
                    description=f"{song['title']} at position {len(queues[ctx.guild.id])}.",
                    color=discord.Color.blue()
                ))
            return await play_song(ctx, song)
        vc = await ctx.author.voice.channel.connect()
        voice_clients[ctx.guild.id] = vc
        await play_song(ctx, song)

    @client.command(name="search")
    @commands.has_role(ROLE_NAME)
    async def search(ctx, *, keywords):
        data = ytdl.extract_info(f"ytsearch5:{keywords}", download=False)
        entries = data.get("entries", [])
        if not entries:
            return await ctx.send("No results found.")

        lines = [
            f"{i}. [{e.get('title', 'Unknown')}]({e.get('webpage_url') or e.get('url') or (youtube_watch_url + e.get('id', ''))})"
            for i, e in enumerate(entries, start=1)
        ]
        em = discord.Embed(
            title=f"Results for “{keywords}”",
            description="\n".join(lines),
            color=discord.Color.gold()
        )
        msg = await ctx.send(embed=em)

        emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]
        for i in range(len(entries)):
            await msg.add_reaction(emojis[i])

        def check(r, u):
            return (
                    u == ctx.author
                    and r.message.id == msg.id
                    and r.emoji in emojis[:len(entries)]
            )

        try:
            reaction, user = await client.wait_for(
                "reaction_add", timeout=30.0, check=check
            )
        except asyncio.TimeoutError:
            return await ctx.send("❌ Selection timed out.")

        try:
            await msg.delete()
        except:
            pass

        idx = emojis.index(reaction.emoji)
        pick = entries[idx]
        pick_url = pick.get("webpage_url") or pick.get("url") or (
                youtube_watch_url + pick.get("id", "")
        )
        song = {
            "title": pick.get("title", "Unknown"),
            "url": pick_url,
            "duration": pick.get("duration", 0),
            "thumbnail": pick.get("thumbnail"),
            "user": ctx.author.display_name,
        }

        gid = ctx.guild.id
        vc = voice_clients.get(gid)
        q = queues.setdefault(gid, [])
        if vc and vc.is_connected() and vc.is_playing():
            q.append(song)
            return await ctx.send(f"✅ Queued **{song['title']}** at position {len(q)}.")
        vc = await ctx.author.voice.channel.connect()
        voice_clients[gid] = vc
        await play_song(ctx, song)

    @client.command(name="shuffle")
    @commands.has_role(ROLE_NAME)
    async def shuffle_cmd(ctx):
        q = queues.get(ctx.guild.id)
        if not q:
            return await ctx.send(embed=discord.Embed(
                title="Error", description="Queue is empty.", color=discord.Color.red()
            ))
        random.shuffle(q)
        await ctx.send(embed=discord.Embed(
            title="🔀 Shuffled", description="Queue randomized!", color=discord.Color.purple()
        ))

    @client.command(name="clear")
    @commands.has_role(ROLE_NAME)
    async def clear(ctx):
        if queues.get(ctx.guild.id):
            queues[ctx.guild.id].clear()
            return await ctx.send(embed=discord.Embed(
                title="Queue Cleared", description="Queue cleared!", color=discord.Color.orange()
            ))
        await ctx.send(embed=discord.Embed(
            title="Queue Error", description="No queue to clear.", color=discord.Color.red()
        ))

    @client.command(name="remove")
    @commands.has_role(ROLE_NAME)
    async def remove(ctx, position: int):
        q = queues.get(ctx.guild.id)
        if not q:
            return await ctx.send(embed=discord.Embed(
                title="Error", description="Queue is empty.", color=discord.Color.red()
            ))
        if position < 1 or position > len(q):
            return await ctx.send(embed=discord.Embed(
                title="Error", description=f"Position must be 1–{len(q)}.", color=discord.Color.red()
            ))
        song = q.pop(position - 1)
        await ctx.send(embed=discord.Embed(
            title="Removed", description=f"Removed **{song['title']}** from position {position}.",
            color=discord.Color.green()
        ))

    @client.command(name="pause")
    @commands.has_role(ROLE_NAME)
    async def pause(ctx):
        vc = voice_clients.get(ctx.guild.id)
        if vc:
            vc.pause()
            await ctx.send(embed=discord.Embed(
                title="Paused", description="Playback paused.", color=discord.Color.orange()
            ))

    @client.command(name="resume")
    @commands.has_role(ROLE_NAME)
    async def resume(ctx):
        vc = voice_clients.get(ctx.guild.id)
        if vc:
            vc.resume()
            await ctx.send(embed=discord.Embed(
                title="Resumed", description="Playback resumed.", color=discord.Color.green()
            ))

    @client.command(name="stop", aliases=["fuckoff"])
    @commands.has_role(ROLE_NAME)
    async def stop(ctx):
        vc = voice_clients.pop(ctx.guild.id, None)
        if vc:
            vc.stop()
            await vc.disconnect()
        current_song.pop(ctx.guild.id, None)
        await ctx.send(embed=discord.Embed(
            title="Stopped", description="Playback stopped and bot disconnected.", color=discord.Color.red()
        ))

    @client.command(name="skip", aliases=["s"])
    @commands.has_role(ROLE_NAME)
    async def skip(ctx):
        vc = voice_clients.get(ctx.guild.id)
        if vc and vc.is_playing():
            vc.stop()
            await ctx.send(embed=discord.Embed(
                title="Skipped", description="Skipped current song.", color=discord.Color.orange()
            ))
            return
        else:
            await ctx.send(embed=discord.Embed(
                title="Error", description="No song is currently playing.", color=discord.Color.red()
            ))

    @client.command(name="queue", aliases=["q"])
    @commands.has_role(ROLE_NAME)
    async def queue_cmd(ctx):
        q = queues.get(ctx.guild.id)
        if q:
            msg = "\n".join(f"{i}. {song['title']}" for i, song in enumerate(q, start=1))
            await ctx.send(embed=discord.Embed(
                title="Current Queue", description=msg, color=discord.Color.blue()
            ))
        else:
            await ctx.send(embed=discord.Embed(
                title="Queue", description="Queue is empty!", color=discord.Color.red()
            ))

    @client.command(name="np")
    @commands.has_role(ROLE_NAME)
    async def np(ctx):
        song = current_song.get(ctx.guild.id)
        start = song_start_times.get(ctx.guild.id)
        if not song or not start:
            return await ctx.send(embed=discord.Embed(
                title="Now Playing",
                description="No song is currently playing.",
                color=discord.Color.red()
            ))

        total = song["duration"]
        elapsed = (datetime.datetime.now() - start).total_seconds()
        if elapsed > total:
            elapsed = total

        # delete any previous NP embed
        prev = last_np_message.get(ctx.guild.id)
        if prev:
            try:
                old = await ctx.fetch_message(prev)
                await old.delete()
            except:
                pass

        embed = discord.Embed(title="Now Playing", color=discord.Color.green())
        embed.add_field(name="Title", value=f"[{song['title']}]({song['url']})", inline=False)
        embed.add_field(name="Duration", value=str(datetime.timedelta(seconds=total)), inline=False)
        embed.add_field(name="Requested by", value=song["user"], inline=False)
        embed.add_field(name="Progress", value=make_progress_bar(elapsed, total), inline=False)
        embed.set_thumbnail(url=song["thumbnail"])
        msg = await ctx.send(embed=embed)
        for emoji in ("⏸️", "▶️", "➡️"):
            await msg.add_reaction(emoji)

        last_np_message[ctx.guild.id] = msg.id

    @client.command(name="lyrics")
    @commands.has_role(ROLE_NAME)
    async def lyrics(ctx):
        song = current_song.get(ctx.guild.id)
        if not song:
            return await ctx.send(embed=discord.Embed(
                title="Error", description="No song is currently playing.", color=discord.Color.red()
            ))
        info = genius.search_song(song["title"])
        if not info:
            return await ctx.send(embed=discord.Embed(
                title="Error", description="Lyrics not found.", color=discord.Color.red()
            ))
        await ctx.send(embed=discord.Embed(
            title=f"Lyrics for {song['title']}",
            description=info.lyrics[:2048],
            color=discord.Color.blue()
        ))

    @client.command(name="playlist")
    @commands.has_role(ROLE_NAME)
    async def playlist(ctx, *, playlist_url):
        if "list=" not in playlist_url:
            return await ctx.send(embed=discord.Embed(
                title="Error", description="Invalid playlist URL provided.", color=discord.Color.red()
            ))
        data = await asyncio.get_event_loop().run_in_executor(
            None, lambda: ytdl.extract_info(playlist_url, download=False)
        )
        for entry in data.get("entries", []):
            await play(ctx, link=youtube_watch_url + entry["id"])

    @client.command(name="voicecheck")
    async def voicecheck(ctx):
        user_vc = ctx.author.voice.channel if ctx.author.voice else None
        bot_vc  = ctx.guild.voice_client.channel if ctx.guild.voice_client else None
        embed = discord.Embed(title="🔊 Voice Check", color=discord.Color.blue())
        embed.add_field(name="You in VC", value="✅ Yes" if user_vc else "❌ No", inline=False)
        embed.add_field(name="Bot in VC", value=f"✅ Yes ({bot_vc.name})" if bot_vc else "❌ No", inline=False)
        if user_vc:
            perms = user_vc.permissions_for(ctx.guild.me)
            embed.add_field(
                name="Permissions",
                value=f"Connect: {'✅' if perms.connect else '❌'}\n"
                      f"Speak:   {'✅' if perms.speak else '❌'}",
                inline=False
            )
        await ctx.send(embed=embed)

    client.remove_command('help')
    @client.command(name="help")
    async def help_command(ctx):
        embed = discord.Embed(
            title="🎵 MusicBot Help",
            description="List of all commands:",
            color=discord.Color.blurple()
        )
        embed.set_thumbnail(url=client.user.avatar.url)
        embed.set_footer(text="Use <> for required, [] for optional")
        embed.add_field(name="▶️ !play <url|search> / !p", value="Play a song or resume queue", inline=False)
        embed.add_field(name="🔍 !search <keywords>",        value="Search YouTube and select a result", inline=False)
        embed.add_field(name="🔀 !shuffle",                  value="Randomize the queue order", inline=False)
        embed.add_field(name="🗒️ !queue / !q",               value="Show the queue", inline=False)
        embed.add_field(name="❌ !clear",                     value="Clear the queue", inline=False)
        embed.add_field(name="🗑️ !remove <position>",        value="Remove a song by position", inline=False)
        embed.add_field(name="⏸️ !pause",                    value="Pause playback", inline=False)
        embed.add_field(name="▶️ !resume",                   value="Resume playback", inline=False)
        embed.add_field(name="⏭️ !skip / !s",                value="Skip the current song", inline=False)
        embed.add_field(name="⏹️ !stop / !fuckoff",          value="Stop and disconnect", inline=False)
        embed.add_field(name="🔁 !loop",                     value="Toggle loop for current song", inline=False)
        embed.add_field(name="🎶 !np",                       value="Show now playing and controls", inline=False)
        embed.add_field(name="📝 !lyrics",                   value="Fetch lyrics for current song", inline=False)
        embed.add_field(name="📜 !playlist",                 value="Queue a YouTube playlist", inline=False)
        embed.add_field(name="🔊 !voicecheck",               value="Check voice channel status", inline=False)
        await ctx.send(embed=embed)

    client.run(DISCORD_TOKEN)

if __name__ == "__main__":
    run_bot()
