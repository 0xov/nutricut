#!/usr/bin/env python3
"""NutriCut Gemini system prompt — 실제 5개 스터디 테스트 (structured output, temp 0.2)."""
import os, json, urllib.request, warnings
warnings.simplefilter("ignore")

# load key
KEY = None
for p in [os.path.expanduser("~/ai-hub/.env")]:
    for line in open(p):
        if line.startswith("GEMINI_API_KEY"):
            KEY = line.split("=", 1)[1].strip().strip('"').strip("'"); break
assert KEY, "no GEMINI_API_KEY"

MODEL = "gemini-2.5-flash"
SYS = """You are a careful research-literacy assistant. Given a health/nutrition study or article, produce a structured trust breakdown. You do NOT decide what is true. Surface (1) the main claim, (2) what the study's design cannot support, (3) known contradicting evidence, so a non-expert can judge for themselves.
Gap heuristics: observational != causal; animal/mouse != human; small or single-cohort n; mechanistic/surrogate endpoint != clinical outcome; no replication; industry funding.
If you cannot find reliable, real contradictions, return an empty array. Never invent a citation. Output only the schema."""

SCHEMA = {
    "type": "object",
    "properties": {
        "primary_claim": {"type": "string"},
        "study_type": {"type": "string", "enum": ["RCT","observational","case_study","meta_analysis","animal_model","mechanistic"]},
        "sample_size": {"type": "string"},
        "confidence": {"type": "string", "enum": ["low","medium","high"]},
        "epistemic_gaps": {"type": "array", "items": {"type": "string"}},
        "contradictions": {"type": "array", "items": {"type": "object", "properties": {"point": {"type": "string"}, "source": {"type": "string"}}, "required": ["point","source"]}},
    },
    "required": ["primary_claim","study_type","sample_size","confidence","epistemic_gaps","contradictions"],
}

STUDIES = [
    ("Coffee & dementia", "A prospective cohort study following 5,000 adults over 10 years found that people who drank 3+ cups of coffee daily had a 27% lower incidence of dementia diagnosis compared to non-coffee-drinkers. Headline: 'Coffee cuts your dementia risk by a quarter.'"),
    ("Creatine & kidney", "A single case report describes a 20-year-old male bodybuilder who developed elevated serum creatinine after starting creatine supplementation. Headline: 'Creatine is destroying your kidneys.'"),
    ("Seed oils & inflammation", "An in-vitro mechanistic paper shows that linoleic acid from seed oils is metabolized into oxylipins that can promote inflammatory signaling in cell cultures. Headline: 'Seed oils are inflaming your body.'"),
    ("Intermittent fasting & lifespan", "A study on 400 mice found that time-restricted feeding extended median lifespan by 18% versus ad-libitum feeding. Headline: 'Intermittent fasting makes you live longer.'"),
    ("Red meat & cancer", "A meta-analysis of observational cohort studies reports a relative risk of 1.17 for colorectal cancer per 100g/day of red meat consumption. Headline: 'Red meat gives you cancer.'"),
]

def call(text):
    body = {
        "systemInstruction": {"parts": [{"text": SYS}]},
        "contents": [{"parts": [{"text": "Study:\n" + text}]}],
        "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json", "responseSchema": SCHEMA},
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={KEY}"
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        d = json.load(r)
    return json.loads(d["candidates"][0]["content"]["parts"][0]["text"])

for name, text in STUDIES:
    print("\n" + "=" * 70 + f"\n### {name}")
    try:
        out = call(text)
        print(json.dumps(out, ensure_ascii=False, indent=2))
    except Exception as e:
        print("  ERROR:", str(e)[:200])
