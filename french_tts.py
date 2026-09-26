#!/usr/bin/env python3
"""
French text -> MP3 TTS pipeline using edge-tts.
Splits large text into chunks (on paragraph/sentence boundaries),
synthesizes each chunk, then concatenates into one final MP3.

Usage:
    python3 french_tts.py input.txt output.mp3 [voice]

Requires:
    pip install edge-tts --break-system-packages
    ffmpeg installed (sudo apt install ffmpeg)
"""

import asyncio
import sys
import os
import re
import subprocess
import tempfile
import edge_tts

MAX_CHARS = 3000  # safe chunk size per TTS call

def split_text(text, max_chars=MAX_CHARS):
    """Split text into chunks, breaking on paragraph then sentence boundaries."""
    paragraphs = re.split(r'\n\s*\n', text)
    chunks = []
    current = ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if len(current) + len(para) + 1 <= max_chars:
            current += ("\n\n" if current else "") + para
        else:
            if current:
                chunks.append(current)
                current = ""
            # paragraph itself too big -> split on sentences
            if len(para) > max_chars:
                sentences = re.split(r'(?<=[.!?])\s+', para)
                for sent in sentences:
                    if len(current) + len(sent) + 1 <= max_chars:
                        current += (" " if current else "") + sent
                    else:
                        if current:
                            chunks.append(current)
                        current = sent
            else:
                current = para
    if current:
        chunks.append(current)
    return chunks


async def synth_chunk(text, voice, out_path):
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(out_path)


async def main():
    if len(sys.argv) < 3:
        print("Usage: python3 french_tts.py input.txt output.mp3 [voice]")
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = sys.argv[2]
    voice = sys.argv[3] if len(sys.argv) > 3 else "fr-FR-DeniseNeural"

    with open(input_path, "r", encoding="utf-8") as f:
        text = f.read()

    chunks = split_text(text)
    print(f"Split into {len(chunks)} chunks. Voice: {voice}")

    with tempfile.TemporaryDirectory() as tmpdir:
        chunk_files = []
        for i, chunk in enumerate(chunks):
            chunk_path = os.path.join(tmpdir, f"chunk_{i:04d}.mp3")
            print(f"  Synthesizing chunk {i+1}/{len(chunks)} ({len(chunk)} chars)...")
            await synth_chunk(chunk, voice, chunk_path)
            chunk_files.append(chunk_path)

        # Build ffmpeg concat list
        list_path = os.path.join(tmpdir, "list.txt")
        with open(list_path, "w") as f:
            for cf in chunk_files:
                f.write(f"file '{cf}'\n")

        print("Concatenating chunks with ffmpeg...")
        subprocess.run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", list_path, "-c", "copy", output_path
        ], check=True)

    print(f"Done: {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
