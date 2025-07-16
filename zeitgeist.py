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
    events[0]
    return


@app.cell
def _():
    return


if __name__ == "__main__":
    app.run()
