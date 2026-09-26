#!/usr/bin/env python3
"""
Pipeline di doppiaggio sincronizzato: SRT (tedesco) -> traduzione (russo) -> TTS -> mux video.

Uso tipico:
    1. Estrai l'audio dal video:
         ffmpeg -i video.mp4 -vn -acodec pcm_s16le -ar 16000 -ac 1 tedesco.wav

    2. Trascrivi con faster-whisper generando un SRT (vedi genera_srt.py sotto,
       oppure usa whisper/faster-whisper con --output_format srt).

    3. Lancia questa pipeline:
         python3 dub_pipeline.py --srt tedesco.srt --video video.mp4 --output video_russo.mp4

Dipendenze (installa con pip):
    pip install edge-tts deep-translator srt

Richiede ffmpeg/ffprobe nel PATH (già presenti su Debian: apt install ffmpeg).
"""

import argparse
import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from typing import List

try:
    import srt as srt_lib
except ImportError:
    print("Manca la libreria 'srt'. Installa con: pip install srt", file=sys.stderr)
    sys.exit(1)

try:
    import edge_tts
except ImportError:
    print("Manca 'edge-tts'. Installa con: pip install edge-tts", file=sys.stderr)
    sys.exit(1)

try:
    from deep_translator import GoogleTranslator
except ImportError:
    GoogleTranslator = None  # traduzione opzionale, vedi --no-translate


# ---------------------------------------------------------------------------
# Configurazione di default
# ---------------------------------------------------------------------------

DEFAULT_VOICE = "ru-RU-DmitryNeural"   # alternativa: ru-RU-SvetlanaNeural
MAX_ATEMPO_PER_STAGE = 2.0             # limite del filtro atempo di ffmpeg per singola applicazione
MIN_ATEMPO_PER_STAGE = 0.5


@dataclass
class Segment:
    index: int
    start_ms: int
    end_ms: int
    text_src: str
    text_tgt: str = ""


# ---------------------------------------------------------------------------
# Step 1: parsing SRT
# ---------------------------------------------------------------------------

def parse_srt(path: str) -> List[Segment]:
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    subs = list(srt_lib.parse(content))
    segments = []
    for sub in subs:
        start_ms = int(sub.start.total_seconds() * 1000)
        end_ms = int(sub.end.total_seconds() * 1000)
        text = sub.content.replace("\n", " ").strip()
        segments.append(Segment(index=sub.index, start_ms=start_ms, end_ms=end_ms, text_src=text))
    return segments


# ---------------------------------------------------------------------------
# Step 2: traduzione DE -> RU
# ---------------------------------------------------------------------------

def translate_segments(segments: List[Segment], source="de", target="ru") -> None:
    if GoogleTranslator is None:
        print("deep-translator non installato: salto la traduzione, uso il testo originale.", file=sys.stderr)
        for s in segments:
            s.text_tgt = s.text_src
        return

    translator = GoogleTranslator(source=source, target=target)
    for s in segments:
        if not s.text_src.strip():
            s.text_tgt = ""
            continue
        try:
            s.text_tgt = translator.translate(s.text_src)
        except Exception as e:
            print(f"[WARN] traduzione fallita per segmento {s.index}: {e}", file=sys.stderr)
            s.text_tgt = s.text_src


# ---------------------------------------------------------------------------
# Step 3: TTS per singolo segmento
# ---------------------------------------------------------------------------

async def _tts_one(text: str, out_path: str, voice: str, rate: str = "+0%") -> None:
    if not text.strip():
        # segmento vuoto: crea un file audio silenzioso minimo (verrà comunque
        # sovrascritto/paddato più avanti in base alla durata target)
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
             "-t", "0.3", "-q:a", "9", out_path],
            check=True, capture_output=True,
        )
        return
    communicate = edge_tts.Communicate(text, voice, rate=rate)
    await communicate.save(out_path)


def tts_segment(text: str, out_path: str, voice: str, rate: str = "+0%") -> None:
    asyncio.run(_tts_one(text, out_path, voice, rate))


# ---------------------------------------------------------------------------
# Utility ffmpeg
# ---------------------------------------------------------------------------

def get_duration_ms(path: str) -> int:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        check=True, capture_output=True, text=True,
    )
    return int(float(result.stdout.strip()) * 1000)


def build_atempo_chain(factor: float) -> str:
    """
    ffmpeg limita atempo a [0.5, 2.0] per singola istanza.
    Per fattori più estremi si incatenano più filtri atempo.
    factor = durata_generata / durata_target
      factor > 1  -> audio troppo lungo, bisogna velocizzarlo (atempo > 1)
      factor < 1  -> audio troppo corto, bisogna rallentarlo (atempo < 1)
    """
    filters = []
    remaining = factor
    # velocizzare (remaining > 1)
    while remaining > MAX_ATEMPO_PER_STAGE:
        filters.append(f"atempo={MAX_ATEMPO_PER_STAGE}")
        remaining /= MAX_ATEMPO_PER_STAGE
    while remaining < MIN_ATEMPO_PER_STAGE:
        filters.append(f"atempo={MIN_ATEMPO_PER_STAGE}")
        remaining /= MIN_ATEMPO_PER_STAGE
    if abs(remaining - 1.0) > 1e-3:
        filters.append(f"atempo={remaining:.4f}")
    if not filters:
        return ""
    return ",".join(filters)


def fit_to_duration(in_path: str, out_path: str, target_ms: int, max_stretch: float = 1.3) -> None:
    """
    Adatta la durata dell'audio TTS alla durata target del segmento SRT.
    - Se la differenza è entro max_stretch, usa atempo per comprimere/allungare.
    - Altrimenti accetta lo scostamento (evita di rendere la voce innaturale)
      e poi pad/trim con silenzio per non sfasare i segmenti successivi.
    """
    gen_ms = get_duration_ms(in_path)
    if gen_ms == 0:
        gen_ms = 1
    factor = gen_ms / target_ms

    factor_clamped = max(1 / max_stretch, min(max_stretch, factor))
    atempo_filter = build_atempo_chain(factor_clamped)

    tmp_stretched = out_path + ".stretched.mp3"
    if atempo_filter:
        subprocess.run(
            ["ffmpeg", "-y", "-i", in_path, "-filter:a", atempo_filter, tmp_stretched],
            check=True, capture_output=True,
        )
    else:
        shutil.copy(in_path, tmp_stretched)

    # pad o trim per matchare esattamente target_ms
    new_ms = get_duration_ms(tmp_stretched)
    if new_ms < target_ms:
        pad_ms = target_ms - new_ms
        subprocess.run(
            ["ffmpeg", "-y", "-i", tmp_stretched, "-af",
             f"apad=pad_dur={pad_ms/1000:.3f}", out_path],
            check=True, capture_output=True,
        )
    else:
        subprocess.run(
            ["ffmpeg", "-y", "-i", tmp_stretched, "-t", f"{target_ms/1000:.3f}", out_path],
            check=True, capture_output=True,
        )
    os.remove(tmp_stretched)


# ---------------------------------------------------------------------------
# Step 4: assemblaggio traccia audio finale
# ---------------------------------------------------------------------------

def build_full_track(segments: List[Segment], workdir: str, voice: str, rate: str,
                      total_duration_ms: int, max_stretch: float) -> str:
    parts = []
    cursor_ms = 0

    for seg in segments:
        # silenzio prima del segmento, se c'è un gap
        if seg.start_ms > cursor_ms:
            gap_ms = seg.start_ms - cursor_ms
            silence_path = os.path.join(workdir, f"silence_{seg.index}.mp3")
            subprocess.run(
                ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
                 "-t", f"{gap_ms/1000:.3f}", "-q:a", "9", silence_path],
                check=True, capture_output=True,
            )
            parts.append(silence_path)
            cursor_ms += gap_ms

        raw_path = os.path.join(workdir, f"seg_{seg.index}_raw.mp3")
        fit_path = os.path.join(workdir, f"seg_{seg.index}_fit.mp3")
        tts_segment(seg.text_tgt, raw_path, voice, rate)

        target_ms = seg.end_ms - seg.start_ms
        fit_to_duration(raw_path, fit_path, target_ms, max_stretch)
        parts.append(fit_path)
        cursor_ms = seg.end_ms

        print(f"[{seg.index}/{len(segments)}] \"{seg.text_tgt[:60]}\"")

    # silenzio finale fino alla durata totale del video, se serve
    if total_duration_ms > cursor_ms:
        tail_ms = total_duration_ms - cursor_ms
        tail_path = os.path.join(workdir, "silence_tail.mp3")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
             "-t", f"{tail_ms/1000:.3f}", "-q:a", "9", tail_path],
            check=True, capture_output=True,
        )
        parts.append(tail_path)

    # concat list per ffmpeg
    concat_list_path = os.path.join(workdir, "concat_list.txt")
    with open(concat_list_path, "w", encoding="utf-8") as f:
        for p in parts:
            f.write(f"file '{os.path.abspath(p)}'\n")

    full_audio_path = os.path.join(workdir, "full_audio.mp3")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list_path,
         "-c", "copy", full_audio_path],
        check=True, capture_output=True,
    )
    return full_audio_path


# ---------------------------------------------------------------------------
# Step 5: mux finale
# ---------------------------------------------------------------------------

def mux_video(video_path: str, audio_path: str, output_path: str) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-i", video_path, "-i", audio_path,
         "-map", "0:v:0", "-map", "1:a:0",
         "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
         "-shortest", output_path],
        check=True, capture_output=True,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Pipeline di doppiaggio sincronizzato SRT -> RU TTS -> video")
    parser.add_argument("--srt", required=True, help="File SRT di partenza (es. in tedesco)")
    parser.add_argument("--video", required=True, help="Video originale")
    parser.add_argument("--output", required=True, help="File video di output")
    parser.add_argument("--voice", default=DEFAULT_VOICE, help="Voce edge-tts (default: %(default)s)")
    parser.add_argument("--rate", default="-10%", help="Regolazione velocità TTS, es. -10%%, +5%% (default: %(default)s)")
    parser.add_argument("--source-lang", default="de", help="Lingua sorgente per traduzione (default: de)")
    parser.add_argument("--target-lang", default="ru", help="Lingua target per traduzione (default: ru)")
    parser.add_argument("--max-stretch", type=float, default=1.3,
                         help="Massimo fattore di stretch/compressione audio prima di accettare lo scostamento (default: 1.3)")
    parser.add_argument("--no-translate", action="store_true", help="Salta la traduzione, usa il testo dell'SRT così com'è")
    parser.add_argument("--keep-temp", action="store_true", help="Non cancellare la cartella temporanea (utile per debug)")
    args = parser.parse_args()

    print("1/5 - Parsing SRT...")
    segments = parse_srt(args.srt)
    print(f"    {len(segments)} segmenti trovati")

    if args.no_translate:
        for s in segments:
            s.text_tgt = s.text_src
    else:
        print(f"2/5 - Traduzione {args.source_lang} -> {args.target_lang}...")
        translate_segments(segments, source=args.source_lang, target=args.target_lang)

    total_duration_ms = get_duration_ms(args.video)

    workdir = tempfile.mkdtemp(prefix="dub_pipeline_")
    print(f"3/5 - Generazione TTS e sincronizzazione segmenti (workdir: {workdir})...")
    try:
        full_audio_path = build_full_track(
            segments, workdir, args.voice, args.rate, total_duration_ms, args.max_stretch
        )

        print("4/5 - Mux video + audio russo...")
        mux_video(args.video, full_audio_path, args.output)

        print(f"5/5 - Fatto: {args.output}")
    finally:
        if not args.keep_temp:
            shutil.rmtree(workdir, ignore_errors=True)
        else:
            print(f"File temporanei conservati in: {workdir}")


if __name__ == "__main__":
    main()
