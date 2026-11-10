"""Hammasini bitta buyruq bilan bajaradi:  python make_video.py

1) edge-tts ovozlari  2) kadrlar render  3) audio miks + yakuniy MP4
"""
import asyncio

import generate_voice
import mix_audio
import render
from config import BUILD

if __name__ == "__main__":
    asyncio.run(generate_voice.main())
    video = render.render_all()
    audio = mix_audio.mix()
    print("Tayyor:", mix_audio.mux(video, audio))
    print("Kesh fayllari:", BUILD)
