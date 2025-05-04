import win32com.client

# Initialize iTunes
itunes = win32com.client.Dispatch("iTunes.Application")

# Access all playlists
playlists = itunes.LibrarySource.Playlists

deleted_count = 0
total_playlists = playlists.Count

print(f"🔍 Checking {total_playlists} playlists...")

# Loop backwards because deleting while looping forward can cause issues
for i in range(total_playlists, 0, -1):
    pl = playlists.Item(i)
    name = pl.Name

    try:
        # Skip system playlists like Genius, Purchased, Recently Added, etc.
        if hasattr(pl, "SpecialKind") and pl.SpecialKind != 0:
            print(f"🚫 Skipping system playlist: {name}")
            continue

        # If empty, delete
        if pl.Tracks.Count == 0:
            print(f"🗑️ Deleting empty playlist: {name}")
            pl.Delete()
            deleted_count += 1
    except Exception as e:
        print(f"⚠️ Error checking playlist '{name}': {e}")

print(f"\n✅ Finished! {deleted_count} empty playlists deleted.")
