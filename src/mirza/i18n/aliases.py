"""i18n key-alias map: rewrite call-sites → legacy corpus keys.

The rewrite uses a few clean names; the legacy corpus (2,386 strings/lang,
admin-editable) keeps the original PHP keys. This map resolves rewrite
keys to legacy paths without touching every handler.
"""
ALIASES: dict[str, str] = {
    # rewrite additions first (exact)
    "users.blocked": "rewrite.blocked",
    "users.services.config": "rewrite.services.config",
    "users.services.changeloc": "rewrite.services.changeloc",
    "users.wallet.topup_prompt": "rewrite.wallet.topup_prompt",
    # legacy-corpus bindings (admin-editable via bottext UI like the PHP)
    "users.Balance.insufficientBalance": "users.Balance.insufficientbalance",
    "users.Balance.giftDeposit": "users.Balance.addedNotice",
    "users.mainMenu.text_sell": "textbot.sell",
    "users.mainMenu.text_extend": "textbot.extend",
    "users.mainMenu.help": "textbot.help",
    "users.mainMenu.accountwallet": "textbot.accountWallet",
    "users.mainMenu.affiliates": "textbot.affiliates",
    "users.mainMenu.usertest": "common.labels.testServiceName",
    "users.mainMenu.wheelLuck": "textbot.wheelLuck",
    "users.mainMenu.purchasedServices": "textbot.purchasedServices",
    "users.mainMenu.support": "textbot.support",
    "users.mainMenu.tariff": "textbot.tariffList",
    "users.start": "users.text_start",
}
