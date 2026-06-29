"""Unity AssetBundle 解包器

使用 ``UnityPy`` 从 Unity AssetBundle 中提取 TextAsset（JSON 场景文件）。

依赖: ``pip install UnityPy``
"""

import json
import logging
from pathlib import Path

from .config import cdn

logger = logging.getLogger(__name__)


def _ensure_unity_version():
    """确保 UnityPy 配置了正确的 Unity 版本。"""
    import warnings
    import UnityPy

    warnings.filterwarnings("ignore", message="No valid Unity version found")

    if UnityPy.config.FALLBACK_UNITY_VERSION != cdn.unity_version:
        UnityPy.config.FALLBACK_UNITY_VERSION = cdn.unity_version
        logger.debug("UnityPy fallback version set to %s", cdn.unity_version)


def extract_scenario(asset_path: Path, output_dir: Path) -> list[Path]:
    """解包单个场景 AssetBundle，提取所有 TextAsset 并写入 ``output_dir``。

    Parameters
    ----------
    asset_path:
        Unity AssetBundle 文件路径。
    output_dir:
        输出目录（不存在则自动创建）。

    Returns
    -------
    list[Path]
        提取出的 JSON 文件路径列表。
    """
    import UnityPy

    _ensure_unity_version()

    asset_path = Path(asset_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("解包: %s", asset_path)

    env = UnityPy.load(str(asset_path))
    extracted: list[Path] = []

    for name, obj in env.container.items():
        # 只处理 MonoBehaviour（场景数据），跳过 AssetBundle、MonoScript 等
        if obj.type.name != "MonoBehaviour":
            continue

        data = obj.read()
        # 文件名取自 m_Name 字段，如 Scenarioevent335-01
        file_name = getattr(data, "m_Name", None)
        if not file_name:
            continue
        if not file_name.lower().startswith("scenario"):
            continue

        if not file_name.endswith(".json"):
            file_name += ".json"

        # read_typetree() 将 Unity 序列化数据转为纯 Python dict
        try:
            tree = obj.read_typetree()
        except Exception as e:
            logger.warning("  读取 %s 类型树失败: %s", file_name, e)
            continue

        out_path = output_dir / file_name
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(tree, f, ensure_ascii=False, indent=2)
        logger.info("  -> %s", out_path.name)
        extracted.append(out_path)

    if not extracted:
        logger.warning("未在 %s 中找到 Scenario MonoBehaviour", asset_path.name)

    return extracted
