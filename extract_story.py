#!/usr/bin/env python3
"""从 Scenarioevent JSON 提取故事为 Excel，可选机翻。

用法:
    python extract_story.py                          # 输出 {chapter}机翻剧情/
    python extract_story.py -d ./event335            # 指定 JSON 目录
    python extract_story.py -o ./output              # 指定输出目录
    python extract_story.py --no-mt                  # 不用机翻(机翻栏留空)
"""

import json
import sys
import argparse
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from openpyxl import Workbook
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "openpyxl"])
    from openpyxl import Workbook

from src.config import load_mt_config, _get
from src.translator import translate_all

logger = logging.getLogger("extract_story")


def parse_json(filepath: str) -> list[dict]:
    """从单个 JSON 提取所有需要翻译的行。

    Returns
        list[dict]: 每项 ``{speaker, text, note}``
    """
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    talks = data.get("talkData", [])
    snippets = data.get("snippets", [])
    effects = data.get("specialEffectData", [])
    layouts = data.get("layoutData", [])

    char_names: dict[int, str] = {}
    for t in talks:
        cids = [c.get("characterId") for c in t.get("talkCharacters", [])]
        name = t.get("windowDisplayName", "")
        for cid in cids:
            if cid not in char_names and name:
                char_names[cid] = name

    lines: list[dict] = []
    # 场景标题(effectType=8)：记录已处理的 effect 索引，防止重复
    seen_effect_indices: set[int] = set()

    def _capture_title(eff_idx):
        title_text = effects[eff_idx].get("stringVal", "")
        if title_text and eff_idx not in seen_effect_indices:
            seen_effect_indices.add(eff_idx)
            lines.append({"speaker": "【场景】", "text": title_text})

    for snip in snippets:
        atype = snip.get("actionType")
        ref = snip.get("referenceIndex", 0)

        if atype == 1:  # 台词
            if ref < len(talks):
                t = talks[ref]
                body = t.get("body", "").replace("\n", " ")
                lines.append({
                    "speaker": t.get("windowDisplayName", ""),
                    "text": body,
                })

        # 场景标题：type=6(角色动作) 或 type=7(显示特效) 引用到 effectType=8
        elif atype in (6, 7) and ref < len(effects) and effects[ref].get("effectType") == 8:
            _capture_title(ref)

    return lines


def build_xlsx(lines: list[dict], translations: list[str], out_path: Path) -> None:
    """写入单个 xlsx 文件。

    Parameters
    ----------
    lines:
        原文行列表。
    translations:
        翻译列表，与 lines 一一对应。
    out_path:
        输出路径。
    """
    wb = Workbook()
    ws = wb.active
    ws.title = out_path.stem
    ws.append(["人名", "原文", "人名", "机翻"])

    for i, line in enumerate(lines):
        speaker = line["speaker"]
        text = line["text"]
        mt = translations[i] if i < len(translations) else ""
        ws.append([speaker, text, speaker, mt])

    # 列宽
    ws.column_dimensions["A"].width = 12
    ws.column_dimensions["B"].width = 55
    ws.column_dimensions["C"].width = 12
    ws.column_dimensions["D"].width = 55

    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)
    logger.info("  -> %s (%d 行)", out_path.name, len(lines))


def main():
    parser = argparse.ArgumentParser(description="提取故事字幕到 Excel,可选机翻")
    parser.add_argument("event_id", nargs="?", type=int, default=None,
                        help="活动 ID(自动寻找 tmp/{id}_story/)")
    parser.add_argument("chapters", nargs="*", type=int, default=None,
                        help="指定话（从 0 开始），可多个如 2 3 4；不传=全部")
    parser.add_argument("-d", "--dir", default=None, help="JSON 文件所在目录(覆盖自动检测)")
    parser.add_argument("-o", "--output", default=None, help="输出目录(默认自动命名)")
    parser.add_argument("--no-mt", action="store_true", help="禁用机翻")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    event_id = args.event_id
    chapter_filter = set(args.chapters) if args.chapters else None
    if event_id is None and not args.dir:
        try:
            raw = input("请输入活动 ID(可带话,如 335 2 3 4): ").strip().split()
            event_id = int(raw[0])
            if len(raw) >= 2:
                chapter_filter = {int(c) for c in raw[1:]}
        except (ValueError, EOFError):
            logger.error("无效的输入")
            sys.exit(1)

    if args.dir:
        search_dir = Path(args.dir)
    elif event_id is not None:
        search_dir = Path(f"tmp/{event_id}_story")
    else:
        search_dir = Path(".")

    json_files = sorted(search_dir.glob("Scenarioevent*.json"))

    if not json_files:
        logger.error("目录 %s 中没有找到 Scenarioevent*.json 文件", args.dir)
        sys.exit(1)

    # event ID：优先用户输入，否则从文件名推断
    if event_id is None:
        first_name = json_files[0].stem
        try:
            event_id = int(first_name.split("Scenarioevent")[1].split("-")[0])
        except (IndexError, ValueError):
            event_id = 0

    # 输出目录(默认 out/)
    if args.output:
        out_dir = Path(args.output)
    else:
        out_dir = Path("out") / f"{event_id}机翻剧情"

    # 机翻配置
    mt_config = None if args.no_mt else load_mt_config()

    do_mt = mt_config and mt_config.enabled and mt_config.api_key

    # 第一步：解析所有 JSON（无网络，快）
    tasks: list[dict] = []  # {i, jf, lines, filename}
    for i, jf in enumerate(json_files):
        if chapter_filter is not None and i not in chapter_filter:
            continue
        lines = parse_json(str(jf))
        name = jf.stem
        parts = name.split("-")
        try:
            chap_num = int(parts[-1]) - 1 if len(parts) >= 2 else i
        except ValueError:
            chap_num = i
        filename = f"{event_id}{chap_num:02d}.xlsx"
        tasks.append({"i": i, "lines": lines, "filename": filename})
        logger.info("解析: %s (%d 句)", jf.name, len(lines))

    # 第二步：并行翻译
    if do_mt:
        from concurrent.futures import ThreadPoolExecutor
        total = len(tasks)
        with ThreadPoolExecutor(max_workers=total) as pool:
            futures = {}
            for t in tasks:
                fut = pool.submit(translate_all, t["lines"], mt_config, str(search_dir))
                futures[fut] = t

            for fut in futures:
                t = futures[fut]
                try:
                    t["translations"] = fut.result()
                    logger.info("翻译 [%d/%d] 第 %d 话 完成", t["i"] + 1, len(json_files), t["i"])
                except Exception as e:
                    logger.error("翻译 [%d/%d] 第 %d 话 失败: %s", t["i"] + 1, len(json_files), t["i"], e)
                    t["translations"] = [f"[翻译失败: {e}]"] * len(t["lines"])
    else:
        for t in tasks:
            t["translations"] = [""] * len(t["lines"])
        logger.info("机翻已禁用，翻译栏留空")

    # 第三步：写出 xlsx
    for t in tasks:
        out_path = out_dir / t["filename"]
        build_xlsx(t["lines"], t["translations"], out_path)

    logger.info("完成，输出目录: %s", out_dir.resolve())

    # 清理中间文件(有原始响应留档时不删)
    keep_temp = _get("KEEP_TEMP", "false").lower() == "true"
    if not keep_temp:
        import shutil
        tmp_dir = Path(f"tmp/{event_id}_story")
        if tmp_dir.exists():
            raw_dumps = list(tmp_dir.glob("_raw_response_*"))
            if raw_dumps:
                logger.warning("存在 %d 个原始响应文件，保留 tmp 目录以便排查", len(raw_dumps))
            else:
                shutil.rmtree(tmp_dir, ignore_errors=True)
                logger.debug("已清理临时目录: %s", tmp_dir)


if __name__ == "__main__":
    main()
