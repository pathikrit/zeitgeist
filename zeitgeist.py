import asyncio
from datetime import date
import json
from pathlib import Path
import os

import polars as pl
from pydantic import BaseModel, Field
from pydantic_ai import Agent
import httpx

from mako.lookup import TemplateLookup

from dotenv import load_dotenv
load_dotenv()

IS_PROD = "GITHUB_ACTIONS" in os.environ
IS_DEV = not IS_PROD

QUICK_TEST = IS_DEV # If True, run quickly on first few predictions; useful for smoke-testing

BATCH_SIZE = 200
RETRIES = 3

CLASSIFYING_MODEL = "openai:gpt-5-mini-2025-08-07"
EVENTS_MODEL = "openai:gpt-5.1-2025-11-13"
SYNTHESIS_MODEL = "openai:gpt-4.1-2025-04-14"

today = date.today()

templates = TemplateLookup(directories=["templates"])

assert "OPENAI_API_KEY" in os.environ, "No OPENAI_API_KEY found; Either add to .env file or run `export OPENAI_API_KEY=???`"

assert not(IS_PROD and QUICK_TEST), "QUICK_TEST must be False in GitHub Actions"

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
            print(f"Fetching from kalshi @ offset={len(predictions)} ...")
            resp = await client.get(f"{API_URL}/events", params=params)
            resp.raise_for_status()
            data = resp.json()
            predictions.extend(data["events"])
            params["cursor"] = data.get("cursor")
            if not params["cursor"] or (QUICK_TEST and len(predictions) > LIMIT):
                print(f"Fetched {len(predictions)} from kalshi")
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
            print(f"Fetching from polymarket @ offset={params['offset']} ...")
            try:
                resp = await client.get(f"{API_URL}/markets", params=params)
                resp.raise_for_status()
                data = resp.json()
                predictions.extend(data)
            except Exception as e:
                print(f"Stopping because of error from Polymarket: {e}")
                data = None
            if not data or (QUICK_TEST and len(predictions) > LIMIT):
                print(f"Fetched {len(predictions)} from polymarket")
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
    # Although this is more elegant, this can lead to "too many requests"
    # tasks = [relevant_prediction_agent.run(batch.write_json()) for batch in predictions.iter_slices(BATCH_SIZE)]
    # results = await asyncio.gather(*tasks)

    dfs = []
    for i, batch in enumerate(predictions.iter_slices(BATCH_SIZE)):
        print(f"Processing batch {i} ...")
        result = await relevant_prediction_agent.run(batch.write_json())
        if result.output:
            dfs.append(pl.DataFrame(result.output))
        await asyncio.sleep(1)

    relevant_predictions = pl.concat(dfs)
    print(f"Picked {len(relevant_predictions)} relevant predictions from {len(predictions)}")
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

breakpoint()

def to_xml_str(input: dict) -> str:
    from dicttoxml import dicttoxml
    return dicttoxml(input, xml_declaration=False, root=False, attr_type=False, return_bytes=False)

async def main():
    from gnews import GNews

    predictions = pl.concat(await asyncio.gather(fetch_from_kalshi(), fetch_from_polymarket()))
    print(f"Total = {len(predictions)} predictions")

    tagged_predictions, events = await asyncio.gather(
        tag_predictions(predictions),
        events_agent.run()
    )
    news = GNews().get_top_news()

    print(f"Fetched {len(news)} news headlines")
    report_input = {
        "prediction_markets": tagged_predictions
            .select("title", "bets", "topics")
            .filter(pl.col("topics").is_not_null())
            .to_dicts(),
        "news_headlines": pl.DataFrame(news).select("title", "description").to_dicts() if news else [],
        "upcoming_catalysts": pl.DataFrame(events.output).to_dicts(),
    }
    report = await synthesizing_agent.run(to_xml_str(report_input))
    html = templates.get_template("index.html.mako").render(today=today, report=report.output)
    output_dir = Path(f".reports/{today.strftime('%Y/%m/%d')}")
    print(f"Writing to {output_dir} ...")
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "index.html").write_text(html, encoding="utf-8")
    print("Done!")


if __name__ == "__main__":
    asyncio.run(main())


