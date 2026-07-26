# Panoptes

### See if your product or business has *actual* demand.

*Argus Panoptes — the hundred-eyed watcher of Greek myth. Half his eyes slept; the rest never closed.*

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-0b1210?style=for-the-badge&logo=python&logoColor=3dcf9a)](https://www.python.org/downloads/)
[![Free · Self-hosted](https://img.shields.io/badge/free-self--hosted-3dcf9a?style=for-the-badge)](#install-in-2-minutes)
[![Public data only](https://img.shields.io/badge/data-public%20only-1f8f68?style=for-the-badge)](#what-panoptes-never-does)
[![GitHub](https://img.shields.io/badge/repo-panoptes%2Fpanoptes-e7f2ec?style=for-the-badge&logo=github&logoColor=0b1210)](https://github.com/panoptes/panoptes)
[![License: Proprietary](https://img.shields.io/badge/license-proprietary-e07a6a?style=for-the-badge)](LICENSE)

---

> **Stop guessing. Start listening.**
>
> Most “validation” is vibes, surveys, and LinkedIn likes.
> **Panoptes finds people who already asked for what you sell — and got silence.**

That is real demand. Not a vanity metric. Not a paid lead list.
A human, on the public internet, stuck, waiting for someone useful to answer.

**Panoptes Demand Radar** turns that moment into:

1. the exact ask (quote + link)
2. a silence score (how unanswered it is)
3. public contact when available (email / phone / site)
4. a first-responder draft that answers *their* question

Then you reply. Book the call. Or learn — fast — that nobody is asking.

---

## Why this hits different

| Old way | Panoptes |
|--------|--------|
| “Would you buy this?” surveys | People already saying **I need this** |
| Cold lists from Apollo | Warm asks with zero useful replies |
| Guess your ICP | Watch which niches scream loudest |
| Generic “saw your post” spam | Evidence-locked drafts that cite the ask |
| Paid APIs & credit burns | **Free · self-hosted · public data** |

If your offer has demand, Panoptes surfaces it.
If it doesn’t — you’ll know before you burn another month building in the dark.

---

## The 30-second demo

```text
You paste:   "I book sales appointments for dental marketing agencies"

Panoptes finds: unanswered posts like
             "anyone know a good setter for dental clinics?"
             → 0 replies · silence 92 · posted 18h ago

You get:     public email/phone when scrapeable
             + a reply that answers THAT question
             + a DM / call opener ready to send
```

**That’s product-market signal you can act on tonight.**

---

## What you get

### Demand Radar (the product)

- **Offer → pain language** — expands your pitch into “looking for / need / recommend” queries  
- **Unanswered ask hunt** — Reddit + web demand surfaces (Google/Yahoo-style search)  
- **Silence score** — prioritizes zero-reply and thin threads  
- **Evidence pack** — quote, URL, age, context (required for every draft)  
- **Public contacts** — site scrape for email + phone when they’re public  
- **Free social deepen** — Instagram, GitHub, YouTube, Linktree, TikTok… LinkedIn with a free cookie; light Facebook/X HTML when open  
- **First-responder drafts** — public reply, DM/email, call opener, SMS  
- **Watch mode** — re-scan every N hours for *new* unanswered demand  
- **Outcomes** — tag replied / booked / ignored so you learn what converts  

### Also included

- **Business contacts mode** — niche → websites with **email + phone**  
- **Profile scrapers** — 8 platforms for deep profile pulls  
- **CSV + Instantly-ready export**  
- **Local API** — wire into Next.js / your stack  

---

## Install in 2 minutes

```bash
git clone https://github.com/panoptes/panoptes.git
cd panoptes
python -m venv .venv

# Windows
.\.venv\Scripts\Activate.ps1

# macOS / Linux
# source .venv/bin/activate

pip install -r requirements.txt
copy .env.example .env     # Windows
# cp .env.example .env     # macOS / Linux
```

### Launch

```bash
python run.py
```

Open **[http://127.0.0.1:8000](http://127.0.0.1:8000)**

```bash
python run.py --host 0.0.0.0 --port 8000
python run.py --reload
```

API docs → [http://127.0.0.1:8000/api/docs](http://127.0.0.1:8000/api/docs)

---

## Run a demand scan

### Web UI (recommended)

1. Open Panoptes  
2. Stay on **Demand Radar**  
3. Paste your offer (what you sell, in plain English)  
4. Keep **Deepen IG / LinkedIn / socials (free)** on  
5. Hit **Scan unanswered demand**  
6. Open asks → copy drafts → reply first  

Optional: **Save watch (6h)** to keep hunting while the app runs.

### CLI

```bash
# Core — does my offer have demand?
python demand_radar.py "I book sales appointments for dental marketing agencies" --target 25

# Tighter silence (only zero/one reply threads)
python demand_radar.py "appointment setting for coaches" --max-comments 1

# Only rows with a public email or phone
python demand_radar.py "outbound for SaaS agencies" --require-contact

# Recurring demand watch
python demand_radar.py "dental marketing help" --watch 6

# Faster / lighter (skip social deepen)
python demand_radar.py "coaching leads" --no-deepen
```

### Outputs

| File | What’s inside |
|------|----------------|
| `exports/radar_*_*.csv` | Asks · silence · contacts · drafts |
| `exports/radar_*_instantly_*.csv` | Email rows ready for Instantly-style tools |
| `data/panoptes_demand.db` | Local asks, outcomes, watches (**don’t wipe casually**) |

---

## How to read the signal

| What you see | What it means |
|--------------|----------------|
| Lots of high-silence asks matching your offer | **Demand is real** — go answer & book |
| Asks exist but wrong niche language | Refine ICP / positioning, re-scan |
| Almost no asks after several query angles | Weak public demand — pivot or change channel |
| Asks + contactable rows | Demand **and** a path to reach them |
| Asks, no contact | Still gold — reply publicly, build authority |

**Success metric that matters:**  
% of rows where you sent the first-responder draft *and* got a reply within 48h.

Not “leads scraped.” **Conversations started from unanswered demand.**

---

## Free forever path (no paid APIs required)

| Layer | Free approach |
|-------|----------------|
| Discovery | Reddit + Yahoo/Bing/Google-style web search |
| Demand phrases | Built-in offer compiler |
| Contacts | Public site /contact /about scrape |
| Social deepen | Built-in Instagram, GitHub, YouTube, Linktree, TikTok, Pinterest, Twitch |
| LinkedIn deepen | Your own free `li_at` cookie (optional) |
| Facebook / X | Best-effort public HTML only (skips login walls) |
| Drafts | Evidence-locked templates |

Optional paid upgrades (paste keys in **Settings** — only used when present):

| Key | What it unlocks |
|-----|-----------------|
| `GOOGLE_PLACES_API_KEY` | Real Google Places business discovery + phone/website |
| `FIRECRAWL_API_KEY` | Stronger site scraping for contact pages |
| `HUNTER_API_KEY` | Email finder / domain search |
| `APOLLO_API_KEY` | People match (email/phone/title) |
| `OPENAI_API_KEY` | GPT-polished first-responder drafts |
| `ANTHROPIC_API_KEY` | Claude-polished drafts (if no OpenAI key) |

Proxies remain optional. The free path always works without any of the above.

---

## Business contacts

Search a niche for people/businesses. Enrichment is **optional**.

```bash
# Fast list — no email/phone scrape
python find_leads.py "real estate coaching" --sources web,reddit --target 50 --no-contacts

# Enrich when available, keep partial contacts (default)
python find_leads.py "saas founders" --sources web,reddit --target 25

# Dial-ready only (both email + phone)
python find_leads.py "dental marketing agencies" --complete-only
```

---

## API (Next.js / automations)

| Endpoint | Purpose |
|----------|---------|
| `POST /api/radar` | Start demand scan `{ offer, niche?, target?, deepen? }` |
| `GET /api/radar/{job_id}` | Poll results |
| `GET /api/radar/leads` | Persisted asks |
| `POST /api/radar/outcome/{ask_id}` | Tag `replied` / `booked` / `ignored` |
| `POST /api/radar/watches` | Recurring demand watch |
| `GET /api/radar/watches` | List watches |
| `POST /api/discover` | Business contact discovery |
| `POST /api/scrape` | Deep profile scrape |

```env
PANOPTES_API_KEY=your-secret
PANOPTES_CORS_ORIGINS=http://localhost:3000
```

Send header: `X-API-Key: your-secret` when the key is set.

---

## Profile scrapers (deepen & manual)

| Platform | Auth | Pulls |
|----------|------|-------|
| Instagram | None | bio, followers, email, phone, links |
| TikTok | None | bio, followers, likes, email |
| LinkedIn | `li_at` cookie | headline, bio, email |
| GitHub | None | bio, repos, email, website |
| YouTube | None | channel, subs, email, links |
| Twitch | None | bio, followers, socials |
| Pinterest | None | bio, pins, website |
| Linktree | None | link-in-bio graphs |

### LinkedIn cookie (optional, free)

1. Log into LinkedIn in Chrome  
2. DevTools → Application → Cookies → `linkedin.com`  
3. Copy `li_at`  
4. Paste in **Settings** or `.env`:

```env
LINKEDIN_COOKIE=your_li_at_cookie_value
```

### Proxies (optional)

```env
PANOPTES_PROXY=http://user:pass@host:port
PANOPTES_PROXY_FILE=proxies.txt
PANOPTES_FREE_PROXY=true
```

Everything works without proxies.

---

## What Panoptes never does

- No data-breach dumps  
- No CAPTCHA / login-wall bypass  
- No private groups, DMs, or behind-auth stalking  
- No pretending cold spam is “validation”  

Public asks. Public contacts. Helpful first reply. That’s the whole game.

---

## Project map

```text
app/demand/     Demand Radar engine (offers, silence, deepen, drafts, store)
app/discovery/  Reddit / web / contacts / extract
app/scrapers/   Platform profile scrapers
app/web/        FastAPI + jobs + UI routes
templates/      Web UI
static/         CSS / JS
demand_radar.py CLI for demand scans
find_leads.py   CLI for business contacts
run.py          Launch the web app
```

---

## Who this is for

- Founders checking **“does anyone actually want this?”**  
- Agencies / setters hunting **warm, unanswered demand**  
- Operators who’d rather answer a stuck buyer than spray 10k cold emails  

If you sell something useful and people are asking for it in public — Panoptes makes sure you’re first.

---

## License

Proprietary. Copyright © 2026 Panoptes. All Rights Reserved.  
See [LICENSE](LICENSE).

---

<p align="center">
  <strong>Panoptes</strong> · <em>all-seeing</em><br/>
  <em>Real demand leaves a trail. Follow it.</em><br/><br/>
  <code>git clone https://github.com/panoptes/panoptes.git</code><br/>
  <code>python run.py</code> → <a href="http://127.0.0.1:8000">http://127.0.0.1:8000</a>
</p>
