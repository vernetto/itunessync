#!/bin/bash

# Directory containing VOB files (default: current directory)
DIR="${1:-.}"

# Check if ffmpeg is installed
if ! command -v ffmpeg &> /dev/null; then
    echo "Error: ffmpeg is not installed. Install it and try again."
    exit 1
fi

# Loop through all VOB files in the specified directory
for vob_file in "$DIR"/*.VOB; do
    # Check if there are VOB files
    if [ ! -f "$vob_file" ]; then
        echo "No VOB files found in $DIR"
        exit 1
    fi

    # Define output filename (replace .VOB with .mp4)
    output_file="${vob_file%.VOB}.mp4"

    echo "Converting: $vob_file -> $output_file"

    # Run ffmpeg conversion
    ffmpeg -i "$vob_file" -c:v libx264 -preset fast -crf 23 -c:a aac -b:a 192k "$output_file"

    if [ $? -eq 0 ]; then
        echo "Successfully converted: $output_file"
    else
        echo "Failed to convert: $vob_file"
    fi
done

echo "All conversions completed."
