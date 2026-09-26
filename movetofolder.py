import win32com.client

playlists = [
    "vernereiseerde"
]

# Connect to iTunes
itunes = win32com.client.Dispatch("iTunes.Application")

sources = itunes.Sources
library = None

# Find the library source
for s in sources:
    if s.Kind == 1:  # ITSourceKindLibrary
        library = s
        break

if not library:
    raise Exception("Library not found")

# Find or create folder playlist
nanofolder = None

for pl in library.Playlists:
    if pl.Name == "nanofolder":
        nanofolder = pl
        break

if not nanofolder:
    nanofolder = library.Playlists.Add("nanofolder")

# Move playlists
for name in playlists:
    try:
        playlist = None

        for pl in library.Playlists:
            if pl.Name == name:
                playlist = pl
                break

        if playlist:
            print(f"Moving: {name}")
            playlist.Parent = nanofolder
        else:
            print(f"Not found: {name}")

    except Exception as e:
        print(f"Error with {name}: {e}")