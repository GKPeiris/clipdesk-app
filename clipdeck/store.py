"""Bounded, private, local clipboard storage. No desktop dependencies."""
import base64
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
from html.parser import HTMLParser

MAX_ITEM = 8 * 1024 * 1024
MAX_TOTAL = 64 * 1024 * 1024
MAX_ITEMS = 1000
ALLOWED = {'text/plain', 'text/html', 'text/uri-list', 'image/png'}
DEFAULTS = dict(limit=100, retention=30, paused=False, images=True,
                background=True, auto_paste=False, hide_after_copy=True,
                theme='dark', autostart=False)


class PlainHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.hidden += 1
        elif tag in ('br', 'p', 'div', 'li'):
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain_html(value):
    parser = PlainHTML()
    parser.feed(value)
    return ''.join(parser.parts).strip()


def validate_formats(formats):
    if not isinstance(formats, dict) or not formats or set(formats) - ALLOWED:
        raise ValueError('Unsupported clipboard format')
    if any(not isinstance(v, bytes) for v in formats.values()):
        raise ValueError('Clipboard payload must be bytes')
    if sum(map(len, formats.values())) > MAX_ITEM:
        raise ValueError('This item exceeds the 8 MB limit')
    formats = {k: v for k, v in formats.items() if v}
    if not formats:
        raise ValueError('Empty clipboard item')
    if 'image/png' in formats and not formats['image/png'].startswith(b'\x89PNG\r\n\x1a\n'):
        raise ValueError('Invalid PNG image')
    for key, value in formats.items():
        if key.startswith('text/'):
            value.decode('utf-8')
    return formats


def encode_formats(formats):
    return json.dumps({k: base64.b64encode(v).decode('ascii') for k, v in formats.items()},
                      sort_keys=True, separators=(',', ':'))


def decode_formats(payload):
    obj = json.loads(payload) if isinstance(payload, str) else payload
    if not isinstance(obj, dict):
        raise ValueError('Invalid clipboard payload')
    return validate_formats({k: base64.b64decode(v, validate=True) for k, v in obj.items()})


def describe(formats):
    text = formats.get('text/plain', b'').decode('utf-8')
    if 'text/uri-list' in formats:
        uris = formats['text/uri-list'].decode('utf-8')
        return 'files', '\n'.join(x for x in uris.splitlines() if x and not x.startswith('#'))
    if 'image/png' in formats:
        return 'image', 'Image · PNG'
    if not text and 'text/html' in formats:
        text = plain_html(formats['text/html'].decode('utf-8'))
    if text.strip().startswith(('https://', 'http://')) and '\n' not in text.strip():
        return 'link', text
    return 'text', text


class Store:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.directory.chmod(0o700)
        self.config_path = self.directory / 'settings.json'
        self.settings = DEFAULTS.copy()
        try:
            saved = json.loads(self.config_path.read_text())
            for key, default in DEFAULTS.items():
                if key in saved and type(saved[key]) is type(default):
                    self.settings[key] = saved[key]
        except (OSError, ValueError, TypeError):
            pass
        self.settings['limit'] = max(10, min(500, self.settings['limit']))
        self.settings['retention'] = max(0, min(365, self.settings['retention']))
        self.db = sqlite3.connect(self.directory / 'history.sqlite3')
        (self.directory / 'history.sqlite3').chmod(0o600)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA secure_delete=ON')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY, digest TEXT NOT NULL UNIQUE,
                kind TEXT NOT NULL, preview TEXT NOT NULL, payload TEXT NOT NULL,
                size INTEGER NOT NULL, created REAL NOT NULL, used REAL NOT NULL,
                pinned INTEGER NOT NULL DEFAULT 0, title TEXT NOT NULL DEFAULT '');
            CREATE INDEX IF NOT EXISTS recent ON items(used DESC);
        ''')
        columns = {r['name'] for r in self.db.execute('PRAGMA table_info(items)')}
        if 'copied' not in columns:
            self.db.execute('ALTER TABLE items ADD COLUMN copied INTEGER NOT NULL DEFAULT 1')
            self.db.commit()
        self.prune()

    def save_settings(self):
        tmp = self.config_path.with_suffix('.tmp')
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as f:
            json.dump(self.settings, f, indent=2)
        tmp.replace(self.config_path)

    def add(self, formats, pinned=False, title='', now=None, copied=True):
        formats = validate_formats(formats)
        payload = encode_formats(formats)
        digest = hashlib.sha256(payload.encode()).hexdigest()
        kind, preview = describe(formats)
        stamp = time.time() if now is None else now
        size = sum(map(len, formats.values()))
        with self.db:
            existing = self.db.execute('SELECT id FROM items WHERE digest=?', (digest,)).fetchone()
            if existing:
                self.db.execute('UPDATE items SET used=?, pinned=MAX(pinned, ?), copied=MAX(copied, ?), title=CASE WHEN ? != \'\' THEN ? ELSE title END WHERE id=?',
                                (stamp, bool(pinned), bool(copied), title, title, existing['id']))
                return existing['id']
            pinned_count, pinned_size = self.db.execute('SELECT COUNT(*), COALESCE(SUM(size),0) FROM items WHERE pinned=1').fetchone()
            if pinned_count >= MAX_ITEMS or pinned_size + size > MAX_TOTAL:
                raise ValueError('Storage is full of pinned items. Remove some pins first.')
            result = self.db.execute('INSERT INTO items(digest,kind,preview,payload,size,created,used,pinned,title,copied) VALUES(?,?,?,?,?,?,?,?,?,?)',
                                    (digest, kind, preview, payload, size, stamp, stamp, bool(pinned), title[:200], bool(copied)))
            item_id = result.lastrowid
        self.prune()
        return item_id

    def prune(self):
        with self.db:
            days = self.settings['retention']
            if days:
                self.db.execute('DELETE FROM items WHERE pinned=0 AND used<?', (time.time() - days * 86400,))
            self.db.execute('DELETE FROM items WHERE id IN (SELECT id FROM items WHERE pinned=0 ORDER BY used DESC, id DESC LIMIT -1 OFFSET ?)',
                            (self.settings['limit'],))
            while True:
                count, size = self.db.execute('SELECT COUNT(*),COALESCE(SUM(size),0) FROM items').fetchone()
                if count <= MAX_ITEMS and size <= MAX_TOTAL:
                    break
                candidate = self.db.execute('SELECT id FROM items WHERE pinned=0 ORDER BY used,id LIMIT 1').fetchone()
                if not candidate:
                    break
                self.db.execute('DELETE FROM items WHERE id=?', (candidate['id'],))

    def list(self, query='', kind='all', pinned=False):
        clauses, args = [], []
        if query:
            clauses.append("(preview LIKE ? ESCAPE '\\' OR title LIKE ? ESCAPE '\\')")
            literal = query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
            args.extend([f'%{literal}%'] * 2)
        if kind != 'all':
            clauses.append('kind=?'); args.append(kind)
        if pinned:
            clauses.append('pinned=1')
        where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
        return self.db.execute('SELECT id,kind,preview,size,created,used,pinned,title,copied FROM items' + where + ' ORDER BY used DESC,id DESC', args).fetchall()

    def clipboard_items(self):
        return [row for row in self.list() if row['copied'] and row['kind'] in ('text', 'link', 'image')]

    def get(self, item_id):
        return self.db.execute('SELECT * FROM items WHERE id=?', (item_id,)).fetchone()

    def pin(self, item_id):
        with self.db:
            self.db.execute('UPDATE items SET pinned=1-pinned WHERE id=?', (item_id,))
        self.prune()

    def delete(self, item_id):
        with self.db:
            self.db.execute('DELETE FROM items WHERE id=?', (item_id,))

    def clear(self, include_pinned=False):
        with self.db:
            self.db.execute('DELETE FROM items' + ('' if include_pinned else ' WHERE pinned=0'))
        self.db.execute('VACUUM')

    def export_file(self, path):
        items = [dict(row) for row in self.db.execute('SELECT payload,pinned,title,copied FROM items ORDER BY used')]
        # Never follow a pre-existing symlink when exporting sensitive history.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w') as f:
            json.dump({'format': 'clipdeck', 'version': 1, 'items': items}, f, indent=2)
        return len(items)

    def import_file(self, path):
        if Path(path).stat().st_size > 96 * 1024 * 1024:
            raise ValueError('Import exceeds 96 MB')
        obj = json.loads(Path(path).read_text())
        if not isinstance(obj, dict) or obj.get('format') != 'clipdeck' or obj.get('version') != 1:
            raise ValueError('Choose a ClipDeck v1 JSON export')
        items = obj.get('items')
        if not isinstance(items, list) or len(items) > MAX_ITEMS:
            raise ValueError('Invalid or oversized item list')
        prepared = []
        size = 0
        for item in items:
            if not isinstance(item, dict) or type(item.get('pinned')) not in (bool, int) or not isinstance(item.get('title'), str):
                raise ValueError('Invalid history entry')
            formats = decode_formats(item['payload'])
            size += sum(map(len, formats.values()))
            if type(item.get('copied', True)) not in (int, bool):
                raise ValueError('Invalid copied flag')
            prepared.append((formats, bool(item['pinned']), item['title'], bool(item.get('copied', True))))
        if size > MAX_TOTAL:
            raise ValueError('Import exceeds the 64 MB history limit')
        # Use an in-memory transaction copy so a failed import cannot partially modify history.
        backup = sqlite3.connect(':memory:')
        self.db.backup(backup)
        try:
            for formats, pinned, title, copied in prepared:
                self.add(formats, pinned, title, copied=copied)
        except Exception:
            self.db.rollback()
            backup.backup(self.db)
            raise
        finally:
            backup.close()
        return len(prepared)

    def close(self):
        self.db.close()
