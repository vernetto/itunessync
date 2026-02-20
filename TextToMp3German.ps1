# powershell -ExecutionPolicy Bypass -File TextToMp3German.ps1 "input.txt" "output.mp3" -DeleteWavAfter


param(
    [Parameter(Mandatory=$true)]
    [string]$InputFile,

    [Parameter(Mandatory=$true)]
    [string]$OutputMp3,

    [switch]$DeleteWavAfter = $false
)

# Temporary WAV file
$TempWav = [System.IO.Path]::ChangeExtension($OutputMp3, ".wav")

# Load .NET speech assembly
Add-Type -AssemblyName System.Speech

$s = New-Object System.Speech.Synthesis.SpeechSynthesizer

# Auto-detect a German (de-DE) voice
$germanVoice = $s.GetInstalledVoices() |
    Where-Object { $_.VoiceInfo.Culture -eq "de-DE" } |
    Select-Object -First 1

if (-not $germanVoice) {
    Write-Host "❌ No German voice (de-DE) found on this system!"
    Write-Host "Install a German voice in Windows Settings → Time & Language → Language → Add language: German"
    exit 1
}

Write-Host "Using German voice: $($germanVoice.VoiceInfo.Name)"
$s.SelectVoice($germanVoice.VoiceInfo.Name)

# Set output WAV
$s.SetOutputToWaveFile($TempWav)

# Read text
$text = Get-Content $InputFile -Raw

# Speak to WAV
$s.Speak($text)
$s.Dispose()

Write-Host "✔ Created WAV: $TempWav"

# Convert to MP3 using ffmpeg
$ffmpeg = "ffmpeg"  # must be installed & in PATH
$arguments = "-y -i `"$TempWav`" -codec:a libmp3lame -qscale:a 2 `"$OutputMp3`""

Write-Host "Converting WAV → MP3..."
$process = Start-Process -FilePath $ffmpeg -ArgumentList $arguments -NoNewWindow -Wait -PassThru

if ($process.ExitCode -ne 0) {
    Write-Host "❌ ffmpeg conversion failed!"
    exit 1
}

Write-Host "✔ Created MP3: $OutputMp3"

# Optionally delete WAV
if ($DeleteWavAfter) {
    Remove-Item $TempWav -Force
    Write-Host "🗑 Deleted temporary WAV."
}

Write-Host "🎉 Done!"
