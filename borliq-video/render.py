"""2-bosqich: videoning vizual qismini chizadi (Pillow + NumPy) va FFmpeg bilan kodlaydi.

Uslub: to'q ko'k/qora koinot, oltin sarlavhalar, harakatlanuvchi yulduzlar,
protsedurali spiral galaktika, silliq fade/zoom animatsiyalar.
Ovozdagi kalit so'zlar vaqti (build/voice_<n>.json) bo'yicha elementlar sinxron chiqadi.

Ishlatish:
    python render.py                  # to'liq render -> build/video_only.mp4
    python render.py --preview 10 40  # berilgan soniyalardagi kadrlarni PNG qilib saqlaydi
"""
import argparse
import json
import math
import os
import subprocess
import sys
from multiprocessing import Pool

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

from config import BUILD, DURATION, FPS, H, INFOGRAPHIC, SCENES, W

# --------------------------------------------------------------------------- shriftlar
FONT_DIRS = ["/usr/share/fonts/truetype"]


def find_font(names):
    for n in names:
        for d in FONT_DIRS:
            for root, _, files in os.walk(d):
                if n in files:
                    return os.path.join(root, n)
    raise FileNotFoundError(names)


F_TITLE = find_font(["Caladea-Bold.ttf", "LiberationSerif-Bold.ttf", "DejaVuSerif-Bold.ttf"])
F_ITALIC = find_font(["Caladea-Italic.ttf", "LiberationSerif-Italic.ttf", "DejaVuSerif-Italic.ttf"])
F_SANS = find_font(["Carlito-Regular.ttf", "LiberationSans-Regular.ttf", "DejaVuSans.ttf"])
F_SANS_B = find_font(["Carlito-Bold.ttf", "LiberationSans-Bold.ttf", "DejaVuSans-Bold.ttf"])
F_ARABIC = find_font(["FreeSerif.ttf", "DejaVuSans.ttf"])

_font_cache = {}


def font(path, size):
    key = (path, size)
    if key not in _font_cache:
        _font_cache[key] = ImageFont.truetype(path, size)
    return _font_cache[key]


GOLD_STOPS = [(0.0, (255, 243, 200)), (0.42, (244, 206, 118)),
              (0.58, (208, 152, 58)), (1.0, (250, 214, 128))]
GOLD = (238, 198, 112)
CREAM = (246, 239, 222)
WHITE = (255, 255, 255)


def uz(s):
    """O'zbek lotin yozuvidagi apostroflarni chiroyli belgilarga almashtiradi."""
    for a, b in (("o'", "o‘"), ("O'", "O‘"), ("g'", "g‘"), ("G'", "G‘")):
        s = s.replace(a, b)
    return s.replace("'", "’")


# --------------------------------------------------------------------------- easing
def clamp01(x):
    return 0.0 if x < 0 else 1.0 if x > 1 else x


def smooth(x):
    x = clamp01(x)
    return x * x * (3 - 2 * x)


def ease_out(x):
    x = clamp01(x)
    return 1 - (1 - x) ** 3


def ramp(t, a, d):
    return smooth((t - a) / d) if d > 0 else float(t >= a)


def window(t, a, b, fi=0.7, fo=0.7):
    return ramp(t, a, fi) * (1 - ramp(t, b - fo, fo))


# --------------------------------------------------------------------------- rasm yordamchilari
def composite(dst, layer, x, y):
    """RGBA qatlamni dst ustiga (x, y) ga joylaydi, chegaradan chiqqan qismini qirqadi."""
    x, y = int(round(x)), int(round(y))
    lw, lh = layer.size
    dw, dh = dst.size
    sx0, sy0 = max(0, -x), max(0, -y)
    dx0, dy0 = max(0, x), max(0, y)
    w = min(lw - sx0, dw - dx0)
    h = min(lh - sy0, dh - dy0)
    if w <= 0 or h <= 0:
        return
    if sx0 or sy0 or w < lw or h < lh:
        layer = layer.crop((sx0, sy0, sx0 + w, sy0 + h))
    dst.alpha_composite(layer, (dx0, dy0))


def fade(img, a):
    if a >= 0.999:
        return img
    r, g, b, al = img.split()
    al = al.point(lambda v: int(v * a))
    return Image.merge("RGBA", (r, g, b, al))


def put(dst, layer, cx, cy, alpha=1.0, scale=1.0):
    if alpha <= 0.004 or layer is None:
        return
    if abs(scale - 1) > 0.002:
        layer = layer.resize((max(1, int(layer.width * scale)), max(1, int(layer.height * scale))),
                             Image.BILINEAR)
    layer = fade(layer, alpha)
    composite(dst, layer, cx - layer.width / 2, cy - layer.height / 2)


def gold_gradient(w, h):
    ys = np.linspace(0, 1, h)
    cols = np.zeros((h, 3), np.float32)
    for c in range(3):
        cols[:, c] = np.interp(ys, [s[0] for s in GOLD_STOPS], [s[1][c] for s in GOLD_STOPS])
    return Image.fromarray(np.repeat(cols[:, None, :], w, axis=1).astype(np.uint8), "RGB")


def text_layer(text, path, size, gold=False, color=CREAM, glow=0, shadow=True,
               glow_color=(255, 178, 70), glow_strength=0.75):
    f = font(path, size)
    bbox = f.getbbox(text)
    pad = int(glow * 3 + 14)
    w, h = bbox[2] - bbox[0] + 2 * pad, bbox[3] - bbox[1] + 2 * pad
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).text((pad - bbox[0], pad - bbox[1]), text, font=f, fill=255)
    if gold:
        rgb = gold_gradient(w, h - 2 * pad)
        full = Image.new("RGB", (w, h), GOLD_STOPS[-1][1])
        full.paste(rgb, (0, pad))
        rgb = full
    else:
        rgb = Image.new("RGB", (w, h), color)
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    if shadow:
        sh = mask.filter(ImageFilter.GaussianBlur(max(3, size // 18))).point(lambda v: int(v * 0.85))
        sl = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        sl.putalpha(sh)
        composite(out, sl, 0, max(2, size // 30))
    if glow:
        g = mask.filter(ImageFilter.GaussianBlur(glow)).point(lambda v: int(min(255, v * glow_strength * 1.6)))
        gl = Image.new("RGBA", (w, h), glow_color + (0,))
        gl.putalpha(g)
        out.alpha_composite(gl)
    t = rgb.convert("RGBA")
    t.putalpha(mask)
    out.alpha_composite(t)
    return out


def stack(layers, spacing=0):
    w = max(l.width for l in layers)
    h = sum(l.height for l in layers) + spacing * (len(layers) - 1)
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    y = 0
    for l in layers:
        out.alpha_composite(l, ((w - l.width) // 2, y))
        y += l.height + spacing
    return out


def wrap(text, path, size, max_w):
    f = font(path, size)
    lines, cur = [], ""
    for word in text.split():
        cand = (cur + " " + word).strip()
        if f.getlength(cand) <= max_w or not cur:
            cur = cand
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def text_block(text, path, size, max_w, spacing=-18, **kw):
    return stack([text_layer(l, path, size, **kw) for l in wrap(text, path, size, max_w)], spacing)


PANEL_PAD = 26


def panel(w, h, radius=26, fill=(7, 13, 34, 218), border=(214, 172, 88, 255), bw=3, glow=True):
    g = PANEL_PAD
    img = Image.new("RGBA", (w + 2 * g, h + 2 * g), (0, 0, 0, 0))
    if glow:
        m = Image.new("L", img.size, 0)
        ImageDraw.Draw(m).rounded_rectangle((g, g, g + w, g + h), radius, outline=255, width=bw + 4)
        m = m.filter(ImageFilter.GaussianBlur(10)).point(lambda v: int(v * 0.55))
        gl = Image.new("RGBA", img.size, (255, 180, 70, 0))
        gl.putalpha(m)
        img.alpha_composite(gl)
    body = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(body).rounded_rectangle((g, g, g + w, g + h), radius, fill=fill, outline=border, width=bw)
    img.alpha_composite(body)
    # yuqori qismida nozik yorug'lik
    hl = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(hl).rounded_rectangle((g + bw + 2, g + bw + 2, g + w - bw - 2, g + h // 3),
                                         radius - 4, fill=(120, 150, 255, 14))
    img.alpha_composite(hl)
    return img


# --------------------------------------------------------------------------- protsedurali teksturalar
def fft_blur(a, sigma):
    """2D Gauss xiralashtirish (FFT orqali), a: (H, W) float."""
    h, w = a.shape
    fy = np.fft.fftfreq(h)[:, None]
    fx = np.fft.rfftfreq(w)[None, :]
    k = np.exp(-2 * (math.pi * sigma) ** 2 * (fx ** 2 + fy ** 2))
    return np.fft.irfft2(np.fft.rfft2(a) * k, s=a.shape)


def fractal_noise(w, h, seed, octaves=6, base=4):
    rng = np.random.default_rng(seed)
    out = np.zeros((h, w), np.float32)
    amp, total = 1.0, 0.0
    for o in range(octaves):
        gw, gh = base * 2 ** o + 1, max(2, int((base * 2 ** o) * h / w) + 1)
        g = (rng.random((gh, gw)) * 255).astype(np.uint8)
        up = np.asarray(Image.fromarray(g).resize((w, h), Image.BICUBIC), np.float32) / 255
        out += up * amp
        total += amp
        amp *= 0.5
    return out / total


def make_galaxy(n_size=1200, seed=7):
    rng = np.random.default_rng(seed)
    N = n_size
    chans = np.zeros((3, N, N), np.float64)

    def splat(x, y, color, weight=1.0):
        hist, _, _ = np.histogram2d(y, x, bins=N, range=[[-1, 1], [-1, 1]])
        for c in range(3):
            chans[c] += hist * color[c] * weight

    # spiral qo'llar
    n = 260000
    r = np.clip(rng.gamma(2.2, 0.15, n), 0.02, 0.98)
    arm = rng.integers(0, 2, n)
    theta = arm * math.pi + 2.6 * np.log(r / 0.05) + rng.normal(0, 0.32, n) * (0.6 + 0.6 * (1 - r))
    rj = r * (1 + rng.normal(0, 0.05, n))
    x, y = rj * np.cos(theta), rj * np.sin(theta)
    splat(x, y, (0.55, 0.70, 1.0))
    # pushti yulduz hosil bo'lish hududlari
    sel = (r > 0.25) & (rng.random(n) < 0.02)
    splat(x[sel], y[sel], (1.0, 0.45, 0.78), 4.0)
    # oq-moviy yorqin yulduzlar
    sel = rng.random(n) < 0.01
    splat(x[sel], y[sel], (0.9, 0.95, 1.0), 6.0)
    # markaziy qavariq (bulge)
    m = 90000
    br = np.abs(rng.normal(0, 0.09, m))
    bt = rng.random(m) * 2 * math.pi
    splat(br * np.cos(bt), br * np.sin(bt) * 0.85, (1.0, 0.82, 0.55), 1.2)
    # siyrak halo
    k = 30000
    hr = rng.random(k) ** 0.6
    ht = rng.random(k) * 2 * math.pi
    splat(hr * np.cos(ht), hr * np.sin(ht), (0.6, 0.65, 0.9), 0.5)

    img = np.zeros((N, N, 3))
    for c in range(3):
        a = chans[c]
        img[..., c] = fft_blur(a, 0.8) + 0.6 * fft_blur(a, 3.5) + 0.45 * fft_blur(a, 14)
    yy, xx = np.mgrid[-1:1:N * 1j, -1:1:N * 1j]
    rr = np.sqrt(xx ** 2 + yy ** 2)
    core = np.exp(-(rr / 0.07) ** 2) * 1.0 + np.exp(-(rr / 0.2) ** 2) * 0.25
    for c, v in enumerate((1.0, 0.88, 0.68)):
        img[..., c] = img[..., c] / np.percentile(img[..., 1], 99.7) + core * v
    img = 1 - np.exp(-1.6 * np.clip(img, 0, None))
    img *= (1 - np.clip((rr - 0.85) / 0.15, 0, 1))[..., None]
    return (np.clip(img, 0, 1) * 255).astype(np.uint8)


def make_nebula(w=2700, h=1500, seed=11):
    n1 = fractal_noise(w, h, seed, octaves=7, base=3)
    n2 = fractal_noise(w, h, seed + 1, octaves=7, base=3)
    n3 = fractal_noise(w, h, seed + 2, octaves=6, base=5)
    a = np.clip((n1 - 0.45) * 2.6, 0, 1) ** 1.7
    b = np.clip((n2 - 0.5) * 2.8, 0, 1) ** 1.8
    dust = np.clip((n3 - 0.35) * 1.8, 0, 1)
    img = (a[..., None] * np.array([22, 55, 130]) + b[..., None] * np.array([80, 30, 110])) * (0.55 + 0.45 * dust[..., None])
    return np.clip(img, 0, 255).astype(np.uint8)


def make_sphere(R, kind, seed):
    S = 2 * R + 4
    yy, xx = np.mgrid[0:S, 0:S].astype(np.float32)
    nx, ny = (xx - S / 2) / R, (yy - S / 2) / R
    rr = nx ** 2 + ny ** 2
    nz = np.sqrt(np.clip(1 - rr, 0, 1))
    n1 = fractal_noise(S, S, seed, octaves=6, base=3)
    n2 = fractal_noise(S, S, seed + 5, octaves=6, base=5)
    if kind == "blue":
        L = np.array([0.85, -0.15, 0.5])
        lo, hi = np.array([8, 30, 95]), np.array([60, 140, 235])
        col = lo + (hi - lo) * n1[..., None]
        cloud = np.clip((n2 - 0.55) * 4, 0, 1)[..., None]
        col = col * (1 - cloud * 0.8) + np.array([235, 245, 255]) * cloud * 0.8
        amb = 0.08
    else:
        L = np.array([-0.85, -0.15, 0.5])
        lo, hi = np.array([190, 50, 8]), np.array([255, 205, 100])
        col = lo + (hi - lo) * (n1 * 0.6 + n2 * 0.4)[..., None]
        amb = 0.45
    L = L / np.linalg.norm(L)
    diff = np.clip(nx * L[0] + ny * L[1] + nz * L[2], 0, 1)
    shade = amb + (1 - amb) * diff
    rgb = col * shade[..., None]
    rim = ((1 - nz) ** 3)[..., None] * (np.array([90, 160, 255]) if kind == "blue" else np.array([255, 150, 50]))
    rgb = np.clip(rgb + rim * 0.9, 0, 255)
    alpha = np.clip((1 - np.sqrt(rr)) * R, 0, 1) * 255
    return Image.fromarray(np.dstack([rgb, alpha]).astype(np.uint8), "RGBA")


def gauss_sprite(size, sigma, color, spikes=False):
    c = size // 2
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32) - c
    g = np.exp(-(xx ** 2 + yy ** 2) / (2 * sigma ** 2))
    if spikes:
        g += 0.5 * np.exp(-(yy ** 2) / 1.2) * np.exp(-np.abs(xx) / (size * 0.12))
        g += 0.5 * np.exp(-(xx ** 2) / 1.2) * np.exp(-np.abs(yy) / (size * 0.12))
    return g[..., None] * np.array(color, np.float32)[None, None, :]


def add_arr(buf, arr, cx, cy, gain=1.0):
    h, w = arr.shape[:2]
    x0, y0 = int(round(cx - w / 2)), int(round(cy - h / 2))
    sx0, sy0 = max(0, -x0), max(0, -y0)
    dx0, dy0 = max(0, x0), max(0, y0)
    ww, hh = min(w - sx0, W - dx0), min(h - sy0, H - dy0)
    if ww <= 0 or hh <= 0 or gain <= 0:
        return
    buf[dy0:dy0 + hh, dx0:dx0 + ww] += arr[sy0:sy0 + hh, sx0:sx0 + ww] * gain


def alpha_arr(buf, img, cx, cy, alpha=1.0):
    """RGBA rasmni numpy buferiga oddiy (alpha) aralashtirish bilan joylaydi."""
    a = np.asarray(img, np.float32)
    h, w = a.shape[:2]
    x0, y0 = int(round(cx - w / 2)), int(round(cy - h / 2))
    sx0, sy0 = max(0, -x0), max(0, -y0)
    dx0, dy0 = max(0, x0), max(0, y0)
    ww, hh = min(w - sx0, W - dx0), min(h - sy0, H - dy0)
    if ww <= 0 or hh <= 0 or alpha <= 0:
        return
    src = a[sy0:sy0 + hh, sx0:sx0 + ww]
    al = src[..., 3:4] / 255 * alpha
    dst = buf[dy0:dy0 + hh, dx0:dx0 + ww]
    dst *= (1 - al)
    dst += src[..., :3] * al


# --------------------------------------------------------------------------- vaqt jadvali
def load_timeline():
    tl = {"words": {}, "subs": []}
    for sc in SCENES:
        d = json.load(open(BUILD / f"voice_{sc['id']}.json"))
        base = sc["start"] + sc["voice_offset"]
        words = d["words"]
        tl["words"][sc["id"]] = [(w["text"], base + w["start"], base + w["end"]) for w in words]
        tl["subs"] += build_subs(sc["text"], words, base)
    return tl


def build_subs(text, words, base):
    spans, pos = [], 0
    for w in words:
        i = text.find(w["text"], pos)
        if i < 0:
            i = pos
        spans.append((i, i + len(w["text"])))
        pos = i + len(w["text"])
    chunks, cur = [], 0
    for k in range(len(words)):
        nxt = spans[k + 1][0] if k + 1 < len(words) else len(text)
        between = text[spans[k][1]:nxt]
        clen = spans[k][1] - spans[cur][0]
        if (k == len(words) - 1 or any(c in between for c in ".?!:;")
                or (clen >= 34 and any(c in between for c in ",—")) or clen >= 50):
            tail = "".join(c for c in between.strip() if c in ".?!")
            ctext = text[spans[cur][0]:spans[k][1]] + tail
            # har bir ko'rinadigan so'z (token) uchun boshlanish vaqti
            tokens, tstarts, cpos = ctext.split(), [], 0
            tok_pos = []
            for tok in tokens:
                i = ctext.find(tok, cpos)
                tok_pos.append((i, i + len(tok)))
                cpos = i + len(tok)
            off = spans[cur][0]
            last = base + words[cur]["start"]
            for (a, b) in tok_pos:
                st = None
                for j in range(cur, k + 1):
                    if a <= spans[j][0] - off < b:
                        st = base + words[j]["start"]
                        break
                last = st if st is not None else last
                tstarts.append(last)
            chunks.append([base + words[cur]["start"], base + words[k]["end"] + 0.3, ctext, tokens, tstarts])
            cur = k + 1
    for a, b in zip(chunks, chunks[1:]):
        a[1] = min(a[1], b[0])
    return chunks


def kw(tl, scene, word, nth=0, default=None):
    hits = [t0 for (w, t0, _) in tl["words"][scene] if w.lower().startswith(word.lower())]
    if len(hits) > nth:
        return hits[nth]
    if default is not None:
        return default
    raise KeyError(f"{word} topilmadi (sahna {scene})")


# --------------------------------------------------------------------------- renderer
class Renderer:
    def __init__(self, tl):
        self.tl = tl
        self.cx, self.cy = W / 2, H / 2
        self.t = {
            "open": kw(tl, 1, "oching"), "falsafa": kw(tl, 1, "Falsafaning"),
            "onto": kw(tl, 1, "Ontologiya"), "nima": kw(tl, 1, "Nima"),
            "fales": kw(tl, 2, "Fales"), "geraklit": kw(tl, 2, "Geraklit"),
            "pifagor": kw(tl, 2, "Pifagor"), "forobiy": kw(tl, 2, "Forobiy"),
            "olti": kw(tl, 2, "olti"), "vv": kw(tl, 2, "Vojibul"),
            "katta": kw(tl, 3, "Katta"), "portlash": kw(tl, 3, "portlash"),
            "birinchi": kw(tl, 3, "Birinchidan"), "ikkinchi": kw(tl, 3, "Ikkinchidan"),
            "xosh": kw(tl, 4, "Xo'sh"), "bol": kw(tl, 4, "Bo'l"),
        }
        self._load_textures()
        self._build_layers()
        self._init_stars()
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        self.rmap = np.sqrt((xx - self.cx) ** 2 + (yy - 520) ** 2)
        d = np.sqrt(((xx - self.cx) / W) ** 2 + ((yy - self.cy) / H) ** 2)
        self.bg = np.dstack([4 + 10 * np.exp(-d * 3), 6 + 14 * np.exp(-d * 3), 14 + 30 * np.exp(-d * 2.6)]).astype(np.float32)
        self.sub_cache = {}

    # ---- teksturalar
    def _load_textures(self):
        self.galaxy = Image.fromarray(np.load(BUILD / "galaxy.npy"))
        self.nebula = np.load(BUILD / "nebula.npy").astype(np.float32)
        self.sph_blue = Image.open(BUILD / "sphere_blue.png")
        self.sph_orange = Image.open(BUILD / "sphere_orange.png")
        self.halo_blue = gauss_sprite(700, 150, (40, 90, 200))
        self.halo_orange = gauss_sprite(700, 150, (230, 110, 30))
        sw, sh = 260, 1000
        yy, xx = np.mgrid[0:sh, 0:sw].astype(np.float32)
        dx, dy = xx - sw / 2, yy - sh / 2
        seam = np.exp(-(dx / 6) ** 2) * np.exp(-(dy / 260) ** 2) + 0.5 * np.exp(-(dx / 35) ** 2) * np.exp(-(dy / 200) ** 2)
        seam += 0.8 * np.exp(-(dx ** 2 + dy ** 2) / (2 * 45 ** 2))
        self.seam = seam[..., None] * np.array([255, 245, 225], np.float32)
        self.star_small = gauss_sprite(15, 1.3, (255, 255, 255))
        self.star_big = gauss_sprite(71, 1.8, (255, 255, 255), spikes=True)
        rng = np.random.default_rng(5)
        n = 2600
        ang = rng.random(n) * 2 * math.pi
        self.debris_dir = np.stack([np.cos(ang), np.sin(ang)], 1)
        self.debris_speed = rng.lognormal(math.log(420), 0.55, n)
        mix = rng.random(n)
        self.debris_col = np.where(mix[:, None] < 0.5, [255, 170, 80], np.where(mix[:, None] < 0.8, [255, 240, 220], [140, 180, 255])).astype(np.float32)
        info = Image.open(INFOGRAPHIC).convert("RGB")
        s = min(info.size)
        self.info = info.crop(((info.width - s) // 2, (info.height - s) // 2,
                               (info.width - s) // 2 + s, (info.height - s) // 2 + s))

    # ---- statik matn/karta qatlamlari
    def _build_layers(self):
        L = {}
        L["title1"] = text_layer("BORLIQ FALSAFASI", F_TITLE, 140, gold=True, glow=20)
        L["onto"] = text_layer("(ONTOLOGIYA)", F_TITLE, 78, gold=True, glow=12)
        L["q1"] = text_layer(uz("Nima uchun hech narsa emas, balki borliq mavjud?"), F_ITALIC, 56, color=CREAM, glow=10,
                             glow_color=(120, 160, 255), glow_strength=0.5)
        L["title2"] = text_layer(uz("Substansiya — olamning ilk asosi"), F_TITLE, 78, gold=True, glow=14)
        L["cards"] = [
            self._phil_card("Fales", "SUV", "mil. av. VII–VI asr", "water"),
            self._phil_card("Geraklit", "OLOV", "mil. av. VI–V asr", "fire"),
            self._phil_card("Pifagor", "RAQAMLAR", "mil. av. VI asr", "numbers"),
        ]
        L["farabi_h"] = text_layer("Abu Nasr Forobiy: Vojibul-vujud (6 bosqich)", F_TITLE, 52, gold=True, glow=10)
        labels = [
            "1. Vojibul-vujud — Birinchi sabab (Yaratuvchi)",
            "2. Ikkinchi sabablar — samoviy aqllar",
            "3. Faol aql",
            "4. Jon (nafs)",
            "5. Shakl (surat)",
            "6. Modda (materiya)",
        ]
        L["bars"] = [self._bar(820 + i * 105, 60, labels[i], i == 0) for i in range(6)]
        L["title3"] = text_layer("Katta portlash va koinotning kengayishi", F_TITLE, 64, gold=True, glow=12)
        L["ayah1"] = self._ayah_card(
            "1", "Anbiyo surasi, 30-oyat",
            ["أَنَّ السَّمَاوَاتِ وَالْأَرْضَ كَانَتَا رَتْقًا فَفَتَقْنَاهُمَا", "وَجَعَلْنَا مِنَ الْمَاءِ كُلَّ شَيْءٍ حَيٍّ"],
            "Osmonlar va yerning ajratilishi hamda suvdan hayot yaralishi",
            uz("“…osmonlar va yer bir-biriga yopishgan holda bo'lganini, bas, Biz ularni ajratganimizni "
               "va har bir tirik narsani suvdan qilganimizni ko'rmadilarmi?”"))
        L["ayah2"] = self._ayah_card(
            "2", "Zoriyot surasi, 47-oyat",
            ["وَالسَّمَاءَ بَنَيْنَاهَا بِأَيْدٍ", "وَإِنَّا لَمُوسِعُونَ"],
            "Koinotning tinimsiz kengayishi",
            "“Osmonni Biz qudrat bilan bino qildik va albatta, Biz uni kengaytiruvchilarmiz.”")
        # infografika ramkasi
        self.info_size = 830
        fr = Image.new("RGBA", (self.info_size + 120, self.info_size + 120), (0, 0, 0, 0))
        m = Image.new("L", fr.size, 0)
        ImageDraw.Draw(m).rectangle((60, 60, 60 + self.info_size, 60 + self.info_size), outline=255, width=14)
        m = m.filter(ImageFilter.GaussianBlur(18))
        gl = Image.new("RGBA", fr.size, (255, 185, 80, 0))
        gl.putalpha(m)
        fr.alpha_composite(gl)
        d = ImageDraw.Draw(fr)
        d.rectangle((52, 52, 68 + self.info_size, 68 + self.info_size), outline=(214, 172, 88, 255), width=5)
        d.rectangle((46, 46, 74 + self.info_size, 74 + self.info_size), outline=(150, 110, 50, 200), width=2)
        for (x, y) in ((46, 46), (74 + self.info_size, 46), (46, 74 + self.info_size), (74 + self.info_size, 74 + self.info_size)):
            d.regular_polygon((x, y, 14), 4, rotation=45, fill=(255, 220, 140, 255))
        L["frame"] = fr
        q = stack([text_layer("Cheksiz borliqda insonning", F_TITLE, 76, gold=True, glow=16),
                   text_layer(uz("o'rni va vazifasi nimadan iborat?"), F_TITLE, 76, gold=True, glow=16)], -22)
        qp = panel(q.width + 80, q.height + 50, fill=(5, 9, 26, 225))
        composite(qp, q, (qp.width - q.width) // 2, (qp.height - q.height) // 2)
        L["q_final"] = qp
        self.L = L

    def _icon(self, kind, size=130):
        S = size * 2  # supersampling
        img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        c = S // 2
        d.ellipse((6, 6, S - 6, S - 6), fill=(14, 24, 60, 255), outline=(214, 172, 88, 255), width=6)
        if kind == "water":
            pts = [(c, 40)]
            for a in np.linspace(-math.pi * 0.15, math.pi * 1.15, 40):
                pts.append((c + 58 * math.cos(a), 150 + 58 * math.sin(a)))
            d.polygon(pts, fill=(70, 150, 245, 255))
            d.ellipse((c - 30, 130, c - 12, 170), fill=(200, 230, 255, 200))
            for i, y in enumerate((222, 236)):
                d.arc((c - 70, y - 14, c, y + 14), 200, 340, fill=(120, 190, 255, 255), width=5)
                d.arc((c, y - 14, c + 70, y + 14), 200, 340, fill=(120, 190, 255, 255), width=5)
        elif kind == "fire":
            for col, sc_ in (((235, 80, 20, 255), 1.0), ((255, 160, 40, 255), 0.72), ((255, 235, 140, 255), 0.42)):
                pts = []
                for a in np.linspace(0, 2 * math.pi, 60):
                    rr = 62 * sc_
                    x = c + rr * math.sin(a) * (0.9)
                    y = 160 + rr * math.cos(a) * 0.9
                    if math.cos(a) < 0:  # yuqori qismi uchli
                        y = 160 + rr * math.cos(a) * 1.9
                        x = c + rr * math.sin(a) * (1 + math.cos(a) * 0.35)
                    pts.append((x, y + 20 * (1 - sc_)))
                d.polygon(pts, fill=col)
        else:  # tetraktis - Pifagorning 10 nuqtasi
            r = 13
            for row in range(4):
                for k in range(row + 1):
                    x = c + (k - row / 2) * 44
                    y = 70 + row * 40
                    d.ellipse((x - r, y - r, x + r, y + r), fill=(255, 215, 120, 255))
            f = font(F_TITLE, 46)
            d.text((c, 238), "1 · 2 · 3 · 4", font=f, fill=(246, 239, 222, 255), anchor="mm")
        return img.resize((size, size), Image.LANCZOS)

    def _phil_card(self, name, element, era, icon):
        w, h = 470, 270
        card = panel(w, h)
        g = PANEL_PAD
        ic = self._icon(icon)
        composite(card, ic, g + (w - ic.width) // 2, g + 14)
        put(card, text_layer(name, F_TITLE, 50, gold=True, glow=6), g + w / 2, g + 175)
        put(card, text_layer(element, F_SANS_B, 38, color=WHITE, shadow=False), g + w / 2, g + 218)
        put(card, text_layer(era, F_ITALIC, 26, color=(190, 200, 230), shadow=False), g + w / 2, g + 250)
        return card

    def _bar(self, w, h, label, top):
        img = Image.new("RGBA", (w + 60, h + 60), (0, 0, 0, 0))
        g = 30
        if top:
            m = Image.new("L", img.size, 0)
            ImageDraw.Draw(m).rounded_rectangle((g, g, g + w, g + h), 16, fill=255)
            m = m.filter(ImageFilter.GaussianBlur(14))
            gl = Image.new("RGBA", img.size, (255, 190, 80, 0))
            gl.putalpha(m)
            img.alpha_composite(gl)
            fill = gold_gradient(w, h).convert("RGBA")
            mask = Image.new("L", (w, h), 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), 16, fill=255)
            fill.putalpha(mask)
            img.alpha_composite(fill, (g, g))
            t = text_layer(label, F_SANS_B, 33, color=(40, 22, 4), shadow=False)
        else:
            ImageDraw.Draw(img).rounded_rectangle((g, g, g + w, g + h), 16, fill=(12, 22, 58, 225),
                                                  outline=(214, 172, 88, 255), width=3)
            t = text_layer(label, F_SANS_B, 32, color=CREAM, shadow=False)
        put(img, t, img.width / 2, img.height / 2)
        return img

    def _ayah_card(self, num, head, arabic, gist, quote):
        w = 600
        parts = []
        hl = text_layer(head, F_TITLE, 44, gold=True, glow=8)
        parts.append(("h", hl))
        for line in arabic:
            parts.append(("a", text_layer(line, F_ARABIC, 42, color=(255, 236, 190), glow=6, glow_strength=0.4)))
        parts.append(("div", None))
        parts.append(("g", text_block(gist, F_SANS_B, 35, w - 70, spacing=-20, color=WHITE)))
        parts.append(("q", text_block(quote, F_ITALIC, 29, w - 70, spacing=-22, color=(205, 212, 235), shadow=False)))
        heights = {"div": 26}
        h = 40 + sum(heights.get(k, l.height if l else 0) for k, l in parts) + 30
        card = panel(w, h)
        g = PANEL_PAD
        y = g + 24
        for k, l in parts:
            if k == "div":
                d = ImageDraw.Draw(card)
                cy = y + 13
                d.line((g + 90, cy, g + w / 2 - 18, cy), fill=(214, 172, 88, 255), width=2)
                d.line((g + w / 2 + 18, cy, g + w - 90, cy), fill=(214, 172, 88, 255), width=2)
                d.regular_polygon((g + w / 2, cy, 8), 4, rotation=45, fill=(255, 220, 140, 255))
                y += 26
                continue
            composite(card, l, g + (w - l.width) / 2, y)
            y += l.height
        # raqamli nishon
        badge = Image.new("RGBA", (76, 76), (0, 0, 0, 0))
        bd = ImageDraw.Draw(badge)
        bd.ellipse((4, 4, 72, 72), fill=(236, 190, 100, 255), outline=(255, 236, 180, 255), width=3)
        bd.text((38, 39), num, font=font(F_TITLE, 44), fill=(40, 22, 4, 255), anchor="mm")
        composite(card, badge, g - 18, g - 18)
        return card

    # ---- yulduzlar
    def _init_stars(self):
        rng = np.random.default_rng(3)
        n = 1800
        self.st_xy = np.stack([(rng.random(n) - 0.5) * W * 1.35, (rng.random(n) - 0.5) * H * 1.35], 1)
        self.st_z = rng.random(n) * 0.8 + 0.2
        self.st_b = np.clip(rng.pareto(2.2, n) * 0.25 + 0.12, 0, 1.6)
        self.st_phase = rng.random(n) * 2 * math.pi
        self.st_freq = rng.random(n) * 2.0 + 0.6
        tint = rng.random(n)
        self.st_col = np.where(tint[:, None] < 0.2, [255, 210, 170], np.where(tint[:, None] < 0.55, [190, 210, 255], [255, 255, 255])).astype(np.float32)
        early = rng.random(n) < 0.07
        to = self.t["open"]
        self.st_app = np.where(early, rng.uniform(0.8, 4.0, n), rng.uniform(to - 0.6, to + 2.8, n))
        order = np.argsort(-self.st_b)
        self.st_bright = order[:150]
        self.st_spike = order[:14]

    def expansion(self, t):
        tb = self.t["portlash"]
        if t < tb:
            return 0.0
        dt = min(t, 95.0) - tb
        return 0.28 * ease_out(dt / 8) + 0.006 * dt

    def draw_stars(self, buf, t, gain=1.0):
        E = self.expansion(t)
        scale = np.exp(E * self.st_z)[:, None]
        drift = np.stack([-7 * self.st_z * t, -1.8 * self.st_z * t], 1)
        p = self.st_xy * scale + drift
        fw, fh = W * 1.35, H * 1.35
        p[:, 0] = (p[:, 0] + fw / 2) % fw - fw / 2 + self.cx
        p[:, 1] = (p[:, 1] + fh / 2) % fh - fh / 2 + self.cy
        app = np.clip((t - self.st_app) / 1.2, 0, 1)
        tw = 0.72 + 0.28 * np.sin(self.st_freq * t + self.st_phase)
        val = self.st_b * tw * app * gain
        # mayda yulduzlar: bilinear taqsimlash (silliq harakat uchun)
        x, y = p[:, 0], p[:, 1]
        ok = (x >= 0) & (x < W - 1) & (y >= 0) & (y < H - 1) & (val > 0.005)
        x, y, v, col = x[ok], y[ok], val[ok], self.st_col[ok]
        x0, y0 = np.floor(x).astype(int), np.floor(y).astype(int)
        fx, fy = x - x0, y - y0
        flat = buf.reshape(-1, 3)
        for dx, dy, wgt in ((0, 0, (1 - fx) * (1 - fy)), (1, 0, fx * (1 - fy)), (0, 1, (1 - fx) * fy), (1, 1, fx * fy)):
            np.add.at(flat, (y0 + dy) * W + (x0 + dx), col * (v * wgt)[:, None])
        # yorqin yulduzlar porlashi
        for i in self.st_bright:
            if val[i] < 0.02:
                continue
            spr = self.star_big if i in self.st_spike else self.star_small
            add_arr(buf, spr, p[i, 0], p[i, 1], val[i] * (0.55 if i in self.st_spike else 0.35))

    # ---- galaktika
    def draw_galaxy(self, buf, cx, cy, width, angle, gain, tilt=0.55, pa=-22):
        if gain <= 0.004 or width < 8:
            return
        s = int(width)
        g = self.galaxy.resize((s, s), Image.BILINEAR).rotate(angle, Image.BILINEAR)
        g = g.resize((s, max(2, int(s * tilt))), Image.BILINEAR).rotate(pa, Image.BILINEAR, expand=True)
        add_arr(buf, np.asarray(g, np.float32), cx, cy, gain)

    # ---- bitta kadr
    def frame(self, fi):
        t = fi / FPS
        T = self.t
        buf = self.bg.copy()

        # tumanlik (sekin suzadi)
        neb_gain = 0.25 + 0.75 * ramp(t, T["open"] - 0.5, 4.0)
        if t > T["portlash"]:
            neb_gain += 0.25 * window(t, T["portlash"], 95, 2, 2)
        ox, oy = int(220 + 4.2 * t), int(160 + 1.4 * t)
        buf += self.nebula[oy:oy + H, ox:ox + W] * (neb_gain * 0.85)
        self.draw_stars(buf, t)

        img = None
        layers = []  # (layer, cx, cy, alpha, scale)

        # ================= 1-SAHNA
        if t < 25.2:
            to, tf = T["open"], T["falsafa"]
            g = ramp(t, to + 0.2, 3.5) * (1 - ramp(t, 23.6, 1.5)) * (1 - 0.35 * ramp(t, tf, 1.5))
            self.draw_galaxy(buf, 960, 470, 560 + 26 * max(0, t - to), -4.5 * t, g)
            out = 1 - ramp(t, 24.3, 0.7)
            a = ramp(t, tf, 1.3) * out
            layers.append((self.L["title1"], 960, 420, a, 0.9 + 0.1 * ease_out((t - tf) / 1.6)))
            a = ramp(t, T["onto"], 1.0) * out
            layers.append((self.L["onto"], 960, 548, a, 0.94 + 0.06 * ease_out((t - T["onto"]) / 1.2)))
            orn = ramp(t, T["onto"] + 0.3, 1.2) * out
            a = ramp(t, T["nima"], 1.2) * out
            layers.append((self.L["q1"], 960, 712 + 18 * (1 - ease_out((t - T["nima"]) / 1.4)), a, 1.0))
            self._ornament_t = (960, 628, 330 * orn, orn)
        else:
            self._ornament_t = None

        # ================= 2-SAHNA
        if 24.8 < t < 55.2:
            win = window(t, 25.0, 55.0, 0.8, 0.7)
            layers.append((self.L["title2"], 960, 105, win * ramp(t, 25.2, 1.0), 0.95 + 0.05 * ease_out((t - 25.2) / 1.2)))
            k = ease_out((t - (T["forobiy"] - 0.3)) / 1.2)
            sc_ = 1 - 0.4 * k
            ys = 360 - (360 - 250) * k
            xs = [960 - 540 * (1 - 0.32 * k), 960, 960 + 540 * (1 - 0.32 * k)]
            for i, key in enumerate(("fales", "geraklit", "pifagor")):
                ta = T[key] - 0.25
                a = ramp(t, ta, 0.8) * win
                layers.append((self.L["cards"][i], xs[i], ys + 40 * (1 - ease_out((t - ta) / 1.0)), a, sc_))
            a = ramp(t, T["forobiy"], 1.0) * win
            layers.append((self.L["farabi_h"], 960, 385, a, 1.0))
            t0, t1 = T["olti"], T["vv"]
            for i in range(6):
                ti = t0 + (5 - i) / 5 * (t1 - t0) - 0.2
                a = ramp(t, ti, 0.7) * win
                pulse = 1.0
                if i == 0 and t > t1:
                    pulse = 1 + 0.03 * math.sin((t - t1) * 4) * math.exp(-(t - t1) * 0.3)
                layers.append((self.L["bars"][i], 960, 462 + i * 72 + 18 * (1 - ease_out((t - ti) / 0.9)), a, pulse))

        # ================= 3-SAHNA
        if 54.8 < t < 95.2:
            tk, tb = T["katta"], T["portlash"]
            win = window(t, 55.0, 95.0, 0.8, 0.8)
            cy = 520
            R = 200
            sep = ease_out((t - tk) / 3.2) * 950
            a_sph = ramp(t, 55.0, 1.0) * (1 - ramp(t, tb + 0.6, 2.6))
            if a_sph > 0:
                bx, ox_ = 960 - R + 10 - sep, 960 + R - 10 + sep
                add_arr(buf, self.halo_blue, bx, cy, a_sph * 0.5)
                add_arr(buf, self.halo_orange, ox_, cy, a_sph * 0.6)
                alpha_arr(buf, self.sph_blue, bx, cy, a_sph)
                alpha_arr(buf, self.sph_orange, ox_, cy, a_sph)
            # chok (ikki jism orasidagi yorug'lik) va portlash chaqnashi
            pre = ramp(t, 55.3, 1.0) * (0.7 + 0.3 * math.sin(t * 5)) * (1 - ramp(t, tb, 0.4))
            add_arr(buf, self.seam, 960, cy, pre * 0.9 * win)
            if t >= tk - 0.2:
                dt = t - tb
                if dt < 0:
                    I = 0.4 * ramp(t, tk - 0.2, tb - tk + 0.2)
                    rad = 160
                else:
                    I = math.exp(-dt / 0.55) * 1.6 + 0.15 * math.exp(-dt / 3)
                    rad = 220 + 1000 * ease_out(dt / 2.5)
                if I > 0.01:
                    fl = np.exp(-(self.rmap / rad) ** 2) * (I * 255)
                    buf += fl[..., None] * np.array([1.0, 0.95, 0.88], np.float32)
                if 0 <= dt < 3.2:
                    r_ = 60 + 1250 * ease_out(dt / 3.2)
                    wdt = 16 + 34 * dt
                    ring = np.exp(-((self.rmap - r_) / wdt) ** 2) * (170 * (1 - dt / 3.2) ** 1.5)
                    buf += ring[..., None] * np.array([0.6, 0.75, 1.0], np.float32)
                if 0 <= dt < 7:
                    dist = self.debris_speed * (1 - math.exp(-1.1 * dt)) / 1.1
                    pos = np.array([960, cy]) + self.debris_dir * dist[:, None]
                    v = math.exp(-dt / 2.2) * 1.6
                    x, y = pos[:, 0], pos[:, 1]
                    ok = (x >= 1) & (x < W - 2) & (y >= 1) & (y < H - 2)
                    xi, yi = x[ok].astype(int), y[ok].astype(int)
                    flat = buf.reshape(-1, 3)
                    c = self.debris_col[ok] * v
                    for ddx, ddy, wgt in ((0, 0, 1.0), (1, 0, 0.5), (0, 1, 0.5), (-1, 0, 0.5), (0, -1, 0.5)):
                        np.add.at(flat, (yi + ddy) * W + xi + ddx, c * wgt)
            # tug'ilayotgan va kengayayotgan galaktika
            if t > tb:
                dt = t - tb
                g = ramp(t, tb + 0.2, 2.5) * (1 - ramp(t, 94.0, 1.2))
                width = 60 + 1100 * ease_out(dt / 9) + 9 * dt
                self.draw_galaxy(buf, 960, cy, width, -11 * (t - 55), g * 1.05, tilt=0.6, pa=-18)
                layers.append((self.L["title3"], 960, 95, ramp(t, tb + 1.8, 1.2) * win, 1.0))
            for key, lay, x in (("birinchi", "ayah1", 385), ("ikkinchi", "ayah2", 1535)):
                ta = T[key] - 0.2
                a = ramp(t, ta, 0.9) * win
                sl = 1 - ease_out((t - ta) / 1.1)
                layers.append((self.L[lay], x + (-60 if x < 960 else 60) * sl, 545, a, 0.96 + 0.04 * (1 - sl)))

        # ================= 4-SAHNA
        if t > 94.8:
            win = ramp(t, 95.0, 1.2)
            tx = T["xosh"]
            dim = 1 - 0.72 * ramp(t, tx - 0.3, 1.2)
            if win > 0:
                # sekin zoom-in (Ken Burns)
                z = 1 + 0.16 * smooth((t - 95) / 24)
                S = self.info.width
                cw = S / z
                fx, fy = S / 2, S / 2 - 0.05 * S * smooth((t - 95) / 24)
                fy = min(max(fy, cw / 2), S - cw / 2)
                crop = self.info.crop((int(fx - cw / 2), int(fy - cw / 2), int(fx + cw / 2), int(fy + cw / 2)))
                crop = crop.resize((self.info_size, self.info_size), Image.BICUBIC)
                if dim < 0.999:
                    crop = Image.eval(crop, lambda v: int(v * dim))
                crop = crop.convert("RGBA")
                sc_ = 0.94 + 0.06 * ease_out((t - 95) / 1.6)
                layers.append((self.L["frame"], 960, 495, win * (0.4 + 0.6 * dim), sc_))
                layers.append((crop, 960, 495, win, sc_))
            a = ramp(t, tx, 1.2)
            layers.append((self.L["q_final"], 960, 495, a, 0.92 + 0.08 * ease_out((t - tx) / 1.5)))

        # ---- PIL qatlamlari
        np.clip(buf, 0, 255, out=buf)
        img = Image.fromarray(buf.astype(np.uint8), "RGB").convert("RGBA")
        for lay, cx, cy, a, sc in layers:
            put(img, lay, cx, cy, a, sc)
        if self._ornament_t:
            x, y, half, a = self._ornament_t
            if a > 0.01:
                d = ImageDraw.Draw(img, "RGBA")
                col = (226, 184, 96, int(255 * a))
                d.line((x - half, y, x - 22, y), fill=col, width=3)
                d.line((x + 22, y, x + half, y), fill=col, width=3)
                d.regular_polygon((x, y, 11), 4, rotation=45, fill=(255, 224, 150, int(255 * a)))
        self.draw_subtitle(img, t)

        out = np.asarray(img.convert("RGB"))
        gfade = ramp(t, 0.0, 1.0) * (1 - ramp(t, DURATION - 1.4, 1.4))
        if gfade < 0.999:
            out = (out.astype(np.float32) * gfade).astype(np.uint8)
        return out

    def sub_layer(self, tokens, hi):
        key = (tuple(tokens), hi)
        if key in self.sub_cache:
            return self.sub_cache[key]
        f = font(F_SANS_B, 54)
        disp = [uz(x) for x in tokens]
        space = f.getlength(" ")
        lines, cur, cw = [], [], 0
        for i, d in enumerate(disp):
            wl = f.getlength(d)
            if cur and cw + space + wl > 1560:
                lines.append(cur)
                cur, cw = [], 0
            cw = cw + (space if cur else 0) + wl
            cur.append(i)
        lines.append(cur)
        asc, desc = f.getmetrics()
        lh = asc + desc + 6
        widths = [sum(f.getlength(disp[i]) for i in ln) + space * (len(ln) - 1) for ln in lines]
        bw, bh = int(max(widths)) + 64, lh * len(lines) + 26
        box = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
        ImageDraw.Draw(box).rounded_rectangle((0, 0, bw - 1, bh - 1), 18, fill=(0, 0, 0, 155),
                                              outline=(214, 172, 88, 110), width=2)
        txt = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
        shadow = Image.new("L", (bw, bh), 0)
        dt, ds = ImageDraw.Draw(txt), ImageDraw.Draw(shadow)
        for li, ln in enumerate(lines):
            x = (bw - widths[li]) / 2
            y = 13 + li * lh
            for i in ln:
                col = (255, 206, 96, 255) if i == hi else (255, 255, 255, 255)
                ds.text((x + 2, y + 3), disp[i], font=f, fill=255)
                dt.text((x, y), disp[i], font=f, fill=col)
                x += f.getlength(disp[i]) + space
        sh = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
        sh.putalpha(shadow.filter(ImageFilter.GaussianBlur(3)).point(lambda v: int(v * 0.9)))
        box.alpha_composite(sh)
        box.alpha_composite(txt)
        self.sub_cache[key] = box
        return box

    def draw_subtitle(self, img, t):
        for t0, t1, text, tokens, tstarts in self.tl["subs"]:
            if t0 - 0.12 <= t <= t1 + 0.12:
                a = ramp(t, t0 - 0.12, 0.12) * (1 - ramp(t, t1, 0.12))
                hi = max([i for i, ts in enumerate(tstarts) if ts <= t] or [-1])
                box = self.sub_layer(tokens, hi)
                put(img, box, W / 2, 1040 - box.height / 2, a)
                break


# --------------------------------------------------------------------------- tayyorlash va parallel render
def prepare_textures():
    BUILD.mkdir(exist_ok=True)
    if not (BUILD / "galaxy.npy").exists():
        print("Galaktika teksturasi yaratilmoqda...")
        np.save(BUILD / "galaxy.npy", make_galaxy())
    if not (BUILD / "nebula.npy").exists():
        print("Tumanlik teksturasi yaratilmoqda...")
        np.save(BUILD / "nebula.npy", make_nebula())
    if not (BUILD / "sphere_blue.png").exists():
        make_sphere(200, "blue", 21).save(BUILD / "sphere_blue.png")
        make_sphere(200, "orange", 33).save(BUILD / "sphere_orange.png")


_R = None


def _init_worker():
    global _R
    _R = Renderer(load_timeline())


def _render_segment(args):
    k, f0, f1 = args
    path = BUILD / f"seg_{k:02d}.mp4"
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
           "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
           "-pix_fmt", "yuv420p", "-threads", "2", str(path)]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for fi in range(f0, f1):
        p.stdin.write(_R.frame(fi).tobytes())
        if (fi - f0) % 150 == 0:
            print(f"  segment {k}: {fi - f0}/{f1 - f0}", flush=True)
    p.stdin.close()
    if p.wait() != 0:
        raise RuntimeError(f"ffmpeg segment {k} xatosi")
    return str(path)


def render_all(workers=None):
    prepare_textures()
    total = DURATION * FPS
    workers = workers or max(1, os.cpu_count() or 1)
    nseg = workers * 2
    bounds = [round(total * i / nseg) for i in range(nseg + 1)]
    jobs = [(k, bounds[k], bounds[k + 1]) for k in range(nseg)]
    print(f"{total} kadr, {workers} jarayon, {nseg} segment")
    with Pool(workers, initializer=_init_worker) as pool:
        segs = pool.map(_render_segment, jobs, chunksize=1)
    lst = BUILD / "segments.txt"
    lst.write_text("".join(f"file '{os.path.abspath(s)}'\n" for s in segs))
    out = BUILD / "video_only.mp4"
    subprocess.check_call(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                           "-c", "copy", str(out)])
    for s in segs:
        os.remove(s)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", nargs="*", type=float, help="faqat shu soniyalardagi kadrlarni PNG qilib saqlash")
    ap.add_argument("--workers", type=int, default=None)
    a = ap.parse_args()
    if a.preview is not None:
        prepare_textures()
        r = Renderer(load_timeline())
        (BUILD / "preview").mkdir(exist_ok=True)
        for s in a.preview:
            Image.fromarray(r.frame(int(s * FPS))).save(BUILD / "preview" / f"frame_{s:06.2f}.png")
            print("saqlandi:", s)
        return
    print("Tayyor:", render_all(a.workers))


if __name__ == "__main__":
    sys.exit(main())
