# NutriCut — Build Spec

Paste a health/nutrition study → the app returns three cards: **claims / hasn't proven / contradicts**. A trust layer, not a fact-checker: it surfaces trust signals so the reader judges for themselves.

## v1 scope
1. **`POST /analyze`** — input `{ "text": "<study text or abstract>" }`, output the ClaimSchema JSON (below) via Gemini structured output.
2. **Three-card UI** — one screen: paste box + 5 "try an example" buttons + 3 result cards (claims / hasn't proven / contradicts) with a study-type badge.
3. **5 built-in examples** — loaded from `fixtures/*.json` instantly, with no network call (reliability).

**Demo set (wire the 5 buttons to exactly these fixtures, in this order):**
1. `ethan_industry_nejm.json` — industry-funded RCT (funding flagged in gaps)
2. `ethan_systematic_review_aha.json` — strong systematic review (high confidence; proves it discriminates strong vs weak)
3. `ethan_specific_obesity.json` — small RCT (medium confidence; calibration)
4. `creatine_kidney.json` — the 🔴 contradicts card fires (ISSN consensus)
5. `red_meat.json` — 🔴 fires + relative-vs-absolute risk reveal
Rationale: 2 examples MUST have non-empty `contradictions` so the red card is shown live — several real abstracts return empty contradictions (correct anti-hallucination behavior), so a demo built only on those would never show card 3.

**Not in v1:** URL scraping, accounts/login, database, multi-paper comparison, numeric "validity %" scoring (confidence is a qualitative badge only), and external-controversy detection (NutriCut reads one paper's design — it does not know about field-level debates not stated in the text). Keep it to the three features above.

## API contract
`POST /analyze` → `200`
```json
{
  "primary_claim": "string — the study's actual measured finding, not the headline",
  "study_type": "RCT | observational | case_study | meta_analysis | animal_model | mechanistic",
  "sample_size": "string",
  "confidence": "low | medium | high",
  "epistemic_gaps": ["string"],
  "contradictions": [{ "point": "string", "source": "string" }]
}
```
- Errors → `{ "error": "message" }` (4xx/5xx). Empty `contradictions: []` is valid and expected — never fabricate.
- This exact schema is already validated: `fixtures/` holds 5 real Gemini outputs. The UI must render those verbatim.

## Gemini call (tested — use as-is; reference impl in `tools/test_prompt.py`)
- Model `gemini-2.5-flash` · `temperature: 0.2` · `responseMimeType: "application/json"` · `responseSchema` = the contract above (enum-locked).
- **System prompt (final):**
  > You are a careful research-literacy assistant. Given a health/nutrition study or article, produce a structured trust breakdown. You do NOT decide what is true. Surface (1) the study's actual measured finding as primary_claim — NOT the sensational headline, (2) what the study's design cannot support, (3) known contradicting evidence — so a non-expert can judge for themselves.
  > Gap heuristics: observational ≠ causal; animal/mouse ≠ human; small or single-cohort n; mechanistic/surrogate endpoint ≠ clinical outcome; no replication; industry funding.
  > Industry funding is a weighting factor, not auto-rejection — judge primarily on study design, and flag funding in epistemic_gaps only when it plausibly biases the specific claim.
  > When a strong scientific consensus contradicts the claim you MAY name it (e.g., "ISSN position stand on creatine"). Otherwise return an empty contradictions array — never invent a citation. Output only the schema.
- `GEMINI_API_KEY` from env — never hardcode, never log it.
- Each `/analyze` is a **fresh stateless call** — no chat history, no accumulated context (one study in → one result out). This prevents context-reinforcement bias.

## Stack & structure
- **Backend**: Python + Flask, single `app.py` (`/analyze` + serve static). `pip install flask google-genai`.
- **Frontend**: React (Vite) or plain HTML+JS in `/static` — either is fine for v1.
- **Colors** (must read in <5s, no legend): claims `#3D7A46` · hasn't-proven `#A9720F` · contradicts `#A8412A`, on off-white. Card = title + study-type badge + bullet list. Large, clean, legible.
```
nutricut/
  app.py                 # Flask: /analyze + serve static
  static/                # UI
  fixtures/*.json        # 5 validated examples — wire the buttons to these
  tools/test_prompt.py   # working Gemini call reference
  requirements.txt
  .env.example           # GEMINI_API_KEY=
```

## Definition of done
- [ ] `POST /analyze {text}` returns valid ClaimSchema for all 5 fixture inputs (matching `fixtures/`)
- [ ] UI: paste box + 5 buttons + 3 cards render; buttons load fixtures with no API call
- [ ] `confidence` shown as a badge; no percentage score
- [ ] empty `contradictions` renders gracefully ("no strong counter-evidence found")
- [ ] README run steps: `pip install -r requirements.txt`, set `GEMINI_API_KEY`, `python app.py`
