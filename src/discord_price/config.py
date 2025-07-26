from typing import Optional, List, Dict
from dataclasses import dataclass, field
import json
import logging

logger = logging.getLogger(__name__)

@dataclass
class GuildConfiguration:
    """Config for a single Discord guild/server."""
    id: int  # Guild/server ID
    update_category: Optional[int] = None  # Voice update category ID
    admin_role_id: Optional[int] = None    # Custom admin role ID
    cmc_api_key: Optional[str] = None      # Guild's CoinMarketCap API key
    voice_tickers: List[str] = field(default_factory=list)             # Voice ticker list
    ratio_tickers: Dict[str, int] = field(default_factory=dict)        # Ratio ticker pairs:channel IDs
    message_tickers: Dict[str, int] = field(default_factory=dict)      # Price tickers:channel IDs

@dataclass
class Configuration:
    """Holds all-guilds' configs. Use get_or_create_guild() for safe access."""
    guilds: Dict[int, GuildConfiguration]
    def get_or_create_guild(self, guild_id: int) -> GuildConfiguration:
        """Get/insert if missing; always returns current config."""
        if guild_id not in self.guilds:
            self.guilds[guild_id] = GuildConfiguration(id=guild_id)
        return self.guilds[guild_id]

class ConfigManager:
    """Load/save all config to JSON, including per-guild settings."""
    def __init__(self, data_file: str = "crypto_bot_data.json"):
        self.data_file = data_file

    @staticmethod
    def _loads_int_map(d: Dict) -> Dict[str, int]:
        """Convert all dict values to int (for channel/role/category IDs) after loading JSON."""
        return {k: int(v) for k, v in d.items()}

    @staticmethod
    def _dumps_int_map(d: Dict[str, int]) -> Dict[str, str]:
        """Convert all dict values to str for JSON."""
        return {k: str(v) for k, v in d.items()}

    def _load_json(self) -> dict:
        """Load config file if exists, else blank dict."""
        try:
            with open(self.data_file, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save_json(self, data: dict):
        """Save nice-formatted config JSON."""
        with open(self.data_file, 'w') as f:
            json.dump(data, f, indent=4)

    def load_configuration(self) -> Configuration:
        """Load from file, convert all fields, and rehydrate into dataclasses."""
        logger.info("📁 Loading configuration from %s", self.data_file)
        data = self._load_json()
        guilds = {}
        for gid_str, gdat in data.items():
            gid = int(gid_str)
            guilds[gid] = GuildConfiguration(
                id=gid,
                update_category=(int(gdat['update_category']) if gdat.get('update_category') else None),
                admin_role_id=(int(gdat['admin_role_id']) if gdat.get('admin_role_id') else None),
                cmc_api_key=gdat.get('cmc_api_key'),
                voice_tickers=gdat.get('voice_tickers', []),
                ratio_tickers=self._loads_int_map(gdat.get('ratio_tickers', {})),
                message_tickers=self._loads_int_map(gdat.get('message_tickers', {}))
            )
        cfg = Configuration(guilds=guilds)
        logger.info("✅ Loaded %d guild configs", len(cfg.guilds))
        return cfg

    def save_configuration(self, config: Configuration):
        """Serialize and dump as text JSON."""
        logger.debug("💾 Saving config to %s", self.data_file)
        data = {}
        for g in config.guilds.values():
            gdat = {
                'voice_tickers'   : g.voice_tickers,
                'ratio_tickers'   : self._dumps_int_map(g.ratio_tickers),
                'message_tickers' : self._dumps_int_map(g.message_tickers),
            }
            if g.update_category: gdat['update_category'] = str(g.update_category)
            if g.admin_role_id  : gdat['admin_role_id'] = str(g.admin_role_id)
            if g.cmc_api_key    : gdat['cmc_api_key'] = g.cmc_api_key
            data[str(g.id)] = gdat
        self._save_json(data)
        logger.debug("✅ Configuration file saved.")

class StyleManager:
    """Manages bot's visual style (icons etc), using optional JSON override."""
    DEFAULT_STYLES = {"price_up_icon": "📈", "price_down_icon": "📉"}
    def __init__(self, styles_file: str = "crypto_bot_styles.json"):
        self.styles_file = styles_file

    def load_styles(self) -> dict:
        """Load emoji/style definitions. If absent or broken, return sane defaults."""
        logger.debug("🎨 Loading styles from %s", self.styles_file)
        styles = dict(self.DEFAULT_STYLES)
        try:
            with open(self.styles_file, 'r') as f:
                styles.update(json.load(f))
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        return styles

def format_price(price: float) -> str:
    """Nicely format price according to range (small coins show more dp)."""
    if price < 0.01:    return f"${price:.6f}"
    if price < 1:       return f"${price:.4f}"
    if price < 1000:    return f"${price:.2f}"
    return f"${price:.0f}"

def get_utc_time() -> str:
    """UTC timestamp, e.g. '03:12 PM UTC' for status/notification."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%I:%M %p UTC")
