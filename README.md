# zeitgeist [![Daily Report](https://github.com/pathikrit/zeitgeist/actions/workflows/daily_report.yml/badge.svg)](https://github.com/pathikrit/zeitgeist/actions/workflows/daily_report.yml)
Daily macro dashboard for an equities investor: prediction markets -> LLM relevance filter -> static dashboard

1. Fetch every open market from Kalshi and Polymarket
2. Ask the OpenAI [Decisions API](https://developers.openai.com/api/docs/guides/decisions) how likely each one is to matter to the investor described in `templates/about_me.mako`, and keep the likely ones
3. Tag the survivors with topics, and add upcoming catalysts, news headlines and macro indicators (FRED, GDPNow, Fear & Greed)
4. Publish `output.json` + `index.html` to GitHub Pages

## Today's Dashboard
- <https://pathikrit.github.io/zeitgeist/>

### Install & run
```shell
git clone git@github.com:pathikrit/zeitgeist.git
cd zeitgeist
cp .env.example .env # then fill in OPENAI_API_KEY (required) and FRED_API_KEY (optional)
uv run python zeitgeist.py
```
