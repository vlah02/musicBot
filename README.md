# MusicBot

MusicBot is a Discord music bot built with discord.py, yt-dlp, and lyricsgenius. It allows users with a specific DJ role to play, search, and manage music playback directly in Discord voice channels. Controls include reaction-based playback management and text commands for advanced queue and playback control.

---

## Features

- **Play**: Stream audio from YouTube by URL or search keywords.
- **Search**: Search YouTube and select results via reaction emojis.
- **Queue Management**: Add, remove, clear, shuffle, and display queued songs.
- **Playback Controls**: Play, pause, resume, skip, stop, and loop tracks.
- **Now Playing**: Dynamic embed showing current track, progress bar, and reaction controls.
- **Lyrics**: Fetch lyrics for the current song using the Genius API.
- **Voicecheck**: Verify your and the bot’s voice channel status and permissions.

---

## Prerequisites

- Python 3.8 or higher
- A Discord bot token
- A Genius API token
- FFmpeg installed and available in your system PATH

---

## Installation

```bash
# Clone the repository
git clone <repo-url>
cd musicbot

# Create and activate a virtual environment
python -m venv venv
# Linux/macOS
source venv/bin/activate
# Windows
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

---

## Configuration

Create a `.env` file in the project root with the following variables:

```env
DISCORD_TOKEN=your_discord_bot_token
GENIUS_TOKEN=your_genius_api_token
ROLE_NAME=your_role_name_for_DJ
```

---

## Usage

Run the bot:

```bash
python main.py
```

Ensure the bot has the specified **ROLE\_NAME** (default `DJ`) and permissions to connect, speak, and add reactions in voice and text channels.

---

## Commands

All commands (except `voicecheck`) require the role defined by `ROLE_NAME`.

| Command              | Description                                                    |
|----------------------|----------------------------------------------------------------|
| `!play <url>`        | Play a song by URL or search keywords, or resume the queue.    |
| `!search <keywords>` | Search YouTube and pick a result via reaction emojis.          |
| `!queue` / `!q`      | Display the current song queue.                                |
| `!clear`             | Clear the entire queue.                                        |
| `!remove <position>` | Remove the song at the given position in the queue.            |
| `!skip` / `!s`       | Skip the currently playing song.                               |
| `!pause`             | Pause playback.                                                |
| `!resume`            | Resume playback.                                               |
| `!stop` / `!fuckoff` | Stop playback and disconnect the bot from the voice channel.   |
| `!shuffle`           | Shuffle the order of the queue.                                |
| `!loop`              | Toggle looping for the current song.                           |
| `!np`                | Show the Now Playing embed with progress bar and controls.     |
| `!lyrics`            | Fetch and display lyrics for the current song.                 |
| `!playlist <url>`    | Queue all songs from a YouTube playlist URL.                   |
| `!voicecheck`        | Check your and the bot’s voice channel status and permissions. |

---

## Environment Variables

- `DISCORD_TOKEN`: **Required.** Your Discord bot token.
- `GENIUS_TOKEN`: **Required.** Your Genius API token.
- `ROLE_NAME`: **Optional.** Name of the role allowed to control music commands (default: `DJ`).

---

## License

This project is licensed under the MIT License.
