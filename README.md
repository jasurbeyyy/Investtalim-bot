# Foreign Investta’lim — kanal uchun avtomatik post boti

Server kerak emas: bot GitHub Actions’da ishlaydi, kompyuter o‘chiq bo‘lsa ham postlar chiqaveradi.

## Qanday ishlaydi
- GitHub har soat :31 da botni ishga tushiradi. Bot `config.yaml` dagi jadvaldan navbatdagi vaqtni topadi.
- Vaqtdan 13 daqiqa oldin AI post yozadi, ikkinchi AI tekshiradi, rasm chiziladi.
- 10 daqiqa oldin post sizga Telegram’da keladi: ✅ / 📤 / ✏️ / 🖼 / 🔄 / ❌ tugmalari bilan.
- Belgilangan vaqtda post kanalga chiqadi (javob bermasangiz ham).

## Kerakli sozlamalar (bir marta)
**Settings → Secrets and variables → Actions → New repository secret**:
- `BOT_TOKEN` — @BotFather bergan token
- `GEMINI_API_KEY` — https://aistudio.google.com/apikey dan bepul kalit

## Sinov posti
**Actions → Kanal postlari → Run workflow** → `tur` (en/ar/ru/tong/tun) va `rejim: sinov` → Run.
Post 1–2 daqiqada sizga keladi; kanalga faqat 📤 bossangiz chiqadi.

## O‘zgartirish
`config.yaml` faylini GitHub’ning o‘zida tahrirlang (✏️ belgisi): jadval, mavzular, post turlari, kontaktlar.

## Telegram buyruqlari
`/holat`, `/pauza`, `/davom` — bot ularni navbatdagi ishga tushishda (1 soat ichida) bajaradi.
