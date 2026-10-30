"""
Kontent generatsiyasi va sifat tekshiruvi.

1-bosqich: AI post yozadi (JSON ko'rinishida).
2-bosqich: boshqa "muharrir" so'rovi postni tekshiradi: faktlar, tarjimalar,
           imlo, arab harakatlari, rus grammatikasi. Xatolarni tuzatadi va baho beradi.
3-bosqich: kod formatni tekshiradi (uzunlik, test variantlari va h.k.).
Baho past bo'lsa — post qaytadan yoziladi.

Bepul AI: Google Gemini (AI Studio kaliti). Zaxira: Groq (ixtiyoriy, bepul kalit).
"""
from __future__ import annotations

import html
import json
import logging
import random
import re
import time

import httpx

log = logging.getLogger("content")

LANG_NAMES = {
    "en": ("English", "Ingliz tili", "🇬🇧"),
    "ar": ("Arabic (Modern Standard Arabic, fusha)", "Arab tili", "🇸🇦"),
    "ru": ("Russian", "Rus tili", "🇷🇺"),
}

POST_TYPES = {
    "grammatika": ("GRAMMATIKA", "One grammar rule explained very simply in Uzbek, 3-4 example sentences in the target language each with Uzbek translation, plus one short 💡 tip about a common mistake.", 3),
    "lugat": ("LUG‘AT", "A themed mini-vocabulary: 5-7 useful words/phrases on one everyday theme, each with Uzbek translation, plus one example sentence using one of them.", 3),
    "ibora": ("IBORA", "One idiom, proverb or set phrase: literal meaning, real meaning, Uzbek equivalent if there is one, and 2 example sentences with translation.", 2),
    "test": ("TEST", "An interactive quiz. The caption briefly introduces the point being tested and invites readers to answer in the quiz poll below (do NOT reveal the answer in the caption). Fill the 'quiz' object.", 3),
    "xatoni_top": ("XATONI TOP", "Interactive 'find the mistake': give 1-2 sentences in the target language containing one typical learner mistake. Ask readers to find it and write in the comments. Put the correct version and short explanation inside ||spoiler|| markers.", 2),
    "dialog": ("DIALOG", "A short natural dialogue (4-6 lines) for an everyday situation, every line with Uzbek translation, then 2-3 key phrases highlighted.", 2),
    "kunning_sozi": ("KUNNING SO‘ZI", "Word of the day: the word, its meaning, part of speech/forms, 2 example sentences with translation, and 1-2 synonyms or related words.", 2),
    "tarjima": ("TARJIMA MASHQI", "Interactive translation exercise: 3 short Uzbek sentences for readers to translate into the target language. Put the correct translations inside ||spoiler|| markers.", 2),
    "farq": ("FARQI NIMADA?", "Two (or three) commonly confused words or forms: clear explanation of the difference in Uzbek with 2 examples each and translations.", 2),
    "fakt": ("QIZIQARLI FAKT", "One interesting, TRUE and well-known fact about the language (history, words, usage), then 3-4 related useful words with translation. Only facts you are completely sure about.", 1),
}

LANG_RULES = {
    "en": "Use correct standard English. Prefer British/American-neutral spelling. Keep level A1-B2.",
    "ar": ("Use correct Modern Standard Arabic (fusha). Put full harakat (tashkeel) on the key words and example "
           "sentences so learners can read them. Use Uzbek grammar terms that Uzbek Arabic learners use "
           "(mubtado, xabar, fe’l, ism, harf, muzakkar, muannas, birlik, ko‘plik, idofa ...). Level beginner-intermediate."),
    "ru": ("Use correct standard Russian. Mention gender/case/aspect where relevant. You may mark stress with an acute "
           "accent (´) on tricky words. Level A1-B2."),
}

UZ_RULES = ("Write the Uzbek parts in correct modern Uzbek LATIN script (never Cyrillic Uzbek). Use o‘ and g‘ "
            "with the ‘ character (U+2018) and ’ (U+2019) for the tutuq belgisi (ta’lim, ma’no). "
            "Natural, friendly, motivating tone for students and parents.")

FORMAT_RULES = """Telegram formatting markers you may use inside text (NO HTML!):
**bold**   __italic__   ||spoiler (hidden answer)||
Use 4-8 emojis that fit the topic (not random), e.g. 📚 ✍️ 💡 ✅ ❌ 🗣 🔹 👉 ❓ 🎯.
Structure: an attention-grabbing first line with an emoji and **bold title**; short blocks separated by blank lines;
examples on separate lines like: 🔹 target-language sentence — Uzbek translation.
End the caption with ONE short engaging question or call to action in Uzbek (e.g. "Izohlarda o‘z misolingizni yozing 👇").
Do NOT add hashtags, links, phone numbers or the learning-centre name to the caption — the bot adds them itself."""

POST_SCHEMA = """Return ONLY a JSON object with exactly these keys:
{
  "topic": "short name of the exact topic in Uzbek (for history, <= 60 chars)",
  "caption": "the post text (Uzbek + target language mixed, with translations), %(min)d-%(max)d characters",
  "hashtags": ["3-5 hashtags in Latin letters without spaces, e.g. #ingliztili #grammatika"],
  "image": {
    "title": "short title IN THE TARGET LANGUAGE for the picture, <= 38 chars (for tests: the tested point, never the answer)",
    "subtitle": "short Uzbek explanation for the picture, <= 70 chars",
    "lines": ["0-4 very short lines for the picture, each <= 34 chars, like 'word — tarjima'"]
  },
  "image_prompt": "English description of a fitting background PHOTO without any text (scene/objects), <= 25 words",
  "quiz": null OR {"question": "<= 250 chars, Uzbek with target-language part", "options": ["2-4 options, each <= 90 chars"], "correct": 0, "explanation": "<= 180 chars, Uzbek"}
}
"quiz" must be filled ONLY when the post type is TEST, otherwise null."""

CHECK_PROMPT = """You are a strict senior editor and native-level expert of %(lang)s and of Uzbek.
Check this Telegram post for a language learning centre. Verify EVERY fact, rule, example, translation and spelling:
- target-language grammar and spelling are 100%% correct, examples sound natural;
- every Uzbek translation is accurate; Uzbek is correct Latin script with o‘ g‘ ’;
- the grammar explanation is true (no invented rules), quiz has exactly ONE correct option and "correct" index points to it;
- facts are real and well known (if doubtful, replace with a safe true one);
- answers are hidden in ||spoiler|| where the post asks readers to guess; caption does not reveal quiz answer;
- caption length is %(min)d-%(max)d characters, no hashtags/links/phones inside caption, emojis fit the topic;
- picture texts are short (title <= 38, subtitle <= 70, each line <= 34 chars).
%(lang_rules)s
Fix every problem yourself. Keep the same topic and post type.
Return ONLY JSON: {"score": 1-10 (quality AFTER your fixes), "issues": ["short list of what you fixed, in Uzbek"], "post": {the full corrected post with exactly the same keys}}

POST TYPE: %(ptype)s
POST:
%(post)s"""

GREETING_PROMPT = """Write a %(kind)s greeting post for the Telegram channel of a foreign-language learning centre in Uzbekistan
(students learn English, Arabic and Russian). Today is %(date)s (%(weekday)s).
Return ONLY JSON:
{
 "caption": "warm greeting in FOUR languages, each on its own line with a fitting emoji: Uzbek (Latin), English, Russian, Arabic (with harakat); then a blank line and one short motivating thought about learning in Uzbek (1-2 sentences); 200-450 characters total; you may use **bold**",
 "wish": "the same motivating thought shortened for the picture, Uzbek, <= 70 chars",
 "image_prompt": "English description of a beautiful %(scene)s photo without any text, <= 20 words",
 "hashtags": ["2-3 hashtags in Latin letters"]
}
""" + UZ_RULES + " Do not add links, phone numbers or the centre name."

MARKER_RE = re.compile(r"\*\*(.+?)\*\*|__(.+?)__|\|\|(.+?)\|\|", re.S)


class AIError(Exception):
    pass


# ───────────────────────── AI mijoz ─────────────────────────
class AI:
    def __init__(self, gemini_key: str, models: list[str], groq_key: str = "", groq_model: str = "llama-3.3-70b-versatile"):
        self.gemini_key = gemini_key.strip()
        self.models = list(models)
        self.groq_key = groq_key.strip()
        self.groq_model = groq_model
        self.last_used = ""
        self.dead: set[str] = set()      # bu ishga tushishda ishlamagan modellar
        self.discovered = False

    def _discover(self):
        """Kalitga ochiq bo'lgan flash modellarni avtomatik topadi (eski modellar yopilsa ham ishlayveradi)."""
        self.discovered = True
        try:
            r = httpx.get("https://generativelanguage.googleapis.com/v1beta/models",
                          headers={"x-goog-api-key": self.gemini_key}, params={"pageSize": 200}, timeout=30)
            names = [m["name"].split("/")[-1] for m in r.json().get("models", [])
                     if "generateContent" in m.get("supportedGenerationMethods", [])]
            bad = ("image", "tts", "live", "audio", "embedding", "omni", "pro")
            extra = [n for n in names if "flash" in n and not any(b in n for b in bad) and n not in self.models]
            extra.sort(key=lambda n: ("preview" in n, "lite" in n))
            self.models += extra
            log.info("Qo'shimcha modellar topildi: %s", extra)
        except Exception as e:
            log.warning("Modellar ro'yxatini olib bo'lmadi: %s", e)

    def _gemini(self, model: str, prompt: str, temperature: float, thinking: str) -> str:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        cfg = {"temperature": temperature, "responseMimeType": "application/json", "maxOutputTokens": 8192}
        if thinking:
            cfg["thinkingConfig"] = {"thinkingLevel": thinking}
        body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": cfg}
        # Yangi "AQ." kalitlar ham, eski "AIza" kalitlar ham sarlavha (header) orqali ishlaydi
        r = httpx.post(url, headers={"x-goog-api-key": self.gemini_key}, json=body, timeout=150)
        if r.status_code == 400 and "thinking" in r.text.lower():  # model bu sozlamani qo'llamasa
            cfg.pop("thinkingConfig", None)
            r = httpx.post(url, headers={"x-goog-api-key": self.gemini_key}, json=body, timeout=150)
        if r.status_code in (401, 403):  # zaxira: kalitni manzil orqali yuborib ko'ramiz
            r = httpx.post(url, params={"key": self.gemini_key}, json=body, timeout=150)
        if r.status_code != 200:
            raise AIError(f"Gemini {model}: {r.status_code} {r.text[:300]}")
        data = r.json()
        try:
            parts = data["candidates"][0]["content"]["parts"]
            return "".join(p.get("text", "") for p in parts if not p.get("thought"))
        except Exception:
            raise AIError(f"Gemini {model}: bo'sh javob {str(data)[:300]}")

    def _groq(self, prompt: str, temperature: float) -> str:
        r = httpx.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {self.groq_key}"},
            json={"model": self.groq_model, "temperature": temperature,
                  "response_format": {"type": "json_object"},
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=120,
        )
        if r.status_code != 200:
            raise AIError(f"Groq: {r.status_code} {r.text[:300]}")
        return r.json()["choices"][0]["message"]["content"]

    def json(self, prompt: str, temperature: float = 0.9, thinking: str = "low") -> dict:
        errors = []
        if self.gemini_key:
            for round_ in range(2):
                for m in [m for m in self.models if m not in self.dead]:
                    for attempt in range(2):
                        try:
                            out = parse_json(self._gemini(m, prompt, temperature, thinking))
                            self.last_used = m
                            return out
                        except Exception as e:
                            msg = str(e)
                            errors.append(msg[:200])
                            log.warning("AI xato (%s): %s", m, msg[:200])
                            if " 404 " in msg or " 403 " in msg or " 401 " in msg:
                                self.dead.add(m)  # bu model yopiq — boshqa urinmaymiz
                                break
                            if "timed out" in msg or " 400 " in msg:
                                break  # sekin yoki mos emas — keyingi modelga
                            if " 429 " in msg or " 503 " in msg or " 500 " in msg:
                                time.sleep(4 * (attempt + 1))
                                continue
                            if attempt == 0:  # JSON buzilgan bo'lsa — bir marta qayta urinamiz
                                continue
                if self.discovered:
                    break
                self._discover()
        if self.groq_key:
            try:
                out = parse_json(self._groq(prompt, temperature))
                self.last_used = "groq:" + self.groq_model
                return out
            except Exception as e:
                errors.append(str(e)[:200])
        raise AIError("Barcha AI urinishlari muvaffaqiyatsiz: " + " | ".join(errors[-3:]))


def parse_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise AIError("JSON topilmadi")
        return json.loads(m.group(0))


# ───────────────────────── Formatlash ─────────────────────────
def to_html(text: str) -> str:
    """**qalin**, __kursiv__, ||yashirin|| → Telegram HTML (xavfsiz)."""
    text = text.replace("<", "‹").replace(">", "›")  # AI HTML yozib qo'ysa ham buzilmasin
    out, pos = [], 0
    for m in MARKER_RE.finditer(text):
        out.append(html.escape(text[pos:m.start()], quote=False))
        b, i, s = m.groups()
        if b is not None:
            out.append(f"<b>{html.escape(b, quote=False)}</b>")
        elif i is not None:
            out.append(f"<i>{html.escape(i, quote=False)}</i>")
        else:
            out.append(f"<tg-spoiler>{html.escape(s, quote=False)}</tg-spoiler>")
        pos = m.end()
    out.append(html.escape(text[pos:], quote=False))
    return "".join(out)


def plain(text: str) -> str:
    return MARKER_RE.sub(lambda m: next(g for g in m.groups() if g is not None), text)


def tg_len(text: str) -> int:
    """Telegram uzunlikni UTF-16 birliklarda sanaydi (emoji = 2)."""
    return len(text.encode("utf-16-le")) // 2


def clean_hashtags(tags) -> list[str]:
    res = []
    for t in tags or []:
        t = re.sub(r"[^\w]", "", str(t).replace("‘", "").replace("’", "").replace("'", ""))
        if t and not t.isdigit():
            res.append("#" + t.lower())
    return list(dict.fromkeys(res))[:5]


def build_caption(body: str, hashtags: list[str], footer: str) -> str:
    parts = [body.strip()]
    if hashtags:
        parts.append(" ".join(hashtags))
    if footer:
        parts.append(footer.strip())
    return "\n\n".join(parts)


def strip_footer(text: str, footer: str) -> str:
    """Admin tahrirlab yuborgan matndan avtomatik qism (heshteg, kontakt)ni olib tashlaydi."""
    first = footer.strip().splitlines()[0] if footer.strip() else ""
    if first and first in text:
        text = text[: text.index(first)]
    lines = text.rstrip().splitlines()
    while lines and (not lines[-1].strip() or all(w.startswith("#") for w in lines[-1].split())):
        lines.pop()
    return "\n".join(lines).strip()


# ───────────────────────── Tekshiruv (kod) ─────────────────────────
def validate(post: dict, ptype: str, min_len: int, max_len: int) -> list[str]:
    errs = []
    for k in ("topic", "caption", "image"):
        if not post.get(k):
            errs.append(f"'{k}' yo'q")
    cap = plain(str(post.get("caption", "")))
    if tg_len(cap) < min_len * 0.7:
        errs.append("matn juda qisqa")
    if tg_len(cap) > max_len * 1.15:
        errs.append("matn juda uzun")
    if re.search(r"https?://|t\.me/|\+998", cap):
        errs.append("matnda havola/telefon bor")
    if re.search(r"[ЎўҚқҒғҲҳ]", cap):
        errs.append("o'zbekcha kirillda yozilgan")
    img = post.get("image") or {}
    if not str(img.get("title", "")).strip():
        errs.append("rasm sarlavhasi yo'q")
    if ptype == "test":
        q = post.get("quiz") or {}
        opts = q.get("options") or []
        if not (2 <= len(opts) <= 10):
            errs.append("test variantlari noto'g'ri")
        if not isinstance(q.get("correct"), int) or not (0 <= q.get("correct", -1) < len(opts)):
            errs.append("to'g'ri javob indeksi noto'g'ri")
        if len(set(map(str, opts))) != len(opts):
            errs.append("test variantlari takrorlangan")
    return errs


def normalize(post: dict, ptype: str) -> dict:
    img = post.get("image") or {}
    img["title"] = str(img.get("title", "")).strip()[:60]
    img["subtitle"] = str(img.get("subtitle", "")).strip()[:110]
    img["lines"] = [str(x).strip()[:48] for x in (img.get("lines") or []) if str(x).strip()][:4]
    post["image"] = img
    post["hashtags"] = clean_hashtags(post.get("hashtags"))
    post["caption"] = str(post.get("caption", "")).strip()
    if ptype == "test" and post.get("quiz"):
        q = post["quiz"]
        q["question"] = str(q.get("question", ""))[:300]
        q["options"] = [str(o)[:100] for o in q.get("options", [])][:10]
        q["explanation"] = str(q.get("explanation", "") or "")[:200]
        try:
            q["correct"] = int(q.get("correct", 0))
        except Exception:
            q["correct"] = -1
    else:
        post["quiz"] = None
    return post


# ───────────────────────── Asosiy funksiyalar ─────────────────────────
def pick_type(history_types: list[str], allowed: list[str] | None = None, rng=random) -> str:
    keys = [k for k in POST_TYPES if not allowed or k in allowed]
    recent = history_types[-3:]
    pool = [k for k in keys if k not in recent] or keys
    weights = [POST_TYPES[k][2] for k in pool]
    return rng.choices(pool, weights=weights, k=1)[0]


def generate_post(ai: AI, lang: str, ptype: str, history_topics: list[str], topic_hints: list[str],
                  min_len: int = 450, max_len: int = 760, min_score: int = 7, extra_style: str = "") -> dict:
    lname, luz, flag = LANG_NAMES[lang]
    label, desc, _ = POST_TYPES[ptype]
    hint = random.choice(topic_hints) if topic_hints else ""
    avoid = "; ".join(history_topics[-40:]) or "—"
    best, best_score, report = None, -1, []
    for attempt in range(3):
        prompt = (
            f"You write daily educational posts for the Telegram channel of 'Foreign Investta’lim' language "
            f"centre (Namangan, Uzbekistan). Audience: Uzbek-speaking school students and adults learning {lname}.\n"
            f"Target language: {lname}. Start the caption with the flag {flag}.\n"
            f"Post type: {label} — {desc}\n"
            + (f"Topic area to choose from (pick something specific inside it): {hint}\n" if hint else "")
            + f"Do NOT repeat these recent topics: {avoid}\n"
            f"{LANG_RULES[lang]}\n{UZ_RULES}\n{FORMAT_RULES}\n{extra_style}\n"
            + POST_SCHEMA % {"min": min_len, "max": max_len}
        )
        try:
            draft = normalize(ai.json(prompt, temperature=0.95), ptype)
        except Exception as e:
            report.append(f"yozishda xato: {e}")
            continue
        # 2-bosqich: muharrir tekshiruvi
        try:
            chk = ai.json(CHECK_PROMPT % {"lang": lname, "min": min_len, "max": max_len,
                                          "lang_rules": LANG_RULES[lang], "ptype": label,
                                          "post": json.dumps(draft, ensure_ascii=False, indent=1)},
                          temperature=0.2, thinking="medium")
            fixed = chk.get("post") or draft
            for k in draft:
                fixed.setdefault(k, draft[k])
            post = normalize(fixed, ptype)
            score = int(chk.get("score", 0) or 0)
            issues = [str(i) for i in (chk.get("issues") or [])][:6]
        except Exception as e:
            post, score, issues = draft, 5, [f"tekshiruv bajarilmadi: {e}"]
        errs = validate(post, ptype, min_len, max_len)
        if errs:
            score = min(score, 6)
            issues += ["format: " + ", ".join(errs)]
        log.info("Post %s/%s urinish %d: baho %s, %s", lang, ptype, attempt + 1, score, issues)
        if score > best_score and not (ptype == "test" and any("test" in e or "indeks" in e for e in errs)):
            best, best_score, report = post, score, issues
        if score >= min_score and not errs:
            break
    if best is None:
        raise AIError("Post yozib bo'lmadi: " + "; ".join(report))
    best["_score"] = best_score
    best["_issues"] = report
    best["_type"] = ptype
    best["_lang"] = lang
    best["_model"] = ai.last_used
    return best


WEEKDAYS = ["Dushanba", "Seshanba", "Chorshanba", "Payshanba", "Juma", "Shanba", "Yakshanba"]


def generate_greeting(ai: AI, kind: str, date) -> dict:
    scene = "sunrise / morning nature" if kind == "morning" else "night sky with moon and stars"
    k = "GOOD MORNING (Xayrli tong)" if kind == "morning" else "GOOD NIGHT (Xayrli tun)"
    try:
        out = ai.json(GREETING_PROMPT % {"kind": k, "date": date.strftime("%d.%m.%Y"),
                                         "weekday": WEEKDAYS[date.weekday()], "scene": scene}, 0.95)
        cap = str(out.get("caption", "")).strip()
        if len(cap) < 60 or re.search(r"https?://|\+998", cap):
            raise AIError("tabrik matni yaroqsiz")
        return {"caption": cap, "wish": str(out.get("wish", ""))[:90], "image_prompt": out.get("image_prompt", scene),
                "hashtags": clean_hashtags(out.get("hashtags")) or ["#investtalim"], "_score": 9, "_issues": [],
                "_model": ai.last_used}
    except Exception as e:  # AI ishlamasa ham tabrik chiqaveradi
        log.warning("Tabrik AI xato, zaxira matn: %s", e)
        return fallback_greeting(kind)


FALLBACK_WISH = {
    "morning": ["Bugun yangi bilim olish uchun ajoyib kun!", "Har bir yangi so‘z — kelajakka qo‘yilgan qadam.",
                "Kuningiz barakali va unumli o‘tsin!", "Kichik qadamlar katta natijalarga olib keladi."],
    "night": ["Yaxshi dam oling, ertaga yangi bilimlar kutmoqda!", "Bugun o‘rgangan so‘zlaringizni bir takrorlab qo‘ying 😉",
              "Shirin tushlar! Ertaga yana birga o‘rganamiz.", "Dam olish ham o‘qishning bir qismi."],
}


def fallback_greeting(kind: str) -> dict:
    wish = random.choice(FALLBACK_WISH[kind])
    if kind == "morning":
        cap = ("☀️ **Xayrli tong, aziz o‘quvchilar!**\n🇬🇧 Good morning!\n🇷🇺 Доброе утро!\n🇸🇦 صَبَاحُ الْخَيْرِ!\n\n" + wish)
    else:
        cap = ("🌙 **Xayrli tun, aziz o‘quvchilar!**\n🇬🇧 Good night!\n🇷🇺 Спокойной ночи!\n🇸🇦 تُصْبِحُ عَلَى خَيْرٍ!\n\n" + wish)
    return {"caption": cap, "wish": wish, "image_prompt": "", "hashtags": ["#investtalim", "#xayrlitong" if kind == "morning" else "#xayrlitun"],
            "_score": 10, "_issues": ["zaxira matn ishlatildi (AI javob bermadi)"], "_model": "zaxira"}
