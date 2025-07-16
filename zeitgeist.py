import marimo

__generated_with = "0.14.11"
app = marimo.App(width="medium")


@app.cell
def _():
    import requests


    def fetch_kalshi():
        BASE = "https://api.elections.kalshi.com/trade-api/v2"
        params = {"status": "open", "with_nested_markets": "true", "limit": 100, "cursor": None}
        all = []
        while True:
            print(f"Fetching from kalshi @ curor={params['cursor']} ...")
            resp = requests.get(f"{BASE}/events", params=params)
            resp.raise_for_status()
            data = resp.json()
            all.extend(data["events"])
            params["cursor"] = data.get("cursor")
            if not params["cursor"]:
                print(f"Fetched {len(all)} items from kalshi")
                return all


    events = fetch_kalshi()
    return (events,)


@app.cell
def _(events):
    def parse_kalshi_event(e):
        obj = {"id": e["event_ticker"], "title": e["title"], "bets": []}
        for m in e["markets"]:
            obj["bets"].append({"prompt": m["yes_sub_title"], "probability": m["last_price"] / m["notional_value"]})
        return obj


    parse_kalshi_event(events[8])
    return


if __name__ == "__main__":
    app.run()
