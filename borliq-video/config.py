"""Loyihaning umumiy sozlamalari: sahnalar, matnlar, vaqtlar."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build"
OUTPUT = ROOT / "borliq_falsafasi.mp4"
INFOGRAPHIC = ROOT / "infografika.png"

W, H = 1920, 1080
FPS = 30
DURATION = 120  # soniya

VOICE = "uz-UZ-SardorNeural"

# Fon musiqasi: 01:50 dan 03:50 gacha (2 daqiqa)
MUSIC_START = 110.0
MUSIC_END = 230.0
MUSIC_VOLUME = 0.18      # ~ -15 dB
MUSIC_FADE_IN = 2.0
MUSIC_FADE_OUT = 4.0

# Har bir sahna: boshlanish/tugash (soniya), ovoz qaysi soniyada boshlanadi, matn
SCENES = [
    {
        "id": 1, "start": 0.0, "end": 25.0, "voice_offset": 2.0,
        "text": (
            "Tasavvur qiling: mutlaq yo'qlik. Na vaqt bor, na makon, na yulduzlar va na biz... "
            "Lekin ko'zingizni oching — atrofimizda cheksiz koinot, murakkab tabiat va hayot qaynamoqda. "
            "Falsafaning eng qadimiy bo'limi — Ontologiya, ya'ni borliq falsafasi ming yillardan beri "
            "bitta eng buyuk savolga javob izlaydi: Nima uchun umuman hech narsa emas, balki borliq mavjud?"
        ),
    },
    {
        "id": 2, "start": 25.0, "end": 55.0, "voice_offset": 0.8,
        "text": (
            "Qadimgi faylasuflar olamdagi barcha narsaning ilk asosini — substansiyani topishga uringanlar. "
            "Fales olamning asosi suv desa, Geraklit olov degan, Pifagor esa barchasi raqamlarda deb hisoblagan. "
            "Buyuk bobokalonimiz Abu Nasr Forobiy esa borliqni olti bosqichga bo'lib, barcha mavjudotning "
            "eng oliy sababchisi — Vojibul-vujud, ya'ni zaruriy mavjud bo'lgan Yaratuvchi ekanligini "
            "ilmiy-falsafiy asoslab bergan."
        ),
    },
    {
        "id": 3, "start": 55.0, "end": 95.0, "voice_offset": 1.5,
        "text": (
            "Zamonaviy astrofizika olamning yaralishini Katta portlash va koinotning tinimsiz kengayishi bilan izohlaydi. "
            "Eng hayratlanarlisi, bu ilmiy haqiqatlar o'n to'rt asr muqaddam Qur'oni Karimda aniq-tiniq bayon qilingan edi. "
            "Birinchidan, Anbiyo surasi o'ttizinchi oyatda osmonlar va yer avval bir-biriga yopishgan bir butun holatda "
            "bo'lgani, so'ngra ajratilgani va barcha tirik mavjudot suvdan yaratilgani aytiladi. "
            "Ikkinchidan, Zoriyot surasi qirq yettinchi oyatda: Osmonni Biz qudrat bilan bino qildik va albatta, "
            "Biz uni kengaytiruvchilarmiz, deyiladi."
        ),
    },
    {
        "id": 4, "start": 95.0, "end": 120.0, "voice_offset": 0.6,
        "text": (
            "Islom aqidasiga ko'ra, borliq o'z-o'zidan tasodifan paydo bo'lmagan. Olamdagi bunday mukammal tartib "
            "va qonuniyatlar azaliy va abadiy Yaratuvchining qudratiga dalolat qiladi — U biror ishni iroda qilsa, "
            "Bo'l! deydi va u bo'ladi. Ilm-fan olamning qanday ishlashini tushuntirsa, falsafa va e'tiqod uning "
            "nima uchun mavjudligini anglatadi. Xo'sh, aziz talabalar, sizningcha, ushbu cheksiz borliqda "
            "insonning o'rni va vazifasi nimadan iborat?"
        ),
    },
]

# Ovoz sahna oxiridan kamida shuncha oldin tugashi kerak
VOICE_TAIL_MARGIN = 0.5
