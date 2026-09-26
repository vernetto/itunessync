# Set the target directory
$path = "H:\pierre\downloads\explodecoracao"

# Check if FFmpeg is installed
if (!(Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Write-Error "FFmpeg is not installed or not in your PATH. Please install it to run this script."
    return
}

# Loop through all MP4 files in the folder
Get-ChildItem -Path $path -Filter *.mp4 | ForEach-Object {
    $outputFile = $_.FullName.Replace(".mp4", ".mp3")
    
    Write-Host "Extracting audio from: $($_.Name)"
    
    # Run FFmpeg to extract audio
    # -i: input file
    # -vn: disable video
    # -acodec libmp3lame: convert to MP3
    # -q:a 2: sets a high-quality variable bitrate (~190 kbps)
    ffmpeg -i "$($_.FullName)" -vn -acodec libmp3lame -q:a 2 "$outputFile"
}

Write-Host "Done! All MP3s have been extracted." -ForegroundColor Green