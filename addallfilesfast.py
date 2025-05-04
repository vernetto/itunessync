import os
import win32com.client

# Initialize iTunes
itunes = win32com.client.Dispatch("iTunes.Application")

# Define base folder
# base_folder = r"D:\pierre\audio"
base_folder = r"D:\pierre\audio"

# Find all first-level subfolders
music_folders = [f.path for f in os.scandir(base_folder) if f.is_dir()]

# Get existing playlist names once (for speed)
existing_playlists = set(pl.Name.lower() for pl in itunes.LibrarySource.Playlists)

# Process each folder
for music_folder in music_folders:
    playlist_name = os.path.basename(os.path.normpath(music_folder))
    
    if playlist_name.lower() in existing_playlists:
        print(f"⚠️ Playlist '{playlist_name}' already exists. Skipping.")
        continue

    print(f"\n🔵 Creating playlist '{playlist_name}' from folder '{music_folder}'")

    # Create new playlist
    new_playlist = itunes.CreatePlaylist(playlist_name)

    # Collect all mp3 files
    mp3_files = []
    for root_dir, _, files in os.walk(music_folder):
        for file in files:
            if file.lower().endswith(".mp3"):
                mp3_files.append(os.path.join(root_dir, file))

    if not mp3_files:
        print(f"⚠️ No MP3 files found in '{music_folder}'. Skipping.")
        continue

    # Sort files alphabetically (case-insensitive)
    mp3_files.sort(key=lambda x: x.lower())

    # Add files directly to playlist
    for file_path in mp3_files:
        print(f"➕ {file_path}")
        new_playlist.AddFile(file_path)  # much faster and simpler

print("\n✅ All folders processed successfully.")
