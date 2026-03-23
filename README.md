# LiveStreamScheduler

A command-line tool and HTTP dashboard for managing church live stream operations. Correlates Google Calendar service schedules with YouTube live broadcasts, provides coverage analysis, and offers a browser-based "Mission Control" UI.

## Features

- Fetches upcoming services from a Google Calendar cache endpoint
- Discovers YouTube live broadcasts via service account or OAuth credentials
- Calendar-to-YouTube coverage analysis (gap detection)
- Mission Control web UI with real-time SSE streaming console
- Configurable per-service metadata defaults
- yt-dlp integration for stream metadata extraction

## Setup

### 1. Configuration

Copy the example config:

```bash
cp fb_config.example.json fb_config.local.json
```

Edit `fb_config.local.json` with your:
- YouTube channel URL
- Calendar cache endpoint URL
- Timezone and coverage preferences

### 2. Credentials

Place your Google API credentials in the project root:
- **Service account key**: `*service_account*.json` (for read-only broadcast listing)
- **OAuth client secret**: `client_secret_*.json` (for user-authenticated operations)

These files are gitignored and must never be committed.

### 3. Dependencies

```bash
pip install google-auth google-auth-oauthlib google-api-python-client python-dateutil
```

## Usage

### Command Line

```bash
# Show upcoming service blocks with YouTube coverage
python fb_scheduler.py --config fb_config.local.json

# List YouTube live broadcasts (service account)
python fb_scheduler.py --config fb_config.local.json --list-youtube-live-broadcasts

# List broadcasts with user OAuth
python fb_scheduler.py --config fb_config.local.json --list-youtube-live-broadcasts-user
```

### Mission Control (Web UI)

```bash
python fb_trigger_server.py
```

Open `http://localhost:8080` in your browser.

## License

MIT — see [LICENSE](LICENSE).
