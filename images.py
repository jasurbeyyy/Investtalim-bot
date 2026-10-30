"""
Rasm dizayn generatori — Foreign Investta'lim boti uchun.

Har bir post uchun yangi rasm chiziladi: 10+ xil shablon, 20+ rang palitrasi,
tasodifiy bezaklar. Xayrli tong / Xayrli tun uchun alohida manzara sahnalari.
Ixtiyoriy ravishda bepul AI fon rasmi (Pollinations) ham qo'shiladi.
Hammasi bepul, internet bo'lmasa ham ishlaydi (AI fondan tashqari).
"""
from __future__ import annotations

import io
import math
import os
import random
import re
import urllib.parse
from dataclasses import dataclass, field

from PIL import Image, ImageDraw, ImageFilter, ImageFont, features

BASE = os.path.dirname(os.path.abspath(__file__))
FONTS = os.path.join(BASE, "fonts")
ASSETS = os.path.join(BASE, "assets")
W, H = 1080, 1350

HAS_RAQM = features.check("raqm")
ARABIC_RE = re.compile(r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]")

try:  # zaxira: raqm bo'lmagan qurilmalar (Windows, Termux) uchun
    import arabic_reshaper
    from bidi.algorithm import get_display
except Exception:  # pragma: no cover
    arabic_reshaper = None
    get_display = None


# ───────────────────────── Shriftlar ─────────────────────────
# Lotin (o'zbek, ingliz): Caladea — Cambria bilan bir xil o'lchamli bepul shrift.
# Kirill (rus): PT Serif — Caladea'da kirill harflari yo'q.
# Arab: Noto Naskh Arabic — Times New Roman kabi klassik naskh yozuvi.
SERIF = {"Regular": "Caladea-Regular.ttf", "Bold": "Caladea-Bold.ttf"}
CYR = {"Regular": "PTSerif-Regular.ttf", "Bold": "PTSerif-Bold.ttf"}
ARABIC_FONT = "NotoNaskhArabic.ttf"
CYR_RE = re.compile(r"[\u0400-\u04FF]")
LATIN_CYR_RE = re.compile(r"[A-Za-z\u0400-\u04FF]")
AR_RUN_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]"
                       r"(?:[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF\s،؛؟]*"
                       r"[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF؟!])?")
_font_cache: dict = {}


def _bold(weight: str) -> str:
    return "Bold" if weight in ("Bold", "SemiBold", "ExtraBold", "Black") else "Regular"


def _load(kind: str, size: int, weight: str) -> ImageFont.FreeTypeFont:
    key = (kind, size, _bold(weight))
    if key in _font_cache:
        return _font_cache[key]
    kw = {"layout_engine": ImageFont.Layout.RAQM} if HAS_RAQM else {}
    if kind == "ar":
        f = ImageFont.truetype(os.path.join(FONTS, ARABIC_FONT), size, **kw)
        try:
            f.set_variation_by_name(_bold(weight))
        except Exception:
            pass
    else:
        files = CYR if kind == "cyr" else SERIF
        f = ImageFont.truetype(os.path.join(FONTS, files[_bold(weight)]), size, **kw)
    f.iv_size, f.iv_weight, f.iv_kind = size, weight, kind
    _font_cache[key] = f
    return f


def font(name: str, size: int, weight: str = "Bold") -> ImageFont.FreeTypeFont:
    """Barcha yozuvlar uchun yagona serif shrift (eski shrift nomlari ham shunga yo'naltiriladi)."""
    return _load("latin", size, weight)


def is_arabic(s: str) -> bool:
    return bool(ARABIC_RE.search(s or ""))


def pure_arabic(s: str) -> bool:
    return is_arabic(s) and not LATIN_CYR_RE.search(s)


def font_for(text: str, name: str, size: int, weight: str = "Bold"):
    """Matn yozuviga qarab shrift tanlaydi: arab / kirill / lotin."""
    if pure_arabic(text):
        return _load("ar", size, weight)
    if CYR_RE.search(text or ""):
        return _load("cyr", size, weight)
    return _load("latin", size, weight)


def _dir(text: str):
    if not is_arabic(text):
        return None
    return "rtl" if pure_arabic(text) else "ltr"


def shape(text: str) -> str:
    """raqm bo'lmasa, arab harflarini qo'lda bog'lab, to'g'ri tartibda chiqaradi."""
    if HAS_RAQM or not is_arabic(text) or arabic_reshaper is None:
        return text
    base = "R" if pure_arabic(text) else "L"
    return get_display(arabic_reshaper.reshape(text), base_dir=base)


def _kw(text):
    d = _dir(text)
    return {"direction": d} if (d and HAS_RAQM) else {}


def _runs(text: str, f):
    """Aralash qatorni (arabcha + lotin/kirill) bo'laklarga ajratadi, har biriga o'z shrifti."""
    out, pos = [], 0
    size, weight = getattr(f, "iv_size", 40), getattr(f, "iv_weight", "Bold")
    for m in AR_RUN_RE.finditer(text):
        if m.start() > pos:
            seg = text[pos:m.start()]
            out.append((seg, font_for(seg, "", size, weight) if seg.strip() else f))
        out.append((m.group(0), _load("ar", size, weight)))
        pos = m.end()
    if pos < len(text):
        seg = text[pos:]
        out.append((seg, font_for(seg, "", size, weight) if seg.strip() else f))
    return out


def _is_mixed(text: str) -> bool:
    return is_arabic(text) and not pure_arabic(text)


def text_w(draw, text, f) -> float:
    if _is_mixed(text):
        return sum(draw.textlength(shape(r), font=rf, **_kw(r)) for r, rf in _runs(text, f))
    return draw.textlength(shape(text), font=f, **_kw(text))


def draw_text(draw, xy, text, f, fill, anchor="la", **kw):
    if not _is_mixed(text):
        kw.update(_kw(text))
        draw.text(xy, shape(text), font=f, fill=fill, anchor=anchor, **kw)
        return
    x, y = xy
    total = text_w(draw, text, f)
    x -= total * {"l": 0, "m": 0.5, "r": 1}.get(anchor[0], 0)
    asc, desc = f.getmetrics()
    v = anchor[1] if len(anchor) > 1 else "a"
    base = {"a": y + asc, "t": y + asc, "m": y + (asc - desc) / 2, "s": y, "d": y - desc, "b": y - desc}.get(v, y + asc)
    for r, rf in _runs(text, f):
        k = dict(kw)
        k.update(_kw(r))
        draw.text((x, base), shape(r), font=rf, fill=fill, anchor="ls", **k)
        x += draw.textlength(shape(r), font=rf, **_kw(r))


def wrap(draw, text: str, f, max_w: int) -> list[str]:
    lines: list[str] = []
    for para in str(text).split("\n"):
        words = para.split()
        if not words:
            continue
        cur = words[0]
        for w_ in words[1:]:
            test = cur + " " + w_
            if text_w(draw, test, f) <= max_w:
                cur = test
            else:
                lines.append(cur)
                cur = w_
        lines.append(cur)
    return lines


def fit_text(draw, text, name, max_w, max_h, start, minimum=34, weight="Bold", spacing=1.12):
    """Matnni berilgan qutiga sig'adigan eng katta o'lchamda joylaydi."""
    if is_arabic(text):  # arab shriftlarining balandligi katta
        spacing *= 1.42
    size = start
    while size >= minimum:
        f = font_for(text, name, size, weight)
        lines = wrap(draw, text, f, max_w)
        lh = int(size * spacing)
        if lh * len(lines) <= max_h and all(text_w(draw, l, f) <= max_w for l in lines):
            return f, lines, lh
        size -= 4
    f = font_for(text, name, minimum, weight)
    lines = wrap(draw, text, f, max_w)
    max_lines = max(1, max_h // int(minimum * spacing))
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(".,;: ") + "…"
    return f, lines, int(minimum * spacing)


def draw_block(draw, lines, f, lh, x, y, fill, align="left", box_w=None, shadow=None):
    for i, line in enumerate(lines):
        yy = y + i * lh
        lw = text_w(draw, line, f)
        rtl = pure_arabic(line)
        if align == "center" and box_w:
            xx = x + (box_w - lw) / 2
        elif (align == "right" or rtl) and box_w:
            xx = x + box_w - lw
        else:
            xx = x
        if shadow:
            draw_text(draw, (xx + 3, yy + 4), line, f, shadow)
        draw_text(draw, (xx, yy), line, f, fill)
    return y + len(lines) * lh


# ───────────────────────── Ranglar ─────────────────────────
def hx(c: str):
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


PALETTES = [  # (fon1, fon2, aksent, qo'shimcha)
    ("#0F2027", "#2C5364", "#FFB703", "#8ECAE6"),
    ("#1A1A2E", "#16213E", "#E94560", "#0F3460"),
    ("#2B2D42", "#8D99AE", "#EF233C", "#EDF2F4"),
    ("#003049", "#005F73", "#F77F00", "#FCBF49"),
    ("#264653", "#2A9D8F", "#E9C46A", "#F4A261"),
    ("#3A0CA3", "#7209B7", "#F72585", "#4CC9F0"),
    ("#10002B", "#3C096C", "#FF9E00", "#C77DFF"),
    ("#0B3D2E", "#1B5E20", "#FFD166", "#A7C957"),
    ("#5F0F40", "#9A031E", "#FB8B24", "#E36414"),
    ("#073B4C", "#118AB2", "#06D6A0", "#FFD166"),
    ("#14213D", "#1F3A68", "#FCA311", "#E5E5E5"),
    ("#22223B", "#4A4E69", "#F2E9E4", "#C9ADA7"),
    ("#0D1B2A", "#1B263B", "#E0E1DD", "#778DA9"),
    ("#6A040F", "#9D0208", "#FFBA08", "#F48C06"),
    ("#023E8A", "#0077B6", "#90E0EF", "#CAF0F8"),
    ("#212529", "#495057", "#FFD60A", "#F8F9FA"),
    ("#386641", "#6A994E", "#F2E8CF", "#BC4749"),
    ("#3D348B", "#7678ED", "#F7B801", "#F35B04"),
    ("#2D3142", "#4F5D75", "#EF8354", "#BFC0C0"),
    ("#1B4332", "#2D6A4F", "#95D5B2", "#D8F3DC"),
    ("#240046", "#5A189A", "#FF6D00", "#E0AAFF"),
    ("#283618", "#606C38", "#DDA15E", "#FEFAE0"),
    ("#03045E", "#023E8A", "#FFB4A2", "#E5989B"),
    ("#4A1942", "#893168", "#F7EDE2", "#F5CAC3"),
]
LIGHT_PALETTES = [  # (fon, matn, aksent, qo'shimcha)
    ("#FFF8E7", "#1D3557", "#E63946", "#457B9D"),
    ("#F1FAEE", "#1D3557", "#E76F51", "#2A9D8F"),
    ("#FEFAE0", "#283618", "#BC6C25", "#606C38"),
    ("#F8F4FF", "#2E1760", "#FF5D8F", "#7B5CFA"),
    ("#EDF6F9", "#006D77", "#E29578", "#83C5BE"),
    ("#FFF1E6", "#3D2C2E", "#F4845F", "#7D8CC4"),
    ("#F0F4F8", "#102A43", "#F0B429", "#334E68"),
    ("#FDF0D5", "#003049", "#C1121F", "#669BBC"),
]

LANG = {
    "en": {"badge": "INGLIZ TILI", "native": "ENGLISH", "glyph": "Aa", "accent": "#E63946"},
    "ar": {"badge": "ARAB TILI", "native": "العربية", "glyph": "ض", "accent": "#2A9D8F"},
    "ru": {"badge": "RUS TILI", "native": "РУССКИЙ", "glyph": "Яя", "accent": "#1D4ED8"},
}


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(len(a)))


def lum(c):
    r, g, b = c[:3]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def gradient(size, c1, c2, angle=90):
    """Chiziqli gradient (angle: 0 = chapdan o'ngga, 90 = yuqoridan pastga)."""
    w, h = size
    small = Image.new("RGB", (256, 256))
    px = small.load()
    a = math.radians(angle)
    dx, dy = math.cos(a), math.sin(a)
    for y in range(256):
        for x in range(256):
            t = ((x - 128) * dx + (y - 128) * dy) / 181 * 0.5 + 0.5
            t = max(0.0, min(1.0, t))
            px[x, y] = lerp(c1, c2, t)
    return small.resize((w, h), Image.BICUBIC)


def radial_glow(size, center, radius, color, strength=200):
    layer = Image.new("RGBA", size, color + (0,))
    m = Image.new("L", size, 0)
    d = ImageDraw.Draw(m)
    cx, cy = center
    d.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=strength)
    m = m.filter(ImageFilter.GaussianBlur(radius * 0.45))
    layer.putalpha(m)
    return layer


# ───────────────────────── Logo ─────────────────────────
_logo_cache: dict = {}


def logo(color: str = "white", width: int = 220) -> Image.Image:
    key = (color, width)
    if key not in _logo_cache:
        im = Image.open(os.path.join(ASSETS, f"logo_{'white' if color == 'white' else 'black'}.png")).convert("RGBA")
        h = int(im.height * width / im.width)
        _logo_cache[key] = im.resize((width, h), Image.LANCZOS)
    return _logo_cache[key]


def paste_logo(img, xy, bg_rgb, width=220):
    col = "black" if lum(bg_rgb) > 150 else "white"
    lg = logo(col, width)
    img.alpha_composite(lg, (int(xy[0]), int(xy[1])))
    return lg.size


def sample_bg(img, box):
    region = img.crop(box).convert("RGB").resize((1, 1), Image.BILINEAR)
    return region.getpixel((0, 0))


# ───────────────────────── Ma'lumot ─────────────────────────
@dataclass
class Card:
    lang: str = "en"               # en / ar / ru
    category: str = "GRAMMATIKA"   # post turi
    title: str = ""                # asosiy sarlavha (o'rganilayotgan tilda)
    subtitle: str = ""             # o'zbekcha izoh
    lines: list = field(default_factory=list)  # 0-4 ta qisqa satr: "apple — olma"
    footer: str = "t.me/investtalim  •  +998 90 642 18 08"
    bg_photo: Image.Image | None = None        # ixtiyoriy AI fon


def pill(draw, xy, text, f, fg, bg, pad=(26, 12), radius=None):
    x, y = xy
    tw = text_w(draw, text, f)
    asc, desc = f.getmetrics()
    h = asc + desc + pad[1] * 2
    w = tw + pad[0] * 2
    draw.rounded_rectangle([x, y, x + w, y + h], radius=radius or h // 2, fill=bg)
    draw_text(draw, (x + pad[0], y + h / 2), text, f, fg, anchor="lm")
    return w, h


def draw_footer(img, card, ink, bar=None, y=None, center=True):
    d = ImageDraw.Draw(img)
    f = font("montserrat", 30, "SemiBold")
    y = y or H - 70
    if bar:
        d.rectangle([0, y - 34, W, H], fill=bar)
    tw = text_w(d, card.footer, f)
    x = (W - tw) / 2 if center else 70
    draw_text(d, (x, y), card.footer, f, ink, anchor="lm")


def draw_lines_list(d, card, x, y, max_w, ink, accent, fname="montserrat", size=44):
    if not card.lines:
        return y
    for item in card.lines[:4]:
        f, lines, lh = fit_text(d, item, fname, max_w - 50, 2 * int(size * 1.22), size, 28, "Medium", 1.22)
        r = max(6, size // 6)
        asc, _ = f.getmetrics()
        cy = y + asc * (0.66 if is_arabic(lines[0]) else 0.6)
        d.ellipse([x + 4, cy - r, x + 4 + 2 * r, cy + r], fill=accent)
        draw_block(d, lines, f, lh, x + 46, y, ink, box_w=max_w - 46)
        y += lh * len(lines) + 18
    return y


def _content(d, card, x, y, box_w, box_h, ink, accent, title_font, align, sub_ink, title_start):
    n = len(card.lines[:4])
    lines_h = n * 74 + (20 if n else 0)
    sub_h = 170 if card.subtitle else 0
    title_h = max(170, box_h - lines_h - sub_h - 40)
    tf, tl, tlh = fit_text(d, card.title, title_font, box_w, min(title_h, 520), title_start, 46, "Bold", 1.1)
    y = draw_block(d, tl, tf, tlh, x, y, ink, align=align, box_w=box_w)
    y += 26
    if card.subtitle:
        if align == "left":
            d.rounded_rectangle([x, y, x + 110, y + 8], 4, fill=accent)
        else:
            d.rounded_rectangle([x + box_w / 2 - 60, y, x + box_w / 2 + 60, y + 8], 4, fill=accent)
        y += 34
        sf, sl, slh = fit_text(d, card.subtitle, "montserrat", box_w, 160, 48, 28, "Medium", 1.22)
        y = draw_block(d, sl, sf, slh, x, y, sub_ink, align=align, box_w=box_w)
        y += 30
    if n and align == "left":
        y = draw_lines_list(d, card, x, y, box_w, sub_ink, accent)
    elif n:
        for item in card.lines[:4]:
            ff, ll, lh = fit_text(d, item, "montserrat", box_w, 110, 42, 26, "Medium", 1.2)
            y = draw_block(d, ll, ff, lh, x, y, sub_ink, align="center", box_w=box_w) + 14
    return y


def content_block(d, card, x, y, box_w, box_h, ink, accent, title_font="montserrat", align="left",
                  sub_ink=None, title_start=124, valign="center"):
    """Sarlavha + izoh + satrlar. Qutiga sig'adigan o'lchamni tanlab, vertikal markazlaydi."""
    sub_ink = sub_ink or ink
    base = d._image
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    end = _content(ld, card, x, y, box_w, box_h, ink, accent, title_font, align, sub_ink, title_start)
    used = end - y
    off = int(max(0, (box_h - used) / 2)) if valign == "center" else 0
    if off:
        layer = layer.transform(layer.size, Image.AFFINE, (1, 0, 0, 0, 1, -off))
    base.alpha_composite(layer)
    return end + off


# ───────────────────────── Shablonlar ─────────────────────────
def t_gradient_blobs(card, rng):
    p = [hx(c) for c in rng.choice(PALETTES)]
    img = gradient((W, H), p[0], p[1], rng.choice([45, 90, 135, 60])).convert("RGBA")
    for _ in range(rng.randint(3, 5)):
        r = rng.randint(180, 420)
        img.alpha_composite(radial_glow((W, H), (rng.randint(0, W), rng.randint(0, H)), r, rng.choice([p[2], p[3]]), rng.randint(90, 170)))
    d = ImageDraw.Draw(img)
    paste_logo(img, (60, 55), (0, 0, 0), 210)
    f = font("montserrat", 30, "Bold")
    bw = text_w(d, LANG[card.lang]["badge"], f) + 52
    pill(d, (W - 60 - bw, 80), LANG[card.lang]["badge"], f, p[0], p[2])
    pill(d, (70, 330), card.category, font("montserrat", 28, "Bold"), (255, 255, 255), lerp(p[0], (0, 0, 0), 0.3))
    content_block(d, card, 70, 420, W - 140, 760, (255, 255, 255), p[2], rng.choice(["montserrat", "oswald", "playfair", "rubik"]), sub_ink=(235, 235, 245))
    draw_footer(img, card, (255, 255, 255), bar=lerp(p[0], (0, 0, 0), 0.35))
    return img


def t_split_panel(card, rng):
    bg, ink, acc, acc2 = [hx(c) for c in rng.choice(LIGHT_PALETTES)]
    img = Image.new("RGBA", (W, H), bg + (255,))
    d = ImageDraw.Draw(img)
    top = 470
    panel = gradient((W, top), acc2, ink, rng.choice([0, 30, 150]))
    img.paste(panel, (0, 0))
    g = LANG[card.lang]["glyph"]
    gf = font_for(g, "playfair", 420, "Black")
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)
    draw_text(od, (W - 60, top - 10), g, gf, (255, 255, 255, 60), anchor="rd")
    img.alpha_composite(ov)
    d = ImageDraw.Draw(img)
    paste_logo(img, (60, 50), (0, 0, 0), 200)
    f = font("montserrat", 30, "Bold")
    pill(d, (60, top - 110), LANG[card.lang]["badge"] + "  •  " + card.category, f, ink, bg)
    d.polygon([(0, top), (W, top - 50), (W, top + 2), (0, top + 2)], fill=bg)
    content_block(d, card, 70, top + 40, W - 140, H - top - 190, ink, acc, rng.choice(["playfair", "montserrat", "rubik"]), sub_ink=lerp(ink, bg, 0.2))
    d.rectangle([0, H - 110, W, H], fill=ink)
    draw_footer(img, card, bg, y=H - 55)
    return img


def t_notebook(card, rng):
    paper = rng.choice([(255, 251, 235), (250, 248, 240), (245, 250, 255), (255, 246, 240)])
    img = Image.new("RGBA", (W, H), paper + (255,))
    d = ImageDraw.Draw(img)
    line_c = rng.choice([(173, 200, 230), (190, 215, 235), (200, 210, 230)])
    for y in range(240, H - 120, 62):
        d.line([(0, y), (W, y)], fill=line_c, width=2)
    d.line([(150, 0), (150, H)], fill=(235, 120, 120), width=4)
    for y in range(120, H, 160):
        d.ellipse([40, y, 80, y + 40], fill=lerp(paper, (0, 0, 0), 0.12))
    ink = rng.choice([(29, 53, 87), (40, 40, 60), (20, 60, 110)])
    acc = rng.choice([(230, 57, 70), (231, 111, 81), (42, 157, 143)])
    paste_logo(img, (W - 250, 40), paper, 190)
    f = font("caveat", 56, "Bold")
    draw_text(d, (190, 120), LANG[card.lang]["badge"].title() + " — " + card.category.lower(), f, acc, anchor="lm")
    d = ImageDraw.Draw(img)
    content_block(d, card, 190, 230, W - 260, 820, ink, acc, "caveat", sub_ink=(60, 60, 80), title_start=124)
    note_c = rng.choice([(255, 236, 153), (255, 205, 210), (200, 230, 201), (187, 222, 251)])
    note = Image.new("RGBA", (300, 150), note_c + (255,))
    nd = ImageDraw.Draw(note)
    nd.text((150, 75), "Yodda tuting!", font=font("caveat", 40, "Bold"), fill=ink, anchor="mm")
    note = note.rotate(rng.uniform(-8, 8), expand=True, resample=Image.BICUBIC)
    sh = Image.new("RGBA", note.size, (0, 0, 0, 0))
    sh.putalpha(note.split()[3].point(lambda a: int(a * 0.25)))
    sh = sh.filter(ImageFilter.GaussianBlur(8))
    img.alpha_composite(sh, (W - 380 + 8, H - 330 + 10))
    img.alpha_composite(note, (W - 380, H - 330))
    draw_footer(img, card, ink, y=H - 60)
    return img


def _shape_layer(rng, colors, n=14):
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for _ in range(n):
        c = rng.choice(colors) + (rng.randint(60, 150),)
        kind = rng.choice(["circle", "ring", "tri", "rect", "plus"])
        x, y, s = rng.randint(-100, W), rng.randint(-100, H), rng.randint(60, 300)
        if kind == "circle":
            d.ellipse([x, y, x + s, y + s], fill=c)
        elif kind == "ring":
            d.ellipse([x, y, x + s, y + s], outline=c, width=rng.randint(8, 22))
        elif kind == "tri":
            d.polygon([(x, y + s), (x + s / 2, y), (x + s, y + s)], fill=c)
        elif kind == "rect":
            d.rounded_rectangle([x, y, x + s, y + s * 0.6], 20, fill=c)
        else:
            t = s // 5
            d.rectangle([x + s / 2 - t / 2, y, x + s / 2 + t / 2, y + s], fill=c)
            d.rectangle([x, y + s / 2 - t / 2, x + s, y + s / 2 + t / 2], fill=c)
    return layer


def t_geometric_glass(card, rng):
    p = [hx(c) for c in rng.choice(PALETTES)]
    img = gradient((W, H), p[0], p[1], rng.choice([90, 120, 60])).convert("RGBA")
    img.alpha_composite(_shape_layer(rng, [p[2], p[3]], rng.randint(10, 18)))
    blurred = img.filter(ImageFilter.GaussianBlur(26))
    box = (60, 300, W - 60, H - 150)
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).rounded_rectangle(box, 46, fill=255)
    img.paste(blurred, (0, 0), mask)
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)
    od.rounded_rectangle(box, 46, fill=(255, 255, 255, 40), outline=(255, 255, 255, 110), width=3)
    img.alpha_composite(ov)
    d = ImageDraw.Draw(img)
    paste_logo(img, ((W - 230) / 2, 40), (0, 0, 0), 230)
    f = font("montserrat", 28, "Bold")
    pill(d, (110, 350), LANG[card.lang]["badge"], f, p[0], p[2])
    bw = text_w(d, card.category, f) + 52
    pill(d, (W - 110 - bw, 350), card.category, f, (255, 255, 255), lerp(p[0], (0, 0, 0), 0.2))
    content_block(d, card, 110, 460, W - 220, H - 460 - 200, (255, 255, 255), p[2], rng.choice(["montserrat", "rubik", "oswald"]), sub_ink=(240, 240, 250))
    draw_footer(img, card, (255, 255, 255), y=H - 75)
    return img


def t_dotgrid_neon(card, rng):
    base = rng.choice([(12, 12, 20), (10, 18, 30), (18, 10, 28), (8, 20, 18)])
    neon = rng.choice([(0, 245, 212), (255, 0, 110), (251, 255, 18), (58, 134, 255), (255, 159, 28), (144, 255, 120)])
    img = Image.new("RGBA", (W, H), base + (255,))
    d = ImageDraw.Draw(img)
    for y in range(30, H, 44):
        for x in range(30, W, 44):
            d.ellipse([x - 2, y - 2, x + 2, y + 2], fill=lerp(base, (255, 255, 255), 0.14))
    img.alpha_composite(radial_glow((W, H), (rng.choice([0, W]), rng.randint(200, 600)), 520, neon, 90))
    d = ImageDraw.Draw(img)
    paste_logo(img, (60, 55), base, 200)
    f = font("oswald", 40, "Bold")
    draw_text(d, (W - 60, 110), LANG[card.lang]["native"], font_for(LANG[card.lang]["native"], "oswald", 44, "Bold"), neon, anchor="rm")
    draw_text(d, (70, 360), "// " + card.category, font("montserrat", 34, "Bold"), neon, anchor="lm")
    d.line([(70, 405), (370, 405)], fill=neon, width=6)
    content_block(d, card, 70, 450, W - 140, H - 450 - 190, (255, 255, 255), neon, rng.choice(["oswald", "montserrat", "rubik"]), sub_ink=(200, 205, 220), title_start=112)
    d.rectangle([0, H - 110, W, H - 104], fill=neon)
    draw_footer(img, card, (230, 230, 240), y=H - 55)
    return img


def t_big_letter(card, rng):
    p = [hx(c) for c in rng.choice(PALETTES)]
    img = Image.new("RGBA", (W, H), p[0] + (255,))
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)
    g = LANG[card.lang]["glyph"]
    draw_text(od, (W / 2, H / 2 + 40), g, font_for(g, "playfair", 900, "Black"), p[1] + (255,), anchor="mm")
    ov = ov.filter(ImageFilter.GaussianBlur(2))
    img.alpha_composite(ov)
    d = ImageDraw.Draw(img)
    for i in range(6):
        d.rectangle([0, 250 + i * 14, 40 + i * 40, 256 + i * 14], fill=p[2])
    paste_logo(img, (W - 260, 50), p[0], 200)
    f = font("montserrat", 32, "Bold")
    draw_text(d, (70, 110), LANG[card.lang]["badge"], f, p[2], anchor="lm")
    draw_text(d, (70, 160), card.category, font("montserrat", 30, "Medium"), (230, 230, 230), anchor="lm")
    content_block(d, card, 70, 420, W - 140, 760, (255, 255, 255), p[2], rng.choice(["playfair", "montserrat"]), sub_ink=(235, 235, 240))
    draw_footer(img, card, p[0], bar=p[2], y=H - 50)
    return img


def t_diagonal_stripes(card, rng):
    bg, ink, acc, acc2 = [hx(c) for c in rng.choice(LIGHT_PALETTES)]
    img = Image.new("RGBA", (W, H), acc2 + (255,))
    d = ImageDraw.Draw(img)
    sw = rng.choice([40, 60, 80])
    shade = lerp(acc2, (0, 0, 0), 0.12)
    for i in range(-H, W + H, sw * 2):
        d.polygon([(i, 0), (i + sw, 0), (i + sw - H, H), (i - H, H)], fill=shade)
    card_box = (60, 210, W - 60, H - 130)
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle((card_box[0] + 14, card_box[1] + 18, card_box[2] + 14, card_box[3] + 18), 40, fill=(0, 0, 0, 90))
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(14)))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(card_box, 40, fill=bg)
    d.rounded_rectangle((card_box[0], card_box[1], card_box[2], card_box[1] + 26), 12, fill=acc)
    paste_logo(img, (W - 270, 290), bg, 170)
    f = font("montserrat", 28, "Bold")
    pill(d, (110, 290), LANG[card.lang]["badge"], f, bg, ink)
    pill(d, (110, 360), card.category, f, ink, lerp(bg, acc, 0.25))
    content_block(d, card, 110, 470, W - 220, H - 470 - 230, ink, acc, rng.choice(["montserrat", "rubik", "comfortaa", "playfair"]), sub_ink=lerp(ink, bg, 0.15))
    draw_footer(img, card, ink, y=H - 62)
    return img


def t_waves(card, rng):
    p = [hx(c) for c in rng.choice(PALETTES)]
    img = gradient((W, H), p[0], p[1], 90).convert("RGBA")
    d = ImageDraw.Draw(img)
    base_y = H - 330
    cols = [lerp(p[2], p[0], 0.55), lerp(p[2], p[0], 0.3), p[2]]
    for k, c in enumerate(cols):
        amp, freq, ph = rng.randint(20, 55), rng.uniform(1.0, 2.4), rng.uniform(0, 6.28)
        pts = [(x, base_y + k * 55 + amp * math.sin(freq * x / W * 6.28 + ph)) for x in range(0, W + 20, 20)]
        d.polygon(pts + [(W, H), (0, H)], fill=c)
    paste_logo(img, (60, 55), (0, 0, 0), 200)
    f = font("montserrat", 30, "Bold")
    bw = text_w(d, LANG[card.lang]["badge"], f) + 52
    pill(d, (W - 60 - bw, 80), LANG[card.lang]["badge"], f, p[0], (255, 255, 255))
    draw_text(d, (70, 330), card.category, font("montserrat", 34, "Bold"), p[2], anchor="lm")
    content_block(d, card, 70, 390, W - 140, base_y - 420, (255, 255, 255), p[2], rng.choice(["montserrat", "playfair", "oswald"]), sub_ink=(230, 235, 245))
    draw_footer(img, card, p[0], y=H - 60)
    return img


def t_frame_classic(card, rng):
    bg, ink, acc, acc2 = [hx(c) for c in rng.choice(LIGHT_PALETTES)]
    img = Image.new("RGBA", (W, H), bg + (255,))
    d = ImageDraw.Draw(img)
    d.rectangle([40, 40, W - 40, H - 40], outline=ink, width=4)
    d.rectangle([58, 58, W - 58, H - 58], outline=acc, width=2)
    for cx, cy in [(40, 40), (W - 40, 40), (40, H - 40), (W - 40, H - 40)]:
        d.rectangle([cx - 14, cy - 14, cx + 14, cy + 14], fill=acc)
    paste_logo(img, ((W - 240) / 2, 90), bg, 240)
    f = font("montserrat", 28, "Bold")
    t = LANG[card.lang]["badge"] + "   •   " + card.category
    draw_text(d, (W / 2, 330), t, f, acc, anchor="mm")
    content_block(d, card, 110, 400, W - 220, H - 400 - 200, ink, acc, rng.choice(["playfair", "montserrat"]), align="center", sub_ink=lerp(ink, bg, 0.2))
    draw_footer(img, card, ink, y=H - 100)
    return img


def t_quiz(card, rng):
    p = [hx(c) for c in rng.choice(PALETTES)]
    img = gradient((W, H), p[0], p[1], rng.choice([45, 135])).convert("RGBA")
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)
    for _ in range(18):
        s = rng.randint(50, 160)
        draw_text(od, (rng.randint(0, W), rng.randint(0, H)), "?", font("montserrat", s, "Black"), (255, 255, 255, rng.randint(15, 45)), anchor="mm")
    img.alpha_composite(ov)
    d = ImageDraw.Draw(img)
    cx, cy, r = W / 2, 400, 150
    img.alpha_composite(radial_glow((W, H), (int(cx), cy), 260, p[2], 140))
    d = ImageDraw.Draw(img)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=p[2])
    draw_text(d, (cx, cy + 10), "?", font("montserrat", 220, "Black"), p[0], anchor="mm")
    paste_logo(img, (60, 50), (0, 0, 0), 170)
    f = font("montserrat", 28, "Bold")
    bw = text_w(d, LANG[card.lang]["badge"], f) + 52
    pill(d, (W - 60 - bw, 70), LANG[card.lang]["badge"], f, p[0], (255, 255, 255))
    draw_text(d, (W / 2, 610), "BILIMINGIZNI SINANG!", font("montserrat", 46, "ExtraBold"), (255, 255, 255), anchor="mm")
    content_block(d, card, 90, 680, W - 180, H - 680 - 170, (255, 255, 255), p[2], "montserrat", align="center", sub_ink=(235, 235, 245), title_start=80)
    draw_footer(img, card, (255, 255, 255), bar=lerp(p[0], (0, 0, 0), 0.4))
    return img


def t_photo(card, rng):
    photo = card.bg_photo.convert("RGB")
    s = max(W / photo.width, H / photo.height)
    photo = photo.resize((int(photo.width * s) + 1, int(photo.height * s) + 1), Image.LANCZOS)
    left, top = (photo.width - W) // 2, (photo.height - H) // 2
    img = photo.crop((left, top, left + W, top + H)).convert("RGBA")
    shade = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shade)
    for y in range(H):
        a = int(70 + 150 * (y / H) ** 1.3)
        sd.line([(0, y), (W, y)], fill=(5, 8, 20, min(a, 230)))
    img.alpha_composite(shade)
    d = ImageDraw.Draw(img)
    p = [hx(c) for c in rng.choice(PALETTES)]
    paste_logo(img, (60, 55), (0, 0, 0), 210)
    f = font("montserrat", 30, "Bold")
    bw = text_w(d, LANG[card.lang]["badge"], f) + 52
    pill(d, (W - 60 - bw, 80), LANG[card.lang]["badge"], f, (20, 20, 30), p[2])
    draw_text(d, (70, 560), card.category, font("montserrat", 34, "Bold"), p[2], anchor="lm")
    content_block(d, card, 70, 610, W - 140, H - 610 - 170, (255, 255, 255), p[2], rng.choice(["montserrat", "playfair"]), sub_ink=(235, 235, 240), title_start=96)
    draw_footer(img, card, (240, 240, 245), y=H - 60)
    return img


TEMPLATES = {
    "gradient": t_gradient_blobs,
    "split": t_split_panel,
    "notebook": t_notebook,
    "glass": t_geometric_glass,
    "neon": t_dotgrid_neon,
    "bigletter": t_big_letter,
    "stripes": t_diagonal_stripes,
    "waves": t_waves,
    "classic": t_frame_classic,
}


def render_card(card: Card, recent: list[str] | None = None, seed=None, is_quiz=False) -> tuple[Image.Image, str]:
    """Post rasmi. recent — oxirgi ishlatilgan shablonlar (takrorlanmasligi uchun)."""
    rng = random.Random(seed)
    recent = recent or []
    if card.bg_photo is not None:
        name = "photo"
        img = t_photo(card, rng)
    elif is_quiz and rng.random() < 0.6:
        name = "quiz"
        img = t_quiz(card, rng)
    else:
        options = [k for k in TEMPLATES if k not in recent[-4:]] or list(TEMPLATES)
        name = rng.choice(options)
        img = TEMPLATES[name](card, rng)
    return img.convert("RGB"), name


# ───────────────────────── Xayrli tong / tun ─────────────────────────
GREET = {
    "morning": [("uz", "Xayrli tong!"), ("en", "Good morning!"), ("ru", "Доброе утро!"), ("ar", "صباح الخير!")],
    "night": [("uz", "Xayrli tun!"), ("en", "Good night!"), ("ru", "Спокойной ночи!"), ("ar", "تصبح على خير!")],
}

DAWN_SKIES = [
    [(255, 183, 94), (255, 126, 103), (106, 76, 147)],
    [(253, 216, 145), (247, 151, 98), (64, 99, 158)],
    [(255, 236, 179), (255, 171, 145), (122, 162, 227)],
    [(255, 207, 112), (240, 128, 128), (93, 63, 211)],
    [(255, 240, 200), (166, 222, 255), (72, 149, 239)],
    [(250, 208, 196), (255, 154, 158), (161, 140, 209)],
]
NIGHT_SKIES = [
    [(9, 12, 38), (34, 30, 84), (85, 55, 120)],
    [(3, 7, 30), (20, 40, 80), (40, 70, 110)],
    [(15, 10, 30), (50, 20, 70), (120, 50, 90)],
    [(2, 12, 24), (8, 40, 60), (20, 80, 90)],
    [(10, 10, 25), (30, 35, 70), (70, 60, 110)],
]


def sky(colors):
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    c_top, c_mid, c_bot = colors[2], colors[1], colors[0]
    for y in range(H):
        t = y / H
        c = lerp(c_top, c_mid, t / 0.55) if t < 0.55 else lerp(c_mid, c_bot, (t - 0.55) / 0.45)
        d.line([(0, y), (W, y)], fill=c)
    return img.convert("RGBA")


def ridge(rng, base_y, rough, n=9):
    pts = [base_y + rng.uniform(-rough, rough), base_y + rng.uniform(-rough, rough)]
    r = rough
    for _ in range(n):
        new = []
        for a, b in zip(pts, pts[1:]):
            new += [a, (a + b) / 2 + rng.uniform(-r, r)]
        new.append(pts[-1])
        pts = new
        r *= 0.55
    step = W / (len(pts) - 1)
    return [(i * step, y) for i, y in enumerate(pts)]


def mountains(img, rng, colors, start_y, layers=3):
    d = ImageDraw.Draw(img)
    for k in range(layers):
        y0 = start_y + k * 90
        pts = ridge(rng, y0, 120 - k * 25)
        d.polygon(pts + [(W, H), (0, H)], fill=colors[k % len(colors)])


def hills(img, rng, colors, start_y, layers=3):
    d = ImageDraw.Draw(img)
    for k in range(layers):
        y0 = start_y + k * 80
        amp, fr, ph = rng.randint(30, 70), rng.uniform(0.7, 1.6), rng.uniform(0, 6.28)
        pts = [(x, y0 + amp * math.sin(fr * x / W * 6.28 + ph)) for x in range(0, W + 10, 10)]
        d.polygon(pts + [(W, H), (0, H)], fill=colors[k % len(colors)])


def city(img, rng, color, base_y, lights=False):
    d = ImageDraw.Draw(img)
    x = -20
    while x < W:
        bw, bh = rng.randint(50, 120), rng.randint(120, 420)
        d.rectangle([x, base_y - bh, x + bw, H], fill=color)
        if rng.random() < 0.25:  # gumbaz / minora
            d.ellipse([x + bw * 0.15, base_y - bh - bw * 0.35, x + bw * 0.85, base_y - bh + bw * 0.35], fill=color)
        if lights:
            for wy in range(base_y - bh + 20, H - 20, 28):
                for wx in range(x + 10, x + bw - 14, 22):
                    if rng.random() < 0.28:
                        d.rectangle([wx, wy, wx + 9, wy + 12], fill=rng.choice([(255, 214, 120), (255, 236, 170), (255, 190, 90)]))
        x += bw + rng.randint(0, 12)


def sea(img, rng, top_c, bot_c, y0, glow_x=None, glow_c=(255, 220, 150)):
    d = ImageDraw.Draw(img)
    for y in range(y0, H):
        d.line([(0, y), (W, y)], fill=lerp(top_c, bot_c, (y - y0) / (H - y0)))
    if glow_x:
        for i in range(40):
            yy = y0 + 8 + i * (H - y0) / 40
            w_ = 140 - i * 2.5 + rng.uniform(-20, 20)
            d.line([(glow_x - w_, yy), (glow_x + w_, yy)], fill=lerp(glow_c, top_c, i / 45), width=3)


def stars(img, rng, n=220):
    d = ImageDraw.Draw(img)
    for _ in range(n):
        x, y = rng.randint(0, W), rng.randint(0, int(H * 0.7))
        r = rng.choice([1, 1, 1, 2, 2, 3])
        c = rng.choice([(255, 255, 255), (255, 244, 214), (214, 230, 255)])
        d.ellipse([x - r, y - r, x + r, y + r], fill=c)
    for _ in range(6):
        x, y = rng.randint(0, W), rng.randint(0, int(H * 0.55))
        img.alpha_composite(radial_glow((W, H), (x, y), 22, (255, 255, 255), 160))


def moon(img, rng, cx, cy, r):
    img.alpha_composite(radial_glow((W, H), (cx, cy), int(r * 2.6), (255, 245, 210), 120))
    d = ImageDraw.Draw(img)
    if rng.random() < 0.5:  # yarim oy
        m = Image.new("L", (W, H), 0)
        md = ImageDraw.Draw(m)
        md.ellipse([cx - r, cy - r, cx + r, cy + r], fill=255)
        off = int(r * 0.45)
        md.ellipse([cx - r + off, cy - r - off * 0.3, cx + r + off, cy + r - off * 0.3], fill=0)
        layer = Image.new("RGBA", (W, H), (255, 246, 214, 255))
        layer.putalpha(m)
        img.alpha_composite(layer)
    else:
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 246, 220))
        for _ in range(5):
            rr = rng.randint(6, int(r * 0.25))
            x, y = cx + rng.randint(-r // 2, r // 2), cy + rng.randint(-r // 2, r // 2)
            d.ellipse([x - rr, y - rr, x + rr, y + rr], fill=(236, 226, 196))


def sun(img, cx, cy, r, color=(255, 236, 170)):
    img.alpha_composite(radial_glow((W, H), (cx, cy), int(r * 3.2), (255, 214, 140), 170))
    ImageDraw.Draw(img).ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)


def clouds(img, rng, color, n=4, ymax=0.45):
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for _ in range(n):
        x, y = rng.randint(-100, W), rng.randint(80, int(H * ymax))
        for _ in range(6):
            w_, h_ = rng.randint(120, 260), rng.randint(50, 100)
            ox, oy = rng.randint(-120, 120), rng.randint(-30, 30)
            d.ellipse([x + ox, y + oy, x + ox + w_, y + oy + h_], fill=color + (150,))
    img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(10)))


def birds(img, rng, color=(60, 40, 60)):
    d = ImageDraw.Draw(img)
    x0, y0 = rng.randint(150, W - 300), rng.randint(250, 500)
    for _ in range(rng.randint(3, 7)):
        x, y, s = x0 + rng.randint(-150, 200), y0 + rng.randint(-80, 80), rng.randint(14, 28)
        d.arc([x - s, y - s / 2, x, y + s / 2], 200, 340, fill=color, width=3)
        d.arc([x, y - s / 2, x + s, y + s / 2], 200, 340, fill=color, width=3)


def scene_morning(rng):
    sk = rng.choice(DAWN_SKIES)
    img = sky(sk)
    kind = rng.choice(["mountains", "sea", "hills", "city"])
    sx, sy = rng.choice([rng.randint(170, 380), rng.randint(700, 910)]), rng.randint(820, 900)
    sun(img, sx, sy, rng.randint(70, 110))
    clouds(img, rng, (255, 245, 235), rng.randint(2, 5), 0.5)
    dark = lerp(sk[2], (20, 20, 40), 0.55)
    if kind == "mountains":
        mountains(img, rng, [lerp(sk[1], dark, 0.35), lerp(sk[1], dark, 0.6), lerp(sk[1], dark, 0.85)], 960)
    elif kind == "sea":
        sea(img, rng, lerp(sk[1], sk[2], 0.4), lerp(sk[2], (10, 20, 50), 0.6), 960, sx)
    elif kind == "hills":
        hills(img, rng, [lerp((120, 190, 110), sk[1], 0.4), (88, 160, 90), (52, 120, 70)], 980)
    else:
        city(img, rng, lerp(sk[2], (25, 20, 45), 0.7), 1200)
    birds(img, rng, lerp(sk[2], (20, 10, 30), 0.7))
    return img, kind


def scene_night(rng):
    sk = rng.choice(NIGHT_SKIES)
    img = sky(sk)
    stars(img, rng, rng.randint(160, 300))
    moon(img, rng, rng.choice([rng.randint(170, 330), rng.randint(750, 910)]), rng.randint(800, 880), rng.randint(65, 95))
    kind = rng.choice(["mountains", "city", "hills", "sea"])
    if kind == "mountains":
        mountains(img, rng, [lerp(sk[2], (0, 0, 0), 0.3), lerp(sk[1], (0, 0, 0), 0.4), (8, 8, 18)], 980)
    elif kind == "city":
        city(img, rng, (12, 12, 26), 1230, lights=True)
    elif kind == "hills":
        hills(img, rng, [lerp(sk[2], (0, 0, 0), 0.35), lerp(sk[1], (0, 0, 0), 0.5), (6, 8, 16)], 1000)
    else:
        sea(img, rng, lerp(sk[1], (0, 0, 0), 0.2), (2, 4, 14), 990, None)
    return img, kind


def _photo_cover(photo):
    photo = photo.convert("RGB")
    s = max(W / photo.width, H / photo.height)
    photo = photo.resize((int(photo.width * s) + 1, int(photo.height * s) + 1), Image.LANCZOS)
    l, t = (photo.width - W) // 2, (photo.height - H) // 2
    return photo.crop((l, t, l + W, t + H)).convert("RGBA")


def render_greeting(kind: str, wish: str = "", footer: str = "t.me/investtalim  •  +998 90 642 18 08",
                    seed=None, bg_photo: Image.Image | None = None) -> tuple[Image.Image, str]:
    """kind: 'morning' yoki 'night'. wish — qisqa tilak (o'zbekcha)."""
    rng = random.Random(seed)
    if bg_photo is not None:
        img, scene = _photo_cover(bg_photo), "photo"
    else:
        img, scene = (scene_morning if kind == "morning" else scene_night)(rng)
    # matn uchun yumshoq qorong'i fon (yuqorida)
    shade = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shade)
    for y in range(0, 800):
        a = int(150 * (1 - y / 800) ** 1.2)
        sd.line([(0, y), (W, y)], fill=(0, 0, 10, a))
    for y in range(H - 260, H):
        a = int(150 * ((y - (H - 260)) / 260) ** 1.2)
        sd.line([(0, y), (W, y)], fill=(0, 0, 10, a))
    img.alpha_composite(shade)
    d = ImageDraw.Draw(img)
    paste_logo(img, ((W - 200) / 2, 36), (0, 0, 0), 200)
    lines = GREET[kind]
    main = lines[0][1]
    mfont_name = rng.choice(["playfair", "caveat", "montserrat", "comfortaa"])
    size = {"caveat": 170, "playfair": 130, "montserrat": 118, "comfortaa": 116}[mfont_name]
    mf = font(mfont_name, size, "Bold")
    y = 250 + size // 2 + 40
    st = {"stroke_width": 2, "stroke_fill": (0, 0, 0, 60)}
    draw_text(d, (W / 2 + 4, y + 6), main, mf, (0, 0, 0, 110), anchor="mm")
    draw_text(d, (W / 2, y), main, mf, (255, 255, 255), anchor="mm", **st)
    y += size // 2 + 54
    for t in [t for _, t in lines[1:]]:
        f = font_for(t, "montserrat", 50 if is_arabic(t) else 46, "SemiBold")
        draw_text(d, (W / 2, y), t, f, (255, 250, 240), anchor="mm", stroke_width=1, stroke_fill=(0, 0, 0, 120))
        y += 66
    if wish:
        y += 20
        wf, wl, wlh = fit_text(d, wish, "montserrat", W - 180, 170, 42, 28, "SemiBold", 1.25)
        for line in wl:
            draw_text(d, (W / 2, y), line, wf, (255, 255, 255), anchor="mm", stroke_width=1, stroke_fill=(0, 0, 0, 130))
            y += wlh
    ff = font("montserrat", 30, "SemiBold")
    draw_text(d, (W / 2, H - 60), footer, ff, (255, 255, 255), anchor="mm")
    return img.convert("RGB"), scene


# ───────────────────────── Bepul AI fon (ixtiyoriy) ─────────────────────────
def fetch_ai_background(prompt: str, seed: int, timeout: float = 60, api_key: str = "") -> Image.Image | None:
    """Pollinations.ai orqali bepul AI rasm. Ishlamasa None qaytaradi (bot chizilgan rasmga o'tadi)."""
    import httpx

    q = urllib.parse.quote(prompt + ", no text, no letters, no watermark, high quality")
    params = f"width=1080&height=1350&seed={seed}&nologo=true&model=flux"
    urls = [f"https://image.pollinations.ai/prompt/{q}?{params}",
            f"https://gen.pollinations.ai/image/{q}?{params}" + (f"&key={api_key}" if api_key else "")]
    for url in urls:
        try:
            r = httpx.get(url, timeout=timeout, follow_redirects=True)
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("image"):
                im = Image.open(io.BytesIO(r.content))
                im.load()
                if im.width >= 400:
                    return im
        except Exception:
            continue
    return None


def to_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=92)
    return buf.getvalue()
