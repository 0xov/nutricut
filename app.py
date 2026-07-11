import os
import re
import html
import json
import time
import socket
import ipaddress
import urllib.request
import urllib.error
import urllib.parse
from collections import deque
from flask import Flask, request, jsonify, send_from_directory

# Cap the text we ever send to Gemini (cost + latency control).
MAX_CHARS = 14000
FETCH_TIMEOUT = 10          # seconds per hop
FETCH_MAX_BYTES = 2_000_000  # 2 MB response cap
FETCH_UA = "NutriCut/1.0 (+https://github.com/0xov/nutricut) research-literacy reader"

# Per-IP rate limit on the costed /analyze path — protects a public endpoint's
# paid Gemini key from billing-drain abuse. In-memory (per instance) + a
# --max-instances cap at deploy bound the blast radius; good enough for a demo.
RL_MAX = 10
RL_WINDOW = 60  # seconds
_HITS = {}


def _rate_limited(ip):
    now = time.time()
    dq = _HITS.setdefault(ip, deque())
    while dq and now - dq[0] > RL_WINDOW:
        dq.popleft()
    if len(dq) >= RL_MAX:
        return True
    dq.append(now)
    if len(_HITS) > 5000:  # bound memory: drop stale buckets
        for k in [k for k, v in list(_HITS.items()) if not v or now - v[-1] > RL_WINDOW]:
            _HITS.pop(k, None)
    return False


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

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Disable automatic redirect following so we can re-validate every hop
    ourselves — otherwise a public URL could 302 to an internal address (SSRF)."""
    def redirect_request(self, *args, **kwargs):
        return None


def _host_is_safe(host):
    """Resolve the hostname and reject if ANY resolved IP is non-global
    (private, loopback, link-local incl. the 169.254.169.254 cloud-metadata
    endpoint, reserved, or multicast)."""
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        return False
    if not infos:
        return False
    for info in infos:
        ip = info[4][0]
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return False
        if not addr.is_global or addr.is_reserved or addr.is_multicast:
            return False
    return True


def _extract_text(raw_html):
    """stdlib-only HTML -> readable text. Drops scripts/nav/chrome, prefers the
    <article>/<main> body, converts blocks to newlines, unescapes entities."""
    s = re.sub(r"(?is)<(script|style|noscript|nav|header|footer|aside|form|svg)[^>]*>.*?</\1>", " ", raw_html)
    m = re.search(r"(?is)<article[^>]*>(.*?)</article>", s) or re.search(r"(?is)<main[^>]*>(.*?)</main>", s)
    body = m.group(1) if m else s
    body = re.sub(r"(?is)<(p|br|div|li|h[1-6]|tr)[^>]*>", "\n", body)
    text = re.sub(r"(?s)<[^>]+>", " ", body)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]*(\n[ \t]*)+", "\n\n", text).strip()
    return text[:MAX_CHARS]


def _safe_fetch(url, max_redirects=4):
    """SSRF-hardened fetch: http(s) only, every hop's resolved IP validated,
    redirects followed manually, timeout + size capped. Returns article text."""
    opener = urllib.request.build_opener(_NoRedirect)
    for _ in range(max_redirects + 1):
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError("only http(s) links are supported")
        if not parsed.hostname or not _host_is_safe(parsed.hostname):
            raise ValueError("that link points somewhere we can't fetch")
        req = urllib.request.Request(url, headers={"User-Agent": FETCH_UA, "Accept": "text/html,*/*", "Accept-Encoding": "identity"})
        try:
            resp = opener.open(req, timeout=FETCH_TIMEOUT)
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308) and e.headers.get("Location"):
                url = urllib.parse.urljoin(url, e.headers["Location"])
                continue
            raise ValueError("the site returned an error (%s)" % e.code)
        ctype = (resp.headers.get("Content-Type") or "").lower()
        if "html" not in ctype and "text" not in ctype and ctype:
            raise ValueError("that link isn't an article page")
        raw = resp.read(FETCH_MAX_BYTES)
        charset = resp.headers.get_content_charset() or "utf-8"
        return _extract_text(raw.decode(charset, errors="replace"))
    raise ValueError("too many redirects")


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

    ip = (request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
          or request.remote_addr or "unknown")
    if _rate_limited(ip):
        return jsonify({"error": "You're going a bit fast — give it a few seconds and try again."}), 429

    data = request.get_json(silent=True) or {}
    url_in = (data.get('url') or '').strip()
    text = (data.get('text') or '').strip()
    source_url = ''

    # URL path: fetch the article server-side, extract its text, then analyze that.
    if url_in:
        try:
            text = _safe_fetch(url_in)
        except Exception as e:
            return jsonify({"error": "Couldn't read that link — %s." % e}), 400
        if len(text) < 40:
            return jsonify({"error": "That link didn't have readable article text. Try pasting the text instead."}), 400
        source_url = url_in
    elif not text:
        return jsonify({"error": "Paste a study, an article, or a link to one."}), 400

    text = text[:MAX_CHARS]

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
        result["source_url"] = source_url
        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    # 5000 collides with macOS Control Center (AirPlay Receiver) → default 5001. Override with PORT env.
    port = int(os.environ.get("PORT", "5001"))
    app.run(port=port, debug=True)
