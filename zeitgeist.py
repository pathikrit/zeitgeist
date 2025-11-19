import asyncio
from datetime import date
import json
from pathlib import Path
import os
import logging as log

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

BATCH_REQUEST_DELAY_SECONDS = 5

BATCH_SIZE = 100
RETRIES = 3

CLASSIFYING_MODEL = "openai:gpt-5-mini-2025-08-07"
EVENTS_MODEL = "openai:gpt-5.1-2025-11-13"
SYNTHESIS_MODEL = "openai:gpt-4.1-2025-04-14"

today = date.today()

load_dotenv()
log.getLogger().setLevel(log.INFO)
templates = TemplateLookup(directories=["templates"])

assert "OPENAI_API_KEY" in os.environ, "No OPENAI_API_KEY found; Either add to .env file or run `export OPENAI_API_KEY=???`"
assert not(IS_PROD and QUICK_TEST), "QUICK_TEST must be False in GitHub Actions"

########################################################################################################

async def fetch_from_kalshi() -> pl.DataFrame:
    LIMIT = 100
    API_URL = "https://api.elections.kalshi.com/trade-api/v2"
    params = {"status": "open", "with_nested_markets": "true", "limit": LIMIT, "cursor": None}
    predictions = []

    def simple_prediction(e):
        bets = []
        for m in e["markets"]:
            bets.append({"prompt": m["yes_sub_title"], "probability": m["last_price"] / m["notional_value"]})
        return {"id": f"kalshi-{e['event_ticker']}", "title": e["title"], "bets": bets}

    async with httpx.AsyncClient() as client:
        while True:
            log.info(f"Fetching from kalshi @ offset={len(predictions)} ...")
            try:
                resp = await client.get(f"{API_URL}/events", params=params)
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
        return {"id": f"pm-{p['id']}", "title": p["question"], "bets": bets}

    async with httpx.AsyncClient() as client:
        while True:
            params = {"active": "true", "closed": "false", "limit": LIMIT, "offset": len(predictions)}
            log.info(f"Fetching from polymarket @ offset={params['offset']} ...")
            try:
                resp = await client.get(f"{API_URL}/markets", params=params)
                resp.raise_for_status()
                data = resp.json()
                predictions.extend(data)
            except Exception as e:
                log.error(f"Stopping because of error from Polymarket: {e}")
                data = None
            if not data or (QUICK_TEST and len(predictions) > LIMIT):
                log.info(f"Fetched {len(predictions)} from polymarket")
                return pl.DataFrame([simple_prediction(p) for p in predictions])


class RelevantPrediction(BaseModel):
    id: str = Field(description="original id from input")
    topics: list[str] = Field(description="public companies or investment sectors or broad alternatives impacted")

relevant_prediction_agent = Agent(
    model=CLASSIFYING_MODEL,
    output_type=list[RelevantPrediction],
    system_prompt=templates.get_template("relevant_prediction_prompt.mako").render(today=today),
    retries=RETRIES,
)

async def tag_predictions(predictions: pl.DataFrame) -> pl.DataFrame:
    async def process_batch_with_delay(i: int, batch: pl.DataFrame) -> pl.DataFrame | None:
        await asyncio.sleep(i * BATCH_REQUEST_DELAY_SECONDS)
        log.info(f"Submitting batch {i} ...")
        try:
            result = await relevant_prediction_agent.run(batch.write_json())
            log.info(f"Completed batch {i}")
            if result.output:
                return pl.DataFrame(result.output)
        except Exception as e:
            log.error(f"Error in tagging batch {i}: {e}")
        return None

    tasks = [
        process_batch_with_delay(i, batch)
        for i, batch in enumerate(predictions.iter_slices(BATCH_SIZE))
    ]
    results = await asyncio.gather(*tasks)
    dfs = [df for df in results if df is not None]
    assert dfs, "No relevant predictions found"
    relevant_predictions = pl.concat(dfs)
    log.info(f"Picked {len(relevant_predictions)} relevant predictions from {len(predictions)}")
    return predictions.join(relevant_predictions, on="id", how="left")


class Event(BaseModel):
    event: str = Field(description="title of macro event or catalyst")
    when: str = Field(description="approximately when; either specific date or stringy like '2025 Q2' or 'next month'")
    impacts: list[str] = Field(description="list of short phrases or topics hinting at how this may impact me")

events_agent = Agent(
    model=EVENTS_MODEL,
    output_type=list[Event],
    system_prompt=templates.get_template("events_prompt.mako").render(today=today),
    model_settings={"tools": [{"type": "web_search", "search_context_size": "high"}]},
    retries=RETRIES,
)

synthesizing_agent = Agent(
    model=SYNTHESIS_MODEL,
    output_type=str,
    system_prompt=templates.get_template("synthesizing_prompt.mako").render(today=today),
    retries=RETRIES,
)

async def get_news() -> pl.DataFrame | None:
    from gnews import GNews
    try:
        news = await asyncio.to_thread(GNews().get_top_news)
        log.info(f"Fetched {len(news)} news headlines")
        return pl.DataFrame(news)
    except Exception as e:
        logging.error(f"Error in getting news from GNews: {e}")
        return None

async def main():
    predictions = pl.concat(await asyncio.gather(fetch_from_kalshi(), fetch_from_polymarket()))
    log.info(f"Total = {len(predictions)} predictions")

    tagged_predictions, events, news = await asyncio.gather(
        tag_predictions(predictions),
        events_agent.run(),
        get_news()
    )

    report_input = {
        "prediction_markets": tagged_predictions
            .select("title", "bets", "topics")
            .filter(pl.col("topics").is_not_null())
            .to_dicts(),
        "news_headlines": news.select("title", "description").to_dicts() if news is not None else None,
        "upcoming_catalysts": pl.DataFrame(events.output).to_dicts(),
    }
    log.info("Generating report...")
    report = await synthesizing_agent.run(json.dumps(report_input))

    output_dir = Path(f".reports/{today.strftime('%Y/%m/%d')}")
    output_dir.mkdir(parents=True, exist_ok=True)
    log.info(f"Writing to {output_dir} ...")
    html = templates.get_template("index.html.mako").render(today=today, report=report.output)
    (output_dir / "index.html").write_text(html, encoding="utf-8")
    log.info("Done!")


if __name__ == "__main__":
    asyncio.run(main())


