import os
import re
import shutil
import sqlite3
import json
import datetime
import logging
import threading
import queue as _queue
import urllib.request
from io import BytesIO
from urllib.parse import urlparse
from pathlib import Path
from dataclasses import dataclass, field
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, colorchooser
import subprocess

import yt_dlp

                                                         
try:
    from PIL import Image, ImageTk, ImageOps, ImageFilter
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

                                                                
try:
    from tkinterdnd2 import TkinterDnD, DND_TEXT, DND_FILES
    DND_AVAILABLE = True
except ImportError:
    DND_AVAILABLE = False


                                                               
           
                                                               

APP_TITLE   = "YouTube Downloader"
APP_VERSION = "1.1"
DEFAULT_DIR = str(Path.home() / "Downloads")
BASE_DIR    = Path(__file__).resolve().parent
DB_PATH     = BASE_DIR / "history.db"

BACKGROUND_CANDIDATES = [
    "Void Horizon.png",
    "background.jpg",
    "background.jpeg",
    "wallpaper.png",
    "wallpaper.jpg",
]

COLORS = {
    "window":        "#11151D",
    "panel":         "#222832",
    "panel_alt":     "#272E39",
    "field":         "#252C38",
    "field_disabled":"#1C222C",
    "border":        "#424B59",
    "text":          "#F3F5F7",
    "muted":         "#AEB7C3",
    "accent":        "#E5A191",
    "accent_hover":  "#F0B0A0",
    "accent_soft":   "#3B2B2D",
    "danger":        "#D97E82",
    "success":       "#86C6A1",
    "black_overlay": "#0B0D12",
}

                                                                             
THEMES: dict[str, dict] = {
    "Void Horizon": {
        "accent":       "#E5A191",
        "accent_hover": "#F0B0A0",
        "accent_soft":  "#3B2B2D",
    },
    "Sakura": {
        "accent":       "#F4A7B9",
        "accent_hover": "#F8C0CC",
        "accent_soft":  "#3D2030",
    },
    "Midnight": {
        "accent":       "#7EB8F7",
        "accent_hover": "#A0CCFF",
        "accent_soft":  "#1C2B3D",
    },
    "Forest": {
        "accent":       "#86C6A1",
        "accent_hover": "#A0D9B8",
        "accent_soft":  "#1E3028",
    },
    "Amber": {
        "accent":       "#F5C842",
        "accent_hover": "#FFD966",
        "accent_soft":  "#352D10",
    },
}

                                         
PANEL_ALPHA              = 0.72
BACKGROUND_OVERLAY_ALPHA = 0.0

                                                                
SETTINGS_PATH = BASE_DIR / "settings.json"

DEFAULT_SETTINGS: dict = {
    "theme":              "Void Horizon",
    "panel_alpha":        0.72,
    "bg_overlay_alpha":   0.0,
    "default_mode":       "Video",
    "default_quality":    "1080p",
    "default_audio_q":   "320K",
    "auto_cleanup":       True,
    "notifications":      True,
    "output_dir":         str(Path.home() / "Downloads"),
}


def load_settings() -> dict:
    try:
        raw = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        merged = {**DEFAULT_SETTINGS, **raw}
        return merged
    except Exception:
        return dict(DEFAULT_SETTINGS)


def save_settings(s: dict):
    try:
        SETTINGS_PATH.write_text(json.dumps(s, indent=2, ensure_ascii=False),
                                 encoding="utf-8")
    except Exception as exc:
        logger.error("Failed to save settings: %s", exc)


                                                               
         
                                                               

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(BASE_DIR / "youtube_downloader.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)




                                                               
            
                                                               

class QueueStatus:
    WAITING     = "Waiting"
    DOWNLOADING = "Downloading"
    DONE        = "Done"
    ERROR       = "Error"
    CANCELLED   = "Cancelled"


@dataclass
class QueueItem:
    url:           str
    mode:          str
    quality:       str
    audio_quality: str
    output_dir:    str
    subtitle_lang: str          = "en"
    status:        str          = QueueStatus.WAITING
    title:         str          = ""
    error_msg:     str          = ""
    file_path:     str          = ""


                                                               
                            
                                                               

class DownloadHistory:
    """Persist download records in a local SQLite database."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS history (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    title     TEXT,
                    date      TEXT,
                    mode      TEXT,
                    file_path TEXT,
                    status    TEXT
                )
            """)
            conn.commit()

    def add_entry(self, title: str, mode: str, file_path: str, status: str):
        date = datetime.datetime.now().strftime("%d %b %Y  %H:%M")
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO history (title, date, mode, file_path, status) "
                "VALUES (?, ?, ?, ?, ?)",
                (title, date, mode, file_path, status),
            )
            conn.commit()

    def get_all(self):
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "SELECT id, title, date, mode, file_path, status "
                "FROM history ORDER BY id DESC"
            )
            return cur.fetchall()

    def clear(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM history")
            conn.commit()


                                                               
          
                                                               

class YouTubeDownloaderApp:

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("1120x840")
        self.root.minsize(960, 760)
        self.root.configure(bg=COLORS["window"])

                                 
        self.settings = load_settings()
        self._apply_theme(self.settings.get("theme", "Void Horizon"))

                                  
        self.events = _queue.Queue()

                        
        self.downloading      = False
        self._cancel_event    = threading.Event()

                        
        self.download_queue: list[QueueItem] = []
        self.queue_lock       = threading.Lock()
        self.queue_processing = False

                 
        self.history = DownloadHistory(DB_PATH)

                                
        self.bg_photo             = None
        self.bg_source_image      = None
        self.bg_last_size         = None
        self.resize_job           = None
        self._bg_rendering        = False
        self.thumbnail_photo      = None
        self.current_thumbnail_url   = None
        self.current_thumbnail_bytes = None

                           
        self._last_clipboard  = ""
        self._clipboard_after = None

                                                       
        self.url_var           = tk.StringVar()
        self.mode_var          = tk.StringVar(value=self.settings.get("default_mode", "Video"))
        self.quality_var       = tk.StringVar(value=self.settings.get("default_quality", "1080p"))
        self.audio_quality_var = tk.StringVar(value=self.settings.get("default_audio_q", "320K"))
        self.subtitle_lang_var = tk.StringVar(value="en")
        self.output_dir_var    = tk.StringVar(value=self.settings.get("output_dir", DEFAULT_DIR))

        self.status_var   = tk.StringVar(value="Ready • paste a YouTube link")
        self.progress_var = tk.DoubleVar(value=0)
        self.speed_var    = tk.StringVar(value="0 KB/s")
        self.eta_var      = tk.StringVar(value="ETA: -")
        self.title_var    = tk.StringVar(value="No video selected")
        self.detail_var   = tk.StringVar(value="-")

        self.build_styles()
        self.build_ui()

                                                     
        self._setup_drag_drop()

        self.root.after(100, self.process_events)
        self.root.after(1500, self._poll_clipboard)                                

    @staticmethod
    def _apply_theme(theme_name: str):
        """Apply accent colours from a theme preset to the global COLORS dict."""
        theme = THEMES.get(theme_name)
        if theme:
            COLORS.update(theme)


                                                                
            
                                                                

    def build_styles(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(
            "Moody.TCombobox",
            fieldbackground=COLORS["field"],
            background=COLORS["field"],
            foreground=COLORS["text"],
            arrowcolor=COLORS["muted"],
            bordercolor=COLORS["border"],
            lightcolor=COLORS["border"],
            darkcolor=COLORS["border"],
            padding=7,
        )
        style.map(
            "Moody.TCombobox",
            fieldbackground=[
                ("disabled", COLORS["field_disabled"]),
                ("readonly", COLORS["field"]),
            ],
            foreground=[
                ("disabled", COLORS["muted"]),
                ("readonly", COLORS["text"]),
            ],
        )
        style.configure(
            "Moody.Horizontal.TProgressbar",
            troughcolor="#303743",
            background=COLORS["accent"],
            bordercolor="#303743",
            lightcolor=COLORS["accent"],
            darkcolor=COLORS["accent"],
            thickness=10,
        )
                          
        style.configure(
            "History.Treeview",
            background=COLORS["panel_alt"],
            foreground=COLORS["text"],
            fieldbackground=COLORS["panel_alt"],
            rowheight=26,
            font=("Segoe UI", 9),
        )
        style.configure(
            "History.Treeview.Heading",
            background=COLORS["field"],
            foreground=COLORS["muted"],
            font=("Segoe UI", 9, "bold"),
        )
        style.map(
            "History.Treeview",
            background=[("selected", COLORS["accent_soft"])],
            foreground=[("selected", COLORS["accent"])],
        )

                                                                
              
                                                                

    def build_ui(self):
        self.canvas = tk.Canvas(
            self.root, bg=COLORS["window"],
            highlightthickness=0, borderwidth=0,
        )
        self.canvas.pack(fill="both", expand=True)
        self.root.bind("<Configure>", self.on_resize)
        self.draw_background()

        self.panel_window = tk.Toplevel(self.root)
        self.panel_window.overrideredirect(True)
        self.panel_window.configure(bg=COLORS["panel"])
        self.panel_window.transient(self.root)
        self.panel_window.attributes("-alpha", PANEL_ALPHA)
        self.panel_window.bind("<Map>", lambda _e: self.panel_window.lift())
        self.root.bind("<FocusIn>", lambda _e: self.panel_window.lift())

        self.panel = tk.Frame(
            self.panel_window,
            bg=COLORS["panel"],
            highlightbackground="#68717E",
            highlightthickness=1,
            bd=0,
        )
        self.panel.pack(fill="both", expand=True)

        self.build_header()
        self.build_url_section()
        self.build_settings()
        self.build_current_item()
        self.build_progress()
        self.build_queue_panel()
        self.build_actions()
        self.build_footer()

        self.on_mode_change()
        self.root.update_idletasks()
        self.on_resize()
        self.panel_window.lift()

                                                               

    def build_header(self):
        header = tk.Frame(self.panel, bg=COLORS["panel"])
        header.pack(fill="x", padx=34, pady=(20, 8))

        tk.Label(
            header,
            text="YouTube Downloader",
            font=("Segoe UI", 25, "bold"),
            fg=COLORS["text"],
            bg=COLORS["panel"],
        ).pack()

        tk.Label(
            header,
            text="Download what you likes  •  MP4 = H.264 + AAC",
            font=("Segoe UI", 10),
            fg=COLORS["muted"],
            bg=COLORS["panel"],
        ).pack(pady=(3, 0))

                                                               

    def build_url_section(self):
        self.section_label("🔗  YouTube URL", "Paste or drop the link you want to download")

        row = tk.Frame(self.panel, bg=COLORS["panel"])
        row.pack(fill="x", padx=34, pady=(3, 12))

        self.url_entry = tk.Entry(
            row,
            textvariable=self.url_var,
            font=("Segoe UI", 10),
            fg=COLORS["text"],
            bg=COLORS["field"],
            relief="flat",
            bd=0,
            insertbackground=COLORS["accent"],
            highlightthickness=1,
            highlightbackground=COLORS["border"],
            highlightcolor=COLORS["accent"],
        )
        self.url_entry.pack(side="left", fill="x", expand=True, ipady=10, padx=(0, 8))
        self.url_entry.focus()

        self.add_queue_btn = self.make_button(
            row, "➕  Queue", self.add_to_queue, primary=False,
        )
        self.add_queue_btn.pack(side="right", ipady=6, padx=(0, 6))

        self.preview_button = self.make_button(
            row, "▶  Preview", self.preview_video, primary=False,
        )
        self.preview_button.pack(side="right", ipady=6, padx=(0, 6))

        self.paste_button = self.make_button(
            row, "📋  Paste", self.paste_url, primary=False,
        )
        self.paste_button.pack(side="right", ipady=6)

                                                                

    def build_settings(self):
        grid = tk.Frame(self.panel, bg=COLORS["panel"])
        grid.pack(fill="x", padx=34)
        for col in range(3):
            grid.columnconfigure(col, weight=1)

              
        self.field_label(grid, 0, "👤  Mode")
        self.mode_combo = ttk.Combobox(
            grid,
            textvariable=self.mode_var,
            values=["Video", "MP3", "Thumbnail", "Subtitle"],
            state="readonly",
            style="Moody.TCombobox",
            font=("Segoe UI", 10),
        )
        self.mode_combo.grid(row=1, column=0, sticky="ew", padx=(0, 7), pady=(4, 13), ipady=2)
        self.mode_combo.bind("<<ComboboxSelected>>", self.on_mode_change)

                       
        self.field_label(grid, 1, "⚙  Video Quality")
        self.quality_combo = ttk.Combobox(
            grid,
            textvariable=self.quality_var,
            values=["Best", "2160p (4K)", "1440p", "1080p", "720p", "480p", "360p"],
            state="readonly",
            style="Moody.TCombobox",
            font=("Segoe UI", 10),
        )
        self.quality_combo.grid(row=1, column=1, sticky="ew", padx=7, pady=(4, 13), ipady=2)

                                                                         
        self.third_col_label = tk.Label(
            grid,
            text="♫  Audio Quality (MP3)",
            font=("Segoe UI", 10, "bold"),
            fg=COLORS["text"],
            bg=COLORS["panel"],
            anchor="w",
        )
        self.third_col_label.grid(row=0, column=2, sticky="ew", padx=(7, 0))

        self.audio_combo = ttk.Combobox(
            grid,
            textvariable=self.audio_quality_var,
            values=["320K", "256K", "192K", "128K"],
            state="disabled",
            style="Moody.TCombobox",
            font=("Segoe UI", 10),
        )
        self.audio_combo.grid(row=1, column=2, sticky="ew", padx=(7, 0), pady=(4, 13), ipady=2)

        self.subtitle_lang_combo = ttk.Combobox(
            grid,
            textvariable=self.subtitle_lang_var,
            values=["en", "id", "ja", "ko", "zh-Hans", "zh-Hant",
                    "es", "fr", "de", "pt", "ar", "ru", "hi", "th"],
            state="readonly",
            style="Moody.TCombobox",
            font=("Segoe UI", 10),
        )
                                                             
        self.subtitle_lang_combo.grid(row=1, column=2, sticky="ew", padx=(7, 0), pady=(4, 13), ipady=2)
        self.subtitle_lang_combo.grid_remove()

                       
        self.field_label(grid, 0, "📁  Output Folder", row=2, columnspan=3)
        folder = tk.Frame(grid, bg=COLORS["panel"])
        folder.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(4, 12))
        folder.columnconfigure(0, weight=1)

        self.folder_entry = tk.Entry(
            folder,
            textvariable=self.output_dir_var,
            font=("Segoe UI", 10),
            fg=COLORS["text"],
            bg=COLORS["field"],
            relief="flat",
            bd=0,
            insertbackground=COLORS["accent"],
            highlightthickness=1,
            highlightbackground=COLORS["border"],
            highlightcolor=COLORS["accent"],
        )
        self.folder_entry.grid(row=0, column=0, sticky="ew", ipady=9, padx=(0, 8))

        self.browse_button = self.make_button(
            folder, "📁  Browse", self.choose_folder, primary=False,
        )
        self.browse_button.grid(row=0, column=1, ipady=5)

                                                               

    def build_current_item(self):
        self.info_box = tk.Frame(
            self.panel,
            bg=COLORS["panel_alt"],
            highlightbackground=COLORS["border"],
            highlightthickness=1,
            bd=0,
        )
        self.info_box.pack(fill="x", padx=34, pady=(0, 10))

        inner = tk.Frame(self.info_box, bg=COLORS["panel_alt"])
        inner.pack(fill="x", padx=14, pady=12)

                           
        preview_col = tk.Frame(inner, bg=COLORS["panel_alt"], width=174, height=98)
        preview_col.pack(side="left", padx=(0, 16))
        preview_col.pack_propagate(False)

        self.thumbnail_box = tk.Frame(
            preview_col,
            bg="#303744",
            highlightbackground=COLORS["border"],
            highlightthickness=1,
        )
        self.thumbnail_box.place(x=0, y=0, width=170, height=96)

        self.thumbnail_label = tk.Label(
            self.thumbnail_box,
            text="▶",
            font=("Segoe UI", 22, "bold"),
            fg=COLORS["muted"],
            bg="#303744",
            bd=0,
            highlightthickness=0,
        )
        self.thumbnail_label.pack(fill="both", expand=True)

                 
        details = tk.Frame(inner, bg=COLORS["panel_alt"])
        details.pack(fill="both", expand=True)

        heading_row = tk.Frame(details, bg=COLORS["panel_alt"])
        heading_row.pack(fill="x")

        tk.Label(
            heading_row,
            text="Current Item",
            font=("Segoe UI", 9),
            fg=COLORS["muted"],
            bg=COLORS["panel_alt"],
            anchor="w",
        ).pack(side="left")

        self.preview_state_label = tk.Label(
            heading_row,
            text="No preview",
            font=("Segoe UI", 8),
            fg=COLORS["muted"],
            bg=COLORS["panel_alt"],
            anchor="e",
        )
        self.preview_state_label.pack(side="right")

        tk.Label(
            details,
            textvariable=self.title_var,
            font=("Segoe UI", 12, "bold"),
            fg=COLORS["text"],
            bg=COLORS["panel_alt"],
            anchor="w",
            justify="left",
            wraplength=650,
        ).pack(fill="x", pady=(5, 3))

        tk.Label(
            details,
            textvariable=self.detail_var,
            font=("Segoe UI", 9),
            fg=COLORS["muted"],
            bg=COLORS["panel_alt"],
            anchor="w",
            justify="left",
        ).pack(fill="x")

                                                               

    def build_progress(self):
        status_row = tk.Frame(self.panel, bg=COLORS["panel"])
        status_row.pack(fill="x", padx=34, pady=(0, 4))

        tk.Label(
            status_row,
            textvariable=self.status_var,
            font=("Segoe UI", 9, "bold"),
            fg=COLORS["accent"],
            bg=COLORS["panel"],
        ).pack(side="left")

        self.percent_label = tk.Label(
            status_row,
            text="0%",
            font=("Segoe UI", 9, "bold"),
            fg=COLORS["text"],
            bg=COLORS["panel"],
        )
        self.percent_label.pack(side="right")

        self.progress = ttk.Progressbar(
            self.panel,
            variable=self.progress_var,
            maximum=100,
            mode="determinate",
            style="Moody.Horizontal.TProgressbar",
        )
        self.progress.pack(fill="x", padx=34, pady=(0, 5))

        meta = tk.Frame(self.panel, bg=COLORS["panel"])
        meta.pack(fill="x", padx=34, pady=(0, 8))

        tk.Label(meta, textvariable=self.speed_var, font=("Segoe UI", 9),
                 fg=COLORS["muted"], bg=COLORS["panel"]).pack(side="left")
        tk.Label(meta, textvariable=self.eta_var, font=("Segoe UI", 9),
                 fg=COLORS["muted"], bg=COLORS["panel"]).pack(side="right")

                                                               

    def build_queue_panel(self):
                    
        q_header = tk.Frame(self.panel, bg=COLORS["panel"])
        q_header.pack(fill="x", padx=34, pady=(0, 4))

        tk.Label(
            q_header,
            text="📋  Download Queue",
            font=("Segoe UI", 10, "bold"),
            fg=COLORS["text"],
            bg=COLORS["panel"],
        ).pack(side="left")

        self.queue_count_label = tk.Label(
            q_header,
            text="Empty",
            font=("Segoe UI", 8),
            fg=COLORS["muted"],
            bg=COLORS["panel"],
        )
        self.queue_count_label.pack(side="left", padx=(8, 0))

        btn_clear_q = self.make_button(
            q_header, "✕ Clear Queue", self.clear_queue, primary=False,
        )
        btn_clear_q.configure(font=("Segoe UI", 8, "bold"), padx=8, pady=4)
        btn_clear_q.pack(side="right")

        btn_remove = self.make_button(
            q_header, "🗑 Remove Selected", self.remove_queue_item, primary=False,
        )
        btn_remove.configure(font=("Segoe UI", 8, "bold"), padx=8, pady=4)
        btn_remove.pack(side="right", padx=(0, 6))

                           
        q_box = tk.Frame(
            self.panel,
            bg=COLORS["panel_alt"],
            highlightbackground=COLORS["border"],
            highlightthickness=1,
            bd=0,
        )
        q_box.pack(fill="x", padx=34, pady=(0, 8))

        self.queue_listbox = tk.Listbox(
            q_box,
            bg=COLORS["panel_alt"],
            fg=COLORS["text"],
            selectbackground=COLORS["accent_soft"],
            selectforeground=COLORS["accent"],
            font=("Segoe UI", 9),
            relief="flat",
            bd=0,
            highlightthickness=0,
            height=4,
            activestyle="none",
        )
        q_scrollbar = ttk.Scrollbar(q_box, orient="vertical",
                                    command=self.queue_listbox.yview)
        self.queue_listbox.configure(yscrollcommand=q_scrollbar.set)
        self.queue_listbox.pack(side="left", fill="both", expand=True,
                                padx=(8, 0), pady=6)
        q_scrollbar.pack(side="right", fill="y", pady=6, padx=(0, 4))

                                                                

    def build_actions(self):
        buttons = tk.Frame(self.panel, bg=COLORS["panel"])
        buttons.pack(pady=(0, 10))

        self.download_button = self.make_button(
            buttons, "⬇  Download Now", self.start_download, primary=True,
        )
        self.download_button.pack(side="left", padx=5, ipadx=16, ipady=5)

        self.start_queue_button = self.make_button(
            buttons, "▶  Start Queue", self.start_queue, primary=True,
        )
        self.start_queue_button.pack(side="left", padx=5, ipadx=16, ipady=5)

        self.cancel_button = self.make_button(
            buttons, "■  Cancel", self.cancel_download, primary=False,
        )
        self.cancel_button.pack(side="left", padx=5, ipadx=19, ipady=5)
        self.cancel_button.configure(state="disabled")

        self.clear_button = self.make_button(
            buttons, "✕  Clear", self.clear, primary=False,
        )
        self.clear_button.pack(side="left", padx=5, ipadx=21, ipady=5)

    def build_footer(self):
        footer = tk.Frame(self.panel, bg=COLORS["panel"])
        footer.pack(fill="x", padx=34, pady=(0, 14))

        tk.Label(
            footer,
            text=f"YouTube Downloader v{APP_VERSION}  •  Made with guts and Python",
            font=("Segoe UI", 8),
            fg=COLORS["muted"],
            bg=COLORS["panel"],
        ).pack(side="left")

        for label, cmd in [
            ("ℹ  About",     self.open_about_window),
            ("⚙  Settings",  self.open_settings_window),
            ("📜  History",   self.open_history_window),
        ]:
            btn = self.make_button(footer, label, cmd, primary=False)
            btn.configure(font=("Segoe UI", 8, "bold"), padx=8, pady=3)
            btn.pack(side="right", padx=(0, 4))

        tk.Label(
            footer,
            text="Still here, still curious.",
            font=("Segoe UI", 8),
            fg=COLORS["muted"],
            bg=COLORS["panel"],
        ).pack(side="right", padx=(0, 8))


                                                                
                    
                                                                

    def section_label(self, title, helper):
        row = tk.Frame(self.panel, bg=COLORS["panel"])
        row.pack(fill="x", padx=34, pady=(3, 2))
        tk.Label(row, text=title, font=("Segoe UI", 10, "bold"),
                 fg=COLORS["text"], bg=COLORS["panel"]).pack(side="left")
        tk.Label(row, text=f"  {helper}", font=("Segoe UI", 8),
                 fg=COLORS["muted"], bg=COLORS["panel"]).pack(side="left")

    def field_label(self, parent, column, text, row=0, columnspan=1):
        tk.Label(
            parent, text=text,
            font=("Segoe UI", 10, "bold"),
            fg=COLORS["text"],
            bg=COLORS["panel"],
            anchor="w",
        ).grid(
            row=row, column=column, columnspan=columnspan,
            sticky="ew",
            padx=(0 if column == 0 else 7, 7 if column < 2 else 0),
        )

    def make_button(self, parent, text, command, primary=False):
        bg     = COLORS["accent"]       if primary else COLORS["field"]
        active = COLORS["accent_hover"] if primary else "#303844"
        fg     = "#181A1F"              if primary else COLORS["text"]
        return tk.Button(
            parent, text=text, command=command,
            font=("Segoe UI", 10, "bold"),
            fg=fg, bg=bg,
            activeforeground=fg, activebackground=active,
            relief="flat", bd=0, cursor="hand2",
            padx=12, pady=6, highlightthickness=0,
        )

                                                                
                
                                                                

    def find_background(self):
        for filename in BACKGROUND_CANDIDATES:
            path = BASE_DIR / filename
            if path.exists():
                return path
        return None

    def draw_background(self):
        width  = max(self.root.winfo_width(),  960)
        height = max(self.root.winfo_height(), 760)
        target_size = (width, height)

        if self.bg_photo is not None and self.bg_last_size == target_size:
            return
        if self._bg_rendering:
            return

        bg_path = self.find_background()
        if PIL_AVAILABLE and bg_path:
            self._bg_rendering = True
            threading.Thread(
                target=self._bg_render_worker,
                args=(bg_path, width, height, target_size),
                daemon=True,
            ).start()
            return

        self.canvas.configure(bg=COLORS["window"])
        self.bg_photo     = None
        self.bg_last_size = target_size

    def on_resize(self, _event=None):
        width  = max(self.root.winfo_width(),  960)
        height = max(self.root.winfo_height(), 760)

        panel_width  = min(940, width  - 70)
        panel_height = min(780, height - 60)

        try:
            root_x = self.root.winfo_rootx()
            root_y = self.root.winfo_rooty()
            x = root_x + max((width  - panel_width)  // 2, 0)
            y = root_y + max((height - panel_height) // 2, 0)
            target_geom = f"{panel_width}x{panel_height}+{x}+{y}"
            if self.panel_window.geometry() != target_geom:
                self.panel_window.geometry(target_geom)
        except (tk.TclError, AttributeError):
            pass

        if self.resize_job is not None:
            try:
                self.root.after_cancel(self.resize_job)
            except tk.TclError:
                pass
        self.resize_job = self.root.after(80, self._redraw_bg_after_resize)

    def _redraw_bg_after_resize(self):
        self.resize_job = None
        self.draw_background()

    def _bg_render_worker(self, bg_path, width, height, target_size):
        try:
            if self.bg_source_image is None or getattr(self, "bg_source_path", None) != bg_path:
                self.bg_source_image = Image.open(bg_path).convert("RGB")
                self.bg_source_path  = bg_path

            img   = self.bg_source_image
            scale = max(width / img.width, height / img.height)
            new_w = max(1, int(img.width  * scale))
            new_h = max(1, int(img.height * scale))
            img   = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

            left = max((img.width  - width)  // 2, 0)
            top  = max((img.height - height) // 2, 0)
            img  = img.crop((left, top, left + width, top + height))

            if BACKGROUND_OVERLAY_ALPHA > 0:
                overlay = Image.new("RGB", img.size, COLORS["black_overlay"])
                img = Image.blend(img, overlay,
                                  max(0.0, min(1.0, BACKGROUND_OVERLAY_ALPHA)))

            self.events.put(("bg_ready", img, target_size))
        except Exception as exc:
            logger.error("Background render failed: %s", exc, exc_info=True)
            self._bg_rendering = False

                                                                
                                  
                                                                

    def _poll_clipboard(self):
        """Check clipboard every second for YouTube URLs."""
        try:
            text = self.root.clipboard_get().strip()
        except tk.TclError:
            text = ""

        if (
            text
            and text != self._last_clipboard
            and self._is_valid_url(text)
            and ("youtube.com" in text or "youtu.be" in text)
            and not self.downloading
            and not self.url_var.get().strip()
        ):
            self._last_clipboard = text
            self._notify_clipboard(text)

        self._clipboard_after = self.root.after(1500, self._poll_clipboard)

    def _notify_clipboard(self, url: str):
        """Show a subtle in-UI banner when a YouTube URL is detected."""
        if hasattr(self, "_clipboard_banner") and self._clipboard_banner.winfo_exists():
            self._clipboard_banner.destroy()

        banner = tk.Frame(
            self.panel,
            bg=COLORS["accent_soft"],
            highlightbackground=COLORS["accent"],
            highlightthickness=1,
        )
        banner.pack(fill="x", padx=34, pady=(0, 4))

        short = url if len(url) <= 56 else url[:53] + "..."
        tk.Label(
            banner,
            text=f"📋  YouTube URL detected: {short}",
            font=("Segoe UI", 8),
            fg=COLORS["accent"],
            bg=COLORS["accent_soft"],
            anchor="w",
        ).pack(side="left", padx=8, pady=4)

        def _use():
            self.url_var.set(url)
            banner.destroy()
            self.preview_video()

        def _queue_it():
            self.url_var.set(url)
            self.add_to_queue()
            banner.destroy()

        tk.Button(
            banner, text="Preview", command=_use,
            font=("Segoe UI", 8, "bold"),
            fg=COLORS["accent"], bg=COLORS["accent_soft"],
            relief="flat", bd=0, cursor="hand2",
            activeforeground=COLORS["accent_hover"],
            activebackground=COLORS["accent_soft"],
            highlightthickness=0, padx=6, pady=2,
        ).pack(side="right", padx=(0, 4), pady=3)

        tk.Button(
            banner, text="Add to Queue", command=_queue_it,
            font=("Segoe UI", 8, "bold"),
            fg=COLORS["text"], bg=COLORS["accent_soft"],
            relief="flat", bd=0, cursor="hand2",
            activeforeground=COLORS["muted"],
            activebackground=COLORS["accent_soft"],
            highlightthickness=0, padx=6, pady=2,
        ).pack(side="right", pady=3)

        tk.Button(
            banner, text="✕", command=banner.destroy,
            font=("Segoe UI", 8),
            fg=COLORS["muted"], bg=COLORS["accent_soft"],
            relief="flat", bd=0, cursor="hand2",
            activeforeground=COLORS["text"],
            activebackground=COLORS["accent_soft"],
            highlightthickness=0, padx=4, pady=2,
        ).pack(side="right", pady=3)

        self._clipboard_banner = banner

                                
        self.root.after(8000, lambda: banner.destroy() if banner.winfo_exists() else None)

                                                                
                      
                                                                

    def add_to_queue(self):
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("URL missing", "Masukkan URL YouTube dulu ya.")
            return
        if not self._is_valid_url(url):
            messagebox.showwarning(
                "URL tidak valid",
                "URL yang dimasukkan tidak valid.\n"
                "Pastikan URL dimulai dengan https://www.youtube.com/...",
            )
            return

        raw_dir = self.output_dir_var.get().strip()
        if not raw_dir:
            messagebox.showwarning("Folder missing", "Pilih folder output dulu.")
            return

        item = QueueItem(
            url=url,
            mode=self.mode_var.get(),
            quality=self.quality_var.get(),
            audio_quality=self.audio_quality_var.get(),
            subtitle_lang=self.subtitle_lang_var.get(),
            output_dir=raw_dir,
        )

        with self.queue_lock:
            self.download_queue.append(item)

        self.url_var.set("")
        self.refresh_queue_ui()
        with self.queue_lock:
            count = len(self.download_queue)
        self.status_var.set(f"Added to queue  •  {count} item(s) waiting")

    def remove_queue_item(self):
        sel = self.queue_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        with self.queue_lock:
            if idx < len(self.download_queue):
                if self.download_queue[idx].status == QueueStatus.DOWNLOADING:
                    messagebox.showwarning(
                        "Sedang didownload",
                        "Item ini sedang didownload.\nGunakan Cancel untuk membatalkan.",
                    )
                    return
                self.download_queue.pop(idx)
        self.refresh_queue_ui()

    def clear_queue(self):
        with self.queue_lock:
            self.download_queue = [
                i for i in self.download_queue
                if i.status == QueueStatus.DOWNLOADING
            ]
        self.refresh_queue_ui()

    def refresh_queue_ui(self):
        self.queue_listbox.delete(0, tk.END)

        with self.queue_lock:
            items = list(self.download_queue)

        STATUS_ICON = {
            QueueStatus.WAITING:     "○",
            QueueStatus.DOWNLOADING: "↓",
            QueueStatus.DONE:        "✓",
            QueueStatus.ERROR:       "✗",
            QueueStatus.CANCELLED:   "–",
        }
        STATUS_COLOR = {
            QueueStatus.WAITING:     COLORS["muted"],
            QueueStatus.DOWNLOADING: COLORS["accent"],
            QueueStatus.DONE:        COLORS["success"],
            QueueStatus.ERROR:       COLORS["danger"],
            QueueStatus.CANCELLED:   COLORS["muted"],
        }

        for item in items:
            icon    = STATUS_ICON.get(item.status, "○")
            display = item.title if item.title else item.url
            if len(display) > 62:
                display = display[:59] + "…"
            label = f"  {icon}  {display}  •  {item.mode}"
            self.queue_listbox.insert(tk.END, label)
            self.queue_listbox.itemconfigure(
                self.queue_listbox.size() - 1,
                fg=STATUS_COLOR.get(item.status, COLORS["text"]),
            )

        total   = len(items)
        waiting = sum(1 for i in items if i.status == QueueStatus.WAITING)
        done    = sum(1 for i in items if i.status == QueueStatus.DONE)

        if total == 0:
            self.queue_count_label.configure(text="Empty")
        else:
            self.queue_count_label.configure(
                text=f"{total} item(s)  •  {waiting} waiting  •  {done} done"
            )

    def start_queue(self):
        with self.queue_lock:
            has_waiting = any(i.status == QueueStatus.WAITING
                              for i in self.download_queue)

        if not has_waiting:
            messagebox.showinfo("Queue kosong",
                                "Tidak ada item yang menunggu di queue.\n"
                                "Tambahkan URL dulu dengan tombol ➕ Queue.")
            return
        if self.queue_processing:
            messagebox.showinfo("Queue berjalan", "Queue sedang diproses.")
            return
        if self.downloading:
            messagebox.showwarning("Sedang download",
                                   "Selesaikan download saat ini dulu.")
            return

        self.queue_processing = True
        self._process_next_queue_item()

    def _process_next_queue_item(self):
        """Pick next WAITING item and start downloading it."""
        with self.queue_lock:
            next_item = next(
                (i for i in self.download_queue if i.status == QueueStatus.WAITING),
                None,
            )

        if next_item is None:
            self.queue_processing = False
            self.events.put(("queue_finished",))
            return

        next_item.status = QueueStatus.DOWNLOADING
        self.refresh_queue_ui()

        output_dir = Path(next_item.output_dir).expanduser()
        output_dir.mkdir(parents=True, exist_ok=True)

                      
        if next_item.mode not in ("Thumbnail", "Subtitle") and shutil.which("ffmpeg") is None:
            next_item.status    = QueueStatus.ERROR
            next_item.error_msg = "FFmpeg tidak ditemukan di sistem."
            self.refresh_queue_ui()
            self.root.after(300, self._process_next_queue_item)
            return

        self._cancel_event.clear()
        self.downloading = True
        self._set_buttons_downloading()

        threading.Thread(
            target=self._queue_download_worker,
            args=(next_item, output_dir),
            daemon=True,
        ).start()

    def _queue_download_worker(self, item: QueueItem, output_dir: Path):
        try:
            self._run_download(
                item.url, output_dir, item.mode,
                item.quality, item.audio_quality,
                item.subtitle_lang,
                queue_item=item,
            )
        except yt_dlp.utils.DownloadCancelled:
            item.status = QueueStatus.CANCELLED
            self._cancel_event.clear()
            self._cleanup_temp_files(output_dir)
            self.events.put(("queue_item_cancelled", item))
        except Exception as exc:
            logger.error("Queue download failed: %s", exc, exc_info=True)
            item.status    = QueueStatus.ERROR
            item.error_msg = self._friendly_error(exc)
            self._cleanup_temp_files(output_dir)
            self.events.put(("queue_item_error", item))

                                                                
                    
                                                                

    def open_history_window(self):
        win = tk.Toplevel(self.root)
        win.title("Download History")
        win.geometry("820x500")
        win.configure(bg=COLORS["panel"])
        win.transient(self.root)
        win.grab_set()

                   
        hdr = tk.Frame(win, bg=COLORS["panel"])
        hdr.pack(fill="x", padx=20, pady=(16, 8))

        tk.Label(
            hdr,
            text="📜  Download History",
            font=("Segoe UI", 14, "bold"),
            fg=COLORS["text"],
            bg=COLORS["panel"],
        ).pack(side="left")

                  
        table_frame = tk.Frame(win, bg=COLORS["panel"])
        table_frame.pack(fill="both", expand=True, padx=20, pady=(0, 8))

        cols = ("Date", "Title", "Mode", "Status", "Path")
        table = ttk.Treeview(
            table_frame, columns=cols, show="headings",
            style="History.Treeview",
        )
        for col in cols:
            table.heading(col, text=col)
        table.column("Date",   width=140, stretch=False)
        table.column("Title",  width=260)
        table.column("Mode",   width=80,  stretch=False)
        table.column("Status", width=70,  stretch=False)
        table.column("Path",   width=230)

        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=table.yview)
        table.configure(yscrollcommand=vsb.set)
        table.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        for row in self.history.get_all():
            _, title, date, mode, path, status = row
            table.insert("", tk.END, values=(date, title, mode, status, path))

                    
        btn_frame = tk.Frame(win, bg=COLORS["panel"])
        btn_frame.pack(fill="x", padx=20, pady=(0, 14))

        self.make_button(
            btn_frame, "📂  Open File",
            lambda: self._history_open_file(table), primary=False,
        ).pack(side="left", padx=(0, 8), ipady=4)

        self.make_button(
            btn_frame, "📁  Open Folder",
            lambda: self._history_open_folder(table), primary=False,
        ).pack(side="left", ipady=4)

        self.make_button(
            btn_frame, "🗑  Clear All",
            lambda: self._clear_history(table), primary=False,
        ).pack(side="left", padx=(8, 0), ipady=4)

        self.make_button(
            btn_frame, "✕  Close",
            win.destroy, primary=False,
        ).pack(side="right", ipady=4)

    def _clear_history(self, table):
        if messagebox.askyesno("Clear History", "Hapus semua riwayat download?"):
            self.history.clear()
            for child in table.get_children():
                table.delete(child)

    def _history_open_file(self, table):
        sel = table.selection()
        if not sel:
            return
        path = table.item(sel[0])["values"][4]
        if path and Path(str(path)).exists():
            os.startfile(str(path))
        else:
            messagebox.showwarning("File tidak ditemukan",
                                   f"File tidak ada lagi:\n{path}")

    def _history_open_folder(self, table):
        sel = table.selection()
        if not sel:
            return
        path = table.item(sel[0])["values"][4]
        if path:
            folder = str(Path(str(path)).parent)
            subprocess.Popen(["explorer", folder])

                                                                
                            
                                                                

    def _setup_drag_drop(self):
        """Register tkinterdnd2 drag-and-drop on the URL entry if available."""
        if not DND_AVAILABLE:
            return
        try:
            self.url_entry.drop_target_register(DND_TEXT, DND_FILES)
            self.url_entry.dnd_bind("<<Drop>>", self._on_drop)
                                                                         
            self.panel_window.drop_target_register(DND_TEXT, DND_FILES)
            self.panel_window.dnd_bind("<<Drop>>", self._on_drop)
        except Exception as exc:
            logger.warning("Drag & drop setup failed: %s", exc)

    def _on_drop(self, event):
        """Handle a dropped URL or text."""
        data = event.data.strip().strip("{}")                                  
                                            
        data = data.splitlines()[0].strip()
        if self._is_valid_url(data) and ("youtube" in data or "youtu.be" in data):
            self.url_var.set(data)
            self.status_var.set("URL dropped • fetching preview…")
            self.preview_video()
        elif data:
            self.url_var.set(data)
            self.status_var.set("Text dropped into URL field.")

                                                                
                                
                                                                

    def open_settings_window(self):
        win = tk.Toplevel(self.root)
        win.title("Settings")
        win.geometry("580x520")
        win.configure(bg=COLORS["panel"])
        win.transient(self.root)
        win.grab_set()
        win.resizable(False, False)

        tk.Label(
            win,
            text="⚙  Settings",
            font=("Segoe UI", 14, "bold"),
            fg=COLORS["text"],
            bg=COLORS["panel"],
        ).pack(padx=24, pady=(18, 4), anchor="w")

        nb = ttk.Notebook(win)
        nb.pack(fill="both", expand=True, padx=20, pady=(0, 10))

        s = ttk.Style()
        s.configure("TNotebook",         background=COLORS["panel"],
                    bordercolor=COLORS["border"])
        s.configure("TNotebook.Tab",     background=COLORS["field"],
                    foreground=COLORS["muted"],
                    padding=[10, 4])
        s.map("TNotebook.Tab",
              background=[("selected", COLORS["panel_alt"])],
              foreground=[("selected", COLORS["accent"])])

                        
        gen = self._settings_tab(nb, "General")

        def_mode_var    = tk.StringVar(value=self.settings.get("default_mode",    "Video"))
        def_quality_var = tk.StringVar(value=self.settings.get("default_quality", "1080p"))
        def_audio_var   = tk.StringVar(value=self.settings.get("default_audio_q", "320K"))

        self._settings_row(gen, "Default Mode",
                           ttk.Combobox(gen, textvariable=def_mode_var,
                                        values=["Video","MP3","Thumbnail","Subtitle"],
                                        state="readonly", style="Moody.TCombobox"),
                           "default_mode")
        self._settings_row(gen, "Default Quality",
                           ttk.Combobox(gen, textvariable=def_quality_var,
                                        values=["Best","2160p (4K)","1440p","1080p","720p","480p","360p"],
                                        state="readonly", style="Moody.TCombobox"),
                           "default_quality")
        self._settings_row(gen, "Default Audio Quality",
                           ttk.Combobox(gen, textvariable=def_audio_var,
                                        values=["320K","256K","192K","128K"],
                                        state="readonly", style="Moody.TCombobox"),
                           "default_audio_q")

                    
        out_var = tk.StringVar(value=self.settings.get("output_dir", DEFAULT_DIR))
        out_row = tk.Frame(gen, bg=COLORS["panel_alt"])
        out_row.pack(fill="x", padx=14, pady=(6, 0))
        tk.Label(out_row, text="Default Output Folder", font=("Segoe UI", 9),
                 fg=COLORS["muted"], bg=COLORS["panel_alt"], anchor="w", width=22).pack(side="left")
        tk.Entry(out_row, textvariable=out_var, font=("Segoe UI", 9),
                 fg=COLORS["text"], bg=COLORS["field"], relief="flat",
                 insertbackground=COLORS["accent"], highlightthickness=0).pack(side="left", fill="x", expand=True, ipady=5, padx=(0,6))
        tk.Button(out_row, text="Browse", command=lambda: out_var.set(filedialog.askdirectory(initialdir=out_var.get()) or out_var.get()),
                  font=("Segoe UI", 8), fg=COLORS["text"], bg=COLORS["field"],
                  activeforeground=COLORS["text"], activebackground="#303844",
                  relief="flat", bd=0, cursor="hand2", padx=8, pady=4,
                  highlightthickness=0).pack(side="left")

                      
        cleanup_var = tk.BooleanVar(value=self.settings.get("auto_cleanup", True))
        notif_var   = tk.BooleanVar(value=self.settings.get("notifications", True))
        for label, var in [("Auto cleanup .part files on error", cleanup_var),
                            ("Show download notifications",       notif_var)]:
            row = tk.Frame(gen, bg=COLORS["panel_alt"])
            row.pack(fill="x", padx=14, pady=(6, 0))
            tk.Label(row, text=label, font=("Segoe UI", 9),
                     fg=COLORS["muted"], bg=COLORS["panel_alt"],
                     anchor="w").pack(side="left", fill="x", expand=True)
            tk.Checkbutton(row, variable=var,
                           bg=COLORS["panel_alt"], fg=COLORS["accent"],
                           activebackground=COLORS["panel_alt"],
                           selectcolor=COLORS["field"],
                           relief="flat", bd=0, highlightthickness=0).pack(side="right")

                           
        app_tab = self._settings_tab(nb, "Appearance")

        theme_var = tk.StringVar(value=self.settings.get("theme", "Void Horizon"))
        self._settings_row(app_tab, "Theme",
                           ttk.Combobox(app_tab, textvariable=theme_var,
                                        values=list(THEMES.keys()),
                                        state="readonly", style="Moody.TCombobox"),
                           "theme_preview")

                       
        alpha_var = tk.DoubleVar(value=self.settings.get("panel_alpha", 0.72))
        alpha_row = tk.Frame(app_tab, bg=COLORS["panel_alt"])
        alpha_row.pack(fill="x", padx=14, pady=(6, 0))
        tk.Label(alpha_row, text="Panel Opacity", font=("Segoe UI", 9),
                 fg=COLORS["muted"], bg=COLORS["panel_alt"], width=22, anchor="w").pack(side="left")
        alpha_label = tk.Label(alpha_row, text=f"{alpha_var.get():.0%}",
                               font=("Segoe UI", 9), fg=COLORS["accent"],
                               bg=COLORS["panel_alt"], width=5)
        alpha_label.pack(side="right")

        def _update_alpha_label(v):
            alpha_label.configure(text=f"{float(v):.0%}")

        tk.Scale(alpha_row, variable=alpha_var, from_=0.3, to=1.0,
                 resolution=0.01, orient="horizontal",
                 bg=COLORS["panel_alt"], fg=COLORS["text"],
                 troughcolor=COLORS["field"], activebackground=COLORS["accent"],
                 highlightthickness=0, bd=0, showvalue=False,
                 command=_update_alpha_label).pack(side="left", fill="x", expand=True, padx=(0,4))

                            
        overlay_var = tk.DoubleVar(value=self.settings.get("bg_overlay_alpha", 0.0))
        ov_row = tk.Frame(app_tab, bg=COLORS["panel_alt"])
        ov_row.pack(fill="x", padx=14, pady=(6, 0))
        tk.Label(ov_row, text="Background Dim", font=("Segoe UI", 9),
                 fg=COLORS["muted"], bg=COLORS["panel_alt"], width=22, anchor="w").pack(side="left")
        ov_label = tk.Label(ov_row, text=f"{overlay_var.get():.0%}",
                            font=("Segoe UI", 9), fg=COLORS["accent"],
                            bg=COLORS["panel_alt"], width=5)
        ov_label.pack(side="right")

        def _update_ov_label(v):
            ov_label.configure(text=f"{float(v):.0%}")

        tk.Scale(ov_row, variable=overlay_var, from_=0.0, to=0.9,
                 resolution=0.05, orient="horizontal",
                 bg=COLORS["panel_alt"], fg=COLORS["text"],
                 troughcolor=COLORS["field"], activebackground=COLORS["accent"],
                 highlightthickness=0, bd=0, showvalue=False,
                 command=_update_ov_label).pack(side="left", fill="x", expand=True, padx=(0,4))

                        
        wp_var = tk.StringVar(value=str(self.find_background() or ""))
        wp_row = tk.Frame(app_tab, bg=COLORS["panel_alt"])
        wp_row.pack(fill="x", padx=14, pady=(6, 0))
        tk.Label(wp_row, text="Wallpaper", font=("Segoe UI", 9),
                 fg=COLORS["muted"], bg=COLORS["panel_alt"], width=22, anchor="w").pack(side="left")
        tk.Entry(wp_row, textvariable=wp_var, font=("Segoe UI", 9),
                 fg=COLORS["text"], bg=COLORS["field"], relief="flat",
                 insertbackground=COLORS["accent"], highlightthickness=0).pack(side="left", fill="x", expand=True, ipady=5, padx=(0,6))
        tk.Button(wp_row, text="Browse",
                  command=lambda: wp_var.set(filedialog.askopenfilename(
                      filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp *.webp")]) or wp_var.get()),
                  font=("Segoe UI", 8), fg=COLORS["text"], bg=COLORS["field"],
                  activeforeground=COLORS["text"], activebackground="#303844",
                  relief="flat", bd=0, cursor="hand2", padx=8, pady=4,
                  highlightthickness=0).pack(side="left")

                                                                         

                                  
        btn_row = tk.Frame(win, bg=COLORS["panel"])
        btn_row.pack(fill="x", padx=20, pady=(0, 16))

        def _save():
            new_settings = dict(self.settings)
            new_settings["default_mode"]    = def_mode_var.get()
            new_settings["default_quality"] = def_quality_var.get()
            new_settings["default_audio_q"] = def_audio_var.get()
            new_settings["output_dir"]      = out_var.get()
            new_settings["auto_cleanup"]    = cleanup_var.get()
            new_settings["notifications"]   = notif_var.get()
            new_settings["theme"]           = theme_var.get()
            new_settings["panel_alpha"]     = round(alpha_var.get(), 2)
            new_settings["bg_overlay_alpha"]= round(overlay_var.get(), 2)
            self.settings = new_settings
            save_settings(new_settings)

                              
            self._apply_theme(theme_var.get())

                                    
            global PANEL_ALPHA, BACKGROUND_OVERLAY_ALPHA
            PANEL_ALPHA              = new_settings["panel_alpha"]
            BACKGROUND_OVERLAY_ALPHA = new_settings["bg_overlay_alpha"]
            try:
                self.panel_window.attributes("-alpha", PANEL_ALPHA)
            except Exception:
                pass

                                                   
            self.bg_source_image = None
            self.bg_last_size    = None
            self.draw_background()

            win.destroy()
            messagebox.showinfo("Settings saved",
                                "Pengaturan berhasil disimpan!\n"
                                "Beberapa perubahan (tema) baru aktif setelah restart.")

        self.make_button(btn_row, "💾  Save", _save, primary=True).pack(side="left", ipady=4, ipadx=16)
        self.make_button(btn_row, "✕  Cancel", win.destroy, primary=False).pack(side="left", padx=(8,0), ipady=4)

    @staticmethod
    def _settings_tab(nb, title):
        frame = tk.Frame(nb, bg=COLORS["panel_alt"])
        nb.add(frame, text=f"  {title}   ")
        return frame

    def _settings_row(self, parent, label_text, widget, _key):
        row = tk.Frame(parent, bg=COLORS["panel_alt"])
        row.pack(fill="x", padx=14, pady=(6, 0))
        tk.Label(row, text=label_text, font=("Segoe UI", 9),
                 fg=COLORS["muted"], bg=COLORS["panel_alt"],
                 anchor="w", width=22).pack(side="left")
        widget.configure(font=("Segoe UI", 9))
        widget.pack(side="left", fill="x", expand=True)

                                                                
                             
                                                                

    def open_about_window(self):
        win = tk.Toplevel(self.root)
        win.title("About")
        win.geometry("400x340")
        win.configure(bg=COLORS["panel"])
        win.transient(self.root)
        win.grab_set()
        win.resizable(False, False)

        tk.Label(
            win, text="🎬",
            font=("Segoe UI", 36),
            fg=COLORS["accent"],
            bg=COLORS["panel"],
        ).pack(pady=(24, 4))

        tk.Label(
            win,
            text=f"YouTube Downloader",
            font=("Segoe UI", 16, "bold"),
            fg=COLORS["text"],
            bg=COLORS["panel"],
        ).pack()

        tk.Label(
            win,
            text=f"Version {APP_VERSION}",
            font=("Segoe UI", 10),
            fg=COLORS["accent"],
            bg=COLORS["panel"],
        ).pack(pady=(2, 12))

        tk.Label(
            win,
            text=(
                "Built with:\n"
                "Python  •  Tkinter  •  yt-dlp  •  FFmpeg  •  Pillow"
            ),
            font=("Segoe UI", 9),
            fg=COLORS["muted"],
            bg=COLORS["panel"],
            justify="center",
        ).pack(pady=(0, 8))

        tk.Label(
            win,
            text="Made for personal use  ♡",
            font=("Segoe UI", 9, "italic"),
            fg=COLORS["muted"],
            bg=COLORS["panel"],
        ).pack()

                            
        dnd_txt = "✓ Drag & Drop aktif" if DND_AVAILABLE else "✗ Drag & Drop tidak tersedia (install tkinterdnd2)"
        dnd_col = COLORS["success"] if DND_AVAILABLE else COLORS["muted"]
        tk.Label(win, text=dnd_txt, font=("Segoe UI", 8),
                 fg=dnd_col, bg=COLORS["panel"]).pack(pady=(8, 0))

        tk.Label(win, text="Still here, still curious.",
                 font=("Segoe UI", 8, "italic"),
                 fg=COLORS["muted"], bg=COLORS["panel"]).pack(pady=(4, 0))

        self.make_button(win, "✕  Close", win.destroy, primary=False).pack(pady=(18, 0), ipadx=16, ipady=4)

                                                                
                             
                                                                

    def _cleanup_temp_files(self, output_dir: Path):
        """Remove leftover .part and .ytdl files from a failed/cancelled download."""
        if not self.settings.get("auto_cleanup", True):
            return
        removed = []
        for pattern in ("*.part", "*.ytdl", "*.temp"):
            for f in output_dir.glob(pattern):
                try:
                    f.unlink()
                    removed.append(f.name)
                except Exception:
                    pass
        if removed:
            logger.info("Auto cleanup removed: %s", ", ".join(removed))

                                                                
             
                                                                


    @staticmethod
    def _is_valid_url(url: str) -> bool:
        try:
            parsed = urlparse(url)
            return parsed.scheme in ("http", "https") and bool(parsed.netloc)
        except Exception:
            return False

    @staticmethod
    def _friendly_error(exc: Exception) -> str:
        """Map common exceptions to user-friendly Indonesian messages."""
        msg   = str(exc)
        lower = msg.lower()

        if "403" in msg or "forbidden" in lower:
            return (
                "Video ini tidak bisa diakses (HTTP 403).\n"
                "Kemungkinan: video privat, dibatasi usia, atau perlu login.\n\n"
                f"Detail teknis: {msg}"
            )
        if "429" in msg or "too many requests" in lower:
            return (
                "Terlalu banyak permintaan ke YouTube (HTTP 429).\n"
                "Tunggu beberapa menit lalu coba lagi."
            )
        if "404" in msg or "not found" in lower:
            return (
                "Video tidak ditemukan (HTTP 404).\n"
                "Pastikan URL benar dan video masih tersedia."
            )
        if "private" in lower:
            return (
                "Video ini bersifat privat.\n"
                "Kamu tidak bisa mendownload video privat tanpa login."
            )
        if "geo" in lower or "blocked in your country" in lower or "not available in your country" in lower:
            return (
                "Video ini diblokir di wilayah kamu (geo-restriction).\n"
                "Coba gunakan VPN atau proxy."
            )
        if "unavailable" in lower or "not available" in lower:
            return (
                "Video tidak tersedia di wilayah ini atau sudah dihapus.\n\n"
                f"Detail teknis: {msg}"
            )
        if "sign in" in lower or "login" in lower:
            return (
                "Video ini memerlukan login.\n"
                "yt-dlp saat ini tidak mendukung sesi login dari GUI ini."
            )
        if "urlopen error" in lower or "connection" in lower or "timeout" in lower:
            return (
                "Gagal terhubung ke internet.\n"
                "Periksa koneksi jaringan kamu dan coba lagi."
            )
        if "no space" in lower or "disk full" in lower or "not enough space" in lower:
            return (
                "Disk penuh!\n"
                "Hapus beberapa file atau pilih folder output yang lain."
            )
        if "permission" in lower or "access is denied" in lower:
            return (
                "Tidak punya izin menulis ke folder ini.\n"
                "Pilih folder lain atau jalankan sebagai Administrator."
            )
        if "requested format" in lower or "format not available" in lower:
            return (
                "Format yang diminta tidak tersedia untuk video ini.\n"
                "Coba resolusi yang lebih rendah atau pilih format lain."
            )
        if "ffmpeg" in lower:
            return (
                "FFmpeg tidak ditemukan atau gagal dijalankan.\n"
                "Pastikan FFmpeg sudah terinstall dan ada di PATH.\n\n"
                "Install: winget install Gyan.FFmpeg"
            )
        return msg

    @staticmethod
    def fetch_thumbnail_bytes(url: str) -> bytes:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/140 Safari/537.36"
                ),
                "Referer": "https://www.youtube.com/",
            },
        )
        with urllib.request.urlopen(req, timeout=20) as response:
            return response.read()

    @staticmethod
    def _save_thumbnail(data: bytes, destination: Path):
        if PIL_AVAILABLE:
            try:
                img = Image.open(BytesIO(data)).convert("RGB")
                img.save(destination, "JPEG", quality=95)
                return
            except Exception:
                pass
        destination.write_bytes(data)

    @staticmethod
    def sanitize_filename(name: str) -> str:
        name = (name or "youtube-video").strip()
        name = re.sub(r'[<>:"/\\|?*]', "_", name)
        name = re.sub(r"[\x00-\x1f]", "",  name)
        name = name.rstrip(" .")
        return (name or "youtube-video")[:180]

                                                                
                 
                                                                

    def on_mode_change(self, _event=None):
        mode = self.mode_var.get()

                      
        self.quality_combo.configure(state="disabled")
        self.audio_combo.configure(state="disabled")
        self.subtitle_lang_combo.grid_remove()
        self.audio_combo.grid()

        if mode == "Video":
            self.quality_combo.configure(state="readonly")
            self.third_col_label.configure(text="♫  Audio Quality (MP3)")
            self.download_button.configure(text="⬇  Download Video")
            self.status_var.set("Video mode selected")

        elif mode == "MP3":
            self.audio_combo.configure(state="readonly")
            self.third_col_label.configure(text="♫  Audio Quality (MP3)")
            self.download_button.configure(text="♫  Download MP3")
            self.status_var.set("MP3 mode selected")

        elif mode == "Subtitle":
            self.audio_combo.grid_remove()
            self.subtitle_lang_combo.grid()
            self.third_col_label.configure(text="🌐  Subtitle Language")
            self.download_button.configure(text="💬  Download Subtitle")
            self.status_var.set("Subtitle mode selected")

        else:             
            self.third_col_label.configure(text="♫  Audio Quality (MP3)")
            self.download_button.configure(text="🖼  Download Thumbnail")
            self.status_var.set("Thumbnail mode selected")

    def choose_folder(self):
        folder = filedialog.askdirectory(initialdir=self.output_dir_var.get())
        if folder:
            self.output_dir_var.set(folder)

    def paste_url(self):
        try:
            text = self.root.clipboard_get().strip()
        except tk.TclError:
            text = ""
        if text:
            self.url_var.set(text)
            self.status_var.set("URL pasted • fetching preview…")
            self.preview_video()

    def clear(self):
        if self.downloading:
            return
        self.url_var.set("")
        self.title_var.set("No video selected")
        self.detail_var.set("-")
        self.status_var.set("Ready • paste a YouTube link")
        self.progress_var.set(0)
        self.percent_label.configure(text="0%")
        self.speed_var.set("0 KB/s")
        self.eta_var.set("ETA: -")
        self.current_thumbnail_url   = None
        self.current_thumbnail_bytes = None
        self.thumbnail_photo         = None
        self.thumbnail_label.configure(image="", text="▶",
                                       fg=COLORS["muted"], bg="#303744")
        self.preview_state_label.configure(text="No preview", fg=COLORS["muted"])
        self.preview_button.configure(state="normal")
        self.paste_button.configure(state="normal")
        self.url_entry.focus()

    def cancel_download(self):
        if self.downloading:
            self._cancel_event.set()
            self.status_var.set("Cancelling…")
            self.cancel_button.configure(state="disabled")

                                                                
             
                                                                

    def preview_video(self):
        if self.downloading:
            return
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("URL missing", "Masukkan URL YouTube dulu ya.")
            return
        if not self._is_valid_url(url):
            messagebox.showwarning(
                "URL tidak valid",
                "URL yang dimasukkan tidak valid.\n"
                "Pastikan URL dimulai dengan https://www.youtube.com/...",
            )
            return

        self.preview_button.configure(state="disabled")
        self.paste_button.configure(state="disabled")
        self.status_var.set("Fetching video preview…")
        self.title_var.set("Loading thumbnail and video info…")
        self.detail_var.set("-")

        threading.Thread(target=self._preview_worker,
                         args=(url,), daemon=True).start()

    def _preview_worker(self, url: str):
        try:
            with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True,
                                   "noplaylist": True}) as ydl:
                info = ydl.extract_info(url, download=False)

            title    = info.get("title") or "Untitled"
            duration = self.format_duration(info.get("duration"))
            uploader = info.get("uploader") or "-"
            views    = info.get("view_count")
            date_raw = info.get("upload_date")               

                                                     
            best_res = ""
            best_fps = ""
            for f in reversed(info.get("formats", [])):
                if f.get("vcodec") and f.get("vcodec") != "none":
                    h  = f.get("height")
                    fr = f.get("fps")
                    if h:
                        best_res = f"{h}p"
                    if fr:
                        best_fps = f"{fr:.0f}fps"
                    break

            views_text  = f"{views:,} views" if views is not None else "Views: -"
            upload_date = ""
            if date_raw and len(date_raw) == 8:
                try:
                    d = datetime.datetime.strptime(date_raw, "%Y%m%d")
                    upload_date = d.strftime("%d %b %Y")
                except ValueError:
                    pass

            parts = [f"Duration: {duration}", f"Uploader: {uploader}", views_text]
            if best_res:
                parts.append(best_res)
            if best_fps:
                parts.append(best_fps)
            if upload_date:
                parts.append(f"Uploaded: {upload_date}")

            detail = "   •   ".join(parts)

            thumbnail_url   = info.get("thumbnail")
            thumbnail_bytes = None
            if thumbnail_url:
                try:
                    thumbnail_bytes = self.fetch_thumbnail_bytes(thumbnail_url)
                except Exception:
                    pass

            self.events.put(("preview", title, detail, thumbnail_url, thumbnail_bytes))

        except Exception as exc:
            logger.error("Preview failed for %s: %s", url, exc, exc_info=True)
            self.events.put(("preview_error", self._friendly_error(exc)))

    def render_thumbnail(self, thumbnail_bytes: bytes) -> bool:
        if not thumbnail_bytes or not PIL_AVAILABLE:
            return False
        try:
            image = Image.open(BytesIO(thumbnail_bytes)).convert("RGB")
            image = ImageOps.fit(image, (168, 94),
                                 method=Image.Resampling.LANCZOS,
                                 centering=(0.5, 0.5))
            self.thumbnail_photo = ImageTk.PhotoImage(image)
            self.thumbnail_label.configure(
                image=self.thumbnail_photo, text="", bg="#303744",
            )
            return True
        except Exception:
            self.thumbnail_photo = None
            self.thumbnail_label.configure(
                image="", text="▶", fg=COLORS["muted"], bg="#303744",
            )
            return False

                                                                
                        
                                                                

    def start_download(self):
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("URL missing", "Masukkan URL YouTube dulu ya.")
            return
        if not self._is_valid_url(url):
            messagebox.showwarning(
                "URL tidak valid",
                "URL yang dimasukkan tidak valid.\n"
                "Pastikan URL dimulai dengan https://www.youtube.com/...",
            )
            return

        raw_dir = self.output_dir_var.get().strip()
        if not raw_dir:
            messagebox.showwarning("Folder missing", "Pilih folder output dulu.")
            return

        mode       = self.mode_var.get()
        output_dir = Path(raw_dir).expanduser()

        if mode not in ("Thumbnail", "Subtitle") and shutil.which("ffmpeg") is None:
            messagebox.showerror(
                "FFmpeg tidak ditemukan",
                "FFmpeg tidak ditemukan di sistem kamu.\n\n"
                "FFmpeg diperlukan untuk menggabungkan video + audio dan konversi ke MP3.\n\n"
                "Cara install di Windows:\n"
                "  1. Download dari: https://ffmpeg.org/download.html\n"
                "     (pilih 'Windows builds from gyan.dev')\n"
                "  2. Ekstrak, lalu tambahkan folder 'bin' ke PATH sistem.\n"
                "  3. Restart terminal / VS Code, lalu coba lagi.\n\n"
                "Cara cepat via Winget (Windows 10/11):\n"
                "  winget install Gyan.FFmpeg",
            )
            return

        output_dir.mkdir(parents=True, exist_ok=True)

        self._cancel_event.clear()
        self.downloading = True
        self._set_buttons_downloading()
        self.progress_var.set(0)
        self.percent_label.configure(text="0%")
        self.status_var.set("Getting video information…")
        self.title_var.set("Fetching video information…")
        self.detail_var.set("-")
        self.speed_var.set("0 KB/s")
        self.eta_var.set("ETA: -")

        threading.Thread(
            target=self._direct_download_worker,
            args=(url, output_dir, mode,
                  self.quality_var.get(),
                  self.audio_quality_var.get(),
                  self.subtitle_lang_var.get()),
            daemon=True,
        ).start()

    def _direct_download_worker(self, url, output_dir, mode,
                                quality, audio_quality, subtitle_lang):
        try:
            self._run_download(url, output_dir, mode,
                               quality, audio_quality, subtitle_lang)
        except yt_dlp.utils.DownloadCancelled:
            self._cancel_event.clear()
            self._cleanup_temp_files(output_dir)
            self.events.put(("cancelled",))
        except Exception as exc:
            logger.error("Download failed for %s: %s", url, exc, exc_info=True)
            self._cleanup_temp_files(output_dir)
            self.events.put(("error", self._friendly_error(exc)))

                                                                

    def _run_download(
        self,
        url: str,
        output_dir: Path,
        mode: str,
        quality: str,
        audio_quality: str,
        subtitle_lang: str = "en",
        queue_item: "QueueItem | None" = None,
    ):
        """
        Shared download implementation used by both direct download and queue.
        Emits 'done' / 'thumbnail_mode_done' for direct, and
        'queue_item_done' for queue downloads.
        """

        def _record_history(title: str, file_path: str):
            self.history.add_entry(title, mode, file_path, "Done")

        def _finish_queue(item: "QueueItem", title: str, file_path: str):
            item.title     = title
            item.file_path = file_path
            item.status    = QueueStatus.DONE
            _record_history(title, file_path)
            self.events.put(("queue_item_done", item))

                                                               
        if mode == "Thumbnail":
            with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True,
                                   "noplaylist": True}) as ydl:
                info = ydl.extract_info(url, download=False)

            title         = info.get("title") or "youtube-video"
            thumbnail_url = info.get("thumbnail")
            if not thumbnail_url:
                raise RuntimeError("Video ini tidak menyediakan thumbnail.")

            data = self.fetch_thumbnail_bytes(thumbnail_url)
            if not data:
                raise RuntimeError("Gagal mengambil thumbnail dari YouTube.")

            filename    = self.sanitize_filename(title)
            destination = output_dir / f"{filename} - thumbnail.jpg"
            self._save_thumbnail(data, destination)

            self.events.put(("title", title))
            self.events.put(("detail", "Mode: Thumbnail"))
            self.events.put(("progress", 100, "", ""))

            if queue_item:
                _finish_queue(queue_item, title, str(destination))
            else:
                _record_history(title, str(destination))
                self.events.put(("thumbnail_mode_done", str(destination)))
            return

                                                               
        if mode == "Subtitle":
            opts = {
                "quiet": True,
                "no_warnings": True,
                "noplaylist": True,
                "outtmpl": str(output_dir / "%(title)s [%(id)s].%(ext)s"),
                "writesubtitles": True,
                "writeautomaticsub": True,
                "subtitleslangs": [subtitle_lang],
                "subtitlesformat": "srt/vtt/best",
                "skip_download": True,
            }
            with yt_dlp.YoutubeDL(opts) as ydl:
                info  = ydl.extract_info(url, download=False)
                title = info.get("title") or "Untitled"
                vid   = info.get("id", "")
                self.events.put(("title", title))
                self.events.put(("detail", f"Mode: Subtitle  •  Language: {subtitle_lang}"))
                self.events.put(("status", "Downloading subtitle…"))
                ydl.download([url])

                                                          
            sub_path = output_dir / f"{self.sanitize_filename(title)} [{vid}].{subtitle_lang}.srt"
            self.events.put(("progress", 100, "", ""))

            if queue_item:
                _finish_queue(queue_item, title, str(sub_path))
            else:
                _record_history(title, str(sub_path))
                self.events.put(("done",
                                 f"Subtitle berhasil didownload!\n"
                                 f"Cek folder: {output_dir}"))
            return

                                                                
        common = {
            "outtmpl":     str(output_dir / "%(title)s [%(id)s].%(ext)s"),
            "noplaylist":  True,
            "progress_hooks": [self.progress_hook],
            "quiet":       True,
            "no_warnings": True,
        }

        if mode == "MP3":
            opts = {
                **common,
                "format": "bestaudio/best",
                "postprocessors": [{
                    "key":             "FFmpegExtractAudio",
                    "preferredcodec":  "mp3",
                    "preferredquality": audio_quality,
                }],
            }
        else:         
            if quality == "Best":
                fmt = ("bv[vcodec^=avc1]+ba[acodec^=mp4a]/"
                       "b[vcodec^=avc1][acodec^=mp4a]")
            else:
                h = quality.replace("p (4K)", "").replace("p", "")
                fmt = (
                    f"bv[vcodec^=avc1][height<={h}]+ba[acodec^=mp4a]/"
                    f"b[vcodec^=avc1][acodec^=mp4a]/"
                    "bv[vcodec^=avc1]+ba[acodec^=mp4a]"
                )
            opts = {**common, "format": fmt, "merge_output_format": "mp4"}

        with yt_dlp.YoutubeDL(opts) as ydl:
            info      = ydl.extract_info(url, download=False)
            title     = info.get("title") or "Untitled"
            duration  = self.format_duration(info.get("duration"))
            uploader  = info.get("uploader") or "-"
            vid       = info.get("id", "")
            detail    = (f"Duration: {duration}   •   "
                         f"Uploader: {uploader}   •   "
                         f"Mode: {mode}")
            thumb_url = info.get("thumbnail")

            self.events.put(("title", title))
            self.events.put(("detail", detail))
            if thumb_url and self.current_thumbnail_bytes is None:
                self.events.put(("thumbnail_url", thumb_url))
            self.events.put(("status", f"Downloading {mode}…"))

            ydl.download([url])

        ext       = "mp3" if mode == "MP3" else "mp4"
        file_path = output_dir / f"{self.sanitize_filename(title)} [{vid}].{ext}"

        if queue_item:
            _finish_queue(queue_item, title, str(file_path))
        else:
            _record_history(title, str(file_path))
            self.events.put(("done",
                             "Download selesai • file sudah tersimpan byyyy"))

    def progress_hook(self, data: dict):
        if self._cancel_event.is_set():
            raise yt_dlp.utils.DownloadCancelled("Cancelled by user")

        status = data.get("status")
        if status == "downloading":
            total      = data.get("total_bytes") or data.get("total_bytes_estimate")
            downloaded = data.get("downloaded_bytes", 0)
            percent    = max(0, min(100, downloaded / total * 100)) if total else 0
            self.events.put((
                "progress",
                percent,
                self.format_speed(data.get("speed")),
                self.format_eta(data.get("eta")),
            ))
        elif status == "finished":
            self.events.put(("progress", 100, "", "Processing…"))

                                                                
                          
                                                                

    def _set_buttons_downloading(self):
        self.download_button.configure(state="disabled")
        self.start_queue_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.clear_button.configure(state="disabled")

    def _reset_ui_after_download(self):
        self.downloading = False
        self.download_button.configure(state="normal")
        self.start_queue_button.configure(state="normal")
        self.cancel_button.configure(state="disabled")
        self.clear_button.configure(state="normal")
        self.preview_button.configure(state="normal")
        self.paste_button.configure(state="normal")

                                                                
                
                                                                

    def process_events(self):
        try:
            while True:
                event = self.events.get_nowait()
                kind  = event[0]

                if kind == "progress":
                    _, percent, speed, eta = event
                    self.progress_var.set(percent)
                    self.percent_label.configure(text=f"{percent:.0f}%")
                    self.speed_var.set(speed)
                    self.eta_var.set(eta)

                elif kind == "title":
                    self.title_var.set(event[1])

                elif kind == "detail":
                    self.detail_var.set(event[1])

                elif kind == "status":
                    self.status_var.set(event[1])

                elif kind == "preview":
                    _, title, detail, thumbnail_url, thumbnail_bytes = event
                    self.title_var.set(title)
                    self.detail_var.set(detail)
                    self.status_var.set("Preview ready yaa~")
                    self.preview_state_label.configure(
                        text="Thumbnail ready yaa~" if thumbnail_url else "No thumbnail",
                        fg=COLORS["accent"] if thumbnail_url else COLORS["muted"],
                    )
                    self.current_thumbnail_url   = thumbnail_url
                    self.current_thumbnail_bytes = thumbnail_bytes
                    if thumbnail_bytes:
                        self.render_thumbnail(thumbnail_bytes)
                    else:
                        self.thumbnail_label.configure(
                            image="", text="▶", fg=COLORS["muted"], bg="#303744",
                        )
                    self.preview_button.configure(state="normal")
                    self.paste_button.configure(state="normal")

                elif kind == "preview_error":
                    self.preview_button.configure(state="normal")
                    self.paste_button.configure(state="normal")
                    self.status_var.set("Preview failed.")
                    self.preview_state_label.configure(
                        text="Preview failed", fg=COLORS["danger"],
                    )
                    messagebox.showerror("Preview failed", event[1])

                elif kind == "thumbnail_url":
                                                                              
                    url = event[1]
                    if url and self.current_thumbnail_bytes is None:
                        threading.Thread(
                            target=self._fetch_render_thumb_bg,
                            args=(url,), daemon=True,
                        ).start()

                elif kind == "render_thumbnail":
                    self.render_thumbnail(event[1])

                                                                

                elif kind == "thumbnail_mode_done":
                    self._reset_ui_after_download()
                    self.progress_var.set(100)
                    self.percent_label.configure(text="100%")
                    self.status_var.set("Thumbnail saved yaa~")
                    self.speed_var.set("")
                    self.eta_var.set("")
                    self.refresh_queue_ui()
                    messagebox.showinfo(
                        "Thumbnail saved yaa~",
                        f"Thumbnail berhasil disimpan di:\n{event[1]}",
                    )

                elif kind == "done":
                    self._reset_ui_after_download()
                    self.status_var.set(event[1])
                    self.on_mode_change()
                    self.progress_var.set(100)
                    self.percent_label.configure(text="100%")
                    self.speed_var.set("")
                    self.eta_var.set("")
                    self.refresh_queue_ui()
                    messagebox.showinfo("Selesai yaa~", event[1])

                elif kind == "error":
                    self._reset_ui_after_download()
                    self.status_var.set("Download gagal.")
                    self.on_mode_change()
                    self.speed_var.set("")
                    self.eta_var.set("")
                    self.refresh_queue_ui()
                    messagebox.showerror("Download gagal", event[1])

                elif kind == "cancelled":
                    self._reset_ui_after_download()
                    self.progress_var.set(0)
                    self.percent_label.configure(text="0%")
                    self.speed_var.set("")
                    self.eta_var.set("")
                    self.status_var.set("Download dibatalkan.")
                    self.on_mode_change()
                    self.refresh_queue_ui()

                                                               

                elif kind == "queue_item_done":
                    item = event[1]
                    self._reset_ui_after_download()
                    self.progress_var.set(100)
                    self.percent_label.configure(text="100%")
                    self.speed_var.set("")
                    self.eta_var.set("")
                    self.refresh_queue_ui()
                    short = item.title[:45] + "…" if len(item.title) > 45 else item.title
                    self.status_var.set(f"✓  '{short}' selesai!")
                    if self.queue_processing:
                        self.root.after(400, self._process_next_queue_item)

                elif kind == "queue_item_error":
                    item = event[1]
                    self._reset_ui_after_download()
                    self.speed_var.set("")
                    self.eta_var.set("")
                    self.refresh_queue_ui()
                    messagebox.showerror(
                        "Queue item gagal",
                        f"{item.title or item.url}\n\n{item.error_msg}",
                    )
                    if self.queue_processing:
                        self.root.after(400, self._process_next_queue_item)

                elif kind == "queue_item_cancelled":
                    self._reset_ui_after_download()
                    self.speed_var.set("")
                    self.eta_var.set("")
                    self.status_var.set("Queue item dibatalkan.")
                    self.queue_processing = False
                    self.refresh_queue_ui()

                elif kind == "queue_finished":
                    self.queue_processing = False
                    self.status_var.set("✓  Semua queue selesai!")
                    self.refresh_queue_ui()
                    messagebox.showinfo(
                        "Queue selesai!",
                        "Semua item di queue sudah selesai didownload.",
                    )

                                                                

                elif kind == "bg_ready":
                    _, pil_image, target_size = event
                    try:
                        self.bg_photo    = ImageTk.PhotoImage(pil_image)
                        self.bg_last_size = target_size
                        self.canvas.delete("background")
                        self.canvas.create_image(
                            0, 0, image=self.bg_photo,
                            anchor="nw", tags="background",
                        )
                        self.canvas.tag_lower("background")
                    except Exception as exc:
                        logger.error("Canvas bg update failed: %s", exc)
                    finally:
                        self._bg_rendering = False

        except _queue.Empty:
            pass

        self.root.after(100, self.process_events)

    def _fetch_render_thumb_bg(self, url: str):
        try:
            data = self.fetch_thumbnail_bytes(url)
            self.current_thumbnail_bytes = data
            self.events.put(("render_thumbnail", data))
        except Exception:
            pass

                                                                
                      
                                                                

    @staticmethod
    def format_speed(bps) -> str:
        if not bps:
            return "0 KB/s"
        v = float(bps)
        for unit in ("B/s", "KB/s", "MB/s", "GB/s"):
            if v < 1024:
                return f"{v:.2f} {unit}"
            v /= 1024
        return f"{v:.2f} TB/s"

    @staticmethod
    def format_eta(seconds) -> str:
        if seconds is None:
            return "ETA: -"
        try:
            seconds = max(0, int(seconds))
        except (TypeError, ValueError):
            return "ETA: -"
        h, r = divmod(seconds, 3600)
        m, s = divmod(r, 60)
        if h:
            return f"ETA: {h}:{m:02d}:{s:02d}"
        return f"ETA: {m:02d}:{s:02d}"

    @staticmethod
    def format_duration(seconds) -> str:
        if seconds is None:
            return "-"
        try:
            seconds = int(seconds)
        except (TypeError, ValueError):
            return "-"
        h, r = divmod(seconds, 3600)
        m, s = divmod(r, 60)
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"


                                                               
             
                                                               

def main():
                                                                        
    if DND_AVAILABLE:
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()
    app  = YouTubeDownloaderApp(root)

    def close_app():
                                  
        if app._clipboard_after is not None:
            try:
                root.after_cancel(app._clipboard_after)
            except tk.TclError:
                pass
                              
        if app.resize_job is not None:
            try:
                root.after_cancel(app.resize_job)
            except tk.TclError:
                pass
                              
        try:
            if app.panel_window and app.panel_window.winfo_exists():
                app.panel_window.destroy()
        except (tk.TclError, AttributeError):
            pass
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", close_app)
    root.mainloop()


if __name__ == "__main__":
    main()
