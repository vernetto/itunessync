import os
import re
import win32com.client
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

# === Your base music folder ===
base_folder = r"D:\pierre\audio"


class ITunesTab(ttk.Frame):
    """Tab: import folders as playlists, delete empty/orphaned playlists."""

    def __init__(self, parent):
        super().__init__(parent, padding=10)
        self.create_widgets()

    def create_widgets(self):
        ttk.Label(self, text=f"Base folder: {base_folder}").pack(anchor="w")

        self.log_area = scrolledtext.ScrolledText(
            self, wrap=tk.WORD, height=20, width=70, state="disabled"
        )
        self.log_area.pack(padx=5, pady=10, fill=tk.BOTH, expand=True)

        button_frame = ttk.Frame(self)
        button_frame.pack(pady=5)

        ttk.Button(
            button_frame, text="📂 Import Music Folders", width=30,
            command=self.import_music_folders
        ).pack(pady=5)
        ttk.Button(
            button_frame, text="🗑️ Delete Empty Playlists", width=30,
            command=self.delete_empty_playlists
        ).pack(pady=5)
        ttk.Button(
            button_frame, text="🧹 Delete Orphaned Playlists", width=30,
            command=self.delete_orphaned_playlists
        ).pack(pady=5)

    def log(self, message):
        self.log_area.configure(state="normal")
        self.log_area.insert(tk.END, message + "\n")
        self.log_area.yview(tk.END)
        self.log_area.configure(state="disabled")
        self.update_idletasks()

    # === Import Music Folders ===
    def import_music_folders(self):
        if not os.path.isdir(base_folder):
            self.log(f"❌ Base folder not found: {base_folder}")
            return

        self.log("📂 Connecting to iTunes...")
        itunes = win32com.client.Dispatch("iTunes.Application")

        music_folders = [f.path for f in os.scandir(base_folder) if f.is_dir()]
        existing_playlists = set(pl.Name.lower() for pl in itunes.LibrarySource.Playlists)

        playlist_added_total = 0
        added_total = 0
        created_playlist_list: list[str] = []

        for music_folder in music_folders:
            playlist_name = os.path.basename(os.path.normpath(music_folder))
            name_lc = playlist_name.lower()

            if name_lc in existing_playlists:
                self.log(f"⏭️ Playlist '{playlist_name}' already exists. Skipping.")
                continue

            self.log(f"🎵 Creating playlist: {playlist_name}")
            new_playlist = itunes.CreatePlaylist(playlist_name)
            playlist_added_total += 1
            created_playlist_list.append(playlist_name)

            mp3_files = []
            for root_dir, _, files in os.walk(music_folder):
                for file in files:
                    if file.lower().endswith(".mp3"):
                        mp3_files.append(os.path.join(root_dir, file))

            if not mp3_files:
                self.log(f"⚠️ No MP3 files found in '{music_folder}'. Skipping.")
                continue

            mp3_files.sort(key=lambda x: x.lower())

            for file_path in mp3_files:
                new_playlist.AddFile(file_path)
                self.log(f"✅ Added: {os.path.basename(file_path)}")
                added_total += 1

        list_as_string = " ".join(created_playlist_list)
        self.log(f"✅ Import complete. {added_total} tracks added, {playlist_added_total} playlists created:")
        self.log(f"✅ {list_as_string}")

    def delete_empty_playlists(self):
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
                    self.log(f"🗑️ Deleting empty playlist: {name}")
                    pl.Delete()
                    deleted += 1
            except Exception as e:
                self.log(f"⚠️ Error on playlist '{name}': {e}")

        self.log(f"\n✅ {deleted} empty playlists deleted.")

    # === Delete Orphaned Playlists ===
    def delete_orphaned_playlists(self):
        if not os.path.isdir(base_folder):
            self.log(f"❌ Base folder not found: {base_folder}")
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
                    self.log(f"🗑️ Deleting orphaned playlist: {name}")
                    pl.Delete()
                    deleted += 1
            except Exception as e:
                self.log(f"⚠️ Error on playlist '{name}': {e}")

        self.log(f"\n✅ {deleted} orphaned playlists deleted.")


class RenameFilesTab(ttk.Frame):
    """Tab: rename MP3 files in selected folders, swapping name_number -> number_name."""

    def __init__(self, parent):
        super().__init__(parent, padding=10)
        self.folders = set()
        self.create_widgets()

    def create_widgets(self):
        ttk.Label(self, text="Selected folders:").pack(anchor="w")

        self.folder_listbox = tk.Listbox(self, height=10)
        self.folder_listbox.pack(fill=tk.X, expand=False, pady=5)

        button_frame = ttk.Frame(self)
        button_frame.pack(fill=tk.X, pady=5)

        ttk.Button(button_frame, text="Add Folder", command=self.add_folder).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Remove Selected", command=self.remove_selected).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Clear All", command=self.clear_all).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Process", command=self.process_folders).pack(side=tk.RIGHT, padx=5)

        self.progress = ttk.Progressbar(self, orient="horizontal", length=100, mode="determinate")
        self.progress.pack(fill=tk.X, pady=5)

        ttk.Label(self, text="Log:").pack(anchor="w")

        self.log = tk.Text(self, height=15)
        self.log.pack(fill=tk.BOTH, expand=True)

    def add_folder(self):
        initial_dir = base_folder

        if not os.path.exists(initial_dir):
            initial_dir = os.path.expanduser("~")

        folder = filedialog.askdirectory(initialdir=initial_dir)

        if folder and folder not in self.folders:
            self.folders.add(folder)
            self.folder_listbox.insert(tk.END, folder)

    def remove_selected(self):
        selected = self.folder_listbox.curselection()

        for index in reversed(selected):
            folder = self.folder_listbox.get(index)
            self.folders.remove(folder)
            self.folder_listbox.delete(index)

    def clear_all(self):
        self.folders.clear()
        self.folder_listbox.delete(0, tk.END)

    def log_message(self, message):
        self.log.insert(tk.END, message + "\n")
        self.log.see(tk.END)
        self.update_idletasks()

    def rename_files(self, folder):
        count = 0
        pattern = re.compile(r"^(.*)_(\d+)$")

        for filename in os.listdir(folder):
            base, ext = os.path.splitext(filename)

            if ext.lower() == ".mp3":
                match = pattern.match(base)

                if match:
                    new_name = f"{match.group(2)}_{match.group(1)}{ext}"

                    old_path = os.path.join(folder, filename)
                    new_path = os.path.join(folder, new_name)

                    if old_path != new_path:
                        os.rename(old_path, new_path)
                        self.log_message(f"{filename} → {new_name}")
                        count += 1

        return count

    def process_folders(self):
        if not self.folders:
            messagebox.showwarning("Warning", "No folders selected")
            return

        total_files = 0

        self.progress["maximum"] = len(self.folders)
        self.progress["value"] = 0

        self.log.delete(1.0, tk.END)

        for i, folder in enumerate(self.folders):
            self.log_message(f"\nProcessing folder: {folder}")

            try:
                count = self.rename_files(folder)
                self.log_message(f"Renamed {count} files")
                total_files += count
            except Exception as e:
                self.log_message(f"ERROR: {e}")

            self.progress["value"] = i + 1
            self.update_idletasks()

        messagebox.showinfo("Done", f"Renamed total {total_files} files")


class PlaylistManagerTab(ttk.Frame):
    """Tab: list all iTunes playlists with checkboxes; delete selected playlists AND their files."""

    def __init__(self, parent):
        super().__init__(parent, padding=10)
        self.playlist_vars = {}  # name -> tk.BooleanVar
        self.create_widgets()
        self.refresh_playlists()

    def create_widgets(self):
        top_frame = ttk.Frame(self)
        top_frame.pack(fill=tk.X, pady=5)

        ttk.Button(top_frame, text="🔄 Refresh List", command=self.refresh_playlists).pack(side=tk.LEFT, padx=5)
        ttk.Button(top_frame, text="☑ Select All", command=self.select_all).pack(side=tk.LEFT, padx=5)
        ttk.Button(top_frame, text="☐ Deselect All", command=self.deselect_all).pack(side=tk.LEFT, padx=5)
        ttk.Button(
            top_frame, text="🗑️ Delete Selected (playlist + library tracks)",
            command=self.delete_selected
        ).pack(side=tk.RIGHT, padx=5)

        # Scrollable checkbox area
        list_container = ttk.Frame(self)
        list_container.pack(fill=tk.BOTH, expand=True, pady=5)

        canvas = tk.Canvas(list_container, borderwidth=0, height=250)
        scrollbar = ttk.Scrollbar(list_container, orient="vertical", command=canvas.yview)
        self.checkbox_frame = ttk.Frame(canvas)

        self.checkbox_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=self.checkbox_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        ttk.Label(self, text="Log:").pack(anchor="w")
        self.log_area = scrolledtext.ScrolledText(self, wrap=tk.WORD, height=10, state="disabled")
        self.log_area.pack(fill=tk.BOTH, expand=True, pady=5)

    def log(self, message):
        self.log_area.configure(state="normal")
        self.log_area.insert(tk.END, message + "\n")
        self.log_area.yview(tk.END)
        self.log_area.configure(state="disabled")
        self.update_idletasks()

    def _get_deletable_playlists(self, itunes):
        """Return list of (name, playlist_object), skipping Library and special playlists."""
        result = []
        playlists = itunes.LibrarySource.Playlists
        for i in range(1, playlists.Count + 1):
            pl = playlists.Item(i)
            try:
                name = pl.Name
                if name.lower() == "library" or (hasattr(pl, "SpecialKind") and pl.SpecialKind != 0):
                    continue
                result.append((name, pl))
            except Exception:
                continue
        return result

    def _build_library_index(self, itunes):
        """
        Build lookup tables (by TrackDatabaseID and by Location) pointing to the actual
        track objects in the main iTunes Library. A track fetched from a *user* playlist
        only represents membership in that playlist — calling Delete() on it removes it
        from that playlist alone, not from the Library. To truly remove the track from
        the Library (and from every playlist it appears in), Delete() must be called on
        the corresponding track object from itunes.LibraryPlaylist.
        """
        by_id = {}
        by_location = {}
        try:
            library_tracks = itunes.LibraryPlaylist.Tracks
        except Exception as e:
            self.log(f"❌ Could not access the Library playlist: {e}")
            return by_id, by_location

        for i in range(1, library_tracks.Count + 1):
            try:
                lib_track = library_tracks.Item(i)
            except Exception:
                continue
            try:
                by_id[lib_track.TrackDatabaseID] = lib_track
            except Exception:
                pass
            try:
                location = lib_track.Location
                if location:
                    by_location[location] = lib_track
            except Exception:
                pass

        return by_id, by_location

    def refresh_playlists(self):
        for widget in self.checkbox_frame.winfo_children():
            widget.destroy()
        self.playlist_vars.clear()

        try:
            itunes = win32com.client.Dispatch("iTunes.Application")
        except Exception as e:
            self.log(f"❌ Could not connect to iTunes: {e}")
            return

        playlists = self._get_deletable_playlists(itunes)

        if not playlists:
            ttk.Label(self.checkbox_frame, text="(No playlists found)").pack(anchor="w")
            return

        for name, pl in sorted(playlists, key=lambda x: x[0].lower()):
            try:
                track_count = pl.Tracks.Count
            except Exception:
                track_count = "?"
            var = tk.BooleanVar(value=False)
            self.playlist_vars[name] = var
            ttk.Checkbutton(
                self.checkbox_frame,
                text=f"{name} ({track_count} tracks)",
                variable=var
            ).pack(anchor="w", pady=1)

        self.log(f"🔄 Loaded {len(playlists)} playlists.")

    def select_all(self):
        for var in self.playlist_vars.values():
            var.set(True)

    def deselect_all(self):
        for var in self.playlist_vars.values():
            var.set(False)

    def delete_selected(self):
        selected_names = [name for name, var in self.playlist_vars.items() if var.get()]

        if not selected_names:
            messagebox.showwarning("Warning", "No playlists selected")
            return

        confirm = messagebox.askyesno(
            "Confirm Delete",
            f"This will delete {len(selected_names)} playlist(s) and remove their tracks "
            "from the iTunes library.\n\nFiles on disk will NOT be touched. Continue?"
        )
        if not confirm:
            return

        try:
            itunes = win32com.client.Dispatch("iTunes.Application")
        except Exception as e:
            self.log(f"❌ Could not connect to iTunes: {e}")
            return

        self.log("🔎 Indexing the iTunes Library...")
        by_id, by_location = self._build_library_index(itunes)
        self.log(f"🔎 Indexed {len(by_location) or len(by_id)} library tracks.")

        deleted_playlists = 0
        deleted_files = 0

        for name in selected_names:
            # Re-fetch playlists each time: deleting one can shift COM indices/objects.
            playlists = self._get_deletable_playlists(itunes)
            pl = next((p for n, p in playlists if n == name), None)

            if pl is None:
                self.log(f"⚠️ Playlist '{name}' not found (already deleted?). Skipping.")
                continue

            self.log(f"🗑️ Processing playlist: {name}")

            try:
                tracks = pl.Tracks
                # Iterate in reverse: deleting a track shifts the indices of the rest.
                for i in range(tracks.Count, 0, -1):
                    track = tracks.Item(i)
                    try:
                        track_name = track.Name
                    except Exception:
                        track_name = "(unknown track)"

                    # Resolve the actual Library track reference — deleting the track
                    # as fetched from the user playlist would only unlink it from this
                    # one playlist, leaving it (and the file) in the Library.
                    lib_track = None
                    try:
                        lib_track = by_id.get(track.TrackDatabaseID)
                    except Exception:
                        pass
                    if lib_track is None:
                        try:
                            location = track.Location
                            if location:
                                lib_track = by_location.get(location)
                        except Exception:
                            pass

                    if lib_track is None:
                        self.log(f"  ⚠️ Could not find '{track_name}' in the Library. Skipping.")
                        continue

                    try:
                        lib_track.Delete()
                        self.log(f"  ✅ Removed from library: {track_name}")
                        deleted_files += 1
                        # Avoid a second, failing delete attempt if the same track
                        # also belongs to another playlist selected in this run.
                        by_id.pop(getattr(lib_track, "TrackDatabaseID", None), None)
                        try:
                            by_location.pop(lib_track.Location, None)
                        except Exception:
                            pass
                    except Exception as e:
                        self.log(f"  ❌ Error removing track '{track_name}' from library: {e}")

                pl.Delete()
                self.log(f"✅ Deleted playlist: {name}")
                deleted_playlists += 1

            except Exception as e:
                # iTunes sometimes auto-deletes a playlist once it becomes empty
                # (all its tracks were just removed from the library above).
                # In that case pl.Delete() fails because it's already gone — treat as success.
                error_text = str(e).lower()
                if "already" in error_text or "has been deleted" in error_text or "no longer exists" in error_text:
                    self.log(f"✅ Playlist '{name}' was auto-removed after its tracks were deleted.")
                    deleted_playlists += 1
                else:
                    self.log(f"❌ Error deleting playlist '{name}': {e}")

        self.log(
            f"\n✅ Done. {deleted_playlists} playlist(s) deleted, "
            f"{deleted_files} track(s) removed from the iTunes library (files on disk untouched)."
        )
        self.refresh_playlists()


class MusicToolsApp:
    def __init__(self, root):
        self.root = root
        self.root.title("🎵 Music Tools")
        self.root.geometry("700x600")

        notebook = ttk.Notebook(root)
        notebook.pack(fill=tk.BOTH, expand=True)

        itunes_tab = ITunesTab(notebook)
        rename_tab = RenameFilesTab(notebook)
        playlist_manager_tab = PlaylistManagerTab(notebook)

        notebook.add(itunes_tab, text="iTunes Playlist Manager")
        notebook.add(rename_tab, text="MP3 Renamer")
        notebook.add(playlist_manager_tab, text="Manage Playlists")


def main():
    root = tk.Tk()
    MusicToolsApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
