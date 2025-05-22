from typing import Optional, List, Dict
from dataclasses import dataclass, field

@dataclass
class GuildConfiguration:
    id: int
    '''
    The guild's guild id.
    '''
    update_category: Optional[int] = None
    voice_tickers: List[str] = field(default_factory=list)
    ratio_tickers: Dict[str,int] = field(default_factory=dict)
    message_tickers: Dict[str, int] = field(default_factory=dict)


@dataclass
class Configuration:
    '''
    Configuration for the entire update bot.
    '''

    guilds: Dict[int,GuildConfiguration]
    '''
    Configuration for invididual servers under the bot's control. Indexed by
    guild id.
    '''


