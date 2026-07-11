import os
import re
import json
import urllib.request
from flask import Flask, request, jsonify, send_from_directory


def _load_dotenv():
    """Zero-dependency .env loader: copy .env.example to .env, paste your key,
    and the app picks it up — no `export` needed. Real env vars still win."""
    path = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()

app = Flask(__name__, static_folder='static', static_url_path='')

# Gemini configuration
KEY = os.environ.get("GEMINI_API_KEY")
MODEL = "gemini-2.5-flash"

SYS_PROMPT = """You are a careful research-literacy assistant. Given a health/nutrition study or article, produce a structured trust breakdown. You do NOT decide what is true. Surface (1) the study's actual measured finding as primary_claim — NOT the sensational headline, (2) what the study's design cannot support, (3) known contradicting evidence — so a non-expert can judge for themselves.
Gap heuristics: observational != causal; animal/mouse != human; small or single-cohort n; mechanistic/surrogate endpoint != clinical outcome; no replication; industry funding.
Industry funding is a weighting factor, not auto-rejection — judge primarily on study design, and flag funding in epistemic_gaps only when it plausibly biases the specific claim.
When a strong scientific consensus contradicts the claim you MAY name it (e.g., "ISSN position stand on creatine"). Otherwise return an empty contradictions array — never invent a citation.
headline_claim: if the input contains a sensational headline or framing that overstates the finding (a causal/personal promise where the study only measured an association), copy that phrase VERBATIM from the input. If there is no such headline — e.g. a sober abstract — return an empty string. Never write a headline yourself; only quote one that is literally present. Output only the schema."""

SCHEMA = {
    "type": "object",
    "properties": {
        "primary_claim": {"type": "string"},
        "study_type": {"type": "string", "enum": ["RCT","observational","case_study","meta_analysis","animal_model","mechanistic"]},
        "sample_size": {"type": "string"},
        "confidence": {"type": "string", "enum": ["low","medium","high"]},
        "epistemic_gaps": {"type": "array", "items": {"type": "string"}},
        "contradictions": {"type": "array", "items": {
            "type": "object",
            "properties": {"point": {"type": "string"}, "source": {"type": "string"}},
            "required": ["point","source"]
        }},
        "headline_claim": {"type": "string"},
    },
    "required": ["primary_claim","study_type","sample_size","confidence","epistemic_gaps","contradictions","headline_claim"],
}


def _norm(s):
    """Lowercase, drop punctuation, collapse whitespace — for substring matching."""
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", (s or "").lower())).strip()


def _guard_headline(result, source_text):
    """Deterministic anti-fabrication guard: the model may only surface a headline
    that is LITERALLY in the input. If the returned headline isn't a substring of
    the source (i.e. the model paraphrased or invented one), blank it out."""
    hc = result.get("headline_claim") or ""
    if hc and _norm(hc) not in _norm(source_text):
        result["headline_claim"] = ""
    return result

@app.route('/')
def index():
    return app.send_static_file('index.html')

@app.route('/fixtures/<path:filename>')
def serve_fixtures(filename):
    return send_from_directory('fixtures', filename)

@app.route('/analyze', methods=['POST'])
def analyze():
    if not KEY:
        return jsonify({"error": "GEMINI_API_KEY not set in environment"}), 500
        
    data = request.get_json()
    if not data or 'text' not in data:
        return jsonify({"error": "Missing 'text' in request body"}), 400
        
    text = data['text']
    
    body = {
        "systemInstruction": {"parts": [{"text": SYS_PROMPT}]},
        "contents": [{"parts": [{"text": "Study:\n" + text}]}],
        "generationConfig": {
            "temperature": 0.2, 
            "responseMimeType": "application/json", 
            "responseSchema": SCHEMA
        },
    }
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={KEY}"
    try:
        req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            resp_data = json.load(r)
            
        result_text = resp_data["candidates"][0]["content"]["parts"][0]["text"]
        result = json.loads(result_text)
        result = _guard_headline(result, text)
        return jsonify(result)
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    # 5000 collides with macOS Control Center (AirPlay Receiver) → default 5001. Override with PORT env.
    port = int(os.environ.get("PORT", "5001"))
    app.run(port=port, debug=True)
