import os
import win32com.client
import tkinter as tk
from tkinter import messagebox, scrolledtext

# === Your base music folder ===
base_folder = r"D:\pierre\audio"

# === GUI setup ===
root = tk.Tk()
root.title("🎵 iTunes Playlist Manager")
root.geometry("600x500")

# === Log area ===
log_area = scrolledtext.ScrolledText(root, wrap=tk.WORD, height=20, width=70, state='disabled')
log_area.pack(padx=10, pady=10)

def log(message):
    log_area.configure(state='normal')
    log_area.insert(tk.END, message + '\n')
    log_area.yview(tk.END)
    log_area.configure(state='disabled')
    root.update_idletasks()

# === Import Music Folders ===
def import_music_folders():
    if not os.path.isdir(base_folder):
        log(f"❌ Base folder not found: {base_folder}")
        return

    log("📂 Connecting to iTunes...")
    itunes = win32com.client.Dispatch("iTunes.Application")

    music_folders = [f.path for f in os.scandir(base_folder) if f.is_dir()]
    existing_playlists = set(pl.Name.lower() for pl in itunes.LibrarySource.Playlists)

    added_total = 0

    for music_folder in music_folders:
        playlist_name = os.path.basename(os.path.normpath(music_folder))
        name_lc = playlist_name.lower()

        if name_lc in existing_playlists:
            log(f"⏭️ Playlist '{playlist_name}' already exists. Skipping.")
            continue

        log(f"🎵 Creating playlist: {playlist_name}")
        new_playlist = itunes.CreatePlaylist(playlist_name)

        mp3_files = []
        for root_dir, _, files in os.walk(music_folder):
            for file in files:
                if file.lower().endswith(".mp3"):
                    mp3_files.append(os.path.join(root_dir, file))

        if not mp3_files:
            log(f"⚠️ No MP3 files found in '{music_folder}'. Skipping.")
            continue

        mp3_files.sort(key=lambda x: x.lower())

        for file_path in mp3_files:
            new_playlist.AddFile(file_path)
            log(f"✅ Added: {os.path.basename(file_path)}")
            added_total += 1

    log(f"✅ Import complete. {added_total} tracks added.")

def delete_empty_playlists():
    itunes = win32com.client.Dispatch("iTunes.Application")
    playlists = itunes.LibrarySource.Playlists
    deleted = 0

    for i in range(playlists.Count, 0, -1):
        pl = playlists.Item(i)
        name = pl.Name
        try:
            if name.lower() == "library" or (hasattr(pl, "SpecialKind") and pl.SpecialKind != 0):
                continue
            if pl.Tracks.Count == 0:
                log(f"🗑️ Deleting empty playlist: {name}")
                pl.Delete()
                deleted += 1
        except Exception as e:
            log(f"⚠️ Error on playlist '{name}': {e}")

    log(f"\n✅ {deleted} empty playlists deleted.")

# === Delete Orphaned Playlists ===
def delete_orphaned_playlists():
    if not os.path.isdir(base_folder):
        log(f"❌ Base folder not found: {base_folder}")
        return

    valid_folder_names = {
        os.path.basename(f.path).lower()
        for f in os.scandir(base_folder)
        if f.is_dir()
    }

    itunes = win32com.client.Dispatch("iTunes.Application")
    playlists = itunes.LibrarySource.Playlists
    deleted = 0

    for i in range(playlists.Count, 0, -1):
        pl = playlists.Item(i)
        name = pl.Name
        name_lc = name.lower()
        try:
            if name_lc == "library" or (hasattr(pl, "SpecialKind") and pl.SpecialKind != 0):
                continue
            if name_lc not in valid_folder_names:
                log(f"🗑️ Deleting orphaned playlist: {name}")
                pl.Delete()
                deleted += 1
        except Exception as e:
            log(f"⚠️ Error on playlist '{name}': {e}")

    log(f"\n✅ {deleted} orphaned playlists deleted.")

# === Action Buttons ===
frame = tk.Frame(root)
frame.pack()

tk.Button(frame, text="📂 Import Music Folders", width=30, command=import_music_folders).pack(pady=5)
tk.Button(frame, text="🗑️ Delete Empty Playlists", width=30, command=delete_empty_playlists).pack(pady=5)
tk.Button(frame, text="🧹 Delete Orphaned Playlists", width=30, command=delete_orphaned_playlists).pack(pady=5)

root.mainloop()
