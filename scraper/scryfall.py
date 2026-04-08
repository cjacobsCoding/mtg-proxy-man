import requests

def get_all_sets():
    """Fetch all MTG sets from Scryfall API."""
    url = "https://api.scryfall.com/sets"
    res = requests.get(url)
    sets = res.json()["data"]
    # Filter to only digital and standard sets
    return [(s["code"], s["name"]) for s in sets if s.get("digital") is False]

def get_cards_by_set(set_code):
    """Fetch all cards from a specific set."""
    url = f"https://api.scryfall.com/cards/search?q=set:{set_code}"
    cards = []

    while url:
        res = requests.get(url)
        data = res.json()

        if "data" in data:
            cards.extend(data["data"])

        url = data.get("next_page")

    return cards