import os, re, ast, sys, json, math, time, glob, zlib, queue, codecs, base64, ctypes, msvcrt, struct, argparse, threading, traceback, contextlib, subprocess, collections
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, font as tkfont


def resolve(text):
    """UI texts can be callables (lambda: app.t(key)), so they follow a language change."""
    return text() if callable(text) else text


class LocalizedError(ValueError):
    """ValueError with a translation key, so the UI shows it in the selected language."""

    def __init__(self, key, **params):
        super().__init__(key)
        self.key = key
        self.params = params


# ---------- anti-aliased drawing ----------
# Tk's canvas draws ovals, polygons and curves without anti-aliasing (jagged edges). Shapes are rendered here as
# signed distance fields (negative inside, in pixels) into small RGBA PNGs, so each edge pixel gets partial alpha.

_AA_IMAGES = {}


def _rgb(color):
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))


def _png_data(w, h, rows):
    def chunk(tag, data):
        return struct.pack('>I', len(data)) + tag + data + struct.pack('>I', zlib.crc32(tag + data) & 0xFFFFFFFF)
    raw = b''.join(b'\x00' + bytes(row) for row in rows)
    png = (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0))
           + chunk(b'IDAT', zlib.compress(raw, 6)) + chunk(b'IEND', b''))
    return base64.b64encode(png).decode('ascii')


def aa_image(master, key, w, h, sdf, color):
    """Cached transparent image of size w x h: pixel (x, y) is covered where sdf(x + .5, y + .5) < 0."""
    key = (key, w, h, color)
    if key not in _AA_IMAGES:
        r, g, b = _rgb(color)
        rows = []
        for y in range(h):
            row = bytearray()
            for x in range(w):
                alpha = min(1.0, max(0.0, 0.5 - sdf(x + 0.5, y + 0.5)))
                row += bytes((r, g, b, round(alpha * 255)))
            rows.append(row)
        _AA_IMAGES[key] = tk.PhotoImage(master=master, data=_png_data(w, h, rows))
    return _AA_IMAGES[key]


def sd_box(px, py, cx, cy, hw, hh, r):
    qx, qy = abs(px - cx) - hw + r, abs(py - cy) - hh + r
    return math.hypot(max(qx, 0), max(qy, 0)) + min(max(qx, qy), 0) - r


def sd_segment(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - ax - t * dx, py - ay - t * dy)


def sd_convex(px, py, points):
    # max of the signed distances to each edge line (points clockwise on screen); exact enough for edge anti-aliasing
    d = -math.inf
    for (ax, ay), (bx, by) in zip(points, points[1:] + points[:1]):
        ex, ey = bx - ax, by - ay
        d = max(d, ((px - ax) * ey - (py - ay) * ex) / math.hypot(ex, ey))
    return d


def aa_round_rect(canvas, x1, y1, x2, y2, r, fill):
    """Rounded rectangle: anti-aliased end caps as images, the straight middle as a plain (already sharp) rectangle."""
    if not fill:
        return
    x1, y1 = round(x1), round(y1)
    w, h = max(1, round(x2) - x1), max(1, round(y2) - y1)
    r = max(0.0, min(r, w / 2, h / 2))
    cap = math.ceil(r)
    if w < 2 * cap + 1:
        img = aa_image(canvas, ('rr', r), w, h, lambda px, py: sd_box(px, py, w / 2, h / 2, w / 2, h / 2, r), fill)
        canvas.create_image(x1, y1, image=img, anchor='nw')
        return
    # with the box 2*cap wide, the first `cap` columns are exactly the left end of any wider box; the right end mirrors it
    left = aa_image(canvas, ('rr-l', r), cap, h, lambda px, py: sd_box(px, py, cap, h / 2, cap, h / 2, r), fill)
    right = aa_image(canvas, ('rr-r', r), cap, h, lambda px, py: sd_box(cap - px, py, cap, h / 2, cap, h / 2, r), fill)
    canvas.create_image(x1, y1, image=left, anchor='nw')
    canvas.create_image(x1 + w - cap, y1, image=right, anchor='nw')
    canvas.create_rectangle(x1 + cap, y1, x1 + w - cap, y1 + h, fill=fill, outline='')


def aa_circle(canvas, cx, cy, radius, fill):
    size = math.ceil(radius * 2) + 2
    img = aa_image(canvas, ('circle', radius), size, size, lambda px, py: math.hypot(px - size / 2, py - size / 2) - radius, fill)
    canvas.create_image(round(cx - size / 2), round(cy - size / 2), image=img, anchor='nw')


def draw_icon(canvas, kind, cx, cy, r, color, under, scale):
    """Small vector glyphs for buttons (play, stop, refresh, moon, sun, eye, copy), drawn anti-aliased."""
    width = max(1.0, 1.6 * scale)
    half = width / 2
    size = math.ceil(r * 2.4) + 2
    c = size / 2

    if kind == 'play':
        tri = [(c - r * 0.55, c - r * 0.85), (c + r * 0.85, c), (c - r * 0.55, c + r * 0.85)]
        sdf = lambda px, py: sd_convex(px, py, tri) - 0.4
    elif kind == 'stop':
        sdf = lambda px, py: sd_box(px, py, c, c, r * 0.7, r * 0.7, r * 0.25)
    elif kind == 'refresh':
        radius = r * 0.85
        head_len, head_w = 5 * scale, 2.5 * scale + half
        end = (c + radius, c)
        start_deg, end_deg = 70, 360 - math.degrees(4 * scale / radius)

        def sdf(px, py):
            deg = math.degrees(math.atan2(c - py, px - c)) % 360
            if start_deg <= deg <= end_deg:
                arc = abs(math.hypot(px - c, py - c) - radius)
            else:
                ends = [(c + radius * math.cos(math.radians(a)), c - radius * math.sin(math.radians(a))) for a in (start_deg, end_deg)]
                arc = min(math.hypot(px - ex, py - ey) for ex, ey in ends)
            # arrow head pointing up (the arc's direction at 360 degrees)
            head = sd_convex(px, py, [(end[0], end[1] - head_len * 0.35), (end[0] + head_w, end[1] + head_len * 0.65),
                                      (end[0] - head_w, end[1] + head_len * 0.65)])
            return min(arc - half, head)
    elif kind == 'moon':
        sdf = lambda px, py: max(math.hypot(px - c, py - c) - r * 0.85, -(math.hypot(px - c - r * 0.3, py - c + r * 0.3) - r * 0.75))
    elif kind == 'sun':
        rays = [(c + r * 0.68 * math.cos(math.radians(i * 45)), c + r * 0.68 * math.sin(math.radians(i * 45)),
                 c + r * 0.98 * math.cos(math.radians(i * 45)), c + r * 0.98 * math.sin(math.radians(i * 45))) for i in range(8)]
        sdf = lambda px, py: min([math.hypot(px - c, py - c) - r * 0.42] + [sd_segment(px, py, *ray) - half for ray in rays])
    elif kind == 'eye':
        sdf = lambda px, py: min(abs((math.hypot((px - c) / r, (py - c) / (r * 0.6)) - 1) * r * 0.6) - half,
                                 math.hypot(px - c, py - c) - r * 0.3)
    elif kind in ('alert', 'info'):
        # '!' and 'i' as shapes: drawn as text, ClearType adds colored fringes on the tinted circle
        stroke, dot = r * 0.13, r * 0.15
        if kind == 'alert':
            bar, dot_y = (c - r * 0.55, c + r * 0.12), c + r * 0.5
        else:
            bar, dot_y = (c - r * 0.1, c + r * 0.55), c - r * 0.5
        sdf = lambda px, py: min(sd_segment(px, py, c, bar[0], c, bar[1]) - stroke, math.hypot(px - c, py - dot_y) - dot)
    elif kind == 'copy':
        back = lambda px, py: sd_box(px, py, c - r * 0.25, c + r * 0.15, r * 0.6, r * 0.7, r * 0.2)
        front = lambda px, py: sd_box(px, py, c + r * 0.25, c - r * 0.25, r * 0.6, r * 0.7, r * 0.2)
        # the back sheet is hidden behind the front one (instead of painting the front with the background color)
        sdf = lambda px, py: min(max(abs(back(px, py)) - half, -(front(px, py) + half)), abs(front(px, py)) - half)
    else:
        return
    img = aa_image(canvas, ('icon', kind, r, scale), size, size, sdf, color)
    canvas.create_image(round(cx - c), round(cy - c), image=img, anchor='nw')


class RoundButton(tk.Canvas):
    """Minimal button: no border, soft background only on hover (variants: ghost, accent, danger)."""

    def __init__(self, master, app, text, command, variant='ghost', bg_key='bg', size=10, icon=None):
        self.app = app
        self.text = text
        self.icon = icon
        self.command = command
        self.variant = variant
        self.bg_key = bg_key
        self.hover = False
        self.disabled = False
        self.font = tkfont.Font(family='Segoe UI Semibold', size=size)
        self.h = self.font.metrics('linespace') + int(12 * app.scale)
        super().__init__(master, height=self.h, width=self._width(), highlightthickness=0, bd=0, cursor='hand2')
        self.bind('<Enter>', lambda e: self._set_hover(True))
        self.bind('<Leave>', lambda e: self._set_hover(False))
        self.bind('<ButtonRelease-1>', self._click)
        app.register(self, self.redraw)

    def _width(self):
        s = self.app.scale
        if not self.text:
            return self.h
        icon_w = int(18 * s) if self.icon else 0
        return self.font.measure(resolve(self.text)) + icon_w + int(24 * s)

    def _set_hover(self, value):
        self.hover = value
        self.redraw()

    def _click(self, event):
        if self.hover and not self.disabled:
            self.command()

    def set(self, text=None, icon=None):
        self.text = self.text if text is None else text
        self.icon = icon
        self.configure(width=self._width())
        self.redraw()

    def set_disabled(self, value):
        self.disabled = value
        self.configure(cursor='arrow' if value else 'hand2')
        self.redraw()

    def redraw(self):
        c, s = self.app.colors, self.app.scale
        bg = c[self.bg_key]
        if self.disabled:
            fill, fg = '', c['faint']
        elif self.variant == 'accent':
            fill = c['accent'] if self.hover else c['accent_soft']
            fg = c['on_accent'] if self.hover else c['accent']
        elif self.variant == 'danger':
            fill = c['error_soft'] if self.hover else ''
            fg = c['error']
        else:
            fill = c['hover'] if self.hover else ''
            fg = c['text'] if self.hover else c['muted']
        if self.hover and self.variant == 'ghost' and self.bg_key == 'hover':
            fill = c['border']
        w = self._width()
        self.configure(bg=bg, width=w)
        self.delete('all')
        aa_round_rect(self, 0, 0, w, self.h, 7 * s, fill)
        under = fill or bg
        if self.text:
            x = int(12 * s)
            if self.icon:
                draw_icon(self, self.icon, x + 6 * s, self.h / 2, 6 * s, fg, under, s)
                x += int(18 * s)
            self.create_text(x, self.h / 2, text=resolve(self.text), font=self.font, fill=fg, anchor='w')
        else:
            draw_icon(self, self.icon, w / 2, self.h / 2, 7 * s, fg, under, s)


class InfoIcon(tk.Canvas):
    """Round '!' / 'i' badge that explains why a bot can't run (or its warnings)."""

    def __init__(self, master, app, level, command, bg_key='surface'):
        self.app = app
        self.level = level
        self.command = command
        self.bg_key = bg_key
        self.hover = False
        self.size = int(22 * app.scale)
        super().__init__(master, width=self.size, height=self.size, highlightthickness=0, bd=0, cursor='hand2')
        self.bind('<Enter>', lambda e: self._set_hover(True))
        self.bind('<Leave>', lambda e: self._set_hover(False))
        self.bind('<ButtonRelease-1>', lambda e: self.hover and self.command())
        app.register(self, self.redraw)

    def _set_hover(self, value):
        self.hover = value
        self.redraw()

    def redraw(self):
        c = self.app.colors
        n = self.size
        self.configure(bg=c[self.bg_key])
        self.delete('all')
        fill = c[self.level] if self.hover else c[f'{self.level}_soft']
        fg = c['on_accent'] if self.hover else c[self.level]
        aa_circle(self, n / 2, n / 2, n / 2 - 1, fill)
        draw_icon(self, 'alert' if self.level == 'error' else 'info', n / 2, n / 2, n / 2 - 1, fg, fill, self.app.scale)


class Pill(tk.Canvas):
    """Status badge: soft tinted background, colored dot and text."""

    def __init__(self, master, app, text, kind, bg_key='bg'):
        self.app = app
        self.text = text
        self.kind = kind
        self.bg_key = bg_key
        self.font = tkfont.Font(family='Segoe UI Semibold', size=9)
        self.h = self.font.metrics('linespace') + int(10 * app.scale)
        super().__init__(master, height=self.h, highlightthickness=0, bd=0)
        app.register(self, self.redraw)

    def set(self, text, kind):
        self.text, self.kind = text, kind
        self.redraw()

    def redraw(self):
        c, s = self.app.colors, self.app.scale
        text = resolve(self.text)
        w = self.font.measure(text) + int(34 * s)
        self.configure(width=w, bg=c[self.bg_key])
        self.delete('all')
        aa_round_rect(self, 0, 0, w, self.h, self.h / 2, c[f'{self.kind}_soft'])
        cy = self.h / 2
        aa_circle(self, 13 * s, cy, 3.5 * s, c[self.kind])
        self.create_text(23 * s, cy, text=text, font=self.font, fill=c[self.kind], anchor='w')


class RoundBar(tk.Canvas):
    """Rounded progress bar (0-100)."""

    def __init__(self, master, app, bg_key='surface'):
        self.app = app
        self.bg_key = bg_key
        self.value = 0
        self.h = int(10 * app.scale)
        super().__init__(master, height=self.h, highlightthickness=0, bd=0)
        self.bind('<Configure>', lambda e: self.redraw())
        app.register(self, self.redraw)

    def set(self, value):
        self.value = value
        self.redraw()

    def redraw(self):
        c = self.app.colors
        w = self.winfo_width()
        self.configure(bg=c[self.bg_key])
        self.delete('all')
        if w <= 1:
            return
        aa_round_rect(self, 0, 0, w, self.h, self.h / 2, c['track'])
        if self.value > 0:
            fill_w = max(self.h, w * self.value / 100)
            aa_round_rect(self, 0, 0, fill_w, self.h, self.h / 2, c['accent'])


class RoundCorners:
    """Rounds a frame (Tk frames are always square): a small canvas over each corner paints the parent's background
    outside the arc, the 1 px border arc (the frame's highlight border is the straight part) and the frame's fill."""

    def __init__(self, app, frame, radius=12, border=True):
        self.app = app
        self.frame = frame
        self.border = border
        self.border_key = 'border'
        self.r = max(3, round(radius * app.scale))
        self.corners = []
        for relx, rely, anchor in ((0, 0, 'nw'), (1, 0, 'ne'), (0, 1, 'sw'), (1, 1, 'se')):
            canvas = tk.Canvas(frame, width=self.r, height=self.r, highlightthickness=0, bd=0)
            canvas.place(relx=relx, rely=rely, anchor=anchor, bordermode='ignore')
            self.corners.append((canvas, anchor))
        # children packed later are stacked above the corners: raise them again once the frame is laid out
        tk.Misc.bind(frame, '<Configure>', lambda e: self.lift(), '+')
        frame.after_idle(self.lift)
        app.register(self.corners[0][0], self.redraw)

    def lift(self):
        for canvas, _ in self.corners:
            tk.Misc.tkraise(canvas)

    def redraw(self):
        c, r = self.app.colors, self.r
        outer = c[getattr(self.frame.master, 'bg_key', 'bg')]
        fill = c[self.frame.bg_key]
        for canvas, anchor in self.corners:
            canvas.configure(bg=outer)
            canvas.delete('all')
            # the corner is one quadrant of a 2r circle shifted into the canvas
            x = 0 if 'w' in anchor else -r
            y = 0 if 'n' in anchor else -r
            if self.border:
                aa_round_rect(canvas, x, y, x + 2 * r, y + 2 * r, r, c[self.border_key])
                aa_round_rect(canvas, x + 1, y + 1, x + 2 * r - 1, y + 2 * r - 1, r - 1, fill)
            else:
                aa_round_rect(canvas, x, y, x + 2 * r, y + 2 * r, r, fill)


class RoundField(tk.Frame):
    """Rounded box around an input (Entry or Combobox) with the accent border while it has the focus. It's what callers
    pack; `widget` is the input, and bind / focus_set go to it."""

    def __init__(self, app, master, bg_key='surface', radius=8):
        self.app = app
        self.bg_key = bg_key
        self.focused = False
        super().__init__(master, bd=0, highlightthickness=1, padx=int(6 * app.scale), pady=int(1 * app.scale))
        self.corners = RoundCorners(app, self, radius)
        self.widget = None
        app.register(self, self.redraw)

    def attach(self, widget):
        self.widget = widget
        widget.pack(fill='both', expand=True)
        widget.bind('<FocusIn>', lambda e: self._set_focus(True), '+')
        widget.bind('<FocusOut>', lambda e: self._set_focus(False), '+')
        return self

    def _set_focus(self, value):
        self.focused = value
        self.redraw()

    def redraw(self):
        c = self.app.colors
        border = c['accent'] if self.focused else c['border']
        self.configure(bg=c[self.bg_key], highlightbackground=border, highlightcolor=border)
        self.corners.border_key = 'accent' if self.focused else 'border'
        self.corners.redraw()

    def bind(self, *args, **kwargs):
        return self.widget.bind(*args, **kwargs)

    def focus_set(self):
        self.widget.focus_set()


class IssuesDialog:
    """Modal popup listing why a bot can't run from the app (errors) or what to expect (warnings)."""

    def __init__(self, app, project):
        self.app = app
        s = app.scale
        blocking = not project['runnable']

        self.top = tk.Toplevel(app.root)
        self.top.withdraw()
        self.top.title(f"{project['name']} - {app.config['APP_NAME']}")
        self.top.transient(app.root)
        self.top.resizable(False, False)
        app.register(self.top, lambda: self.top.configure(bg=app.colors['bg']))

        root = app.frame(self.top, 'bg', padx=24, pady=20)
        root.pack(fill='both', expand=True)

        header = app.frame(root, 'bg')
        header.pack(fill='x')
        InfoIcon(header, app, 'error' if blocking else 'warning', lambda: None, bg_key='bg').pack(side='left', padx=(0, 12))
        titles = app.frame(header, 'bg')
        titles.pack(side='left', fill='x', expand=True)
        title = app.t('issues.blocking') if blocking else app.t('issues.warnings')
        app.label(titles, title, 'h1', 'bg').pack(anchor='w')
        app.label(titles, project['name'], 'muted', 'bg').pack(anchor='w')

        for issue in project['issues']:
            self._issue(root, issue)

        footer = app.frame(root, 'bg')
        footer.pack(fill='x', pady=(18, 0))
        RoundButton(footer, app, app.t('issues.close'), self.close, variant='accent').pack(side='right')

        self.top.bind('<Escape>', lambda e: self.close())
        self.top.bind('<Return>', lambda e: self.close())
        self.top.update_idletasks()
        w, h = self.top.winfo_reqwidth(), self.top.winfo_reqheight()
        x = app.root.winfo_rootx() + (app.root.winfo_width() - w) // 2
        y = app.root.winfo_rooty() + max(0, (app.root.winfo_height() - h) // 3)
        self.top.geometry(f'+{max(0, x)}+{max(0, y)}')
        self.top.deiconify()
        app.style_window(self.top)
        self.top.grab_set()
        self.top.focus_force()

    def _issue(self, master, issue):
        app = self.app
        card = app.card(master, padx=8, pady=8)
        card.pack(fill='x', pady=(12, 0))
        # rounded colored strip (error / warning) at the left of the card
        bar = tk.Canvas(card, width=int(4 * app.scale), highlightthickness=0, bd=0)

        def draw_bar():
            w = int(4 * app.scale)
            bar.configure(bg=app.colors['surface'])
            bar.delete('all')
            aa_round_rect(bar, 0, 0, w, max(w, bar.winfo_height()), w / 2, app.colors[issue['level']])

        bar.bind('<Configure>', lambda e: draw_bar())
        app.register(bar, draw_bar)
        bar.pack(side='left', fill='y', pady=4)
        content = app.frame(card, 'surface', padx=8, pady=4)
        content.pack(side='left', fill='both', expand=True)
        app.label(content, issue['title'], 'h2', 'surface').pack(anchor='w')
        detail = app.label(content, issue['detail'], 'body', 'surface')
        detail.configure(wraplength=int(440 * app.scale))
        detail.pack(anchor='w', pady=(4, 0))
        if issue.get('command'):
            cmd = app.soft_box(content, 'track', padx=10, pady=6)
            cmd.pack(fill='x', pady=(10, 0))
            # shown one step per line, copied as a single PowerShell line
            btn = RoundButton(cmd, app, app.t('issues.copy'), lambda: self._copy('; '.join(issue['command']), btn), bg_key='track', size=9, icon='copy')
            btn.pack(side='right', anchor='n')
            code = app.label(cmd, '\n'.join(issue['command']), 'mono', 'track')
            code.configure(wraplength=int(340 * app.scale))
            code.pack(side='left', fill='x', expand=True)

    def _copy(self, text, btn):
        self.app.root.clipboard_clear()
        self.app.root.clipboard_append(text)
        btn.set(self.app.t('issues.copied'), 'copy')
        self.top.after(1500, lambda: btn.winfo_exists() and btn.set(self.app.t('issues.copy'), 'copy'))

    def close(self):
        self.top.grab_release()
        self.top.destroy()


class ProjectConfig:
    """Reads the config.json / .env files a bot's Pipeline loads and writes back only the edited keys."""

    SOURCE_NAMES = ('filename_args_json', 'filename_args_env')
    SECRET_RE = re.compile(r'PASS|PWD|SECRET|TOKEN|API_?KEY|CREDENTIAL', re.I)
    ENV_LINE_RE = re.compile(r'^(\s*(?:export\s+)?)([A-Za-z_][\w.-]*)(\s*=\s*)(.*)$')

    def __init__(self, project, projects_path):
        self.files = []
        json_rels, env_rels = self.find_sources(project['main'])
        src = os.path.dirname(project['main'])
        hdfs = os.path.dirname(projects_path)
        for kind, rels in (('json', json_rels), ('env', env_rels)):
            for rel in rels:
                path = os.path.normpath(os.path.join(src, rel))
                shared = not path.startswith(project['path'] + os.sep)
                label = os.path.relpath(path, hdfs if shared else project['path']).replace('\\', '/')
                self.files.append(self._load_file(len(self.files), path, label, kind, shared))

        # same precedence as Pipeline: json files in order, then env files in order; the last one wins
        winner = {}
        for f in self.files:
            for key in f['entries']:
                winner[key] = f['label']
        for f in self.files:
            for key, entry in f['entries'].items():
                entry['overridden_by'] = winner[key] if winner[key] != f['label'] else None

    def _load_file(self, index, path, label, kind, shared):
        f = {'path': path, 'label': label, 'kind': kind, 'shared': shared, 'exists': os.path.isfile(path),
             'error': None, 'mtime': None, 'entries': {}}
        if not f['exists']:
            return f
        f['mtime'] = os.path.getmtime(path)
        raw = self._read(path)
        try:
            if kind == 'json':
                data = json.loads(raw)
                if not isinstance(data, dict):
                    raise LocalizedError('error.not_json_object')
                pairs = list(data.items())
            else:
                pairs = [(k, v) for k, v, _ in self.parse_env(raw)]
        except ValueError as err:
            f['error'] = err
            return f
        for i, (key, value) in enumerate(pairs):
            f['entries'][key] = {'iid': f'{index}:{i}', 'file': index, 'key': key, 'kind': kind,
                                 'original': value, 'value': value, 'secret': bool(self.SECRET_RE.search(key))}
        return f

    @classmethod
    def find_sources(cls, main_path):
        with open(main_path, encoding='utf-8-sig', errors='replace') as fh:
            source = fh.read()
        try:
            tree = ast.parse(source)
        except SyntaxError:
            tree = ast.Module(body=[], type_ignores=[])
        found = {}
        for node in ast.walk(tree):
            pairs = []
            if isinstance(node, ast.Assign):
                pairs = [(t.id, node.value) for t in node.targets if isinstance(t, ast.Name)]
            elif isinstance(node, ast.keyword):
                pairs = [(node.arg, node.value)]
            for name, value in pairs:
                if name in cls.SOURCE_NAMES and name not in found:
                    try:
                        literal = ast.literal_eval(value)
                    except ValueError:
                        continue
                    found[name] = [literal] if isinstance(literal, str) else list(literal)
        return (found.get('filename_args_json', ['../config/config.json']),
                found.get('filename_args_env', ['../config/.env']))

    @classmethod
    def parse_env(cls, text):
        result = []
        for line in text.splitlines():
            match = cls.ENV_LINE_RE.match(line)
            if not match or line.strip().startswith('#'):
                continue
            value = match.group(4).strip()
            quote = ''
            if value[:1] in ('"', "'"):
                end = value.find(value[0], 1)
                if end > 0:
                    quote, value = value[0], value[1:end]
            else:
                value = re.split(r'\s+#', value, maxsplit=1)[0].strip()
            result.append((match.group(2), value, quote))
        return result

    @classmethod
    def update_env(cls, text, changes):
        lines = text.splitlines(keepends=True)
        for i, line in enumerate(lines):
            body = line.rstrip('\r\n')
            match = cls.ENV_LINE_RE.match(body)
            if not match or body.strip().startswith('#') or match.group(2) not in changes:
                continue
            old = match.group(4).strip()
            new = changes[match.group(2)]
            quote = old[0] if old[:1] in ('"', "'") else ''
            if not quote and re.search(r'[\s#"\']', new):
                quote = '"'
            if quote and quote in new:
                quote = "'" if quote == '"' and "'" not in new else '"'
                new = new.replace('"', '\\"') if quote == '"' else new
            lines[i] = f'{match.group(1)}{match.group(2)}{match.group(3)}{quote}{new}{quote}{line[len(body):]}'
        return ''.join(lines)

    @staticmethod
    def json_spans(text):
        decoder, ws = json.JSONDecoder(), re.compile(r'\s*')
        i = ws.match(text, 0).end()
        if text[i] != '{':
            raise LocalizedError('error.not_json_object')
        i = ws.match(text, i + 1).end()
        spans = {}
        while text[i] != '}':
            key, i = decoder.raw_decode(text, i)
            i = ws.match(text, i).end() + 1
            start = ws.match(text, i).end()
            _, end = decoder.raw_decode(text, start)
            spans[key] = (start, end)
            i = ws.match(text, end).end()
            if text[i] == ',':
                i = ws.match(text, i + 1).end()
        return spans

    @classmethod
    def update_json(cls, text, changes):
        # replaces only the edited values, so the rest of the file keeps its hand-made formatting
        spans = cls.json_spans(text)
        unit = re.search(r'\n([ \t]+)"', text)
        unit = len(unit.group(1)) if unit else 4
        for key in sorted(changes, key=lambda k: spans[k][0], reverse=True):
            start, end = spans[key]
            value = changes[key]
            line_start = text.rfind('\n', 0, start) + 1
            indent = re.match(r'[ \t]*', text[line_start:]).group(0)
            # a value written on one line stays on one line; a multi-line one is re-indented
            multiline = isinstance(value, (dict, list)) and '\n' in text[start:end]
            dumped = json.dumps(value, ensure_ascii=False, indent=unit if multiline else None)
            text = text[:start] + dumped.replace('\n', '\n' + indent) + text[end:]
        json.loads(text)
        return text

    @staticmethod
    def same(a, b):
        return json.dumps(a, ensure_ascii=False) == json.dumps(b, ensure_ascii=False)

    def entries(self):
        return [e for f in self.files for e in f['entries'].values()]

    def changes(self):
        return [e for e in self.entries() if not self.same(e['value'], e['original'])]

    def save(self):
        by_file = {}
        for entry in self.changes():
            by_file.setdefault(entry['file'], {})[entry['key']] = entry['value']
        for index, changes in by_file.items():
            f = self.files[index]
            if os.path.getmtime(f['path']) != f['mtime']:
                raise LocalizedError('error.changed_on_disk', file=f['label'])
            raw = self._read(f['path'])
            new = self.update_json(raw, changes) if f['kind'] == 'json' else self.update_env(raw, changes)
            with open(f['path'], 'rb') as fh:
                bom = fh.read(3) == codecs.BOM_UTF8
            tmp = f['path'] + '.tmp'
            with open(tmp, 'w', encoding='utf-8-sig' if bom else 'utf-8', newline='') as fh:
                fh.write(new)
            os.replace(tmp, f['path'])

    @staticmethod
    def _read(path):
        with open(path, encoding='utf-8-sig', newline='') as fh:
            return fh.read()


class JsonEditor:
    """Modal editor for list/dict values of config.json."""

    def __init__(self, app, parent, entry, on_save):
        self.app = app
        self.on_save = on_save
        self.top = tk.Toplevel(parent)
        self.top.withdraw()
        self.top.title(f"{entry['key']} - {app.config['APP_NAME']}")
        self.top.transient(parent)
        self.top.geometry(f'{int(620 * app.scale)}x{int(460 * app.scale)}')
        app.register(self.top, lambda: self.top.configure(bg=app.colors['bg']))

        root = app.frame(self.top, 'bg', padx=20, pady=18)
        root.pack(fill='both', expand=True)
        app.label(root, entry['key'], 'h1', 'bg').pack(anchor='w')
        app.label(root, app.t('json.hint'), 'muted', 'bg').pack(anchor='w')

        footer = app.frame(root, 'bg')
        footer.pack(side='bottom', fill='x', pady=(12, 0))
        RoundButton(footer, app, app.t('json.save'), self.save, variant='accent').pack(side='right')
        RoundButton(footer, app, app.t('config.cancel'), self.close).pack(side='right', padx=(0, 6))
        self.lbl_error = app.label(footer, '', 'muted', 'bg')
        self.lbl_error.fg_key = 'error'
        app.apply_widget(self.lbl_error)
        self.lbl_error.pack(side='left', fill='x', expand=True)

        card = app.card(root, padx=12, pady=10)
        card.pack(fill='both', expand=True, pady=(12, 0))
        self.text = tk.Text(card, wrap='none', bd=0, highlightthickness=0, font=app.font_mono, undo=True)
        self.text.insert('1.0', json.dumps(entry['value'], ensure_ascii=False, indent=4))
        app.register(self.text, lambda: self.text.configure(bg=app.colors['surface'], fg=app.colors['text'],
                                                            insertbackground=app.colors['text'],
                                                            selectbackground=app.colors['accent_soft'],
                                                            selectforeground=app.colors['text']))
        self.text.pack(fill='both', expand=True)

        self.top.bind('<Escape>', lambda e: self.close())
        self.top.deiconify()
        app.style_window(self.top)
        self.top.grab_set()
        self.text.focus_set()

    def save(self):
        try:
            value = json.loads(self.text.get('1.0', 'end'))
        except json.JSONDecodeError as err:
            self.lbl_error.configure(text=self.app.t('json.invalid', msg=err.msg, line=err.lineno, col=err.colno))
            return
        self.close()
        self.on_save(value)

    def close(self):
        self.top.grab_release()
        self.top.destroy()


class ConfigDialog:
    """Shows every key of the bot's config.json / .env files in an editable table before launching it."""

    def __init__(self, app, project, on_accept):
        self.app = app
        self.project = project
        self.on_accept = on_accept
        self.show_secrets = False
        self.editor = None
        self.editor_entry = None
        self.config = ProjectConfig(project, app.projects_path)
        self.entries = {e['iid']: e for e in self.config.entries()}
        s = app.scale

        self.top = tk.Toplevel(app.root)
        self.top.withdraw()
        self.top.title(app.t('config.window_title', name=project['name']))
        self.top.transient(app.root)
        self.top.geometry(f'{int(920 * s)}x{int(640 * s)}')
        self.top.minsize(int(640 * s), int(420 * s))
        self.top.protocol('WM_DELETE_WINDOW', self.cancel)
        app.register(self.top, lambda: self.top.configure(bg=app.colors['bg']))

        root = app.frame(self.top, 'bg', padx=24, pady=20)
        root.pack(fill='both', expand=True)

        header = app.frame(root, 'bg')
        header.pack(fill='x')
        self.btn_secrets = RoundButton(header, app, app.t('config.show_values'), self.toggle_secrets, icon='eye')
        self.btn_secrets.pack(side='right', anchor='n')
        app.image_label(header, 28, 'bg').pack(side='left', padx=(0, 12))
        titles = app.frame(header, 'bg')
        titles.pack(side='left', fill='x', expand=True)
        app.label(titles, app.t('config.title'), 'h1', 'bg').pack(anchor='w')
        app.label(titles, project['name'], 'muted', 'bg').pack(anchor='w')

        search = app.frame(root, 'bg')
        search.pack(fill='x', pady=(16, 8))
        self.var_search = tk.StringVar()
        self.ent_search = themed_entry(app, search, self.var_search, 20)
        self.ent_search.pack(side='left', ipady=int(3 * s))
        self.var_search.trace_add('write', lambda *a: self.populate())
        app.label(search, app.t('config.search'), 'muted', 'bg').pack(side='left')
        app.label(search, app.t('config.edit_hint'), 'muted', 'bg').pack(side='right')

        footer = app.frame(root, 'bg')
        footer.pack(side='bottom', fill='x', pady=(14, 0))
        RoundButton(footer, app, app.t('config.save_start'), self.accept, variant='accent', icon='play').pack(side='right')
        RoundButton(footer, app, app.t('config.cancel'), self.cancel).pack(side='right', padx=(0, 6))
        self.lbl_changes = app.label(footer, '', 'muted', 'bg')
        self.lbl_changes.pack(side='left')

        card = app.card(root, padx=6, pady=6)
        card.pack(fill='both', expand=True)
        self.tree = ttk.Treeview(card, columns=('value', 'note'), style='Config.Treeview', selectmode='browse')
        self.tree.heading('#0', text=app.t('config.col_key'), anchor='w')
        self.tree.heading('value', text=app.t('config.col_value'), anchor='w')
        self.tree.heading('note', text=app.t('config.col_description'), anchor='w')
        self.tree.column('#0', width=int(280 * s), stretch=False)
        self.tree.column('value', width=int(380 * s), stretch=True)
        self.tree.column('note', width=int(200 * s), stretch=False)
        scroll = ttk.Scrollbar(card, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.tree.pack(side='left', fill='both', expand=True)
        self.tree.bind('<Double-1>', self.edit)
        self.tree.bind('<Return>', self.edit)
        # the inline editor is placed over a cell; scrolling or resizing would leave it misplaced
        self.tree.bind('<Configure>', lambda e: self.editor is not None and self._commit(self.editor_entry), add='+')
        self.tree.bind('<MouseWheel>', lambda e: self.editor is not None and self._commit(self.editor_entry), add='+')
        app.register(self.tree, self._theme_tree)

        self.populate()
        self.top.bind('<Escape>', lambda e: self.editor is None and self.cancel())
        self.top.update_idletasks()
        x = app.root.winfo_rootx() + (app.root.winfo_width() - self.top.winfo_reqwidth()) // 2
        y = app.root.winfo_rooty() + int(30 * s)
        self.top.geometry(f'+{max(0, x)}+{max(0, y)}')
        self.top.deiconify()
        app.style_window(self.top)
        self.top.grab_set()
        self.tree.focus_set()

    def _theme_tree(self):
        c = self.app.colors
        self.tree.tag_configure('file', background=c['track'], foreground=c['text'], font=('Segoe UI Semibold', 10))
        self.tree.tag_configure('missing', background=c['track'], foreground=c['error'], font=('Segoe UI Semibold', 10))
        self.tree.tag_configure('entry', foreground=c['text'])
        self.tree.tag_configure('overridden', foreground=c['muted'])
        self.tree.tag_configure('modified', foreground=c['accent'], font=('Segoe UI Semibold', 10))

    # ---------- table ----------

    def _display(self, entry):
        value = entry['value']
        if entry['secret'] and not self.show_secrets:
            return '••••••••' if value not in ('', None) else ''
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        text = text.replace('\r', ' ').replace('\n', ' ')
        return text if len(text) <= 300 else text[:300] + '…'

    def _note(self, entry):
        t = self.app.t
        notes = []
        if not ProjectConfig.same(entry['value'], entry['original']):
            notes.append(t('config.note_modified'))
        if entry['overridden_by']:
            notes.append(t('config.note_overridden', file=entry['overridden_by']))
        if isinstance(entry['value'], (dict, list)):
            notes.append(t('config.note_json'))
        return '  ·  '.join(notes)

    def _tags(self, entry):
        if not ProjectConfig.same(entry['value'], entry['original']):
            return ('modified',)
        return ('overridden',) if entry['overridden_by'] else ('entry',)

    def _file_note(self, f):
        t = self.app.t
        if not f['exists']:
            return t('config.file_missing')
        if f['error']:
            return t('config.file_error', error=self.app.error_text(f['error']))
        note = t('config.file_keys', n=len(f['entries']))
        return note + '  ·  ' + t('config.file_shared') if f['shared'] else note

    def populate(self):
        query = self.var_search.get().strip().lower()
        self.tree.delete(*self.tree.get_children())
        for i, f in enumerate(self.config.files):
            tag = 'file' if f['exists'] and not f['error'] else 'missing'
            parent = self.tree.insert('', 'end', iid=f'file{i}', text=f['label'], values=('', self._file_note(f)), open=True, tags=(tag,))
            for entry in f['entries'].values():
                shown = self._display(entry)
                if query and query not in entry['key'].lower() and query not in shown.lower():
                    continue
                self.tree.insert(parent, 'end', iid=entry['iid'], text=entry['key'],
                                 values=(shown, self._note(entry)), tags=self._tags(entry))
        self._update_changes()

    def _refresh_row(self, entry):
        if self.tree.exists(entry['iid']):
            self.tree.item(entry['iid'], values=(self._display(entry), self._note(entry)), tags=self._tags(entry))
        self._update_changes()

    def _update_changes(self):
        n = len(self.config.changes())
        self.lbl_changes.fg_key = 'accent' if n else 'muted'
        self.app.apply_widget(self.lbl_changes)
        t = self.app.t
        text = t('config.changes_one' if n == 1 else 'config.changes_other', n=n) if n else t('config.no_changes')
        self.lbl_changes.configure(text=text)

    def toggle_secrets(self):
        self.show_secrets = not self.show_secrets
        self.btn_secrets.set(self.app.t('config.hide_values' if self.show_secrets else 'config.show_values'), 'eye')
        self.populate()

    # ---------- editing ----------

    def edit(self, event=None):
        iid = self.tree.identify_row(event.y) if event is not None and event.type == tk.EventType.ButtonPress else self.tree.focus()
        entry = self.entries.get(iid)
        if entry is None or self.editor is not None or not self.tree.winfo_ismapped():
            return
        if isinstance(entry['value'], (dict, list)):
            JsonEditor(self.app, self.top, entry, lambda value: self._set_value(entry, value))
            return
        self.tree.see(iid)
        self.tree.update_idletasks()
        bbox = self.tree.bbox(iid, 'value')
        if not bbox:
            return
        x, y, w, h = bbox
        c = self.app.colors
        editor = tk.Entry(self.tree, bd=0, highlightthickness=1, relief='flat', font=('Segoe UI', 10),
                          bg=c['surface'], fg=c['text'], insertbackground=c['text'],
                          highlightbackground=c['accent'], highlightcolor=c['accent'])
        value = entry['value']
        editor.insert(0, value if isinstance(value, str) else json.dumps(value, ensure_ascii=False))
        if entry['secret'] and not self.show_secrets:
            editor.configure(show='•')
        editor.place(x=x, y=y, width=w, height=h)
        editor.focus_set()
        editor.select_range(0, 'end')
        editor.bind('<Return>', lambda e: self._commit(entry))
        editor.bind('<KP_Enter>', lambda e: self._commit(entry))
        editor.bind('<Escape>', lambda e: (self._close_editor(), 'break')[1])
        editor.bind('<FocusOut>', lambda e: self._commit(entry))
        self.editor = editor
        self.editor_entry = entry

    def _parse(self, entry, text):
        if entry['kind'] == 'env' or isinstance(entry['original'], str):
            return text
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            raise LocalizedError('config.invalid_value', text=text, key=entry['key'])

    def _commit(self, entry):
        if self.editor is None:
            return True
        try:
            value = self._parse(entry, self.editor.get())
        except ValueError as err:
            editor, self.editor = self.editor, None
            messagebox.showerror(self.app.t('config.invalid_title'), self.app.error_text(err), parent=self.top)
            self.editor = editor
            editor.focus_set()
            return False
        self._close_editor()
        self._set_value(entry, value)
        return True

    def _close_editor(self):
        if self.editor is not None:
            editor, self.editor = self.editor, None
            editor.destroy()
            self.tree.focus_set()

    def _set_value(self, entry, value):
        entry['value'] = value
        self._refresh_row(entry)

    # ---------- accept / cancel ----------

    def accept(self):
        if self.editor is not None and not self._commit(self.editor_entry):
            return
        changes = self.config.changes()
        if changes:
            files = {}
            for entry in changes:
                files.setdefault(entry['file'], []).append(entry['key'])
            lines = [f"•  {self.config.files[i]['label']}:  {', '.join(keys)}" for i, keys in files.items()]
            shared = [self.config.files[i]['label'] for i in files if self.config.files[i]['shared']]
            t = self.app.t
            message = t('config.save_message', lines='\n'.join(lines))
            if shared:
                message += t('config.save_shared', files=', '.join(shared))
            message += t('config.save_confirm')
            if not messagebox.askyesno(t('config.save_title'), message, icon='warning' if shared else 'question', parent=self.top):
                return
            try:
                self.config.save()
            except (OSError, ValueError) as err:
                messagebox.showerror(t('config.save_error_title'), self.app.error_text(err), parent=self.top)
                return
        self.close()
        self.on_accept()

    def cancel(self):
        self._close_editor()
        n = len(self.config.changes())
        t = self.app.t
        if n and not messagebox.askyesno(t('config.discard_title'), t('config.discard_one' if n == 1 else 'config.discard_other', n=n),
                                         parent=self.top):
            return
        self.close()

    def close(self):
        self.top.grab_release()
        self.top.destroy()


class ProjectRow:
    """One project in the main list: name, detail, status badge, issues icon and run button."""

    def __init__(self, app, master, project, status):
        self.app = app
        self.project = project
        name = project['name']

        self.frame = app.frame(master, 'surface', padx=18, pady=12)
        self.frame.pack(fill='x')
        self.left = app.frame(self.frame, 'surface')
        self.left.pack(side='left', fill='x', expand=True)
        self.lbl_name = app.label(self.left, name, 'h2', 'surface')
        self.lbl_name.pack(anchor='w')
        sub = f"{app.watch_name}/{project['group']}" if project['runnable'] else project['issues'][0]['title']
        self.lbl_sub = app.label(self.left, sub, 'muted', 'surface')
        self.lbl_sub.pack(anchor='w')

        self.btn = RoundButton(self.frame, app, lambda: app.t('row.start'), lambda: app.run_project(name), variant='accent',
                               bg_key='surface', size=9, icon='play')
        self.btn.pack(side='right')
        self.pill = Pill(self.frame, app, *status, bg_key='surface')
        self.pill.pack(side='right', padx=(0, 14))
        self.widgets = [self.frame, self.left, self.lbl_name, self.lbl_sub, self.pill, self.btn]

        if project['issues']:
            level = 'warning' if project['runnable'] else 'error'
            self.info = InfoIcon(self.frame, app, level, lambda: IssuesDialog(app, project))
            self.info.pack(side='right', padx=(0, 10))
            self.widgets.append(self.info)

        if not project['runnable']:
            self.lbl_name.fg_key = 'muted'
            self.btn.set_disabled(True)
            app.apply_widget(self.lbl_name)

        for widget in self.widgets:
            widget.bind('<Enter>', self._check_hover, add='+')
            widget.bind('<Leave>', self._check_hover, add='+')
        for widget in self.widgets[:5]:
            widget.bind('<Double-1>', lambda e: app.run_project(name))

    def _check_hover(self, event):
        widget = self.frame.winfo_containing(event.x_root, event.y_root)
        self.set_hover(widget is not None and str(widget).startswith(str(self.frame)))

    def set_hover(self, value):
        key = 'hover' if value else 'surface'
        if self.frame.bg_key == key:
            return
        for widget in self.widgets:
            widget.bg_key = key
            self.app.apply_widget(widget)

    def set_status(self, text, kind, running):
        self.pill.set(text, kind)
        if running:
            self.btn.set(lambda: self.app.t('row.view'), None)
        else:
            self.btn.set(lambda: self.app.t('row.start'), 'play')


class RunView:
    """One execution, live or finished: tqdm progress, log events, console output, duration and status. Everything is
    read from the files the runner writes (runs/<bot>/<run_id>.out and the kreton-watch log), so the same view works
    for a run started by the UI or by the driver, while it runs or later from the history.

    run: the bot's lock (live) or its history record: bot, run_id/id, trigger, start, end, status, code, out, log."""

    TQDM_RE = re.compile(r'(?:(?P<desc>[^|\r\n]*?):\s*)?(?P<pct>\d{1,3})%\|[^|]*\|\s*(?P<n>[\d.]+[kMGT]?)/(?P<total>[\d.]+[kMGT]?)')
    LOG_SEPARATOR = '§'
    # where a flattened error had its line breaks: Selenium "(Session info:" / "Stacktrace:" and each native frame
    # ("chromedriver!GetHandleVerifier [0x...]"), Python "Traceback ..." and each 'File "...", line N'
    BREAK_RE = re.compile(r' (?=Stacktrace:|Traceback \(most recent call last\):|File "[^"]*", line \d+|\(Session info:|'
                          r'For documentation on this error|[\w.-]+![\w(])')
    # inside a traceback, the closing exception line ("TimeoutError: ...") also starts a new line
    EXCEPTION_RE = re.compile(r' (?=(?:\w+\.)*\w*(?:Error|Exception|Exit|Interrupt)\b:)')

    STATUSES = {'running': ('status.running', 'accent'), 'succeeded': ('status.succeeded', 'ok'),
                'failed': ('status.failed', 'error'), 'aborted': ('status.aborted', 'warning'),
                'start_failed': ('status.start_failed', 'error'), 'interrupted': ('status.interrupted', 'warning')}

    def __init__(self, app, master, run, on_close=None):
        self.app = app
        self.run = dict(run)
        self.bot = run['bot']
        self.run_id = run.get('run_id') or run['id']
        self.on_close = on_close
        project = app.projects.get(self.bot, {})
        self.group = project.get('group', self.bot)
        self.no_progress = project.get('no_progress', False)
        self.finished = self.run.get('status', 'running') != 'running'
        self.closed = False
        self.lost_polls = 0

        self.out_pos = 0
        self.out_buf = ''
        self.out_decoder = codecs.getincrementaldecoder('utf-8')('replace')
        self.log_path = None
        self.log_pos = 0
        self.log_buf = ''
        self.log_decoder = codecs.getincrementaldecoder('utf-8')('replace')

        self.frame = app.frame(master, 'bg', padx=24, pady=20)
        self._build()
        start = parse_time(self.run.get('start'))
        self.lbl_start.configure(text=f'{start:%H:%M:%S}' if start else '--:--:--')
        self._set_status(*self._status())
        self._poll()

    # ---------- parsing ----------

    @classmethod
    def parse_tqdm(cls, line):
        match = cls.TQDM_RE.search(line)
        if not match:
            return None
        return {
            'desc': (match.group('desc') or '').strip(),
            'pct': min(int(match.group('pct')), 100),
            'n': match.group('n'),
            'total': match.group('total'),
        }

    @classmethod
    def parse_log_line(cls, line):
        parts = line.rstrip('\r\n').split(cls.LOG_SEPARATOR, 4)
        if len(parts) != 5:
            return None
        return {'time': parts[2].strip(), 'level': parts[3].strip().upper(), 'message': parts[4]}

    @classmethod
    def split_message(cls, message):
        """pi_kreton_rpa's log._sanitize turns the line breaks of a multi-line error (traceback, Selenium stack
        trace) into spaces; this puts them back so the event can be shown one line per row."""
        parts = cls.BREAK_RE.split(message)
        if 'Traceback (most recent call last):' in message:
            parts = [p for part in parts for p in cls.EXCEPTION_RE.split(part)]
        return [p.strip() for p in parts if p.strip()] or [message]

    @staticmethod
    def format_elapsed(seconds):
        seconds = int(seconds)
        return f'{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}'

    # ---------- ui ----------

    def _build(self):
        app = self.app
        root = self.frame

        header = app.frame(root, 'bg')
        header.pack(fill='x')
        logo = app.image_label(header, 28, 'bg')
        logo.pack(side='left', padx=(0, 12))
        titles = app.frame(header, 'bg')
        titles.pack(side='left', fill='x', expand=True)
        app.label(titles, self.bot, 'title', 'bg').pack(anchor='w')
        trigger_key = 'run.trigger_cron' if self.run.get('trigger') == 'cron' else 'run.trigger_manual'
        app.label(titles, lambda: f"{app.watch_name}/{self.group}  ·  {app.t(trigger_key)}", 'muted', 'bg').pack(anchor='w')
        self.pill = Pill(header, app, lambda: app.t('status.running'), 'accent', bg_key='bg')
        self.pill.pack(side='right')

        stats = app.frame(root, 'bg')
        stats.pack(fill='x', pady=(18, 0))
        for col in range(3):
            stats.columnconfigure(col, weight=1, uniform='stats')
        self.lbl_elapsed = self._stat(stats, 0, lambda: app.t('run.duration'), '00:00:00', 'clock')
        self.lbl_start = self._stat(stats, 1, lambda: app.t('run.start_time'), '--:--:--', 'value')
        self.lbl_log = self._stat(stats, 2, lambda: app.t('run.log_stream'), lambda: app.t('run.waiting'), 'value')

        progress = app.card(root)
        progress.pack(fill='x', pady=(12, 0))
        row = app.frame(progress, 'surface')
        row.pack(fill='x')
        app.label(row, lambda: app.t('run.progress'), 'h2', 'surface').pack(side='left')
        self.lbl_pct = app.label(row, '0%', 'pct', 'surface')
        self.lbl_pct.pack(side='right')
        desc_key = 'run.no_progress_bot' if self.no_progress else 'run.no_progress_yet'
        self.lbl_desc = app.label(progress, lambda: app.t(desc_key), 'muted', 'surface')
        self.lbl_desc.pack(anchor='w', pady=(2, 10))
        self.bar = RoundBar(progress, app)
        self.bar.pack(fill='x')

        # footer is packed before the logs card so it keeps its space when the window shrinks
        footer = app.frame(root, 'bg')
        footer.pack(side='bottom', fill='x', pady=(14, 0))
        if self.on_close:
            RoundButton(footer, app, lambda: app.t('run.close'), self.on_close).pack(side='right')
        self.btn_stop = RoundButton(footer, app, lambda: app.t('run.stop'), self.stop, variant='danger', icon='stop')
        self.btn_stop.pack(side='right', padx=(0, 6))
        # runs are detached (main.py --run): closing a view, or the app, doesn't stop the bot
        self.lbl_hint = app.label(footer, lambda: app.t('run.background_hint'), 'muted', 'bg')
        self.lbl_hint.pack(side='left')

        logs = app.card(root)
        logs.pack(fill='both', expand=True, pady=(12, 0))
        head = app.frame(logs, 'surface')
        head.pack(fill='x', pady=(0, 8))
        app.label(head, lambda: app.t('run.log_events'), 'h2', 'surface').pack(side='left')
        # CloudWatch-like "Filter events": a level (ERROR, WARNING, INFO) or any text of the timestamp/message
        self.var_filter = tk.StringVar()
        self.ent_filter = themed_entry(app, head, self.var_filter, 28)
        self.ent_filter.pack(side='right', ipady=int(2 * app.scale))
        app.label(head, lambda: app.t('run.filter_events'), 'muted', 'surface').pack(side='right', padx=(0, 8))
        self.lbl_matches = app.label(head, '', 'muted', 'surface')
        self.lbl_matches.pack(side='right', padx=(0, 12))
        self.var_filter.trace_add('write', lambda *a: self._apply_filter())
        self.ent_filter.bind('<Escape>', lambda e: self.var_filter.set(''))
        body = app.frame(logs, 'surface')
        body.pack(fill='both', expand=True)
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)
        # CloudWatch-like table: one row per event, no wrapping; long messages scroll horizontally
        s = app.scale
        self.log_font = tkfont.Font(font=app.font_mono)
        self.log_rows = collections.deque()
        self.rows_by_iid = {}
        self.log_stripe = False
        self.msg_width = 0
        # same columns as CloudWatch "Log events": ▶ | Timestamp | Message ([LEVEL] prefix, as Lambda writes it);
        # a multi-line event (traceback) is one row that expands to show every line
        self.fixed_width = int(28 * s) + int(170 * s)
        self.tree_log = ttk.Treeview(body, columns=('time', 'message'), show=('tree', 'headings'),
                                     style='Log.Treeview', selectmode='extended')
        self.tree_log.column('#0', width=int(28 * s), minwidth=int(28 * s), stretch=False)
        self.tree_log.column('time', width=int(170 * s), minwidth=int(170 * s), stretch=False, anchor='w')
        self.tree_log.column('message', width=int(600 * s), stretch=False, anchor='w')
        yscroll = ttk.Scrollbar(body, orient='vertical', command=self.tree_log.yview)
        xscroll = ttk.Scrollbar(body, orient='horizontal', command=self.tree_log.xview)
        self.tree_log.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.tree_log.grid(row=0, column=0, sticky='nsew')
        yscroll.grid(row=0, column=1, sticky='ns')
        xscroll.grid(row=1, column=0, sticky='ew')
        self.tree_log.bind('<Configure>', lambda e: self._fit_message_column())
        # Tk's default Shift+wheel moves 1 px per notch
        self.tree_log.bind('<Shift-MouseWheel>', lambda e: (self.tree_log.xview_scroll(int(-e.delta / 120) * int(60 * s), 'units'), 'break')[1])
        self.tree_log.bind('<ButtonPress-1>', lambda e: self.tree_log.focus_set(), add='+')
        self.tree_log.bind('<Control-c>', lambda e: self._copy(with_time=True))
        self.tree_log.bind('<Control-a>', lambda e: self._select_all())
        self.tree_log.bind('<Button-3>', self._show_menu)
        self.menu_log = tk.Menu(self.frame, tearoff=0, bd=0)
        self.menu_log.add_command(command=lambda: self._copy(with_time=False))
        self.menu_log.add_command(command=lambda: self._copy(with_time=True), accelerator='Ctrl+C')
        self.menu_log.add_separator()
        self.menu_log.add_command(command=self._select_all, accelerator='Ctrl+A')
        app.register(self.tree_log, self._theme_tree)

    def _stat(self, master, col, caption, value, role):
        card = self.app.card(master)
        card.grid(row=0, column=col, sticky='nsew', padx=(0 if col == 0 else 6, 0 if col == 2 else 6))
        self.app.label(card, caption, 'caption', 'surface').pack(anchor='w')
        lbl = self.app.label(card, value, role, 'surface')
        lbl.pack(anchor='w', pady=(4, 0))
        return lbl

    def _theme_tree(self):
        c = self.app.colors
        self.tree_log.heading('time', text=self.app.t('run.col_timestamp'), anchor='w')
        self.tree_log.heading('message', text=self.app.t('run.col_message'), anchor='w')
        self.tree_log.tag_configure('STRIPE', background=c['track'])
        self.tree_log.tag_configure('INFO', foreground=c['text'])
        self.tree_log.tag_configure('WARNING', foreground=c['warning'])
        self.tree_log.tag_configure('ERROR', foreground=c['error'])
        self.tree_log.tag_configure('CONSOLE', foreground=c['muted'])
        self.menu_log.configure(bg=c['surface'], fg=c['text'], activebackground=c['accent_soft'], activeforeground=c['text'],
                                font=('Segoe UI', 10))
        for index, key in ((0, 'run.copy_message'), (1, 'run.copy_event'), (3, 'run.select_all')):
            self.menu_log.entryconfigure(index, label=self.app.t(key))
        # the "(+N lines)" hint follows a language change
        for row in self.log_rows:
            if len(row['lines']) > 1:
                self.tree_log.item(row['iid'], values=(row['time'], self._summary(row)))

    def _fit_message_column(self):
        # the message column is as wide as the longest message (or fills the view), so the x scrollbar covers it all
        available = self.tree_log.winfo_width() - self.fixed_width
        self.tree_log.column('message', width=max(self.msg_width, available))

    def _select_all(self):
        self.tree_log.selection_set(self.tree_log.get_children())
        return 'break'

    def _show_menu(self, event):
        iid = self.tree_log.identify_row(event.y)
        if iid and iid not in self.tree_log.selection():
            self.tree_log.selection_set(iid)
        self.tree_log.focus_set()
        if self.tree_log.selection():
            self.menu_log.tk_popup(event.x_root, event.y_root)
        return 'break'

    def _copy(self, with_time):
        texts = []
        for iid in self.tree_log.selection():
            row = self.rows_by_iid.get(iid)
            if row is not None:
                # a multi-line event is copied with its line breaks
                time_text, message = row['time'], '\n'.join(row['lines'])
            else:
                time_text, message = (str(v) for v in self.tree_log.item(iid, 'values'))
            texts.append(f'{time_text}\t{message}' if with_time and time_text else message)
        if texts:
            self.frame.clipboard_clear()
            self.frame.clipboard_append('\n'.join(texts))
        return 'break'

    def _status(self):
        key, kind = self.STATUSES.get(self.run.get('status', 'running'), self.STATUSES['running'])
        code = self.run.get('code')
        return (lambda: self.app.t(key, code=code), kind)

    def _set_status(self, text, kind):
        self.status = (text, kind)
        self.pill.set(text, kind)
        self.app.set_project_status(self.bot, text, kind)

    @staticmethod
    def log_matches(query, level, time_text, message):
        """CloudWatch-like filter: a level name shows only that level; any other text is searched (case-insensitive)."""
        query = query.strip().lower()
        if not query:
            return True
        if query in ('info', 'warning', 'warn', 'error'):
            return level.lower().startswith(query[:4])
        return query in f'{time_text} {message}'.lower()

    @staticmethod
    def continues_block(lines, text):
        """Console output (a traceback) arrives one line at a time: indented lines continue the previous block,
        and so does the exception line that closes a traceback."""
        if text[:1].isspace():
            return True
        return lines[0].startswith('Traceback') and lines[-1][:1].isspace()

    def _summary(self, row):
        lines = row['lines']
        if len(lines) == 1:
            return lines[0]
        # a traceback is identified by its last line (the exception); anything else by its first one
        head = lines[-1] if lines[0].startswith('Traceback') else lines[0]
        return f"{head}   {self.app.t('run.more_lines', n=len(lines) - 1)}"

    def _insert(self, time_text, message, tag, level='', lines=None):
        at_bottom = self.tree_log.yview()[1] >= 0.999
        # 'message' is the full text (filter, copy fallback); 'lines' is how it is shown: one line per child row
        row = {'time': time_text, 'message': message, 'tag': tag, 'level': level, 'lines': lines or [message]}
        summary = self._summary(row)
        row['iid'] = self.tree_log.insert('', 'end', values=(time_text, summary), tags=(tag,))
        if len(row['lines']) > 1:
            for line in row['lines']:
                self.tree_log.insert(row['iid'], 'end', values=('', line), tags=(tag,))
                self._measure(line)
        self.rows_by_iid[row['iid']] = row
        self.log_rows.append(row)
        while len(self.log_rows) > self.app.config['MAX_LOG_LINES']:
            old = self.log_rows.popleft()
            self.rows_by_iid.pop(old['iid'], None)
            self.tree_log.delete(old['iid'])
        if self.log_matches(self.var_filter.get(), level, time_text, message):
            self._stripe(row)
        else:
            self.tree_log.detach(row['iid'])
        self._update_matches()
        self._measure(summary)
        if at_bottom:
            self.tree_log.yview_moveto(1.0)

    def _extend(self, row, text):
        # the event shows a one-line summary; expanding it (▶ or double-click) shows every line on its own row
        at_bottom = self.tree_log.yview()[1] >= 0.999
        if len(row['lines']) == 1:
            self.tree_log.insert(row['iid'], 'end', values=('', row['lines'][0]), tags=self.tree_log.item(row['iid'], 'tags'))
        row['lines'].append(text)
        row['message'] = ' '.join(line.strip() for line in row['lines'])
        self.tree_log.insert(row['iid'], 'end', values=('', text), tags=self.tree_log.item(row['iid'], 'tags'))
        summary = self._summary(row)
        self.tree_log.item(row['iid'], values=(row['time'], summary))
        self._measure(text)
        self._measure(summary)
        if self.var_filter.get().strip():
            self._apply_filter()
        elif at_bottom:
            self.tree_log.yview_moveto(1.0)

    def _measure(self, text):
        width = self.log_font.measure(text) + int(24 * self.app.scale)
        if width > self.msg_width:
            self.msg_width = width
            self._fit_message_column()

    def _stripe(self, row):
        # zebra over the visible rows only, so it stays even while filtering
        tags = (row['tag'], 'STRIPE') if self.log_stripe else (row['tag'],)
        self.log_stripe = not self.log_stripe
        self.tree_log.item(row['iid'], tags=tags)
        for child in self.tree_log.get_children(row['iid']):
            self.tree_log.item(child, tags=tags)

    def _apply_filter(self):
        query = self.var_filter.get()
        self.log_stripe = False
        index = 0
        for row in self.log_rows:
            if self.log_matches(query, row['level'], row['time'], row['message']):
                self.tree_log.reattach(row['iid'], '', index)
                self._stripe(row)
                index += 1
            else:
                self.tree_log.detach(row['iid'])
        self._update_matches()
        self.tree_log.yview_moveto(1.0)

    def _update_matches(self):
        if not self.var_filter.get().strip():
            self.app.set_text(self.lbl_matches, '')
            return
        shown, total = len(self.tree_log.get_children()), len(self.log_rows)
        self.app.set_text(self.lbl_matches, lambda: self.app.t('run.filter_matches', shown=shown, total=total))

    def _append_log(self, parsed):
        level = parsed['level'] if parsed['level'] in ('INFO', 'WARNING', 'ERROR') else 'INFO'
        message = f"[{parsed['level']}] {parsed['message']}"
        self._insert(parsed['time'], message, level, parsed['level'], lines=self.split_message(message))

    def _append_console(self, text):
        last = self.log_rows[-1] if self.log_rows else None
        if last is not None and last['tag'] == 'CONSOLE' and self.continues_block(last['lines'], text):
            self._extend(last, text)
        else:
            self._insert('', text, 'CONSOLE', lines=[text])

    # ---------- sources ----------

    def _read_out(self):
        """New bytes of the bot's stdout/stderr file: tqdm updates move the bar, any other line is console output."""
        path = self.run.get('out')
        if not path:
            return
        try:
            with open(path, 'rb') as fh:
                fh.seek(self.out_pos)
                data = fh.read()
        except OSError:
            return
        self.out_pos += len(data)
        self.out_buf += self.out_decoder.decode(data, final=self.finished)
        parts = re.split(r'[\r\n]', self.out_buf)
        self.out_buf = parts.pop()
        for part in parts:
            self._handle_output(part)
        if self.finished and self.out_buf:
            self._handle_output(self.out_buf)
            self.out_buf = ''
        elif self.out_buf:
            # tqdm rewrites its line with '\r' and leaves the latest state unterminated
            progress = self.parse_tqdm(self.out_buf)
            if progress:
                self._show_progress(progress)

    def _refresh(self):
        """Live run: follow the bot's lock (it carries the kreton-watch log once the runner finds it). When the runner
        removes the lock, the final status, exit code and log come from the history."""
        lock = self.app.scheduler.read_lock(self.bot)
        if lock and lock.get('run_id') == self.run_id:
            self.run['log'] = lock.get('log') or self.run.get('log')
            return
        record = next((h for h in self.app.scheduler.history() if h.get('id') == self.run_id), None)
        if record and record.get('end'):
            self.run.update(record)
            self.finished = True
        else:
            # lock gone without an 'end' record: give the runner a moment to write it, then close the run as lost
            self.lost_polls += 1
            if self.lost_polls > 25:
                self.run['status'] = 'interrupted'
                self.finished = True

    def _handle_output(self, line):
        progress = self.parse_tqdm(line)
        if progress:
            self._show_progress(progress)
        elif line.strip():
            self._append_console(line.rstrip())

    def _show_progress(self, progress):
        desc = progress['desc'] or self.app.t('run.progress_default')
        self.app.set_text(self.lbl_desc, f"{desc}  ·  {progress['n']} / {progress['total']}")
        self.lbl_pct.configure(text=f"{progress['pct']}%")
        self.bar.set(progress['pct'])

    def _tail_log(self):
        if self.log_path is None:
            if not self.run.get('log'):
                if self.finished:
                    self.app.set_text(self.lbl_log, '-')
                return
            self.log_path = self.run['log']
            self.app.set_text(self.lbl_log, os.path.basename(self.log_path))

        try:
            with open(self.log_path, 'rb') as f:
                f.seek(self.log_pos)
                data = f.read()
        except OSError:
            return
        if not data:
            return
        self.log_pos += len(data)
        self.log_buf += self.log_decoder.decode(data)
        lines = self.log_buf.split('\n')
        self.log_buf = lines.pop()
        for line in lines:
            parsed = self.parse_log_line(line)
            if parsed:
                self._append_log(parsed)
            elif line.strip():
                self._append_console(line.rstrip())

    def _poll(self):
        if self.closed:
            return
        was_running = not self.finished
        if was_running:
            self._refresh()
        # log before console: a finished run is read at once, and its console output (a traceback) comes last
        self._tail_log()
        self._read_out()

        start = parse_time(self.run.get('start'))
        end = parse_time(self.run.get('end')) if self.finished else datetime.now()
        if start and end:
            self.lbl_elapsed.configure(text=self.format_elapsed(max(0, (end - start).total_seconds())))

        if self.finished:
            self.btn_stop.set_disabled(True)
            self.lbl_hint.pack_forget()
            if was_running or self.status[1] == 'accent':
                self._set_status(*self._status())
        else:
            self.frame.after(self.app.config['POLL_MS'], self._poll)

    def is_running(self):
        return not self.finished

    def stop(self):
        if self.finished:
            return
        t = self.app.t
        if messagebox.askyesno(t('run.stop_title'), t('run.stop_confirm', name=self.bot), parent=self.frame):
            self._set_status(lambda: self.app.t('status.aborting'), 'warning')
            self.app.scheduler.stop(self.bot)

    def destroy(self):
        self.closed = True
        self.frame.destroy()


def item_status(app, item):
    """(text, kind) of a history item: a run (by its status) or a notice (missed / queued / cancelled)."""
    event = item.get('event')
    if event == 'missed':
        return app.t('status.missed', n=item.get('count', 1)), 'warning'
    if event == 'queued':
        return app.t('status.queued'), 'muted'
    if event == 'cancelled':
        return app.t('status.cancelled'), 'muted'
    key, kind = RunView.STATUSES.get(item.get('status', 'running'), RunView.STATUSES['running'])
    return app.t(key, code=item.get('code')), kind


def trigger_text(app, trigger):
    return app.t('trigger.cron') if trigger == 'cron' else app.t('trigger.manual')


def short_time(text):
    # '2026-10-09T11:47:46' -> '2026-10-09 11:47:46'
    return (text or '').replace('T', ' ')


def duration_text(item):
    start, end = parse_time(item.get('start')), parse_time(item.get('end'))
    if not start or 'status' not in item:
        return ''
    end = end or (datetime.now() if item.get('status') == 'running' else None)
    return RunView.format_elapsed(max(0, (end - start).total_seconds())) if end else ''


def themed_entry(app, master, var, width, font=('Segoe UI', 10)):
    """Rounded text input: returns the RoundField to pack (its `widget` is the Entry)."""
    field = RoundField(app, master)
    entry = tk.Entry(field, textvariable=var, bd=0, highlightthickness=0, font=font, relief='flat', width=width)
    app.register(entry, lambda: entry.configure(
        bg=app.colors['surface'], fg=app.colors['text'], insertbackground=app.colors['text'],
        selectbackground=app.colors['accent_soft'], selectforeground=app.colors['text']))
    return field.attach(entry)


def themed_combobox(app, master, var, width, values=()):
    """Rounded read-only drop-down: returns the RoundField to pack (its `widget` is the Combobox)."""
    field = RoundField(app, master)
    combo = ttk.Combobox(field, textvariable=var, values=values, state='readonly', width=width,
                         font=('Segoe UI', 10), style='Round.TCombobox')
    return field.attach(combo)


class ActivityRow:
    """One item of the Activities list: a running, queued or (this session) finished execution."""

    def __init__(self, page, item):
        app = self.app = page.app
        self.page = page
        self.frame = app.frame(page.list_inner, 'surface', padx=14, pady=10, cursor='hand2')
        self.frame.pack(fill='x')
        top = app.frame(self.frame, 'surface')
        top.pack(fill='x')
        self.lbl_name = app.label(top, item['bot'], 'h2', 'surface')
        self.lbl_name.pack(side='left')
        self.pill = Pill(top, app, '', 'muted', bg_key='surface')
        self.pill.pack(side='right')
        self.lbl_sub = app.label(self.frame, '', 'muted', 'surface')
        self.lbl_sub.pack(anchor='w', pady=(2, 0))
        self.widgets = [self.frame, top, self.lbl_name, self.pill, self.lbl_sub]
        for widget in self.widgets:
            widget.bind('<Button-1>', lambda e: page.select(self.item['key']))
        self.update(item)

    def update(self, item):
        self.item = item
        if item['kind'] == 'queued':
            self.pill.set(lambda: self.app.t('status.queued'), 'muted')
            sub = self.app.t('act.queued_since', time=short_time(item['start'])[11:16])
        else:
            text, kind = item_status(self.app, item)
            self.pill.set(text, kind)
            sub = f"{trigger_text(self.app, item.get('trigger'))}  ·  {short_time(item['start'])[11:16]}  ·  {duration_text(item)}"
        self.lbl_sub.configure(text=sub)

    def set_selected(self, value):
        for widget in self.widgets:
            widget.bg_key = 'accent_soft' if value else 'surface'
            self.app.apply_widget(widget)


class ActivitiesPage:
    """Running and queued executions (plus the ones that ended while the app was open), each with its RunView,
    instead of a window per execution."""

    def __init__(self, app, master):
        self.app = app
        s = app.scale
        self.frame = app.frame(master, 'bg')
        self.rows, self.items, self.finished = {}, {}, {}
        self.selected = None
        self.view = None
        self.view_key = None

        left = app.card(self.frame, padx=0, pady=0, width=int(330 * s))
        left.pack(side='left', fill='y')
        left.pack_propagate(False)
        head = app.frame(left, 'surface', padx=14, pady=10)
        head.pack(fill='x')
        app.label(head, lambda: app.t('act.title'), 'caption', 'surface').pack(side='left')
        RoundButton(head, app, lambda: app.t('act.clear'), self.clear_finished, bg_key='surface', size=9).pack(side='right')
        app.frame(left, 'border', height=1).pack(fill='x')
        self.list_inner = app.frame(left, 'surface')
        self.list_inner.pack(fill='both', expand=True)

        self.detail = app.frame(self.frame, 'bg')
        self.detail.pack(side='left', fill='both', expand=True, padx=(12, 0))
        self.empty = app.label(self.detail, lambda: app.t('act.empty'), 'muted', 'bg')
        self.empty.place(relx=0.5, rely=0.4, anchor='center')

    def refresh(self, running, queue):
        items = {}
        for bot, lock in sorted(running.items(), key=lambda kv: kv[1]['start']):
            items[lock['run_id']] = {**lock, 'key': lock['run_id'], 'kind': 'running', 'status': 'running'}
        for bot, item in sorted(queue.items(), key=lambda kv: kv[1]['queued_at']):
            items[f'queued-{bot}'] = {'key': f'queued-{bot}', 'kind': 'queued', 'bot': bot, 'trigger': item['trigger'],
                                      'start': item['queued_at']}
        ended = [key for key, old in self.items.items() if old['kind'] == 'running' and key not in items]
        if ended:
            # runs that ended while the app was open stay listed with their final status until cleared
            history = {h.get('id'): h for h in self.app.scheduler.history()}
            for key in ended:
                self.finished[key] = {**self.items[key], **history.get(key, {}), 'key': key, 'kind': 'finished'}
        items.update({k: v for k, v in self.finished.items() if k not in items})

        if list(items) != list(self.rows):
            for row in self.rows.values():
                row.frame.destroy()
            self.rows = {key: ActivityRow(self, item) for key, item in items.items()}
        else:
            for key, item in items.items():
                self.rows[key].update(item)
        self.items = items
        if self.selected not in items:
            self.selected = None
            if self.view is not None:
                self.view.destroy()
                self.view, self.view_key = None, None
            if items:
                self.select(next(iter(items)))
        for key, row in self.rows.items():
            row.set_selected(key == self.selected)
        if self.view is None:
            self.empty.place(relx=0.5, rely=0.4, anchor='center')

    def select(self, key):
        self.selected = key
        for k, row in self.rows.items():
            row.set_selected(k == key)
        if self.view_key == key:
            return
        if self.view is not None:
            self.view.destroy()
        item = self.items[key]
        self.empty.place_forget()
        if item['kind'] == 'queued':
            self.view = self._queued_panel(item)
        else:
            self.view = RunView(self.app, self.detail, item)
            self.view.frame.pack(fill='both', expand=True)
        self.view_key = key

    def _queued_panel(self, item):
        app = self.app
        panel = app.frame(self.detail, 'bg', padx=24, pady=20)
        panel.pack(fill='both', expand=True)
        header = app.frame(panel, 'bg')
        header.pack(fill='x')
        app.label(header, item['bot'], 'title', 'bg').pack(side='left')
        Pill(header, app, lambda: app.t('status.queued'), 'muted', bg_key='bg').pack(side='right')
        app.label(panel, lambda: app.t('act.queued_detail', trigger=trigger_text(app, item['trigger']),
                                       time=short_time(item['start'])), 'body', 'bg').pack(anchor='w', pady=(12, 0))

        def cancel():
            app.scheduler.cancel_queued(item['bot'])
            app.refresh_ui()

        RoundButton(panel, app, lambda: app.t('act.cancel_queued'), cancel, variant='danger').pack(anchor='w', pady=(16, 0))
        return panel

    def show(self, key):
        self.app.refresh_ui()
        if key in self.items:
            self.select(key)

    def clear_finished(self):
        self.finished = {}
        self.app.refresh_ui()


class HistoryPage:
    """Every execution (and every missed / queued notice), filterable; an execution opens in its RunView."""

    FILTERS = (('all', None), ('running', {'running'}), ('succeeded', {'succeeded'}),
               ('failed', {'failed', 'start_failed', 'interrupted'}), ('aborted', {'aborted'}),
               ('missed', {'missed'}), ('queued', {'queued', 'cancelled'}))

    def __init__(self, app, master):
        self.app = app
        s = app.scale
        self.frame = app.frame(master, 'bg')
        self.items, self.iid_items = [], {}
        self.mtime = -1
        self.view = None

        self.list_page = app.frame(self.frame, 'bg')
        self.list_page.pack(fill='both', expand=True)
        filters = app.frame(self.list_page, 'bg')
        filters.pack(fill='x', pady=(0, 10))
        app.label(filters, lambda: app.t('hist.filter_bot'), 'muted', 'bg').pack(side='left', padx=(0, 6))
        self.var_bot = tk.StringVar()
        field = themed_combobox(app, filters, self.var_bot, 32)
        field.pack(side='left')
        self.cmb_bot = field.widget
        app.label(filters, lambda: app.t('hist.filter_status'), 'muted', 'bg').pack(side='left', padx=(16, 6))
        self.var_status = tk.StringVar()
        field = themed_combobox(app, filters, self.var_status, 13)
        field.pack(side='left')
        self.cmb_status = field.widget
        app.label(filters, lambda: app.t('hist.search'), 'muted', 'bg').pack(side='left', padx=(16, 6))
        self.var_search = tk.StringVar()
        themed_entry(app, filters, self.var_search, 22).pack(side='left', ipady=int(3 * s))
        RoundButton(filters, app, '', lambda: self.refresh(full=True), icon='refresh').pack(side='right')
        self.lbl_count = app.label(filters, '', 'muted', 'bg')
        self.lbl_count.pack(side='right', padx=(0, 8))
        for var in (self.var_bot, self.var_status, self.var_search):
            var.trace_add('write', lambda *a: self._populate())

        bottom = app.frame(self.list_page, 'bg')
        bottom.pack(side='bottom', fill='x', pady=(8, 0))
        app.label(bottom, lambda: app.t('hist.hint'), 'muted', 'bg').pack(side='left')
        self.btn_upload = RoundButton(bottom, app, lambda: app.t('hist.upload'), self.upload_logs, variant='accent')
        self.btn_upload.pack(side='right')
        RoundButton(bottom, app, lambda: app.t('hist.server_logs'), self.open_server).pack(side='right', padx=(0, 6))
        card = app.card(self.list_page, padx=6, pady=6)
        card.pack(fill='both', expand=True)
        self.columns = (('start', 170), ('bot', 260), ('trigger', 110), ('status', 230), ('duration', 100), ('code', 90))
        self.tree = ttk.Treeview(card, columns=[c for c, _ in self.columns], show='headings', style='Config.Treeview', selectmode='browse')
        for col, width in self.columns:
            self.tree.column(col, width=int(width * s), stretch=col == 'bot', anchor='w')
        scroll = ttk.Scrollbar(card, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.tree.pack(side='left', fill='both', expand=True)
        self.tree.bind('<Double-1>', lambda e: self.open_selected())
        self.tree.bind('<Return>', lambda e: self.open_selected())
        app.register(self.tree, self._theme_tree)

        self.detail_page = app.frame(self.frame, 'bg')
        back = app.frame(self.detail_page, 'bg')
        back.pack(fill='x')
        RoundButton(back, app, lambda: f"←  {app.t('hist.back')}", self.back).pack(side='left')
        self.detail = app.frame(self.detail_page, 'bg')
        self.detail.pack(fill='both', expand=True)
        self.server = ServerLogsView(app, self.frame, self.back_from_server)

    def open_server(self):
        self.list_page.pack_forget()
        self.server.show()

    def back_from_server(self):
        self.server.frame.pack_forget()
        self.list_page.pack(fill='both', expand=True)

    def upload_logs(self):
        """Uploads every finished log of the logs folder to the log database and deletes it (after confirming)."""
        app, t = self.app, self.app.t
        busy = [lock.get('log') for lock in app.scheduler.running().values() if lock.get('log')]
        pending = [f for f in watch_logs(app.watch_path)
                   if not any(same_path(f.removesuffix(UPLOAD_SUFFIX), b) for b in busy)]
        if not pending:
            messagebox.showinfo(t('upload.title'), t('upload.nothing', path=app.watch_path), parent=app.root)
            return
        db = app.config['LOG_DB']
        if not messagebox.askyesno(t('upload.title'), t('upload.confirm', n=len(pending), path=app.watch_path,
                                                         table=f"{db.get('DATABASE')}.{db.get('TABLE')}"),
                                   icon='warning', parent=app.root):
            return
        self.btn_upload.set_disabled(True)

        def progress(n, total):
            if self.btn_upload.winfo_exists():
                self.btn_upload.set(t('upload.running', n=n, total=total))

        def done(result, err):
            if not self.btn_upload.winfo_exists():
                return
            self.btn_upload.set_disabled(False)
            self.btn_upload.set(lambda: app.t('hist.upload'))
            if err:
                messagebox.showerror(t('upload.title'), app.error_text(err), parent=app.root)
                return
            message = t('upload.done', files=result['files'], rows=result['rows'], skipped=result['skipped'])
            if result['failed']:
                message += '\n\n' + t('upload.failed', n=result['failed'], error=result['error'])
                messagebox.showwarning(t('upload.title'), message, parent=app.root)
            else:
                messagebox.showinfo(t('upload.title'), message, parent=app.root)

        app.run_db('upload', done, on_progress=progress)

    def _theme_tree(self):
        c, t = self.app.colors, self.app.t
        for col, _ in self.columns:
            self.tree.heading(col, text=t(f'hist.col_{col}'), anchor='w')
        for kind in ('ok', 'error', 'warning', 'accent', 'muted'):
            self.tree.tag_configure(kind, foreground=c['text'] if kind == 'ok' else c[kind])
        self.tree.tag_configure('notice', foreground=c['muted'])
        self.filter_names = [(t(f'hist.status_{key}'), codes) for key, codes in self.FILTERS]
        current = self.cmb_status.current()
        self.cmb_status.configure(values=[name for name, _ in self.filter_names])
        self.cmb_status.current(current if current >= 0 else 0)

    def refresh(self, full=False):
        path = self.app.scheduler.history_path
        mtime = os.path.getmtime(path) if os.path.isfile(path) else None
        running = any(i.get('status') == 'running' for i in self.items)
        if not full and mtime == self.mtime and not running:
            return
        self.mtime = mtime
        self.items = self.app.scheduler.history()
        bots = sorted({i['bot'] for i in self.items})
        values = [self.app.t('hist.all')] + bots
        if list(self.cmb_bot['values']) != values:
            current = self.var_bot.get()
            self.cmb_bot.configure(values=values)
            self.var_bot.set(current if current in values else values[0])
        self._populate()

    def _populate(self):
        if not hasattr(self, 'filter_names'):
            return
        bot = self.var_bot.get()
        index = self.cmb_status.current()
        codes = self.filter_names[index][1] if index >= 0 else None
        query = self.var_search.get().strip().lower()
        selected = self.iid_items.get(self.tree.focus(), {}).get('id')
        self.tree.delete(*self.tree.get_children())
        self.iid_items = {}
        for n, item in enumerate(self.items):
            if bot and bot != self.app.t('hist.all') and item['bot'] != bot:
                continue
            code = item.get('status') if 'status' in item else item.get('event')
            if codes and code not in codes:
                continue
            status, kind = item_status(self.app, item)
            values = (short_time(item.get('start') or item.get('time')), item['bot'],
                      trigger_text(self.app, item.get('trigger')) if item.get('trigger') else '', status,
                      duration_text(item), '' if item.get('code') is None else item['code'])
            if query and query not in ' '.join(str(v) for v in values).lower():
                continue
            iid = self.tree.insert('', 'end', iid=f'i{n}', values=values, tags=(kind if 'status' in item else 'notice',))
            self.iid_items[iid] = item
            if item.get('id') == selected:
                self.tree.focus(iid)
                self.tree.selection_set(iid)
        self.lbl_count.configure(text=self.app.t('hist.count', n=len(self.iid_items)))

    def open_selected(self):
        item = self.iid_items.get(self.tree.focus())
        if not item or 'status' not in item:
            return
        if self.view is not None:
            self.view.destroy()
        self.view = RunView(self.app, self.detail, item)
        self.view.frame.pack(fill='both', expand=True)
        self.list_page.pack_forget()
        self.detail_page.pack(fill='both', expand=True)

    def back(self):
        if self.view is not None:
            self.view.destroy()
            self.view = None
        self.detail_page.pack_forget()
        self.list_page.pack(fill='both', expand=True)
        self.refresh(full=True)


class ScheduledPage:
    """CRON_DRIVER schedules (config/schedules.json): driver status, pause on this PC, and the schedule of each bot."""

    def __init__(self, app, master):
        self.app = app
        t = app.t
        self.frame = app.frame(master, 'bg')
        self.driver = None
        self.driver_checked = 0
        self.mtime = None

        top = app.card(self.frame)
        top.pack(fill='x')
        row = app.frame(top, 'surface')
        row.pack(fill='x')
        self.pill = Pill(row, app, '', 'muted', bg_key='surface')
        self.pill.pack(side='left')
        self.lbl_tick = app.label(row, '', 'muted', 'surface')
        self.lbl_tick.pack(side='left', padx=(12, 0))
        self.btn_pause = RoundButton(row, app, '', self.toggle_pause, bg_key='surface', size=9)
        self.btn_pause.pack(side='right')
        self.btn_install = RoundButton(row, app, lambda: t('sch.install'), self.install_driver, variant='accent', bg_key='surface', size=9)
        app.label(top, lambda: t('sch.session_hint'), 'muted', 'surface').pack(anchor='w', pady=(8, 0))
        app.label(top, lambda: t('sch.shared_hint', file=app.config['SCHEDULES_FILE']), 'muted', 'surface').pack(anchor='w')

        actions = app.frame(self.frame, 'bg')
        actions.pack(fill='x', pady=(14, 10))
        RoundButton(actions, app, lambda: t('sch.new'), self.new, variant='accent').pack(side='left')
        for key, command in (('sch.edit', self.edit), ('sch.toggle', self.toggle), ('sch.run_now', self.run_now), ('sch.delete', self.delete)):
            RoundButton(actions, app, lambda k=key: t(k), command, variant='danger' if key == 'sch.delete' else 'ghost').pack(side='left', padx=(6, 0))

        card = app.card(self.frame, padx=6, pady=6)
        card.pack(fill='both', expand=True)
        s = app.scale
        self.columns = (('bot', 200), ('schedule', 330), ('next', 140), ('last', 280), ('enabled', 70))
        self.tree = ttk.Treeview(card, columns=[c for c, _ in self.columns], show='headings', style='Config.Treeview', selectmode='browse')
        for col, width in self.columns:
            self.tree.column(col, width=int(width * s), stretch=col == 'schedule', anchor='w')
        scroll = ttk.Scrollbar(card, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.tree.pack(side='left', fill='both', expand=True)
        self.tree.bind('<Double-1>', lambda e: self.edit())
        app.register(self.tree, self._theme_tree)
        self.lbl_empty = app.label(self.tree, lambda: t('sch.empty'), 'muted', 'surface')

    def _theme_tree(self):
        c = self.app.colors
        for col, _ in self.columns:
            self.tree.heading(col, text=self.app.t(f'sch.col_{col}'), anchor='w')
        self.tree.tag_configure('disabled', foreground=c['muted'])
        self.tree.tag_configure('invalid', foreground=c['error'])

    def refresh(self, full=False):
        # the UI loop calls it every second; next/last runs only need a recalculation every few seconds
        if not full and time.monotonic() - getattr(self, 'refreshed', 0) < 10:
            return
        self.refreshed = time.monotonic()
        app, t = self.app, self.app.t
        scheduler = app.scheduler
        if full or time.monotonic() - self.driver_checked > 30:
            self.driver = scheduler.driver_status()
            self.driver_checked = time.monotonic()
        state = scheduler.read_state()
        paused = bool(state.get('paused_here'))
        if paused:
            self.pill.set(lambda: t('sch.paused'), 'warning')
        else:
            kind = {'ok': 'ok', 'missing': 'error'}.get(self.driver, 'warning')
            self.pill.set(lambda d=self.driver: t(f'sch.driver_{d}'), kind)
        last = parse_time(state.get('last_tick'))
        pc = os.environ.get('COMPUTERNAME', '')
        self.lbl_tick.configure(text=t('sch.last_tick', time=f'{last:%Y-%m-%d %H:%M}', pc=pc) if last else t('sch.never_ticked', pc=pc))
        self.btn_pause.set(lambda: t('sch.resume' if paused else 'sch.pause'), None)
        if self.driver in ('missing', 'moved'):
            self.btn_install.pack(side='right', padx=(0, 6))
        else:
            self.btn_install.pack_forget()

        try:
            schedules, self.mtime = scheduler.load_schedules()
        except (OSError, ValueError) as err:
            schedules = {}
            self.lbl_tick.configure(text=app.error_text(err))
        last_runs = {}
        if full or self.tree.get_children() or schedules:
            for item in scheduler.history():
                if 'status' in item and item['bot'] not in last_runs:
                    last_runs[item['bot']] = item
        selected = self.tree.focus()
        now = datetime.now()
        self.tree.delete(*self.tree.get_children())
        for bot, entry in sorted(schedules.items()):
            descriptions, nexts, invalid = [], [], False
            for expr in entry.get('CRON_DRIVER', []):
                try:
                    cron = CronExpression(expr)
                except ValueError:
                    descriptions.append(f'{expr} (!)')
                    invalid = True
                    continue
                descriptions.append(cron.describe(t))
                nexts.append(cron.next_after(now))
            enabled = entry.get('ENABLED', True)
            nexts = [n for n in nexts if n]
            next_text = f'{min(nexts):%Y-%m-%d %H:%M}' if enabled and nexts and not paused else '—'
            run = last_runs.get(bot)
            last_text = f"{item_status(app, run)[0]}  ·  {short_time(run.get('start'))[5:16]}" if run else '—'
            tag = 'invalid' if invalid else '' if enabled else 'disabled'
            self.tree.insert('', 'end', iid=bot, open=True, tags=(tag,),
                             values=(bot, descriptions[0] if descriptions else '—', next_text, last_text,
                                     t('sch.yes') if enabled else t('sch.no')))
            # one sub-row per extra expression, so each description reads in full
            for n, description in enumerate(descriptions[1:]):
                self.tree.insert(bot, 'end', iid=f'{bot}\x00{n}', values=('', description, '', '', ''), tags=(tag,))
        if selected and self.tree.exists(selected):
            self.tree.focus(selected)
            self.tree.selection_set(selected)
        if schedules:
            self.lbl_empty.place_forget()
        else:
            self.lbl_empty.place(relx=0.5, rely=0.4, anchor='center')

    def _selected(self):
        bot = self.tree.focus().split('\x00')[0]
        if not bot:
            messagebox.showinfo(self.app.config['APP_NAME'], self.app.t('sch.select_first'), parent=self.app.root)
        return bot

    def _save(self, change):
        """Re-reads schedules.json, applies change(schedules) and saves it (refused if it changed on disk meanwhile)."""
        try:
            schedules, mtime = self.app.scheduler.load_schedules()
            change(schedules)
            self.app.scheduler.save_schedules(schedules, mtime)
        except (OSError, ValueError) as err:
            messagebox.showerror(self.app.t('sch.save_error_title'), self.app.error_text(err), parent=self.app.root)
        self.refresh(full=True)

    def new(self):
        ScheduleEditor(self.app, None, lambda: self.refresh(full=True))

    def edit(self):
        bot = self._selected()
        if bot:
            ScheduleEditor(self.app, bot, lambda: self.refresh(full=True))

    def toggle(self):
        bot = self._selected()
        if bot:
            self._save(lambda data: data[bot].update(ENABLED=not data[bot].get('ENABLED', True)))

    def delete(self):
        bot = self._selected()
        if bot and messagebox.askyesno(self.app.t('sch.delete_title'), self.app.t('sch.delete_confirm', name=bot), parent=self.app.root):
            self._save(lambda data: data.pop(bot, None))

    def run_now(self):
        bot = self._selected()
        if bot and bot in self.app.projects:
            self.app.run_project(bot)

    def toggle_pause(self):
        self.app.scheduler.set_paused_here(not self.app.scheduler.read_state().get('paused_here'))
        self.refresh(full=True)

    def install_driver(self):
        setup = os.path.join(self.app.base_path, f"setup-{self.app.config['APP_NAME']}.ps1")
        self.app.root.configure(cursor='watch')
        self.app.root.update()
        result = subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', setup, '-NoShortcut'],
                                capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
        self.app.root.configure(cursor='')
        if result.returncode == 0:
            messagebox.showinfo(self.app.config['APP_NAME'], self.app.t('sch.install_done'), parent=self.app.root)
        else:
            tail = '\n'.join((result.stdout + result.stderr).strip().splitlines()[-6:])
            messagebox.showerror(self.app.config['APP_NAME'], self.app.t('sch.install_failed', error=tail), parent=self.app.root)
        self.refresh(full=True)


class ScheduleEditor:
    """Modal editor of one bot's CRON_DRIVER: several expressions, presets, live validation and the next runs."""

    PRESETS = (('sched.preset_15min', '*/15 * * * *'), ('sched.preset_hourly', '0 * * * *'),
               ('sched.preset_daily', '0 8 * * *'), ('sched.preset_weekdays', '0 8 * * 1-5'))

    def __init__(self, app, bot, on_saved):
        self.app = app
        self.bot = bot
        self.on_saved = on_saved
        t, s = app.t, app.scale
        schedules, _ = app.scheduler.load_schedules()
        entry = schedules.get(bot, {}) if bot else {}
        self.exprs = list(entry.get('CRON_DRIVER', []))

        self.top = tk.Toplevel(app.root)
        self.top.withdraw()
        self.top.title(t('sched.title_edit', name=bot) if bot else t('sched.title_new'))
        self.top.transient(app.root)
        self.top.resizable(False, False)
        app.register(self.top, lambda: self.top.configure(bg=app.colors['bg']))
        root = app.frame(self.top, 'bg', padx=24, pady=20)
        root.pack(fill='both', expand=True)

        app.label(root, t('sched.title_edit', name=bot) if bot else t('sched.title_new'), 'h1', 'bg').pack(anchor='w')
        if bot is None:
            row = app.frame(root, 'bg')
            row.pack(fill='x', pady=(12, 0))
            app.label(row, t('sched.bot'), 'muted', 'bg').pack(side='left', padx=(0, 8))
            self.var_bot = tk.StringVar()
            choices = [name for name, p in app.projects.items() if p['runnable'] and name not in schedules]
            themed_combobox(app, row, self.var_bot, 40, choices).pack(side='left')

        app.label(root, t('sched.expressions'), 'caption', 'bg').pack(anchor='w', pady=(16, 6))
        card = app.card(root, padx=6, pady=6)
        card.pack(fill='x')
        self.tree = ttk.Treeview(card, columns=('expr', 'desc'), show='headings', style='Config.Treeview', height=4, selectmode='browse')
        self.tree.heading('expr', text='CRON_DRIVER', anchor='w')
        self.tree.heading('desc', text=t('sched.description'), anchor='w')
        self.tree.column('expr', width=int(170 * s), stretch=False)
        self.tree.column('desc', width=int(420 * s))
        self.tree.pack(fill='x')
        self.tree.bind('<Double-1>', lambda e: self.edit_selected())
        buttons = app.frame(root, 'bg')
        buttons.pack(fill='x', pady=(6, 0))
        RoundButton(buttons, app, t('sched.remove'), self.remove, variant='danger', size=9).pack(side='left')
        app.label(buttons, t('sched.edit_hint'), 'muted', 'bg').pack(side='left', padx=(10, 0))

        app.label(root, t('sched.expression'), 'caption', 'bg').pack(anchor='w', pady=(16, 6))
        row = app.frame(root, 'bg')
        row.pack(fill='x')
        self.var_expr = tk.StringVar()
        entry_widget = themed_entry(app, row, self.var_expr, 26, font=app.font_mono)
        entry_widget.pack(side='left', ipady=int(3 * s))
        entry_widget.bind('<Return>', lambda e: self.add())
        RoundButton(row, app, t('sched.add'), self.add, variant='accent', size=9).pack(side='left', padx=(8, 0))
        presets = app.frame(root, 'bg')
        presets.pack(fill='x', pady=(8, 0))
        app.label(presets, t('sched.presets'), 'muted', 'bg').pack(side='left', padx=(0, 4))
        for key, expr in self.PRESETS:
            RoundButton(presets, app, t(key), lambda e=expr: self.var_expr.set(e), size=9).pack(side='left')
        self.lbl_check = app.label(root, '', 'muted', 'bg')
        self.lbl_check.configure(wraplength=int(600 * s))
        self.lbl_check.pack(anchor='w', pady=(8, 0))

        self.var_enabled = tk.BooleanVar(value=entry.get('ENABLED', True))
        check = tk.Checkbutton(root, text=t('sched.enabled'), variable=self.var_enabled, bd=0, highlightthickness=0,
                               font=('Segoe UI', 10), anchor='w')
        app.register(check, lambda: check.configure(bg=app.colors['bg'], fg=app.colors['text'], selectcolor=app.colors['surface'],
                                                    activebackground=app.colors['bg'], activeforeground=app.colors['text']))
        check.pack(anchor='w', pady=(14, 0))
        self.lbl_next = app.label(root, '', 'muted', 'bg')
        self.lbl_next.pack(anchor='w', pady=(4, 0))

        footer = app.frame(root, 'bg')
        footer.pack(fill='x', pady=(18, 0))
        RoundButton(footer, app, t('sched.save'), self.save, variant='accent').pack(side='right')
        RoundButton(footer, app, t('config.cancel'), self.close).pack(side='right', padx=(0, 6))
        self.lbl_error = app.label(footer, '', 'muted', 'bg')
        self.lbl_error.fg_key = 'error'
        app.apply_widget(self.lbl_error)
        self.lbl_error.pack(side='left')

        self.var_expr.trace_add('write', lambda *a: self._check())
        self._populate()
        self.top.bind('<Escape>', lambda e: self.close())
        self.top.update_idletasks()
        x = app.root.winfo_rootx() + (app.root.winfo_width() - self.top.winfo_reqwidth()) // 2
        y = app.root.winfo_rooty() + int(40 * s)
        self.top.geometry(f'+{max(0, x)}+{max(0, y)}')
        self.top.deiconify()
        app.style_window(self.top)
        self.top.grab_set()
        entry_widget.focus_set()

    def _cron(self, text):
        try:
            return CronExpression(text), None
        except ValueError as err:
            return None, self.app.error_text(err)

    def _check(self):
        text = self.var_expr.get().strip()
        if not text:
            self.lbl_check.configure(text='')
            return
        cron, error = self._cron(text)
        if error:
            self.lbl_check.fg_key = 'error'
            self.lbl_check.configure(text=error)
        else:
            upcoming = cron.upcoming(datetime.now(), 3)
            self.lbl_check.fg_key = 'muted'
            self.lbl_check.configure(text=f"{cron.describe(self.app.t)}  ·  {self.app.t('sched.next_runs', times=self._times(upcoming))}")
        self.app.apply_widget(self.lbl_check)

    @staticmethod
    def _times(values):
        return ', '.join(f'{v:%Y-%m-%d %H:%M}' for v in values) or '—'

    def _populate(self):
        self.tree.delete(*self.tree.get_children())
        upcoming = []
        for n, expr in enumerate(self.exprs):
            cron, error = self._cron(expr)
            self.tree.insert('', 'end', iid=str(n), values=(expr, error or cron.describe(self.app.t)))
            if cron:
                upcoming += cron.upcoming(datetime.now(), 5)
        next_runs = sorted(set(upcoming))[:5]
        self.lbl_next.configure(text=self.app.t('sched.next_runs', times=self._times(next_runs)))

    def add(self):
        text = ' '.join(self.var_expr.get().split())
        cron, error = self._cron(text)
        if error:
            self._check()
            return False
        if text not in self.exprs:
            self.exprs.append(text)
        self.var_expr.set('')
        self._populate()
        return True

    def remove(self):
        selected = self.tree.focus()
        if selected:
            del self.exprs[int(selected)]
            self._populate()

    def edit_selected(self):
        selected = self.tree.focus()
        if selected:
            self.var_expr.set(self.exprs.pop(int(selected)))
            self._populate()

    def save(self):
        t = self.app.t
        if self.var_expr.get().strip() and not self.add():
            return
        bot = self.bot or self.var_bot.get()
        if not bot:
            self.lbl_error.configure(text=t('sched.need_bot'))
            return
        if not self.exprs:
            self.lbl_error.configure(text=t('sched.need_expr'))
            return
        try:
            schedules, mtime = self.app.scheduler.load_schedules()
            schedules[bot] = {'CRON_DRIVER': self.exprs, 'ENABLED': bool(self.var_enabled.get())}
            self.app.scheduler.save_schedules(schedules, mtime)
        except (OSError, ValueError) as err:
            self.lbl_error.configure(text=self.app.error_text(err))
            return
        self.close()
        self.on_saved()

    def close(self):
        self.top.grab_release()
        self.top.destroy()


class SettingsDialog:
    """This PC's settings: the logs folder and the log database (Python with pymysql, .env with the credentials,
    database and table). Each value is checked as it's typed; the .env check lists the variables it must have."""

    EXAMPLE = {'host': '192.168.1.10', 'port': '3306', 'user': 'rpa_user', 'password': 'your-password'}

    def __init__(self, app):
        self.app = app
        t, s = app.t, app.scale
        db = app.config['LOG_DB']
        self.keys = db['ENV_KEYS']
        self.detected = find_db_python(app.projects_path)

        self.top = tk.Toplevel(app.root)
        self.top.withdraw()
        self.top.title(f"{t('settings.title')} - {app.config['APP_NAME']}")
        self.top.transient(app.root)
        self.top.resizable(False, False)
        app.register(self.top, lambda: self.top.configure(bg=app.colors['bg']))
        root = app.frame(self.top, 'bg', padx=24, pady=20)
        root.pack(fill='both', expand=True)
        app.label(root, t('settings.title'), 'h1', 'bg').pack(anchor='w')
        app.label(root, t('settings.subtitle'), 'muted', 'bg').pack(anchor='w')
        # two columns, so the window fits a 1080 px screen: logs folder and database | credentials (.env)
        columns = app.frame(root, 'bg')
        columns.pack(fill='both')
        left = app.frame(columns, 'bg')
        left.pack(side='left', fill='y', anchor='n')
        right = app.frame(columns, 'bg')
        right.pack(side='left', fill='y', anchor='n', padx=(16, 0))

        app.label(left, t('settings.logs_section'), 'caption', 'bg').pack(anchor='w', pady=(16, 6))
        card = app.card(left)
        card.pack(fill='x')
        self.var_watch = tk.StringVar(value=app.watch_path)
        self.lbl_watch = self._field(card, t('settings.watch'), t('settings.watch_hint'), self.var_watch,
                                     lambda: filedialog.askdirectory(parent=self.top, initialdir=self.var_watch.get()))

        app.label(left, t('settings.db_section'), 'caption', 'bg').pack(anchor='w', pady=(16, 6))
        card = app.card(left)
        card.pack(fill='x')
        self.var_python = tk.StringVar(value=db.get('PYTHON', ''))
        self.lbl_python = self._field(card, t('settings.python'), t('settings.python_hint'), self.var_python,
                                      lambda: filedialog.askopenfilename(parent=self.top, title=t('settings.python'),
                                                                         filetypes=[('python.exe', 'python.exe')]))

        app.label(right, t('settings.env_section'), 'caption', 'bg').pack(anchor='w', pady=(16, 6))
        env_card = app.card(right)
        env_card.pack(fill='both', expand=True)
        env_path = os.path.abspath(os.path.join(app.base_path, db['ENV_FILE'])) if db.get('ENV_FILE') else ''
        self.var_env = tk.StringVar(value=env_path)
        self.lbl_env = self._field(env_card, t('settings.env'), t('settings.env_hint'), self.var_env,
                                   lambda: filedialog.askopenfilename(parent=self.top, title=t('settings.env'),
                                                                      initialdir=os.path.dirname(self.var_env.get()),
                                                                      filetypes=[('.env', '*.env'), ('*', '*')]))

        # what the .env must have: one row per variable (name, what it holds, whether this file has it)
        box = app.soft_box(env_card, 'track', padx=12, pady=10)
        box.pack(fill='x', pady=(8, 0))
        app.label(box, t('settings.env_vars'), 'caption', 'track').grid(row=0, column=0, columnspan=2, sticky='w', pady=(0, 6))
        self.lbl_vars = {}
        for n, role in enumerate(LogDatabase.ROLES):
            row = 1 + n * 2
            app.label(box, self.keys[role], 'mono', 'track').grid(row=row, column=0, sticky='w', padx=(0, 12), pady=(6, 0))
            self.lbl_vars[role] = app.label(box, '', 'muted', 'track')
            self.lbl_vars[role].grid(row=row, column=1, sticky='e', pady=(6, 0))
            desc = app.label(box, t(f'settings.var_{role}'), 'muted', 'track')
            desc.configure(wraplength=int(460 * s))
            desc.grid(row=row + 1, column=0, columnspan=2, sticky='w')
        app.label(box, t('settings.example'), 'muted', 'track').grid(row=9, column=0, columnspan=2, sticky='w', pady=(14, 2))
        example = '\n'.join(f'{self.keys[role]}={self.EXAMPLE[role]}' for role in LogDatabase.ROLES)
        app.label(box, example, 'mono', 'track').grid(row=10, column=0, sticky='w')
        btn_copy = RoundButton(box, app, t('issues.copy'), lambda: self._copy(example, btn_copy), bg_key='track', size=9, icon='copy')
        btn_copy.grid(row=10, column=1, sticky='se')
        box.columnconfigure(1, weight=1)

        names = app.frame(card, 'surface')
        names.pack(fill='x', pady=(14, 0))
        self.var_database = tk.StringVar(value=db.get('DATABASE', ''))
        self.var_table = tk.StringVar(value=db.get('TABLE', ''))
        for col, (title, var) in enumerate(((t('settings.database'), self.var_database), (t('settings.table'), self.var_table))):
            field = app.frame(names, 'surface')
            field.pack(side='left', padx=(0, 16))
            app.label(field, title, 'h2', 'surface').pack(anchor='w')
            themed_entry(app, field, var, 28).pack(anchor='w', pady=(6, 0), ipady=int(3 * s))
        app.label(card, t('settings.table_hint'), 'muted', 'surface').pack(anchor='w', pady=(4, 0))

        test = app.frame(card, 'surface')
        test.pack(fill='x', pady=(14, 0))
        self.btn_test = RoundButton(test, app, t('settings.test'), self.test, bg_key='surface', variant='accent', size=9)
        self.btn_test.pack(side='left', anchor='n')
        self.lbl_test = app.label(test, '', 'muted', 'surface')
        self.lbl_test.configure(wraplength=int(400 * s))
        self.lbl_test.pack(side='left', padx=(10, 0), anchor='w')

        footer = app.frame(root, 'bg')
        footer.pack(fill='x', pady=(18, 0))
        RoundButton(footer, app, t('settings.save'), self.save, variant='accent').pack(side='right')
        RoundButton(footer, app, t('config.cancel'), self.close).pack(side='right', padx=(0, 6))
        self.lbl_error = app.label(footer, '', 'muted', 'bg')
        self.lbl_error.configure(wraplength=int(440 * s))
        self.lbl_error.pack(side='left')

        for var in (self.var_watch, self.var_python, self.var_env):
            var.trace_add('write', lambda *a: self._check())
        self._check()
        self.top.bind('<Escape>', lambda e: self.close())
        self.top.update_idletasks()
        w, h = self.top.winfo_reqwidth(), self.top.winfo_reqheight()
        x = app.root.winfo_rootx() + (app.root.winfo_width() - w) // 2
        y = app.root.winfo_rooty() + max(0, (app.root.winfo_height() - h) // 4)
        # never past the bottom of the screen (the taskbar takes about 60 px)
        x = min(x, self.top.winfo_screenwidth() - w)
        y = min(y, self.top.winfo_screenheight() - h - int(80 * s))
        self.top.geometry(f'+{max(0, x)}+{max(0, y)}')
        self.top.deiconify()
        app.style_window(self.top)
        self.top.grab_set()
        self.top.focus_force()

    def _field(self, master, title, hint, var, browse, pady=(0, 0)):
        app, s = self.app, self.app.scale
        box = app.frame(master, 'surface')
        box.pack(fill='x', pady=pady)
        app.label(box, title, 'h2', 'surface').pack(anchor='w')
        lbl = app.label(box, hint, 'muted', 'surface')
        lbl.configure(wraplength=int(480 * s))
        lbl.pack(anchor='w')
        row = app.frame(box, 'surface')
        row.pack(fill='x', pady=(6, 0))
        themed_entry(app, row, var, 50).pack(side='left', ipady=int(3 * s))
        RoundButton(row, app, app.t('settings.browse'), lambda: self._browse(var, browse), bg_key='surface', size=9).pack(side='left', padx=(8, 0))
        status = app.label(box, '', 'muted', 'surface')
        status.configure(wraplength=int(480 * s))
        status.pack(anchor='w', pady=(4, 0))
        return status

    def _browse(self, var, ask):
        value = ask()
        if value:
            var.set(os.path.normpath(value))

    def _status(self, lbl, text, kind='muted'):
        lbl.fg_key = kind
        self.app.set_text(lbl, text)
        self.app.apply_widget(lbl)

    def _copy(self, text, btn):
        self.app.root.clipboard_clear()
        self.app.root.clipboard_append(text)
        btn.set(self.app.t('issues.copied'), 'copy')
        self.top.after(1500, lambda: btn.winfo_exists() and btn.set(self.app.t('issues.copy'), 'copy'))

    def _check(self):
        t = self.app.t
        watch = self.var_watch.get().strip()
        if watch and os.path.isdir(watch):
            files = watch_logs(watch)
            groups = len({os.path.dirname(f) for f in files})
            self._status(self.lbl_watch, t('settings.watch_ok', files=len(files), groups=groups), 'ok')
        else:
            self._status(self.lbl_watch, t('settings.watch_missing'), 'error')

        python = self.var_python.get().strip()
        if not python:
            if self.detected:
                self._status(self.lbl_python, t('settings.python_detected', path=self.detected), 'ok')
            else:
                self._status(self.lbl_python, t('settings.python_none'), 'error')
        elif not os.path.isfile(python):
            self._status(self.lbl_python, t('settings.python_missing'), 'error')
        elif has_pymysql(python):
            self._status(self.lbl_python, t('settings.python_ok'), 'ok')
        else:
            self._status(self.lbl_python, t('settings.python_no_lib', python=python), 'error')

        env = self.var_env.get().strip()
        exists = bool(env) and os.path.isfile(env)
        self._status(self.lbl_env, '' if exists else t('settings.env_missing'), 'error')
        values = LogDatabase.env_values(env, self.keys) if exists else {}
        for role, lbl in self.lbl_vars.items():
            value = values.get(role)
            if not value:
                self._status(lbl, t('settings.var_missing'), 'error')
            elif role == 'password':
                self._status(lbl, t('settings.var_secret'), 'ok')
            else:
                self._status(lbl, t('settings.var_found', value=value), 'ok')

    def _db_values(self):
        return {'PYTHON': self.var_python.get().strip(), 'ENV_FILE': self.var_env.get().strip(),
                'DATABASE': self.var_database.get().strip(), 'TABLE': self.var_table.get().strip()}

    def test(self):
        self.btn_test.set_disabled(True)
        self._status(self.lbl_test, self.app.t('settings.testing'))

        def done(result, err):
            if not self.top.winfo_exists():
                return
            self.btn_test.set_disabled(False)
            if err:
                self._status(self.lbl_test, self.app.error_text(err), 'error')
            else:
                self._status(self.lbl_test, self.app.t('settings.test_ok', rows=result['rows']), 'ok')

        self.app.run_db('test', done, db=self._db_values())

    def save(self):
        watch = self.var_watch.get().strip()
        if not watch or not os.path.isdir(watch):
            self._status(self.lbl_error, self.app.t('settings.err_watch', path=watch or '-'), 'error')
            return
        self.close()
        self.app.save_user_settings(os.path.abspath(watch), self._db_values())

    def close(self):
        self.top.grab_release()
        self.top.destroy()


class ServerLogsView:
    """Logs already uploaded to the log database (LOG_DB), queried with `main.py --db query`: filters, newest first,
    and the whole message of the selected row."""

    LEVELS = ('INFO', 'WARNING', 'ERROR', 'DEBUG', 'CRITICAL')
    DATE_RE = re.compile(r'^\d{4}-\d\d-\d\d$')

    def __init__(self, app, master, on_back):
        self.app = app
        s = app.scale
        self.frame = app.frame(master, 'bg')
        self.rows = {}
        self.processes = []
        self.busy = False

        top = app.frame(self.frame, 'bg')
        top.pack(fill='x')
        RoundButton(top, app, lambda: f"←  {app.t('hist.back')}", on_back).pack(side='left')
        app.label(top, lambda: app.t('server.title'), 'h1', 'bg').pack(side='left', padx=(12, 0))
        self.lbl_table = app.label(top, '', 'muted', 'bg')
        self.lbl_table.pack(side='left', padx=(10, 0), pady=(4, 0))

        filters = app.frame(self.frame, 'bg')
        filters.pack(fill='x', pady=(12, 10))
        self.var_process, self.var_level = tk.StringVar(), tk.StringVar()
        self.var_text, self.var_from, self.var_to = tk.StringVar(), tk.StringVar(), tk.StringVar()
        app.label(filters, lambda: app.t('server.process'), 'muted', 'bg').pack(side='left', padx=(0, 6))
        field = themed_combobox(app, filters, self.var_process, 24)
        field.pack(side='left')
        self.cmb_process = field.widget
        app.label(filters, lambda: app.t('server.level'), 'muted', 'bg').pack(side='left', padx=(14, 6))
        field = themed_combobox(app, filters, self.var_level, 9)
        field.pack(side='left')
        self.cmb_level = field.widget
        entries = []
        for key, var, width in (('server.text', self.var_text, 18), ('server.from', self.var_from, 11), ('server.to', self.var_to, 11)):
            app.label(filters, lambda k=key: app.t(k), 'muted', 'bg').pack(side='left', padx=(14, 6))
            entry = themed_entry(app, filters, var, width)
            entry.pack(side='left', ipady=int(3 * s))
            entry.bind('<Return>', lambda e: self.search())
            entries.append(entry)
        self.btn_search = RoundButton(filters, app, lambda: app.t('server.search'), self.search, variant='accent')
        self.btn_search.pack(side='left', padx=(14, 0))
        self.lbl_count = app.label(filters, lambda: app.t('server.empty'), 'muted', 'bg')
        self.lbl_count.pack(side='right')

        app.label(self.frame, lambda: app.t('server.hint'), 'muted', 'bg').pack(side='bottom', anchor='w', pady=(8, 0))
        detail = app.card(self.frame, padx=12, pady=8)
        detail.pack(side='bottom', fill='x', pady=(10, 0))
        self.txt_detail = tk.Text(detail, height=6, bd=0, highlightthickness=0, wrap='word', font=app.font_mono, state='disabled')
        app.register(self.txt_detail, lambda: self.txt_detail.configure(bg=app.colors['surface'], fg=app.colors['text'],
                                                                         insertbackground=app.colors['text'],
                                                                         selectbackground=app.colors['accent_soft'],
                                                                         selectforeground=app.colors['text']))
        self.txt_detail.pack(fill='x')

        card = app.card(self.frame, padx=6, pady=6)
        card.pack(fill='both', expand=True)
        card.rowconfigure(0, weight=1)
        card.columnconfigure(0, weight=1)
        self.columns = (('time', 160), ('process', 200), ('run', 140), ('level', 90), ('message', 700))
        self.tree = ttk.Treeview(card, columns=[c for c, _ in self.columns], show='headings', style='Config.Treeview')
        for col, width in self.columns:
            self.tree.column(col, width=int(width * s), stretch=col == 'message', anchor='w')
        yscroll = ttk.Scrollbar(card, orient='vertical', command=self.tree.yview)
        xscroll = ttk.Scrollbar(card, orient='horizontal', command=self.tree.xview)
        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.tree.grid(row=0, column=0, sticky='nsew')
        yscroll.grid(row=0, column=1, sticky='ns')
        xscroll.grid(row=1, column=0, sticky='ew')
        self.tree.bind('<<TreeviewSelect>>', lambda e: self._show_detail())
        self.tree.bind('<Control-c>', lambda e: self._copy())
        app.register(self.tree, self._theme)

    def _theme(self):
        c, t = self.app.colors, self.app.t
        for col, _ in self.columns:
            self.tree.heading(col, text=t(f'server.col_{col}'), anchor='w')
        self.tree.tag_configure('WARNING', foreground=c['warning'])
        for level in ('ERROR', 'CRITICAL'):
            self.tree.tag_configure(level, foreground=c['error'])
        self._set_choices()

    def _set_choices(self):
        # "All" is translated: the comboboxes are rebuilt when the language (or the list of processes) changes
        everything = self.app.t('server.all')
        for cmb, var, values in ((self.cmb_process, self.var_process, self.processes), (self.cmb_level, self.var_level, self.LEVELS)):
            choices = [everything, *values]
            cmb.configure(values=choices)
            if var.get() not in choices:
                var.set(everything)

    def show(self):
        db = self.app.config['LOG_DB']
        self.lbl_table.configure(text=f"{db.get('DATABASE')}.{db.get('TABLE')}")
        self.frame.pack(fill='both', expand=True)

    def search(self):
        if self.busy:
            return
        t = self.app.t
        dates = (self.var_from.get().strip(), self.var_to.get().strip())
        if any(d and not self.DATE_RE.match(d) for d in dates):
            messagebox.showerror(t('server.title'), t('db.err_date'), parent=self.app.root)
            return
        everything = t('server.all')
        filters = {'process': '' if self.var_process.get() == everything else self.var_process.get(),
                   'level': '' if self.var_level.get() == everything else self.var_level.get(),
                   'text': self.var_text.get().strip(), 'date_from': dates[0], 'date_to': dates[1]}
        self.busy = True
        self.btn_search.set_disabled(True)
        self.app.set_text(self.lbl_count, lambda: self.app.t('server.loading'))
        self.app.run_db('query', self._show_rows, payload={'filters': filters})

    def _show_rows(self, result, err):
        if not self.frame.winfo_exists():
            return
        app = self.app
        self.busy = False
        self.btn_search.set_disabled(False)
        if err:
            app.set_text(self.lbl_count, '')
            messagebox.showerror(app.t('server.title'), app.error_text(err), parent=app.root)
            return
        self.processes = result['processes']
        self._set_choices()
        self.tree.delete(*self.tree.get_children())
        self.rows = {}
        for stamp, process, run_id, level, message in result['rows']:
            iid = self.tree.insert('', 'end', values=(stamp, process, run_id, level, message.split('\n', 1)[0]), tags=(level.upper(),))
            self.rows[iid] = (stamp, process, run_id, level, message)
        n = len(result['rows'])
        app.set_text(self.lbl_count, lambda: app.t('server.more' if result['more'] else 'server.count', n=n))
        self._show_detail()

    def _show_detail(self):
        rows = [self.rows[iid] for iid in self.tree.selection() if iid in self.rows]
        self.txt_detail.configure(state='normal')
        self.txt_detail.delete('1.0', 'end')
        if rows:
            stamp, process, run_id, level, message = rows[0]
            self.txt_detail.insert('1.0', f'{stamp}  ·  {process}  ·  {run_id}  ·  {level}\n{message}')
        self.txt_detail.configure(state='disabled')

    def _copy(self):
        rows = [self.rows[iid] for iid in self.tree.selection() if iid in self.rows]
        if rows:
            self.app.root.clipboard_clear()
            self.app.root.clipboard_append('\n'.join('\t'.join(str(v) for v in row) for row in rows))


# ---------- scheduler (CRON_DRIVER) ----------
# A Windows scheduled task (the "driver") runs `main.py --tick` every minute. The tick launches the bots whose
# CRON_DRIVER expressions are due through `main.py --run <bot>`: a detached runner that owns the bot process, writes its
# output to a file and records it in the history, so runs survive the UI being closed. Schedules live in
# config/schedules.json (shared with the app); runtime state (locks, queue, history, outputs) is per PC.


def find_group_log(source):
    match = re.search(r"GROUP_LOG\s*=\s*['\"]([^'\"]+)", source) or re.search(r"set_group\(\s*['\"]([^'\"]+)", source)
    return match.group(1) if match else None


def find_venv(path, name):
    """Returns the bot's venv folder: venv-<name> if usable, else any subfolder that is a venv (has pyvenv.cfg
    and Scripts\\python.exe), whatever it is called. Falls back to venv-<name> when there is none."""
    default = os.path.join(path, f'venv-{name}')
    if os.path.isfile(os.path.join(default, 'Scripts', 'python.exe')):
        return default
    try:
        entries = sorted(os.listdir(path), key=str.lower)
    except OSError:
        return default
    for entry in entries:
        candidate = os.path.join(path, entry)
        if (os.path.isfile(os.path.join(candidate, 'pyvenv.cfg'))
                and os.path.isfile(os.path.join(candidate, 'Scripts', 'python.exe'))):
            return candidate
    return default


def iso(dt):
    return dt.isoformat(timespec='seconds') if dt else None


def parse_time(text):
    try:
        return datetime.fromisoformat(text) if text else None
    except ValueError:
        return None


def process_started(pid):
    """Creation time of a running process (FILETIME as int), or None; compared with the stored one so a reused PID
    isn't taken for the same process."""
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_bool, ctypes.c_ulong]
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return None
    try:
        code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(ctypes.c_void_p(handle), ctypes.byref(code)) or code.value != 259:  # STILL_ACTIVE
            return None
        times = [ctypes.c_ulonglong() for _ in range(4)]
        kernel32.GetProcessTimes(ctypes.c_void_p(handle), *(ctypes.byref(t) for t in times))
        return times[0].value
    finally:
        kernel32.CloseHandle(ctypes.c_void_p(handle))


class CronExpression:
    """Standard 5-field cron (minute hour day-of-month month day-of-week) with *, a-b, lists, /steps, JAN-DEC, SUN-SAT
    and @hourly/@daily/@weekly/@monthly/@yearly. As in Vixie cron, when both day fields are restricted either matches."""

    MACROS = {'@hourly': '0 * * * *', '@daily': '0 0 * * *', '@midnight': '0 0 * * *', '@weekly': '0 0 * * 0',
              '@monthly': '0 0 1 * *', '@yearly': '0 0 1 1 *', '@annually': '0 0 1 1 *'}
    BOUNDS = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))
    MONTHS = ('JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC')
    WEEKDAYS = ('SUN', 'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT')

    def __init__(self, text):
        self.text = ' '.join(text.split())
        fields = self.MACROS.get(self.text.lower(), self.text).split()
        if len(fields) != 5:
            raise LocalizedError('cron.invalid_fields', expr=self.text)
        self.minutes, self.hours, self.days, self.months, weekdays = (self._parse(f, i) for i, f in enumerate(fields))
        self.weekdays = {d % 7 for d in weekdays}
        # Vixie cron: a day field starting with '*' (also '*/2') doesn't make the two day fields an OR
        self.days_star = fields[2].startswith('*')
        self.weekdays_star = fields[4].startswith('*')

    def _value(self, text, index):
        names = {3: self.MONTHS, 4: self.WEEKDAYS}.get(index)
        if names and text.upper() in names:
            return names.index(text.upper()) + (1 if index == 3 else 0)
        return int(text)

    def _parse(self, field, index):
        low, high = self.BOUNDS[index]
        values = set()
        for part in field.split(','):
            base, slash, step = part.partition('/')
            try:
                step = int(step) if slash else 1
                if base == '*':
                    start, end = low, high
                elif '-' in base:
                    start, end = (self._value(v, index) for v in base.split('-', 1))
                else:
                    start = self._value(base, index)
                    end = high if slash else start
                if step < 1 or not low <= start <= end <= high:
                    raise ValueError(part)
            except ValueError:
                raise LocalizedError('cron.invalid_value', value=part, position=index + 1, low=low, high=high) from None
            values.update(range(start, end + 1, step))
        return values

    def _day_matches(self, day):
        dom = day.day in self.days
        dow = (day.weekday() + 1) % 7 in self.weekdays
        return dom and dow if self.days_star or self.weekdays_star else dom or dow

    def matches(self, dt):
        return dt.minute in self.minutes and dt.hour in self.hours and dt.month in self.months and self._day_matches(dt)

    def next_after(self, dt):
        """First firing time strictly after dt (None if the date never exists, e.g. 30 FEB)."""
        t = dt.replace(second=0, microsecond=0) + timedelta(minutes=1)
        hours, minutes = sorted(self.hours), sorted(self.minutes)
        # a 29 FEB expression can wait 8 years (2096 -> 2104)
        for _ in range(366 * 8 + 1):
            if t.month in self.months and self._day_matches(t):
                for h in hours:
                    for m in minutes:
                        if (h, m) >= (t.hour, t.minute):
                            return t.replace(hour=h, minute=m)
            t = (t + timedelta(days=1)).replace(hour=0, minute=0)
        return None

    def between(self, after, until, limit=1000):
        """Firing times in (after, until]."""
        result, t = [], after
        while len(result) < limit:
            t = self.next_after(t)
            if t is None or t > until:
                break
            result.append(t)
        return result

    def upcoming(self, after, n):
        result, t = [], after
        for _ in range(n):
            t = self.next_after(t)
            if t is None:
                break
            result.append(t)
        return result

    @staticmethod
    def _step(values):
        if len(values) < 2:
            return None
        steps = {b - a for a, b in zip(values, values[1:])}
        return steps.pop() if len(steps) == 1 else None

    @staticmethod
    def _compress(values, fmt):
        # 1,2,3,4,5 -> "Mon–Fri"; 1,15 -> "1, 15"
        groups, run = [], [values[0]]
        for v in values[1:]:
            if v == run[-1] + 1:
                run.append(v)
            else:
                groups.append(run)
                run = [v]
        groups.append(run)
        return ', '.join(f'{fmt(g[0])}–{fmt(g[-1])}' if len(g) >= 3 else ', '.join(fmt(v) for v in g) for g in groups)

    def describe(self, t):
        """Readable text in the UI language (t = App.t); falls back to the expression itself for unusual patterns."""
        if self.next_after(datetime(2000, 1, 1)) is None:
            return t('cron.never')
        hhmm = lambda h, m: f'{h:02d}:{m:02d}'
        minutes, hours = sorted(self.minutes), sorted(self.hours)
        all_minutes, all_hours = len(minutes) == 60, len(hours) == 24
        step_m, step_h = self._step(minutes), self._step(hours)
        if all_minutes and all_hours:
            when = t('cron.every_minute')
        elif all_hours and step_m and minutes[0] == 0 and 60 % step_m == 0 and len(minutes) == 60 // step_m:
            when = t('cron.every_n_minutes', n=step_m)
        elif all_hours:
            when = t('cron.minutes_past', minutes=', '.join(str(m) for m in minutes))
        elif len(minutes) == 1 and len(hours) > 2 and step_h and step_h > 1:
            when = t('cron.every_n_hours', n=step_h, start=hhmm(hours[0], minutes[0]), end=hhmm(hours[-1], minutes[0]))
        elif len(minutes) * len(hours) <= 6:
            when = t('cron.at_times', times=', '.join(hhmm(h, m) for h in hours for m in minutes))
        else:
            return self.text

        dow_names = t('cron.dow_names').split(',')
        dom = t('cron.on_days_of_month', days=self._compress(sorted(self.days), str)) if len(self.days) < 31 else None
        dow = self._compress(sorted(self.weekdays), lambda v: dow_names[v]) if len(self.weekdays) < 7 else None
        if dom and dow:
            days = f'{dom}  ·  {dow}' if self.days_star or self.weekdays_star else t('cron.or', a=dom, b=dow)
        else:
            days = dom or dow or t('cron.every_day')
        parts = [when, days]
        if len(self.months) < 12:
            month_names = t('cron.month_names').split(',')
            parts.append(t('cron.in_months', months=self._compress(sorted(self.months), lambda v: month_names[v - 1])))
        return '  ·  '.join(parts)


class Scheduler:
    """CRON_DRIVER engine shared by the UI, the per-minute tick and the runner (no Tk here).

    State dir (%LOCALAPPDATA%/<APP_NAME>/scheduler): state.json (last tick, queue, paused on this PC),
    locks/<bot>.json (one per running bot), runs/<bot>/<run_id>.out (stdout/stderr), history.jsonl."""

    def __init__(self, base_path, config, state_dir=None):
        self.config = config
        self.projects_path = os.path.abspath(os.path.join(base_path, config['PROJECTS_PATH']))
        self.watch_path = os.path.abspath(os.path.join(base_path, config['WATCH_PATH']))
        self.schedules_path = os.path.abspath(os.path.join(base_path, config['SCHEDULES_FILE']))
        self.state_dir = state_dir or os.path.join(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')), config['APP_NAME'], 'scheduler')
        self.locks_dir = os.path.join(self.state_dir, 'locks')
        self.runs_dir = os.path.join(self.state_dir, 'runs')
        self.state_path = os.path.join(self.state_dir, 'state.json')
        self.history_path = os.path.join(self.state_dir, 'history.jsonl')
        os.makedirs(self.locks_dir, exist_ok=True)
        os.makedirs(self.runs_dir, exist_ok=True)
        pythonw = os.path.join(base_path, f"venv-{config['APP_NAME']}", 'Scripts', 'pythonw.exe')
        self.app_python = pythonw if os.path.isfile(pythonw) else sys.executable
        self.app_main = os.path.abspath(__file__)

    @staticmethod
    def now():
        return datetime.now().replace(microsecond=0)

    # ---------- files ----------

    @contextlib.contextmanager
    def locked(self):
        """Inter-process lock: the UI, the tick and every runner read-modify-write the same state files. Not re-entrant."""
        with open(os.path.join(self.state_dir, '.lock'), 'a+b') as fh:
            deadline = time.monotonic() + 30
            while True:
                try:
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() > deadline:
                        raise
                    time.sleep(0.05)
            try:
                yield
            finally:
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)

    @staticmethod
    def _read_json(path, default):
        try:
            with open(path, encoding='utf-8-sig') as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return default

    @staticmethod
    def _write_json(path, data):
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(data, fh, indent=4, ensure_ascii=False)
            fh.write('\n')
        os.replace(tmp, path)

    def read_state(self):
        return self._read_json(self.state_path, {})

    def _history_add(self, **record):
        with open(self.history_path, 'a', encoding='utf-8') as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + '\n')

    # ---------- schedules ----------

    def load_schedules(self):
        """({bot: {'CRON_DRIVER': [...], 'ENABLED': bool}}, mtime); mtime is None when the file doesn't exist."""
        try:
            mtime = os.path.getmtime(self.schedules_path)
            with open(self.schedules_path, encoding='utf-8-sig') as fh:
                data = json.load(fh)
        except FileNotFoundError:
            return {}, None
        if not isinstance(data, dict):
            raise LocalizedError('error.not_json_object')
        return data, mtime

    def save_schedules(self, schedules, mtime):
        current = os.path.getmtime(self.schedules_path) if os.path.isfile(self.schedules_path) else None
        if current != mtime:
            raise LocalizedError('error.changed_on_disk', file=self.config['SCHEDULES_FILE'])
        self._write_json(self.schedules_path, schedules)
        return os.path.getmtime(self.schedules_path)

    # ---------- runs ----------

    def lock_path(self, bot):
        return os.path.join(self.locks_dir, f'{bot}.json')

    def read_lock(self, bot):
        return self._read_json(self.lock_path(bot), None)

    def out_path(self, bot, run_id):
        return os.path.join(self.runs_dir, bot, f'{run_id}.out')

    def running(self, cleanup=False):
        """{bot: lock} of the runs whose runner is alive. With cleanup (caller holds the lock), a lock left by a runner
        that died without finishing is removed and its run closed as 'interrupted'."""
        result = {}
        for name in os.listdir(self.locks_dir):
            if not name.endswith('.json'):
                continue
            path = os.path.join(self.locks_dir, name)
            lock = self._read_json(path, None)
            if lock and process_started(lock['runner_pid']) == lock.get('runner_started'):
                result[lock['bot']] = lock
            elif cleanup:
                if lock:
                    self._history_add(event='end', id=lock['run_id'], bot=lock['bot'], end=iso(self.now()), status='interrupted', code=None)
                os.remove(path)
        return result

    def history(self):
        """Every run (start + end merged by id) and every missed/queued notice, newest first."""
        runs, notices = {}, []
        try:
            with open(self.history_path, encoding='utf-8') as fh:
                lines = fh.readlines()
        except OSError:
            lines = []
        for line in lines:
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if record.get('event') in ('start', 'end'):
                runs.setdefault(record['id'], {'status': 'running'}).update({k: v for k, v in record.items() if k != 'event'})
            else:
                notices.append(record)
        items = list(runs.values()) + notices
        return sorted(items, key=lambda r: r.get('start') or r.get('time') or '', reverse=True)

    # ---------- tick ----------

    def tick(self, now=None):
        now = (now or self.now()).replace(second=0, microsecond=0)
        with self.locked():
            state = self.read_state()
            last = parse_time(state.get('last_tick'))
            if last is None or last >= now:
                last = now - timedelta(minutes=1)
            running = self.running(cleanup=True)
            self._drain(state, running)
            if not state.get('paused_here'):
                schedules, _ = self.load_schedules()
                late_after = timedelta(minutes=self.config['MISSED_AFTER_MINUTES'])
                for bot, entry in schedules.items():
                    if not entry.get('ENABLED', True):
                        continue
                    due = None
                    for expr in entry.get('CRON_DRIVER', []):
                        try:
                            fires = CronExpression(expr).between(last, now)
                        except ValueError:
                            continue
                        # PC off, asleep or without a session: those runs are skipped (like cron) and recorded once
                        late = [f for f in fires if now - f > late_after]
                        if late:
                            self._history_add(event='missed', id=f"missed-{bot}-{late[0]:%Y%m%d%H%M}", bot=bot, expr=expr,
                                              count=len(late), first=iso(late[0]), last=iso(late[-1]), time=iso(now))
                        on_time = [f for f in fires if now - f <= late_after]
                        if on_time and (due is None or on_time[-1] > due):
                            due = on_time[-1]
                    if due:
                        self._request(bot, 'cron', due, state, running)
            state['last_tick'] = iso(now)
            if state.get('pruned_on') != now.date().isoformat():
                self._prune(now)
                state['pruned_on'] = now.date().isoformat()
            self._write_json(self.state_path, state)

    def request_run(self, bot, trigger='manual'):
        """Starts a run now, or queues it when the bot is already running or MAX_PARALLEL is reached.
        Returns 'started', 'queued' or 'already_queued'."""
        with self.locked():
            state = self.read_state()
            result = self._request(bot, trigger, None, state, self.running(cleanup=True))
            self._write_json(self.state_path, state)
        return result

    def cancel_queued(self, bot):
        with self.locked():
            state = self.read_state()
            item = state.get('queue', {}).pop(bot, None)
            if item:
                self._history_add(event='cancelled', id=f"cancelled-{bot}-{self.now():%Y%m%d%H%M%S}", bot=bot,
                                  trigger=item['trigger'], time=iso(self.now()))
            self._write_json(self.state_path, state)
        return item is not None

    @property
    def driver_task(self):
        return f"{self.config['APP_NAME']} driver"

    def driver_status(self):
        """'missing', 'disabled', 'moved' (the task runs another copy of the app: re-run the setup) or 'ok'.
        Read from `schtasks /XML`, whose content (unlike its text output) doesn't depend on the Windows language."""
        result = subprocess.run(['schtasks', '/Query', '/TN', self.driver_task, '/XML'], capture_output=True,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode != 0:
            return 'missing'
        raw = result.stdout
        text = raw.decode('utf-16') if raw[:2] in (b'\xff\xfe', b'\xfe\xff') else raw.decode('utf-8', errors='replace')
        ns = {'t': 'http://schemas.microsoft.com/windows/2004/02/mit/task'}
        try:
            root = ET.fromstring(text.lstrip('﻿'))
        except ET.ParseError:
            return 'missing'
        if (root.findtext('t:Settings/t:Enabled', 'true', ns) or 'true').strip().lower() == 'false':
            return 'disabled'
        arguments = root.findtext('t:Actions/t:Exec/t:Arguments', '', ns)
        return 'ok' if os.path.normcase(self.app_main) in os.path.normcase(arguments) else 'moved'

    def set_paused_here(self, value):
        with self.locked():
            state = self.read_state()
            state['paused_here'] = bool(value)
            self._write_json(self.state_path, state)

    def _request(self, bot, trigger, scheduled_for, state, running):
        queue = state.setdefault('queue', {})
        if bot in running or len(running) >= self.config['MAX_PARALLEL']:
            if bot in queue:
                return 'already_queued'
            queue[bot] = {'trigger': trigger, 'scheduled_for': iso(scheduled_for), 'queued_at': iso(self.now())}
            self._history_add(event='queued', id=f"queued-{bot}-{self.now():%Y%m%d%H%M%S}", bot=bot, trigger=trigger,
                              scheduled_for=iso(scheduled_for), time=iso(self.now()),
                              reason='already_running' if bot in running else 'max_parallel')
            return 'queued'
        queue.pop(bot, None)
        running[bot] = self._launch(bot, trigger, scheduled_for)
        return 'started'

    def _drain(self, state, running):
        queue = state.setdefault('queue', {})
        for bot, item in sorted(queue.items(), key=lambda kv: kv[1]['queued_at']):
            if bot not in running and len(running) < self.config['MAX_PARALLEL']:
                del queue[bot]
                running[bot] = self._launch(bot, item['trigger'], parse_time(item['scheduled_for']))

    def _spawn(self, args):
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        common = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
        try:
            # the driver task runs inside a job object; breaking away keeps the runner alive after the tick ends
            return subprocess.Popen(args, creationflags=flags | subprocess.CREATE_BREAKAWAY_FROM_JOB, **common)
        except OSError:
            return subprocess.Popen(args, creationflags=flags, **common)

    def _launch(self, bot, trigger, scheduled_for):
        start = self.now()
        run_id = f"{datetime.now():%Y%m%d%H%M%S%f}"[:17] + f'-{bot}'
        args = [self.app_python, self.app_main, '--run', bot, '--run-id', run_id, '--trigger', trigger]
        if scheduled_for:
            args += ['--scheduled-for', iso(scheduled_for)]
        proc = self._spawn(args)
        lock = {'bot': bot, 'run_id': run_id, 'trigger': trigger, 'scheduled_for': iso(scheduled_for), 'start': iso(start),
                'runner_pid': proc.pid, 'runner_started': process_started(proc.pid), 'out': self.out_path(bot, run_id)}
        self._write_json(self.lock_path(bot), lock)
        self._history_add(event='start', id=run_id, bot=bot, trigger=trigger, scheduled_for=iso(scheduled_for),
                          start=iso(start), out=lock['out'])
        return lock

    def stop(self, bot):
        """Aborts a running bot (its whole process tree: jobs, Chrome...). The runner records it as 'aborted'."""
        with self.locked():
            lock = self._read_json(self.lock_path(bot), None)
            if not lock:
                return False
            lock['abort_requested'] = True
            self._write_json(self.lock_path(bot), lock)
        subprocess.run(['taskkill', '/PID', str(lock.get('child_pid') or lock['runner_pid']), '/T', '/F'],
                       capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        return True

    # ---------- runner (main.py --run) ----------

    def run(self, bot, run_id, trigger, scheduled_for):
        path = os.path.join(self.projects_path, bot)
        main = os.path.join(path, 'src', 'main.py')
        python = os.path.join(find_venv(path, bot), 'Scripts', 'python.exe')
        group = bot
        if os.path.isfile(main):
            with open(main, encoding='utf-8', errors='replace') as fh:
                group = find_group_log(fh.read()) or bot
        watch_dir = os.path.join(self.watch_path, group)
        known = set(os.listdir(watch_dir)) if os.path.isdir(watch_dir) else set()
        out = self.out_path(bot, run_id)
        os.makedirs(os.path.dirname(out), exist_ok=True)

        code = None
        with open(out, 'wb') as fh:
            env = os.environ.copy()
            env['PYTHONIOENCODING'] = 'utf-8'
            env['PYTHONUNBUFFERED'] = '1'
            try:
                child = subprocess.Popen([python, main], cwd=path, env=env, stdin=subprocess.DEVNULL, stdout=fh,
                                         stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
            except OSError as err:
                fh.write(f'could not start the process: {err}\n'.encode('utf-8'))
            else:
                self._update_lock(bot, run_id, child_pid=child.pid)
                # while it runs, the bot's kreton-watch log is published in the lock as soon as it appears
                log = None
                while True:
                    try:
                        code = child.wait(timeout=1)
                        break
                    except subprocess.TimeoutExpired:
                        pass
                    if log is None:
                        log = self._new_log(watch_dir, known)
                        if log:
                            self._update_lock(bot, run_id, log=log)

        new_log = self._new_log(watch_dir, known)
        with self.locked():
            lock = self._read_json(self.lock_path(bot), None)
            aborted = bool(lock and lock['run_id'] == run_id and lock.get('abort_requested'))
            if lock and lock['run_id'] == run_id:
                os.remove(self.lock_path(bot))
            status = 'aborted' if aborted else 'start_failed' if code is None else 'succeeded' if code == 0 else 'failed'
            self._history_add(event='end', id=run_id, bot=bot, end=iso(self.now()), status=status, code=code, log=new_log)
            # a finished run frees a slot: start what was waiting
            state = self.read_state()
            self._drain(state, self.running(cleanup=True))
            self._write_json(self.state_path, state)

    def _update_lock(self, bot, run_id, **values):
        with self.locked():
            lock = self._read_json(self.lock_path(bot), None)
            if lock and lock['run_id'] == run_id:
                lock.update(values)
                self._write_json(self.lock_path(bot), lock)

    @staticmethod
    def _new_log(watch_dir, known):
        # the first log file created after the run started is the one of its main.py (Pipeline's group log)
        if not os.path.isdir(watch_dir):
            return None
        new = sorted(f for f in os.listdir(watch_dir) if f.endswith('.txt') and f not in known)
        return os.path.join(watch_dir, new[0]) if new else None

    def _prune(self, now):
        cutoff = iso(now - timedelta(days=self.config['HISTORY_DAYS']))
        try:
            with open(self.history_path, encoding='utf-8') as fh:
                lines = fh.readlines()
        except OSError:
            return
        live = {lock['run_id'] for lock in self.running().values()}
        records = []
        for line in lines:
            try:
                records.append((json.loads(line), line))
            except ValueError:
                continue
        # a run is kept or dropped as a whole, by its newest timestamp (its 'end')
        newest = {}
        for record, _ in records:
            stamp = record.get('end') or record.get('start') or record.get('time') or ''
            newest[record.get('id')] = max(newest.get(record.get('id'), ''), stamp)
        kept = [line for record, line in records if newest[record.get('id')] >= cutoff or record.get('id') in live]
        with open(self.history_path + '.tmp', 'w', encoding='utf-8') as fh:
            fh.writelines(kept)
        os.replace(self.history_path + '.tmp', self.history_path)
        for root, _, files in os.walk(self.runs_dir):
            for name in files:
                full = os.path.join(root, name)
                if datetime.fromtimestamp(os.path.getmtime(full)) < now - timedelta(days=self.config['HISTORY_DAYS']):
                    os.remove(full)


# ---------- settings and log database ----------
# Per-PC settings (%LOCALAPPDATA%\<APP_NAME>\settings.json) override config.json: the logs folder (WATCH_PATH) and the
# log database fields of LOG_DB. The app is standard library only, so uploads and server queries run as
# `main.py --db <action>` under another Python that has pymysql (a bot's venv), which prints JSON lines.

LOG_DB_EDITABLE = ('PYTHON', 'ENV_FILE', 'DATABASE', 'TABLE')
WATCH_LINE_RE = re.compile(r'^([^§]*)§(\d{1,16})§(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)§([^§]*)§(.*)$')
UPLOAD_SUFFIX = '.uploading'


def settings_file(config):
    return os.path.join(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')), config['APP_NAME'], 'settings.json')


def read_settings(config):
    try:
        with open(settings_file(config), encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def apply_settings(config, settings):
    """config.json with this PC's overrides: WATCH_PATH and the editable LOG_DB fields."""
    merged = {**config, 'LOG_DB': dict(config.get('LOG_DB', {}))}
    if settings.get('WATCH_PATH'):
        merged['WATCH_PATH'] = settings['WATCH_PATH']
    for key, value in (settings.get('LOG_DB') or {}).items():
        if key in LOG_DB_EDITABLE:
            merged['LOG_DB'][key] = value
    return merged


def find_db_python(projects_path):
    """python.exe of the first bot venv with pymysql installed: the default Python for the log database."""
    try:
        projects = sorted(os.listdir(projects_path), key=str.lower)
    except OSError:
        return ''
    for name in projects:
        path = os.path.join(projects_path, name)
        try:
            entries = sorted(os.listdir(path), key=str.lower) if os.path.isdir(path) else []
        except OSError:
            continue
        for entry in entries:
            python = os.path.join(path, entry, 'Scripts', 'python.exe')
            if os.path.isfile(python) and has_pymysql(python):
                return python
    return ''


def has_pymysql(python):
    # venv layout: <venv>\Scripts\python.exe and <venv>\Lib\site-packages (also a base install: <python>\Lib\site-packages)
    folder = os.path.dirname(os.path.abspath(python))
    roots = (os.path.dirname(folder), folder)
    return any(os.path.isdir(os.path.join(root, 'Lib', 'site-packages', 'pymysql')) for root in roots)


def parse_watch_log(text):
    """Rows (process_name, id_process, timestamp_log, type_log, message) of a watch log. A line that isn't an event
    (a raw line break inside a message) continues the previous message."""
    rows = []
    for line in text.splitlines():
        match = WATCH_LINE_RE.match(line)
        if match:
            group, run_id, stamp, level, message = match.groups()
            rows.append([group, int(run_id), stamp, level, message])
        elif rows and line.strip():
            rows[-1][4] += '\n' + line
    return [tuple(row) for row in rows]


def watch_logs(watch_path):
    """Log files under <watch>/<GROUP_LOG>/, including the ones an interrupted upload left claimed (.uploading)."""
    files = []
    try:
        groups = sorted(os.listdir(watch_path))
    except OSError:
        return files
    for group in groups:
        folder = os.path.join(watch_path, group)
        if os.path.isdir(folder):
            files += [os.path.join(folder, f) for f in sorted(os.listdir(folder)) if f.endswith(('.txt', '.txt' + UPLOAD_SUFFIX))]
    return files


def same_path(a, b):
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


class LogDatabase:
    """Uploads the watch logs to MySQL (LOG_DB) and queries them back. Runs inside `main.py --db`, under a Python with
    pymysql. The credentials are read from LOG_DB.ENV_FILE (variables named in ENV_KEYS); the app never stores them."""

    IDENT_RE = re.compile(r'^[A-Za-z0-9_$]+$')
    COLUMNS = ('process_name', 'id_process', 'timestamp_log', 'type_log', 'message', 'update_at')
    ROLES = ('host', 'port', 'user', 'password')

    def __init__(self, base_path, db):
        self.db = db
        self.env_path = os.path.abspath(os.path.join(base_path, db['ENV_FILE'])) if db.get('ENV_FILE') else ''

    @staticmethod
    def env_values(path, keys):
        """{role: value or None} of the .env variables the connection needs (roles: host, port, user, password)."""
        values = {}
        if path and os.path.isfile(path):
            with open(path, encoding='utf-8-sig', errors='replace') as f:
                values = {key: value for key, value, _ in ProjectConfig.parse_env(f.read())}
        return {role: values.get(keys[role]) or None for role in LogDatabase.ROLES}

    def credentials(self):
        if not os.path.isfile(self.env_path):
            raise LocalizedError('db.err_env_missing', path=self.env_path or '-')
        keys = self.db['ENV_KEYS']
        values = self.env_values(self.env_path, keys)
        missing = [keys[role] for role in self.ROLES if not values[role]]
        if missing:
            raise LocalizedError('db.err_env_keys', keys=', '.join(missing))
        if not values['port'].isdigit():
            raise LocalizedError('db.err_port', var=keys['port'])
        for name in (self.db.get('DATABASE') or '', self.db.get('TABLE') or ''):
            if not self.IDENT_RE.match(name):
                raise LocalizedError('db.err_name', name=name)
        return values

    @property
    def table(self):
        return f"`{self.db['DATABASE']}`.`{self.db['TABLE']}`"

    def connect(self):
        values = self.credentials()
        try:
            import pymysql
        except ImportError:
            raise LocalizedError('db.err_no_pymysql', python=sys.executable)
        return pymysql.connect(host=values['host'], port=int(values['port']), user=values['user'], password=values['password'],
                               database=self.db['DATABASE'], charset='utf8mb4', connect_timeout=10, autocommit=False)

    def test(self):
        conn = self.connect()
        try:
            with conn.cursor() as cur:
                cur.execute(f'SHOW COLUMNS FROM {self.table}')
                columns = {row[0] for row in cur.fetchall()}
                missing = [c for c in self.COLUMNS if c not in columns]
                if missing:
                    raise LocalizedError('db.err_columns', columns=', '.join(missing))
                cur.execute(f'SELECT COUNT(*) FROM {self.table}')
                return {'rows': cur.fetchone()[0]}
        finally:
            conn.close()

    def upload(self, watch_path, busy, emit=lambda **data: None):
        """Uploads every finished log and deletes it, one transaction per file. The transaction first deletes the rows
        of the same runs, so retrying a file (e.g. one that couldn't be deleted) doesn't duplicate them. Logs a bot is
        still writing are skipped: the ones in `busy` (running locks) and any file another process holds open (it
        can't be renamed). Group folders left empty are removed."""
        files = watch_logs(watch_path)
        result = {'files': 0, 'rows': 0, 'skipped': 0, 'failed': 0, 'error': ''}

        def fail(name, err):
            result['failed'] += 1
            result['error'] = result['error'] or f'{name}: {err}'

        conn = self.connect()
        try:
            for n, path in enumerate(files, 1):
                emit(progress=n, total=len(files))
                original = path[:-len(UPLOAD_SUFFIX)] if path.endswith(UPLOAD_SUFFIX) else path
                name = os.path.relpath(original, watch_path)
                if any(same_path(original, b) for b in busy if b):
                    result['skipped'] += 1
                    continue
                claimed = original + UPLOAD_SUFFIX
                try:
                    if path != claimed:
                        os.rename(path, claimed)
                except OSError:
                    result['skipped'] += 1
                    continue
                try:
                    with open(claimed, encoding='utf-8', errors='replace') as f:
                        rows = parse_watch_log(f.read())
                    self._insert(conn, rows)
                except Exception as err:
                    with contextlib.suppress(Exception):
                        conn.rollback()
                    with contextlib.suppress(OSError):
                        os.rename(claimed, original)
                    fail(name, err)
                    continue
                result['rows'] += len(rows)
                try:
                    os.remove(claimed)
                except OSError as err:
                    fail(name, err)
                    continue
                result['files'] += 1
        finally:
            conn.close()
        for group in os.listdir(watch_path) if os.path.isdir(watch_path) else []:
            with contextlib.suppress(OSError):
                os.rmdir(os.path.join(watch_path, group))
        return result

    def _insert(self, conn, rows):
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with conn.cursor() as cur:
            for process, run_id in dict.fromkeys((row[0][:64], row[1]) for row in rows):
                cur.execute(f'DELETE FROM {self.table} WHERE process_name = %s AND id_process = %s', (process, run_id))
            if rows:
                cur.executemany(f"INSERT INTO {self.table} ({', '.join(self.COLUMNS)}) VALUES (%s, %s, %s, %s, %s, %s)",
                                [(group[:64], run_id, stamp, level[:16], message, now)
                                 for group, run_id, stamp, level, message in rows])
        conn.commit()

    def query(self, filters):
        """Newest events first, at most QUERY_LIMIT; filters: process, level, text, date_from, date_to (YYYY-MM-DD)."""
        where, params = [], []
        for key, sql, value in (('process', 'process_name = %s', None), ('level', 'type_log = %s', None),
                                ('text', 'message LIKE %s', lambda v: f'%{v}%'),
                                ('date_from', 'timestamp_log >= %s', lambda v: f'{v} 00:00:00'),
                                ('date_to', 'timestamp_log <= %s', lambda v: f'{v} 23:59:59')):
            if filters.get(key):
                where.append(sql)
                params.append(value(filters[key]) if value else filters[key])
        limit = int(self.db.get('QUERY_LIMIT', 1000))
        sql = f'SELECT timestamp_log, process_name, id_process, type_log, message FROM {self.table}'
        if where:
            sql += ' WHERE ' + ' AND '.join(where)
        sql += f' ORDER BY timestamp_log DESC, id DESC LIMIT {limit + 1}'
        conn = self.connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
                cur.execute(f'SELECT DISTINCT process_name FROM {self.table} ORDER BY process_name')
                processes = [row[0] for row in cur.fetchall()]
        finally:
            conn.close()
        return {'rows': [['' if v is None else str(v) for v in row] for row in rows[:limit]],
                'more': len(rows) > limit, 'processes': processes}


def run_db_command(base_path, config, action, payload):
    """`main.py --db test|upload|query`: prints JSON lines (progress, then a result or an error) for the app."""
    def emit(**data):
        print(json.dumps(data, ensure_ascii=False, default=str), flush=True)

    overrides = {k: v for k, v in (payload.get('db') or {}).items() if k in LOG_DB_EDITABLE}
    database = LogDatabase(base_path, {**config['LOG_DB'], **overrides})
    try:
        if action == 'test':
            result = database.test()
        elif action == 'upload':
            busy = [lock.get('log') for lock in Scheduler(base_path, config).running().values()]
            result = database.upload(os.path.abspath(os.path.join(base_path, config['WATCH_PATH'])), busy, emit)
        else:
            result = database.query(payload.get('filters') or {})
    except LocalizedError as err:
        emit(error=err.key, params=err.params)
        return 1
    except Exception as err:
        emit(error='db.err_generic', params={'error': f'{type(err).__name__}: {err}'})
        return 1
    emit(result=result)
    return 0


class App:
    """Main window: tabs Processes (the bots), Activities (running / queued), Scheduled (CRON_DRIVER) and History."""

    def __init__(self, base_path, config):
        self.base_config = config
        config = self.config = apply_settings(config, read_settings(config))
        self.projects_path = os.path.abspath(os.path.join(base_path, config['PROJECTS_PATH']))
        self.watch_path = os.path.abspath(os.path.join(base_path, config['WATCH_PATH']))
        self.assets_path = os.path.abspath(os.path.join(base_path, config['ASSETS_PATH']))
        self.icon_path = os.path.join(self.assets_path, config['ICON_FILE'])
        self.theme_name = config['THEME_DEFAULT']
        with open(os.path.join(base_path, config['I18N_FILE']), encoding='utf-8') as f:
            self.i18n = json.load(f)
        # per-user choice (not in the repo): %LOCALAPPDATA%\<APP_NAME>\settings.json
        self.settings_path = settings_file(config)
        language = self._read_settings().get('LANGUAGE')
        self.lang = language if language in self.i18n else config['LANGUAGE_DEFAULT']
        self.base_path = base_path
        self.projects = {}
        self.rows = {}
        self.row_modes = {}
        self.active_count = 0
        self.current_tab = None
        self.themed = []
        self.images = {}
        self.hicons = {}
        self.scheduler = Scheduler(base_path, config)

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
            # own taskbar identity, so Windows shows the app icon instead of python's
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(config['APP_ID'])
        except (AttributeError, OSError):
            pass

        self.root = tk.Tk()
        self.root.withdraw()
        self.scale = self.root.winfo_fpixels('1i') / 96
        self.root.title(config['APP_NAME'])
        self.root.iconbitmap(default=self.icon_path)
        self.root.geometry(f'{int(1100 * self.scale)}x{int(720 * self.scale)}')
        self.root.minsize(int(860 * self.scale), int(560 * self.scale))
        self.root.protocol('WM_DELETE_WINDOW', self.close)

        families = set(self.root.tk.call('font', 'families'))
        self.font_mono = ('Cascadia Mono', 9) if 'Cascadia Mono' in families else ('Consolas', 9)
        self.roles = {
            'title': (('Segoe UI Semibold', 17), 'text'),
            'h1': (('Segoe UI Semibold', 13), 'text'),
            'h2': (('Segoe UI Semibold', 11), 'text'),
            'body': (('Segoe UI', 10), 'text'),
            'muted': (('Segoe UI', 9), 'muted'),
            'caption': (('Segoe UI Semibold', 8), 'muted'),
            'clock': (('Segoe UI Semibold', 22), 'accent'),
            'value': (('Segoe UI Semibold', 13), 'text'),
            'pct': (('Segoe UI Semibold', 13), 'accent'),
            'mono': (self.font_mono, 'text'),
        }
        self.style = ttk.Style(self.root)
        self.style.theme_use('clam')

        self._build()
        self.apply_theme()
        self.load_projects()
        self.show_tab('processes')
        self.root.deiconify()
        self.style_window(self.root)
        self.root.after(1000, self._ui_loop)

    @property
    def colors(self):
        return self.config['THEMES'][self.theme_name]

    # ---------- language ----------

    def t(self, key, **params):
        # a key missing in the selected language falls back to English
        text = self.i18n[self.lang].get(key) or self.i18n['en'][key]
        return text.format(**params)

    def error_text(self, err):
        return self.t(err.key, **err.params) if isinstance(err, LocalizedError) else str(err)

    def _read_settings(self):
        return read_settings(self.config)

    def _save_settings(self, **values):
        try:
            os.makedirs(os.path.dirname(self.settings_path), exist_ok=True)
            with open(self.settings_path, 'w', encoding='utf-8') as f:
                json.dump({**self._read_settings(), **values}, f, indent=4)
        except OSError:
            pass

    def toggle_language(self):
        languages = list(self.i18n)
        self.lang = languages[(languages.index(self.lang) + 1) % len(languages)]
        self._save_settings(LANGUAGE=self.lang)
        # the project list (and its diagnostics) is rebuilt in the new language; open run windows follow via apply_theme
        self.load_projects()
        self.apply_theme()
        self.refresh_ui(full=True)

    # ---------- settings and log database ----------

    @property
    def watch_name(self):
        return os.path.basename(self.watch_path.rstrip('\\/')) or self.watch_path

    def save_user_settings(self, watch_path, log_db):
        """Saves the Settings window values for this PC and applies them (the tick and the runners read them too)."""
        self._save_settings(WATCH_PATH=watch_path, LOG_DB=log_db)
        self.config = apply_settings(self.base_config, self._read_settings())
        self.watch_path = self.scheduler.watch_path = os.path.abspath(os.path.join(self.base_path, self.config['WATCH_PATH']))
        self.scheduler.config = self.config
        self.load_projects()
        self.apply_theme()
        self.refresh_ui(full=True)

    def run_db(self, action, on_done, payload=None, on_progress=None, db=None):
        """Runs `main.py --db <action>` with the log database's Python in a thread. on_progress(n, total) and
        on_done(result, error) are called on the Tk thread."""
        db = {**self.config['LOG_DB'], **(db or {})}
        python = db.get('PYTHON') or find_db_python(self.projects_path)
        if not python or not os.path.isfile(python):
            on_done(None, LocalizedError('db.err_no_python'))
            return
        args = [python, self.scheduler.app_main, '--db', action, '--db-args', json.dumps({**(payload or {}), 'db': db})]
        events = queue.Queue()

        def work():
            output = []
            try:
                proc = subprocess.Popen(args, cwd=self.base_path, env={**os.environ, 'PYTHONIOENCODING': 'utf-8'},
                                        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        creationflags=subprocess.CREATE_NO_WINDOW)
                for raw in proc.stdout:
                    line = raw.decode('utf-8', errors='replace').strip()
                    try:
                        events.put(json.loads(line))
                    except ValueError:
                        # not a JSON line: a traceback (e.g. that Python can't import the app), shown if there's no result
                        output.append(line)
                proc.wait()
            except OSError as err:
                output.append(str(err))
            events.put({'done': output})

        final = {}

        def poll():
            while True:
                try:
                    data = events.get_nowait()
                except queue.Empty:
                    break
                if 'progress' in data:
                    on_progress and on_progress(data['progress'], data['total'])
                elif 'done' in data:
                    if 'result' in final:
                        on_done(final['result'], None)
                    elif 'error' in final:
                        on_done(None, LocalizedError(final['error'], **final.get('params', {})))
                    else:
                        on_done(None, LocalizedError('db.err_generic', error='\n'.join(data['done'][-8:]) or '?'))
                    return
                else:
                    final.update(data)
            self.root.after(100, poll)

        threading.Thread(target=work, daemon=True).start()
        self.root.after(100, poll)

    # ---------- themed widget helpers ----------

    def register(self, widget, apply):
        widget.theme_apply = apply
        self.themed.append(widget)
        apply()

    def apply_widget(self, widget):
        widget.theme_apply()

    def _image(self, size):
        if size not in self.images:
            self.images[size] = tk.PhotoImage(file=os.path.join(self.assets_path, f'logo-{size}.png'))
        return self.images[size]

    def image_label(self, master, size, bg_key):
        available = (20, 24, 28, 32, 36, 40, 48, 56, 64, 72)
        target = size * self.scale
        lbl = tk.Label(master, image=self._image(min(available, key=lambda n: abs(n - target))), bd=0)
        lbl.bg_key = bg_key
        self.register(lbl, lambda: lbl.configure(bg=self.colors[lbl.bg_key]))
        return lbl

    def label(self, master, text='', role='body', bg_key='bg'):
        font, fg_key = self.roles[role]
        lbl = tk.Label(master, text=resolve(text), font=font, anchor='w', justify='left', bd=0)
        lbl.bg_key, lbl.fg_key, lbl.text_src = bg_key, fg_key, text
        self.register(lbl, lambda: self._apply_label(lbl))
        return lbl

    def _apply_label(self, lbl):
        lbl.configure(bg=self.colors[lbl.bg_key], fg=self.colors[lbl.fg_key])
        # only translatable texts are refreshed; plain ones (clock, file name...) keep what the code last set
        if callable(lbl.text_src):
            lbl.configure(text=lbl.text_src())

    def set_text(self, lbl, text):
        lbl.text_src = text
        lbl.configure(text=resolve(text))

    def frame(self, master, bg_key='bg', **kwargs):
        frm = tk.Frame(master, bd=0, **kwargs)
        frm.bg_key = bg_key
        self.register(frm, lambda: frm.configure(bg=self.colors[frm.bg_key]))
        return frm

    def card(self, master, **kwargs):
        options = {'padx': 18, 'pady': 14, **kwargs}
        frm = tk.Frame(master, bd=0, highlightthickness=1, **options)
        frm.bg_key = 'surface'
        self.register(frm, lambda: frm.configure(bg=self.colors['surface'], highlightbackground=self.colors['border'],
                                                 highlightcolor=self.colors['border']))
        RoundCorners(self, frm, 12)
        return frm

    def soft_box(self, master, bg_key='track', **kwargs):
        """Rounded tinted box without border (a command to copy, the .env help)."""
        frm = self.frame(master, bg_key, **kwargs)
        RoundCorners(self, frm, 8, border=False)
        return frm

    # ---------- projects ----------

    def _diagnose(self, name, path):
        src = os.path.join(path, 'src')
        main = os.path.join(src, 'main.py')
        venv = find_venv(path, name)
        python = os.path.join(venv, 'Scripts', 'python.exe')
        project ={'name': name, 'path': path, 'main': main, 'python': python, 'group': name,
                   'no_progress': False, 'issues': []}
        issues = project['issues']

        t = self.t

        def add(level, title, detail, command=None):
            issues.append({'level': level, 'title': title, 'detail': detail, 'command': command})

        if not os.path.isdir(src):
            add('error', t('issue.no_src.title'), t('issue.no_src.detail'))
        else:
            scripts = sorted(f for f in os.listdir(src) if f.endswith('.py'))
            if not scripts:
                add('error', t('issue.src_empty.title'), t('issue.src_empty.detail'))
            elif 'main.py' not in scripts:
                bats = [os.path.basename(b) for b in glob.glob(os.path.join(path, 'run-*.bat'))]
                launcher = t('issue.no_main.launcher', bat=bats[0]) if bats else ''
                add('error', t('issue.no_main.title'), t('issue.no_main.detail', scripts=', '.join(scripts), launcher=launcher))

        if os.path.isfile(main):
            with open(main, encoding='utf-8', errors='replace') as f:
                source = f.read()
            group = find_group_log(source)
            if group:
                project['group'] = group
            else:
                add('warning', t('issue.no_group_log.title'), t('issue.no_group_log.detail', name=name, watch=self.watch_name))
            if re.search(r'stream_output\s*=\s*False', source):
                project['no_progress'] = True
                add('warning', t('issue.no_progress.title'), t('issue.no_progress.detail'))

            cd = f'cd "{path}"'
            install = ([f'.\\{os.path.basename(venv)}\\Scripts\\pip install -r requirements.txt']
                       if os.path.isfile(os.path.join(path, 'requirements.txt')) else [])
            if not os.path.isfile(python):
                add('error', t('issue.no_venv.title'), t('issue.no_venv.detail', name=name),
                    [cd, f'py -3.13 -m venv venv-{name}', *install])
            elif 'pi_kreton_rpa' in source and not os.path.isdir(os.path.join(venv, 'Lib', 'site-packages', 'pi_kreton_rpa')):
                add('error', t('issue.no_lib.title'),
                    t('issue.no_lib.detail') + t('issue.no_lib.install_cmd' if install else 'issue.no_lib.install_whl'),
                    [cd, *install] if install else None)

        issues.sort(key=lambda i: i['level'] != 'error')
        project['runnable'] = not any(i['level'] == 'error' for i in issues)
        return project

    def _discover_projects(self):
        projects = {}
        for name in sorted(os.listdir(self.projects_path), key=str.lower):
            path = os.path.join(self.projects_path, name)
            if name in self.config['EXCLUDED_PROJECTS'] or name.startswith(('.', '_')) or not os.path.isdir(path):
                continue
            projects[name] = self._diagnose(name, path)
        return projects

    # ---------- main window ----------

    def _build(self):
        self.register(self.root, lambda: self.root.configure(bg=self.colors['bg']))
        root = self.frame(self.root, 'bg', padx=24, pady=20)
        root.pack(fill='both', expand=True)

        header = self.frame(root, 'bg')
        header.pack(fill='x')
        self.btn_theme = RoundButton(header, self, '', self.toggle_theme, icon='moon')
        self.btn_theme.pack(side='right', anchor='n')
        RoundButton(header, self, lambda: self.t('lang.button'), self.toggle_language).pack(side='right', anchor='n', padx=(0, 4))
        RoundButton(header, self, lambda: self.t('settings.button'), lambda: SettingsDialog(self)).pack(side='right', anchor='n', padx=(0, 4))
        RoundButton(header, self, '', self.load_projects, icon='refresh').pack(side='right', anchor='n', padx=(0, 4))
        self.image_label(header, 40, 'bg').pack(side='left', padx=(0, 12))
        titles = self.frame(header, 'bg')
        titles.pack(side='left', fill='x', expand=True)
        self.label(titles, self.config['APP_NAME'], 'title', 'bg').pack(anchor='w')
        self.lbl_count = self.label(titles, '', 'muted', 'bg')
        self.lbl_count.pack(anchor='w')

        # tabs: Processes | Activities (n) | Scheduled | History
        tabbar = self.frame(root, 'bg')
        tabbar.pack(fill='x', pady=(16, 12))
        self.tabs = {}
        for key, text in (('processes', lambda: self.t('tab.processes')),
                          ('activities', lambda: self.t('tab.activities_n', n=self.active_count) if self.active_count else self.t('tab.activities')),
                          ('scheduled', lambda: self.t('tab.scheduled')),
                          ('history', lambda: self.t('tab.history'))):
            self.tabs[key] = RoundButton(tabbar, self, text, lambda k=key: self.show_tab(k))
            self.tabs[key].pack(side='left', padx=(0, 4))
        pages = self.frame(root, 'bg')
        pages.pack(fill='both', expand=True)

        processes = self.frame(pages, 'bg')
        section = self.frame(processes, 'bg')
        section.pack(fill='x', pady=(0, 8))
        self.label(section, lambda: self.t('main.section'), 'caption', 'bg').pack(side='left')
        self.label(section, lambda: self.t('main.hint'), 'muted', 'bg').pack(side='right')

        footer = self.frame(processes, 'bg')
        footer.pack(side='bottom', fill='x', pady=(12, 0))
        self.label(footer, lambda: self.t('main.footer', watch=self.watch_name), 'muted', 'bg').pack(side='left')

        card = self.card(processes, padx=6, pady=6)
        card.pack(fill='both', expand=True)
        self.list_canvas = tk.Canvas(card, highlightthickness=0, bd=0)
        self.register(self.list_canvas, lambda: self.list_canvas.configure(bg=self.colors['surface']))
        scroll = ttk.Scrollbar(card, orient='vertical', command=self.list_canvas.yview)
        self.list_canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.list_canvas.pack(side='left', fill='both', expand=True)
        self.list_inner = self.frame(self.list_canvas, 'surface')
        window = self.list_canvas.create_window(0, 0, window=self.list_inner, anchor='nw')
        self.list_inner.bind('<Configure>', lambda e: self.list_canvas.configure(scrollregion=self.list_canvas.bbox('all')))
        self.list_canvas.bind('<Configure>', lambda e: self.list_canvas.itemconfigure(window, width=e.width))
        self.root.bind_all('<MouseWheel>', self._on_wheel, add='+')

        self.activities = ActivitiesPage(self, pages)
        self.scheduled = ScheduledPage(self, pages)
        self.history = HistoryPage(self, pages)
        self.pages = {'processes': processes, 'activities': self.activities.frame,
                      'scheduled': self.scheduled.frame, 'history': self.history.frame}

    def show_tab(self, key):
        for name, page in self.pages.items():
            if name != key:
                page.pack_forget()
        self.pages[key].pack(fill='both', expand=True)
        for name, button in self.tabs.items():
            button.variant = 'accent' if name == key else 'ghost'
            button.redraw()
        self.current_tab = key
        self.refresh_ui(full=True)

    def refresh_ui(self, full=False):
        """Running / queued state from the scheduler files (the driver and the runners change it from other processes):
        Activities count, project rows and the visible page."""
        running = self.scheduler.running()
        queue = self.scheduler.read_state().get('queue', {})
        count = len(running) + len(queue)
        if count != self.active_count:
            self.active_count = count
            self.tabs['activities'].redraw()
        history = None
        for name in self.rows:
            mode = 'running' if name in running else 'queued' if name in queue else None
            if mode == self.row_modes.get(name):
                continue
            self.row_modes[name] = mode
            if mode == 'running':
                self.set_project_status(name, lambda: self.t('status.running'), 'accent')
            elif mode == 'queued':
                self.set_project_status(name, lambda: self.t('status.queued'), 'muted')
            else:
                # back to idle: show how its last execution ended (or Ready)
                history = history if history is not None else self.scheduler.history()
                last = next((h for h in history if h.get('bot') == name and 'status' in h), None)
                if last and last.get('end'):
                    self.set_project_status(name, lambda item=last: item_status(self, item)[0], item_status(self, last)[1])
                else:
                    self.set_project_status(name, *self._default_status(self.projects[name]))
        if self.current_tab == 'activities':
            self.activities.refresh(running, queue)
        elif self.current_tab == 'history':
            self.history.refresh(full)
        elif self.current_tab == 'scheduled':
            self.scheduled.refresh(full)

    def _ui_loop(self):
        try:
            self.refresh_ui()
        finally:
            self.root.after(1000, self._ui_loop)

    def _on_wheel(self, event):
        if str(event.widget).startswith(str(self.list_canvas)):
            self.list_canvas.yview_scroll(int(-event.delta / 120), 'units')

    def load_projects(self):
        self.projects = self._discover_projects()
        for child in self.list_inner.winfo_children():
            child.destroy()
        self.rows = {}
        # runnable projects first; the sort is stable, so each group keeps its alphabetical order
        ordered = sorted(self.projects.items(), key=lambda item: not item[1]['runnable'])
        for i, (name, project) in enumerate(ordered):
            if i:
                self.frame(self.list_inner, 'border', height=1).pack(fill='x')
            row = ProjectRow(self, self.list_inner, project, self._default_status(project))
            self.rows[name] = row
        # the rows are new: refresh_ui sets running / queued / last result again
        self.row_modes = {name: 'stale' for name in self.rows}
        self.refresh_ui()
        self.themed = [w for w in self.themed if w.winfo_exists()]
        self.list_canvas.yview_moveto(0)
        runnable = sum(p['runnable'] for p in self.projects.values())
        self.lbl_count.configure(text=self.t('main.count', runnable=runnable, total=len(self.projects)))

    def _default_status(self, project):
        key = 'status.ready' if project['runnable'] else 'status.unavailable'
        return (lambda: self.t(key), 'muted')

    def set_project_status(self, name, text, kind):
        row = self.rows.get(name)
        if row is not None:
            row.set_status(text, kind, kind == 'accent')

    def run_project(self, name):
        project = self.projects[name]
        if not project['runnable']:
            IssuesDialog(self, project)
            return
        if name in self.scheduler.running():
            self._open_view(name)
            return
        ConfigDialog(self, project, lambda: self._launch(name))

    def _launch(self, name):
        # manual runs go through the same detached runner as the scheduled ones (queued if the bot or MAX_PARALLEL is busy)
        result = self.scheduler.request_run(name, 'manual')
        if result != 'started':
            messagebox.showinfo(self.t('run.queued_title'), self.t('run.queued_message', name=name), parent=self.root)
        self._open_view(name)

    def _open_view(self, name):
        """Activities tab with the bot's execution (or its queued entry) selected."""
        self.show_tab('activities')
        lock = self.scheduler.read_lock(name)
        key = lock['run_id'] if lock else f'queued-{name}'
        if key in self.activities.items:
            self.activities.select(key)

    def toggle_theme(self):
        self.theme_name = 'dark' if self.theme_name == 'light' else 'light'
        self.apply_theme()

    # ---------- windows ----------

    def _hicon(self, size):
        # icons are loaded at the exact pixel size the shell draws them, so Windows doesn't rescale (blur) them
        if size not in self.hicons:
            user32 = ctypes.windll.user32
            user32.LoadImageW.restype = ctypes.c_void_p
            user32.LoadImageW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
            self.hicons[size] = user32.LoadImageW(None, self.icon_path, 1, size, size, 0x10)
        return self.hicons[size]

    def style_window(self, window):
        try:
            window.update_idletasks()
            user32 = ctypes.windll.user32
            hwnd = user32.GetParent(window.winfo_id())
            # Windows 10/11: DWMWA_USE_IMMERSIVE_DARK_MODE = 20
            value = ctypes.c_int(1 if self.theme_name == 'dark' else 0)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(value), ctypes.sizeof(value))
            # WM_SETICON: ICON_BIG (taskbar, 24 px logical) and ICON_SMALL (title bar, 16 px logical)
            user32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_void_p]
            user32.SendMessageW(hwnd, 0x0080, 1, self._hicon(round(24 * self.scale)))
            user32.SendMessageW(hwnd, 0x0080, 0, self._hicon(round(16 * self.scale)))
        except (AttributeError, OSError):
            pass

    def apply_theme(self):
        c = self.colors
        self.style.configure('Vertical.TScrollbar', background=c['border'], troughcolor=c['surface'],
                             bordercolor=c['surface'], arrowcolor=c['muted'], lightcolor=c['border'],
                             darkcolor=c['border'], gripcount=0, arrowsize=int(12 * self.scale))
        self.style.map('Vertical.TScrollbar', background=[('active', c['muted'])])
        self.style.configure('Horizontal.TScrollbar', background=c['border'], troughcolor=c['surface'],
                             bordercolor=c['surface'], arrowcolor=c['muted'], lightcolor=c['border'],
                             darkcolor=c['border'], gripcount=0, arrowsize=int(12 * self.scale))
        self.style.map('Horizontal.TScrollbar', background=[('active', c['muted'])])
        self.style.layout('Log.Treeview', [('Treeview.treearea', {'sticky': 'nswe'})])
        self.style.configure('Log.Treeview', background=c['surface'], fieldbackground=c['surface'], foreground=c['text'],
                             bordercolor=c['surface'], lightcolor=c['surface'], darkcolor=c['surface'],
                             rowheight=tkfont.Font(font=self.font_mono).metrics('linespace') + int(8 * self.scale),
                             font=self.font_mono)
        self.style.map('Log.Treeview', background=[('selected', c['accent_soft'])], foreground=[('selected', c['text'])])
        self.style.configure('Log.Treeview.Heading', background=c['surface'], foreground=c['muted'], bordercolor=c['border'],
                             lightcolor=c['surface'], darkcolor=c['surface'], relief='flat',
                             font=('Segoe UI Semibold', 9), padding=(8, 6))
        self.style.map('Log.Treeview.Heading', background=[('active', c['hover'])])
        self.style.layout('Config.Treeview', [('Treeview.treearea', {'sticky': 'nswe'})])
        self.style.configure('Config.Treeview', background=c['surface'], fieldbackground=c['surface'], foreground=c['text'],
                             bordercolor=c['surface'], lightcolor=c['surface'], darkcolor=c['surface'],
                             rowheight=int(30 * self.scale), font=('Segoe UI', 10), indent=int(14 * self.scale))
        self.style.map('Config.Treeview', background=[('selected', c['accent_soft'])], foreground=[('selected', c['text'])])
        self.style.configure('Config.Treeview.Heading', background=c['surface'], foreground=c['muted'], bordercolor=c['border'],
                             lightcolor=c['surface'], darkcolor=c['surface'], relief='flat',
                             font=('Segoe UI Semibold', 9), padding=(8, 6))
        self.style.map('Config.Treeview.Heading', background=[('active', c['hover'])])
        self.themed = [w for w in self.themed if w.winfo_exists()]
        for widget in self.themed:
            widget.theme_apply()
        self.style.configure('TCombobox', fieldbackground=c['surface'], background=c['surface'], foreground=c['text'],
                             arrowcolor=c['muted'], bordercolor=c['border'], lightcolor=c['surface'], darkcolor=c['surface'],
                             selectbackground=c['surface'], selectforeground=c['text'], padding=int(4 * self.scale))
        self.style.map('TCombobox', fieldbackground=[('readonly', c['surface'])], foreground=[('readonly', c['text'])],
                       selectbackground=[('readonly', c['surface'])], selectforeground=[('readonly', c['text'])],
                       bordercolor=[('focus', c['accent'])])
        # the rounded drop-downs (themed_combobox): no border of their own, the RoundField around them draws it
        self.style.configure('Round.TCombobox', fieldbackground=c['surface'], background=c['surface'], foreground=c['text'],
                             arrowcolor=c['muted'], bordercolor=c['surface'], lightcolor=c['surface'], darkcolor=c['surface'],
                             selectbackground=c['surface'], selectforeground=c['text'], padding=int(3 * self.scale),
                             arrowsize=int(12 * self.scale))
        self.style.map('Round.TCombobox', fieldbackground=[('readonly', c['surface'])], foreground=[('readonly', c['text'])],
                       background=[('active', c['surface']), ('pressed', c['surface']), ('readonly', c['surface'])],
                       selectbackground=[('readonly', c['surface'])], selectforeground=[('readonly', c['text'])],
                       bordercolor=[('focus', c['surface'])], lightcolor=[('focus', c['surface'])],
                       darkcolor=[('focus', c['surface'])], arrowcolor=[('active', c['text'])])
        # the drop-down list of a Combobox is a plain Tk listbox (option database, applies to the next ones opened)
        for option, key in (('background', 'surface'), ('foreground', 'text'), ('selectBackground', 'accent_soft'),
                            ('selectForeground', 'text')):
            self.root.option_add(f'*TCombobox*Listbox.{option}', c[key])
        self.btn_theme.set('', 'sun' if self.theme_name == 'dark' else 'moon')
        self.style_window(self.root)

    def close(self):
        # runs are detached: they go on after the app closes and show up again when it reopens
        self.root.destroy()


def main():
    base_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    with open(os.path.join(base_path, 'config', 'config.json'), encoding='utf-8') as f:
        config = json.load(f)
    # every mode (UI, tick, runner, --db) uses this PC's logs folder and log database settings
    config = apply_settings(config, read_settings(config))

    parser = argparse.ArgumentParser(description='Desktop app to run the RPA bots; --tick and --run are the scheduler modes.')
    parser.add_argument('--tick', action='store_true', help='evaluate the CRON_DRIVER schedules once (the driver task runs it every minute)')
    parser.add_argument('--run', metavar='BOT', help='run one bot detached, recording its output and history')
    parser.add_argument('--run-id')
    parser.add_argument('--trigger', default='manual', choices=('manual', 'cron'))
    parser.add_argument('--scheduled-for')
    parser.add_argument('--db', choices=('test', 'upload', 'query'),
                        help='log database action; run it with a Python that has pymysql (prints JSON lines)')
    parser.add_argument('--db-args', default='{}', help='JSON: LOG_DB overrides ("db") and query filters ("filters")')
    args = parser.parse_args()

    if args.db:
        sys.exit(run_db_command(base_path, config, args.db, json.loads(args.db_args)))
    if not (args.tick or args.run):
        App(base_path, config).root.mainloop()
        return
    scheduler = Scheduler(base_path, config)
    try:
        if args.tick:
            scheduler.tick()
        else:
            scheduler.run(args.run, args.run_id or f'{datetime.now():%Y%m%d%H%M%S}-{args.run}', args.trigger, args.scheduled_for)
    except Exception:
        # pythonw has no console: errors of the background modes go to scheduler/driver.log
        with open(os.path.join(scheduler.state_dir, 'driver.log'), 'a', encoding='utf-8') as fh:
            fh.write(f'{datetime.now():%Y-%m-%d %H:%M:%S} {" ".join(sys.argv[1:])}\n{traceback.format_exc()}\n')
        sys.exit(1)


if __name__ == '__main__':
    main()
