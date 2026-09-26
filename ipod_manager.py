#!/usr/bin/env python3
"""
iPod Mini Manager - A Far Manager-style TUI for managing iPod mini without iTunes.

Features:
  - Dual-pane browser (local ↔ iPod)
  - Multi-select with Space (Far Manager style)
  - Bulk copy selected files to iPod
  - Playlist create / rename / delete
  - Add / remove tracks from playlists
  - Pure-Python iTunesDB read/write (no libgpod needed)

Dependencies:
    pip install textual mutagen
"""

import os, sys, shutil, struct, time, random, string
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

# ── Audio metadata ────────────────────────────────────────────────────────────
try:
    from mutagen import File as MutagenFile
    HAS_MUTAGEN = True
except ImportError:
    HAS_MUTAGEN = False

# ── TUI ───────────────────────────────────────────────────────────────────────
from textual.app import App, ComposeResult
from textual.widgets import (
    Header, Footer, DataTable, Label, Static,
    ProgressBar, Input, Button, Select, ListView, ListItem,
)
from textual.containers import Horizontal, Vertical, Container, ScrollableContainer
from textual.screen import ModalScreen
from textual.binding import Binding
from textual import work
from textual.reactive import reactive
from rich.text import Text


# ─────────────────────────────────────────────────────────────────────────────
#  Data model
# ─────────────────────────────────────────────────────────────────────────────

AUDIO_EXTENSIONS = {'.mp3', '.m4a', '.aac', '.aiff', '.aif', '.wav', '.m4b', '.m4p'}
IPOD_MUSIC_DIR   = "iPod_Control/Music"
IPOD_DB_PATH     = "iPod_Control/iTunes/iTunesDB"
IPOD_CDB_PATH    = "iPod_Control/iTunes/iTunesCDB"   # newer iPods use this name

# Sentinel value used as the left-pane path when showing the Windows drive list
_DRIVES_ROOT = "__DRIVES__"


def _list_windows_drives() -> list[str]:
    """Return available drive letters on Windows, e.g. ['C:\\', 'D:\\', 'F:\\']."""
    drives = []
    if sys.platform == "win32":
        import ctypes
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        for i, letter in enumerate(string.ascii_uppercase):
            if bitmask & (1 << i):
                drives.append(f"{letter}:\\")
    return drives


@dataclass
class Track:
    title:    str = "Unknown"
    artist:   str = "Unknown"
    album:    str = "Unknown"
    genre:    str = ""
    duration: int = 0       # seconds
    size:     int = 0       # bytes
    path:     str = ""      # iPod-relative (colon-separated) or local abs path
    ext:      str = ".mp3"
    dbid:     int = 0       # unique id in iTunesDB


@dataclass
class Playlist:
    name:     str        = "New Playlist"
    pid:      int        = 0            # unique id
    is_master: bool      = False
    track_ids: list[int] = field(default_factory=list)   # list of Track.dbid


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _read_metadata(filepath: str) -> Track:
    t = Track(path=filepath, ext=Path(filepath).suffix.lower())
    t.size = os.path.getsize(filepath)
    if not HAS_MUTAGEN:
        t.title = Path(filepath).stem
        return t
    try:
        audio = MutagenFile(filepath, easy=True)
        if audio is None:
            t.title = Path(filepath).stem
            return t
        t.title  = str(audio.get("title",  [Path(filepath).stem])[0])
        t.artist = str(audio.get("artist", ["Unknown"])[0])
        t.album  = str(audio.get("album",  ["Unknown"])[0])
        t.genre  = str(audio.get("genre",  [""])[0])
        if hasattr(audio, "info") and hasattr(audio.info, "length"):
            t.duration = int(audio.info.length)
    except Exception:
        t.title = Path(filepath).stem
    return t


def _fmt_duration(secs: int) -> str:
    m, s = divmod(secs, 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _fmt_size(b: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} TB"


def _new_id() -> int:
    return int(time.time() * 1000) ^ random.randint(0, 0xFFFFFF)


# ─────────────────────────────────────────────────────────────────────────────
#  iTunesDB  (pure-Python binary reader / writer)
# ─────────────────────────────────────────────────────────────────────────────
# Spec: https://www.ipodlinux.org/ITunesDB/
#
#  mhbd ─┬─ mhsd(1) ── mhlt ── mhit* ── mhod*   (track list)
#         └─ mhsd(2) ── mhlp ── mhyp* ── mhod+mhip*  (playlists)

def _le32(d, o):  return struct.unpack_from("<I", d, o)[0]
def _le64(d, o):  return struct.unpack_from("<Q", d, o)[0]
def _p32(v):      return struct.pack("<I", v)
def _p64(v):      return struct.pack("<Q", v)


class IpodDB:
    def __init__(self, mount: str):
        self.mount      = Path(mount)
        self.tracks:    list[Track]    = []
        self.playlists: list[Playlist] = []
        # Prefer iTunesCDB (newer iPods) over iTunesDB, fall back to iTunesDB
        cdb = self.mount / IPOD_CDB_PATH
        idb = self.mount / IPOD_DB_PATH
        self._db_path   = cdb if cdb.exists() else idb
        self._music_dir = self.mount / IPOD_MUSIC_DIR

    # ── public API ────────────────────────────────────────────────────────────

    def load(self):
        self.tracks = []
        self.playlists = []
        if not self._db_path.exists():
            # Fresh iPod with no database yet — that is fine, start empty
            self._ensure_master_playlist()
            return
        try:
            data = self._db_path.read_bytes()
            self._parse(data)
        except Exception as e:
            # Corrupt or unrecognised DB — start fresh rather than crashing
            self.tracks = []
            self.playlists = []
        self._ensure_master_playlist()

    def _ensure_master_playlist(self):
        if not any(p.is_master for p in self.playlists):
            master = Playlist(name="Library", pid=_new_id(), is_master=True,
                              track_ids=[t.dbid for t in self.tracks])
            self.playlists.insert(0, master)
        else:
            # Sync master with actual track list
            master = next(p for p in self.playlists if p.is_master)
            existing = set(master.track_ids)
            for t in self.tracks:
                if t.dbid not in existing:
                    master.track_ids.append(t.dbid)

    def save(self):
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path.write_bytes(self._build())

    def add_track(self, src_path: str, progress_cb=None) -> Track:
        """Copy audio file to iPod; register in tracks + master playlist."""
        self._music_dir.mkdir(parents=True, exist_ok=True)
        subdir = self._music_dir / f"F{random.randint(0,49):02d}"
        subdir.mkdir(exist_ok=True)
        ext       = Path(src_path).suffix
        dest_name = ''.join(random.choices(string.ascii_uppercase, k=8)) + ext
        dest_path = subdir / dest_name

        src_size = os.path.getsize(src_path)
        copied   = 0
        with open(src_path, "rb") as fin, open(dest_path, "wb") as fout:
            while chunk := fin.read(65536):
                fout.write(chunk)
                copied += len(chunk)
                if progress_cb:
                    progress_cb(copied, src_size)

        track       = _read_metadata(src_path)
        rel         = dest_path.relative_to(self.mount)
        track.path  = ":" + str(rel).replace("/", ":")
        track.size  = src_size
        track.dbid  = _new_id()
        self.tracks.append(track)

        # Add to master playlist
        master = next((p for p in self.playlists if p.is_master), None)
        if master:
            master.track_ids.append(track.dbid)
        return track

    def remove_track(self, track: Track):
        rel  = track.path.lstrip(":").replace(":", "/")
        full = self.mount / rel
        try:
            full.unlink(missing_ok=True)
        except Exception:
            pass
        self.tracks = [t for t in self.tracks if t.dbid != track.dbid]
        # Remove from all playlists
        for pl in self.playlists:
            pl.track_ids = [tid for tid in pl.track_ids if tid != track.dbid]

    # ── Playlist operations ───────────────────────────────────────────────────

    def create_playlist(self, name: str) -> Playlist:
        pl = Playlist(name=name, pid=_new_id())
        self.playlists.append(pl)
        return pl

    def rename_playlist(self, pl: Playlist, name: str):
        pl.name = name

    def delete_playlist(self, pl: Playlist):
        if pl.is_master:
            raise ValueError("Cannot delete the master Library playlist.")
        self.playlists = [p for p in self.playlists if p.pid != pl.pid]

    def add_to_playlist(self, pl: Playlist, track: Track):
        if track.dbid not in pl.track_ids:
            pl.track_ids.append(track.dbid)

    def remove_from_playlist(self, pl: Playlist, track: Track):
        pl.track_ids = [tid for tid in pl.track_ids if tid != track.dbid]

    def tracks_in_playlist(self, pl: Playlist) -> list[Track]:
        by_id = {t.dbid: t for t in self.tracks}
        return [by_id[tid] for tid in pl.track_ids if tid in by_id]

    # ── Parser ────────────────────────────────────────────────────────────────

    def _parse(self, data: bytes):
        if data[:4] != b"mhbd":
            return
        hdr_len = _le32(data, 4)
        pos     = hdr_len
        while pos < len(data) - 8:
            tag = data[pos:pos+4]
            if tag != b"mhsd":
                break
            sd_hdr = _le32(data, pos+4)
            sd_tot = _le32(data, pos+8)
            sd_typ = _le32(data, pos+12)
            if sd_typ == 1:
                self._parse_mhlt(data, pos + sd_hdr)
            elif sd_typ == 2:
                self._parse_mhlp(data, pos + sd_hdr)
            pos += sd_tot

    def _parse_mhlt(self, data: bytes, pos: int):
        if data[pos:pos+4] != b"mhlt":
            return
        hdr   = _le32(data, pos+4)
        count = _le32(data, pos+8)
        pos  += hdr
        for _ in range(count):
            if pos >= len(data)-8 or data[pos:pos+4] != b"mhit":
                break
            item_hdr  = _le32(data, pos+4)
            item_tot  = _le32(data, pos+8)
            num_mhod  = _le32(data, pos+12)
            dbid      = _le64(data, pos+16) if len(data) > pos+24 else 0
            duration  = _le32(data, pos+24) if len(data) > pos+28 else 0
            track     = Track(duration=duration//1000, dbid=int(dbid))
            mhod_pos  = pos + item_hdr
            for _ in range(num_mhod):
                mhod_pos = self._parse_mhod_str(data, mhod_pos, track)
            self.tracks.append(track)
            pos += item_tot

    def _parse_mhod_str(self, data: bytes, pos: int, track: Track) -> int:
        if pos >= len(data)-8 or data[pos:pos+4] != b"mhod":
            return pos+1
        hdr = _le32(data, pos+4)
        tot = _le32(data, pos+8)
        typ = _le32(data, pos+12)
        if typ in (1, 2, 3, 4, 6) and hdr <= tot:
            str_off = pos + 40
            str_len = _le32(data, pos+28) if pos+32 <= len(data) else 0
            enc     = _le32(data, pos+32) if pos+36 <= len(data) else 0
            if str_off + str_len <= len(data):
                raw = data[str_off:str_off+str_len]
                try:
                    s = raw.decode("utf-16-le") if enc == 0 else raw.decode("utf-8", errors="replace")
                except Exception:
                    s = ""
                if   typ == 1: track.title  = s
                elif typ == 2: track.path   = s
                elif typ == 3: track.album  = s
                elif typ == 4: track.artist = s
                elif typ == 6: track.genre  = s
        return pos + tot

    def _parse_mhlp(self, data: bytes, pos: int):
        if data[pos:pos+4] != b"mhlp":
            return
        hdr   = _le32(data, pos+4)
        count = _le32(data, pos+8)
        pos  += hdr
        for _ in range(count):
            if pos >= len(data)-8 or data[pos:pos+4] != b"mhyp":
                break
            yp_hdr    = _le32(data, pos+4)
            yp_tot    = _le32(data, pos+8)
            num_child = _le32(data, pos+12)
            is_master = bool(_le32(data, pos+20) if pos+24 <= len(data) else 0)
            pl        = Playlist(pid=_new_id(), is_master=is_master)
            child_pos = pos + yp_hdr
            for _ in range(num_child):
                if child_pos >= len(data)-8:
                    break
                ctag = data[child_pos:child_pos+4]
                if ctag == b"mhod":
                    c_hdr = _le32(data, child_pos+4)
                    c_tot = _le32(data, child_pos+8)
                    c_typ = _le32(data, child_pos+12)
                    if c_typ == 1:   # playlist name
                        str_off = child_pos + 40
                        str_len = _le32(data, child_pos+28) if child_pos+32 <= len(data) else 0
                        enc     = _le32(data, child_pos+32) if child_pos+36 <= len(data) else 0
                        if str_off + str_len <= len(data):
                            raw = data[str_off:str_off+str_len]
                            try:
                                pl.name = raw.decode("utf-16-le") if enc == 0 else raw.decode("utf-8", errors="replace")
                            except Exception:
                                pass
                    child_pos += c_tot
                elif ctag == b"mhip":
                    ip_hdr = _le32(data, child_pos+4)
                    ip_tot = _le32(data, child_pos+8)
                    # dbid of referenced track at offset 16 in mhip
                    ref_dbid = _le64(data, child_pos+16) if child_pos+24 <= len(data) else 0
                    if ref_dbid:
                        pl.track_ids.append(int(ref_dbid))
                    child_pos += ip_tot
                else:
                    break
            self.playlists.append(pl)
            pos += yp_tot

    # ── Builder ───────────────────────────────────────────────────────────────

    def _build(self) -> bytes:
        mhsd1 = self._wrap_mhsd(self._build_mhlt(), typ=1)
        mhsd2 = self._wrap_mhsd(self._build_mhlp(), typ=2)
        body  = mhsd1 + mhsd2
        hdr   = (b"mhbd" + _p32(104) + _p32(104+len(body)) + _p32(1)
                 + _p32(len(self.tracks)) + _p32(2)
                 + b"\x13\x00\x00\x00" + b"\x00"*80)
        return hdr + body

    def _wrap_mhsd(self, content: bytes, typ: int) -> bytes:
        return (b"mhsd" + _p32(96) + _p32(96+len(content))
                + _p32(typ) + b"\x00"*80) + content

    def _build_mhlt(self) -> bytes:
        items = b"".join(self._build_mhit(t) for t in self.tracks)
        return (b"mhlt" + _p32(92) + _p32(92+len(items))
                + _p32(len(self.tracks)) + b"\x00"*80) + items

    def _build_mhit(self, t: Track) -> bytes:
        mhods = (self._build_mhod(1, t.title) + self._build_mhod(2, t.path)
                 + self._build_mhod(3, t.album) + self._build_mhod(4, t.artist)
                 + self._build_mhod(6, t.genre))
        hdr = (b"mhit" + _p32(156) + _p32(156+len(mhods)) + _p32(5)
               + _p64(t.dbid) + _p32(t.duration*1000) + _p32(t.size)
               + b"\x00"*(156-4*6-8))
        return hdr + mhods

    def _build_mhod(self, typ: int, value: str) -> bytes:
        enc     = value.encode("utf-16-le")
        payload = _p32(0) + _p32(len(enc)) + _p32(0) + _p32(0) + enc
        total   = 40 + len(payload)
        return (b"mhod" + _p32(24) + _p32(total) + _p32(typ) + b"\x00"*12) + payload

    def _build_mhlp(self) -> bytes:
        playlists_bytes = b"".join(self._build_mhyp(pl) for pl in self.playlists)
        return (b"mhlp" + _p32(92) + _p32(92+len(playlists_bytes))
                + _p32(len(self.playlists)) + b"\x00"*80) + playlists_bytes

    def _build_mhyp(self, pl: Playlist) -> bytes:
        # Build mhip entries for each track in this playlist
        by_dbid = {t.dbid: i for i, t in enumerate(self.tracks)}
        mhips   = b""
        valid_ids = []
        for tid in pl.track_ids:
            if tid in by_dbid:
                idx   = by_dbid[tid]
                mhip  = (b"mhip" + _p32(76) + _p32(76) + _p32(0)
                         + _p32(idx) + _p64(tid) + b"\x00"*(76-4*4-8))
                mhips += mhip
                valid_ids.append(tid)
        mhod_name = self._build_mhod(1, pl.name)
        num_child = 1 + len(valid_ids)   # 1 mhod + N mhip
        master_flag = 1 if pl.is_master else 0
        hdr = (b"mhyp" + _p32(108) + _p32(108+len(mhod_name)+len(mhips))
               + _p32(num_child) + _p32(len(valid_ids)) + _p32(master_flag)
               + b"\x00"*(108-4*5))
        return hdr + mhod_name + mhips


# ─────────────────────────────────────────────────────────────────────────────
#  iPod auto-discovery
# ─────────────────────────────────────────────────────────────────────────────

def find_ipod_mounts() -> list[str]:
    candidates = []
    for base in ["/media", "/mnt", "/run/media"]:
        if os.path.isdir(base):
            for entry in Path(base).rglob("iPod_Control"):
                candidates.append(str(entry.parent))
    if sys.platform == "darwin":
        for vol in Path("/Volumes").iterdir():
            if (vol / "iPod_Control").exists():
                candidates.append(str(vol))
    if sys.platform == "win32":
        import string as _s
        for drive in _s.ascii_uppercase:
            p = Path(f"{drive}:\\iPod_Control")
            if p.exists():
                candidates.append(f"{drive}:\\")
    return candidates


# ─────────────────────────────────────────────────────────────────────────────
#  CSS
# ─────────────────────────────────────────────────────────────────────────────

CSS = """
Screen { background: #1a1a2e; }

#top-bar { height: 1; background: #16213e; color: #e2e2e2; padding: 0 2; }

#panels { height: 1fr; }

.panel { width: 1fr; border: solid #0f3460; background: #16213e; }
.panel.focused { border: solid #e94560; }

.panel-title {
    background: #0f3460; color: #e2e2e2;
    text-align: center; height: 1; padding: 0 1;
}
.panel-title.active { background: #e94560; color: #ffffff; }

DataTable { background: #16213e; color: #e2e2e2; height: 1fr; }
DataTable > .datatable--header { background: #0f3460; color: #a8dadc; text-style: bold; }
DataTable > .datatable--cursor { background: #e94560; color: #ffffff; }
DataTable > .datatable--highlight { background: #533483; color: #e2e2e2; }

#status-bar { height: 1; background: #0f3460; color: #a8dadc; padding: 0 2; }

#progress-area { height: 3; background: #16213e; padding: 0 2; display: none; }
#progress-area.visible { display: block; }
ProgressBar { width: 1fr; }

/* ── Modals ── */
ConfirmScreen, InfoScreen, InputScreen, IpodMountScreen,
PlaylistScreen, TrackToPlaylistScreen { align: center middle; }

#dialog {
    background: #16213e; border: solid #e94560;
    padding: 1 2; width: 64; height: auto; max-height: 30;
}
#dialog-wide {
    background: #16213e; border: solid #e94560;
    padding: 1 2; width: 80; height: auto; max-height: 36;
}
#dialog-title { text-align: center; color: #e94560; text-style: bold; margin-bottom: 1; }
#dialog-body  { color: #e2e2e2; margin-bottom: 1; }
#dialog-buttons { align: center middle; height: auto; margin-top: 1; }

Button { margin: 0 1; background: #0f3460; color: #e2e2e2; border: solid #533483; min-width: 10; }
Button:focus { background: #e94560; color: #ffffff; }
Button.-primary { background: #e94560; }

Input { background: #0f3460; color: #e2e2e2; border: solid #533483; margin-bottom: 1; }

/* Playlist editor specifics */
#pl-left  { width: 30; border: solid #0f3460; background: #16213e; }
#pl-right { width: 1fr; border: solid #0f3460; background: #16213e; }
.pl-section-title {
    background: #0f3460; color: #a8dadc; text-align: center;
    height: 1; text-style: bold;
}
#pl-buttons { height: auto; align: center middle; margin-top: 1; }
ListView { height: 1fr; background: #16213e; }
ListItem { color: #e2e2e2; padding: 0 1; }
ListItem:hover { background: #533483; }
ListItem.--highlight { background: #e94560; color: #ffffff; }
"""


# ─────────────────────────────────────────────────────────────────────────────
#  Modal screens
# ─────────────────────────────────────────────────────────────────────────────

class ConfirmScreen(ModalScreen):
    BINDINGS = [Binding("y","yes","Yes"), Binding("n","no","No"), Binding("escape","no","")]
    def __init__(self, title, message, **kw):
        super().__init__(**kw); self._t = title; self._m = message
    def compose(self):
        with Container(id="dialog"):
            yield Label(self._t, id="dialog-title")
            yield Label(self._m, id="dialog-body")
            with Horizontal(id="dialog-buttons"):
                yield Button("Yes [Y]", id="y", variant="error")
                yield Button("No [N]",  id="n")
    def on_button_pressed(self, e): self.dismiss(e.button.id == "y")
    def action_yes(self): self.dismiss(True)
    def action_no(self):  self.dismiss(False)


class InfoScreen(ModalScreen):
    BINDINGS = [Binding("escape,enter,space","close","")]
    def __init__(self, title, message, **kw):
        super().__init__(**kw); self._t = title; self._m = message
    def compose(self):
        with Container(id="dialog"):
            yield Label(self._t, id="dialog-title")
            yield Label(self._m, id="dialog-body")
            with Horizontal(id="dialog-buttons"):
                yield Button("OK", id="ok", variant="primary")
    def on_button_pressed(self, _): self.dismiss(None)
    def action_close(self): self.dismiss(None)


class InputScreen(ModalScreen):
    """Single-line text input dialog; dismisses with the string or None."""
    BINDINGS = [Binding("escape","cancel","")]
    def __init__(self, title, placeholder="", default="", **kw):
        super().__init__(**kw)
        self._t = title; self._ph = placeholder; self._def = default
    def compose(self):
        with Container(id="dialog"):
            yield Label(self._t, id="dialog-title")
            yield Input(value=self._def, placeholder=self._ph, id="inp")
            with Horizontal(id="dialog-buttons"):
                yield Button("OK",     id="ok",  variant="primary")
                yield Button("Cancel", id="can")
    def on_button_pressed(self, e):
        if e.button.id == "ok":
            self.dismiss(self.query_one("#inp", Input).value.strip() or None)
        else:
            self.dismiss(None)
    def action_cancel(self): self.dismiss(None)


class IpodMountScreen(ModalScreen):
    BINDINGS = [Binding("escape","cancel","Cancel")]

    def __init__(self, mounts, **kw):
        super().__init__(**kw); self._mounts = mounts

    def compose(self):
        with Container(id="dialog"):
            yield Label("Connect iPod", id="dialog-title")
            if self._mounts:
                yield Label("Detected devices (click or Enter):", id="dialog-body")
                for m in self._mounts:
                    yield Button(m, classes="mount-btn")
            else:
                yield Label("No iPod detected. Enter path manually:", id="dialog-body")
            yield Input(placeholder="/media/user/iPod  or  D:\\", id="manual")
            with Horizontal(id="dialog-buttons"):
                yield Button("Connect", id="conn", variant="primary")
                yield Button("Cancel",  id="can")

    def on_mount(self):
        # Focus first device button so Enter works immediately
        btns = self.query(".mount-btn")
        if btns:
            list(btns)[0].focus()
        else:
            self.query_one("#manual", Input).focus()

    def on_button_pressed(self, e):
        if "mount-btn" in e.button.classes:
            self.dismiss(str(e.button.label))
        elif e.button.id == "conn":
            v = self.query_one("#manual", Input).value.strip()
            self.dismiss(v if v else (self._mounts[0] if self._mounts else None))
        else:
            self.dismiss(None)

    def action_cancel(self): self.dismiss(None)


# ─────────────────────────────────────────────────────────────────────────────
#  Playlist editor screen
# ─────────────────────────────────────────────────────────────────────────────

class PlaylistScreen(ModalScreen):
    """
    Full-screen playlist editor.

    Left pane  : playlist list  (N = new, R = rename, D = delete)
    Right pane : tracks in selected playlist  (Del = remove from playlist)
    Bottom bar : F5 = add tracks from library to playlist
    """

    BINDINGS = [
        Binding("escape,f6", "close",           "Close"),
        Binding("n",         "new_playlist",     "N New"),
        Binding("r",         "rename_playlist",  "R Rename"),
        Binding("d",         "delete_playlist",  "D Delete"),
        Binding("f5",        "add_tracks",       "F5 Add tracks"),
        Binding("delete",    "remove_track",     "Del Remove track"),
        Binding("tab",       "switch_focus",     "Tab Switch"),
    ]

    def __init__(self, db: IpodDB, **kw):
        super().__init__(**kw)
        self.db            = db
        self._pl_focus     = True          # True=left(playlist list), False=right(track list)
        self._selected_pl: Optional[Playlist] = None

    def compose(self) -> ComposeResult:
        with Container(id="dialog-wide"):
            yield Label("🎵 Playlist Editor", id="dialog-title")
            with Horizontal():
                with Vertical(id="pl-left"):
                    yield Label("Playlists  [N]ew [R]ename [D]el", classes="pl-section-title")
                    yield ListView(id="pl-list")
                with Vertical(id="pl-right"):
                    yield Label("Tracks in playlist  [F5] Add  [Del] Remove", classes="pl-section-title")
                    yield DataTable(id="pl-track-table", cursor_type="row", zebra_stripes=True)
            with Horizontal(id="pl-buttons"):
                yield Button("F5 Add tracks", id="btn-add",    variant="primary")
                yield Button("Del Remove",    id="btn-remove")
                yield Button("N New PL",      id="btn-new")
                yield Button("R Rename",      id="btn-rename")
                yield Button("D Delete PL",   id="btn-del-pl", variant="error")
                yield Button("Esc Close",     id="btn-close")

    def on_mount(self):
        t = self.query_one("#pl-track-table", DataTable)
        t.add_columns("Title", "Artist", "Album", "Dur")
        self._refresh_pl_list()
        if self.db.playlists:
            self._select_playlist(self.db.playlists[0])

    # ── playlist list ─────────────────────────────────────────────────────────

    def _refresh_pl_list(self):
        lv = self.query_one("#pl-list", ListView)
        lv.clear()
        for pl in self.db.playlists:
            star = " ★" if pl.is_master else ""
            lv.append(ListItem(Label(f"{pl.name}{star}  ({len(pl.track_ids)})")))

    def _select_playlist(self, pl: Playlist):
        self._selected_pl = pl
        self._refresh_track_table()

    def _refresh_track_table(self):
        t = self.query_one("#pl-track-table", DataTable)
        t.clear()
        if not self._selected_pl:
            return
        for track in self.db.tracks_in_playlist(self._selected_pl):
            t.add_row(track.title, track.artist, track.album,
                      _fmt_duration(track.duration), key=str(track.dbid))

    def on_list_view_selected(self, event: ListView.Selected):
        idx = self.query_one("#pl-list", ListView).index
        if idx is not None and 0 <= idx < len(self.db.playlists):
            self._select_playlist(self.db.playlists[idx])

    # ── actions ───────────────────────────────────────────────────────────────

    def action_close(self): self.dismiss(None)

    def action_switch_focus(self):
        self._pl_focus = not self._pl_focus
        if self._pl_focus:
            self.query_one("#pl-list", ListView).focus()
        else:
            self.query_one("#pl-track-table", DataTable).focus()

    def action_new_playlist(self):
        self.app.push_screen(InputScreen("New Playlist", placeholder="Playlist name"), self._on_new_pl)

    def _on_new_pl(self, name: Optional[str]):
        if name:
            pl = self.db.create_playlist(name)
            self._refresh_pl_list()
            self._select_playlist(pl)

    def action_rename_playlist(self):
        if not self._selected_pl or self._selected_pl.is_master:
            self.app.push_screen(InfoScreen("Rename", "Cannot rename the master Library."))
            return
        self.app.push_screen(
            InputScreen("Rename Playlist", default=self._selected_pl.name),
            self._on_rename_pl
        )

    def _on_rename_pl(self, name: Optional[str]):
        if name and self._selected_pl:
            self.db.rename_playlist(self._selected_pl, name)
            self._refresh_pl_list()

    def action_delete_playlist(self):
        if not self._selected_pl:
            return
        if self._selected_pl.is_master:
            self.app.push_screen(InfoScreen("Delete", "Cannot delete the master Library."))
            return
        self.app.push_screen(
            ConfirmScreen("Delete Playlist", f"Delete playlist '{self._selected_pl.name}'?\n(Tracks stay on iPod)"),
            self._on_delete_pl
        )

    def _on_delete_pl(self, ok: bool):
        if ok and self._selected_pl:
            self.db.delete_playlist(self._selected_pl)
            self._selected_pl = None
            self._refresh_pl_list()
            self._refresh_track_table()
            if self.db.playlists:
                self._select_playlist(self.db.playlists[0])

    def action_add_tracks(self):
        if not self._selected_pl:
            self.app.push_screen(InfoScreen("Add Tracks", "Select a playlist first."))
            return
        self.app.push_screen(TrackToPlaylistScreen(self.db, self._selected_pl), self._on_tracks_added)

    def _on_tracks_added(self, _):
        self._refresh_pl_list()
        self._refresh_track_table()

    def action_remove_track(self):
        if not self._selected_pl:
            return
        t = self.query_one("#pl-track-table", DataTable)
        if t.cursor_row < 0:
            return
        rk = t.coordinate_to_cell_key((t.cursor_row, 0)).row_key.value
        track = next((tr for tr in self.db.tracks if str(tr.dbid) == rk), None)
        if track:
            self.db.remove_from_playlist(self._selected_pl, track)
            self._refresh_pl_list()
            self._refresh_track_table()

    def on_button_pressed(self, event: Button.Pressed):
        actions = {
            "btn-add":    self.action_add_tracks,
            "btn-remove": self.action_remove_track,
            "btn-new":    self.action_new_playlist,
            "btn-rename": self.action_rename_playlist,
            "btn-del-pl": self.action_delete_playlist,
            "btn-close":  self.action_close,
        }
        fn = actions.get(event.button.id)
        if fn: fn()


# ─────────────────────────────────────────────────────────────────────────────
#  Track picker: add tracks from library to a playlist
# ─────────────────────────────────────────────────────────────────────────────

class TrackToPlaylistScreen(ModalScreen):
    """Shows all library tracks; Space toggles selection; Enter/OK adds them."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("space",  "toggle_select", "Space Select"),
        Binding("a",      "select_all",    "A All"),
    ]

    def __init__(self, db: IpodDB, playlist: Playlist, **kw):
        super().__init__(**kw)
        self.db         = db
        self.playlist   = playlist
        self._selected: set[int] = set()   # selected dbids

    def compose(self) -> ComposeResult:
        with Container(id="dialog-wide"):
            yield Label(f"Add tracks → '{self.playlist.name}'  [Space]=select  [A]=all",
                        id="dialog-title")
            yield Label("★ = already in playlist", id="dialog-body")
            yield DataTable(id="pick-table", cursor_type="row", zebra_stripes=True)
            with Horizontal(id="dialog-buttons"):
                yield Button("Add selected", id="btn-add", variant="primary")
                yield Button("Cancel",       id="btn-can")

    def on_mount(self):
        t = self.query_one("#pick-table", DataTable)
        t.add_columns("", "Title", "Artist", "Album", "Dur")
        self._refresh()
        t.focus()

    def _refresh(self):
        t = self.query_one("#pick-table", DataTable)
        t.clear()
        in_pl = set(self.playlist.track_ids)
        for track in self.db.tracks:
            star   = "★" if track.dbid in in_pl else " "
            check  = Text("✓", style="bold green") if track.dbid in self._selected else Text(" ")
            t.add_row(check, track.title, track.artist, track.album,
                      _fmt_duration(track.duration), key=str(track.dbid))

    def action_toggle_select(self):
        t = self.query_one("#pick-table", DataTable)
        if t.cursor_row < 0:
            return
        rk = t.coordinate_to_cell_key((t.cursor_row, 0)).row_key.value
        dbid = int(rk)
        if dbid in self._selected:
            self._selected.discard(dbid)
        else:
            self._selected.add(dbid)
        self._refresh()
        # Restore cursor row
        if t.cursor_row < t.row_count:
            t.move_cursor(row=t.cursor_row)

    def action_select_all(self):
        if len(self._selected) == len(self.db.tracks):
            self._selected.clear()
        else:
            self._selected = {tr.dbid for tr in self.db.tracks}
        self._refresh()

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "btn-add":
            by_id = {tr.dbid: tr for tr in self.db.tracks}
            for dbid in self._selected:
                if dbid in by_id:
                    self.db.add_to_playlist(self.playlist, by_id[dbid])
            self.dismiss(True)
        else:
            self.dismiss(None)

    def action_cancel(self): self.dismiss(None)


# ─────────────────────────────────────────────────────────────────────────────
#  Main App
# ─────────────────────────────────────────────────────────────────────────────

class IpodManagerApp(App):
    CSS = CSS

    BINDINGS = [
        Binding("f5",           "copy",          "F5 Copy"),
        Binding("f8,delete",    "delete_item",   "F8 Delete"),
        Binding("f2",           "save_db",       "F2 Save DB"),
        Binding("f6",           "open_playlists","F6 Playlists"),
        Binding("tab",          "switch_panel",  "Tab Switch"),
        Binding("f10,q",        "quit",          "F10 Quit"),
        Binding("f1",           "show_help",     "F1 Help"),
        Binding("f7",           "connect_ipod",  "F7 iPod"),
        Binding("r",            "refresh",       "R Refresh"),
        Binding("backspace",    "go_up",         "← Up"),
        Binding("enter",        "enter_dir",     "Enter"),
        Binding("f3",           "drive_select",  "F3 Drive"),
        Binding("space",        "toggle_select", "Spc Select"),
        Binding("ctrl+a",       "select_all",    "^A All"),
    ]

    focus_left: reactive[bool] = reactive(True)

    def __init__(self):
        super().__init__()
        self.left_path    = str(Path.home())
        self.ipod_db:     Optional[IpodDB] = None
        self.ipod_mount:  Optional[str]    = None
        # Multi-select: sets of row keys (filename for local, dbid str for iPod)
        self._local_sel:  set[str] = set()
        self._ipod_sel:   set[str] = set()

    # ── Layout ────────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Static(id="top-bar"):
            yield Label("iPod Manager │ F1:Help F2:Save F3:Drives F5:Copy F6:Playlists F7:iPod F8:Del Spc:Select F10:Quit")
        with Horizontal(id="panels"):
            with Vertical(classes="panel focused", id="left-panel"):
                yield Label("📁 Local Files", classes="panel-title active", id="left-title")
                yield DataTable(id="left-table", cursor_type="row", zebra_stripes=True)
            with Vertical(classes="panel", id="right-panel"):
                yield Label("🎵 iPod  [not connected]", classes="panel-title", id="right-title")
                yield DataTable(id="right-table", cursor_type="row", zebra_stripes=True)
        with Container(id="progress-area"):
            yield Label("", id="progress-label")
            yield ProgressBar(id="progress-bar", total=100, show_eta=False)
        yield Label("Ready – F7 to connect iPod", id="status-bar")
        yield Footer()

    def on_mount(self):
        for tid in ("left-table", "right-table"):
            t = self.query_one(f"#{tid}", DataTable)
            t.add_columns("", "Name", "Size", "Duration", "Artist", "Album")
        self._load_local(self.left_path)
        mounts = find_ipod_mounts()
        if mounts:
            self._status(f"iPod detected at {mounts[0]} – press F7 to connect.")

    # ── Local pane ────────────────────────────────────────────────────────────

    def _load_local(self, path: str):
        t = self.query_one("#left-table", DataTable)
        t.clear()
        self._local_sel.clear()

        # ── Windows drive list (virtual root) ────────────────────────────────
        if path == _DRIVES_ROOT:
            self.query_one("#left-title", Label).update("📁 [Drive list]")
            for drive in _list_windows_drives():
                t.add_row("", drive, "[DRIVE]", "", "", "")
            return

        self.query_one("#left-title", Label).update(f"📁 {path}")
        p = Path(path)
        rows = []

        # On Windows, show ".." only when not already at a drive root (e.g. C:\)
        at_drive_root = (sys.platform == "win32" and p == p.parent)
        if at_drive_root:
            rows.append(("", "[Drives]", "[DIR]", "", "", ""))   # go back to drive list
        elif p.parent != p:
            rows.append(("", "..", "[DIR]", "", "", ""))

        try:
            entries = sorted(p.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
        except PermissionError:
            self._status(f"Permission denied: {path}"); return
        for entry in entries:
            if entry.is_dir():
                rows.append(("", entry.name + "/", "[DIR]", "", "", ""))
            elif entry.suffix.lower() in AUDIO_EXTENSIONS:
                size = _fmt_size(entry.stat().st_size)
                if HAS_MUTAGEN:
                    try:
                        tr = _read_metadata(str(entry))
                        rows.append(("", entry.name, size, _fmt_duration(tr.duration), tr.artist, tr.album))
                    except Exception:
                        rows.append(("", entry.name, size, "", "", ""))
                else:
                    rows.append(("", entry.name, size, "", "", ""))
            else:
                rows.append(("", Text(entry.name, style="dim"),
                             Text(_fmt_size(entry.stat().st_size), style="dim"), "", "", ""))
        for row in rows:
            t.add_row(*row)

    # ── iPod pane ─────────────────────────────────────────────────────────────

    def _load_ipod(self):
        t = self.query_one("#right-table", DataTable)
        t.clear()
        self._ipod_sel.clear()
        if not self.ipod_db:
            return
        self.query_one("#right-title", Label).update(
            f"🎵 iPod  [{self.ipod_mount}]  {len(self.ipod_db.tracks)} tracks")
        for track in self.ipod_db.tracks:
            t.add_row("", track.title, _fmt_size(track.size),
                      _fmt_duration(track.duration), track.artist, track.album,
                      key=str(track.dbid))

    # ── Multi-select ──────────────────────────────────────────────────────────

    def action_toggle_select(self):
        """Space: toggle selection on current row (Far Manager style)."""
        if self.focus_left:
            self._toggle_local_row()
        else:
            self._toggle_ipod_row()

    def _toggle_local_row(self):
        t = self.query_one("#left-table", DataTable)
        if t.cursor_row < 0:
            return
        row  = t.get_row_at(t.cursor_row)
        name = str(row[1])   # col 1 = Name (col 0 = checkbox)
        if name in ("..", "[DIR]") or str(row[2]) == "[DIR]":
            t.move_cursor(row=t.cursor_row + 1)
            return
        if name in self._local_sel:
            self._local_sel.discard(name)
            t.update_cell_at((t.cursor_row, 0), Text(" "))
        else:
            self._local_sel.add(name)
            t.update_cell_at((t.cursor_row, 0), Text("●", style="bold yellow"))
        # Advance cursor
        if t.cursor_row + 1 < t.row_count:
            t.move_cursor(row=t.cursor_row + 1)
        self._status(f"{len(self._local_sel)} file(s) selected")

    def _toggle_ipod_row(self):
        if not self.ipod_db:
            return
        t = self.query_one("#right-table", DataTable)
        if t.cursor_row < 0:
            return
        rk = t.coordinate_to_cell_key((t.cursor_row, 0)).row_key.value
        if rk in self._ipod_sel:
            self._ipod_sel.discard(rk)
            t.update_cell_at((t.cursor_row, 0), Text(" "))
        else:
            self._ipod_sel.add(rk)
            t.update_cell_at((t.cursor_row, 0), Text("●", style="bold yellow"))
        if t.cursor_row + 1 < t.row_count:
            t.move_cursor(row=t.cursor_row + 1)
        self._status(f"{len(self._ipod_sel)} track(s) selected")

    def action_select_all(self):
        """Ctrl+A: select/deselect all audio files in active pane."""
        if self.focus_left:
            t = self.query_one("#left-table", DataTable)
            # Collect all audio rows
            audio_names = set()
            for row_i in range(t.row_count):
                row = t.get_row_at(row_i)
                name = str(row[1])
                if str(row[2]) != "[DIR]" and name != "..":
                    audio_names.add(name)
            if self._local_sel == audio_names:
                self._local_sel.clear()
            else:
                self._local_sel = audio_names
            # Redraw checkmarks
            for row_i in range(t.row_count):
                row  = t.get_row_at(row_i)
                name = str(row[1])
                mark = Text("●", style="bold yellow") if name in self._local_sel else Text(" ")
                t.update_cell_at((row_i, 0), mark)
            self._status(f"{len(self._local_sel)} file(s) selected")
        else:
            if not self.ipod_db:
                return
            t = self.query_one("#right-table", DataTable)
            all_keys = {str(tr.dbid) for tr in self.ipod_db.tracks}
            if self._ipod_sel == all_keys:
                self._ipod_sel.clear()
            else:
                self._ipod_sel = all_keys.copy()
            for row_i in range(t.row_count):
                rk   = t.coordinate_to_cell_key((row_i, 0)).row_key.value
                mark = Text("●", style="bold yellow") if rk in self._ipod_sel else Text(" ")
                t.update_cell_at((row_i, 0), mark)
            self._status(f"{len(self._ipod_sel)} track(s) selected")

    # ── Focus / panel switch ──────────────────────────────────────────────────

    def action_switch_panel(self):
        self.focus_left = not self.focus_left
        lp = self.query_one("#left-panel")
        rp = self.query_one("#right-panel")
        lt = self.query_one("#left-title")
        rt = self.query_one("#right-title")
        if self.focus_left:
            lp.add_class("focused");   rp.remove_class("focused")
            lt.add_class("active");    rt.remove_class("active")
            self.query_one("#left-table").focus()
        else:
            rp.add_class("focused");   lp.remove_class("focused")
            rt.add_class("active");    lt.remove_class("active")
            self.query_one("#right-table").focus()

    # ── Navigation ────────────────────────────────────────────────────────────

    def action_enter_dir(self):
        if not self.focus_left:
            return
        t = self.query_one("#left-table", DataTable)
        if t.cursor_row < 0:
            return
        row  = t.get_row_at(t.cursor_row)
        name = str(row[1]).rstrip("/")
        kind = str(row[2])

        if kind == "[DRIVE]":
            # Row is a drive letter like "D:\"
            self.left_path = name
            self._load_local(name)
        elif kind == "[DIR]":
            if name in ("..", "[Drives]"):
                # Go up — if already at drive root, go to drive list
                p = Path(self.left_path)
                if self.left_path == _DRIVES_ROOT or p == p.parent:
                    self.left_path = _DRIVES_ROOT
                    self._load_local(_DRIVES_ROOT)
                else:
                    new = str(p.parent)
                    self.left_path = new
                    self._load_local(new)
            else:
                new = str(Path(self.left_path) / name)
                self.left_path = new
                self._load_local(new)

    def action_go_up(self):
        if not self.focus_left:
            return
        if self.left_path == _DRIVES_ROOT:
            return   # already at top
        p = Path(self.left_path)
        if sys.platform == "win32" and p == p.parent:
            # At drive root (e.g. C:\) — go to drive list
            self.left_path = _DRIVES_ROOT
            self._load_local(_DRIVES_ROOT)
        else:
            parent = str(p.parent)
            self.left_path = parent
            self._load_local(parent)

    def action_drive_select(self):
        """F3: jump straight to the Windows drive list."""
        if sys.platform == "win32":
            self.left_path = _DRIVES_ROOT
            self._load_local(_DRIVES_ROOT)
        else:
            self._status("Drive list is Windows-only. Use Backspace to navigate up.")

    # ── iPod connect ──────────────────────────────────────────────────────────

    def action_connect_ipod(self):
        self.push_screen(IpodMountScreen(find_ipod_mounts()), self._on_ipod_selected)

    def _on_ipod_selected(self, mount: Optional[str]):
        if not mount or not Path(mount).is_dir():
            if mount:
                self.push_screen(InfoScreen("Error", f"Path not found:\n{mount}"))
            return
        self.ipod_mount = mount
        self.ipod_db    = IpodDB(mount)
        self._status(f"Loading iPod database…")
        self._bg_load_db()

    @work(thread=True)
    def _bg_load_db(self):
        try:
            self.ipod_db.load()
            self.call_from_thread(self._load_ipod)
            n = len(self.ipod_db.tracks)
            msg = (f"iPod connected: {n} tracks, {len(self.ipod_db.playlists)} playlists."
                   if n > 0 else
                   "iPod connected — no tracks yet. Use F5 to copy music, then F2 to save.")
            self.call_from_thread(self._status, msg)
        except Exception as e:
            self.call_from_thread(self._status, f"Error: {e}")

    # ── Copy (F5) — supports multi-select ────────────────────────────────────

    def action_copy(self):
        if not self.ipod_db:
            self.push_screen(InfoScreen("No iPod", "Connect an iPod first (F7).")); return
        if not self.focus_left:
            self.push_screen(InfoScreen("Info", "Switch to the left pane and select files to copy.")); return

        # Gather files: selected set, or cursor row if nothing selected
        files = []
        if self._local_sel:
            for name in sorted(self._local_sel):
                p = Path(self.left_path) / name
                if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS:
                    files.append(str(p))
        else:
            t    = self.query_one("#left-table", DataTable)
            row  = t.get_row_at(t.cursor_row) if t.cursor_row >= 0 else None
            if row:
                name = str(row[1])
                src  = Path(self.left_path) / name
                if src.is_file() and src.suffix.lower() in AUDIO_EXTENSIONS:
                    files.append(str(src))

        if not files:
            self.push_screen(InfoScreen("Copy", "No audio file(s) selected.\nUse Space to select, or move cursor to an audio file.")); return

        msg = (f"Copy {len(files)} file(s) to iPod?" if len(files) > 1
               else f"Copy to iPod?\n\n{Path(files[0]).name}")
        self.push_screen(ConfirmScreen("Copy to iPod", msg),
                         lambda ok: self._bg_copy_files(files) if ok else None)

    @work(thread=True)
    def _bg_copy_files(self, files: list[str]):
        total = len(files)
        for i, src in enumerate(files):
            name = Path(src).name
            self.call_from_thread(self._show_progress, f"[{i+1}/{total}] Copying {name}…")
            try:
                def prog(done, tot, _i=i):
                    overall = int((_i + done/tot) / total * 100) if tot else 0
                    self.call_from_thread(self._set_progress, overall)
                self.ipod_db.add_track(src, progress_cb=prog)
            except Exception as e:
                self.call_from_thread(self._status, f"Error copying {name}: {e}")
        self.call_from_thread(self._hide_progress)
        self.call_from_thread(self._load_ipod)
        self.call_from_thread(self._local_sel.clear)
        # Clear checkmarks in left table
        self.call_from_thread(self._clear_local_marks)
        self.call_from_thread(self._status,
            f"Copied {total} file(s) to iPod.  Press F2 to save database!")

    def _clear_local_marks(self):
        t = self.query_one("#left-table", DataTable)
        for row_i in range(t.row_count):
            t.update_cell_at((row_i, 0), Text(" "))

    # ── Delete (F8) ───────────────────────────────────────────────────────────

    def action_delete_item(self):
        if self.focus_left:
            t    = self.query_one("#left-table", DataTable)
            row  = t.get_row_at(t.cursor_row) if t.cursor_row >= 0 else None
            if not row: return
            name = str(row[1]).rstrip("/")
            if name == "..": return
            path = Path(self.left_path) / name
            self.push_screen(ConfirmScreen("Delete", f"Delete local file?\n\n{name}"),
                             lambda ok: self._delete_local(path) if ok else None)
        else:
            if not self.ipod_db: return
            # Delete selected tracks or cursor track
            victims = []
            if self._ipod_sel:
                by_id = {str(t.dbid): t for t in self.ipod_db.tracks}
                victims = [by_id[k] for k in self._ipod_sel if k in by_id]
            else:
                t  = self.query_one("#right-table", DataTable)
                rk = (t.coordinate_to_cell_key((t.cursor_row, 0)).row_key.value
                      if t.cursor_row >= 0 else None)
                if rk:
                    tr = next((x for x in self.ipod_db.tracks if str(x.dbid) == rk), None)
                    if tr: victims = [tr]
            if not victims: return
            msg = (f"Remove {len(victims)} track(s) from iPod?" if len(victims) > 1
                   else f"Remove from iPod?\n\n{victims[0].title}")
            self.push_screen(ConfirmScreen("Delete from iPod", msg),
                             lambda ok, v=victims: self._delete_ipod_tracks(v) if ok else None)

    def _delete_local(self, path: Path):
        try:
            path.unlink() if path.is_file() else shutil.rmtree(path)
            self._load_local(self.left_path)
            self._status(f"Deleted: {path.name}")
        except Exception as e:
            self._status(f"Delete failed: {e}")

    def _delete_ipod_tracks(self, tracks: list[Track]):
        for tr in tracks:
            self.ipod_db.remove_track(tr)
        self._ipod_sel.clear()
        self._load_ipod()
        self._status(f"Removed {len(tracks)} track(s).  Press F2 to save.")

    # ── Save DB (F2) ──────────────────────────────────────────────────────────

    def action_save_db(self):
        if not self.ipod_db:
            self.push_screen(InfoScreen("No iPod", "No iPod connected.")); return
        self.push_screen(
            ConfirmScreen("Save Database", "Write changes to iPod?\n(Updates iTunesDB + playlists)"),
            lambda ok: self._bg_save() if ok else None)

    @work(thread=True)
    def _bg_save(self):
        try:
            self.call_from_thread(self._status, "Saving iTunesDB…")
            self.ipod_db.save()
            self.call_from_thread(self._status, "✓ Database saved successfully!")
        except Exception as e:
            self.call_from_thread(self._status, f"Save failed: {e}")

    # ── Playlist editor (F6) ──────────────────────────────────────────────────

    def action_open_playlists(self):
        if not self.ipod_db:
            self.push_screen(InfoScreen("Playlists", "Connect an iPod first (F7).")); return
        self.push_screen(PlaylistScreen(self.ipod_db), lambda _: self._load_ipod())

    # ── Refresh ───────────────────────────────────────────────────────────────

    def action_refresh(self):
        self._load_local(self.left_path)
        if self.ipod_db: self._load_ipod()
        self._status("Refreshed.")

    # ── Help ─────────────────────────────────────────────────────────────────

    def action_show_help(self):
        self.push_screen(InfoScreen("Help – iPod Manager",
            "KEYBOARD SHORTCUTS\n\n"
            "Tab        – Switch panes\n"
            "Enter      – Enter directory / select drive\n"
            "Backspace  – Go up (reaches drive list on Windows)\n"
            "F3         – Jump to Windows drive list\n"
            "Space      – Toggle select (multi-select)\n"
            "Ctrl+A     – Select / deselect all audio files\n"
            "F5         – Copy selected (or cursor) to iPod\n"
            "F8 / Del   – Delete selected (or cursor) item\n"
            "F2         – Save iPod database\n"
            "F6         – Open playlist editor\n"
            "F7         – Connect / change iPod\n"
            "R          – Refresh both panes\n"
            "F10 / Q    – Quit\n\n"
            "PLAYLIST EDITOR (F6)\n\n"
            "N  – New playlist\n"
            "R  – Rename playlist\n"
            "D  – Delete playlist\n"
            "F5 – Add tracks to playlist\n"
            "Del– Remove track from playlist\n\n"
            "NOTE: Always press F2 before unplugging!"))

    # ── Progress ──────────────────────────────────────────────────────────────

    def _show_progress(self, label: str):
        self.query_one("#progress-area").add_class("visible")
        self.query_one("#progress-label", Label).update(label)
        self.query_one("#progress-bar", ProgressBar).update(progress=0)

    def _set_progress(self, pct: int):
        self.query_one("#progress-bar", ProgressBar).update(progress=pct)

    def _hide_progress(self):
        self.query_one("#progress-area").remove_class("visible")

    def _status(self, msg: str):
        self.query_one("#status-bar", Label).update(msg)

    # ── Quit ──────────────────────────────────────────────────────────────────

    def action_quit(self):
        if self.ipod_db:
            self.push_screen(ConfirmScreen("Quit", "Quit? (Unsaved changes will be lost.)"),
                             lambda ok: self.exit() if ok else None)
        else:
            self.exit()


# ─────────────────────────────────────────────────────────────────────────────

def main():
    if not HAS_MUTAGEN:
        print("[warn] mutagen not installed – metadata won't be read.")
        print("       pip install mutagen")
    IpodManagerApp().run()


if __name__ == "__main__":
    main()
