import asyncio
from datetime import date, datetime, timedelta
import hashlib
import json
from pathlib import Path
from typing import Literal
import os
import logging as log
import shutil
import sqlite3
from zoneinfo import ZoneInfo

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

# Relevance filter and tags: OpenAI Decisions API, one choice question per prediction
# https://developers.openai.com/api/docs/guides/decisions
DECISIONS_API_URL = "https://api.openai.com/v1/decisions"
RELEVANCE_MODEL = "gpt-6-luna" # the only model the Decisions API supports
DECISIONS_BATCH_SIZE = 400 # API maximum questions per request
DECISIONS_CONCURRENCY = 4
DECISIONS_TIMEOUT_SECONDS = 120
RELEVANCE_THRESHOLD = 0.5 # keep predictions at or above this probability of being relevant
NOT_RELEVANT = "Not relevant" # the answer for a prediction that gets no tag

# The tags a relevant prediction or a catalyst can get, in order of priority, each with its subject.
# The subjects are part of the prompts (templates/tags.mako), in ASD-STE100 Simplified Technical English.
TAGS = {
    "Crypto": "Crypto assets and the crypto industry. Examples: the price of Bitcoin or Ethereum, a crypto ETF, a crypto law, a crypto exchange.",
    "Macro": "Economic indicators and the policy of central banks. Examples: PCE, CPI, employment data, GDP, inflation, interest rates, a decision of the Federal Reserve, a recession.",
    "Commodities": "The price or the supply of a commodity. Examples: gold, silver, crude oil, natural gas, gasoline, copper.",
    "Market": "A specific company, its stock, or a stock index. Examples: the price of Nvidia stock, the level of the S&P 500, an earnings report, a merger, an IPO.",
    "Geopolitical": "A conflict or an agreement between countries. Examples: a war, a military operation, a ceasefire, sanctions, tariffs, a trade agreement.",
    "International": "The politics of one country that is not the United States. Examples: an election in a foreign country, a new leader of a foreign country, a foreign law.",
    "Govt": "The government of the United States. Examples: the president, the administration, Congress, the Supreme Court, a federal agency, a United States election, a government shutdown.",
    "Other": "A subject that has no other tag. Examples: a natural disaster, a pandemic, a milestone of a technology.",
}
MAX_BETS_PER_QUESTION = 20 # only the most likely outcomes are shown to the model
DECISIONS_USD_PER_1M_INPUT_TOKENS = 0.10 # uncached; output tokens are free

EVENTS_MODEL = "openai:gpt-5.1-2025-11-13"

# SQLite database kept between runs (see the workflow): cached relevance scores + daily snapshots
DB_FILE = Path(".data/zeitgeist.db")
DB_RETENTION_DAYS = 30 # forget markets not seen for this long


today = date.today()

load_dotenv()
log.getLogger().setLevel(log.INFO)
templates = TemplateLookup(directories=["templates"])

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

def to_date(timestamp: str | None) -> date | None:
    """Calendar date of an ISO timestamp in US Eastern time, which is what both platforms set deadlines in
    (a "by December 31" market ends at 2027-01-01T04:59:00Z)."""
    if not timestamp:
        return None
    return datetime.fromisoformat(timestamp).astimezone(ZoneInfo("America/New_York")).date()

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
            # An event's markets can resolve on different dates; keep the last, when the whole question is settled
            "resolution_date": to_date(max((m.get("expected_expiration_time") or "" for m in e["markets"]), default=None)),
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
            "resolution_date": to_date(p.get("endDate")),
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


def relevance_input(day: date) -> str:
    """What every question of a Decisions API request shares: the investor, the relevance rules and the tags."""
    return templates.get_template("relevance_input.mako").render(today=day, tags=TAGS, not_relevant=NOT_RELEVANT)

RELEVANCE_INPUT = relevance_input(today)
RELEVANCE_QUESTION = "Select the answer for this prediction market."
RELEVANCE_CHOICES = [{"value": answer} for answer in [*TAGS, NOT_RELEVANT]] # their meaning is in RELEVANCE_INPUT
# A cached score is only reused while the model and prompt are unchanged (the date in the prompt is ignored)
PROMPT_HASH = hashlib.sha256("\n".join([RELEVANCE_MODEL, relevance_input(date(2000, 1, 1)), RELEVANCE_QUESTION]).encode()).hexdigest()[:16]

def open_db() -> sqlite3.Connection:
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_FILE)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS markets (
            id TEXT PRIMARY KEY, source TEXT, title TEXT, url TEXT,
            relevance REAL, prompt_hash TEXT, first_seen TEXT, last_seen TEXT, resolution_date DATE, tag TEXT
        );
        CREATE TABLE IF NOT EXISTS snapshots (
            market_id TEXT, date TEXT, bets_json TEXT, volume REAL, volume_24h REAL,
            PRIMARY KEY (market_id, date)
        );
    """)
    # Columns that a database created before they existed does not have yet
    existing = {column[1] for column in db.execute("PRAGMA table_info(markets)")}
    for column, kind in {"resolution_date": "DATE", "tag": "TEXT"}.items():
        if column not in existing:
            db.execute(f"ALTER TABLE markets ADD COLUMN {column} {kind}")
    return db

def cached_scores(db: sqlite3.Connection) -> dict[str, dict]:
    """The relevance and tag already computed with the current model and prompt, by market id."""
    rows = db.execute("SELECT id, relevance, tag FROM markets WHERE prompt_hash = ?", (PROMPT_HASH,))
    return {id: {"relevance": relevance, "tag": tag} for id, relevance, tag in rows}

def save_scores(db: sqlite3.Connection, predictions: pl.DataFrame, scores: dict[str, dict]):
    """Upsert every scored market seen today, so tomorrow's run can skip it."""
    db.executemany(
        """
        INSERT INTO markets (id, source, title, url, relevance, tag, prompt_hash, first_seen, last_seen, resolution_date)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (id) DO UPDATE SET
            title = excluded.title, url = excluded.url, relevance = excluded.relevance, tag = excluded.tag,
            prompt_hash = excluded.prompt_hash, last_seen = excluded.last_seen,
            resolution_date = excluded.resolution_date
        """,
        [
            (p["id"], "kalshi" if p["id"].startswith("k-") else "polymarket", p["title"], p["url"],
             scores[p["id"]]["relevance"], scores[p["id"]]["tag"], PROMPT_HASH, today.isoformat(), today.isoformat(),
             p["resolution_date"] and p["resolution_date"].isoformat())
            for p in predictions.select("id", "title", "url", "resolution_date").to_dicts() if p["id"] in scores
        ],
    )
    db.commit()

def save_snapshots(db: sqlite3.Connection, relevant: pl.DataFrame):
    """Record today's odds and volume for the relevant markets, building up a history."""
    db.executemany(
        "INSERT OR REPLACE INTO snapshots (market_id, date, bets_json, volume, volume_24h) VALUES (?, ?, ?, ?, ?)",
        [(p["id"], today.isoformat(), json.dumps(p["bets"]), p["volume"], p["volume_24h"]) for p in relevant.to_dicts()],
    )
    db.commit()

def prune_db(db: sqlite3.Connection):
    cutoff = (today - timedelta(days=DB_RETENTION_DAYS)).isoformat()
    db.execute("DELETE FROM snapshots WHERE market_id IN (SELECT id FROM markets WHERE last_seen < ?)", (cutoff,))
    deleted = db.execute("DELETE FROM markets WHERE last_seen < ?", (cutoff,)).rowcount
    db.commit()
    db.execute("VACUUM")
    log.info(f"Pruned {deleted} markets not seen since {cutoff}")

def relevance_question(prediction: dict) -> dict:
    """One choice question for the Decisions API; its name is the prediction id so the answer maps back."""
    bets = sorted(prediction["bets"] or [], key=lambda b: b["probability"], reverse=True)[:MAX_BETS_PER_QUESTION]
    # No odds in the text: the score should describe the market, not today's prices, so it can be cached
    outcomes = "; ".join(b["prompt"] for b in bets)
    return {
        "type": "choice",
        "name": prediction["id"],
        "instructions": f"{RELEVANCE_QUESTION}\nTitle: {prediction['title']}\nOutcomes: {outcomes}",
        "choices": RELEVANCE_CHOICES,
    }

def read_answer(answer: dict) -> dict:
    """A choice answer has a probability for each choice: relevance is the chance that any tag applies, and the tag is the likeliest one."""
    probability = {p["value"]: p["probability"] for p in answer["probabilities"]}
    return {
        "relevance": sum(probability.get(tag, 0.0) for tag in TAGS),
        "tag": max(TAGS, key=lambda tag: probability.get(tag, 0.0)),
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

async def find_relevant_predictions(predictions: pl.DataFrame, db: sqlite3.Connection) -> pl.DataFrame:
    """Tag the predictions not already in the database with the Decisions API; keep those above RELEVANCE_THRESHOLD."""
    cached = cached_scores(db)
    to_score = predictions.filter(~pl.col("id").is_in(list(cached)))
    log.info(f"{len(predictions) - len(to_score)} predictions already scored, {len(to_score)} new ones to score")
    semaphore = asyncio.Semaphore(DECISIONS_CONCURRENCY)
    input_tokens = 0

    async def process_batch(i: int, batch: pl.DataFrame, client: httpx.AsyncClient) -> dict[str, dict]:
        nonlocal input_tokens
        async with semaphore:
            log.info(f"Asking Decisions API about batch {i} ({len(batch)} predictions) ...")
            try:
                decision = await ask_decisions(client, [relevance_question(p) for p in batch.to_dicts()])
            except Exception as e:
                log.error(f"Error in relevance batch {i}: {e}")
                return {}
        input_tokens += (decision.get("usage") or {}).get("input_tokens", 0)
        # A question the model declines to answer comes back as type "refusal"; it counts as not relevant
        scores = {a["name"]: read_answer(a) if a["type"] == "choice" else {"relevance": 0.0, "tag": None} for a in decision["answers"]}
        if len(scores) < len(batch):
            log.warning(f"Batch {i}: {len(batch) - len(scores)} of {len(batch)} predictions got no answer")
        return scores

    async with httpx.AsyncClient(
        headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
        timeout=DECISIONS_TIMEOUT_SECONDS,
    ) as client:
        results = await asyncio.gather(*[
            process_batch(i, batch, client)
            for i, batch in enumerate(to_score.select("id", "title", "bets").iter_slices(DECISIONS_BATCH_SIZE))
        ])

    new_scores = {id: score for batch_scores in results for id, score in batch_scores.items()}
    assert new_scores or not len(to_score), "Decisions API returned no answers"
    scores = cached | new_scores
    save_scores(db, predictions, scores)
    relevance = pl.DataFrame(
        [{"id": id, **score} for id, score in scores.items()],
        schema={"id": pl.String, "relevance": pl.Float64, "tag": pl.String},
    )
    relevant = predictions.join(relevance, on="id", how="inner").filter(pl.col("relevance") >= RELEVANCE_THRESHOLD)
    log.info(f"Picked {len(relevant)} relevant predictions from {len(predictions)} ({len(new_scores)} scored now)")
    log.info(f"Tags: {dict(relevant['tag'].value_counts(sort=True).iter_rows())}")
    log.info(f"Decisions API usage: {input_tokens:,} input tokens ~ ${input_tokens * DECISIONS_USD_PER_1M_INPUT_TOKENS / 1e6:.3f}")
    return relevant


class Event(BaseModel):
    title: str = Field(description="title of macro event or catalyst")
    when: str = Field(description="approximately when; either specific date or stringy like '2025 Q2' or 'next month'")
    expected_date: date = Field(description="best single calendar date for `when`; for a period use its last day e.g. 'late January 2027' -> 2027-01-31 or '2027 Q2' -> 2027-06-30")
    tag: Literal[*TAGS] = Field(description="the one tag from <tags> that fits the event best")
    url: str | None = Field(description="web url linking to a page with details about the event - okay to skip if url is not available or too generic")

events_agent = Agent(
    model=EVENTS_MODEL,
    output_type=list[Event],
    system_prompt=templates.get_template("events_prompt.mako").render(today=today, tags=TAGS),
    model_settings={"tools": [{"type": "web_search", "search_context_size": "high"}]},
    retries=RETRIES,
)

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

    # Predictions are keyed by id; catalysts are positional (same order as in output.json)
    if preds := data.get("relevant_predictions"):
        texts = [f"{p['title']} {' '.join(b['prompt'] for b in (p.get('bets') or []))}" for p in preds]
        result["predictions"] = dict(zip((p["id"] for p in preds), embed("predictions", texts)))

    if cats := data.get("upcoming_catalysts"):
        result["catalysts"] = embed("catalysts", [f"{c['title']} {c.get('when', '')}" for c in cats])

    log.info(
        f"Embeddings ready: {len(result.get('predictions', {}))} predictions, "
        f"{len(result.get('catalysts', []))} catalysts"
    )
    return result


async def main():
    predictions = pl.concat(await asyncio.gather(fetch_from_kalshi(), fetch_from_polymarket()))
    log.info(f"Total = {len(predictions)} predictions")
    predictions = predictions.filter(pl.col("volume_24h") > 0)
    log.info(f"After volume filter = {len(predictions)} predictions")

    db = open_db()
    relevant_predictions, events = await asyncio.gather(find_relevant_predictions(predictions, db), get_events())

    save_snapshots(db, relevant_predictions)
    prune_db(db)
    db.close()

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
    }
    output_json_file.write_text(json.dumps(output_data, indent=2, default=str), encoding="utf-8") # default=str writes dates as YYYY-MM-DD

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
