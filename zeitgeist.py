import marimo

__generated_with = "0.14.11"
app = marimo.App(width="medium")


@app.cell
def _():
    import requests


    def fetch_kalshi(simple: bool = False):
        BASE = "https://api.elections.kalshi.com/trade-api/v2"
        params = {"status": "open", "with_nested_markets": "true", "limit": 100, "cursor": None}
        events = []
        while True:
            print(f"Fetching from kalshi @ curor={params['cursor']} ...")
            resp = requests.get(f"{BASE}/events", params=params)
            resp.raise_for_status()
            data = resp.json()
            events.extend(data["events"])
            params["cursor"] = data.get("cursor")
            if not params["cursor"]:
                print(f"Fetched {len(events)} items from kalshi")
                if simple:
                    def simple_event(e):
                        obj = {"id": e["event_ticker"], "title": e["title"], "bets": []}
                        for m in e["markets"]:
                            obj["bets"].append({"prompt": m["yes_sub_title"], "probability": m["last_price"] / m["notional_value"]})
                        return obj
                    return [simple_event(e) for e in events]
                else:
                    return events


    events = fetch_kalshi(simple=True)
    return (events,)


@app.cell
def _(events):
    events[563]
    return


@app.cell
def _():
    from pydantic_ai import Agent
    from pydantic import BaseModel, Field

    class RelevantEvent(BaseModel):
        id: str = Field(description="original id from input")
        topics: list[str] = Field(description="investment tickers or sectors to investigate")

    relevant_agent = Agent(  
        model='openai:gpt-4.1',    
        output_type=list[RelevantEvent],
        system_prompt=(
            'You will be provided an array of questions from an online betting market'
            'Your job is to return only the ids of questions relevant to me'
            'I am an American equities investor and I am interested in questions'
            'whose answers would impact the market in the relatively short term'
            'or could change how I invest'
            'Some examples of things that are unlikely to impact (unless a reason is provided):'
            '1. Celebrity gossips e.g. how many tweets would Elon tweet this month'
            '2. Sports related e.g. Would Ronaldo be traded this season'
            '3. Events far in the future: Would India host the Olympics by 2040'
            '4. Geography e.g. election results in Kiribati is unlikely to impact my US equities'
            'Examine each question and return a subset of ids and related topics they may impact'
            'Topics be few must be short strings like sectors or tickers or short phrases'
            'that would be impacted by this question'
        ),
    )
    return (relevant_agent,)


@app.cell
async def _(events, relevant_agent):
    import json

    output = await relevant_agent.run(json.dumps(events, indent=2))
    return


if __name__ == "__main__":
    app.run()
