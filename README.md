# better-drpc

Discord Rich Presence bridge for self-hosted media servers.

`better-drpc` polls your active sessions from:
- Jellyfin
- Plex
- Audiobookshelf

Then it updates your Discord activity with media metadata, progress, and artwork.

## Features

- Live Discord Rich Presence updates for movies, episodes, music, and audiobooks
- Multi-server polling (Jellyfin, Plex, Audiobookshelf)
- Automatic image caching and temporary image hosting for Discord-compatible artwork URLs
- Session prioritization when multiple servers are active (most recently active session wins)
- Basic Discord RPC reconnect handling when Discord restarts or the RPC pipe closes
- Cache clearing command for all or specific providers

## Requirements

- Python 3.8+
- Discord desktop app running (RPC is local-only)
- At least one configured server (Jellyfin, Plex, or Audiobookshelf)

## Installation

1. Clone the repository.
2. Create and activate a virtual environment.
3. Install dependencies.

```bash
pip install -r requirements.txt
```

## Configuration

Create a `.env` file in the project root.

### Core

- `CLIENT_ID` (required): Discord application client ID used by `pypresence`

### Jellyfin

- `JELLYFIN_SERVER_URL` (optional)
- `JELLYFIN_API_KEY` (optional)
- `JELLYFIN_USER` (optional, filter by username)

### Plex

- `PLEX_TOKEN` (optional)
- `PLEX_SERVER_NAME` (optional)
- `PLEX_USER` (optional, filter by Plex username)

### Audiobookshelf

- `AUDIOBOOKSHELF_SERVER_URL` (optional)
- `AUDIOBOOKSHELF_API_KEY` (optional)
- `AUDIOBOOKSHELF_USER` (optional, filter sessions by Audiobookshelf **user ID** — not the display name; find it in Settings → Users in the Audiobookshelf web UI)

### Device Filter

- `ONLY_GET_THIS_DEVICE` (optional, `true`/`false`)
	- Intended to only show sessions from the current machine hostname when supported.

## Example `.env`

```env
CLIENT_ID=123456789012345678

JELLYFIN_SERVER_URL=http://192.168.1.20:8096
JELLYFIN_API_KEY=your_jellyfin_api_key
JELLYFIN_USER=your_jellyfin_username

PLEX_TOKEN=your_plex_token
PLEX_SERVER_NAME=YourPlexServer
PLEX_USER=your_plex_username

AUDIOBOOKSHELF_SERVER_URL=http://192.168.1.30:13378
AUDIOBOOKSHELF_API_KEY=your_abs_api_key
AUDIOBOOKSHELF_USER=usr_yourUserIdHere

ONLY_GET_THIS_DEVICE=false
```

## Usage

Run the app:

```bash
python main.py
```

Help:

```bash
python main.py --help
```

Clear cache:

```bash
python main.py --clear-cache jellyfin
python main.py --clear-cache plex
python main.py --clear-cache abs
python main.py --clear-cache all
```

## How It Works

1. Polls each provider for active sessions.
2. Skips paused sessions.
3. Builds a normalized media payload (`movie`, `episode`, `track`).
4. Caches and uploads cover art to get externally reachable image URLs.
5. Pushes the payload to Discord Rich Presence.

When multiple services are active, the newest active one is shown.

## Project Structure

- `main.py`: App loop, server arbitration, Discord RPC update/clear logic
- `djelly.py`: Jellyfin session polling and payload normalization
- `dplex.py`: Plex session polling and payload normalization
- `dabs.py`: Audiobookshelf session polling and payload normalization
- `cache.py`: Image download/cache + temporary URL upload helper
- `cache/`: Local cache files and provider-specific cache directories

## Notes

- Discord Rich Presence image keys require public URLs; this project uses temporary hosted URLs for artwork.
- If artwork expires or breaks, use `--clear-cache` and let it refresh.
- If Discord is closed, updates will fail until Discord desktop is open again.

## Troubleshooting

- Presence does not update:
	- Confirm Discord desktop app is running.
	- Confirm `CLIENT_ID` is correct.
	- Check server credentials/URLs in `.env`.
- No media detected:
	- Verify you are actively playing (not paused).
	- Verify the configured user filters match your active session user.
- Wrong/old artwork:
	- Clear cache with `--clear-cache <provider>` or `all`.

## Disclaimer

This is an unofficial community project and is not affiliated with Discord, Plex, Jellyfin, or Audiobookshelf.
