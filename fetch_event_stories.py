#!/usr/bin/env python3
"""从邦邦官方 CDN 获取指定活动故事。

用法::

    python fetch_event_stories.py 335          # 下载活动 335 的故事
    python fetch_event_stories.py 335 --force  # 强制重新下载

中间文件（JSON / AssetBundle）放在 ``tmp/{eventId}_story/``，
默认提取完成后自动清理。设 ``KEEP_TEMP=true`` 可保留。
"""

import sys
import shutil
import argparse
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.api import get_data_version
from src.asset_info import AssetInfo
from src.downloader import download_file
from src.extractor import extract_scenario
from src.config import cdn, _get

logger = logging.getLogger("fetch_event_stories")


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


def main():
    parser = argparse.ArgumentParser(description="从邦邦官方 CDN 获取指定活动故事文本")
    parser.add_argument("event_id", nargs="?", type=int, default=None, help="活动 ID，如 335")
    parser.add_argument("--force", action="store_true", help="强制重新下载（忽略缓存）")
    parser.add_argument("-v", "--verbose", action="store_true", help="详细日志")
    args = parser.parse_args()
    setup_logging(args.verbose)

    event_id = args.event_id
    if event_id is None:
        try:
            event_id = int(input("请输入活动 ID: ").strip())
        except (ValueError, EOFError):
            logger.error("无效的活动 ID")
            sys.exit(1)
    keep_temp = _get("KEEP_TEMP", "false").lower() == "true"
    tmp_dir = Path(f"tmp/{event_id}_story")

    try:
        # Step 1: 获取 dataVersion
        logger.info("获取最新版本号 …")
        data_ver = get_data_version()
        logger.info("dataVersion: %s", data_ver)

        # Step 2: 下载 & 解析 AssetBundleInfo
        info = AssetInfo(data_ver)
        info.fetch(force=args.force)

        # Step 3: 搜索活动故事路径
        found = info.find_event_story(event_id)
        if not found:
            logger.error("未找到活动 %d 的故事文件", event_id)
            sys.exit(1)

        asset_path, asset_hash = found
        asset_url = f"{info.base_url}{asset_path}"
        logger.info("找到: %s", asset_path)

        # Step 4: 下载 AssetBundle
        bundle_path = tmp_dir / f"event{event_id}.bundle"
        ok = download_file(asset_url, bundle_path)
        if not ok:
            logger.error("下载失败")
            sys.exit(1)

        # Step 5: 解包 → JSON
        json_files = extract_scenario(bundle_path, tmp_dir)
        logger.info("提取 %d 个 JSON → %s", len(json_files), tmp_dir)

        # tmp/ 目录留给 extract_story.py 消费后统一清理
        logger.info("完成。下一步: python extract_story.py -d %s", tmp_dir)

    except Exception as e:
        logger.error("失败: %s", e)
        if not keep_temp and tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
