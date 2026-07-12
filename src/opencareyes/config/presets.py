"""Preset mode definitions."""

PRESETS = {
    "office": {
        "temp": 5500,
        "dim": 0,
        "desc": "办公模式 - 轻度过滤",
        "desc_en": "Office - Light filtering",
    },
    "game": {
        "temp": 6200,
        "dim": 0,
        "desc": "游戏模式 - 最小过滤",
        "desc_en": "Game - Minimal filtering",
    },
    "movie": {
        "temp": 5000,
        "dim": 30,
        "desc": "电影模式 - 中度暖色",
        "desc_en": "Movie - Moderate warm",
    },
    "reading": {
        "temp": 4500,
        "dim": 20,
        "desc": "阅读模式 - 暖色护眼",
        "desc_en": "Reading - Warm eye care",
    },
    "night": {
        "temp": 3400,
        "dim": 50,
        "desc": "夜间模式 - 强力过滤",
        "desc_en": "Night - Strong filtering",
    },
    "custom": {
        "temp": 5000,
        "dim": 0,
        "desc": "自定义模式",
        "desc_en": "Custom",
    },
}
