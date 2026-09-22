from typing import Dict, Any
from .db import get_all_cards

CATEGORY_KEYWORDS = {
    "dining": ["restaurant", "cafe", "coffee", "bistro", "starbucks", "mcdonald", "chipotle", "doordash", "uber eats", "grubhub", "blue bottle", "sweetgreen", "shake shack"],
    "gas": ["chevron", "shell", "exxon", "mobil", "76", "bp", "speedway", "costco gas", "arco", "valero"],
    "ev_charging": ["tesla supercharger", "evgo", "electrify america", "chargepoint", "blink", "rivian"],
    "groceries": ["whole foods", "trader joe", "kroger", "safeway", "aldi", "sprouts", "heb", "publix", "wegmans", "h mart", "target"],
    "travel": ["united airlines", "delta", "american airlines", "marriott", "hilton", "hyatt", "airbnb", "uber", "lyft", "expedia", "booking.com"],
    "streaming": ["netflix", "spotify", "hulu", "disney", "apple music", "youtube premium", "hbo", "max", "peacock"]
}

def infer_category(merchant_name: str) -> str:
    merchant_lower = merchant_name.lower().strip()
    for cat, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in merchant_lower for kw in keywords):
            return cat
    return "default"

def recommend_best_card(merchant_name: str, category_override: str = None) -> Dict[str, Any]:
    category = category_override if category_override else infer_category(merchant_name)
    cards = get_all_cards()
    
    best_card = None
    max_multiplier = 0.0
    all_options = []
    
    for card in cards:
        rewards = card.get("rewards", {})
        multiplier = rewards.get(category, rewards.get("default", 1.0))
        
        # Check quarterly category bonus if applicable
        if card.get("quarterly_category") and card.get("quarterly_category").lower() == category.lower():
            multiplier = max(multiplier, 5.0)
            
        card_option = {
            "card_id": card["id"],
            "name": card["name"],
            "issuer": card["issuer"],
            "multiplier": multiplier,
            "spend_cap_monthly": card.get("spend_cap_monthly", 0),
            "notes": card.get("notes", "")
        }
        all_options.append(card_option)
        
        if multiplier > max_multiplier:
            max_multiplier = multiplier
            best_card = card_option
    
    all_options.sort(key=lambda x: x["multiplier"], reverse=True)
    
    tip = f"Swipe {best_card['name']} for {max_multiplier}x on {category.upper()} spend." if best_card else "Use standard catch-all card."
    if best_card and best_card.get("spend_cap_monthly", 0) > 0:
        tip += f" (Note: ${best_card['spend_cap_monthly']:,.0f}/mo cap on bonus rate)"
        
    return {
        "merchant": merchant_name,
        "detected_category": category,
        "recommended_card": best_card,
        "multiplier": max_multiplier,
        "all_cards_ranking": all_options,
        "tip": tip
    }
