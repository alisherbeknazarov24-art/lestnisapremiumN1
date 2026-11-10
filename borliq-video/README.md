# Borliq falsafasi (Ontologiya) — avtomatik video

2 daqiqalik (120 s, 30 fps, 1920×1080) o'quv videosi: `borliq_falsafasi.mp4`.

## Ishga tushirish
```bash
sudo apt install ffmpeg          # FFmpeg kerak
pip install -r requirements.txt
python make_video.py             # ovoz -> render -> miks -> borliq_falsafasi.mp4
```
Papkada `infografika.png` va `music.mp3` (yoki `.m4a/.wav`) bo'lishi kerak.

## Bosqichlar
| Fayl | Vazifasi |
|---|---|
| `config.py` | Sahnalar, matnlar, vaqtlar, musiqa sozlamalari |
| `generate_voice.py` | edge-tts (`uz-UZ-SardorNeural`) ovozi + so'z vaqtlari. Sahnaga sig'masa tezlikni avtomatik oshiradi |
| `render.py` | Pillow + NumPy bilan kadrlar: yulduzlar, galaktika, Katta portlash, kartochkalar, subtitr. `--preview 10 60` bilan alohida kadrlarni ko'rish mumkin |
| `mix_audio.py` | Musiqa 01:50–03:50, 18% balandlik, 2 s fade-in / 4 s fade-out, ovozlar bilan miks |

## Subtitr
edge-tts'ning `WordBoundary` vaqtlari (SubMaker ishlatadigan ma'lumot) bo'yicha chiqadi: yarim shaffof
qora quticha, oq harflar, ayni aytilayotgan so'z oltin rangda.

## Sozlash
- Musiqa qismi: `config.py` → `MUSIC_START` / `MUSIC_END`.
- Matnni o'zgartirsangiz `python make_video.py` ni qayta ishga tushiring — animatsiyalar kalit so'zlarga
  (Fales, Geraklit, Forobiy, portlash, Birinchidan…) avtomatik bog'lanadi.
