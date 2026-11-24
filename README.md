# zeitgeist [![Daily Report](https://github.com/pathikrit/zeitgeist/actions/workflows/daily_report.yml/badge.svg)](https://github.com/pathikrit/zeitgeist/actions/workflows/daily_report.yml)
Daily macro dashboard for an equities investor: prediction markets -> LLM relevance filter -> static dashboard

1. Fetch every open market from Kalshi and Polymarket
2. Ask the OpenAI [Decisions API](https://developers.openai.com/api/docs/guides/decisions) how likely each one is to matter to the investor described in `templates/about_me.mako`, and keep the likely ones
   - Scores are cached in a SQLite database, so each run only asks about markets it has not seen (or all of them again if the prompt changes)
3. Add upcoming catalysts, news headlines and macro indicators (FRED, GDPNow, Fear & Greed)
4. Publish `output.json` + `index.html` to GitHub Pages

## Database
`zeitgeist.db` (SQLite) is stored as an asset on the [`data` release](https://github.com/pathikrit/zeitgeist/releases/tag/data); the daily job downloads it, updates it and uploads it again.
- `markets`: every traded market seen in the last 30 days with its relevance score and resolution date
- `snapshots`: daily odds and volume of the relevant markets

## Today's Dashboard
- <https://pathikrit.github.io/zeitgeist/>

### Install & run
```shell
git clone git@github.com:pathikrit/zeitgeist.git
cd zeitgeist
cp .env.example .env # then fill in OPENAI_API_KEY (required) and FRED_API_KEY (optional)
uv run python zeitgeist.py
```
