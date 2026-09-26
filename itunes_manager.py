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


class MusicToolsApp:
    def __init__(self, root):
        self.root = root
        self.root.title("🎵 Music Tools")
        self.root.geometry("700x600")

        notebook = ttk.Notebook(root)
        notebook.pack(fill=tk.BOTH, expand=True)

        itunes_tab = ITunesTab(notebook)
        rename_tab = RenameFilesTab(notebook)

        notebook.add(itunes_tab, text="iTunes Playlist Manager")
        notebook.add(rename_tab, text="MP3 Renamer")


def main():
    root = tk.Tk()
    MusicToolsApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
