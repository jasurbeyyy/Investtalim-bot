// Foreign Investta'lim — post botini har 10 daqiqada uyg'otadi (Google Apps Script)
// 1) GITHUB_TOKEN ga GitHub tokeningizni qo'ying.  2) "boshlash" funksiyasini bir marta ishga tushiring.

const GITHUB_TOKEN = 'BU_YERGA_TOKENNI_QOYING';
const URL = 'https://api.github.com/repos/jasurbeyyy/Investtalim-bot/actions/workflows/postlar.yml/dispatches';

function uygotish() {
  const soat = Number(Utilities.formatDate(new Date(), 'Asia/Tashkent', 'H'));
  if (soat < 6 || soat > 21) return; // tunda post yo'q
  const javob = UrlFetchApp.fetch(URL, {
    method: 'post',
    contentType: 'application/json',
    headers: { Authorization: 'Bearer ' + GITHUB_TOKEN, Accept: 'application/vnd.github+json' },
    payload: JSON.stringify({ ref: 'main', inputs: { tur: 'en', rejim: 'jadval' } }),
    muteHttpExceptions: true,
  });
  console.log('GitHub javobi: ' + javob.getResponseCode() + ' ' + javob.getContentText());
}

function boshlash() {
  ScriptApp.getProjectTriggers().forEach(function (t) { ScriptApp.deleteTrigger(t); });
  ScriptApp.newTrigger('uygotish').timeBased().everyMinutes(10).create();
  uygotish();
  console.log('Tayyor: bot har 10 daqiqada uyg\'otiladi. 204 javobi = hammasi joyida.');
}
