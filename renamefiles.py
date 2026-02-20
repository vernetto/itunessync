import os
import re
import tkinter as tk
from tkinter import ttk, filedialog, messagebox


class RenameFilesApp:

    def __init__(self, root):

        self.root = root
        self.root.title("MP3 Renamer")
        self.root.geometry("700x500")

        self.folders = set()

        self.create_widgets()


    def create_widgets(self):

        main_frame = ttk.Frame(self.root, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)


        # Folder list label
        ttk.Label(main_frame, text="Selected folders:").pack(anchor="w")


        # Listbox
        self.folder_listbox = tk.Listbox(main_frame, height=10)
        self.folder_listbox.pack(fill=tk.X, expand=False, pady=5)


        # Buttons frame
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=5)


        ttk.Button(
            button_frame,
            text="Add Folder",
            command=self.add_folder
        ).pack(side=tk.LEFT, padx=5)


        ttk.Button(
            button_frame,
            text="Remove Selected",
            command=self.remove_selected
        ).pack(side=tk.LEFT, padx=5)


        ttk.Button(
            button_frame,
            text="Clear All",
            command=self.clear_all
        ).pack(side=tk.LEFT, padx=5)


        ttk.Button(
            button_frame,
            text="Process",
            command=self.process_folders
        ).pack(side=tk.RIGHT, padx=5)


        # Progress bar
        self.progress = ttk.Progressbar(
            main_frame,
            orient="horizontal",
            length=100,
            mode="determinate"
        )
        self.progress.pack(fill=tk.X, pady=5)


        # Log label
        ttk.Label(main_frame, text="Log:").pack(anchor="w")


        # Log text area
        self.log = tk.Text(main_frame, height=15)
        self.log.pack(fill=tk.BOTH, expand=True)


    def add_folder(self):

        initial_dir = r"D:\pierre\audio"

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
        self.root.update_idletasks()


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
            self.root.update_idletasks()


        messagebox.showinfo(
            "Done",
            f"Renamed total {total_files} files"
        )


def main():

    root = tk.Tk()

    app = RenameFilesApp(root)

    root.mainloop()


if __name__ == "__main__":
    main()
