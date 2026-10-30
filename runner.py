"""
GitHub Actions uchun bir martalik ishga tushiriladigan post boti (server kerak emas).

GitHub har bir jadval vaqtidan ~30 daqiqa oldin shu skriptni ishga tushiradi:
  1) navbatdagi vaqtni topadi va vaqtdan 13 daqiqa oldin postni tayyorlaydi (AI + tekshiruv + rasm);
  2) postni adminga tugmalar bilan yuboradi;
  3) belgilangan vaqtgacha admin javobini kutadi (tasdiqlash, tahrirlash, qayta yozish, bekor qilish);
  4) vaqt kelganda kanalga chiqaradi va holatni (state.json) saqlaydi.

Qo'lda sinov:  python runner.py --tur en --test
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import logging
import os
import random
import sys
import time
from zoneinfo import ZoneInfo

import httpx
import yaml

import content as C
import images as I

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
os.makedirs(os.path.join(DATA, "rasmlar"), exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout),
                              logging.FileHandler(os.path.join(BASE, "jurnal.txt"), mode="w", encoding="utf-8")])
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("runner")

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE, ".env"))
except Exception:
    pass

with open(os.path.join(BASE, "config.yaml"), encoding="utf-8") as f:
    CFG = yaml.safe_load(f)

TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN = int(os.getenv("ADMIN_ID") or CFG.get("admin_id") or 0)
CHANNEL = (os.getenv("KANAL", "") or CFG.get("kanal", "")).strip()
TZ = ZoneInfo(CFG.get("vaqt_mintaqasi", "Asia/Tashkent"))
APPROVE = CFG.get("tasdiqlash", {})
LEAD_MIN = int(APPROVE.get("oldindan_daqiqa", 10))
PREP_MIN = int(APPROVE.get("tayyorlash_daqiqa", 3))
POSTCFG = CFG.get("post", {})
FOOTER = CFG.get("pastki_qism", "").strip()
IMG_FOOTER = CFG.get("rasm_yozuvi", "t.me/investtalim")
RASM = CFG.get("rasm", {})
CAPTION_LIMIT = 1024
MIN_REVIEW = dt.timedelta(minutes=3)   # kechikkan bo'lsa ham kamida shuncha vaqt ko'rib chiqishga beriladi
LATE_LIMIT = dt.timedelta(minutes=40)  # vaqtdan shuncha o'tib ketsa, post o'tkazib yuboriladi

KIND_INFO = {
    "en": ("🇬🇧", "Ingliz tili"), "ar": ("🇸🇦", "Arab tili"), "ru": ("🇷🇺", "Rus tili"),
    "tong": ("☀️", "Xayrli tong"), "tun": ("🌙", "Xayrli tun"),
}

ai = C.AI(os.getenv("GEMINI_API_KEY", ""), CFG.get("ai", {}).get("gemini_modellar", ["gemini-2.5-flash"]),
          os.getenv("GROQ_API_KEY", ""), CFG.get("ai", {}).get("groq_model", "llama-3.3-70b-versatile"))


def now() -> dt.datetime:
    return dt.datetime.now(TZ)


def slot_dt(date: dt.date, hhmm: str) -> dt.datetime:
    h, m = map(int, hhmm.split(":"))
    return dt.datetime(date.year, date.month, date.day, h, m, tzinfo=TZ)


# ───────────────────────── Holat ─────────────────────────
STATE_PATH = os.path.join(BASE, "state.json")


def load_state() -> dict:
    st = {"history": {}, "types": {}, "templates": [], "paused": False, "done": {}, "offset": 0}
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, encoding="utf-8") as f:
                st.update(json.load(f))
        except Exception:
            log.exception("state.json o'qilmadi")
    return st


def save_state(st: dict):
    cutoff = (now() - dt.timedelta(days=14)).date().isoformat()
    st["done"] = {k: v for k, v in st.get("done", {}).items() if k[:10] >= cutoff}
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)


def push(lst: list, value, keep=60):
    lst.append(value)
    del lst[:-keep]


# ───────────────────────── Telegram (oddiy HTTP) ─────────────────────────
class TG:
    def __init__(self, token):
        self.base = f"https://api.telegram.org/bot{token}/"
        self.fbase = f"https://api.telegram.org/file/bot{token}/"
        self.c = httpx.Client(timeout=60)

    def call(self, method, files=None, **params):
        data = {k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v)
                for k, v in params.items() if v is not None}
        for attempt in range(4):
            try:
                r = self.c.post(self.base + method, data=data, files=files,
                                timeout=70 if method == "getUpdates" else 60)
                j = r.json()
                if j.get("ok"):
                    return j["result"]
                if j.get("error_code") == 429:
                    time.sleep(int(j.get("parameters", {}).get("retry_after", 5)) + 1)
                    continue
                raise RuntimeError(f"{method}: {j.get('description')}")
            except (httpx.TransportError, ValueError) as e:
                log.warning("Telegram tarmoq xatosi (%s): %s", method, e)
                time.sleep(3 * (attempt + 1))
                if files:
                    for v in files.values():
                        try:
                            v[1].seek(0)
                        except Exception:
                            pass
        raise RuntimeError(f"{method}: Telegram javob bermadi")

    def send_message(self, chat, text, kb=None):
        return self.call("sendMessage", chat_id=chat, text=text, parse_mode="HTML",
                         disable_web_page_preview=True, reply_markup=kb)

    def send_photo(self, chat, path, caption=None):
        with open(path, "rb") as ph:
            return self.call("sendPhoto", files={"photo": ("post.jpg", ph, "image/jpeg")}, chat_id=chat,
                             caption=caption, parse_mode="HTML" if caption else None)

    def send_poll(self, chat, q):
        return self.call("sendPoll", chat_id=chat, question=q["question"][:300],
                         options=[o[:100] for o in q["options"]], type="quiz",
                         correct_option_id=int(q["correct"]), explanation=(q.get("explanation") or None)
                         and q["explanation"][:200], is_anonymous=True)

    def edit(self, chat, mid, text, kb=None):
        try:
            return self.call("editMessageText", chat_id=chat, message_id=mid, text=text, parse_mode="HTML",
                             disable_web_page_preview=True, reply_markup=kb or {"inline_keyboard": []})
        except Exception as e:
            if "not modified" not in str(e):
                log.warning("Tahrirlab bo'lmadi: %s", e)

    def answer(self, cb_id, text=""):
        try:
            self.call("answerCallbackQuery", callback_query_id=cb_id, text=text[:190])
        except Exception:
            pass

    def updates(self, offset, timeout=20):
        return self.call("getUpdates", offset=offset, timeout=timeout,
                         allowed_updates=["message", "callback_query"])

    def download(self, file_id, path):
        info = self.call("getFile", file_id=file_id)
        r = self.c.get(self.fbase + info["file_path"])
        with open(path, "wb") as f:
            f.write(r.content)


def entities_to_html(text: str, entities: list | None) -> str:
    """Telegram matnidagi qalin/kursiv/yashirin formatlashni HTML ga o'giradi."""
    if not entities:
        return html.escape(text, quote=False)
    u = text.encode("utf-16-le")
    tags = {"bold": "b", "italic": "i", "underline": "u", "strikethrough": "s", "spoiler": "tg-spoiler",
            "code": "code"}
    ents = sorted([e for e in entities if e.get("type") in tags], key=lambda e: e["offset"])
    out, pos = [], 0
    for e in ents:
        s, l = e["offset"], e["length"]
        if s < pos:
            continue  # ichma-ich formatlash — soddalashtiramiz
        out.append(html.escape(u[pos * 2:s * 2].decode("utf-16-le"), quote=False))
        t = tags[e["type"]]
        out.append(f"<{t}>{html.escape(u[s * 2:(s + l) * 2].decode('utf-16-le'), quote=False)}</{t}>")
        pos = s + l
    out.append(html.escape(u[pos * 2:].decode("utf-16-le"), quote=False))
    return "".join(out)


# ───────────────────────── Qoralama ─────────────────────────
def maybe_ai_photo(prompt: str, chance: float):
    if not prompt or random.random() >= chance:
        return None
    return I.fetch_ai_background(prompt, random.randint(1, 10 ** 9), api_key=os.getenv("POLLINATIONS_KEY", ""))


def render_post_image(st, kind, ptype, img_texts, image_prompt, topic, path):
    photo = maybe_ai_photo(image_prompt, float(RASM.get("ai_fon_ehtimoli", 0.35)))
    card = I.Card(lang=kind, category=C.POST_TYPES[ptype][0], title=img_texts.get("title") or topic,
                  subtitle=img_texts.get("subtitle", ""), lines=img_texts.get("lines", []), footer=IMG_FOOTER,
                  bg_photo=photo)
    img, tname = I.render_card(card, recent=st["templates"], is_quiz=ptype == "test")
    img.save(path, "JPEG", quality=92)
    push(st["templates"], tname, keep=12)


def render_greeting_image(kind, wish, image_prompt, path):
    photo = maybe_ai_photo(image_prompt, float(RASM.get("ai_fon_tabrik", 0.5)))
    img, _ = I.render_greeting("morning" if kind == "tong" else "night", wish, IMG_FOOTER, bg_photo=photo)
    img.save(path, "JPEG", quality=92)


def build_draft(st, kind, key) -> dict:
    path = os.path.join(DATA, "rasmlar", f"{key}.jpg")
    if kind in ("tong", "tun"):
        g = C.generate_greeting(ai, "morning" if kind == "tong" else "night", now().date())
        render_greeting_image(kind, g.get("wish", ""), g.get("image_prompt", ""), path)
        return {"body_html": C.to_html(g["caption"]), "body_plain": C.plain(g["caption"]), "hashtags": g["hashtags"],
                "quiz": None, "image": path, "score": g["_score"], "issues": g["_issues"], "ptype": kind,
                "topic": "", "wish": g.get("wish", ""), "image_prompt": g.get("image_prompt", "")}
    ptype = C.pick_type(st["types"].get(kind, []), POSTCFG.get("turlar"))
    post = C.generate_post(ai, kind, ptype, st["history"].get(kind, []), CFG.get("mavzular", {}).get(kind, []),
                           int(POSTCFG.get("min_belgi", 450)), int(POSTCFG.get("max_belgi", 720)),
                           int(POSTCFG.get("min_baho", 7)), POSTCFG.get("qoshimcha_uslub", ""))
    render_post_image(st, kind, ptype, post.get("image") or {}, post.get("image_prompt", ""), post.get("topic", ""), path)
    push(st["history"].setdefault(kind, []), post.get("topic", ""))
    push(st["types"].setdefault(kind, []), ptype, keep=10)
    return {"body_html": C.to_html(post["caption"]), "body_plain": C.plain(post["caption"]),
            "hashtags": post["hashtags"], "quiz": post.get("quiz"), "image": path, "score": post["_score"],
            "issues": post["_issues"], "ptype": ptype, "topic": post.get("topic", ""),
            "img_texts": post.get("image") or {}, "image_prompt": post.get("image_prompt", "")}


def full_caption(d) -> tuple[str, int]:
    tags = " ".join(d.get("hashtags") or [])
    ph, pp = [d["body_html"].strip()], [d["body_plain"].strip()]
    if tags:
        ph.append(html.escape(tags)); pp.append(tags)
    if FOOTER:
        ph.append(html.escape(FOOTER)); pp.append(FOOTER)
    return "\n\n".join(ph), C.tg_len("\n\n".join(pp))


def send_post(tg: TG, chat, d) -> list:
    cap, n = full_caption(d)
    msgs = []
    if n <= CAPTION_LIMIT:
        msgs.append(tg.send_photo(chat, d["image"], cap))
    else:
        msgs.append(tg.send_photo(chat, d["image"]))
        msgs.append(tg.send_message(chat, cap))
    q = d.get("quiz")
    if q and q.get("options"):
        msgs.append(tg.send_poll(chat, q))
    return msgs


def control_text(d, deadline) -> str:
    e, name = KIND_INFO.get(d["kind"], ("📌", d["kind"]))
    label = C.POST_TYPES[d["ptype"]][0] if d.get("ptype") in C.POST_TYPES else ""
    lines = [f"{e} <b>{name}</b>" + (f" · {label}" if label else "")]
    if d.get("test"):
        lines.append("🧪 Sinov posti — kanalga faqat 📤 tugmasi bilan chiqadi")
    else:
        lines.append(f"🕒 Chiqish vaqti: <b>{deadline:%H:%M}</b>")
    if d.get("topic"):
        lines.append(f"📝 Mavzu: {html.escape(d['topic'])}")
    if d.get("score") is not None:
        lines.append(f"🔍 Sifat bahosi: <b>{d['score']}/10</b>")
    if d.get("issues"):
        lines.append("✏️ Tekshiruvda tuzatildi: " + html.escape("; ".join(map(str, d["issues"][:4])))[:500])
    st = d["status"]
    txt = {
        "pending": ("⏳ Javob bermasangiz, belgilangan vaqtda avtomatik chiqadi."
                    if APPROVE.get("javob_bolmasa", "yuborish") == "yuborish" else "⏳ Tasdiqlamasangiz, chiqmaydi."),
        "approved": "✅ Tasdiqlandi — belgilangan vaqtda chiqadi.",
        "cancelled": "❌ Bekor qilindi — kanalga chiqmaydi.",
        "published": "📢 Kanalga chiqdi" + (f": {d['link']}" if d.get("link") else "."),
        "failed": "❗ Yuborilmadi: " + html.escape(d.get("error", ""))[:300],
        "working": "⚙️ Ishlanmoqda...",
    }.get(st, "")
    if d.get("test") and st == "pending":
        txt = "Kanalga yuborish uchun 📤 tugmasini bosing (10 daqiqa ichida)."
    lines.append("\n" + txt)
    return "\n".join(lines)


def control_kb(d, key):
    st = d["status"]
    if st in ("published", "failed", "working"):
        return None
    if st == "cancelled":
        return {"inline_keyboard": [[{"text": "↩️ Qaytarish", "callback_data": f"restore|{key}"}]]}
    rows = []
    if st == "pending" and not d.get("test"):
        rows.append([{"text": "✅ Tasdiqlash", "callback_data": f"ok|{key}"},
                     {"text": "📤 Hozir chiqarish", "callback_data": f"now|{key}"}])
    else:
        rows.append([{"text": "📤 Hozir chiqarish", "callback_data": f"now|{key}"}])
    rows.append([{"text": "✏️ Matnni tahrirlash", "callback_data": f"edit|{key}"},
                 {"text": "🖼 Rasmni almashtirish", "callback_data": f"img|{key}"}])
    rows.append([{"text": "🔄 Boshqa post yozish", "callback_data": f"regen|{key}"},
                 {"text": "❌ Bekor qilish", "callback_data": f"cancel|{key}"}])
    return {"inline_keyboard": rows}


# ───────────────────────── Asosiy jarayon ─────────────────────────
def find_slot(done: dict, force_kind=None):
    """Hozirgi vaqtga eng yaqin, hali bajarilmagan jadval vaqtini topadi."""
    n = now()
    best = None
    for slot in CFG.get("jadval", []):
        hhmm, kind = str(slot["vaqt"]), str(slot["tur"])
        if force_kind and kind != force_kind:
            continue
        for day in (n.date(), n.date() + dt.timedelta(days=1)):
            t = slot_dt(day, hhmm)
            if f"{t.date().isoformat()}_{hhmm.replace(':', '')}_{kind}" in done:
                continue
            if t - dt.timedelta(minutes=40) <= n <= t + LATE_LIMIT:
                if best is None or abs((t - n).total_seconds()) < abs((best[0] - n).total_seconds()):
                    best = (t, hhmm, kind)
    return best


def handle_commands(tg, st, msg):
    text = (msg.get("text") or "").strip().split("@")[0]
    if text == "/pauza":
        st["paused"] = True
        tg.send_message(ADMIN, "⏸ Avtomatik postlar to'xtatildi. Yoqish: /davom")
    elif text == "/davom":
        st["paused"] = False
        tg.send_message(ADMIN, "▶️ Avtomatik postlar yoqildi.")
    elif text in ("/holat", "/start", "/yordam"):
        lines = ["📋 <b>Jadval</b>" + ("  ⏸ PAUZA" if st.get("paused") else "")]
        today = now().date().isoformat()
        for slot in CFG.get("jadval", []):
            k = f"{today}_{str(slot['vaqt']).replace(':', '')}_{slot['tur']}"
            e, name = KIND_INFO.get(str(slot["tur"]), ("📌", slot["tur"]))
            mark = {"published": "📢", "cancelled": "❌", "failed": "❗"}.get(st["done"].get(k, ""), "•")
            lines.append(f"{mark} {slot['vaqt']}  {e} {name}")
        lines.append("\nBuyruqlar: /pauza /davom /holat\nSinov posti: GitHub → Actions → «Run workflow».\n"
                     "<i>Bot faqat post vaqtlari atrofida javob beradi.</i>")
        tg.send_message(ADMIN, "\n".join(lines))
    else:
        return False
    return True


def run(force_kind=None, test=False, manual=False):
    if not TOKEN or not ADMIN or not CHANNEL:
        log.error("BOT_TOKEN, ADMIN_ID yoki KANAL yo'q (GitHub Secrets ni tekshiring)")
        sys.exit(1)
    tg = TG(TOKEN)
    st = load_state()
    try:
        tg.call("deleteWebhook")
    except Exception:
        pass

    if test or manual:
        t = now() + dt.timedelta(minutes=LEAD_MIN)
        hhmm, kind = t.strftime("%H:%M"), force_kind or "en"
        key = f"{'test' if test else 'qolda'}-{int(time.time())}-{kind}"
    else:
        slot = find_slot(st["done"], force_kind)
        if not slot:
            log.info("Hozir navbatdagi post yo'q.")
            poll_commands(tg, st)
            save_state(st)
            return
        t, hhmm, kind = slot
        key = f"{t.date().isoformat()}_{hhmm.replace(':', '')}_{kind}"
        if key in st["done"]:
            log.info("%s allaqachon bajarilgan (%s)", key, st["done"][key])
            return
        prep_at = t - dt.timedelta(minutes=LEAD_MIN + PREP_MIN)
        # tayyorlash vaqtigacha kutamiz (shu orada admin buyruqlarini ham o'qiymiz)
        while now() < prep_at:
            poll_commands(tg, st, timeout=min(25, max(1, int((prep_at - now()).total_seconds()))))
        if st.get("paused"):
            log.info("Pauza yoqilgan — %s o'tkazib yuborildi", key)
            st["done"][key] = "paused"
            save_state(st)
            return
        if now() > t + LATE_LIMIT:
            st["done"][key] = "late"
            save_state(st)
            return

    d = {"kind": kind, "status": "working", "test": test}
    try:
        d.update(make_draft(st, kind, key))
    except Exception as e:
        log.exception("Post tayyorlanmadi")
        tg.send_message(ADMIN, f"❗ {KIND_INFO.get(kind, ('', kind))[1]} ({hhmm}) posti tayyorlanmadi.\n"
                               f"Sabab: {html.escape(str(e))[:600]}")
        if not test and not manual:
            st["done"][key] = "failed"
        save_state(st)
        return
    d["status"] = "pending"
    deadline = max(t, now() + MIN_REVIEW)
    control_id = send_preview(tg, d, key, deadline)
    save_state(st)

    # ── admin javobini kutish ──
    awaiting_edit = False
    end = now() + dt.timedelta(minutes=LEAD_MIN) if test else deadline
    while now() < end and d["status"] in ("pending", "approved", "cancelled"):
        left = int((end - now()).total_seconds())
        try:
            ups = tg.updates(st.get("offset", 0), timeout=max(1, min(20, left)))
        except Exception as e:
            log.warning("getUpdates xato: %s", e)
            time.sleep(5)
            continue
        for u in ups:
            st["offset"] = u["update_id"] + 1
            cb = u.get("callback_query")
            msg = u.get("message")
            if cb:
                if cb["from"]["id"] != ADMIN:
                    tg.answer(cb["id"], "Ruxsat yo'q")
                    continue
                action, _, ckey = cb.get("data", "").partition("|")
                if ckey != key:
                    tg.answer(cb["id"], "Bu post eskirgan.")
                    continue
                if action == "ok":
                    d["status"] = "approved"
                    tg.answer(cb["id"], "✅ Tasdiqlandi")
                    if APPROVE.get("tasdiqlansa", "vaqtida") == "darhol":
                        end = now()
                elif action == "now":
                    d["status"] = "approved"
                    tg.answer(cb["id"], "📤 Yuborilmoqda...")
                    end = now()
                elif action == "cancel":
                    d["status"] = "cancelled"
                    tg.answer(cb["id"], "❌ Bekor qilindi")
                elif action == "restore":
                    d["status"] = "pending"
                    tg.answer(cb["id"], "↩️ Qaytarildi")
                elif action == "edit":
                    awaiting_edit = True
                    tg.answer(cb["id"])
                    tg.send_message(ADMIN, "✏️ Yangi matnni yuboring (heshteg va kontaktlar avtomatik qo'shiladi).\n"
                                           "🖼 Yoki o'z rasmingizni yuboring — rasm almashtiriladi.")
                elif action in ("img", "regen"):
                    tg.answer(cb["id"], "⚙️ Bajarilmoqda, biroz kuting...")
                    prev = d["status"]
                    d["status"] = "working"
                    tg.edit(ADMIN, control_id, control_text(d, deadline))
                    try:
                        if action == "img":
                            new_image(st, d)
                        else:
                            d.update(make_draft(st, kind, key))
                    except Exception as e:
                        tg.send_message(ADMIN, "❗ Bajarib bo'lmadi: " + html.escape(str(e))[:400])
                    d["status"] = "pending" if action == "regen" else prev
                    deadline = max(deadline, now() + MIN_REVIEW)
                    if not test:
                        end = deadline
                    control_id = send_preview(tg, d, key, deadline)
                    continue
                tg.edit(ADMIN, control_id, control_text(d, deadline), control_kb(d, key))
            elif msg and msg.get("from", {}).get("id") == ADMIN and msg.get("chat", {}).get("type") == "private":
                if handle_commands(tg, st, msg):
                    continue
                if awaiting_edit and (msg.get("text") or msg.get("photo")):
                    if msg.get("photo"):
                        tg.download(msg["photo"][-1]["file_id"], d["image"])
                        try:
                            from PIL import Image
                            Image.open(d["image"]).convert("RGB").save(d["image"], "JPEG", quality=92)
                        except Exception:
                            pass
                        if msg.get("caption"):
                            d["body_html"] = C.strip_footer(entities_to_html(msg["caption"], msg.get("caption_entities")), FOOTER)
                            d["body_plain"] = C.strip_footer(msg["caption"], FOOTER)
                    else:
                        d["body_html"] = C.strip_footer(entities_to_html(msg["text"], msg.get("entities")), FOOTER)
                        d["body_plain"] = C.strip_footer(msg["text"], FOOTER)
                    d["issues"] = ["admin tomonidan tahrirlandi"]
                    awaiting_edit = False
                    deadline = max(deadline, now() + MIN_REVIEW)
                    if not test:
                        end = deadline
                    tg.send_message(ADMIN, "✅ Yangilandi. Yangi ko'rinish:")
                    control_id = send_preview(tg, d, key, deadline)
        save_state(st)

    # ── kanalga chiqarish ──
    publish = d["status"] == "approved" or (
        d["status"] == "pending" and not test and APPROVE.get("javob_bolmasa", "yuborish") == "yuborish")
    if publish:
        try:
            msgs = send_post(tg, CHANNEL, d)
            d["status"] = "published"
            if CHANNEL.startswith("@") and msgs:
                d["link"] = f"https://t.me/{CHANNEL[1:]}/{msgs[0]['message_id']}"
            log.info("Kanalga chiqdi: %s", key)
        except Exception as e:
            d["status"], d["error"] = "failed", str(e)
            tg.send_message(ADMIN, "❗ Kanalga yuborib bo'lmadi: " + html.escape(str(e))[:400] +
                            "\nBot kanalda admin ekanini tekshiring.")
    elif d["status"] == "pending":
        d["status"] = "cancelled"
    tg.edit(ADMIN, control_id, control_text(d, deadline), None)
    if not test and not manual:
        st["done"][key] = d["status"]
    save_state(st)


def make_draft(st, kind, key):
    last = None
    for attempt in range(3):
        try:
            return build_draft(st, kind, key)
        except Exception as e:
            last = e
            log.warning("Urinish %d muvaffaqiyatsiz: %s", attempt + 1, e)
            time.sleep(20)
    raise last


def new_image(st, d):
    if d["kind"] in ("tong", "tun"):
        render_greeting_image(d["kind"], d.get("wish", ""), "", d["image"])
    else:
        render_post_image(st, d["kind"], d["ptype"], d.get("img_texts") or {}, "", d.get("topic", ""), d["image"])


def send_preview(tg, d, key, deadline):
    tg.send_message(ADMIN, "👇 <b>Kanalga chiqadigan post ko'rinishi:</b>")
    send_post(tg, ADMIN, d)
    return tg.send_message(ADMIN, control_text(d, deadline), control_kb(d, key))["message_id"]


def poll_commands(tg, st, timeout=1):
    try:
        for u in tg.updates(st.get("offset", 0), timeout=timeout):
            st["offset"] = u["update_id"] + 1
            msg, cb = u.get("message"), u.get("callback_query")
            if cb:
                tg.answer(cb["id"], "Bu post eskirgan.")
            elif msg and msg.get("from", {}).get("id") == ADMIN:
                handle_commands(tg, st, msg)
    except Exception as e:
        log.warning("Buyruqlarni o'qib bo'lmadi: %s", e)
        time.sleep(min(timeout, 10))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--tur", default="", help="en / ar / ru / tong / tun")
    p.add_argument("--test", action="store_true", help="sinov posti (kanalga faqat 📤 bilan chiqadi)")
    p.add_argument("--hozir", action="store_true", help="hozir post tayyorlash, 10 daqiqadan keyin avtomatik chiqadi")
    a = p.parse_args()
    log.info("Ishga tushdi: tur=%s test=%s hozir=%s | token=%s gemini=%s admin=%s kanal=%s",
             a.tur, a.test, a.hozir, "bor" if TOKEN else "YO'Q", "bor" if ai.gemini_key else "YO'Q", ADMIN, CHANNEL)
    try:
        run(a.tur.strip() or None, a.test, a.hozir)
    except SystemExit:
        raise
    except Exception:
        log.exception("Kutilmagan xato")
        sys.exit(1)
