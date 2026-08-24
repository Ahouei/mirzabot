"""New strings introduced by the rewrite (not present in legacy corpora).

Merged over the legacy tables at import time; legacy keys win on collision
so admin-customized texts keep priority.
"""

STRINGS = {
    "en": {
        "rewrite": {
            "blocked": "🚫 You are blocked from using this bot.",
            "services": {
                "config": "config:",
                "changeloc": "📍 change location",
                "extend_prompt": "🔄 send days to add:",
            },
            "wallet": {"topup_prompt": "💵 send the amount to top up:"},
        },
    },
    "fa": {
        "rewrite": {
            "blocked": "🚫 دسترسی شما به این ربات مسدود شده است.",
            "services": {
                "config": "کانفیگ:",
                "changeloc": "📍 تغییر لوکیشن",
                "extend_prompt": "🔄 تعداد روز برای تمدید را بفرست:",
            },
            "wallet": {"topup_prompt": "💵 مبلغ شارژ کیف پول را بفرست:"},
        },
    },
    "ru": {
        "rewrite": {
            "blocked": "🚫 Вам заблокирован доступ к этому боту.",
            "services": {
                "config": "конфиг:",
                "changeloc": "📍 сменить локацию",
                "extend_prompt": "🔄 отправьте число дней:",
            },
            "wallet": {"topup_prompt": "💵 отправьте сумму пополнения:"},
        },
    },
    "zh": {
        "rewrite": {
            "blocked": "🚫 您已被禁止使用此机器人。",
            "services": {
                "config": "配置：",
                "changeloc": "📍 更改位置",
                "extend_prompt": "🔄 请发送续费天数：",
            },
            "wallet": {"topup_prompt": "💵 请发送充值金额："},
        },
    },
}
