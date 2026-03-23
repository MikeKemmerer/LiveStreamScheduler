# Live Services Mission Control Workflow

This project is now centered on one workflow:

- show upcoming service blocks from calendar data
- show whether each service already has a YouTube stream
- provide copy-ready metadata for manual scheduling in YouTube and Facebook

## 1) Setup local config

Copy the example and fill in your values:

- Source: fb_config.example.json
- Local: fb_config.local.json

Required fields in fb_config.local.json:

- youtube.channel_url

Coverage-mode settings:

- defaults.calendar_youtube_coverage: true/false
- calendar.url
- calendar.timezone
- calendar.coverage_days
- calendar.gap_minutes

Notes:

- fb_config.local.json is ignored by git.

## 2) Generate services coverage data from CLI (optional)

To run the services-vs-YouTube coverage report from config:

- defaults.calendar_youtube_coverage = true

Then run:

python3 fb_scheduler.py

Behavior:

- Reads upcoming services from calendar
- Compares those services against existing YouTube streams
- Produces matched (scheduled) and missing (unscheduled) groups

Output files:

- analysis/calendar_youtube_coverage.md

You can still force the report mode from CLI using:

- --calendar-youtube-coverage

## 3) Use the local web trigger

Start server:

python3 fb_trigger_server.py

Open:

http://127.0.0.1:8777

Use the form to:

- optionally refresh streams first
- open Mission Control for current upcoming services

Mission Control highlights:

- left pane: pending queue (unscheduled) and scheduled queue cards
- top chips: Total, Scheduled, Unscheduled with click-to-filter behavior
- right pane tabs: Scheduled, Reference, Activity
- Mark Scheduled button: moves an unscheduled card to scheduled state, updates counters, and logs the action
- copy actions: title and description fields are copy-ready for manual paste

## 4) Schedule manually in YouTube / Facebook

Use Mission Control as your reference and copy workspace, then schedule manually in your publishing tools.

Facebook Live Producer:

Open:

https://business.facebook.com/live/producer/v2

Then:

- create a scheduled live video event
- paste Title and Description from Mission Control
- set start time using the service card date/time
- confirm stream profile/key selection
- save/schedule

YouTube Studio:

- create the stream manually when needed
- paste title/description from Mission Control
- verify service time and visibility settings