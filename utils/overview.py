import json

OVERVIEW_CONFIG_KEYS = [
    ("ADMIN_ROLE_IDS", "Admin Roles", "role_list"),
    ("ADMIN_ROLE_ID", "Admin Role (legacy, single-role)", "role"),
    ("VERIFIED_ROLE_ID", "Verified Role", "role"),
    ("TICKET_CATEGORY_ID", "Ticket Category", "channel"),
    ("TICKET_TRANSCRIPT_CHANNEL_ID", "Ticket Transcript Channel", "channel"),
    ("TICKET_PANEL_CHANNEL_ID", "Ticket Panel", "channel"),
    ("WELCOME_CHANNEL_ID", "Welcome Channel", "channel"),
    ("RULES_CHANNEL_ID", "Rules Channel", "channel"),
    ("LOG_CHANNEL_ID", "Log Channel", "channel"),
    ("LEADERBOARD_CHANNEL_ID", "Leaderboard Panel", "channel"),
    ("POLL_CHANNEL_ID", "Poll Channel", "channel"),
    ("INVITE_EXCLUSIVE_CHANNEL_ID", "Invite Exclusive Chat", "channel"),
    ("INVITE_REWARDS_CHANNEL_ID", "Invite Rewards Channel", "channel"),
    ("INVITE_BASIC_ROLE_ID", "Basic Inviter Role", "role"),
    ("INVITE_COPPER_ROLE_ID", "Copper Inviter Role", "role"),
    ("INVITE_IRON_ROLE_ID", "Iron Inviter Role", "role"),
    ("INVITE_GOLD_ROLE_ID", "Gold Inviter Role", "role"),
    ("INVITE_VIP_ROLE_ID", "VIP Role", "role"),
]


def resolve_overview_value(guild, kind: str, raw_value):
    """Turn a stored config value into something readable, using live
    guild data to resolve IDs to names where possible. Returns None
    for a "role_list" that's set but empty (nothing worth showing)."""
    if kind == "role_list":
        try:
            role_ids = json.loads(raw_value)
        except (TypeError, ValueError):
            return str(raw_value)
        if not role_ids:
            return None
        names = []
        for rid in role_ids:
            role = guild.get_role(rid)
            names.append(f"{role.name} ({rid})" if role else f"{rid} (not found)")
        return ", ".join(names)

    try:
        value_int = int(raw_value)
    except (TypeError, ValueError):
        return f"{raw_value}"

    if kind == "channel":
        channel = guild.get_channel(value_int)
        return f"Channel: {channel.name} ({value_int})" if channel else f"Channel: {value_int} (not found)"
    if kind == "role":
        role = guild.get_role(value_int)
        return f"Role: {role.name} ({value_int})" if role else f"Role: {value_int} (not found)"
    return f"{value_int}"
