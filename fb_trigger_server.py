#!/usr/bin/env python3
import argparse
import errno
import html
import json
import logging
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from fb_scheduler import (
    DEFAULT_CALENDAR_URL,
    build_calendar_youtube_coverage_report,
    read_config,
)


ROOT = Path(__file__).resolve().parent
LOGGER = logging.getLogger(__name__)

# --- SSE log store for streaming console output ---
_run_sessions: dict[str, dict] = {}
_sessions_lock = threading.Lock()


def _create_run_session() -> str:
    import secrets
    session_id = secrets.token_hex(8)
    with _sessions_lock:
        _run_sessions[session_id] = {
            "lines": [],
            "done": False,
            "error": None,
            "lock": threading.Lock(),
        }
    return session_id


def _push_log(session_id: str, line: str) -> None:
    with _sessions_lock:
        session = _run_sessions.get(session_id)
    if session:
        with session["lock"]:
            session["lines"].append(line)


def _finish_session(session_id: str, error: str | None = None) -> None:
    with _sessions_lock:
        session = _run_sessions.get(session_id)
    if session:
        with session["lock"]:
            session["done"] = True
            session["error"] = error


def _is_client_disconnect_error(exc: BaseException) -> bool:
  if isinstance(exc, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)):
    return True
  if not isinstance(exc, OSError):
    return False
  disconnect_errnos = {errno.EPIPE, errno.ECONNRESET}
  if hasattr(errno, "ECONNABORTED"):
    disconnect_errnos.add(errno.ECONNABORTED)
  return exc.errno in disconnect_errnos or getattr(exc, "winerror", None) in {10053, 10054}


def to_bool(form_values: dict[str, list[str]], key: str) -> bool:
    val = form_values.get(key, [""])[0].strip().lower()
    return val in {"1", "true", "on", "yes"}


def _as_dict(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _to_int(value: object, default: int) -> int:
  if isinstance(value, int):
    return value
  if isinstance(value, float):
    return int(value)
  if isinstance(value, str):
    try:
      return int(value)
    except ValueError:
      return default
  try:
    return int(str(value))
  except (TypeError, ValueError):
    return default


def _render_coverage_html(
  report: dict[str, object],
) -> str:
    missing_obj = report.get("missing_services")
    if not isinstance(missing_obj, list):
        missing_obj = report.get("missing_divine")
    missing = missing_obj if isinstance(missing_obj, list) else []

    matched_obj = report.get("matched_services")
    if not isinstance(matched_obj, list):
        matched_obj = report.get("matched_divine")
    matched = matched_obj if isinstance(matched_obj, list) else []

    missing_count = report.get("service_blocks_missing", report.get("divine_blocks_missing", 0))
    matched_count = report.get("service_blocks_matched", report.get("divine_blocks_matched", 0))
    total_count = report.get("service_blocks_total", report.get("divine_blocks_total", 0))

    out = [
        '<section class="mission-shell">',
        '<div class="mission-header">',
        '<h2>Mission Control</h2>',
        '<p>Review missing streams and copy prepared metadata for manual publishing.</p>',
        '</div>',
        '<div class="mission-stats">',
        f'<button type="button" class="stat-chip stat-filter is-active" data-filter="all">Total: {html.escape(str(total_count))}</button>',
        f'<button type="button" class="stat-chip stat-filter stat-ok" data-filter="scheduled">Scheduled: {html.escape(str(matched_count))}</button>',
        f'<button type="button" class="stat-chip stat-filter stat-attn" data-filter="unscheduled">Unscheduled: {html.escape(str(missing_count))}</button>',
        '</div>',
        '<div class="mission-grid">',
        '<section class="mission-left" id="unscheduled-streams">',
        '<h3>Pending Queue</h3>',
    ]

    if not missing:
        out.append("<p>All service blocks in the current window already have a YouTube stream.</p>")

    for idx, item in enumerate(missing, start=1):
        if not isinstance(item, dict):
            continue

        date_txt = html.escape(str(item.get("date") or ""))
        service_txt = html.escape(str(item.get("service_label") or ""))
        window_txt = html.escape(f"{item.get('start_local')} - {item.get('end_local')}")
        chapel_url = html.escape(str(item.get("chapel_url") or ""))
        kids_raw = str(item.get("kids_url") or "").strip()
        kids_url = html.escape(kids_raw)

        title_id = f"cov-title-{idx}"
        title_copy_id = f"cov-title-copy-{idx}"
        title_count_id = f"cov-title-count-{idx}"
        title_options_wrap_id = f"cov-title-options-wrap-{idx}"
        title_status_id = f"cov-title-status-{idx}"
        desc_id = f"cov-desc-{idx}"
        desc_count_id = f"cov-desc-count-{idx}"
        desc_status_id = f"cov-desc-status-{idx}"
        body_id = f"draft-body-{idx}"
        chapel_link_id = f"cov-chapel-link-{idx}"
        kids_link_id = f"cov-kids-link-{idx}"

        title_base_raw = str(item.get("title_base") or "").strip()
        if not title_base_raw:
            title_base_raw = str(item.get("title") or "").strip()
        start_local_raw = str(item.get("start_local") or "")
        start_local_attr = html.escape(start_local_raw, quote=True)
        service_attr = html.escape(str(item.get("service_label") or "Service"), quote=True)
        title_value = html.escape(title_base_raw)
        title_raw = title_base_raw
        desc_raw = title_base_raw
        desc_value = html.escape(desc_raw)
        desc_rest_attr = html.escape(json.dumps(""), quote=True)
        block_id = html.escape(str(item.get("service_block_id") or f"draft-{idx}"), quote=True)

        announcement_option = str(item.get("title_announcement_option") or "").strip()
        feast_options_obj = item.get("title_feast_options")
        feast_options = feast_options_obj if isinstance(feast_options_obj, list) else []

        option_items: list[str] = []
        opt_index = 0
        if announcement_option:
            opt_id = f"cov-opt-{idx}-{opt_index}"
            opt_value = html.escape(announcement_option)
            option_items.append(
                f'<label class="opt-item"><input type="checkbox" class="title-opt" id="{opt_id}" data-target-title="{title_id}" data-target-count="{title_count_id}" data-target-copy="{title_copy_id}" data-target-desc="{desc_id}" data-target-desc-count="{desc_count_id}" data-base-title="{html.escape(title_base_raw)}" value="{opt_value}" onchange="updateTitleFromOptions(this)" /> Announcement: {opt_value}</label>'
            )
            opt_index += 1

        for raw in feast_options:
            if not isinstance(raw, str):
                continue
            clean = raw.strip()
            if not clean:
                continue
            opt_id = f"cov-opt-{idx}-{opt_index}"
            opt_value = html.escape(clean)
            option_items.append(
                f'<label class="opt-item"><input type="checkbox" class="title-opt" id="{opt_id}" data-target-title="{title_id}" data-target-count="{title_count_id}" data-target-copy="{title_copy_id}" data-target-desc="{desc_id}" data-target-desc-count="{desc_count_id}" data-base-title="{html.escape(title_base_raw)}" value="{opt_value}" onchange="updateTitleFromOptions(this)" /> Feast Day: {opt_value}</label>'
            )
            opt_index += 1

        option_html = ""
        if option_items:
            option_html = "".join(option_items)
        else:
            option_html = '<p class="char-count">No Announcement/Feast options available for this draft.</p>'

        out.extend(
            [
          f'<div class="card draft-card stream-item" data-stream-status="unscheduled" data-service-block-id="{block_id}" data-service-label="{service_attr}" data-start-local="{start_local_attr}" data-title-id="{title_id}">',
          f'<div class="copy-row"><p><strong>Service {idx}</strong> <span class="status-chip status-pending">Unscheduled</span></p><button class="ghost-btn" type="button" onclick="markDraftScheduled(this)">Mark Scheduled</button><button class="ghost-btn toggle-draft-btn" data-target-body="{body_id}" type="button">Collapse</button></div>',
                f'<div id="{body_id}" class="draft-body">',
                f"<p><strong>Date:</strong> {date_txt}</p>",
                f"<p><strong>Service:</strong> {service_txt}</p>",
                f"<p><strong>Service Window:</strong> {window_txt}</p>",
            f'<p><strong>Chapel Link:</strong> <a id="{chapel_link_id}" href="{chapel_url}" target="reference-pane" rel="noopener" onclick="activateRightTab(\'reference\');">{chapel_url}</a></p>',
            ]
        )

        if kids_raw:
            out.append(
            f'<p><strong>Sunday School Link:</strong> <a id="{kids_link_id}" href="{kids_url}" target="reference-pane" rel="noopener" onclick="activateRightTab(\'reference\');">{kids_url}</a></p>'
            )

        out.extend(
            [
                f'<div class="copy-row"><p><strong>Title Options</strong></p></div>',
                f'<div id="{title_options_wrap_id}" class="opt-wrap">{option_html}</div>',
                f'<div class="copy-row"><p><strong>Title</strong></p><button id="{title_copy_id}" type="button" onclick="copyFromId(\'{title_id}\', \'{title_status_id}\')">Copy to Clipboard</button><span id="{title_status_id}" class="copy-status" aria-live="polite"></span></div>',
                f'<p id="{title_count_id}" class="char-count">{len(title_raw)}/100</p>',
                f'<textarea id="{title_id}" rows="2" style="width:100%;font-family:monospace;">{title_value}</textarea>',
                f'<div class="copy-row"><p><strong>Core Description</strong></p><button type="button" onclick="copyFromId(\'{desc_id}\', \'{desc_status_id}\')">Copy to Clipboard</button><span id="{desc_status_id}" class="copy-status" aria-live="polite"></span></div>',
                f'<p id="{desc_count_id}" class="char-count">{len(desc_raw)}/5000</p>',
                f'<textarea id="{desc_id}" data-rest-json="{desc_rest_attr}" rows="8" style="width:100%;font-family:monospace;">{desc_value}</textarea>',
                '</div>',
                '</div>',
            ]
        )

    scheduled_cards: list[str] = []
    scheduled_compact_items: list[str] = []
    for matched_item in matched:
        if not isinstance(matched_item, dict):
            continue
        service_txt = html.escape(str(matched_item.get("service_label") or "Service"))
        start_txt = html.escape(str(matched_item.get("start_local") or ""))
        date_txt = html.escape(str(matched_item.get("date") or ""))
        title_raw = str(matched_item.get("youtube_title") or "").strip()
        if not title_raw:
            title_raw = "Scheduled Livestream"
        title_txt = html.escape(title_raw)
        desc_raw = str(matched_item.get("youtube_description") or "").strip()
        if not desc_raw:
            desc_raw = title_raw
        desc_txt = html.escape(desc_raw)
        url_txt = html.escape(str(matched_item.get("youtube_url") or ""), quote=True)
        sched_idx = len(scheduled_cards) + 1
        title_id = f"sched-title-{sched_idx}"
        title_status_id = f"sched-title-status-{sched_idx}"
        desc_id = f"sched-desc-{sched_idx}"
        desc_status_id = f"sched-desc-status-{sched_idx}"
        body_id = f"sched-body-{sched_idx}"
        scheduled_cards.append(
            '<div class="card scheduled-item stream-item" data-stream-status="scheduled">'
            f'<div class="copy-row"><p><strong>Scheduled {sched_idx}</strong> <span class="status-chip status-done">Scheduled</span></p><button class="ghost-btn toggle-draft-btn" data-target-body="{body_id}" type="button">Collapse</button></div>'
            f'<div id="{body_id}" class="draft-body">'
            f'<p><strong>Date:</strong> {date_txt}</p>'
            f'<p><strong>Service:</strong> {service_txt}</p>'
            f'<p><strong>Start:</strong> {start_txt}</p>'
            f'<p><strong>YouTube:</strong> <a href="{url_txt}" target="reference-pane" rel="noopener" onclick="activateRightTab(\'reference\');">{title_txt or url_txt}</a></p>'
            f'<div class="copy-row"><p><strong>Title</strong></p><button type="button" onclick="copyFromId(\'{title_id}\', \'{title_status_id}\')">Copy to Clipboard</button><span id="{title_status_id}" class="copy-status" aria-live="polite"></span></div>'
            f'<p class="char-count">{len(title_raw)}/100</p>'
            f'<textarea id="{title_id}" rows="2" style="width:100%;font-family:monospace;" readonly>{title_txt}</textarea>'
            f'<div class="copy-row"><p><strong>Description</strong></p><button type="button" onclick="copyFromId(\'{desc_id}\', \'{desc_status_id}\')">Copy to Clipboard</button><span id="{desc_status_id}" class="copy-status" aria-live="polite"></span></div>'
            f'<p class="char-count">{len(desc_raw)}/5000</p>'
            f'<textarea id="{desc_id}" rows="6" style="width:100%;font-family:monospace;" readonly>{desc_txt}</textarea>'
            '</div>'
            '</div>'
        )
        scheduled_compact_items.append(
            '<div class="scheduled-item stream-item" data-stream-status="scheduled">'
            f'<p><strong>{service_txt}</strong> <small>{start_txt}</small></p>'
            f'<p><a href="{url_txt}" target="reference-pane" rel="noopener" onclick="activateRightTab(\'reference\');">{title_txt or url_txt}</a></p>'
            '</div>'
        )

    if scheduled_cards:
        out.append('<h3>Scheduled Queue</h3>')
        out.extend(scheduled_cards)

    scheduled_html = "".join(scheduled_compact_items) if scheduled_compact_items else "<p>No already-scheduled services in this coverage window.</p>"
    out.extend(
        [
            '</section>',
            '<aside class="mission-right" id="right-panel">',
            '<div class="tabs" role="tablist" aria-label="Mission right panel tabs">',
          '<button type="button" class="tab-btn is-active" data-tab="scheduled" role="tab" aria-selected="true" onclick="activateRightTab(\'scheduled\')">Scheduled</button>',
          '<button type="button" class="tab-btn" data-tab="reference" role="tab" aria-selected="false" onclick="activateRightTab(\'reference\')">Reference</button>',
          '<button type="button" class="tab-btn" data-tab="activity" role="tab" aria-selected="false" onclick="activateRightTab(\'activity\')">Activity</button>',
            '</div>',
            f'<section class="tab-panel" data-panel="scheduled" id="panel-scheduled">{scheduled_html}</section>',
            '<section class="tab-panel is-hidden" data-panel="reference">',
          '<p>Use this panel for side-by-side context while you complete pending drafts. If GOARCH blocks embedding, use the link below.</p>',
          '<p><a href="https://www.goarch.org" target="_blank" rel="noopener">Open GOARCH in a new tab</a></p>',
            '<iframe class="reference-frame" name="reference-pane" src="https://goarch.org" title="GOARCH Reference" loading="lazy"></iframe>',
            '</section>',
            '<section class="tab-panel is-hidden" data-panel="activity" id="panel-activity">',
            '<ul class="activity-list" id="activity-log">',
            '<li class="activity-item"><p><strong>Session started</strong></p><p>Use Mark Scheduled to log status transitions here.</p></li>',
            '</ul>',
            '</section>',
            '</aside>',
            '</div>',
            '</section>',
        ]
    )

    return "\n".join(out)


class Handler(BaseHTTPRequestHandler):
    def _send_html(self, status: int, content: str) -> None:
        body = content.encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except OSError as exc:
            if _is_client_disconnect_error(exc):
                LOGGER.warning(
                    "Client disconnected before response completed status=%s error=%s",
                    int(status),
                    exc.__class__.__name__,
                )
                return
            raise

    def do_GET(self) -> None:
        parsed = urlparse(self.path)

        if parsed.path == "/run-stream":
            self._handle_sse(parsed)
            return

        if parsed.path not in {"/", "/index.html"}:
            self._send_html(HTTPStatus.NOT_FOUND, "<h1>Not Found</h1>")
            return

        query = parse_qs(parsed.query)
        config_name = query.get("config", ["fb_config.local.json"])[0].strip() or "fb_config.local.json"

        page = f"""
<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <title>Live Scheduler</title>
    <style>
      :root {{
        --bg: #f5f3ef;
        --panel: #fffdf8;
        --card: #ffffff;
        --text: #1f2430;
        --muted: #5d6678;
        --border: #d9d1c5;
        --accent: #11468f;
        --error: #b91c1c;
        --link: #0a4aa6;
        --link-visited: #6b2da8;
      }}
      body.theme-dark {{
        --bg: #101418;
        --panel: #1a232b;
        --card: #212d36;
        --text: #e8edf2;
        --muted: #b7c3cf;
        --border: #33424f;
        --accent: #74b5ff;
        --error: #ff9c9c;
        --link: #8ec5ff;
        --link-visited: #c9a7ff;
      }}
      body {{ font-family: "Segoe UI", Tahoma, sans-serif; margin: 20px; background: radial-gradient(circle at top, #f9f6f1, var(--bg)); color: var(--text); }}
      body.theme-dark {{ background: radial-gradient(circle at top, #1a2630, var(--bg)); }}
      .run-shell {{ max-width: 1320px; margin: 0 auto; }}
      .top-row {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }}
      h1 {{ margin-bottom: 8px; }}
      .card {{ border: 1px solid var(--border); border-radius: 10px; padding: 16px; margin-bottom: 14px; background: var(--card); }}
      .row {{ margin: 10px 0; }}
      button {{ padding: 10px 16px; border: 1px solid var(--border); border-radius: 7px; background: var(--card); color: var(--text); cursor: pointer; }}
      input[type="text"], input[type="number"] {{ border: 1px solid var(--border); border-radius: 6px; background: var(--panel); color: var(--text); padding: 6px 8px; }}
      code {{ background: var(--panel); padding: 2px 4px; border: 1px solid var(--border); border-radius: 4px; }}
      a {{ color: var(--link); }}
      a:visited {{ color: var(--link-visited); }}
      a:hover {{ color: var(--accent); }}
      small {{ color: var(--muted); }}
      .error {{ color: var(--error); }}
      .theme-btn {{ border: 1px solid var(--border); background: var(--card); color: var(--text); border-radius: 7px; padding: 8px 12px; cursor: pointer; }}
      .console-wrap {{ display: none; margin-top: 14px; }}
      .console-wrap.visible {{ display: block; }}
      .console-output {{ background: #0d1117; color: #c9d1d9; font-family: "Cascadia Mono", "Consolas", monospace; font-size: 0.85em; padding: 12px; border-radius: 8px; max-height: 320px; overflow-y: auto; white-space: pre-wrap; word-break: break-all; border: 1px solid #30363d; }}
      .console-output .log-error {{ color: #ff7b72; }}
      .console-output .log-done {{ color: #7ee787; }}
    </style>
    <script>
      function initializeTheme() {{
        const key = 'missionTheme';
        const btn = document.getElementById('theme-toggle');
        if (!btn) return;

        const applyTheme = (theme) => {{
          const dark = theme === 'dark';
          document.body.classList.toggle('theme-dark', dark);
          btn.textContent = dark ? 'Switch to Light' : 'Switch to Dark';
        }};

        const saved = localStorage.getItem(key) || 'light';
        applyTheme(saved);
        btn.addEventListener('click', () => {{
          const dark = document.body.classList.contains('theme-dark');
          const next = dark ? 'light' : 'dark';
          localStorage.setItem(key, next);
          applyTheme(next);
        }});
      }}

      function handleFormSubmit(e) {{
        const form = e.target;
        const refreshBox = form.querySelector('input[name="refresh_streams"]');
        if (!refreshBox || !refreshBox.checked) return;

        e.preventDefault();
        const configInput = form.querySelector('input[name="config"]');
        const configVal = configInput ? configInput.value : 'fb_config.local.json';
        const submitBtn = form.querySelector('button[type="submit"]');
        if (submitBtn) {{ submitBtn.disabled = true; submitBtn.textContent = 'Fetching...'; }}

        const consoleWrap = document.getElementById('console-wrap');
        const consoleOut = document.getElementById('console-output');
        consoleWrap.classList.add('visible');
        consoleOut.textContent = '';

        const body = 'config=' + encodeURIComponent(configVal) + '&refresh_streams=on';
        fetch('/run-start', {{ method: 'POST', headers: {{ 'Content-Type': 'application/x-www-form-urlencoded' }}, body: body }})
          .then(r => r.json())
          .then(data => {{
            const sessionId = data.session;
            const source = new EventSource('/run-stream?session=' + encodeURIComponent(sessionId));

            source.onmessage = (ev) => {{
              const line = ev.data || '';
              const span = document.createElement('span');
              if (line.startsWith('ERROR') || line.startsWith('FATAL')) {{
                span.className = 'log-error';
              }}
              span.textContent = line + '\\n';
              consoleOut.appendChild(span);
              consoleOut.scrollTop = consoleOut.scrollHeight;
            }};

            source.addEventListener('done', () => {{
              source.close();
              const done = document.createElement('span');
              done.className = 'log-done';
              done.textContent = '\\n✓ Fetch complete. Loading results...\\n';
              consoleOut.appendChild(done);
              consoleOut.scrollTop = consoleOut.scrollHeight;
              setTimeout(() => {{ form.submit(); }}, 800);
            }});

            source.addEventListener('error', (ev) => {{
              if (source.readyState === EventSource.CLOSED) return;
              source.close();
              const err = document.createElement('span');
              err.className = 'log-error';
              err.textContent = '\\nConnection to server lost.\\n';
              consoleOut.appendChild(err);
              if (submitBtn) {{ submitBtn.disabled = false; submitBtn.textContent = 'Show Upcoming Services'; }}
            }});
          }})
          .catch(err => {{
            consoleOut.textContent += 'Failed to start: ' + err + '\\n';
            if (submitBtn) {{ submitBtn.disabled = false; submitBtn.textContent = 'Show Upcoming Services'; }}
          }});
      }}

      document.addEventListener('DOMContentLoaded', () => {{
        initializeTheme();
        const form = document.querySelector('form[action="/run"]');
        if (form) form.addEventListener('submit', handleFormSubmit);
      }});
    </script>
  </head>
  <body>
    <div class="run-shell">
      <div class="top-row">
        <h1>Live Scheduler</h1>
        <button id="theme-toggle" type="button" class="theme-btn">Switch to Dark</button>
      </div>
      <div class="card">
        <form method="post" action="/run">
          <div class="row">
            <label>Config Path: <input type="text" name="config" value="{html.escape(config_name)}" size="48" /></label>
          </div>
          <div class="row">
            <label><input type="checkbox" name="refresh_streams" /> Refresh YouTube streams first (slower)</label>
          </div>
          <div class="row">
            <button type="submit">Show Upcoming Services</button>
          </div>
        </form>
      </div>
      <div id="console-wrap" class="console-wrap">
        <div class="card">
          <p><strong>Fetch Console</strong></p>
          <div id="console-output" class="console-output"></div>
        </div>
      </div>
      <p>This view compares upcoming services with existing YouTube streams and supports manual scheduling workflows.</p>
    </div>
  </body>
</html>
"""
        self._send_html(HTTPStatus.OK, page)

    def _handle_sse(self, parsed) -> None:
        """Server-Sent Events endpoint: GET /run-stream?session=<id>"""
        query = parse_qs(parsed.query)
        session_id = query.get("session", [""])[0].strip()
        with _sessions_lock:
            session = _run_sessions.get(session_id)
        if not session:
            self._send_html(HTTPStatus.NOT_FOUND, "<h1>Session not found</h1>")
            return

        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()

            sent = 0
            while True:
                with session["lock"]:
                    lines = session["lines"][sent:]
                    done = session["done"]
                    error = session["error"]
                for line in lines:
                    self.wfile.write(f"data: {line}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    sent += 1
                if done:
                    if error:
                        self.wfile.write(f"event: error\ndata: {error}\n\n".encode("utf-8"))
                    self.wfile.write(b"event: done\ndata: complete\n\n")
                    self.wfile.flush()
                    break
                time.sleep(0.3)
        except OSError:
            pass
        finally:
            with _sessions_lock:
                _run_sessions.pop(session_id, None)

    def _handle_run_start(self) -> None:
        """POST /run-start — starts report generation in background, returns session ID for SSE."""
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        form = parse_qs(raw)

        config_name = form.get("config", ["fb_config.local.json"])[0].strip()
        config_path = (ROOT / config_name).resolve()
        refresh_streams = to_bool(form, "refresh_streams")

        session_id = _create_run_session()

        def _run():
            try:
                config = read_config(config_path)
                calendar_cfg = _as_dict(config.get("calendar"))
                calendar_url = str(calendar_cfg.get("url") or DEFAULT_CALENDAR_URL)
                coverage_days = _to_int(calendar_cfg.get("coverage_days", 10), 10)
                gap_minutes = _to_int(calendar_cfg.get("gap_minutes", 15), 15)

                build_calendar_youtube_coverage_report(
                    root=ROOT,
                    config=config,
                    refresh_streams=refresh_streams,
                    calendar_url=calendar_url,
                    coverage_days=max(coverage_days, 1),
                    gap_minutes=max(gap_minutes, 0),
                    on_log=lambda line: _push_log(session_id, line),
                )
                _finish_session(session_id)
            except Exception as exc:
                _push_log(session_id, f"FATAL: {exc}")
                _finish_session(session_id, error=str(exc))

        t = threading.Thread(target=_run, daemon=True)
        t.start()

        body = json.dumps({"session": session_id}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        if self.path == "/run-start":
            self._handle_run_start()
            return
        if self.path != "/run":
            self._send_html(HTTPStatus.NOT_FOUND, "<h1>Not Found</h1>")
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        form = parse_qs(raw)

        config_name = form.get("config", ["fb_config.local.json"])[0].strip()
        config_path = (ROOT / config_name).resolve()

        refresh_streams = to_bool(form, "refresh_streams")

        try:
            config = read_config(config_path)
            calendar_cfg = _as_dict(config.get("calendar"))
            calendar_url = str(calendar_cfg.get("url") or DEFAULT_CALENDAR_URL)
            coverage_days = _to_int(calendar_cfg.get("coverage_days", 10), 10)
            gap_minutes = _to_int(calendar_cfg.get("gap_minutes", 15), 15)

            report = build_calendar_youtube_coverage_report(
                root=ROOT,
                config=config,
                refresh_streams=refresh_streams,
                calendar_url=calendar_url,
                coverage_days=max(coverage_days, 1),
                gap_minutes=max(gap_minutes, 0),
            )
            pretty_obj: dict[str, object] = report
            mode_text = "Upcoming Services Status"
            content_html = _render_coverage_html(report)

            pretty = json.dumps(pretty_obj, ensure_ascii=False, indent=2)

            page = f"""
<!doctype html>
<html>
  <head>
    <meta charset=\"utf-8\" />
    <title>Run Complete</title>
    <style>
      :root {{
        --bg: #f5f3ef;
        --panel: #fffdf8;
        --card: #ffffff;
        --text: #1f2430;
        --muted: #5d6678;
        --border: #d9d1c5;
        --chip: #ece4d6;
        --ok: #1f6f2c;
        --attn: #8f5a00;
        --accent: #11468f;
        --link: #0a4aa6;
        --link-visited: #6b2da8;
      }}
      body.theme-dark {{
        --bg: #101418;
        --panel: #1a232b;
        --card: #212d36;
        --text: #e8edf2;
        --muted: #b7c3cf;
        --border: #33424f;
        --chip: #2a3946;
        --ok: #7edb95;
        --attn: #ffbf66;
        --accent: #74b5ff;
        --link: #8ec5ff;
        --link-visited: #c9a7ff;
      }}
      body {{ font-family: "Segoe UI", Tahoma, sans-serif; margin: 20px; background: radial-gradient(circle at top, #f9f6f1, var(--bg)); color: var(--text); }}
      body.theme-dark {{ background: radial-gradient(circle at top, #1a2630, var(--bg)); }}
      .run-shell {{ max-width: 1320px; margin: 0 auto; }}
      .top-row {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }}
      .card {{ border: 1px solid var(--border); border-radius: 10px; padding: 14px; margin-bottom: 14px; background: var(--card); }}
      pre {{ background: var(--panel); border: 1px solid var(--border); padding: 12px; overflow-x: auto; }}
      textarea {{ border: 1px solid var(--border); border-radius: 6px; padding: 8px; background: var(--panel); color: var(--text); }}
      a {{ color: var(--link); }}
      a:visited {{ color: var(--link-visited); }}
      a:hover {{ color: var(--accent); }}
      .copy-row {{ display: flex; align-items: center; gap: 10px; margin-top: 12px; }}
      .copy-row p {{ margin: 0; }}
      .copy-row button {{ padding: 6px 10px; cursor: pointer; }}
      .copy-status {{ color: var(--ok); font-size: 0.9em; }}
      .char-count {{ color: var(--muted); font-size: 0.85em; margin: 6px 0 4px; }}
      .char-count.over-limit {{ color: #d64045; font-weight: 600; }}
      .opt-wrap {{ border: 1px solid var(--border); border-radius: 6px; padding: 8px; margin: 6px 0 10px; }}
      .opt-item {{ display: block; margin: 4px 0; }}
      .is-hidden {{ display: none; }}
      .ghost-btn {{ background: transparent; border: 1px solid var(--border); border-radius: 6px; padding: 4px 10px; color: var(--text); }}
      .theme-btn {{ border: 1px solid var(--border); background: var(--card); color: var(--text); border-radius: 7px; padding: 8px 12px; cursor: pointer; }}
      .mission-shell {{ margin-top: 12px; }}
      .mission-header h2 {{ margin: 0 0 6px; }}
      .mission-header p {{ margin: 0 0 10px; color: var(--muted); }}
      .mission-stats {{ display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 14px; }}
      .stat-chip {{ background: var(--chip); border: 1px solid var(--border); border-radius: 999px; padding: 5px 10px; font-size: 0.9em; color: var(--text); }}
      .stat-filter {{ cursor: pointer; }}
      .stat-filter.is-active {{ outline: 2px solid var(--accent); outline-offset: 1px; }}
      .stat-chip.stat-ok {{ color: var(--ok); }}
      .stat-chip.stat-attn {{ color: var(--attn); }}
      .mission-grid {{ display: grid; grid-template-columns: minmax(0, 1.5fr) minmax(300px, 1fr); gap: 16px; align-items: start; }}
      .mission-left, .mission-right {{ background: var(--panel); border: 1px solid var(--border); border-radius: 12px; padding: 12px; }}
      .mission-left h3 {{ margin-top: 12px; }}
      .mission-left h3:first-of-type {{ margin-top: 0; }}
      .mission-right {{ position: sticky; top: 14px; max-height: calc(100vh - 30px); overflow-y: auto; }}
      .tabs {{ display: flex; gap: 8px; margin-bottom: 10px; }}
      .tab-btn {{ border: 1px solid var(--border); border-radius: 999px; background: var(--card); color: var(--text); padding: 6px 11px; cursor: pointer; }}
      .tab-btn.is-active {{ background: var(--accent); color: #fff; border-color: var(--accent); }}
      .status-chip {{ display: inline-flex; align-items: center; padding: 2px 8px; border-radius: 999px; font-size: 0.78em; border: 1px solid var(--border); margin-left: 8px; color: var(--text); }}
      .status-pending {{ color: var(--attn); background: #fff3dd; }}
      .status-done {{ color: var(--ok); background: #e9f8ee; }}
      body.theme-dark .status-pending {{ background: #3a2d17; color: var(--attn); }}
      body.theme-dark .status-done {{ background: #193325; color: var(--ok); }}
      .draft-card.is-complete {{ border-left: 5px solid var(--ok); }}
      .scheduled-item {{ border: 1px solid var(--border); border-radius: 8px; padding: 10px; margin-bottom: 8px; background: var(--card); }}
      .scheduled-item p {{ margin: 4px 0; }}
      .reference-frame {{ width: 100%; min-height: 420px; border: 1px solid var(--border); border-radius: 8px; background: #fff; }}
      .activity-list {{ list-style: none; margin: 0; padding: 0; display: grid; gap: 8px; }}
      .activity-item {{ border: 1px solid var(--border); border-radius: 8px; padding: 10px; background: var(--card); }}
      .activity-item p {{ margin: 3px 0; }}
      .stream-item.is-filtered-out {{ display: none; }}
      @media (max-width: 980px) {{
        .mission-grid {{ grid-template-columns: 1fr; }}
      }}
    </style>
    <script>
      function toggleDraftBody(bodyId, btn) {{
        const body = document.getElementById(bodyId);
        if (!body || !btn) return;
        const hidden = body.classList.toggle('is-hidden');
        btn.textContent = hidden ? 'Expand' : 'Collapse';
      }}

      function initializeCollapseButtons() {{
        document.querySelectorAll('.toggle-draft-btn[data-target-body]').forEach((btn) => {{
          if (btn.dataset.bound === '1') return;
          btn.dataset.bound = '1';
          btn.addEventListener('click', () => {{
            const bodyId = btn.dataset.targetBody || '';
            if (!bodyId) return;
            toggleDraftBody(bodyId, btn);
          }});
        }});
      }}


      function activateRightTab(target, sourceButton) {{
        const buttons = document.querySelectorAll('.tab-btn[data-tab]');
        const panels = document.querySelectorAll('.tab-panel[data-panel]');
        if (!buttons.length || !panels.length) return;

        buttons.forEach((button) => {{
          const active = button.dataset.tab === target;
          button.classList.toggle('is-active', active);
          button.setAttribute('aria-selected', active ? 'true' : 'false');
        }});

        panels.forEach((panel) => {{
          panel.classList.toggle('is-hidden', panel.dataset.panel !== target);
        }});
      }}

      function initializeTabs() {{
        const buttons = document.querySelectorAll('.tab-btn[data-tab]');
        if (!buttons.length) return;
        buttons.forEach((button) => {{
          if (button.dataset.bound === '1') return;
          button.dataset.bound = '1';
          button.addEventListener('click', () => activateRightTab(button.dataset.tab || '', button));
        }});
      }}

      function applyStreamFilter(mode) {{
        const normalized = mode === 'scheduled' || mode === 'unscheduled' ? mode : 'all';
        document.querySelectorAll('.stream-item[data-stream-status]').forEach((item) => {{
          const status = item.dataset.streamStatus || '';
          const visible = normalized === 'all' || status === normalized;
          item.classList.toggle('is-filtered-out', !visible);
        }});

        if (normalized === 'scheduled') {{
          activateRightTab('scheduled');
        }} else if (normalized === 'unscheduled') {{
          activateRightTab('reference');
        }}
      }}

      function initializeStatFilters() {{
        const chips = document.querySelectorAll('.stat-filter[data-filter]');
        if (!chips.length) return;
        chips.forEach((chip) => {{
          if (chip.dataset.bound === '1') return;
          chip.dataset.bound = '1';
          chip.addEventListener('click', () => {{
            const target = chip.dataset.filter || 'all';
            chips.forEach((c) => c.classList.toggle('is-active', c === chip));
            applyStreamFilter(target);
          }});
        }});
      }}

      function activeFilterMode() {{
        const activeChip = document.querySelector('.stat-filter.is-active[data-filter]');
        return activeChip ? (activeChip.dataset.filter || 'all') : 'all';
      }}

      function parseStatCount(chip) {{
        if (!chip) return 0;
        const text = chip.textContent || '';
        const parts = text.split(':');
        if (parts.length < 2) return 0;
        const value = Number.parseInt(parts[1].trim(), 10);
        return Number.isNaN(value) ? 0 : value;
      }}

      function setStatCount(chip, label, value) {{
        if (!chip) return;
        const safeValue = Math.max(0, value);
        chip.textContent = label + ': ' + safeValue;
      }}

      function updateMissionCountersOnTransition(fromStatus, toStatus) {{
        if (fromStatus !== 'unscheduled' || toStatus !== 'scheduled') return;

        const scheduledChip = document.querySelector('.stat-filter[data-filter="scheduled"]');
        const unscheduledChip = document.querySelector('.stat-filter[data-filter="unscheduled"]');
        if (!scheduledChip || !unscheduledChip) return;

        const scheduledCount = parseStatCount(scheduledChip);
        const unscheduledCount = parseStatCount(unscheduledChip);
        setStatCount(scheduledChip, 'Scheduled', scheduledCount + 1);
        setStatCount(unscheduledChip, 'Unscheduled', unscheduledCount - 1);
      }}

      function appendActivityItem(title, detail) {{
        const list = document.getElementById('activity-log');
        if (!list) return;

        const item = document.createElement('li');
        item.className = 'activity-item';
        const now = new Date();
        const timestamp = now.toLocaleTimeString([], {{ hour: '2-digit', minute: '2-digit' }});
        item.innerHTML =
          '<p><strong>' + title + '</strong> <small>' + timestamp + '</small></p>' +
          '<p>' + detail + '</p>';
        list.prepend(item);
      }}

      function markDraftScheduled(button) {{
        const card = button ? button.closest('.draft-card.stream-item[data-stream-status="unscheduled"]') : null;
        if (!card) return;
        const previousStatus = card.dataset.streamStatus || '';

        const chip = card.querySelector('.status-chip');
        if (chip) {{
          chip.textContent = 'Scheduled';
          chip.classList.remove('status-pending');
          chip.classList.add('status-done');
        }}

        card.dataset.streamStatus = 'scheduled';
        card.classList.add('scheduled-item');
        card.classList.add('is-complete');
        updateMissionCountersOnTransition(previousStatus, 'scheduled');
        if (button) {{
          button.disabled = true;
          button.textContent = 'Marked Scheduled';
        }}

        const collapseBtn = card.querySelector('.toggle-draft-btn[data-target-body]');
        if (collapseBtn) {{
          const bodyId = collapseBtn.dataset.targetBody || '';
          const body = bodyId ? document.getElementById(bodyId) : null;
          if (body && !body.classList.contains('is-hidden')) {{
            toggleDraftBody(bodyId, collapseBtn);
          }}
        }}

        const service = card.dataset.serviceLabel || 'Service';
        const start = card.dataset.startLocal || '';
        const titleId = card.dataset.titleId || '';
        const titleField = titleId ? document.getElementById(titleId) : null;
        const title = titleField && 'value' in titleField ? (titleField.value || '').trim() : '';

        const panel = document.getElementById('panel-scheduled');
        if (panel) {{
          const emptyMsg = panel.querySelector('p');
          if (emptyMsg && /No already-scheduled services/i.test(emptyMsg.textContent || '')) {{
            panel.innerHTML = '';
          }}
          const compact = document.createElement('div');
          compact.className = 'scheduled-item stream-item';
          compact.dataset.streamStatus = 'scheduled';
          compact.innerHTML =
            '<p><strong>' + service + '</strong> <small>' + start + '</small></p>' +
            '<p>' + (title || 'Scheduled stream') + '</p>';
          panel.prepend(compact);
        }}

        appendActivityItem('Marked scheduled', service + (start ? ' at ' + start : ''));

        applyStreamFilter(activeFilterMode());
      }}

      function initializeTheme() {{
        const key = 'missionTheme';
        const btn = document.getElementById('theme-toggle');
        if (!btn) return;

        const applyTheme = (theme) => {{
          const dark = theme === 'dark';
          document.body.classList.toggle('theme-dark', dark);
          btn.textContent = dark ? 'Switch to Light' : 'Switch to Dark';
        }};

        const saved = localStorage.getItem(key) || 'light';
        applyTheme(saved);
        btn.addEventListener('click', () => {{
          const dark = document.body.classList.contains('theme-dark');
          const next = dark ? 'light' : 'dark';
          localStorage.setItem(key, next);
          applyTheme(next);
        }});
      }}


      function updateTitleFromOptions(changedCheckbox) {{
        if (!changedCheckbox) return;

        const targetTitleId = changedCheckbox.dataset.targetTitle;
        const targetCountId = changedCheckbox.dataset.targetCount;
        const targetCopyId = changedCheckbox.dataset.targetCopy;
        const targetDescId = changedCheckbox.dataset.targetDesc;
        const targetDescCountId = changedCheckbox.dataset.targetDescCount;
        const baseTitle = changedCheckbox.dataset.baseTitle || '';
        if (!targetTitleId || !targetCountId || !targetCopyId) return;

        const titleField = document.getElementById(targetTitleId);
        const descField = targetDescId ? document.getElementById(targetDescId) : null;
        const titleEdited = titleField && titleField.dataset.manuallyEdited === '1';
        const descEdited = descField && descField.dataset.manuallyEdited === '1';
        if (titleEdited || descEdited) {{
          if (!confirm('This will overwrite your manual edits to the title/description. Continue?')) {{
            changedCheckbox.checked = !changedCheckbox.checked;
            return;
          }}
          if (titleField) titleField.dataset.manuallyEdited = '';
          if (descField) descField.dataset.manuallyEdited = '';
        }}

        const checkboxes = document.querySelectorAll('input.title-opt[data-target-title="' + targetTitleId + '"]');
        const selected = [];
        checkboxes.forEach((cb) => {{
          if (cb.checked && cb.value && cb.value.trim()) selected.push(cb.value.trim());
        }});

        let title = baseTitle;
        if (selected.length > 0) {{
          title = selected.join('; ') + ' • ' + baseTitle;
        }}

        const countField = document.getElementById(targetCountId);
        const copyBtn = document.getElementById(targetCopyId);
        if (!titleField || !countField || !copyBtn) return;

        titleField.value = title;
        const len = title.length;
        countField.textContent = len + '/100';
        const overLimit = len > 100;
        countField.classList.toggle('over-limit', overLimit);
        copyBtn.disabled = overLimit;

        // Keep description first line in sync with title.
        if (targetDescId && descField) {{
            descField.value = title;
            if (targetDescCountId) {{
              const descCount = document.getElementById(targetDescCountId);
              if (descCount) descCount.textContent = descField.value.length + '/5000';
            }}
        }}
      }}

      function initializeTitleBuilders() {{
        const seen = new Set();
        document.querySelectorAll('input.title-opt').forEach((cb) => {{
          const id = cb.dataset.targetTitle || '';
          if (!id || seen.has(id)) return;
          seen.add(id);
          updateTitleFromOptions(cb);
        }});
      }}

      function initializeManualEditTracking() {{
        document.querySelectorAll('textarea[id^="cov-title-"], textarea[id^="cov-desc-"]').forEach((ta) => {{
          if (ta.dataset.editBound === '1') return;
          ta.dataset.editBound = '1';
          ta.addEventListener('input', () => {{
            ta.dataset.manuallyEdited = '1';
          }});
          ta.addEventListener('input', () => {{
            const countId = ta.id.replace('cov-title-', 'cov-title-count-').replace('cov-desc-', 'cov-desc-count-');
            const limit = ta.id.startsWith('cov-title-') ? 100 : 5000;
            const countEl = document.getElementById(countId);
            if (countEl) {{
              const len = ta.value.length;
              countEl.textContent = len + '/' + limit;
              countEl.classList.toggle('over-limit', len > limit);
            }}
          }});
        }});
      }}

      async function copyFromId(fieldId, statusId) {{
        const field = document.getElementById(fieldId);
        const status = document.getElementById(statusId);
        if (!field || !status) return;

        const text = field.value || field.textContent || '';
        try {{
          if (navigator.clipboard && navigator.clipboard.writeText) {{
            await navigator.clipboard.writeText(text);
          }} else {{
            const wasReadonly = field.hasAttribute('readonly');
            if (wasReadonly) field.removeAttribute('readonly');
            field.select();
            document.execCommand('copy');
            if (wasReadonly) field.setAttribute('readonly', 'readonly');
          }}
          status.textContent = 'Copied';
          setTimeout(() => {{ status.textContent = ''; }}, 1400);
        }} catch (err) {{
          status.textContent = 'Copy failed';
        }}
      }}

      document.addEventListener('DOMContentLoaded', () => {{
        initializeTheme();
        initializeTabs();
        initializeCollapseButtons();
        initializeStatFilters();
        initializeTitleBuilders();
        initializeManualEditTracking();
        applyStreamFilter('all');
      }});
      window.addEventListener('pageshow', () => {{
        initializeTabs();
        initializeCollapseButtons();
        initializeStatFilters();
      }});
    </script>
  </head>
  <body data-config=\"{html.escape(config_name, quote=True)}\">
    <div class="run-shell">
      <div class="top-row">
        <h1>Run Complete</h1>
        <button id="theme-toggle" type="button" class="theme-btn">Switch to Dark</button>
      </div>
      <p><strong>Mode:</strong> {html.escape(mode_text)}</p>
      <p><a href=\"/\">Back</a></p>
      {content_html}
      <details>
        <summary>Show Raw JSON (optional)</summary>
        <pre>{html.escape(pretty)}</pre>
      </details>
    </div>
  </body>
</html>
"""
            self._send_html(HTTPStatus.OK, page)
        except Exception as exc:
            if _is_client_disconnect_error(exc):
                LOGGER.warning(
                    "Client disconnected while handling POST /run error=%s",
                    exc.__class__.__name__,
                )
                return
            page = f"""
<!doctype html>
<html>
  <head><meta charset=\"utf-8\" /><title>Run Failed</title></head>
  <body>
    <h1>Run Failed</h1>
    <p><a href=\"/\">Back</a></p>
    <h2>Error</h2>
    <pre>{html.escape(str(exc))}</pre>
  </body>
</html>
"""
            self._send_html(HTTPStatus.INTERNAL_SERVER_ERROR, page)


def main() -> int:
    parser = argparse.ArgumentParser(description="Manual trigger server for Facebook scheduler")
    parser.add_argument("--host", default="0.0.0.0", help="Host/IP to bind (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8777, help="Port to bind (default: 8777)")
    args = parser.parse_args()

    host = args.host
    port = args.port
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"Serving manual trigger at http://{host}:{port}")
    if host == "0.0.0.0":
        print(f"Try in browser: http://localhost:{port}")
    print("Use Ctrl+C to stop")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())