import asyncio
from contextlib import closing
from datetime import date, datetime, timedelta
import hashlib
import json
import operator
from pathlib import Path
from typing import Annotated, Literal, NamedTuple, TypedDict
import os
import logging as log
import shutil
import sqlite3
import sys
import tempfile
from zoneinfo import ZoneInfo

import polars as pl
from pydantic import BaseModel, Field
from pydantic_ai import Agent
import httpx
from langgraph.graph import StateGraph, START, END
from langgraph.types import Send

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

MAX_BETS_PER_QUESTION = 20 # only the most likely outcomes are shown to the model
DECISIONS_USD_PER_1M_INPUT_TOKENS = 0.10 # uncached; output tokens are free
NOT_RELEVANT = "Not relevant" # the answer for a prediction that gets no tag

class Tag(NamedTuple):
    subject: str  # what the tag is about
    examples: str # for the prompt that gives a market its tag
    focus: str    # what the writer of this tag's memo must research

# The tags a relevant prediction or a catalyst can get, in order of priority.
# They are part of the prompts (templates/tags.mako and templates/memo_tag.mako), in ASD-STE100 Simplified Technical English.
TAGS = {
    "Crypto": Tag(
        "Crypto assets and the crypto industry.",
        "the price of Bitcoin or Ethereum, a crypto ETF, a crypto law, a crypto exchange.",
        "Research what drives the questions: flows into spot ETFs, pending laws and enforcement in the United States, and events at large exchanges and issuers. "
        "Include the listed companies that depend on crypto: exchanges, miners, and companies that hold Bitcoin.",
    ),
    "Macro": Tag(
        "Economic indicators and the policy of central banks.",
        "PCE, CPI, employment data, GDP, inflation, interest rates, a decision of the Federal Reserve, a recession.",
        "Build the path that the questions imply for inflation, employment, growth and the policy rate, meeting by meeting. "
        "Compare it with the latest official data and with what the Federal Reserve said last. "
        "Include bond duration, the yield curve, the dollar and rate-sensitive sectors.",
    ),
    "Commodities": Tag(
        "The price or the supply of a commodity.",
        "gold, silver, crude oil, natural gas, gasoline, copper.",
        "Research the supply and the demand behind each price question: decisions of OPEC+, inventories, weather, sanctions and shipping. "
        "Include the effect on inflation, and on producers, refiners, miners and large consumers such as airlines.",
    ),
    "Market": Tag(
        "A specific company, its stock, or a stock index.",
        "the price of Nvidia stock, the level of the S&P 500, an earnings report, a merger, an IPO.",
        "For each company or index, research the event behind the question: the earnings date and what is expected, "
        "a deal and its path through regulators, an IPO, a change of management. Include competitors, suppliers and the sector.",
    ),
    "Geopolitical": Tag(
        "A conflict or an agreement between countries.",
        "a war, a military operation, a ceasefire, sanctions, tariffs, a trade agreement.",
        "For each conflict or negotiation, research its present state, the parties, and the realistic paths to escalation and to settlement. "
        "Include energy, shipping lanes, defense, exposure to sanctions and safe-haven assets.",
    ),
    "International": Tag(
        "The politics of one country that is not the United States.",
        "a national election in a large foreign economy, a new leader of a foreign country, a foreign law.",
        "For each election or change of leader, research each candidate that has a real chance: the party, and the positions on trade, fiscal policy, industry and the currency. "
        "Include the exchange rate with the dollar and United States companies that do business in that country.",
    ),
    "Govt": Tag(
        "The government of the United States.",
        "the president, the administration, Congress, the Supreme Court, a federal agency, a national election, a government shutdown.",
        "For each question about a person, research who the candidates are and what they would do in the post. "
        "For each question about a law, a ruling or a deadline, research where it stands and what it changes. "
        "Include taxes, tariffs, the budget, regulation and the sectors that depend on them.",
    ),
    "Calamities": Tag(
        "A disaster that is not a war.",
        "an earthquake, a hurricane, a tornado, a flood, a wildfire, a pandemic.",
        "Research the present state and the official forecasts of each event. "
        "Include insurers and reinsurers, utilities, supply chains, commodity prices and the regions that are exposed.",
    ),
    "Other": Tag(
        "A subject that has no other tag.",
        "a milestone of a technology, a discovery in science.",
        "Research what is behind each question and why it can matter to the investor. Include the assets or sectors that it touches.",
    ),
}

# Memos: one for each tag and one that combines them, written by a reasoning model (see the graphs at the end)
RESPONSES_API_URL = "https://api.openai.com/v1/responses"
MEMO_MODEL = os.getenv("MEMO_MODEL") or "gpt-6.2-astra"
MEMO_EFFORT = "high" # reasoning effort
MEMO_INTERVAL_DAYS = 7 # write new memos when the stored ones are this old; 1 = with every daily report
FORCE_MEMOS = os.getenv("FORCE_MEMOS", "").lower() == "true" # write new memos now, whatever their age
MEMO_WORDS = {"tag": 300, "summary": 350} # the length limit in each prompt
MEMO_CONCURRENCY = 3
MEMO_TIMEOUT_SECONDS = 30 * 60 # research at high effort takes minutes
MEMO_USD_PER_1M_TOKENS = {"input": 8.00, "output": 40.00} # gpt-6.2-astra; reasoning tokens count as output
CODEX_BIN = os.getenv("CODEX_BIN") or "codex" # without an OPENAI_API_KEY the local Codex CLI writes the memos (development)

EVENTS_MODEL = "openai:gpt-5.1-2025-11-13"

# SQLite database kept between runs (see the workflow): cached relevance scores + daily snapshots + the latest memos
DB_FILE = Path(".data/zeitgeist.db")
DB_RETENTION_DAYS = 30 # forget markets not seen for this long


today = date.today()

load_dotenv()
log.getLogger().setLevel(log.INFO)
templates = TemplateLookup(directories=["templates"])

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
RELEVANCE_QUESTION = "Is this prediction market relevant to the investor? If it is relevant, which tag does it get?"
# "Not relevant" comes first, and each tag says again that it is only for a relevant market: a market that fits
# a tag well is otherwise called relevant because of the tag
RELEVANCE_CHOICES = [
    {"value": NOT_RELEVANT, "description": "The result has no very clear effect on the investor."},
    *({"value": name, "description": f"The result has a very clear effect on the investor. Subject: {tag.subject}"} for name, tag in TAGS.items()),
]
# A cached score is only reused while the model and prompt are unchanged (the date in the prompt is ignored)
PROMPT_HASH = hashlib.sha256("\n".join([
    RELEVANCE_MODEL, relevance_input(date(2000, 1, 1)), RELEVANCE_QUESTION, json.dumps(RELEVANCE_CHOICES),
]).encode()).hexdigest()[:16]

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
        CREATE TABLE IF NOT EXISTS memos (date TEXT, tag TEXT, markdown TEXT, PRIMARY KEY (date, tag));
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

SUMMARY = "" # the "tag" under which the combined memo is stored

def save_memos(db: sqlite3.Connection, tag_memos: dict[str, str], summary: str | None):
    """Replace the stored memos with the set written today."""
    db.execute("DELETE FROM memos")
    memos = tag_memos | ({SUMMARY: summary} if summary else {})
    db.executemany("INSERT INTO memos (date, tag, markdown) VALUES (?, ?, ?)", [(today.isoformat(), tag, memo) for tag, memo in memos.items()])
    db.commit()

def latest_memos(db: sqlite3.Connection) -> dict | None:
    """The stored memos as they go into output.json, or None if there are none yet."""
    rows = db.execute("SELECT date, tag, markdown FROM memos").fetchall()
    if not rows:
        return None
    memos = {tag: memo for _, tag, memo in rows}
    return {"date": rows[0][0], "summary": memos.get(SUMMARY), "tags": {tag: memos[tag] for tag in TAGS if tag in memos}}

def memos_are_due(db: sqlite3.Connection) -> bool:
    newest = db.execute("SELECT max(date) FROM memos").fetchone()[0]
    return FORCE_MEMOS or newest is None or newest <= (today - timedelta(days=MEMO_INTERVAL_DAYS)).isoformat()

def prune_db(db: sqlite3.Connection):
    cutoff = (today - timedelta(days=DB_RETENTION_DAYS)).isoformat()
    db.execute("DELETE FROM snapshots WHERE market_id IN (SELECT id FROM markets WHERE last_seen < ?)", (cutoff,))
    deleted = db.execute("DELETE FROM markets WHERE last_seen < ?", (cutoff,)).rowcount
    db.commit()
    db.execute("VACUUM")
    log.info(f"Pruned {deleted} markets not seen since {cutoff}")

def top_bets(prediction: dict) -> list[dict]:
    """The outcomes of a prediction that a model gets to see: the most likely ones."""
    return sorted(prediction["bets"] or [], key=lambda b: b["probability"], reverse=True)[:MAX_BETS_PER_QUESTION]

def relevance_question(prediction: dict) -> dict:
    """One choice question for the Decisions API; its name is the prediction id so the answer maps back."""
    # No odds in the text: the answer should describe the market, not today's prices, so it can be cached
    outcomes = "; ".join(b["prompt"] for b in top_bets(prediction))
    return {
        "type": "choice",
        "name": prediction["id"],
        "instructions": f"{RELEVANCE_QUESTION}\nTitle: {prediction['title']}\nOutcomes: {outcomes}",
        "choices": RELEVANCE_CHOICES,
    }

def read_answer(answer: dict) -> dict:
    """The relevance and the tag of a prediction, from the answer to its relevance_question()."""
    if answer["type"] != "choice": # a question the model declines to answer comes back as type "refusal"
        return {"relevance": 0.0, "tag": None}
    # A choice answer has a probability for each choice: relevance is the chance that any tag applies, and the tag is the likeliest one
    probability = {p["value"]: p["probability"] for p in answer["probabilities"]}
    return {
        "relevance": sum(probability.get(tag, 0.0) for tag in TAGS),
        "tag": max(TAGS, key=lambda tag: probability.get(tag, 0.0)),
    }

async def post_to_openai(client: httpx.AsyncClient, url: str, body: dict) -> dict:
    """POST to an OpenAI API and return its JSON response; waits and tries again on rate limits and server errors."""
    error = None
    for _ in range(RETRIES):
        try:
            resp = await client.post(url, json=body)
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
    raise RuntimeError(f"Request to {url} failed: {error}")

async def ask_decisions(client: httpx.AsyncClient, questions: list[dict]) -> dict:
    """Ask the Decisions API one batch of questions about RELEVANCE_INPUT."""
    return await post_to_openai(client, DECISIONS_API_URL, {"model": RELEVANCE_MODEL, "input": RELEVANCE_INPUT, "questions": questions})

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
        scores = {answer["name"]: read_answer(answer) for answer in decision["answers"]}
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

async def get_events() -> pl.DataFrame:
    events_agent = Agent(
        model=EVENTS_MODEL,
        output_type=list[Event],
        system_prompt=templates.get_template("events_prompt.mako").render(today=today, tags=TAGS),
        model_settings={"tools": [{"type": "web_search", "search_context_size": "high"}]},
        retries=RETRIES,
    )
    res = await events_agent.run()
    return pl.DataFrame(res.output)

############################################### Memos ####################################################

def memo_input(tag: str, predictions: pl.DataFrame, catalysts: pl.DataFrame) -> dict:
    """What the writer of one tag's memo reads: the questions and the catalysts with that tag, soonest first."""
    questions = predictions.filter(pl.col("tag") == tag).sort("resolution_date", nulls_last=True).to_dicts()
    events = catalysts.filter(pl.col("tag") == tag).sort("expected_date").to_dicts() if "tag" in catalysts.columns else []
    return {
        "questions": [
            {"title": q["title"], "resolves": q["resolution_date"], "url": q["url"],
             "outcomes": {b["prompt"]: round(b["probability"], 2) for b in top_bets(q)}}
            for q in questions
        ],
        "catalysts": [{"title": e["title"], "when": e["when"], "url": e["url"]} for e in events],
    }

async def write_with_api(instructions: str, input: str, web_search: bool) -> str:
    """One answer from MEMO_MODEL through the OpenAI Responses API."""
    body = {
        "model": MEMO_MODEL, "reasoning": {"effort": MEMO_EFFORT}, "instructions": instructions, "input": input,
        "tools": [{"type": "web_search"}] if web_search else [],
    }
    async with httpx.AsyncClient(headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"}, timeout=MEMO_TIMEOUT_SECONDS) as client:
        response = await post_to_openai(client, RESPONSES_API_URL, body)
    assert response["status"] == "completed", f"Response is {response['status']}: {response.get('incomplete_details') or response.get('error')}"
    usage = response["usage"]
    cost = sum(usage[f"{kind}_tokens"] * usd / 1e6 for kind, usd in MEMO_USD_PER_1M_TOKENS.items())
    log.info(f"{MEMO_MODEL} usage: {usage['input_tokens']:,} input + {usage['output_tokens']:,} output tokens ~ ${cost:.2f}")
    # The output holds reasoning and web search steps too; the answer is the text of its message(s)
    return "".join(part["text"] for item in response["output"] if item["type"] == "message" for part in item["content"] if part["type"] == "output_text")

async def write_with_codex(instructions: str, input: str, web_search: bool) -> str:
    """One answer from MEMO_MODEL through the local Codex CLI, for development on a machine that has no API key."""
    rules = "Reply with the markdown only. Do not run commands. Do not read or write files." + ("" if web_search else " Do not search the web.")
    with tempfile.TemporaryDirectory() as folder: # Codex works in an empty folder, not in this repository
        answer = Path(folder) / "answer.md"
        codex = await asyncio.create_subprocess_exec(
            CODEX_BIN, "exec", "--model", MEMO_MODEL, "--config", f'model_reasoning_effort="{MEMO_EFFORT}"', "--sandbox", "read-only",
            "--ephemeral", "--skip-git-repo-check", "--color", "never", "--cd", folder, "--output-last-message", str(answer), "-",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
        )
        _, errors = await asyncio.wait_for(codex.communicate(f"{instructions}\n<input>\n{input}\n</input>\n\n{rules}".encode()), MEMO_TIMEOUT_SECONDS)
        assert codex.returncode == 0 and answer.exists(), f"codex exec failed: {errors.decode()[-500:]}"
        return answer.read_text(encoding="utf-8")

memo_writers = asyncio.Semaphore(MEMO_CONCURRENCY)

async def write(instructions: str, input: dict, web_search: bool) -> str:
    """Markdown from the memo model: through the OpenAI API when there is a key, else through the local Codex CLI."""
    async with memo_writers:
        write_with = write_with_api if os.getenv("OPENAI_API_KEY") else write_with_codex
        return (await write_with(instructions, json.dumps(input, default=str), web_search)).strip()

class MemoState(TypedDict, total=False):
    predictions: pl.DataFrame # the relevant ones, each with a tag
    catalysts: pl.DataFrame
    tag_memos: Annotated[dict[str, str], operator.or_] # every write_tag_memo adds its own
    summary: str

def tags_to_write(state: MemoState) -> list[Send] | str:
    """One write_tag_memo for each tag that has questions; straight to the end when no tag has any."""
    inputs = {tag: memo_input(tag, state["predictions"], state["catalysts"]) for tag in TAGS}
    return [Send("write_tag_memo", {"tag": tag, "input": input}) for tag, input in inputs.items() if input["questions"]] or END

async def write_tag_memo(task: dict) -> dict:
    name, tag = task["tag"], TAGS[task["tag"]]
    log.info(f"Writing the {name} memo from {len(task['input']['questions'])} questions and {len(task['input']['catalysts'])} catalysts ...")
    instructions = templates.get_template("memo_tag.mako").render(today=today, tag=name, subject=tag.subject, focus=tag.focus, words=MEMO_WORDS["tag"])
    try:
        return {"tag_memos": {name: await write(instructions, task["input"], web_search=True)}}
    except Exception as e: # the other memos and the dashboard do not depend on this one
        log.error(f"No {name} memo: {e!r}")
        return {"tag_memos": {}}

async def write_summary(state: MemoState) -> dict:
    sections = {tag: state["tag_memos"][tag] for tag in TAGS if tag in state["tag_memos"]}
    if not sections:
        return {}
    log.info(f"Writing the summary memo from {len(sections)} tag memos ...")
    instructions = templates.get_template("memo_summary.mako").render(today=today, tags=list(sections), words=MEMO_WORDS["summary"])
    try:
        return {"summary": await write(instructions, sections, web_search=False)}
    except Exception as e:
        log.error(f"No summary memo: {e!r}")
        return {}

memos = StateGraph(MemoState)
memos.add_node("write_tag_memo", write_tag_memo)
memos.add_node("write_summary", write_summary)
memos.add_conditional_edges(START, tags_to_write, ["write_tag_memo", END])
memos.add_edge("write_tag_memo", "write_summary")
memos.add_edge("write_summary", END)
memo_graph = memos.compile()

async def write_memos_for(report_file: Path, tags: list[str]):
    """Development: write the memos for a saved report (an output.json) and put them into it; `tags` limits which ones."""
    report = json.loads(report_file.read_text(encoding="utf-8"))
    predictions = pl.DataFrame(report["relevant_predictions"]).filter(pl.col("tag").is_in(tags or list(TAGS)))
    state = await memo_graph.ainvoke({"predictions": predictions, "catalysts": pl.DataFrame(report["upcoming_catalysts"])})
    report["memos"] = {"date": today.isoformat(), "summary": state.get("summary"), "tags": state["tag_memos"]}
    report_file.write_text(json.dumps(report, indent=2), encoding="utf-8")
    log.info(f"Wrote {len(state['tag_memos'])} tag memos and {'a' if state.get('summary') else 'no'} summary into {report_file}")

############################################## Pipeline ##################################################

class State(MemoState, total=False):
    kalshi: pl.DataFrame
    polymarket: pl.DataFrame
    memos_due: bool

async def fetch_kalshi(state: State) -> dict:
    return {"kalshi": await fetch_from_kalshi()}

async def fetch_polymarket(state: State) -> dict:
    return {"polymarket": await fetch_from_polymarket()}

async def find_catalysts(state: State) -> dict:
    return {"catalysts": await get_events()}

async def score_and_tag(state: State) -> dict:
    predictions = pl.concat([state["kalshi"], state["polymarket"]])
    predictions = predictions.unique(subset="id", keep="first", maintain_order=True) # a market can come back on two pages
    log.info(f"Total = {len(predictions)} predictions")
    predictions = predictions.filter(pl.col("volume_24h") > 0)
    log.info(f"After volume filter = {len(predictions)} predictions")
    with closing(open_db()) as db:
        return {"predictions": await find_relevant_predictions(predictions, db)}

def check_memos(state: State) -> dict:
    with closing(open_db()) as db:
        due = memos_are_due(db)
    log.info(f"New memos are {'due' if due else f'not due: the stored ones are less than {MEMO_INTERVAL_DAYS} days old'}")
    return {"memos_due": due}

def publish(state: State) -> dict:
    with closing(open_db()) as db:
        save_snapshots(db, state["predictions"])
        if state.get("tag_memos"):
            save_memos(db, state["tag_memos"], state.get("summary"))
        memos = latest_memos(db)
        prune_db(db)

    output_dir = Path(".reports")
    output_dir.mkdir(parents=True, exist_ok=True)

    index_file = output_dir / "index.html"
    shutil.copy("index.html", index_file)
    log.info(f"Copied index.html to {index_file}")

    output_json_file = output_dir / "output.json"
    log.info(f"Writing output to {output_json_file} ...")
    output_data = {
        "date": today.isoformat(),
        "relevant_predictions": state["predictions"].to_dicts(),
        "upcoming_catalysts": state["catalysts"].to_dicts(),
        "memos": memos,
    }
    output_json_file.write_text(json.dumps(output_data, indent=2, default=str), encoding="utf-8") # default=str writes dates as YYYY-MM-DD
    return {}

# The whole report as one graph. See the diagram in the README: print(pipeline.get_graph(xray=1).draw_mermaid())
steps = StateGraph(State)
for step in (fetch_kalshi, fetch_polymarket, find_catalysts, score_and_tag, check_memos, publish):
    steps.add_node(step.__name__, step)
steps.add_node("write_memos", memo_graph)
for first in ("fetch_kalshi", "fetch_polymarket", "find_catalysts"):
    steps.add_edge(START, first)
steps.add_edge(["fetch_kalshi", "fetch_polymarket"], "score_and_tag")
steps.add_edge(["score_and_tag", "find_catalysts"], "check_memos")
steps.add_conditional_edges("check_memos", lambda state: "write_memos" if state["memos_due"] else "publish", ["write_memos", "publish"])
steps.add_edge("write_memos", "publish")
steps.add_edge("publish", END)
pipeline = steps.compile()

async def main():
    assert os.getenv("OPENAI_API_KEY"), "No OPENAI_API_KEY found; Either add to .env file or run `export OPENAI_API_KEY=???`"
    await pipeline.ainvoke({})
    log.info("Done!")
    if IS_DEV:
        import webbrowser
        webbrowser.open(Path(".reports/index.html").absolute().as_uri())

if __name__ == "__main__":
    if sys.argv[1:2] == ["memos"]: # python zeitgeist.py memos .reports/output.json [Macro Crypto ...]
        asyncio.run(write_memos_for(Path(sys.argv[2]), sys.argv[3:]))
    else:
        asyncio.run(main())
