#!/usr/bin/env python3
import json
import subprocess
import os
import time
import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, quote
import html

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_FILE = os.path.join(BASE_DIR, 'template.html')
CSS_FILE = os.path.join(BASE_DIR, 'style.css')
LOGO_FILE = os.path.join(BASE_DIR, 'ytb-logo.png')

RESULTS_PER_PAGE = 35
RECOMMENDED_FETCH = 120
SEARCH_FETCH = 120
TAB_FETCH = 120
CHANNEL_FETCH = 120
CHANNEL_PL_FETCH = 60
DEFAULT_SORT = 'recent'
COOKIES_BROWSER = 'firefox'
CACHE_TTL = 300

_cache = {}

SEARCH_PREFIX_MAP = {
    'c': 'channel',
    'p': 'playlist',
    'v': 'video',
    's': 'short',
    'a': 'all',
}


# ---------- helpers ----------

def parse_search_prefix(raw):
    if not raw or not raw.startswith('/'):
        return None, raw
    body = raw[1:]
    if not body:
        return None, raw
    letter = body[0].lower()
    if letter not in SEARCH_PREFIX_MAP:
        return None, raw
    if len(body) > 1 and body[1] != ' ':
        return None, raw
    rest = body[2:].strip() if len(body) > 2 else ''
    return SEARCH_PREFIX_MAP[letter], rest


def is_playlist(entry):
    if entry.get('_type') == 'playlist':
        return True
    vid = str(entry.get('id', ''))
    if vid.startswith('UC') and len(vid) == 24:
        return False
    if entry.get('ie_key') != 'YoutubeTab':
        return False
    return vid[:2] in ('PL', 'UU', 'LL', 'FL', 'OL', 'RD', 'PU', 'SB')


def is_channel(entry):
    vid = str(entry.get('id', ''))
    if vid.startswith('UC') and len(vid) == 24:
        return True
    if entry.get('ie_key') != 'YoutubeTab':
        return False
    return not is_playlist(entry)


def is_short(entry):
    if is_channel(entry) or is_playlist(entry):
        return False
    dur = entry.get('duration')
    try:
        return dur is not None and 0 < int(dur) <= 60
    except (TypeError, ValueError):
        return False


def is_playlist_id(vid):
    if vid.startswith('UC') and len(vid) == 24:
        return False
    return vid[:2] in ('PL', 'UU', 'LL', 'FL', 'OL', 'RD', 'PU', 'SB')


def format_upload_date(s):
    if not s or len(s) != 8 or not s.isdigit():
        return ''
    try:
        d = datetime.datetime.strptime(s, '%Y%m%d')
    except ValueError:
        return ''
    days = (datetime.datetime.now() - d).days
    if days < 0:
        return ''
    if days < 1:
        return 'today'
    if days < 7:
        return f'{days}d ago'
    if days < 30:
        return f'{days // 7}w ago'
    if days < 365:
        return f'{days // 30}mo ago'
    return f'{days // 365}y ago'


def format_views(n):
    try:
        n = int(n)
    except (TypeError, ValueError):
        return ''
    if n < 1000:
        return f'{n} views'
    if n < 1_000_000:
        return f'{n/1000:.1f}K views'.replace('.0K', 'K')
    if n < 1_000_000_000:
        return f'{n/1_000_000:.1f}M views'.replace('.0M', 'M')
    return f'{n/1_000_000_000:.1f}B views'.replace('.0B', 'B')


def apply_sort(entries, mode):
    if mode == 'popular':
        with_val = [e for e in entries if e.get('view_count') is not None]
        without = [e for e in entries if e.get('view_count') is None]
        with_val.sort(key=lambda e: e['view_count'], reverse=True)
        return with_val + without
    if mode == 'older':
        dated = [e for e in entries if e.get('upload_date')]
        undated = [e for e in entries if not e.get('upload_date')]
        dated.sort(key=lambda e: e['upload_date'])
        return dated + undated
    dated = [e for e in entries if e.get('upload_date')]
    undated = [e for e in entries if not e.get('upload_date')]
    dated.sort(key=lambda e: e['upload_date'], reverse=True)
    return dated + undated


def run_ytdlp(url, extra=None):
    cmd = ['yt-dlp', url, '--dump-json', '--no-warnings',
           '--cookies-from-browser', COOKIES_BROWSER,
           '--extractor-args', 'youtubetab:approximate_date']
    if extra:
        cmd.extend(extra)
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return [json.loads(l) for l in result.stdout.strip().split('\n') if l]


def cached_fetch(url, extra=None):
    now = time.time()
    hit = _cache.get(url)
    if hit and now - hit[0] < CACHE_TTL:
        return hit[1]
    entries = run_ytdlp(url, extra)
    _cache[url] = (now, entries)
    return entries


# ---------- HTTP handler ----------

class Handler(BaseHTTPRequestHandler):

    def _send_file(self, path, content_type):
        if not os.path.exists(path):
            self.send_error(404)
            return
        with open(path, 'rb') as f:
            data = f.read()
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'max-age=86400')
        self.end_headers()
        self.wfile.write(data)

    def send_css(self):
        self._send_file(CSS_FILE, 'text/css; charset=utf-8')

    def send_logo(self):
        ext = os.path.splitext(LOGO_FILE)[1].lower()
        ctype = {
            '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
            '.svg': 'image/svg+xml', '.webp': 'image/webp', '.gif': 'image/gif',
        }.get(ext, 'application/octet-stream')
        self._send_file(LOGO_FILE, ctype)

    # ---------- routes ----------

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == '/style.css':
            return self.send_css()
        if parsed.path == '/ytb-logo.png':
            return self.send_logo()
        if parsed.path.startswith('/copy/'):
            return self.handle_copy(parsed)
        if parsed.path.startswith('/channel/'):
            return self.handle_channel(parsed)

        return self.handle_index(parsed)

    def handle_copy(self, parsed):
        vid_id = parsed.path.rsplit('/', 1)[-1]
        if vid_id:
            if is_playlist_id(vid_id):
                url = f"https://www.youtube.com/playlist?list={vid_id}"
            else:
                url = f"https://www.youtube.com/watch?v={vid_id}"
            try:
                subprocess.run(
                    ['xclip', '-selection', 'clipboard'],
                    input=url.encode(), check=True,
                    env={**os.environ,
                         'DISPLAY': os.environ.get('DISPLAY', ':0'),
                         'XAUTHORITY': os.environ.get('XAUTHORITY',
                                                      os.path.expanduser('~/.Xauthority'))}
                )
            except subprocess.CalledProcessError as e:
                print(f"xclip failed: {e}", flush=True)
            except FileNotFoundError:
                print("xclip not found in PATH", flush=True)

        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', '0')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()

    def handle_channel(self, parsed):
        channel_id = parsed.path.rsplit('/', 1)[-1]
        if not channel_id:
            self.send_error(404)
            return

        q = parse_qs(parsed.query)
        type_filter = q.get('type', ['all'])[0]
        sort_mode = q.get('sort', [DEFAULT_SORT])[0]
        if sort_mode not in ('recent', 'popular', 'older'):
            sort_mode = DEFAULT_SORT
        try:
            page = int(q.get('page', ['1'])[0])
        except ValueError:
            page = 1

        try:
            if type_filter == 'playlist':
                url = f'https://www.youtube.com/channel/{channel_id}/playlists'
                entries = cached_fetch(
                    url, ['--flat-playlist', '--playlist-end', str(CHANNEL_PL_FETCH)]
                )
            else:
                url = f'https://www.youtube.com/channel/{channel_id}/videos'
                entries = cached_fetch(
                    url, ['--flat-playlist', '--playlist-end', str(CHANNEL_FETCH)]
                )

            ch_name = ''
            if entries:
                ch_name = entries[0].get('channel') or entries[0].get('uploader') or ''
            if not ch_name:
                ch_name = f'Channel {channel_id[:12]}…'

            self.render_page('', entries, page=page, type_filter=type_filter,
                             sort_mode=sort_mode, heading=ch_name,
                             channel_id=channel_id)
        except subprocess.CalledProcessError as e:
            self.send_error(500, e.stderr or str(e))
        except Exception as e:
            self.send_error(500, str(e))

    def handle_index(self, parsed):
        q = parse_qs(parsed.query)

        if q.get('refresh', ['0'])[0] == '1':
            _cache.clear()

        raw_query = q.get('q', [''])[0]
        prefix_type, search_query = parse_search_prefix(raw_query)

        url_type = q.get('type', ['all'])[0]
        type_filter = prefix_type if prefix_type else url_type

        sort_mode = q.get('sort', [DEFAULT_SORT])[0]
        if sort_mode not in ('recent', 'popular', 'older'):
            sort_mode = DEFAULT_SORT

        try:
            page = int(q.get('page', ['1'])[0])
        except ValueError:
            page = 1

        try:
            if not search_query:
                if prefix_type:
                    label = {'playlist': 'Playlists',
                             'channel': 'Channels',
                             'video': 'Videos',
                             'short': 'Shorts',
                             'all': 'Search'}.get(type_filter, 'Search')
                    self.render_page(
                        raw_query, [], page=1, type_filter=type_filter,
                        sort_mode=sort_mode,
                        heading=f'{label} search — type a query after the prefix',
                        stripped_query=''
                    )
                    return
                entries = cached_fetch(
                    'https://www.youtube.com/feed/recommended',
                    ['--flat-playlist', '--playlist-end', str(RECOMMENDED_FETCH)]
                )
                self.render_page('', entries, page=page, type_filter=type_filter,
                                 sort_mode=sort_mode, heading='Recommended')
            else:
                if type_filter == 'channel':
                    url = (f'https://www.youtube.com/results?search_query='
                           f'{quote(search_query)}&sp=EgIQAg%3D%3D')
                    entries = cached_fetch(
                        url, ['--flat-playlist', '--playlist-end', str(TAB_FETCH)]
                    )
                elif type_filter == 'playlist':
                    url = (f'https://www.youtube.com/results?search_query='
                           f'{quote(search_query)}&sp=EgIQAw%3D%3D')
                    entries = cached_fetch(
                        url, ['--flat-playlist', '--playlist-end', str(TAB_FETCH)]
                    )
                else:
                    entries = cached_fetch(
                        f'ytsearch{SEARCH_FETCH}:{search_query}',
                        ['--flat-playlist']
                    )

                self.render_page(raw_query, entries, page=page,
                                 type_filter=type_filter,
                                 sort_mode=sort_mode,
                                 stripped_query=search_query)
        except subprocess.CalledProcessError as e:
            self.send_error(500, e.stderr or str(e))
        except Exception as e:
            self.send_error(500, str(e))

    # ---------- card builders ----------

    def _meta_line(self, channel, upload_date, views, fallback_dur=None):
        parts = []
        if channel:
            parts.append(html.escape(channel))
        views_str = format_views(views) if views else ''
        if views_str:
            parts.append(views_str)
        date_str = format_upload_date(upload_date)
        if date_str:
            parts.append(date_str)
        if not parts and fallback_dur:
            parts.append(fallback_dur)
        return ' • '.join(parts)

    def _video_card(self, v, query, page, type_filter, sort_mode, channel_id=None):
        title = html.escape(v.get('title') or 'Untitled')
        vid_id = html.escape(str(v.get('id', '')))
        channel = v.get('channel') or v.get('uploader') or ''
        duration = v.get('duration') or 0
        try:
            mins, secs = divmod(int(duration), 60)
            if mins >= 60:
                hrs, mins = divmod(mins, 60)
                dur_str = f"{hrs}h{mins}m"
            else:
                dur_str = f"{mins}:{secs:02d}"
        except (TypeError, ValueError):
            dur_str = ''
        thumb = f"https://i.ytimg.com/vi/{vid_id}/mqdefault.jpg"

        if channel_id:
            copy_url = (f"/copy/{vid_id}?channel={channel_id}"
                        f"&page={page}&type={type_filter}&sort={sort_mode}")
        else:
            copy_url = (f"/copy/{vid_id}?q={quote(query)}&page={page}"
                        f"&type={type_filter}&sort={sort_mode}")

        initial = (channel[:1] or '?').upper()
        palette = ['#e06060', '#e09040', '#d0b040', '#78b060',
                   '#40a8a8', '#5080d0', '#8060c0', '#b058a0']
        color = palette[sum(ord(c) for c in channel) % len(palette)] if channel else '#504945'
        duration_badge = (f'<span class="duration">{dur_str}</span>'
                          if dur_str else '')

        meta = self._meta_line(channel, v.get('upload_date'),
                               v.get('view_count'), fallback_dur=dur_str)

        return (
            f'<a class="card" target="copyframe" href="{copy_url}">'
            f'  <div class="thumb-wrap">'
            f'    <img loading="lazy" src="{thumb}" alt="">'
            f'    {duration_badge}'
            f'  </div>'
            f'  <div class="info">'
            f'    <div class="avatar" style="background:{color}">{html.escape(initial)}</div>'
            f'    <div class="text">'
            f'      <div class="title">{title}</div>'
            f'      <div class="meta">{meta}</div>'
            f'    </div>'
            f'  </div>'
            f'</a>'
        )

    def _playlist_card(self, p, query, page, type_filter, sort_mode, channel_id=None):
        pid = html.escape(str(p.get('id', '')))
        title = html.escape(p.get('title') or 'Playlist')
        creator = p.get('uploader') or p.get('channel') or ''
        count = p.get('playlist_count')

        thumbs = p.get('thumbnails') or []
        thumb = ''
        if thumbs:
            thumb = thumbs[-1].get('url', '')
        if thumb.startswith('//'):
            thumb = 'https:' + thumb
        if not thumb:
            thumb = 'https://i.ytimg.com/img/no_thumbnail.jpg'

        badge = 'Playlist'
        if count:
            badge = f'Playlist · {count}'

        if channel_id:
            copy_url = (f"/copy/{pid}?channel={channel_id}"
                        f"&page={page}&type={type_filter}&sort={sort_mode}")
        else:
            copy_url = (f"/copy/{pid}?q={quote(query)}&page={page}"
                        f"&type={type_filter}&sort={sort_mode}")

        initial = (creator[:1] or '?').upper()
        palette = ['#e06060', '#e09040', '#d0b040', '#78b060',
                   '#40a8a8', '#5080d0', '#8060c0', '#b058a0']
        color = palette[sum(ord(c) for c in creator) % len(palette)] if creator else '#504945'

        meta = html.escape(creator) if creator else 'Playlist'

        return (
            f'<a class="card" target="copyframe" href="{copy_url}">'
            f'  <div class="thumb-wrap">'
            f'    <img loading="lazy" src="{html.escape(thumb)}" alt="">'
            f'    <span class="duration playlist-badge">{badge}</span>'
            f'  </div>'
            f'  <div class="info">'
            f'    <div class="avatar" style="background:{color}">{html.escape(initial)}</div>'
            f'    <div class="text">'
            f'      <div class="title">{title}</div>'
            f'      <div class="meta">{meta}</div>'
            f'    </div>'
            f'  </div>'
            f'</a>'
        )

    def _channel_card(self, c):
        cid = html.escape(str(c.get('id', '')))
        cname = html.escape(c.get('title') or c.get('channel') or 'Channel')
        thumbs = c.get('thumbnails') or []
        cthumb = ''
        if thumbs:
            cthumb = thumbs[-1].get('url', '')
        elif c.get('thumbnail'):
            cthumb = c.get('thumbnail')
        if cthumb.startswith('//'):
            cthumb = 'https:' + cthumb
        img = (f'<img loading="lazy" src="{html.escape(cthumb)}" alt="">'
               if cthumb else '<div class="ch-ph"></div>')
        followers = c.get('channel_follower_count')
        meta = 'channel'
        if followers:
            meta = format_views(followers).replace(' views', '')
        return (
            f'<a class="ch-card" href="/channel/{cid}">'
            f'{img}'
            f'<div class="title">{cname}</div>'
            f'<div class="meta">{meta}</div>'
            f'</a>'
        )

    def _render_card(self, e, query, page, type_filter, sort_mode, channel_id=None):
        if is_playlist(e):
            return self._playlist_card(e, query, page, type_filter, sort_mode, channel_id)
        if is_channel(e):
            return self._channel_card(e)
        return self._video_card(e, query, page, type_filter, sort_mode, channel_id)

    # ---------- render ----------

    def render_page(self, query, entries=None, page=1, type_filter='all',
                    sort_mode=DEFAULT_SORT, heading='',
                    stripped_query=None, channel_id=None):
        entries = entries or []

        if stripped_query is None:
            stripped_query = query

        in_channel = bool(channel_id)

        # 1. type filter
        if type_filter == 'video':
            filtered = [e for e in entries
                        if not is_channel(e) and not is_playlist(e) and not is_short(e)]
        elif type_filter == 'short':
            filtered = [e for e in entries
                        if not is_channel(e) and not is_playlist(e) and is_short(e)]
        elif type_filter == 'playlist':
            filtered = [e for e in entries if is_playlist(e)]
        elif type_filter == 'channel':
            filtered = [e for e in entries if is_channel(e)]
        else:
            filtered = entries

        # 2. sort
        filtered = apply_sort(filtered, sort_mode)

        # 3. paginate
        total = len(filtered)
        total_pages = max(1, (total + RESULTS_PER_PAGE - 1) // RESULTS_PER_PAGE)
        page = max(1, min(page, total_pages))
        start = (page - 1) * RESULTS_PER_PAGE
        current = filtered[start:start + RESULTS_PER_PAGE]

        rows = ''.join(
            self._render_card(e, query, page, type_filter, sort_mode, channel_id)
            for e in current
        )

        heading_block = f'<h1>{html.escape(heading)}</h1>' if heading else ''

        # 4. pagination
        pagination = ''
        if total_pages > 1:
            parts = []
            for p in range(1, total_pages + 1):
                if p == page:
                    parts.append(f'<span class="current">{p}</span>')
                else:
                    if in_channel:
                        href = (f"/channel/{channel_id}?page={p}"
                                f"&type={type_filter}&sort={sort_mode}")
                    elif query:
                        href = (f"/?q={quote(query)}&page={p}"
                                f"&type={type_filter}&sort={sort_mode}")
                    else:
                        href = (f"/?page={p}"
                                f"&type={type_filter}&sort={sort_mode}")
                    parts.append(f'<a href="{href}">{p}</a>')
            pagination = '<div class="pagination">' + ' '.join(parts) + '</div>'

        # 5. type chips
        def type_btn(t, label):
            cls = 'active' if t == type_filter else ''
            if in_channel:
                href = f"/channel/{channel_id}?type={t}&sort={sort_mode}"
            elif stripped_query:
                href = f"/?q={quote(stripped_query)}&type={t}&sort={sort_mode}"
            else:
                href = f"/?type={t}&sort={sort_mode}"
            return f'<a class="{cls}" href="{href}">{label}</a>'

        type_filters = ('<div class="filters type-filters">'
                        + type_btn('all', 'All')
                        + type_btn('video', 'Videos')
                        + type_btn('short', 'Shorts')
                        + type_btn('playlist', 'Playlists')
                        + '</div>')

        # 6. sort chips (hidden until hover)
        def sort_href(s):
            if in_channel:
                return f"/channel/{channel_id}?type={type_filter}&sort={s}"
            if stripped_query:
                return (f"/?q={quote(stripped_query)}&type={type_filter}"
                        f"&sort={s}")
            return f"/?type={type_filter}&sort={s}"

        def sort_btn(s, label):
            cls = 'active' if s == sort_mode else ''
            return f'<a class="{cls}" href="{sort_href(s)}">{label}</a>'

        sort_filters = ('<div class="filters sort-filters">'
                        + sort_btn('recent', 'Recent')
                        + sort_btn('popular', 'Popular')
                        + sort_btn('older', 'Older')
                        + '</div>')

        filters = type_filters + sort_filters

        with open(TEMPLATE_FILE, 'r', encoding='utf-8') as f:
            template = f.read()

        output = (template
                  .replace('{{QUERY}}', html.escape(query))
                  .replace('{{HEADING_BLOCK}}', heading_block)
                  .replace('{{FILTERS}}', filters)
                  .replace('{{ROWS}}', rows)
                  .replace('{{PAGINATION}}', pagination))

        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(output.encode())


if __name__ == '__main__':
    port = 8080
    server = HTTPServer(('localhost', port), Handler)
    print(f"Serving on http://localhost:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.server_close()
