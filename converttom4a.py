import os
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext

# ------------------------------------------------------
# CONFIGURATION
# ------------------------------------------------------

# Hard-coded FFmpeg path (Chocolatey)
FFMPEG_PATH = r"C:\ProgramData\chocolatey\lib\ffmpeg\tools\ffmpeg\bin\ffmpeg.exe"

BITRATE = "32k"   # change to 24k / 48k if needed


# ------------------------------------------------------
# FUNCTIONS
# ------------------------------------------------------

def convert_folder():
    folder = folder_var.get().strip()
    if not folder:
        messagebox.showerror("Error", "Please select a folder first.")
        return

    if not os.path.isdir(folder):
        messagebox.showerror("Error", "Invalid folder selected.")
        return

    # Check FFmpeg exists
    if not os.path.isfile(FFMPEG_PATH):
        messagebox.showerror("Error", f"FFmpeg not found at:\n{FFMPEG_PATH}")
        return

    log_text.delete(1.0, tk.END)

    mp3_files = [f for f in os.listdir(folder) if f.lower().endswith(".mp3")]
    if not mp3_files:
        log("No MP3 files found in the folder.")
        return

    log(f"Found {len(mp3_files)} MP3 files.\n")

    # Run conversion in a separate thread
    threading.Thread(target=convert_files_thread, args=(folder, mp3_files), daemon=True).start()


def convert_files_thread(folder, mp3_files):
    for f in mp3_files:
        input_path = os.path.join(folder, f)
        output_path = os.path.splitext(input_path)[0] + ".m4a"

        log(f"Converting: {f} → {os.path.basename(output_path)}")

        cmd = [
            FFMPEG_PATH,
            "-y",
            "-i", input_path,
            "-c:a", "aac",
            "-b:a", BITRATE,
            output_path
        ]

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            universal_newlines=True
        )

        # FFmpeg sends progress to stderr
        for line in process.stderr:
            line = line.strip()
            if ("size=" in line or "time=" in line or "bitrate=" in line):
                log(line)

        process.wait()

        if process.returncode == 0:
            log("✓ Completed\n")
        else:
            log("⚠ Error during conversion\n")

    log("All conversions completed.")


def browse_folder():
    folder = filedialog.askdirectory()
    if folder:
        folder_var.set(folder)


def log(message):
    log_text.insert(tk.END, message + "\n")
    log_text.see(tk.END)


# ------------------------------------------------------
# GUI
# ------------------------------------------------------

root = tk.Tk()
root.title("MP3 → AAC/M4A Converter (with Progress)")

# Folder selection
frame = tk.Frame(root)
frame.pack(pady=10, padx=10, fill="x")

folder_var = tk.StringVar()

tk.Label(frame, text="Folder:").pack(side="left")
tk.Entry(frame, textvariable=folder_var, width=40).pack(side="left", padx=5)
tk.Button(frame, text="Browse", command=browse_folder).pack(side="left")

# Convert button
tk.Button(root, text="Convert MP3 to AAC/M4A", command=convert_folder,
          bg="#4CAF50", fg="white").pack(pady=10)

# Log output
log_text = scrolledtext.ScrolledText(root, width=70, height=25)
log_text.pack(padx=10, pady=10)

root.mainloop()
