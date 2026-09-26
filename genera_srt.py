#!/usr/bin/env python3
"""
Genera un file SRT da un audio/video usando faster-whisper (molto più veloce
della libreria openai-whisper originale, specialmente su GPU CUDA).

Installa con:
    pip install faster-whisper

Uso:
    python3 genera_srt.py --input video.mp4 --output tedesco.srt --lang de --device cuda --model medium

Note sui modelli (velocità/qualità, con GPU CUDA tipo la tua RTX):
    tiny, base   -> velocissimi, qualità bassa
    small        -> buon compromesso per parlato chiaro
    medium       -> consigliato per tedesco standard, ottimo rapporto qualità/tempo
    large-v3     -> massima qualità, più lento, serve per audio rumoroso o accenti forti

Se non hai GPU disponibile, usa --device cpu --compute-type int8 (più lento ma funziona).
"""

import argparse
import datetime as dt

from faster_whisper import WhisperModel


def format_timestamp(seconds: float) -> str:
    td = dt.timedelta(seconds=seconds)
    total_ms = int(td.total_seconds() * 1000)
    hours, rem = divmod(total_ms, 3600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def main():
    parser = argparse.ArgumentParser(description="Genera SRT con faster-whisper")
    parser.add_argument("--input", required=True, help="File audio o video di input")
    parser.add_argument("--output", required=True, help="File SRT di output")
    parser.add_argument("--lang", default="de", help="Lingua parlata nell'audio (default: de)")
    parser.add_argument("--model", default="medium", help="Modello whisper (tiny/base/small/medium/large-v3)")
    parser.add_argument("--device", default="cuda", help="cuda o cpu")
    parser.add_argument("--compute-type", default="float16", help="float16 (GPU), int8 (CPU) ecc.")
    args = parser.parse_args()

    print(f"Carico modello '{args.model}' su {args.device} ({args.compute_type})...")
    model = WhisperModel(args.model, device=args.device, compute_type=args.compute_type)

    print("Trascrizione in corso...")
    segments, info = model.transcribe(args.input, language=args.lang, vad_filter=True)

    print(f"Lingua rilevata: {info.language} (probabilità {info.language_probability:.2f})")

    with open(args.output, "w", encoding="utf-8") as f:
        for i, seg in enumerate(segments, start=1):
            f.write(f"{i}\n")
            f.write(f"{format_timestamp(seg.start)} --> {format_timestamp(seg.end)}\n")
            f.write(f"{seg.text.strip()}\n\n")
            print(f"[{format_timestamp(seg.start)} -> {format_timestamp(seg.end)}] {seg.text.strip()}")

    print(f"SRT salvato in: {args.output}")


if __name__ == "__main__":
    main()
