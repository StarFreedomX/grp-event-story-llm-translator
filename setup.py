#!/usr/bin/env python3
"""配置向导 —— 终端 UI 交互式配置 .env，自动安装缺失依赖。

↑↓ 选字段  ←→ 切分类  Enter 编辑  Esc 保存退出
"""

import sys
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV_PATH = ROOT / ".env"
ENV_EXAMPLE_PATH = ROOT / ".env.example"

DEPS = ["requests", "cryptography", "UnityPy", "openpyxl", "urllib3"]
SECRET_FIELDS = {"MT_API_KEY"}

# (key, label, hint, is_bool)
CATEGORIES = [
    ("CDN / 游戏资源", [
        ("UNITY_VERSION",           "Unity 版本",           None,   False),
        ("AES_KEY",                 "AES 密钥",             None,   False),
        ("AES_IV",                  "AES IV",               None,   False),
        ("CLIENT_VERSION_FALLBACK", "客户端版本 fallback",   None,   False),
        ("DATA_VERSION_FALLBACK",   "数据版本 fallback",     None,   False),
        ("KEEP_TEMP",               "保留中间文件",          None,   True),
    ]),
    ("机翻 (Machine Translation)", [
        ("MT_ENABLED",       "启用机翻",           None,   True),
        ("MT_PROVIDER",      "服务商",              "openai | anthropic | deepseek | gemini | qwen", False),
        ("MT_API_FORMAT",    "HTTP 协议格式",       "openai | anthropic", False),
        ("MT_BASE_URL",      "API 地址",            None,   False),
        ("MT_API_KEY",       "API Key",             None,   False),
        ("MT_MODEL",         "模型名称",            None,   False),
        ("MT_REASONING_MODE","思考模式",             "disabled | auto | enabled", False),
        ("MT_REASONING_EFFORT", "思考强度",         "auto | low | medium | high | max", False),
        ("MT_TEMPERATURE",          "温度",                   "0.0 ~ 2.0", False),
        ("MT_FURTHER_PROMPT_FILE",  "额外提示词文件",          None,         False),
    ]),
    ("依赖", [
        ("_DEPS", "自动检测并安装缺失依赖", "按 Enter 执行", False),
    ]),
]

HELP = "↑↓ 选择  ←→ 切分类  Enter 编辑  Esc 退出"
POPUP_SAVE  = "保存并退出"
POPUP_DISCARD = "放弃编辑并退出"
POPUP_BACK = "继续编辑"
POPUP_OPTS = [POPUP_SAVE, POPUP_DISCARD, POPUP_BACK]
P_SAVE, P_DISCARD, P_BACK = 1, 2, 3  # popup 索引


# ═══════════════════════════════
# 键盘输入 (Windows / Unix)
# ═══════════════════════════════

def _getch_win():
    """Windows: 返回原始字节序列。"""
    import msvcrt
    ch = msvcrt.getch()
    if ch in (b"\x00", b"\xe0"):
        return ch + msvcrt.getch()
    return ch

def _getch_unix():
    """Unix: 返回原始字节序列。"""
    import tty, termios
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.buffer.read(1)
        if ch == b"\x1b":
            rest = sys.stdin.buffer.read(2)
            return ch + rest if rest else ch
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)

_IS_WIN = sys.platform == "win32"

def get_key() -> str:
    raw = _getch_win() if _IS_WIN else _getch_unix()
    # 常见映射
    MAP = {
        # Unix
        b"\x1b[A": "up",    b"\x1b[B": "down",
        b"\x1b[C": "right", b"\x1b[D": "left",
        b"\t":     "tab",   b"\r":     "enter",
        b"\n":     "enter", b"\x1b":   "esc",
        b"\x7f":   "bs",
        # Win32 (\xe0 前缀)
        b"\xe0H":  "up",    b"\xe0P":  "down",
        b"\xe0M":  "right", b"\xe0K":  "left",
        # Win32 (\x00 前缀)
        b"\x00H":  "up",    b"\x00P":  "down",
        b"\x00M":  "right", b"\x00K":  "left",
    }
    if raw in MAP:
        return MAP[raw]
    # 单字节
    if len(raw) == 1:
        b = raw[0]
        if b == 3:    # Ctrl+C
            return "\x03"
        if b == 8:    # Backspace
            return "bs"
        if 32 <= b <= 126:
            return chr(b)
    return "?"


# ═══════════════════════════════
# 依赖
# ═══════════════════════════════

def _check_deps():
    missing = []
    for pkg in DEPS:
        mod = pkg.replace("-", "_").split("[")[0]
        try:
            __import__(mod)
        except ImportError:
            missing.append(pkg)
    return missing

_deps_cache = None

def _deps_status():
    """返回依赖状态字符串，用于 UI 显示（有缓存）。"""
    global _deps_cache
    if _deps_cache is None:
        _deps_cache = _check_deps()
    if not _deps_cache:
        return "✓ 全部已安装"
    return f"✗ 缺少: {', '.join(_deps_cache)}"

def _install_deps():
    """交互式安装依赖。"""
    global _deps_cache
    missing = _check_deps()
    if not missing:
        return
    print(f"\n\033[2J\033[H")  # 清屏
    print(f"缺少依赖: {', '.join(missing)}")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])
        print("\n安装完成！")
    except subprocess.CalledProcessError:
        print("\n安装失败，请手动执行: pip install " + " ".join(missing))
        print("按 Enter 返回 …")
    input()
    _deps_cache = None  # 清除缓存，下次渲染重新检测


# ═══════════════════════════════
# .env 读写
# ═══════════════════════════════

def parse_env(text):
    result = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, _, v = line.partition("=")
            result[k.strip()] = v.strip()
    return result

def format_env(config, template_text):
    lines = template_text.splitlines()
    out = []
    for line in lines:
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            key = s.split("=")[0].strip()
            if key in config:
                out.append(f"{key}={config[key]}")
                continue
        out.append(line)
    return "\n".join(out) + "\n"

def mask(key, val):
    if key in SECRET_FIELDS and val:
        return val[:4] + "****" + val[-4:] if len(val) > 8 else "****"
    if len(val) > 42:
        return val[:39] + "..."
    return val


# ═══════════════════════════════
# TUI 渲染
# ═══════════════════════════════

# 记录上次渲染的行数，用于下次覆盖
_prev_lines = 0

def _goto_home():
    """回到界面第一行（不是清屏，是覆盖）。"""
    if _prev_lines > 0:
        sys.stdout.write(f"\033[{_prev_lines}A")  # 上移
    sys.stdout.write("\033[0J")  # 从光标处清到屏幕底
    sys.stdout.flush()

def render(ci, fi, config, editing, edit_buf, popup_choice=0):
    global _prev_lines
    _goto_home()

    lines = []

    # 顶栏
    lines.append("\033[7m 配置向导 \033[0m  \033[2m按 Esc 保存退出\033[0m")
    lines.append("")

    # 分类 tabs
    tabs = ""
    for c in range(len(CATEGORIES)):
        name = CATEGORIES[c][0]
        tabs += "\033[7m " + name + " \033[0m " if c == ci else " " + name + "  "
    lines.append(tabs)
    lines.append("")

    # 字段
    fields = CATEGORIES[ci][1]
    for f in range(len(fields)):
        key, label, hint, is_bool = fields[f]

        # 依赖字段特殊处理
        if key == "_DEPS":
            display = _deps_status()
        elif is_bool:
            display = config.get(key, "false")
        else:
            display = mask(key, config.get(key, ""))
            hint = f" ({hint})" if hint else ""

        if f == fi:
            prefix = "\033[7m▸\033[0m"
        else:
            prefix = " "

        if editing and f == fi:
            if is_bool:
                lines.append(f" {prefix} \033[4m{label}\033[0m: {edit_buf}  ←→切换")
            else:
                buf = edit_buf if edit_buf else "(空)"
                lines.append(f" {prefix} \033[4m{label}\033[0m: {buf}_")
        else:
            if is_bool:
                lines.append(f" {prefix} {label}: {display}")
            else:
                lines.append(f" {prefix} {label}: {display}{hint}")

    lines.append("")
    lines.append("\033[2m " + HELP + " \033[0m")

    # 退出确认弹窗
    if popup_choice > 0:
        lines.append("")
        line = ""
        for i, opt in enumerate(POPUP_OPTS):
            padded = f"  {opt}  "
            line += ("\033[7m" + padded + "\033[0m  ") if i + 1 == popup_choice else (padded + "  ")
        lines.append(line)

    out = "\n".join(lines) + "\n"
    sys.stdout.write(out)
    sys.stdout.flush()
    _prev_lines = len(lines)


# ═══════════════════════════════
# 主循环
# ═══════════════════════════════

def run_tui(config):
    """返回 True=保存, False=放弃。"""
    global _prev_lines
    _prev_lines = 0

    ci, fi = 0, 0
    editing = False
    edit_buf = ""
    popup = 0

    def _tick():
        try:
            return get_key()
        except KeyboardInterrupt:
            return "\x03"  # Ctrl+C 信号

    try:
        render(ci, fi, config, editing, edit_buf, popup)

        while True:
            key = _tick()

            # Ctrl+C → 直接退出不保存
            if key == "\x03":
                return False

            # ── 弹窗模式 ──
            if popup > 0:
                if key == "left":
                    popup = P_BACK if popup == P_SAVE else popup - 1
                elif key == "right":
                    popup = P_SAVE if popup == P_BACK else popup + 1
                elif key == "enter":
                    if popup == P_SAVE:
                        return True
                    elif popup == P_DISCARD:
                        return False
                    else:
                        popup = 0
                elif key == "esc":
                    popup = 0
                elif key == "\x03":
                    return False  # 弹窗中 Ctrl+C → 直接放弃退出
                render(ci, fi, config, editing, edit_buf, popup)
                continue

            # ── 编辑模式 ──
            if editing:
                _, _, _, is_bool = CATEGORIES[ci][1][fi]
                if key == "esc":
                    editing = False
                elif key == "enter":
                    config[CATEGORIES[ci][1][fi][0]] = edit_buf.strip()
                    editing = False
                elif is_bool and key in ("left", "right"):
                    edit_buf = "false" if edit_buf == "true" else "true"
                elif not is_bool:
                    if key == "bs":
                        edit_buf = edit_buf[:-1]
                    elif len(key) == 1:
                        edit_buf += key
                render(ci, fi, config, editing, edit_buf, popup)
                continue

            # ── 导航模式 ──
            if key == "esc":
                popup = P_SAVE
            elif key == "up":
                fi = (fi - 1) % len(CATEGORIES[ci][1])
            elif key == "down":
                fi = (fi + 1) % len(CATEGORIES[ci][1])
            elif key in ("right", "tab"):
                ci = (ci + 1) % len(CATEGORIES)
                fi = 0
            elif key == "left":
                ci = (ci - 1) % len(CATEGORIES)
                fi = 0
            elif key == "enter":
                key_name = CATEGORIES[ci][1][fi][0]
                if key_name == "_DEPS":
                    _install_deps()  # 全屏安装流程，返回后刷新
                else:
                    edit_buf = config.get(key_name, "")
                    editing = True

            render(ci, fi, config, editing, edit_buf, popup)

    finally:
        sys.stdout.write("\n")


# ═══════════════════════════════
# Main
# ═══════════════════════════════

def main():
    print("=" * 50)
    print("  邦邦剧情翻译流水线 — 配置向导")
    print("=" * 50)

    if ENV_PATH.exists():
        template = ENV_PATH.read_text(encoding="utf-8")
        print(f"检测到已有 .env，在此基础上配置。")
    elif ENV_EXAMPLE_PATH.exists():
        template = ENV_EXAMPLE_PATH.read_text(encoding="utf-8")
        print(f"从 .env.example 创建配置。")
    else:
        print("错误: 缺少 .env.example")
        sys.exit(1)

    config = parse_env(template)

    saved = run_tui(config)

    if saved:
        output = format_env(config, template)
        ENV_PATH.write_text(output, encoding="utf-8")
        print("\n✓ 已保存到 .env\n")
        for key, *_ in [f for cat in CATEGORIES for f in cat[1]]:
            if key in config:
                print(f"  {key}={mask(key, config[key])}")
    else:
        print("\n✗ 已放弃，未保存。")


if __name__ == "__main__":
    main()
