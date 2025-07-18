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


    class RelevantPrediction(BaseModel):
        id: str = Field(description="original id from input")
        topics: list[str] = Field(description="public companies or investment sectors impacted")


    relevant_prediction_agent = Agent(
        model="openai:gpt-4.1",
        output_type=list[RelevantPrediction],
        system_prompt=(
            "You will be provided an array of questions from an online betting market"
            "Your job is to return only the ids of questions relevant to me"
            "I am an American equities investor and I am interested in questions"
            "whose answers would impact the market in the relatively short term or could change how I invest"
            "Besides publicly listed equities, I can have exposure to borad indices (e.g. $SPY and $QQQ)"
            "sectors (e.g. defense - $XAR, healthcare -  $XLV)"
            "and alternatives like gold, energy, commodities, crypto, bonds, TIPS, REITs, mortgage-backed securities etc"
            "through ETFs/vehicles like $IAU, $DBC, $BTC, $ZROZ, $TIPZ, $VNQ etc"
            "so pay particular attention to macroeconomic themes"
            "Some examples of things that are UNLIKELY to impact (unless a good reason is provided):"
            "  - Celebrity gossips e.g. how many tweets would Elon tweet this month"
            "  - Sports related e.g. Would Ronaldo be traded this season"
            "  - Events far (10+ years) in the future: Would India host the Olympics by 2040"
            "  - Geography e.g. election results in Kiribati is unlikely to impact my investments"
            "    but major economies like Chinese, India, EU, MEA politics is likely to impact"
            "  - Media e.g. what song will be in top billboard this week"
            "  - Ignore memecoins and NFTs (but focus on major crypto themes like BTC, solana and ethereum etc)"
            "  - Ignore essentially gambling bets on short term prices e.g. what will be USD/JPY today at 12pm"
            "Some examples of things that are LIKELY to impact my investments:"
            "  - Short term macroeconomic indicators like GDP, unemployment, CPI, trade deficit etc."
            "  - Public or private companies suing each other or M&A activities"
            "  - Foreign politics that would affect USD rates with major international currencies like JPY,CNY,EUR etc"
            "  - EV/climate legislatation and goals in short term (<5 years)"
            "  - US policies and outlook on debt, budget, tax laws, tariffs, healthcare"
            "  - General major geopolitical events that can happen near future (<5 years)"
            "  - Specific public companies mentioned like Tesla, Apple, Nvidia etc"
            "  - Major natural disasters or crisis with high (>50%) probabilities"
            "Examine each question and return a subset of ids and related topics they may impact"
            "Topics be few must be short strings like sectors or tickers or short phrases that would be impacted by this question"
            "Think about second order implications of the questions too"
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


if __name__ == "__main__":
    app.run()
