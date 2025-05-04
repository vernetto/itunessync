import os
import win32com.client

# 📂 Base folder where music folders live
base_folder = r"D:\pierre\audio"

# Get all folder names under base_folder (case-insensitive)
if not os.path.isdir(base_folder):
    print(f"❌ Base folder not found: {base_folder}")
    exit()

valid_folder_names = {
    os.path.basename(f.path).lower()
    for f in os.scandir(base_folder)
    if f.is_dir()
}

# Initialize iTunes
itunes = win32com.client.Dispatch("iTunes.Application")
playlists = itunes.LibrarySource.Playlists

deleted_empty = 0
deleted_orphaned = 0
total_playlists = playlists.Count

print(f"🔍 Checking {total_playlists} playlists...")

# Loop backwards to safely delete
for i in range(total_playlists, 0, -1):
    pl = playlists.Item(i)
    name = pl.Name

    try:
        # Skip system playlists
        if hasattr(pl, "SpecialKind") and pl.SpecialKind != 0:
            print(f"🚫 Skipping system playlist: {name}")
            continue

        name_lc = name.strip().lower()
        
        if name_lc == "library":
            print(f"🚫 Skipping root playlist: {name}")
            continue
            
        # Delete if empty
        if pl.Tracks.Count == 0:
            print(f"🗑️ Deleting empty playlist: {name}")
            pl.Delete()
            deleted_empty += 1
            continue

        # Delete if no corresponding folder exists
        if name_lc not in valid_folder_names:
            print(f"🗑️ Deleting orphaned playlist (no matching folder): {name}")
            pl.Delete()
            deleted_orphaned += 1

    except Exception as e:
        print(f"⚠️ Error checking playlist '{name}': {e}")

print(f"\n✅ Done!")
print(f"🗑️ {deleted_empty} empty playlists deleted.")
print(f"🗑️ {deleted_orphaned} orphaned playlists deleted (no folder match).")
