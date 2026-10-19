"""Explicit server configuration, separate from the desktop databases."""
from dataclasses import dataclass, field
import os
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    root: Path = field(default_factory=lambda: Path(__file__).resolve().parents[2] / 'data' / 'miniprogram')
    mode: str = 'wechat'
    lan_demo: bool = False
    appid: str = ''
    appsecret: str = field(default='', repr=False)
    research_enabled: bool = False
    session_seconds: int = 86400
    daily_runs: int = 5
    daily_resumes: int = 12
    max_searches: int = 6
    global_active: int = 2
    max_users: int = 20

    def __post_init__(self):
        if self.mode not in {'wechat', 'demo'}:
            raise ValueError('mode must be wechat or demo')
        if self.lan_demo and self.mode != 'demo':
            raise ValueError('LAN demonstration is available only in explicit demo mode')
        if not 2 <= self.max_searches <= 16:
            raise ValueError('max_searches must be 2..16')
        if not all(1 <= n <= 100000 for n in (self.session_seconds, self.daily_runs, self.daily_resumes, self.global_active, self.max_users)):
            raise ValueError('invalid mini-program limits')

    @classmethod
    def from_env(cls):
        from src.env import load_env
        load_env()
        defaults = cls()
        return cls(root=Path(os.getenv('RP_MINI_DATA_ROOT', str(defaults.root))),
                   appid=os.getenv('WECHAT_APP_ID', ''), appsecret=os.getenv('WECHAT_APP_SECRET', ''),
                   research_enabled=os.getenv('RP_MINI_ENABLE_RESEARCH') == '1')
