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
	- Create one under **Settings → API Keys**. An **admin** key is recommended: only
		admins may read `/api/sessions/open`, which is the endpoint that reports live
		playback. A non-admin key still works, but falls back to that user's own
		listening history, which updates a little later.
- `AUDIOBOOKSHELF_USER` (optional, filter by Audiobookshelf username or user id)
	- Leave unset to accept whichever user the API key can see.
- `AUDIOBOOKSHELF_STALE_AFTER` (optional, default `30`, minimum `25`)
	- Seconds without a progress sync before playback counts as paused. Audiobookshelf
		clients sync 20 seconds after playback starts and every 10 seconds after that,
		so values below ~25 make the presence flicker or never appear. Raise it if you
		listen on a client that syncs less often.

### Device Filter

- `ONLY_GET_THIS_DEVICE` (optional, `true`/`false`)
	- Intended to only show sessions from the current machine hostname when supported.

### Image Upload Host

- `IMAGE_UPLOAD_HOSTS` (optional, default `litterbox,imgbb`)
	- Comma-separated list of hosts used to upload cover art so Discord can display it, tried in order until one succeeds.
	- Supported values: `litterbox` (litterbox.catbox.moe) and `imgbb` (imgbb.com).
	- litterbox is blocked by some ISPs/regions (e.g. Turkey). If it is unreachable for you, set `IMAGE_UPLOAD_HOSTS=imgbb` to skip it, or reorder the list to change priority.
- `IMGBB_API_KEY` (required only when using the `imgbb` host)
	- Get a free key at <https://api.imgbb.com/> (sign in, then "Get API key"). The `imgbb` host is skipped if this is unset.

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
AUDIOBOOKSHELF_USER=your_abs_username
# seconds without a progress sync before playback counts as paused
AUDIOBOOKSHELF_STALE_AFTER=30

ONLY_GET_THIS_DEVICE=false

# litterbox is blocked in some regions (e.g. Turkey); reorder or drop it if needed
IMAGE_UPLOAD_HOSTS=litterbox,imgbb
# required only if the imgbb host is used; get a free key at https://api.imgbb.com/
IMGBB_API_KEY=your_imgbb_api_key
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

Audiobookshelf has no "is playing" flag, so playback is inferred from how recently
the session was synced (see `AUDIOBOOKSHELF_STALE_AFTER`). Session timestamps are
compared against the server's own clock, read from the HTTP `Date` header, so the
two machines do not need synchronized clocks.

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
	- Run `python main.py --debug` to see which sessions each provider returned and
		why they were skipped.
- Audiobookshelf never shows up:
	- Check `AUDIOBOOKSHELF_USER` — it must match your username or user id exactly,
		or be left unset.
	- If the key is not an admin key, playback is read from listening history and can
		take a few extra seconds to appear.
	- Presence appearing and disappearing usually means `AUDIOBOOKSHELF_STALE_AFTER`
		is shorter than your client's sync interval; raise it.
- Wrong/old artwork:
	- Clear cache with `--clear-cache <provider>` or `all`.

## Disclaimer

This is an unofficial community project and is not affiliated with Discord, Plex, Jellyfin, or Audiobookshelf.
