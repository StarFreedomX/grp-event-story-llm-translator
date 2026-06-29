"""从 .env 文件加载配置，提供类型化访问。"""

import os
from pathlib import Path
from dataclasses import dataclass, field


_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def _load_dotenv() -> dict[str, str]:
    """手动解析 .env（不依赖 python-dotenv 库）。"""
    result: dict[str, str] = {}
    if not _ENV_PATH.exists():
        return result
    with open(_ENV_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, val = line.partition("=")
                result[key.strip()] = val.strip()
    return result


_env = _load_dotenv()


def _get(key: str, default: str = "") -> str:
    return _env.get(key, os.environ.get(key, default))


@dataclass
class CdnConfig:
    """CDN / 游戏资源配置"""
    unity_version: str = "2022.3.62f1"
    aes_key: bytes = b""
    aes_iv: bytes = b""
    client_version_fallback: str = "10.1.2"
    data_version_fallback: str = ""


@dataclass
class MtConfig:
    """机翻配置"""
    enabled: bool = False
    provider: str = "openai"     # openai | anthropic | deepseek | gemini | qwen
    api_format: str = "openai"   # HTTP 协议：openai 或 anthropic
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "gpt-4o-mini"
    reasoning_mode: str = "disabled"   # disabled | auto | enabled
    reasoning_effort: str = "auto"     # low | medium | high | max | auto
    temperature: float = 0.3
    further_prompt_file: str = ""


def load_cdn_config() -> CdnConfig:
    aes_key_raw = _get("AES_KEY", "")
    aes_iv_raw = _get("AES_IV", "")
    if not aes_key_raw or not aes_iv_raw:
        raise RuntimeError("请在 .env 中配置 AES_KEY 和 AES_IV")
    return CdnConfig(
        unity_version=_get("UNITY_VERSION", "2022.3.62f1"),
        aes_key=aes_key_raw.encode("utf-8"),
        aes_iv=aes_iv_raw.encode("utf-8"),
        client_version_fallback=_get("CLIENT_VERSION_FALLBACK", "10.1.2"),
        data_version_fallback=_get("DATA_VERSION_FALLBACK", ""),
    )


def load_mt_config() -> MtConfig:
    return MtConfig(
        enabled=_get("MT_ENABLED", "false").lower() == "true",
        provider=_get("MT_PROVIDER", "openai").lower(),
        api_format=_get("MT_API_FORMAT", "openai").lower(),
        base_url=_get("MT_BASE_URL", "https://api.openai.com/v1"),
        api_key=_get("MT_API_KEY", ""),
        model=_get("MT_MODEL", "gpt-4o-mini"),
        reasoning_mode=_get("MT_REASONING_MODE", "disabled").lower(),
        reasoning_effort=_get("MT_REASONING_EFFORT", "auto").lower(),
        temperature=float(_get("MT_TEMPERATURE", "0.3")),
        further_prompt_file=_get("MT_FURTHER_PROMPT_FILE", ""),
    )


# 模块级单例
cdn = load_cdn_config()
mt = load_mt_config()
