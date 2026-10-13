"""Dimming presets; legacy temperatures are retained for stored-data compatibility."""

PRESETS = {
    "office": {
        "temp": 5500,
        "dim": 0,
        "desc": "办公方案 - 不调暗",
        "desc_en": "Office - No dimming",
    },
    "game": {
        "temp": 6200,
        "dim": 0,
        "desc": "游戏方案 - 保持清爽",
        "desc_en": "Game - Crisp display",
    },
    "movie": {
        "temp": 5000,
        "dim": 30,
        "desc": "电影方案 - 柔和调暗",
        "desc_en": "Movie - Soft dimming",
    },
    "reading": {
        "temp": 4500,
        "dim": 20,
        "desc": "阅读方案 - 轻微调暗",
        "desc_en": "Reading - Gentle dimming",
    },
    "night": {
        "temp": 3400,
        "dim": 50,
        "desc": "夜间方案 - 深度调暗",
        "desc_en": "Night - Deeper dimming",
    },
    "custom": {
        "temp": 5000,
        "dim": 0,
        "desc": "自定义模式",
        "desc_en": "Custom",
    },
}
