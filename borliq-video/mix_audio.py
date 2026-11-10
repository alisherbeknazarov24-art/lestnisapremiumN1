"""3-bosqich: ovozlar + fon musiqasini FFmpeg bilan birlashtiradi va videoga qo'shadi.

- musiqa: 01:50–03:50 qismi, 18% balandlik, 2 s fade-in, oxirgi 4 s fade-out
- har bir sahna ovozi o'z vaqtiga (adelay) qo'yiladi
"""
import glob
import subprocess

from config import (BUILD, DURATION, MUSIC_END, MUSIC_FADE_IN, MUSIC_FADE_OUT, MUSIC_START,
                    MUSIC_VOLUME, OUTPUT, ROOT, SCENES)


def find_music():
    for ext in ("mp3", "m4a", "wav", "aac", "ogg", "flac"):
        hits = glob.glob(str(ROOT / f"music.{ext}"))
        if hits:
            return hits[0]
    raise SystemExit("music.* fayli topilmadi")


def mix():
    music = find_music()
    seg = MUSIC_END - MUSIC_START
    cmd = ["ffmpeg", "-y", "-v", "error", "-ss", str(MUSIC_START), "-t", str(seg), "-i", music]
    for sc in SCENES:
        cmd += ["-i", str(BUILD / f"voice_{sc['id']}.mp3")]
    fmt = "aformat=sample_rates=48000:channel_layouts=stereo"
    f = [f"[0:a]{fmt},volume={MUSIC_VOLUME},afade=t=in:st=0:d={MUSIC_FADE_IN},"
         f"afade=t=out:st={DURATION - MUSIC_FADE_OUT}:d={MUSIC_FADE_OUT}[m]"]
    labels = ["[m]"]
    for i, sc in enumerate(SCENES, start=1):
        ms = int(round((sc["start"] + sc["voice_offset"]) * 1000))
        f.append(f"[{i}:a]{fmt},adelay={ms}|{ms}[v{i}]")
        labels.append(f"[v{i}]")
    f.append("".join(labels) + f"amix=inputs={len(labels)}:normalize=0:duration=longest,"
             f"atrim=0:{DURATION},alimiter=limit=0.95[out]")
    out = BUILD / "audio_mix.wav"
    cmd += ["-filter_complex", ";".join(f), "-map", "[out]", str(out)]
    subprocess.check_call(cmd)
    return out


def mux(video, audio):
    subprocess.check_call([
        "ffmpeg", "-y", "-v", "error", "-i", str(video), "-i", str(audio),
        "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-t", str(DURATION), "-movflags", "+faststart", str(OUTPUT)])
    return OUTPUT


if __name__ == "__main__":
    a = mix()
    print("Audio:", a)
    print("Video:", mux(BUILD / "video_only.mp4", a))
