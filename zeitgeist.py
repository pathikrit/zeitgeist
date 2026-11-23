import asyncio
from datetime import date, datetime
import json
from pathlib import Path
import os
import logging as log
import re
import shutil

import polars as pl
from pydantic import BaseModel, Field
from pydantic_ai import Agent
import httpx

from mako.lookup import TemplateLookup

from dotenv import load_dotenv

########################################## Setup Configs #################################################

IS_PROD = "GITHUB_ACTIONS" in os.environ
IS_DEV = not IS_PROD

QUICK_TEST = IS_DEV # If True, run quickly on first few predictions; useful for smoke-testing

RATE_LIMIT_WAIT_SECONDS = 10
RETRIES = 3

# Relevance filter: OpenAI Decisions API, one predicate question per prediction
# https://developers.openai.com/api/docs/guides/decisions
DECISIONS_API_URL = "https://api.openai.com/v1/decisions"
RELEVANCE_MODEL = "gpt-6-luna" # the only model the Decisions API supports
DECISIONS_BATCH_SIZE = 400 # API maximum questions per request
DECISIONS_CONCURRENCY = 4
DECISIONS_TIMEOUT_SECONDS = 120
RELEVANCE_THRESHOLD = 0.5 # keep predictions at or above this probability of being relevant
MAX_BETS_PER_QUESTION = 20 # only the most likely outcomes are shown to the model
DECISIONS_USD_PER_1M_INPUT_TOKENS = 0.10 # uncached; output tokens are free

EVENTS_MODEL = "openai:gpt-5.1-2025-11-13"


today = date.today()

load_dotenv()
log.getLogger().setLevel(log.INFO)
templates = TemplateLookup(directories=["templates"])

FRED_API_KEY=os.getenv("FRED_API_KEY")
NUM_FRED_DATAPOINTS = 10

FRED_CODES = {
    "CPILFESL": "CPI (Core)",
    "PCEPILFE": "PCE Price Index (Core)",
    "PAYEMS": "Nonfarm Payrolls",
    "UNRATE": "Unemployment Rate",
    "CCSA": "Continuing Jobless Claims",
    "JTSJOL": "Job Openings (JOLTS)",
    "INDPRO": "Industrial Production",
    "RSAFS": "Retail Sales (Headline)",
    "HOUST": "Housing Starts",
    "CSUSHPISA": "Case-Shiller U.S. Home Price Index",
    "FEDFUNDS": "Fed Funds Rate",
    "M2SL": "M2 Money Supply",
    "DGS3MO": "3M Treasury Yield",
    "DGS2": "2Y Treasury Yield",
    "DGS5": "5Y Treasury Yield",
    "DGS10": "10Y Treasury Yield",
    "DGS30": "30Y Treasury Yield",
    "T10Y2Y": "10Y–2Y Yield Spread",
    "T10Y3M": "10Y–3M Yield Spread",
    "NFCI": "Chicago Fed Financial Conditions Index",
    "DTWEXBGS": "Trade-Weighted USD Index (Broad)",
    "DCOILWTICO": "WTI Crude Oil Price",
    "UMCSENT": "Michigan Consumer Sentiment",
    "VIXCLS": "VIX",
    "BAMLH0A0HYM2": "HY Credit Spread (OAS)",
    "BAMLC0A4CBBB": "BBB Credit Spread (OAS)",
}

assert "OPENAI_API_KEY" in os.environ, "No OPENAI_API_KEY found; Either add to .env file or run `export OPENAI_API_KEY=???`"
assert not(IS_PROD and QUICK_TEST), "QUICK_TEST must be False in GitHub Actions"

########################################################################################################

async def sleep_if_rate_limit(response: httpx.Response) -> bool:
    if response.status_code != 429:
        return False
    log.warning(
        f"Sleeping for {RATE_LIMIT_WAIT_SECONDS}s since we got {response.status_code} from {response.url}..."
    )
    await asyncio.sleep(RATE_LIMIT_WAIT_SECONDS)
    return True

async def fetch_from_kalshi() -> pl.DataFrame:
    LIMIT = 100
    API_URL = "https://api.elections.kalshi.com/trade-api/v2"
    params = {"status": "open", "with_nested_markets": "true", "limit": LIMIT, "cursor": None}
    predictions = []

    def simple_prediction(e):
        bets = []
        for m in e["markets"]:
            bets.append({"prompt": m["yes_sub_title"], "probability": float(m["last_price_dollars"]) / float(m["notional_value_dollars"])})
        return {
            "id": f"k-{e['event_ticker']}",
            "title": e["title"],
            "bets": bets,
            "url": f"https://kalshi.com/markets/{e['series_ticker']}",
            "volume": sum(float(m.get("volume_fp") or 0) for m in e["markets"]),
            "volume_24h": sum(float(m.get("volume_24h_fp") or 0) for m in e["markets"]),
        }

    async with httpx.AsyncClient() as client:
        while True:
            log.info(f"Fetching from kalshi @ offset={len(predictions)} ...")
            try:
                resp = await client.get(f"{API_URL}/events", params=params)
                if await sleep_if_rate_limit(resp):
                    continue
                resp.raise_for_status()
                data = resp.json()
                predictions.extend(data["events"])
                params["cursor"] = data.get("cursor")
            except Exception as e:
                log.error(f"Stopping because of error from Kalshi: {e}")
                params["cursor"] = None
            if not params["cursor"] or (QUICK_TEST and len(predictions) > LIMIT):
                log.info(f"Fetched {len(predictions)} from kalshi")
                return pl.DataFrame([simple_prediction(p) for p in predictions])

async def fetch_from_polymarket() -> pl.DataFrame:
    LIMIT = 100
    API_URL = "https://gamma-api.polymarket.com"
    predictions = []

    def simple_prediction(p):
        bets = []
        for prompt, probability in zip(json.loads(p["outcomes"]), json.loads(p.get("outcomePrices", "[]"))):
            bets.append({"prompt": prompt, "probability": float(probability)})
        return {
            "id": f"pm-{p['id']}",
            "title": p["question"],
            "bets": bets,
            "url": f"https://polymarket.com/event/{p['slug']}",
            "volume": p.get("volumeNum") or 0,
            "volume_24h": p.get("volume24hr") or 0,
        }

    # Offset paging is capped at 2000 rows, so use the keyset endpoint. Sorting by 24h volume
    # lets us stop at the first page with no traded market instead of walking ~140k markets.
    params = {"active": "true", "closed": "false", "limit": LIMIT, "order": "volume24hr", "ascending": "false"}
    async with httpx.AsyncClient(timeout=30) as client:
        while True:
            log.info(f"Fetching from polymarket @ {len(predictions)} ...")
            try:
                resp = await client.get(f"{API_URL}/markets/keyset", params=params)
                if await sleep_if_rate_limit(resp):
                    continue
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                log.error(f"Stopping because of error from Polymarket: {e}")
                data = {}
            traded = [p for p in data.get("markets", []) if (p.get("volume24hr") or 0) > 0]
            predictions.extend(traded)
            params["after_cursor"] = data.get("next_cursor")
            if not traded or not params["after_cursor"] or (QUICK_TEST and len(predictions) > LIMIT):
                log.info(f"Fetched {len(predictions)} from polymarket")
                return pl.DataFrame([simple_prediction(p) for p in predictions])


def get_fred_data() -> pl.DataFrame | None:
    from fredapi import Fred

    if not FRED_API_KEY:
        log.warning("No FRED API key found; skipping FRED data points ...")
        return None

    fred_client = Fred(api_key=FRED_API_KEY)

    out = []
    for code, title in FRED_CODES.items():
        log.info(f"Fetching {title} ({code}) from FRED ...")
        try:
            series = fred_client.get_series_latest_release(code)
            log.info(f"Fetched {len(series)} data points for FRED {code=}")
            records = [
                {"date": d.date().isoformat(), "value": float(v)}
                for d, v in zip(series.index, series.values)
                if v == v  # skip NaN
            ]
            out.append({
                "code": code,
                "title": title,
                "data": records[-NUM_FRED_DATAPOINTS:],
                "url": f"https://fred.stlouisfed.org/series/{code}"
            })
        except Exception as e:
            log.error(f"Failed to fetch FRED {code=}: {e}")

    return pl.DataFrame(out)


RELEVANCE_INPUT = templates.get_template("relevance_input.mako").render(today=today)
RELEVANCE_QUESTION = "Would the outcome of this prediction market have a VERY obvious impact on this investor?"

def relevance_question(prediction: dict) -> dict:
    """One predicate question for the Decisions API; its name is the prediction id so the answer maps back."""
    bets = sorted(prediction["bets"] or [], key=lambda b: b["probability"], reverse=True)[:MAX_BETS_PER_QUESTION]
    outcomes = "; ".join(f"{b['prompt']} ({b['probability']:.0%})" for b in bets)
    return {
        "type": "predicate",
        "name": prediction["id"],
        "instructions": f"{RELEVANCE_QUESTION}\nMarket: {prediction['title']}\nOutcomes: {outcomes}",
    }

async def ask_decisions(client: httpx.AsyncClient, questions: list[dict]) -> dict:
    """POST one batch of questions about RELEVANCE_INPUT to the Decisions API and return its response."""
    body = {"model": RELEVANCE_MODEL, "input": RELEVANCE_INPUT, "questions": questions}
    error = None
    for _ in range(RETRIES):
        try:
            resp = await client.post(DECISIONS_API_URL, json=body)
        except httpx.TransportError as e:
            error = repr(e)
            continue
        error = f"{resp.status_code}: {resp.text[:500]}"
        if await sleep_if_rate_limit(resp):
            continue
        if resp.status_code >= 500:
            await asyncio.sleep(RATE_LIMIT_WAIT_SECONDS)
            continue
        if resp.is_error:
            break
        return resp.json()
    raise RuntimeError(f"Decisions API request failed: {error}")

async def find_relevant_predictions(predictions: pl.DataFrame) -> pl.DataFrame:
    """Score every prediction's relevance with the Decisions API and keep those above RELEVANCE_THRESHOLD."""
    semaphore = asyncio.Semaphore(DECISIONS_CONCURRENCY)
    input_tokens = 0

    async def process_batch(i: int, batch: pl.DataFrame, client: httpx.AsyncClient) -> list[dict]:
        nonlocal input_tokens
        async with semaphore:
            log.info(f"Asking Decisions API about batch {i} ({len(batch)} predictions) ...")
            try:
                decision = await ask_decisions(client, [relevance_question(p) for p in batch.to_dicts()])
            except Exception as e:
                log.error(f"Error in relevance batch {i}: {e}")
                return []
        answers = decision["answers"]
        input_tokens += (decision.get("usage") or {}).get("input_tokens", 0)
        # A question the model declines to answer comes back as type "refusal"; treat it as not relevant
        scores = [{"id": a["name"], "relevance": a["probability"]} for a in answers if a["type"] == "predicate"]
        if len(scores) < len(batch):
            log.warning(f"Batch {i}: {len(batch) - len(scores)} of {len(batch)} predictions got no answer")
        return scores

    async with httpx.AsyncClient(
        headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
        timeout=DECISIONS_TIMEOUT_SECONDS,
    ) as client:
        results = await asyncio.gather(*[
            process_batch(i, batch, client)
            for i, batch in enumerate(predictions.select("id", "title", "bets").iter_slices(DECISIONS_BATCH_SIZE))
        ])

    scores = [score for batch_scores in results for score in batch_scores]
    assert scores, "Decisions API returned no answers"
    relevance = pl.DataFrame(scores, schema={"id": pl.String, "relevance": pl.Float64})
    relevant = predictions.join(relevance, on="id", how="inner").filter(pl.col("relevance") >= RELEVANCE_THRESHOLD)
    log.info(f"Picked {len(relevant)} relevant predictions from {len(predictions)} ({len(scores)} scored)")
    log.info(f"Decisions API usage: {input_tokens:,} input tokens ~ ${input_tokens * DECISIONS_USD_PER_1M_INPUT_TOKENS / 1e6:.3f}")
    return relevant


class Event(BaseModel):
    title: str = Field(description="title of macro event or catalyst")
    when: str = Field(description="approximately when; either specific date or stringy like '2025 Q2' or 'next month'")
    url: str | None = Field(description="web url linking to a page with details about the event - okay to skip if url is not available or too generic")

events_agent = Agent(
    model=EVENTS_MODEL,
    output_type=list[Event],
    system_prompt=templates.get_template("events_prompt.mako").render(today=today),
    model_settings={"tools": [{"type": "web_search", "search_context_size": "high"}]},
    retries=RETRIES,
)

async def get_gdpnow() -> dict | None:
    """Fetch Atlanta Fed GDPNow estimate by parsing the embedded JS arrays on their page."""
    url = "https://www.atlantafed.org/cqer/research/gdpnow"
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
            resp.raise_for_status()

        text = resp.text

        # Arrays are embedded in a JS section starting ~offset 57k; search only that region
        section = text[50000:270000]
        fd = re.search(r'\bforecastDates\s*=\s*(\[.*?\]);', section, re.DOTALL)
        gf = re.search(r'\bgdpForecast\s*=\s*(\[.*?\]);', section, re.DOTALL)
        if not fd or not gf:
            log.error("GDPNow: could not find embedded data arrays on page")
            return None

        dates     = json.loads(fd.group(1))
        forecasts = json.loads(gf.group(1))

        # Quarters are concatenated newest-first; find the boundary of the current quarter
        # by detecting when the parsed date jumps significantly backward.
        parsed = []
        for d, v in zip(dates, forecasts):
            try:
                parsed.append((datetime.strptime(d, "%m/%d/%Y"), float(v)))
            except (ValueError, TypeError):
                pass

        current_quarter = []
        for i, (d, v) in enumerate(parsed):
            if i > 0 and (parsed[i-1][0] - d).days > 30:
                break
            current_quarter.append({"date": d.strftime("%Y-%m-%d"), "value": v})

        if not current_quarter:
            return None

        latest = current_quarter[-1]
        # Extract the quarter label from the page card (e.g. "2026:Q1" → "2026 Q1")
        q_match = re.search(r'GDPNow Estimate for (\d{4}):Q(\d)', text)
        quarter = f"{q_match.group(1)} Q{q_match.group(2)}" if q_match else ""
        log.info(f"GDPNow: {latest['value']}% for {quarter} as of {latest['date']} ({len(current_quarter)} updates)")
        return {
            "estimate": latest["value"],
            "quarter": quarter,
            "date": latest["date"],
            "history": current_quarter,
            "url": url,
        }
    except Exception as e:
        log.error(f"Error fetching GDPNow: {e}")
        return None


async def get_fear_greed() -> list | None:
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get("https://api.alternative.me/fng/?limit=30")
            resp.raise_for_status()
            data = resp.json().get("data", [])
            log.info(f"Fetched {len(data)} Fear & Greed data points")
            return data
    except Exception as e:
        log.error(f"Error fetching Fear & Greed: {e}")
        return None


async def get_events() -> pl.DataFrame:
    res = await events_agent.run()
    return pl.DataFrame(res.output)

def generate_embeddings(data: dict) -> dict:
    """Generate semantic embeddings using fastembed all-MiniLM-L6-v2 (384-dim, L2-normalised).

    Compatible with Xenova/all-MiniLM-L6-v2 served by transformers.js in the browser,
    so dot-product of a pre-built embedding and a browser-side query embedding equals cosine similarity.
    """
    from fastembed import TextEmbedding

    log.info("Loading fastembed model (all-MiniLM-L6-v2) ...")
    model = TextEmbedding(model_name="sentence-transformers/all-MiniLM-L6-v2")

    def embed(kind: str, texts: list[str]) -> list[list[float]]:
        log.info(f"Embedding {len(texts)} {kind} ...")
        return [[round(float(x), 5) for x in emb] for emb in model.embed(texts)]

    result: dict = {}

    # Predictions are keyed by id; catalysts and news are positional (same order as in output.json)
    if preds := data.get("relevant_predictions"):
        texts = [f"{p['title']} {' '.join(b['prompt'] for b in (p.get('bets') or []))}" for p in preds]
        result["predictions"] = dict(zip((p["id"] for p in preds), embed("predictions", texts)))

    if cats := data.get("upcoming_catalysts"):
        result["catalysts"] = embed("catalysts", [f"{c['title']} {c.get('when', '')}" for c in cats])

    if news := data.get("news_headlines"):
        result["news"] = embed("news items", [f"{n.get('title', '')} {n.get('description', '')}" for n in news])

    log.info(
        f"Embeddings ready: {len(result.get('predictions', {}))} predictions, "
        f"{len(result.get('catalysts', []))} catalysts, {len(result.get('news', []))} news"
    )
    return result


def get_news() -> pl.DataFrame | None:
    from gnews import GNews
    try:
        news = GNews().get_top_news()
        log.info(f"Fetched {len(news)} news headlines")
        return pl.DataFrame(news)
    except Exception as e:
        log.error(f"Error in getting news from GNews: {e}")
        return None

async def main():
    predictions = pl.concat(await asyncio.gather(fetch_from_kalshi(), fetch_from_polymarket()))
    log.info(f"Total = {len(predictions)} predictions")
    predictions = predictions.filter(pl.col("volume_24h") > 0)
    log.info(f"After volume filter = {len(predictions)} predictions")

    relevant_predictions, events, news, fred_data, fear_greed, gdpnow = await asyncio.gather(
        find_relevant_predictions(predictions),
        get_events(),
        asyncio.to_thread(get_news),
        asyncio.to_thread(get_fred_data),
        get_fear_greed(),
        get_gdpnow(),
    )

    output_dir = Path(".reports")
    output_dir.mkdir(parents=True, exist_ok=True)

    index_file = output_dir / "index.html"
    shutil.copy("index.html", index_file)
    log.info(f"Copied index.html to {index_file}")

    output_json_file = output_dir / "output.json"
    log.info(f"Writing output to {output_json_file} ...")
    output_data = {
        "date": today.isoformat(),
        "relevant_predictions": relevant_predictions.to_dicts(),
        "upcoming_catalysts": events.to_dicts(),
        "news_headlines": news.to_dicts() if news is not None else None,
        "fred_data": fred_data.to_dicts() if fred_data is not None else None,
        "fear_greed": fear_greed,
        "gdpnow": gdpnow,
    }
    output_json_file.write_text(json.dumps(output_data, indent=2), encoding="utf-8")

    embeddings = generate_embeddings(output_data)
    embeddings_file = output_dir / "embeddings.json"
    embeddings_file.write_text(json.dumps(embeddings), encoding="utf-8")
    log.info(f"Wrote semantic index to {embeddings_file}")

    log.info("Done!")
    if IS_DEV:
        import webbrowser
        webbrowser.open(index_file.absolute().as_uri())

if __name__ == "__main__":
    asyncio.run(main())
