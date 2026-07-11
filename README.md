# NutriCut

Paste a sports-science study and an AI separates **what it claims**, **what it hasn't proven**, and **where the evidence actually stands**. A trust layer, not a fact-checker — it shows you *how much weight* a study really carries, so you decide what to believe. (The *cut* is the bodybuilding term; the job is the same — strip a claim down to what's really there.)

## The problem
Every season, sports and fitness culture serves up another confident headline: ice baths build muscle, you must slam a shake within 30 minutes, creatine wrecks your kidneys, five minutes of running adds three years to your life. Half of it is oversold supplement marketing or a viral headline stripped of every caveat, and most people — athletes included — can't tell a strong study from a weak one. The result is confusion, wasted money, and eventually giving up on evidence altogether.

## What it does
Paste a study abstract or article (or tap a built-in example) and get:
- **A verdict banner** — the evidence *strength* (Strong / Moderate / Early-stage), computed deterministically from the study design, not an AI opinion on truth.
- **What it claims** — the actual measured finding, with study type, sample size, and a link to look it up.
- **An evidence ladder** — where the study design sits (meta-analysis → RCT → cohort → case report → animal → in-vitro). A guide to design, not a score.
- **What it hasn't proven** — the limits of the design (observational ≠ causal; a mouse model ≠ humans; n=24 ≠ everyone).
- **What contradicts it** — known opposing findings, each with a one-click search link. Empty is a valid answer: it never invents a citation.
- **Headline vs. reality** — when the input carries a sensational headline, it shows the headline beside what the study actually measured.

## Why it's not a fact-checker
It doesn't decide what's true (that's error-prone and overconfident). It reasons about a study's *structure* and surfaces trust signals — so it's useful with almost no database and never pretends to know the answer. When it can't find counter-evidence, it says so instead of fabricating one.

## Run it locally

```bash
# 1. install (Python 3.9+)
pip install -r requirements.txt

# 2. add your Gemini API key — get one free at https://aistudio.google.com/apikey
cp .env.example .env
#   then open .env and paste your key:  GEMINI_API_KEY=your_key_here

# 3. run
python app.py
#   → open http://localhost:5001
```

The built-in examples load instantly with no API call, so the demo works even offline. Live analysis of your own pasted text needs the key. `.env` is git-ignored — your key never gets committed. You can also pass the key inline (`GEMINI_API_KEY=... python app.py`) or set `PORT` to change the port.

## Stack
Python (Flask, single `app.py`) · plain HTML/CSS/JS (`static/`) · Gemini API with structured output (enum-locked schema). No database, no accounts.
