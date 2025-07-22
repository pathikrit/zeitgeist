import marimo

__generated_with = "0.14.11"
app = marimo.App(width="medium")


@app.cell
def _():
    from datetime import date
    import json
    from pathlib import Path
    import os

    import polars as pl
    from pydantic import BaseModel, Field
    from pydantic_ai import Agent
    import requests
    import marimo as mo


    today = date.today()

    assert "OPENAI_API_KEY" in os.environ, "No OPENAI_API_KEY found in env. Either add to .env file in this repo or export it in terminal"
    return Agent, BaseModel, Field, Path, json, mo, pl, requests, today


@app.cell
def _(pl, requests):
    def fetch_from_kalshi() -> pl.DataFrame:
        API_URL = "https://api.elections.kalshi.com/trade-api/v2"
        params = {"status": "open", "with_nested_markets": "true", "limit": 100, "cursor": None}
        predictions = []

        def simple_prediction(e):
            bets = []
            for m in e["markets"]:
                bets.append({"prompt": m["yes_sub_title"], "probability": m["last_price"] / m["notional_value"]})
            return {"id": f"kalshi-{e['event_ticker']}", "title": e["title"], "bets": bets}

        while True:
            print(f"Fetching from kalshi @ offset={len(predictions)} ...")
            resp = requests.get(f"{API_URL}/events", params=params)
            resp.raise_for_status()
            data = resp.json()
            predictions.extend(data["events"])
            params["cursor"] = data.get("cursor")
            if not params["cursor"]:
                print(f"Fetched {len(predictions)} from kalshi")
                return pl.DataFrame([simple_prediction(p) for p in predictions])


    kalshi_predictions = fetch_from_kalshi()
    return (kalshi_predictions,)


@app.cell
def _(json, pl, requests):
    def fetch_from_polymarket() -> pl.DataFrame:
        API_URL = "https://gamma-api.polymarket.com"
        predictions = []

        def simple_prediction(p):
            bets = []
            for prompt, probability in zip(json.loads(p["outcomes"]), json.loads(p.get("outcomePrices", "[]"))):
                bets.append({"prompt": prompt, "probability": float(probability)})
            return {"id": f"pm-{p['id']}", "title": p["question"], "bets": bets}

        while True:
            params = {"active": "true", "closed": "false", "limit": 100, "offset": len(predictions)}
            print(f"Fetching from polymarket @ offset={params['offset']} ...")
            resp = requests.get(f"{API_URL}/markets", params=params)
            resp.raise_for_status()
            data = resp.json()
            predictions.extend(data)
            if not data:
                print(f"Fetched {len(predictions)} from polymarket")
                return pl.DataFrame([simple_prediction(p) for p in predictions])

        return predictions


    polymarket_predictions = fetch_from_polymarket()
    return (polymarket_predictions,)


@app.cell
def _(kalshi_predictions, polymarket_predictions):
    predictions = kalshi_predictions.extend(polymarket_predictions)
    len(predictions)
    return (predictions,)


@app.cell
def _():
    REASONING_MODEL = "openai:o3-2025-04-16"
    DEFAULT_MODEL = "openai:gpt-4.1-2025-04-14"
    return (DEFAULT_MODEL,)


@app.cell
async def _(Agent, BaseModel, DEFAULT_MODEL, Field, pl, predictions, today):
    about_me = (
        "<about_me>"
        "I am an American equities investor and I am interested in topics"
        "that would impact the market in the relatively short term or could change how I invest"
        "Besides publicly listed equities, I can have exposure to broad indices (e.g. $SPY and $QQQ)"
        "sectors (e.g. defense - $XAR, healthcare -  $XLV) and alternativles"
        "like gold, energy, commodities, crypto, bonds, TIPS, REITs, mortgage-backed securities etc"
        "through ETFs/vehicles like $IAU, $DBC, $BTC, $ZROZ, $TIPZ, $VNQ etc"
        "so pay particular attention to macroeconomic themes"
        "Some examples of things that are LIKELY to impact my investments:"
        "  - Short term macroeconomic indicators like GDP, unemployment, CPI, trade deficit etc."
        "  - Public or private companies suing each other or M&A activities"
        "  - Foreign politics that would affect USD rates with major international currencies like JPY,CNY,EUR etc"
        "  - EV/climate legislatation and goals in short term (<5 years)"
        "  - US policies and outlook on debt, budget, tax laws, tariffs, healthcare, energy"
        "  - General major geopolitical events that can happen near future (<5 years)"
        "  - Specific public companies mentioned like Tesla, Apple, Nvidia etc"
        "  - Major natural disasters, pandemics or crisis with high (>50%) probabilities"
        f"FYI: today's date is {today.strftime('%d-%b-%Y')}"
        "General instuctions:"
        "- Think deeply about second or third order effects"
        "- Don't restrict yourself or fixate on only the tickers or themes mentioned above"
        "  since these are just examples I used to give you a general idea of how I can invest"
        "</about_me>"
    )


    class RelevantPrediction(BaseModel):
        id: str = Field(description="original id from input")
        topics: list[str] = Field(description="public companies or investment sectors or broad alternatives impacted")


    relevant_prediction_agent = Agent(
        model=DEFAULT_MODEL,
        output_type=list[RelevantPrediction],
        system_prompt=(
            "<task>"
            "You will be provided an array of questions from an online betting market"
            "Your job is to return only the ids of questions relevant to me"
            "</task>"
            f"{about_me}"
            "Some examples of things that are UNLIKELY to impact (unless a good reason is provided):"
            "  - Celebrity gossips e.g. how many tweets would Elon tweet this month"
            "  - Sports related e.g. Would Ronaldo be traded this season"
            "  - Events far (10+ years) in the future: Would India host the Olympics by 2040"
            "  - Geography e.g. election results in Kiribati is unlikely to impact my investments"
            "    but major economies like Chinese, India, EU, MEA politics is likely to impact"
            "  - Media e.g. what song will be in top billboard this week"
            "  - Ignore memecoins and NFTs (but focus on major crypto themes like BTC, solana and ethereum etc)"
            "  - Ignore essentially gambling bets on short term prices e.g. what will be USD/JPY today at 12pm"
            "Examine each question and return a subset of ids and related topics they may impact"
            "Topics be few must be short strings like sectors or tickers"
            "or short phrases that would be impacted by this question"
            "Generally be lenient when possible to decide whether to include an id or not"
        ),
    )


    async def tag_predictions(predictions: pl.DataFrame) -> pl.DataFrame:
        try:
            relevant_predictions = await relevant_prediction_agent.run(predictions.write_json())
        except e:
            if e.__cause__:
                print(f"Underlying error: {type(e.__cause__).__name__}: {str(e.__cause__)}")
            else:
                print(f"Underlying error: {str(e)}")
            raise
        relevant_predictions = pl.DataFrame(relevant_predictions.output)
        print(f"Picked {len(relevant_predictions)} relevant predictions from {len(predictions)}")
        return predictions.join(relevant_predictions, on="id", how="left")


    tagged_predictions = await tag_predictions(predictions)
    tagged_predictions
    return about_me, tagged_predictions


@app.cell
def _():
    from gnews import GNews

    news = GNews().get_top_news()
    print(f"Fetched {len(news)} news headlines")
    news
    return (news,)


@app.cell
async def _(Agent, DEFAULT_MODEL, about_me, mo, news, pl, tagged_predictions):
    def to_xml_str(input: dict) -> str:
        from dicttoxml import dicttoxml

        return dicttoxml(input, xml_declaration=False, root=False, attr_type=False, return_bytes=False)


    synthesizing_agent = Agent(
        model=DEFAULT_MODEL,
        output_type=str,
        system_prompt=(
            f"{about_me}"
            "<task>"
            "You will be provided an array of questions and probabilities from an online betting market"
            f"along with today's top news headlines"
            "Consolidate and summarize into a 1-pager investment guideline thesis report"
            "The provided topics column can serve as hints to explore but think deeply about 2nd and 3rd order effects"
            "Take into account the probabilities and the fact that the topic is being discussed in the first place"
            "but also keep in mind that prediction markets often have longshot bias i.e."
            "people sometime tend to overweight extreme low-probability outcomes and underweight high-probability ones"
            "due to the non-linear probability weighting function in their model"
            "</task>"
            "<output_format>"
            "Present in a markdown format with sections and sub-sections"
            "Go from broad (e.g. macro) to narrow (e.g. sector) and finally individual names as top-level sections"
            "Also add and consolidate any important or relevant news items"
            "in simple bullets at the top in a separate news section"
            f"This is intended to be consumed daily as a news memo"
            "So just use the title: Daily Memo (date)"
            "Things to avoid:"
            "  - Don't mention that your input was prediction markets; the reader is aware of that"
            "  - Avoid putting the exact probabilities from the input; just use plain English to describe the prospects"
            "  - Avoid general guidelines like 'review this quarterly'"
            "  - Unless it pertains to an individual company or currency"
            "    avoid mentioning broad ETF tickers as I can figure that out from the sector or bond duration etc"
            "</output_format>"
        ),
    )

    report_input = {
        "prediction_markets": tagged_predictions.select("title", "bets", "topics")
        .filter(pl.col("topics").is_not_null())
        .to_dicts(),
        "news_headlines": pl.DataFrame(news).select("title", "description").to_dicts() if news else [],
    }

    report = await synthesizing_agent.run(to_xml_str(report_input))
    mo.md(report.output)
    return (report,)


@app.cell
def _(Path, report, today):
    from markdown_it import MarkdownIt

    output_dir = Path(f".reports/{today.strftime("%Y/%m/%d")}")
    output_dir.mkdir(parents=True, exist_ok=True)

    html = f"""<!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>Report {today.strftime('%d-%b-%Y')}</title>
    </head>
    <body>{MarkdownIt().render(report.output)}</body>
    </html>
    """

    print(f"Writing to {output_dir} ...")
    (output_dir / "index.html").write_text(html, encoding="utf-8")
    print("Done!")
    html
    return


if __name__ == "__main__":
    app.run()
