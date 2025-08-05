import asyncio
import os
import logging
import time
from datetime import datetime
from typing import Optional
import json

import discord
from discord.ext import commands
from dotenv import load_dotenv

from config import (
    GuildConfiguration, Configuration, ConfigManager, StyleManager,
    format_price
)
from quote import PriceQuoteCache

# ============== LOGGING SETUP ==================
import colorlog

log_colors = {
    'DEBUG': 'cyan', 'INFO': 'green', 'WARNING': 'yellow',
    'ERROR': 'red', 'CRITICAL': 'bold_red',
}

formatter = colorlog.ColoredFormatter(
    '%(log_color)s%(asctime)s.%(msecs)03d %(name)-12s [%(levelname)-8s] %(message)s',
    datefmt='%Y-%m-%dT%H:%M:%S',
    log_colors=log_colors,
)

logger = logging.getLogger(__name__)
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logging.getLogger().handlers.clear()
logging.getLogger().addHandler(console_handler)
logging.getLogger().setLevel(logging.INFO)
for comp in ['discord', 'discord.client', 'discord.gateway']:
    logging.getLogger(comp).setLevel(logging.INFO)
logging.getLogger('discord.http').setLevel(logging.WARNING)

# ============== CONFIG/STARTUP ==================
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN")

config_mgr, style_mgr = ConfigManager(), StyleManager()
Config: Configuration = config_mgr.load_configuration()
STYLES = style_mgr.load_styles()
PriceQuoter = PriceQuoteCache()

intents = discord.Intents.all()
bot = commands.Bot(command_prefix='!', intents=intents)
tree = bot.tree

# ============== LEADERBOARD INTEGRATION ==================
from discord import Embed, TextChannel

LEADERBOARD_CHANNELS_FILE = "leaderboard_channels.json"

def load_leaderboard_channels():
    try:
        with open(LEADERBOARD_CHANNELS_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_leaderboard_channels(channels):
    with open(LEADERBOARD_CHANNELS_FILE, "w") as f:
        json.dump(channels, f, indent=2)

async def get_top_tickers():
    ticker_guilds = {}
    for gid, g in Config.guilds.items():
        tickers = set()
        if getattr(g, "voice_tickers", None):
            tickers |= set([t.upper() for t in g.voice_tickers])
        if getattr(g, "message_tickers", None):
            tickers |= set([t.upper() for t in g.message_tickers.keys()])
        if getattr(g, "ratio_tickers", None):
            for pair in g.ratio_tickers.keys():
                for t in pair.split(":"):
                    tickers.add(t.upper())
        for t in tickers:
            ticker_guilds.setdefault(t, set()).add(gid)
    leaderboard = sorted(
        [(t, len(gids)) for t, gids in ticker_guilds.items()],
        key=lambda x: (-x[1], x[0])
    )
    return leaderboard[:10]

async def make_leaderboard_embed():
    lb = await get_top_tickers()
    embed = Embed(
        title=":trophy: Most-Saved Tickers Leaderboard",
        description="Top 10 most-added tickers (across all servers).",
        color=discord.Color.gold()
    )
    for idx, (ticker, count) in enumerate(lb, 1):
        embed.add_field(
            name=f"{idx}. {ticker}",
            value=f"Saved in **{count}** server{'s' if count!=1 else ''}",
            inline=False
        )
    if not lb:
        embed.add_field(name="No tickers.", value="No tickers are currently tracked.", inline=False)
    return embed

async def send_or_update_ticker_leaderboard(guild, channel):
    channels = load_leaderboard_channels()
    entry = channels.get(str(guild.id), {})
    message_id = entry.get("message_id")
    embed = await make_leaderboard_embed()
    msg = None
    if message_id:
        try:
            msg = await channel.fetch_message(message_id)
            await msg.edit(embed=embed, content=None)
        except Exception:
            msg = None
    if not msg:
        msg = await channel.send(embed=embed)
    channels[str(guild.id)] = {"channel_id": channel.id, "message_id": msg.id}
    save_leaderboard_channels(channels)
    return msg

# ============== HELPERS/DECORATORS ===============
def is_admin_check():
    async def predicate(ctx):
        gid = getattr(ctx.guild, "id", None) or ctx.guild_id
        user = ctx.user if hasattr(ctx, 'user') else ctx.author
        if user.guild_permissions.administrator:
            return True
        gconf = Config.guilds.get(gid)
        if gconf and gconf.admin_role_id:
            return any(getattr(r, "id", 0) == gconf.admin_role_id for r in getattr(user, "roles", []))
        await ctx.response.send_message("Admin or configured role required.", ephemeral=True)
        return False
    return commands.check(predicate)

async def verify_ticker_exists(api_key: str, ticker: str) -> bool:
    return bool(await PriceQuoter.fetch_no_cache(api_key, [ticker]))

def guild_has_api_key(guild_id: int) -> bool:
    g = Config.guilds.get(guild_id)
    return bool(g and g.cmc_api_key)

def get_guild_conf(ctx) -> Optional[GuildConfiguration]:
    gid = getattr(ctx.guild, "id", None) or ctx.guild_id
    return Config.guilds.get(gid)

# ================ UPDATE/UTILITY ================

async def update_voice_channels():
    logger.info("🎤 Voice updates for all guilds")
    for g in Config.guilds.values():
        if not (g.voice_update_category and g.voice_tickers and g.cmc_api_key):
            continue
        guild = bot.get_guild(g.id)
        cat = discord.utils.get(guild.categories, id=g.voice_update_category) if guild else None
        if not (guild and cat): continue
        quotes = await PriceQuoter.fetch(g.cmc_api_key, g.voice_tickers, time.time())
        sorted_quotes = sorted(quotes, key=lambda q: q.market_cap or 0, reverse=True)
        # Remove all existing, then create
        for ch in list(cat.voice_channels): await ch.delete()
        for q in sorted_quotes:
            emoji = STYLES['price_up_icon'] if q.percent_change_1h >= 0 else STYLES['price_down_icon']
            await cat.create_voice_channel(name=f"{q.symbol} {emoji} {format_price(q.price_usd)}")

async def update_message_tickers(regular: bool = True, ratio: bool = True):
    for g in Config.guilds.values():
        if not g.cmc_api_key: continue
        guild = bot.get_guild(g.id)
        if not guild: continue
        if regular and g.message_tickers: await update_regular_tickers(g, guild)
        if ratio and g.ratio_tickers: await update_ratio_tickers(g, guild)

async def update_regular_tickers(g: GuildConfiguration, guild):
    syms = list(g.message_tickers.keys())
    quotes = await PriceQuoter.fetch(g.cmc_api_key, syms, time.time())
    q_by_sym = {q.symbol: q for q in quotes}
    for sym, cid in g.message_tickers.items():
        ch = guild.get_channel(cid)
        if not (ch and q_by_sym.get(sym)):
            continue
        q = q_by_sym[sym]
        coin_url = f"https://coinmarketcap.com/currencies/{getattr(q, 'slug', q.symbol.lower())}/"
        base_url = "https://coinmarketcap.com/"
        sym_link = f"[{sym}](<{coin_url}>)"
        cmc_link = f"[CMC](<{base_url}>)"
        await ch.send(
            f"The price of {q.name} ({sym_link}) is ${q.price_usd:.2f} USD on {cmc_link}"
        )

async def update_ratio_tickers(g: GuildConfiguration, guild):
    for pair, cid in g.ratio_tickers.items():
        t1, t2 = pair.split(":")
        quotes = await PriceQuoter.fetch(g.cmc_api_key, [t1, t2], time.time())
        qd = {q.symbol: q for q in quotes}
        if t1 in qd and t2 in qd:
            ch = guild.get_channel(cid)
            q1 = qd[t1]
            q2 = qd[t2]

            def cmc_url(q, symbol):
                return f"https://coinmarketcap.com/currencies/{getattr(q, 'slug', symbol.lower())}/"

            t1_link = f"[{t1}](<{cmc_url(q1, t1)}>)"
            t2_link = f"[{t2}](<{cmc_url(q2, t2)}>)"
            pair_link = f"{t1_link}:{t2_link}"
            base_cmc_link = f"https://coinmarketcap.com/currencies/{getattr(q2, 'slug', t2.lower())}/"
            cmc_anchor = f"[CMC](<{base_cmc_link}>)"

            try:
                ratio = int(q2.price_usd / q1.price_usd)
            except (ZeroDivisionError, TypeError):
                ratio = "N/A"
            await ch.send(
                f"The swap rate of {pair_link} is {ratio}:1 on {cmc_anchor}"
            )

# ============ CLOCK-BOUNDARY UPDATE LOOPS ============

async def wait_for_boundary(interval: int, name: str):
    now = time.time()
    next_boundary = interval - (now % interval)
    logger.info("⏰ Waiting %.1f seconds until next %s update", next_boundary, name)
    await asyncio.sleep(next_boundary)
    while bot.is_closed():
        logger.warning("⚠️ Client disconnected, retrying %s update in 3 minutes", name)
        await asyncio.sleep(180)

async def voice_update_loop():
    logger.info("🎤 Voice update loop initialized")
    await bot.wait_until_ready()
    while True:
        await wait_for_boundary(3600, "voice channel")
        await update_voice_channels()

async def message_update_loop():
    logger.info("💬 Message update loop initialized")
    await bot.wait_until_ready()
    while True:
        await wait_for_boundary(1800, "message ticker")
        await update_message_tickers()

async def ticker_leaderboard_update_loop():
    logger.info("🏆 Ticker leaderboard update loop initialized")
    await bot.wait_until_ready()
    while True:
        await wait_for_boundary(3600, "ticker leaderboard")
        logger.info("🏆 Updating ticker leaderboards for all guilds")
        channels = load_leaderboard_channels()
        for gid_str, entry in channels.items():
            try:
                guild = bot.get_guild(int(gid_str))
                if not guild:
                    continue
                ch = guild.get_channel(entry["channel_id"])
                if not isinstance(ch, TextChannel):
                    continue
                await send_or_update_ticker_leaderboard(guild, ch)
            except Exception as e:
                logger.warning(f"Could not update leaderboard for guild {gid_str}: {e}")

# ============== COMMANDS / SLASH TREE ===============

@tree.command(name="set_cmc_api_key", description="Set this server's CMC API key")
@is_admin_check()
async def set_cmc_api_key(ctx, api_key: str):
    api_key = api_key.strip()
    if len(api_key) < 10 or not await verify_ticker_exists(api_key, "BTC"):
        await ctx.response.send_message("Invalid or unaccepted API key.", ephemeral=True)
        return
    g = Config.get_or_create_guild(ctx.guild_id)
    g.cmc_api_key = api_key
    config_mgr.save_configuration(Config)
    await ctx.response.send_message("API key saved and validated.", ephemeral=True)

@tree.command(name="remove_cmc_api_key", description="Remove CMC API key")
@is_admin_check()
async def remove_cmc_api_key(ctx):
    g = get_guild_conf(ctx)
    if g and g.cmc_api_key:
        g.cmc_api_key = None
        config_mgr.save_configuration(Config)
        await ctx.response.send_message("API key removed.", ephemeral=True)
    else:
        await ctx.response.send_message("No API key set.", ephemeral=True)

@tree.command(name="set_admin_role", description="Set admin role")
@is_admin_check()
async def set_admin_role(ctx, role_id: str):
    try:
        role = ctx.guild.get_role(int(role_id))
        if not role: raise ValueError
        g = Config.get_or_create_guild(ctx.guild_id)
        g.admin_role_id = role.id
        config_mgr.save_configuration(Config)
        await ctx.response.send_message(
            f"Admin role set to {role.mention}.", ephemeral=True)
    except:
        await ctx.response.send_message("Invalid role ID.", ephemeral=True)

@tree.command(name="set_voice_voice_update_category", description="Set update category for voice tickers")
@is_admin_check()
async def set_voice_voice_update_category(ctx, category_id: str):
    try:
        cat = discord.utils.get(ctx.guild.categories, id=int(category_id))
        if not cat: raise ValueError
        g = Config.get_or_create_guild(ctx.guild_id)
        g.voice_update_category = cat.id
        g.voice_tickers.clear()
        config_mgr.save_configuration(Config)
        await ctx.response.send_message(f"Update category set to **{cat.name}**", ephemeral=True)
    except:
        await ctx.response.send_message("Invalid category ID.", ephemeral=True)

@tree.command(name="add_voice_ticker", description="Add a voice price ticker")
@is_admin_check()
async def add_voice_ticker(ctx, ticker: str):
    ticker = ticker.upper()
    g = get_guild_conf(ctx)
    if not (g and g.voice_update_category and g.cmc_api_key):
        await ctx.response.send_message(
            "Set update category and CMC API key first.", ephemeral=True
        )
        return
    if not await verify_ticker_exists(g.cmc_api_key, ticker):
        await ctx.response.send_message(f"Ticker {ticker} not found.", ephemeral=True)
        return
    if ticker not in g.voice_tickers:
        g.voice_tickers.append(ticker)
        config_mgr.save_configuration(Config)
        await update_voice_channels()
        await ctx.response.send_message(f"Added {ticker} to updates.", ephemeral=True)
    else:
        await ctx.response.send_message(f"{ticker} already tracked.", ephemeral=True)

@tree.command(name="remove_voice_ticker", description="Remove voice ticker")
@is_admin_check()
async def remove_voice_ticker(ctx, ticker: str):
    ticker = ticker.upper()
    g = get_guild_conf(ctx)
    if g and ticker in g.voice_tickers:
        g.voice_tickers.remove(ticker)
        config_mgr.save_configuration(Config)
        await update_voice_channels()
        await ctx.response.send_message(f"Removed {ticker}.", ephemeral=True)
    else:
        await ctx.response.send_message(f"{ticker} not tracked.", ephemeral=True)

@tree.command(name="add_message_ticker", description="Add message price updates")
@is_admin_check()
async def add_message_ticker(ctx, ticker: str, channel_id: str):
    ticker, cid = ticker.upper(), int(channel_id)
    g = get_guild_conf(ctx)
    ch = ctx.guild.get_channel(cid)
    if not (g and g.cmc_api_key and ch):
        await ctx.response.send_message("Check API key and channel.", ephemeral=True)
        return
    if not await verify_ticker_exists(g.cmc_api_key, ticker):
        await ctx.response.send_message(f"Ticker {ticker} not found.", ephemeral=True)
        return
    g.message_tickers[ticker] = cid
    config_mgr.save_configuration(Config)
    await ctx.response.send_message(f"Added {ticker} to #{ch.name}.", ephemeral=True)

@tree.command(name="remove_message_ticker", description="Remove a message price ticker from a specific channel")
@is_admin_check()
async def remove_message_ticker(ctx, ticker: str, channel_id: str):
    ticker = ticker.upper()
    cid = int(channel_id)
    g = get_guild_conf(ctx)
    if g:
        if ticker in g.message_tickers and g.message_tickers[ticker] == cid:
            del g.message_tickers[ticker]
            config_mgr.save_configuration(Config)
            await ctx.response.send_message(f"Removed {ticker} from <#{cid}>.", ephemeral=True)
        else:
            await ctx.response.send_message(f"{ticker} is not tracked in <#{cid}>.", ephemeral=True)
    else:
        await ctx.response.send_message("No config for this guild.", ephemeral=True)

@tree.command(name="add_message_ratio_tickers", description="Add a ticker ratio for messages")
@is_admin_check()
async def add_message_ratio_tickers(ctx, ticker1: str, ticker2: str, channel_id: str):
    t1, t2, cid = ticker1.upper(), ticker2.upper(), int(channel_id)
    g = get_guild_conf(ctx)
    ch = ctx.guild.get_channel(cid)
    if not (g and g.cmc_api_key and ch):
        await ctx.response.send_message("Check API key and channel.", ephemeral=True)
        return
    data = await PriceQuoter.fetch_no_cache(g.cmc_api_key, [t1, t2])
    have = {q.symbol for q in data}
    if t1 not in have or t2 not in have:
        await ctx.response.send_message(f"One or both tickers invalid.", ephemeral=True)
        return
    g.ratio_tickers[f"{t1}:{t2}"] = cid
    config_mgr.save_configuration(Config)
    await ctx.response.send_message(f"Added {t1}:{t2} to #{ch.name}.", ephemeral=True)

@tree.command(name="remove_message_ratio_tickers", description="Remove a ratio pair from a specific channel")
@is_admin_check()
async def remove_message_ratio_tickers(ctx, ticker1: str, ticker2: str, channel_id: str):
    t1, t2, cid = ticker1.upper(), ticker2.upper(), int(channel_id)
    pair = f"{t1}:{t2}"
    g = get_guild_conf(ctx)
    if g:
        if pair in g.ratio_tickers and g.ratio_tickers[pair] == cid:
            del g.ratio_tickers[pair]
            config_mgr.save_configuration(Config)
            await ctx.response.send_message(f"Removed {pair} from <#{cid}>.", ephemeral=True)
        else:
            await ctx.response.send_message(f"{pair} is not tracked in <#{cid}>.", ephemeral=True)
    else:
        await ctx.response.send_message("No config for this guild.", ephemeral=True)

@tree.command(name="show_settings", description="Show this server's config")
@is_admin_check()
async def show_settings(ctx):
    g = get_guild_conf(ctx)
    embed = discord.Embed(
        title="Crypto Bot Settings",
        description=f"Current settings for **{ctx.guild.name}**",
        color=discord.Color.blue(),
        timestamp=datetime.now()
    )
    if bot.user and bot.user.avatar:
        embed.set_thumbnail(url=bot.user.avatar.url)
    if not g:
        embed.add_field(name="Status", value="No settings configured.", inline=False)
    else:
        ak = g.cmc_api_key
        api_key_disp = f"✅ ...{ak[-4:]}" if ak else "❌ Not configured"
        embed.add_field(name="CoinMarketCap API Key", value=api_key_disp, inline=False)
        # Admin role
        if g.admin_role_id:
            role = ctx.guild.get_role(g.admin_role_id)
            val = f"**{role.name}** ({g.admin_role_id})" if role else f"ID {g.admin_role_id} (deleted)"
        else:
            val = "Not configured"
        embed.add_field(name="Admin Role", value=val, inline=False)
        # Category
        if g.voice_update_category:
            cat = discord.utils.get(ctx.guild.categories, id=g.voice_update_category)
            cname = cat.name if cat else "Unknown (deleted)"
            embed.add_field(name="Update Category", value=f"{cname} ({g.voice_update_category})", inline=False)
        # Tickers
        vt = ", ".join(g.voice_tickers) if g.voice_tickers else "None"
        embed.add_field(name="Voice Tickers", value=vt, inline=False)
        if g.message_tickers:
            mt = '\n'.join([f"{k}→#{ctx.guild.get_channel(cid).name if ctx.guild.get_channel(cid) else cid}"
                            for k, cid in g.message_tickers.items()])
            embed.add_field(name="Message Tickers", value=mt, inline=False)
        if g.ratio_tickers:
            rt = '\n'.join([f"{pair}→#{ctx.guild.get_channel(cid).name if ctx.guild.get_channel(cid) else cid}"
                            for pair, cid in g.ratio_tickers.items()])
            embed.add_field(name="Ratio Tickers", value=rt, inline=False)
    await ctx.response.send_message(embed=embed, ephemeral=True)

# == Convenience force-update commands
def update_wrap(method, **kwargs):
    async def inner(ctx):
        if not guild_has_api_key(ctx.guild_id):
            await ctx.response.send_message("Set API key first.", ephemeral=True)
            return
        await ctx.response.send_message("Updating...", ephemeral=True)
        await method(**kwargs)
    return inner

tree.command(name="force_update_voice_tickers", description="Force update all voice channels")(
    is_admin_check()(update_wrap(update_voice_channels))
)
tree.command(name="force_update_message_tickers", description="Force update message tickers")(
    is_admin_check()(update_wrap(update_message_tickers, regular=True, ratio=False))
)
tree.command(name="force_update_ratio_tickers", description="Force update ratio tickers")(
    is_admin_check()(update_wrap(update_message_tickers, regular=False, ratio=True))
)

@tree.command(name="remove_admin_role", description="Remove configured admin role")
@is_admin_check()
async def remove_admin_role(ctx):
    g = get_guild_conf(ctx)
    if g and g.admin_role_id:
        g.admin_role_id = None
        config_mgr.save_configuration(Config)
        await ctx.response.send_message("Admin role removed. Only admins can use admin commands now.", ephemeral=True)
    else:
        await ctx.response.send_message("No admin role configured.", ephemeral=True)

# ============== TICKER LEADERBOARD COMMAND ===========
@tree.command(name="add_ticker_leaderboard", description="Set a channel as this server's Ticker Leaderboard destination")
@is_admin_check()
async def add_ticker_leaderboard(ctx, channel_id: str):
    try:
        cid = int(channel_id)
        ch = ctx.guild.get_channel(cid)
        if not isinstance(ch, TextChannel):
            raise ValueError
    except Exception:
        await ctx.response.send_message("Invalid channel ID (must be a text channel).", ephemeral=True)
        return
    channels = load_leaderboard_channels()
    channels[str(ctx.guild_id)] = {"channel_id": cid}
    save_leaderboard_channels(channels)
    await ctx.response.send_message(f"Leaderboard will be sent/updated in <#{cid}>.", ephemeral=True)
    msg = await send_or_update_ticker_leaderboard(ctx.guild, ch)
    channels[str(ctx.guild_id)]["message_id"] = msg.id
    save_leaderboard_channels(channels)

# ============= MAIN BOT EVENT & STARTUP ======================
@bot.event
async def on_ready():
    await tree.sync()
    logger.info("Bot ready and slash commands synced")
    # Start update loops (clock-aligned)
    if not hasattr(bot, "voice_update_task"):
        bot.voice_update_task = asyncio.create_task(voice_update_loop())
    if not hasattr(bot, "message_update_task"):
        bot.message_update_task = asyncio.create_task(message_update_loop())
    if not hasattr(bot, "ticker_leaderboard_update_task"):
        bot.ticker_leaderboard_update_task = asyncio.create_task(ticker_leaderboard_update_loop())

if __name__ == "__main__":
    logger.info("🚀 Starting Crypto Bot ...")
    try:
        bot.run(DISCORD_TOKEN, log_handler=None)
    except Exception as e:
        logger.critical("❌ Failed to start bot: %s", str(e))
        raise
