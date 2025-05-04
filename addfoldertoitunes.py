import os
import time
import win32com.client

# Initialize iTunes
itunes = win32com.client.Dispatch("iTunes.Application")

# List of music folders to process
music_folders = [
    r"D:\pierre\audio\changingworldorder"
]

# Access the main Library Playlist
library_playlist = itunes.LibraryPlaylist

for music_folder in music_folders:
    if not os.path.isdir(music_folder):
        print(f"Skipping {music_folder}: Not a valid folder.")
        continue

    # Get the folder name to use as playlist name
    playlist_name = os.path.basename(os.path.normpath(music_folder))
    print(f"\n🔵 Processing folder: {music_folder}")
    print(f"🎵 Target playlist: {playlist_name}")

    # Find or create the playlist
    found_playlist = None
    for pl in itunes.LibrarySource.Playlists:
        if pl.Name == playlist_name:
            found_playlist = pl
            break

    if found_playlist is None:
        found_playlist = itunes.CreatePlaylist(playlist_name)

    # Collect all mp3 files
    mp3_files = []
    for root, dirs, files in os.walk(music_folder):
        for file in files:
            if file.lower().endswith(".mp3"):
                file_path = os.path.join(root, file)
                mp3_files.append(file_path)

    # Sort the list alphabetically
    mp3_files.sort(key=lambda x: x.lower())

    if not mp3_files:
        print(f"⚠️ No MP3 files found in {music_folder}. Skipping.")
        continue

    # Add files in sorted order
    for file_path in mp3_files:
        print(f"➕ Adding {file_path}...")

        # Add file to library
        library_playlist.AddFile(file_path)
        time.sleep(1)  # give iTunes a second to process

        # Find the track by filename
        file_name_only = os.path.basename(file_path)
        track_to_add = None

        for track in library_playlist.Tracks:
            if track.Name in file_name_only:
                track_to_add = track
                break

        if track_to_add is not None:
            found_playlist.AddTrack(track_to_add)
            print(f"✅ Added to playlist: {track_to_add.Name}")
        else:
            print(f"⚠️ Warning: Could not find track for {file_path}")

print("\n✅ All folders processed successfully!")
