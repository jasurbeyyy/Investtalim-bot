"""Gemini modellarini tekshiradi: qaysilari ishlaydi va qanchalik tez."""
import json, os, time
import httpx
key = os.getenv("GEMINI_API_KEY", "").strip()
out = []
r = httpx.get("https://generativelanguage.googleapis.com/v1beta/models", headers={"x-goog-api-key": key},
              params={"pageSize": 200}, timeout=60)
out.append(f"models list: {r.status_code}")
names = []
if r.status_code == 200:
    for m in r.json().get("models", []):
        if "generateContent" in m.get("supportedGenerationMethods", []):
            names.append(m["name"].split("/")[-1])
out.append("generateContent: " + ", ".join(names))
cands = [n for n in names if "flash" in n and not any(x in n for x in ("image", "tts", "live", "audio", "embedding"))]
for n in cands[:12]:
    for tc in ({"thinkingConfig": {"thinkingLevel": "low"}}, {"thinkingConfig": {"thinkingBudget": 0}}, {}):
        body = {"contents": [{"role": "user", "parts": [{"text": 'Return JSON {"ok": true, "uz": "salom"}'}]}],
                "generationConfig": {"responseMimeType": "application/json", "maxOutputTokens": 200, **tc}}
        t = time.time()
        try:
            rr = httpx.post(f"https://generativelanguage.googleapis.com/v1beta/models/{n}:generateContent",
                            headers={"x-goog-api-key": key}, json=body, timeout=90)
            txt = rr.text[:160].replace("\n", " ")
            out.append(f"{n} {list(tc.values())[0] if tc else 'default'}: {rr.status_code} {time.time()-t:.1f}s {txt if rr.status_code!=200 else ''}")
            if rr.status_code == 200:
                break
        except Exception as e:
            out.append(f"{n} {tc}: XATO {e} {time.time()-t:.1f}s")
open("jurnal.txt", "w").write("\n".join(out))
print("\n".join(out))
