import marimo

__generated_with = "0.14.11"
app = marimo.App(width="medium")


@app.cell
def _():
    import asyncio
    from datetime import date
    import json
    from pathlib import Path
    import os

    import polars as pl
    from pydantic import BaseModel, Field
    from pydantic_ai import Agent
    import requests
    import marimo as mo

    IS_PROD = "GITHUB_ACTIONS" in os.environ
    IS_DEV = not IS_PROD

    QUICK_TEST = IS_DEV # If True, run quickly on first few predictions; useful for smoke-testing

    BATCH_SIZE = 200
    RETRIES = 3

    CLASSIFYING_MODEL = "openai:gpt-5-mini-2025-08-07"
    EVENTS_MODEL = "openai:gpt-5.1-2025-11-13"
    SYNTHESIS_MODEL = "openai:gpt-4.1-2025-04-14"

    today = date.today()

    assert "OPENAI_API_KEY" in os.environ, "No OPENAI_API_KEY found; Either add to .env file or run `export OPENAI_API_KEY=???`"

    assert not(IS_PROD and QUICK_TEST), "QUICK_TEST must be False in GitHub Actions"
    return (
        Agent,
        BATCH_SIZE,
        BaseModel,
        CLASSIFYING_MODEL,
        EVENTS_MODEL,
        Field,
        Path,
        QUICK_TEST,
        RETRIES,
        SYNTHESIS_MODEL,
        asyncio,
        json,
        mo,
        pl,
        requests,
        today,
    )


@app.cell
def _(QUICK_TEST, pl, requests):
    def fetch_from_kalshi() -> pl.DataFrame:
        LIMIT = 100
        API_URL = "https://api.elections.kalshi.com/trade-api/v2"
        params = {"status": "open", "with_nested_markets": "true", "limit": LIMIT, "cursor": None}
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
            if not params["cursor"] or (QUICK_TEST and len(predictions) > LIMIT):
                print(f"Fetched {len(predictions)} from kalshi")
                return pl.DataFrame([simple_prediction(p) for p in predictions])


    kalshi_predictions = fetch_from_kalshi()
    return (kalshi_predictions,)


@app.cell
def _(QUICK_TEST, json, pl, requests):
    def fetch_from_polymarket() -> pl.DataFrame:
        LIMIT = 100
        API_URL = "https://gamma-api.polymarket.com"
        predictions = []

        def simple_prediction(p):
            bets = []
            for prompt, probability in zip(json.loads(p["outcomes"]), json.loads(p.get("outcomePrices", "[]"))):
                bets.append({"prompt": prompt, "probability": float(probability)})
            return {"id": f"pm-{p['id']}", "title": p["question"], "bets": bets}

        while True:
            params = {"active": "true", "closed": "false", "limit": LIMIT, "offset": len(predictions)}
            print(f"Fetching from polymarket @ offset={params['offset']} ...")
            try:
                resp = requests.get(f"{API_URL}/markets", params=params)
                resp.raise_for_status()
                data = resp.json()
                predictions.extend(data)
            except Exception as e:
                print(f"Stopping because of error from Polymarket: {e}")
                data = None
            if not data or (QUICK_TEST and len(predictions) > LIMIT):
                print(f"Fetched {len(predictions)} from polymarket")
                return pl.DataFrame([simple_prediction(p) for p in predictions])


    polymarket_predictions = fetch_from_polymarket()
    return (polymarket_predictions,)


@app.cell
def _(kalshi_predictions, pl, polymarket_predictions):
    predictions = pl.concat([kalshi_predictions, polymarket_predictions])
    len(predictions)
    return (predictions,)


@app.cell
async def _(
    Agent,
    BATCH_SIZE,
    BaseModel,
    CLASSIFYING_MODEL,
    Field,
    RETRIES,
    asyncio,
    pl,
    predictions,
    today,
):
    about_me = (
        "<about_me>"
        "I am an American equities investor and I am interested in topics"
        "that would impact the market in the relatively short term or could change how I invest"
        "Besides publicly listed equities, I can have exposure to broad indices (e.g. $SPY and $QQQ)"
        "sectors (e.g. defense: $XAR, healthcare: $XLV) and alternatives"
        "like gold, energy, commodities, crypto, bonds, TIPS, REITs, mortgage-backed securities etc"
        "through ETFs/vehicles like $IAU, $DBC, $BTC, $ZROZ, $TIPZ, $VNQ etc"
        "so pay particular attention to macroeconomic themes"
        "Some examples of things that are LIKELY to impact my investments:"
        "  - Short term macroeconomic indicators like GDP, unemployment, CPI, trade deficit etc."
        "  - Public or private companies suing each other or M&A activities"
        "  - Foreign politics that would affect USD rates with major international currencies like JPY, CNY, EUR etc"
        "  - EV/climate legislation and goals in short term (<5 years)"
        "  - US policies and outlook on debt, budget, tax laws, tariffs, healthcare, energy"
        "  - General major geopolitical events that can happen near future (<2 years)"
        "  - Specific major public companies mentioned like Tesla, Apple, Nvidia etc"
        "  - Major natural disasters, pandemics or crisis with high (>50%) probabilities"
        f"FYI: today's date is {today.strftime('%d-%b-%Y')}"
        "General instructions:"
        "- Think deeply about second or third order effects"
        "- Don't restrict yourself or fixate on only the tickers or themes mentioned above"
        "  since these are just examples I used to give you a general idea of how I can invest"
        "</about_me>"
    )


    class RelevantPrediction(BaseModel):
        id: str = Field(description="original id from input")
        topics: list[str] = Field(description="public companies or investment sectors or broad alternatives impacted")


    relevant_prediction_agent = Agent(
        model=CLASSIFYING_MODEL,
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


    tagged_predictions = await tag_predictions(predictions)
    tagged_predictions
    return about_me, tagged_predictions


@app.cell
async def _(Agent, BaseModel, EVENTS_MODEL, Field, RETRIES, about_me):
    class Event(BaseModel):
        event: str = Field(description="title of macro event or catalyst")
        when: str = Field(description="approximately when; either specific date or stringy like '2025 Q2' or 'next month'")
        impacts: list[str] = Field(description="list of short phrases or topics hinting at how this may impact me")


    events_agent = Agent(
        model=EVENTS_MODEL,
        output_type=list[Event],
        system_prompt=(
            f"{about_me}"
            "<task>"
            "List key macro events and catalysts that might impact me"
            "e.g. FED or FOMC meetings, rate cuts, govt shutdowns, major economic prints, major earnings calls, "
            "investor days, 13F, regulatory events, diplomatic events & visits, trade talks, supreme court descisions"
            "tech days, demos, analyst events, headline numbers, trade talks etc"
            "Avoid generic events or ongoing events (like wars) without any concrete timelines or concrete resolutions"
            "Also avoid things that can happen far in the future (>1 yr from now)"
            "ALWAYS USE the web search tool call"
            "</task>"        
        ),
        model_settings={"tools": [{"type": "web_search", "search_context_size": "high"}]},
        retries=RETRIES,
    )

    events = await events_agent.run()
    events.output
    return (events,)


@app.cell
def _():
    from gnews import GNews

    news = GNews().get_top_news()
    print(f"Fetched {len(news)} news headlines")
    news
    return (news,)


@app.cell
async def _(
    Agent,
    RETRIES,
    SYNTHESIS_MODEL,
    about_me,
    events,
    mo,
    news,
    pl,
    tagged_predictions,
):
    def to_xml_str(input: dict) -> str:
        from dicttoxml import dicttoxml

        return dicttoxml(input, xml_declaration=False, root=False, attr_type=False, return_bytes=False)


    synthesizing_agent = Agent(
        model=SYNTHESIS_MODEL,
        output_type=str,
        system_prompt=(
            f"{about_me}"
            "<task>"
            "You will be provided an array of questions and probabilities from an online betting market"
            "along with today's top news headlines and a list of upcoming catalyst events"
            "Consolidate and summarize into a 1-pager investment guideline thesis report"
            "The provided topics column can serve as hints to explore but think deeply about 2nd and 3rd order effects"
            "and if any current news or upcoming events can impact these topics"
            "Take into account the probabilities and the fact that the topic is being discussed in the first place"
            "but also keep in mind that prediction markets often have moonshot bias i.e."
            "people sometime tend to overweight extreme low-probability outcomes and underweight high-probability ones"
            "Use critical thinking and self-reflection"
            "When appropriate or possible synthesize the betting market info with any relevant news or upcoming catalysts"
            "</task>"
            "<output_format>"
            "Present in a markdown format with sections and sub-sections"
            "Go from broad (e.g. macro) to narrow (e.g. sector) and finally individual names as top-level sections"
            "Consolidate any important or relevant news items into simple bullets at the top in a separate news section"
            "Consolidate all events and upcoming catalysts into a 'Upcoming Catalysts' section at the bottom'"
            "  - Skip generic things without any concrete timelines or dates"
            "  - Sort by soonest to furthest out"
            "  - If possible, for each catalyst mention a short phrase how it may impact me"
            "  - Avoid general guidelines like 'watch for regulatory moves or geopolitical risks' as that is not helpful"
            "This is intended to be consumed daily by a PM as a news memo, so just use the title: Daily Memo (date)"
            "Things to avoid:"
            "  - Don't mention that your input was prediction markets; the reader is aware of that"
            "  - Avoid putting the exact probabilities from the input; just use plain English to describe the prospects"
            "  - Avoid general guidelines like 'review this quarterly' or 'keep an eye'"
            "  - Avoid mentioning broad ETF tickers as I can figure that out from the sector or bond duration etc."
            "  - Avoid any generic or broad statements; be succinct and specific."
            "  - No hallucinations: never fabricate nor use illustrative numbers, metrics, quotes, or sources"
            "Writing style: "
            "  - No fluff; get to the heart of the matter as quickly as possible"
            "  - Be very careful to not be too verbose i.e. no essays; you'll waste time and lose attention"
            "  - Use short bullet points; nest bullets in markdown if nessecary"
            "  - Everything you say should sound wise and should stand up to scrutiny"
            "</output_format>"
        ),
        retries=RETRIES,
    )

    report_input = {
        "prediction_markets": tagged_predictions
            .select("title", "bets", "topics")
            .filter(pl.col("topics").is_not_null())
            .to_dicts(),
        "news_headlines": pl.DataFrame(news).select("title", "description").to_dicts() if news else [],
        "upcoming_catalysts": pl.DataFrame(events.output).to_dicts(),
    }

    report = await synthesizing_agent.run(to_xml_str(report_input))
    mo.md(report.output)
    return (report,)


@app.cell
def _(Path, report, today):
    from markdown_it import MarkdownIt

    output_dir = Path(f".reports/{today.strftime('%Y/%m/%d')}")
    output_dir.mkdir(parents=True, exist_ok=True)

    html = f"""<!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.classless.min.css">
        <title>Report {today.strftime("%d-%b-%Y")}</title>
    </head>
    <body>
    <main>
    <a href="https://github.com/pathikrit/zeitgeist" target="_blank" rel="noopener" style="float: right;">
        <img src="https://github.githubassets.com/images/modules/logos_page/GitHub-Mark.png" alt="GitHub" width="30" height="30">
    </a>
    {MarkdownIt().render(report.output)}
    </main>
    </body>
    </html>
    """

    print(f"Writing to {output_dir} ...")
    (output_dir / "index.html").write_text(html, encoding="utf-8")
    print("Done!")
    html
    return


if __name__ == "__main__":
    app.run()
