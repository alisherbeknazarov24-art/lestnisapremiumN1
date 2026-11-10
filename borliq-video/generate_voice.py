"""1-bosqich: har bir sahna uchun edge-tts (uz-UZ-SardorNeural) bilan ovoz yaratadi.

Har bir sahna uchun build/voice_<n>.mp3 va so'z vaqtlari build/voice_<n>.json saqlanadi.
Agar ovoz sahnaga sig'masa, nutq tezligi avtomatik oshiriladi.
"""
import asyncio
import json
import os
import subprocess

import edge_tts

from config import BUILD, SCENES, VOICE, VOICE_TAIL_MARGIN


def proxy_url():
    return os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or None


def audio_duration(path):
    out = subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "csv=p=0", str(path)])
    return float(out.strip())


async def synth(text, rate, mp3_path):
    comm = edge_tts.Communicate(text, VOICE, rate=rate, boundary="WordBoundary",
                                proxy=proxy_url())
    words = []
    with open(mp3_path, "wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                words.append({
                    "text": chunk["text"],
                    "start": chunk["offset"] / 1e7,
                    "end": (chunk["offset"] + chunk["duration"]) / 1e7,
                })
    return words


async def main():
    BUILD.mkdir(exist_ok=True)
    for sc in SCENES:
        budget = sc["end"] - sc["start"] - sc["voice_offset"] - VOICE_TAIL_MARGIN
        mp3 = BUILD / f"voice_{sc['id']}.mp3"
        rate_pct = 0
        for _ in range(8):
            rate = f"{rate_pct:+d}%"
            words = await synth(sc["text"], rate, mp3)
            dur = audio_duration(mp3)
            print(f"Sahna {sc['id']}: tezlik {rate}, davomiylik {dur:.2f}s (limit {budget:.2f}s)")
            if dur <= budget:
                break
            # kerakli tezlashtirishni hisoblab, biroz zaxira bilan oshiramiz
            need = dur / budget
            rate_pct = int(round((1 + rate_pct / 100) * need * 100 - 100)) + 2
        else:
            raise SystemExit(f"Sahna {sc['id']} ovozi sig'madi")
        json.dump({"rate": rate, "duration": dur, "words": words},
                  open(BUILD / f"voice_{sc['id']}.json", "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    asyncio.run(main())
