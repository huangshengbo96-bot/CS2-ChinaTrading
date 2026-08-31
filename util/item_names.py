"""
Shared item-name utilities: English <-> Chinese <-> BUFF goods_id mapping.

The mapping table lives in config/items_mapping.json (generated from BUFF):
    { "market_hash_name": {"goods_id": int, "name_cn": str, "short_name_cn": str} }

CN_ALIASES here is the shared Chinese-alias table used by the NGA sentiment
source to match English tickers against Chinese forum posts.
"""

import os
import json
from typing import Dict, List, Optional

_MAPPING_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config", "items_mapping.json",
)

# Chinese aliases used to match NGA (Chinese) posts against English tickers.
CN_ALIASES = {
    "AK-47": ["AK", "AK47", "AK 47", "ak", "卡拉什"],
    "AWP": ["awp", "大狙", "鸟狙", "aw"],
    "Desert Eagle": ["沙鹰", "deagle", "DE"],
    "M4A4": ["M4", "m4"],
    "M4A1-S": ["M4A1", "消音", "m4a1"],
    "Redline": ["红线"],
    "Asiimov": ["二西莫夫", "二西"],
    "Bloodsport": ["血腥运动", "血运"],
    "Neo-Noir": ["黑色魅影", "新黑色", "黑幻"],
    "Printstream": ["印花集", "印花"],
    "Mecha Industries": ["机械工业", "机械"],
    "Hyper Beast": ["暴怒野兽", "野兽"],
    "Desolate Space": ["死寂空间", "荒芜空间", "荒芜"],
    "Dragon King": ["龙王", "龙"],
    "Decimator": ["毁灭者", "屠戮者"],
    "Leaded Glass": ["破碎铅秋", "铅玻璃", "铅"],
    "Dreams & Nightmares": ["梦魇", "梦境与噩梦", "噩梦"],
    "Broken Fang": ["狂牙"],
    "Riptide": ["激流"],
    "Wildfire": ["野火"],
    "Glove Case": ["手套武器箱", "手套箱", "手套"],
    "Operation": ["行动", "大行动"],
    "Sticker": ["印花", "贴纸"],
    "Case": ["武器箱", "箱子", "箱"],
    "Holo": ["全息"],
    "Foil": ["闪亮", "箔"],
    "FaZe Clan": ["faze", "法泽"],
    "Team Liquid": ["液体", "liquid"],
    "Paris 2023": ["巴黎2023", "巴黎 2023", "巴黎", "2023年巴黎锦标赛"],
    "Bolt Energy": ["闪电能量"],
    "Taste Buddy": ["气味相投", "味道"],
    "Hypnoteyes": ["催眠之眼", "催眠"],
    "Factory New": ["崭新", "崭新出厂"],
    "Field-Tested": ["久经沙场", "久经"],
    "Minimal Wear": ["略有磨损", "略磨"],
    "Well-Worn": ["破损不堪", "破损"],
    "Battle-Scarred": ["战痕累累", "战痕"],
}


def load_items_mapping() -> Dict:
    """Load config/items_mapping.json; returns {} if missing or invalid."""
    if not os.path.exists(_MAPPING_PATH):
        return {}
    try:
        with open(_MAPPING_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


_ITEMS_MAPPING = load_items_mapping()


def get_goods_id(market_hash_name: str) -> Optional[int]:
    """Get the BUFF goods_id for an item (from the mapping table)."""
    entry = _ITEMS_MAPPING.get(market_hash_name)
    if entry and entry.get("goods_id"):
        return int(entry["goods_id"])
    return None


def get_name_cn(market_hash_name: str) -> str:
    """Get the Chinese BUFF name for an item."""
    entry = _ITEMS_MAPPING.get(market_hash_name) or {}
    return entry.get("name_cn") or ""


def get_aliases_cn(market_hash_name: str) -> List[str]:
    """Collect Chinese aliases for an item: from its CN name tokens + shared alias table.

    Used by the NGA sentiment matcher to broaden keyword hits.
    """
    aliases = []
    ticker_lower = market_hash_name.lower()

    # 1) aliases from the shared table for matching English tokens
    for en, alias_list in CN_ALIASES.items():
        if en.lower() in ticker_lower:
            aliases.extend(alias_list)

    # 2) Chinese name itself (e.g. "AK-47 | 二西莫夫 (崭新出厂)")
    name_cn = get_name_cn(market_hash_name)
    if name_cn:
        aliases.append(name_cn)
        # strip parenthetical wear like (崭新出厂) -> keep base CN name
        base_cn = name_cn.split("(")[0].strip()
        if base_cn:
            aliases.append(base_cn)

    # deduplicate, keep order
    seen = set()
    result = []
    for a in aliases:
        a = a.strip()
        if a and a.lower() not in seen:
            seen.add(a.lower())
            result.append(a)
    return result
