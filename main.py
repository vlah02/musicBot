import discord
from discord.ext import commands
import os
import asyncio
import yt_dlp
import lyricsgenius
from dotenv import load_dotenv
import urllib.parse, urllib.request, re
import datetime

def run_bot():
    load_dotenv()
    DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
    GENIUS_TOKEN = os.getenv('GENIUS_TOKEN')
    ROLE_NAME = "DJ"
    RESTRICTED_USER_ID = 123456789012345678

    intents = discord.Intents.default()
    intents.message_content = True
    intents.voice_states = True
    client = commands.Bot(command_prefix="!", intents=intents)

    queues = {}
    voice_clients = {}
    current_song = {}
    song_start_times = {}
    loop_status = {}

    youtube_base_url = 'https://www.youtube.com/'
    youtube_results_url = youtube_base_url + 'results?'
    youtube_watch_url = youtube_base_url + 'watch?v='

    yt_dl_options = {
        "format": "bestaudio/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist"
    }
    ytdl = yt_dlp.YoutubeDL(yt_dl_options)
    genius = lyricsgenius.Genius(GENIUS_TOKEN)

    ffmpeg_options = {
        'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
        'options': '-vn -filter:a "volume=0.25"'
    }

    @client.event
    async def on_ready():
        print(f'{client.user} is now jamming')

    @client.event
    async def on_voice_state_update(member, before, after):
        # Clean up if bot is disconnected manually
        if member == client.user and before.channel is not None and after.channel is None:
            guild_id = before.channel.guild.id
            print(f"[INFO] Bot was disconnected from voice channel in guild {guild_id}")
            vc = voice_clients.pop(guild_id, None)
            if vc:
                vc.stop()
            current_song.pop(guild_id, None)
            song_start_times.pop(guild_id, None)

    async def play_song(ctx, song):
        try:
            data = await asyncio.get_event_loop().run_in_executor(
                None, lambda: ytdl.extract_info(song['url'], download=False)
            )
        except Exception as e:
            print(f"Error extracting info: {e}")
            await ctx.send(embed=discord.Embed(
                title="Error",
                description="There was an error extracting the video information.",
                color=discord.Color.red()
            ))
            return

        player = discord.FFmpegOpusAudio(data['url'], **ffmpeg_options)

        def after_playing(err):
            vc = voice_clients.get(ctx.guild.id)
            if vc is None or not vc.is_connected():
                return
            coro = play_song(ctx, song) if loop_status.get(ctx.guild.id) else handle_queue(ctx)
            asyncio.run_coroutine_threadsafe(coro, client.loop)

        voice_clients[ctx.guild.id].play(player, after=after_playing)
        current_song[ctx.guild.id] = song
        song_start_times[ctx.guild.id] = datetime.datetime.now()

        embed = discord.Embed(title="Now Playing", color=discord.Color.green())
        embed.add_field(name="Title", value=f"[{song['title']}]({song['url']})", inline=False)
        embed.add_field(name="Duration", value=str(datetime.timedelta(seconds=song['duration'])), inline=False)
        embed.add_field(name="Added by", value=song['user'], inline=False)
        embed.set_thumbnail(url=song['thumbnail'])
        await ctx.send(embed=embed)

    async def handle_queue(ctx):
        if queues.get(ctx.guild.id):
            next_song = queues[ctx.guild.id].pop(0)
            await play_song(ctx, next_song)
        else:
            await disconnect_bot(ctx)

    async def disconnect_bot(ctx):
        if ctx.guild.id in voice_clients:
            await voice_clients[ctx.guild.id].disconnect()
            del voice_clients[ctx.guild.id]
        current_song.pop(ctx.guild.id, None)
        await ctx.send(embed=discord.Embed(
            title="Disconnected",
            description="The queue is empty. The bot has disconnected.",
            color=discord.Color.red()
        ))

    @client.before_invoke
    async def check_restricted_user(ctx):
        if ctx.author.id == RESTRICTED_USER_ID:
            await ctx.send(embed=discord.Embed(
                title="Access Denied",
                description="You are restricted from using this command.",
                color=discord.Color.red()
            ))
            raise commands.CheckFailure("Restricted user")

    @client.command(name="play")
    @commands.has_role(ROLE_NAME)
    async def play(ctx, *, link=None, user=None):
        queues.setdefault(ctx.guild.id, [])
        if link is None:
            # Resume or show empty queue
            if queues[ctx.guild.id]:
                vc = voice_clients.get(ctx.guild.id)
                if vc and vc.is_connected() and not vc.is_playing():
                    song = queues[ctx.guild.id].pop(0)
                    await play_song(ctx, song)
                else:
                    try:
                        vc = await ctx.author.voice.channel.connect()
                        voice_clients[ctx.guild.id] = vc
                        song = queues[ctx.guild.id].pop(0)
                        await play_song(ctx, song)
                    except Exception as e:
                        print(e)
            else:
                await ctx.send(embed=discord.Embed(title="Queue", description="The queue is empty.", color=discord.Color.red()))
            return

        # Search mode
        if youtube_base_url not in link:
            query = urllib.parse.urlencode({'search_query': link})
            html = urllib.request.urlopen(youtube_results_url + query).read().decode()
            m = re.search(r'/watch\?v=(.{11})', html)
            if m:
                link = youtube_watch_url + m.group(1)

        try:
            data = await asyncio.get_event_loop().run_in_executor(
                None, lambda: ytdl.extract_info(link, download=False)
            )
        except Exception as e:
            print(f"Error extracting info: {e}")
            await ctx.send(embed=discord.Embed(
                title="Error", description="Error extracting video info.", color=discord.Color.red()
            ))
            return

        song = {
            'title': data['title'],
            'url': link,
            'duration': data['duration'],
            'thumbnail': data['thumbnail'],
            'user': user or ctx.author.display_name
        }

        vc = voice_clients.get(ctx.guild.id)
        if vc and vc.is_connected():
            if vc.is_playing():
                queues[ctx.guild.id].append(song)
                await ctx.send(embed=discord.Embed(
                    title="Added to Queue",
                    description=f"{song['title']} added at position {len(queues[ctx.guild.id])}.",
                    color=discord.Color.blue()
                ))
            else:
                await play_song(ctx, song)
        else:
            try:
                vc = await ctx.author.voice.channel.connect()
                voice_clients[ctx.guild.id] = vc
                await play_song(ctx, song)
            except Exception as e:
                print(e)

    @client.command(name="p")
    @commands.has_role(ROLE_NAME)
    async def p(ctx, *, link=None):
        await play(ctx, link=link)

    @client.command(name="clear")
    @commands.has_role(ROLE_NAME)
    async def clear(ctx):
        if queues.get(ctx.guild.id):
            queues[ctx.guild.id].clear()
            await ctx.send(embed=discord.Embed(
                title="Queue Cleared",
                description="The queue has been cleared.",
                color=discord.Color.orange()
            ))
        else:
            await ctx.send(embed=discord.Embed(
                title="Queue Error",
                description="There is no queue to clear.",
                color=discord.Color.red()
            ))

    @client.command(name="remove")
    @commands.has_role(ROLE_NAME)
    async def remove(ctx, position: int):
        """Remove a song from the queue by its position."""
        q = queues.get(ctx.guild.id)
        if not q:
            return await ctx.send(embed=discord.Embed(
                title="Error",
                description="The queue is empty.",
                color=discord.Color.red()
            ))
        if position < 1 or position > len(q):
            return await ctx.send(embed=discord.Embed(
                title="Error",
                description=f"Position must be between 1 and {len(q)}.",
                color=discord.Color.red()
            ))
        removed = q.pop(position - 1)
        await ctx.send(embed=discord.Embed(
            title="Removed from Queue",
            description=f"Removed **{removed['title']}** from position {position}.",
            color=discord.Color.green()
        ))

    @client.command(name="pause")
    @commands.has_role(ROLE_NAME)
    async def pause(ctx):
        try:
            voice_clients[ctx.guild.id].pause()
            await ctx.send(embed=discord.Embed(
                title="Paused",
                description="Playback paused.",
                color=discord.Color.orange()
            ))
        except Exception:
            pass

    @client.command(name="resume")
    @commands.has_role(ROLE_NAME)
    async def resume(ctx):
        try:
            voice_clients[ctx.guild.id].resume()
            await ctx.send(embed=discord.Embed(
                title="Resumed",
                description="Playback resumed.",
                color=discord.Color.green()
            ))
        except Exception:
            pass

    @client.command(name="stop")
    @commands.has_role(ROLE_NAME)
    async def stop(ctx):
        try:
            voice_clients[ctx.guild.id].stop()
            await voice_clients[ctx.guild.id].disconnect()
            del voice_clients[ctx.guild.id]
            if ctx.guild.id in current_song:
                del current_song[ctx.guild.id]
            embed = discord.Embed(title="Stopped", description="Playback has been stopped and the bot has disconnected.", color=discord.Color.red())
            await ctx.send(embed=embed)
        except Exception as e:
            print(e)

    @client.command(name="fuckoff")
    @commands.has_role(ROLE_NAME)
    async def fuckoff(ctx):
        await stop(ctx)

    @client.command(name="skip")
    @commands.has_role(ROLE_NAME)
    async def skip(ctx):
        try:
            vc = voice_clients.get(ctx.guild.id)
            if vc and vc.is_playing():
                vc.stop()
                await ctx.send(embed=discord.Embed(
                    title="Skipped",
                    description="Skipped current song.",
                    color=discord.Color.orange()
                ))
                await handle_queue(ctx)
            else:
                await ctx.send(embed=discord.Embed(
                    title="Error",
                    description="No song is currently playing.",
                    color=discord.Color.red()
                ))
        except Exception:
            pass

    @client.command(name="s")
    @commands.has_role(ROLE_NAME)
    async def s(ctx):
        await skip(ctx)

    @client.command(name="loop")
    @commands.has_role(ROLE_NAME)
    async def loop(ctx):
        loop_status[ctx.guild.id] = not loop_status.get(ctx.guild.id, False)
        status = "enabled" if loop_status[ctx.guild.id] else "disabled"
        embed = discord.Embed(title="Loop", description=f"Looping is now {status}.", color=discord.Color.purple())
        await ctx.send(embed=embed)

    @client.command(name="queue")
    @commands.has_role(ROLE_NAME)
    async def queue_cmd(ctx):
        q = queues.get(ctx.guild.id)
        if q:
            msg = ""
            for i, song in enumerate(q, start=1):
                msg += f"{i}. {song['title']}\n"
            await ctx.send(embed=discord.Embed(
                title="Current Queue",
                description=msg,
                color=discord.Color.blue()
            ))
        else:
            await ctx.send(embed=discord.Embed(
                title="Queue",
                description="The queue is empty!",
                color=discord.Color.red()
            ))

    @client.command(name="q")
    @commands.has_role(ROLE_NAME)
    async def q(ctx):
        await queue_cmd(ctx)

    @client.command(name="np")
    @commands.has_role(ROLE_NAME)
    async def np(ctx):
        song = current_song.get(ctx.guild.id)
        if song:
            await ctx.send(embed=discord.Embed(
                title="Now Playing",
                description=f"[{song['title']}]({song['url']})",
                color=discord.Color.green()
            ))
        else:
            await ctx.send(embed=discord.Embed(
                title="Now Playing",
                description="No song is currently playing.",
                color=discord.Color.red()
            ))

    @client.command(name="lyrics")
    @commands.has_role(ROLE_NAME)
    async def lyrics(ctx):
        song = current_song.get(ctx.guild.id)
        if song:
            try:
                info = genius.search_song(song['title'])
                if info:
                    await ctx.send(embed=discord.Embed(
                        title=f"Lyrics for {song['title']}",
                        description=info.lyrics[:2048],
                        color=discord.Color.blue()
                    ))
                else:
                    await ctx.send(embed=discord.Embed(
                        title="Error",
                        description="Lyrics not found.",
                        color=discord.Color.red()
                    ))
            except Exception as e:
                print(e)
                await ctx.send(embed=discord.Embed(
                    title="Error",
                    description="There was an error fetching the lyrics.",
                    color=discord.Color.red()
                ))
        else:
            await ctx.send(embed=discord.Embed(
                title="Error",
                description="No song is currently playing.",
                color=discord.Color.red()
            ))

    client.remove_command('help')

    @client.command(name="help")
    async def help_command(ctx):
        embed = discord.Embed(
            title="🎵 MusicBot Help",
            description="Here’s a list of all my commands:",
            color=discord.Color.blurple()
        )
        embed.set_thumbnail(url=client.user.avatar.url)
        embed.set_footer(text="Use <> for required, [] for optional")

        # Play & Queue
        embed.add_field(
            name="▶️ !play <url|search>",
            value="Plays a song from YouTube (by URL or search). Joins your VC if needed.",
            inline=False
        )
        embed.add_field(
            name="📜 !playlist <url>",
            value="Queues an entire YouTube playlist.",
            inline=False
        )
        embed.add_field(
            name="🗒️ !queue",
            value="Shows the current queue.",
            inline=False
        )
        embed.add_field(
            name="❌ !clear",
            value="Clears the queue.",
            inline=False
        )
        embed.add_field(
            name="🗑️ !remove <position>",
            value="Removes the song at the given position from the queue.",
            inline=False
        )

        # Playback controls
        embed.add_field(
            name="⏸️ !pause",
            value="Pauses playback.",
            inline=False
        )
        embed.add_field(
            name="▶️ !resume",
            value="Resumes playback.",
            inline=False
        )
        embed.add_field(
            name="⏭️ !skip",
            value="Skips the current song.",
            inline=False
        )
        embed.add_field(
            name="🔁 !loop",
            value="Toggles looping for the current song.",
            inline=False
        )
        embed.add_field(
            name="⏹️ !stop",
            value="Stops and disconnects the bot.",
            inline=False
        )

        # Info & Extras
        embed.add_field(
            name="🎶 !np",
            value="Shows what’s Now Playing.",
            inline=False
        )
        embed.add_field(
            name="📝 !lyrics",
            value="Fetches lyrics for the current song.",
            inline=False
        )
        embed.add_field(
            name="🔊 !voicecheck",
            value="Checks your & bot’s voice‑channel status and permissions.",
            inline=False
        )

        await ctx.send(embed=embed)

    @client.command(name="playlist")
    @commands.has_role(ROLE_NAME)
    async def playlist(ctx, *, playlist_url):
        if "list=" not in playlist_url:
            await ctx.send(embed=discord.Embed(
                title="Error",
                description="Invalid playlist URL provided.",
                color=discord.Color.red()
            ))
            return
        try:
            info = await asyncio.get_event_loop().run_in_executor(
                None, lambda: ytdl.extract_info(playlist_url, download=False)
            )
            for entry in info.get('entries', []):
                await play(ctx, link=youtube_watch_url + entry['id'])
        except Exception as e:
            print(e)
            await ctx.send(embed=discord.Embed(
                title="Error",
                description="There was an error processing the playlist.",
                color=discord.Color.red()
            ))

    @client.command(name="voicecheck")
    async def voicecheck(ctx):
        user_vc = ctx.author.voice.channel if ctx.author.voice else None
        bot_vc = ctx.guild.voice_client.channel if ctx.guild.voice_client else None

        embed = discord.Embed(title="🔊 Voice Check", color=discord.Color.blue())
        embed.add_field(name="🧑 You in Voice Channel", value="✅ Yes" if user_vc else "❌ No", inline=False)
        embed.add_field(name="🤖 Bot in Voice Channel", value=f"✅ Yes ({bot_vc.name})" if bot_vc else "❌ No", inline=False)

        if user_vc:
            perms = user_vc.permissions_for(ctx.guild.me)
            embed.add_field(
                name="🔐 Bot Permissions",
                value=f"Connect: {'✅' if perms.connect else '❌'}\nSpeak: {'✅' if perms.speak else '❌'}",
                inline=False
            )

        await ctx.send(embed=embed)

    client.run(DISCORD_TOKEN)

if __name__ == "__main__":
    run_bot()
