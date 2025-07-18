import marimo

__generated_with = "0.14.11"
app = marimo.App(width="medium")


@app.cell
def _():
    import requests
    import polars as pl


    def fetch_from_kalshi() -> pl.DataFrame:
        BASE = "https://api.elections.kalshi.com/trade-api/v2"
        params = {"status": "open", "with_nested_markets": "true", "limit": 100, "cursor": None}
        predictions = []

        def simple_prediction(e):
            obj = {"id": e["event_ticker"], "title": e["title"], "bets": []}
            for m in e["markets"]:
                obj["bets"].append({"prompt": m["yes_sub_title"], "probability": m["last_price"] / m["notional_value"]})
            return obj

        while True:
            print(f"Fetching from kalshi @ curor={params['cursor']} ...")
            resp = requests.get(f"{BASE}/events", params=params)
            resp.raise_for_status()
            data = resp.json()
            predictions.extend(data["events"])
            params["cursor"] = data.get("cursor")
            if not params["cursor"]:
                return pl.DataFrame([simple_prediction(p) for p in predictions])


    predictions = fetch_from_kalshi()
    predictions
    return pl, predictions


@app.cell
async def _(pl, predictions):
    from pydantic_ai import Agent
    from pydantic import BaseModel, Field


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
        "  - US policies and outlook on debt, budget, tax laws, tariffs, healthcare"
        "  - General major geopolitical events that can happen near future (<5 years)"
        "  - Specific public companies mentioned like Tesla, Apple, Nvidia etc"
        "  - Major natural disasters or crisis with high (>50%) probabilities"
        "General instuctions:"
        "- Think deeply about second or third order effects"
        "- Don't restrict yourself or fixate on tickers or themes mentioned above"
        "  since these are just examples I used to give you a general idea of how I can invest"
        "</about_me>"
    )

    class RelevantPrediction(BaseModel):
        id: str = Field(description="original id from input")
        topics: list[str] = Field(description="public companies or investment sectors or broad alternatives impacted")


    relevant_prediction_agent = Agent(
        model="openai:gpt-4.1",
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
        ),
    )


    async def tag_predictions(predictions: pl.DataFrame) -> pl.DataFrame:
        relevant_predictions = await relevant_prediction_agent.run(predictions.write_json())
        relevant_predictions = pl.DataFrame(relevant_predictions.output)
        print(f"Picked {len(relevant_predictions)} relevant predictions from {len(predictions)}")
        return predictions.join(relevant_predictions, on="id", how="left")


    tagged_predictions = await tag_predictions(predictions)
    tagged_predictions
    return


app._unparsable_cell(
    r"""
    import marimo as mo
    from datetime import date


    synthesizing_agent = Agent(
        model=\"openai:o3-2025-04-16\",
        output_type=str,
        system_prompt=(
            f\"{about_me}\"
            \"<task>\"
            \"You will be provided an array of questions and probabilities from an online betting market\"
            \"Consolidate and summarize into a 1-pager investment guideline thesis report\"
            \"The provided topics column can serve as hints to explore but think deeply about 2nd and 3rd order effects\"
            \"Take into account the probabilities and the fact that the topic is being discussed in the first place\"
            \"but also keep in mind that prediction markets often have longshot bias i.e.\"
            \"people sometime tend to overweight extreme low-probability outcomes and underweight high-probability ones\"
            \"due to the non-linear probability weighting function in their model\"
            \"</task>\"
            \"<output_format>\"
            \"Present in a markdown format with sections and sub-sections\"
            \"Go from broad (e.g. macro) to narrow (e.g. sector) and finally individual names as top-level sections\"
            f\"This is intended to be consumed daily as a news memo (today's date is {date.today().strftime(\"%d-%b-%Y\")})\"
            \"So just use the title: Daily Memo (date)\"
            \"Things to avoid:\"
            \"  - Don't mention that your input was prediction markets; the reader is aware of that\"
            \"  - Avoid putting the exact probabilities from the input; just use plain English to describe the prospects\"
            \"  - Avoid general guidelines like 'review this quarterly'\"
            \"</output_format>\"
        ),
    )

    report_input = tagged_predictions.drop(\"id\").filter(pl.col(\"topics\").is_not_null())
    report = await synthesizing_agent.run(report_input.write_json())
    mo.md(report.output)


    git branch -M master
    git push -u origin master
    """,
    name="_"
)


if __name__ == "__main__":
    app.run()
