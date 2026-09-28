"""机器翻译客户端

支持 OpenAI / Anthropic / DeepSeek / Gemini / Qwen。
"""

import logging
import re
from pathlib import Path

import requests
import urllib3

from .config import MtConfig

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompt.md"


def _load_prompt(config: MtConfig | None = None) -> str:
    prompt = ""
    if _PROMPT_PATH.exists():
        prompt = _PROMPT_PATH.read_text(encoding="utf-8")
    if config and config.further_prompt_file:
        fp_path = Path(__file__).resolve().parent.parent / config.further_prompt_file
        if fp_path.exists():
            prompt += "\n\n" + fp_path.read_text(encoding="utf-8")
        else:
            logger.debug("further_prompt 文件不存在: %s", config.further_prompt_file)
    return prompt or "你是一个日语翻译专家，请将以下日文翻译成简体中文。"


# ═══════════════════════════════════════════════════════════════
# Reasoning / Thinking 参数构建
# ═══════════════════════════════════════════════════════════════

def build_reasoning_params(config: MtConfig) -> dict:
    """根据 provider + reasoning_mode + reasoning_effort 构建请求参数。"""
    mode = config.reasoning_mode
    effort = config.reasoning_effort
    provider = config.provider

    # ── DISABLED ──
    if mode == "disabled":
        if provider == "deepseek":
            return {"thinking": {"type": "disabled"}}
        if provider == "qwen":
            return {"chat_template_kwargs": {"enable_thinking": False}}
        return {}  # openai / anthropic / gemini: omit = disabled

    # ── AUTO ──
    if mode == "auto":
        if provider == "deepseek":
            return {"thinking": {"type": "enabled"}}
        if provider == "anthropic":
            return {"thinking": {"type": "auto"}}
        return {}  # openai / gemini / qwen: omit

    # ── ENABLED ──
    if provider == "deepseek":
        params: dict = {"thinking": {"type": "enabled"}}
        if effort == "max":
            params["reasoning_effort"] = "max"
        elif effort != "auto":
            params["reasoning_effort"] = "high"
        return params

    if provider == "openai":
        if effort in ("auto", "max"):
            return {"reasoning_effort": "high"}
        return {"reasoning_effort": effort}

    if provider == "anthropic":
        budget_map = {"low": 2048, "medium": 8192, "high": 16384, "max": 32000}
        budget = budget_map.get(effort, 4096)
        return {"thinking": {"type": "enabled", "budget_tokens": budget}}

    if provider == "gemini":
        gemini_effort = "high" if effort == "max" else effort
        if gemini_effort == "auto":
            gemini_effort = "medium"
        return {"reasoning_effort": gemini_effort}

    if provider == "qwen":
        return {"chat_template_kwargs": {"enable_thinking": True}}

    return {}


# ═══════════════════════════════════════════════════════════════
# API 调用
# ═══════════════════════════════════════════════════════════════

def _build_input_json(lines: list[dict]) -> str:
    """构建发给 AI 的 JSON 输入。"""
    import json as _json
    items = [{"s": l["speaker"], "t": l["text"]} for l in lines]
    return _json.dumps(items, ensure_ascii=False, indent=1)


def _dump_raw(raw: str, save_dir: str | None, label: str = ""):
    """保存原始 AI 响应到文件。"""
    if not save_dir:
        return
    from datetime import datetime
    path = Path(save_dir)
    path.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%H%M%S_%f")
    dump = path / f"_raw_response_{ts}.txt"
    dump.write_text(raw, encoding="utf-8")
    logger.warning("原始响应已保存至: %s %s", dump, label)


def _parse_output_text(raw: str, count: int, save_dir: str | None = None) -> list[str]:
    """按 [序号] 解析译文；缺号或重号时拒绝写入错位结果。"""
    matches = list(re.finditer(r"(?m)^\s*\[(\d+)\][ \t]*(.*)$", raw))
    numbers = [int(m.group(1)) for m in matches]
    if numbers != list(range(1, count + 1)) or (matches and raw[:matches[0].start()].strip()):
        logger.warning("翻译编号不匹配: 期望 1-%d, 实际 %s", count, numbers)
        _dump_raw(raw, save_dir, "(编号不匹配)")
        raise ValueError(f"翻译编号不匹配: 期望 1-{count}")

    translations = []
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(raw)
        translations.append(raw[match.start(2):end].strip())
    if any(not item for item in translations):
        _dump_raw(raw, save_dir, "(空译文)")
        raise ValueError("存在空译文")
    return translations


def _call_openai(
    lines: list[dict],
    config: MtConfig,
    prompt: str,
    save_dir: str | None = None,
) -> list[str]:
    """调用 OpenAI 兼容 API，发送/接收 JSON。"""
    import json as _json
    input_json = _build_input_json(lines)
    user_msg = f"{input_json}\n\n请按顺序翻译以上 JSON 中每个元素的 t 字段为中文，共 {len(lines)} 条。每条以 [1]、[2] 等连续编号开头，编号从 1 开始；每条译文只占一行，不要 JSON、说话人或其他内容。"
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": user_msg},
    ]

    body: dict = {
        "model": config.model,
        "messages": messages,
        "temperature": config.temperature,
    }

    reasoning = build_reasoning_params(config)
    body.update(reasoning)

    headers = {
        "Authorization": f"Bearer {config.api_key}",
        "Content-Type": "application/json",
    }
    url = config.base_url.rstrip("/") + "/chat/completions"
    logger.debug("OpenAI 请求: model=%s, %d 句", config.model, len(lines))

    resp = requests.post(url, json=body, headers=headers, timeout=180, verify=False)
    resp.raise_for_status()
    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    return _parse_output_text(content, len(lines), save_dir)


def _call_anthropic(
    lines: list[dict],
    config: MtConfig,
    prompt: str,
    save_dir: str | None = None,
) -> list[str]:
    """调用 Anthropic API，JSON 输入，纯文本输出。"""
    input_json = _build_input_json(lines)
    user_msg = f"{input_json}\n\n请按顺序翻译以上 JSON 中每个元素的 t 字段为中文，共 {len(lines)} 条。每条以 [1]、[2] 等连续编号开头，编号从 1 开始；每条译文只占一行，不要 JSON、说话人或其他内容。"

    body: dict = {
        "model": config.model,
        "max_tokens": 4096,
        "system": prompt,
        "messages": [{"role": "user", "content": user_msg}],
        "temperature": config.temperature,
    }

    reasoning = build_reasoning_params(config)
    body.update(reasoning)

    headers = {
        "x-api-key": config.api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    url = config.base_url.rstrip("/") + "/v1/messages"
    logger.debug("Anthropic 请求: model=%s, %d 句", config.model, len(lines))

    resp = requests.post(url, json=body, headers=headers, timeout=180, verify=False)
    resp.raise_for_status()
    data = resp.json()
    content = data["content"][0]["text"]
    return _parse_output_text(content, len(lines), save_dir)


# ═══════════════════════════════════════════════════════════════
# 批量翻译
# ═══════════════════════════════════════════════════════════════

def translate_all(
    lines: list[dict],
    config: MtConfig | None = None,
    save_dir: str | None = None,
) -> list[str]:
    """翻译台词列表，返回翻译后的文本列表（与输入一一对应）。

    整话一次性发送，使用编号验证译文与输入逐条对应。
    """
    if config is None:
        from .config import load_mt_config
        config = load_mt_config()

    if not lines:
        return []
    if not config.enabled or not config.api_key:
        return [""] * len(lines)

    logger.info("翻译 %d 句 …", len(lines))

    prompt = _load_prompt(config)
    try:
        if config.api_format == "anthropic":
            call = _call_anthropic
        else:
            call = _call_openai
        for attempt in range(2):
            try:
                return call(lines, config, prompt, save_dir)
            except ValueError:
                if attempt == 0:
                    logger.warning("译文格式不正确，重试一次")
                    continue
                raise
    except Exception as e:
        logger.error("翻译调用失败: %s", e)
        raise
