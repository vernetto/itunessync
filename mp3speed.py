import os
import subprocess
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
from tkinter.ttk import Progressbar
import threading

FFMPEG = 'ffmpeg.exe'


def change_speed(input_path, speed_factor, log_widget):
    filters = []
    remaining = speed_factor

    while remaining < 0.5 or remaining > 2.0:
        if remaining < 0.5:
            filters.append("atempo=0.5")
            remaining /= 0.5
        else:
            filters.append("atempo=2.0")
            remaining /= 2.0

    filters.append(f"atempo={remaining:.4f}")
    atempo_filter = ','.join(filters)

    temp_output = input_path + ".tmp.mp3"

    cmd = [
        FFMPEG,
        '-y',
        '-i', input_path,
        '-filter:a', atempo_filter,
        temp_output
    ]

    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for line in process.stdout:
        log_widget.insert(tk.END, line)
        log_widget.see(tk.END)
    process.wait()

    os.replace(temp_output, input_path)


def process_folder(folder_path, speed_factor, log_widget, progress):
    mp3_files = [f for f in os.listdir(folder_path) if f.lower().endswith('.mp3')]
    total = len(mp3_files)

    for idx, filename in enumerate(mp3_files, 1):
        input_path = os.path.join(folder_path, filename)
        log_widget.insert(tk.END, f"\nProcessing: {filename}\n")
        log_widget.see(tk.END)
        change_speed(input_path, speed_factor, log_widget)
        progress['value'] = (idx / total) * 100
        root.update_idletasks()

    messagebox.showinfo("Done", f"Processed all MP3 files in {folder_path} with speed factor {speed_factor}.")


def browse_folder():
    folder = filedialog.askdirectory()
    if folder:
        folder_var.set(folder)


def start_processing():
    folder = folder_var.get()
    try:
        speed = float(speed_var.get())
        if not (0.1 <= speed <= 5.0):
            raise ValueError
    except ValueError:
        messagebox.showerror("Invalid Input", "Please enter a number between 0.1 and 5 for speed factor.")
        return

    if not os.path.isdir(folder):
        messagebox.showerror("Invalid Folder", "Please select a valid folder.")
        return

    log_text.delete(1.0, tk.END)
    progress_bar['value'] = 0

    thread = threading.Thread(target=process_folder, args=(folder, speed, log_text, progress_bar))
    thread.start()


# Tkinter UI
root = tk.Tk()
root.title("MP3 Speed Changer")
root.geometry("600x400")

folder_var = tk.StringVar(value="D:/pierre/audio")
speed_var = tk.StringVar(value="1.0")

frame = tk.Frame(root, padx=10, pady=10)
frame.pack(fill='both', expand=True)

tk.Label(frame, text="Folder:").grid(row=0, column=0, sticky='w')
tk.Entry(frame, textvariable=folder_var, width=50).grid(row=0, column=1)
tk.Button(frame, text="Browse", command=browse_folder).grid(row=0, column=2, padx=5)

tk.Label(frame, text="Speed factor (0.1 - 5.0):").grid(row=1, column=0, sticky='w', pady=10)
tk.Entry(frame, textvariable=speed_var).grid(row=1, column=1, sticky='w')

tk.Button(frame, text="Start", command=start_processing, bg="green", fg="white").grid(row=1, column=2, pady=10)

progress_bar = Progressbar(frame, orient='horizontal', length=400, mode='determinate')
progress_bar.grid(row=2, column=0, columnspan=3, pady=10)

log_text = scrolledtext.ScrolledText(frame, width=70, height=15)
log_text.grid(row=3, column=0, columnspan=3, pady=10)

root.mainloop()
