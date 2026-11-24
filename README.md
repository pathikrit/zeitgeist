# zeitgeist [![Daily Report](https://github.com/pathikrit/zeitgeist/actions/workflows/daily_report.yml/badge.svg)](https://github.com/pathikrit/zeitgeist/actions/workflows/daily_report.yml)
Daily forward-looking dashboard for an equities investor: prediction markets -> LLM relevance filter -> timeline of what resolves when

1. Fetch every open market from Kalshi and Polymarket
2. Ask the OpenAI [Decisions API](https://developers.openai.com/api/docs/guides/decisions) one question per market: is it relevant to the investor described in `templates/about_me.mako`, and if so which tag fits it (Crypto, Macro, Commodities, Market, Geopolitical, International, Govt, Calamities or Other)?
   - The answer has a probability for each choice. A market is kept when the tags together are at least as likely as "Not relevant", and gets its most likely tag
   - Answers are cached in a SQLite database, so each run only asks about markets it has not seen (or all of them again if the prompt changes)
   - The prompts in `templates/` are written in ASD-STE100 Simplified Technical English
3. Add upcoming catalysts, each with an expected date and a tag
4. Publish `output.json` + `index.html` to GitHub Pages
   - A slider picks a month between now and five years out; the page shows the questions resolving and the catalysts expected by then
   - `index.html` has no build step: [Astryx](https://astryx.atmeta.com/) components and Font Awesome icons load from CDNs

## Database
`zeitgeist.db` (SQLite) is stored as an asset on the [`data` release](https://github.com/pathikrit/zeitgeist/releases/tag/data); the daily job downloads it, updates it and uploads it again.
- `markets`: every traded market seen in the last 30 days with its relevance score, tag and resolution date
- `snapshots`: daily odds and volume of the relevant markets

## Today's Dashboard
- <https://pathikrit.github.io/zeitgeist/>

### Install & run
```shell
git clone git@github.com:pathikrit/zeitgeist.git
cd zeitgeist
cp .env.example .env # then fill in OPENAI_API_KEY
uv run python zeitgeist.py
```
