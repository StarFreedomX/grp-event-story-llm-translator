"""AssetBundleInfo 清单下载与搜索

游戏 CDN 上的 ``AssetBundleInfo`` 是包含所有资源路径及 SHA-256 哈希的文本清单。
本模块负责：
1. 根据版本号构造 CDN URL
2. 下载并缓存 AssetBundleInfo
3. 按路径模式搜索指定资源
"""

import json
import re
import logging
from pathlib import Path

from .downloader import download_file

logger = logging.getLogger(__name__)

# CDN 基址
_CDN_BASE = "https://content.garupa.jp/Release"

# 本地缓存目录（存放下载的 AssetBundleInfo 文本）
_CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"
_CACHE_DIR.mkdir(exist_ok=True)

# 版本→hash 映射文件
_HASH_FILE = Path(__file__).resolve().parent.parent / "version_hash.json"


# ---------- 版本号 / hash 工具 ----------

def _major_key(data_version: str) -> str:
    """从 ``dataVersion`` 提取大版本号（前三段）。

    >>> _major_key("10.1.0.190")
    '10.1'
    """
    parts = data_version.split(".")
    return ".".join(parts[:2])


def _load_hash_map() -> dict:
    """加载 ``version_hash.json``。"""
    if not _HASH_FILE.exists():
        raise FileNotFoundError(
            f"缺少 {_HASH_FILE}，请创建大版本→CDN hash 的映射文件"
        )
    with open(_HASH_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def build_asset_info_url(data_version: str) -> str:
    """根据 ``dataVersion`` 构造 AssetBundleInfo 下载 URL。

    例如 ``data_version="10.1.0.190"``
    → ``https://content.garupa.jp/Release/10.1.0.190_{hash}/Android/AssetBundleInfo``
    """
    major = _major_key(data_version)
    hash_map = _load_hash_map()
    cdn_hash = hash_map.get(major)
    if not cdn_hash:
        raise KeyError(
            f"未找到大版本 {major} 的 CDN hash，请在 {_HASH_FILE} 中添加"
        )
    return f"{_CDN_BASE}/{data_version}_{cdn_hash}/Android/AssetBundleInfo"


# ---------- AssetBundleInfo 解析 ----------

# 在二进制流中匹配路径片段
_PATH_RE = re.compile(rb"[A-Za-z][A-Za-z0-9_\-./]*[A-Za-z0-9]")
# 匹配 @ + 64 位十六进制 SHA-256（@ = 0x40，也是 protobuf hash 字段的 length）
_HASH_RE = re.compile(rb"@([a-fA-F0-9]{64})")


def parse_asset_info(text: bytes) -> dict[str, str]:
    """解析 AssetBundleInfo 文本，返回 ``{path: sha256_hash}`` 映射。

    AssetBundleInfo 是 protobuf 编码的二进制文本。每个条目大致结构为：
    ``...{path}{tag}{length}{path}@<64-hex-sha256>{more}``

    其中 ``@`` 实际上是 protobuf 中 hash 字符串的长度字节（0x40 = 64），
    恰好等于 SHA-256 十六进制长度。解析策略与 garupa-getAssets 一致：
    先找到 ``@<64-hex>``，再向前搜索最近的合法路径。
    """
    result: dict[str, str] = {}

    # 一次性找到所有 @<hash> 的位置
    hash_matches = list(_HASH_RE.finditer(text))
    if not hash_matches:
        return result

    # 找到所有路径的位置（按起始偏移排序）
    path_matches = list(_PATH_RE.finditer(text))
    if not path_matches:
        return result

    # 双指针：对每个 @hash，找到它前面最近的 path
    pi = 0  # path_matches 的游标
    for hm in hash_matches:
        hash_pos = hm.start()
        sha = hm.group(1).decode("ascii")

        # 在 path_matches 中前进，找到 hash 前最后一个 path
        # 从上次停下的位置继续（path 和 hash 都是顺序出现的）
        while pi < len(path_matches) and path_matches[pi].start() < hash_pos:
            candidate = path_matches[pi].group(0)
            pi += 1

        # pi 此时指向 hash 后的第一个 path，所以 candidate 是 hash 前最后一个
        if pi > 0:
            path = path_matches[pi - 1].group(0).decode("ascii")
            result[path] = sha

    logger.debug("解析到 %d 条资产路径", len(result))
    return result


# ---------- 公开 API ----------

class AssetInfo:
    """已下载的 AssetBundleInfo 清单，可按路径搜索。"""

    def __init__(self, data_version: str):
        self.data_version = data_version
        self._url = build_asset_info_url(data_version)
        self._base_url = self._url.rsplit("/", 1)[0] + "/"  # 去尾 /AssetBundleInfo
        self._paths: dict[str, str] = {}  # path → hash

    # -- 属性 --

    @property
    def url(self) -> str:
        """AssetBundleInfo 的下载 URL。"""
        return self._url

    @property
    def base_url(self) -> str:
        """拼接单个资产下载用的基址。

        例 ``https://content.garupa.jp/Release/10.1.0.190_{hash}/Android/``
        """
        return self._base_url

    @property
    def path_count(self) -> int:
        """已解析的资产条目数。"""
        return len(self._paths)

    # -- 下载与解析 --

    def fetch(self, force: bool = False) -> None:
        """下载并解析 AssetBundleInfo。

        Parameters
        ----------
        force:
            为 ``True`` 时强制重新下载，忽略缓存。
        """
        cache_path = _CACHE_DIR / f"AssetBundleInfo_{self.data_version}.txt"
        if not force and cache_path.exists():
            logger.info("使用缓存: %s", cache_path)
            text = cache_path.read_bytes()
        else:
            logger.info("下载 AssetBundleInfo: %s", self._url)
            ok = download_file(self._url, cache_path)
            if not ok:
                raise RuntimeError(f"下载 AssetBundleInfo 失败: {self._url}")
            text = cache_path.read_bytes()

        self._paths = parse_asset_info(text)
        logger.info("AssetBundleInfo 共 %d 条资产", len(self._paths))

    # -- 搜索 --

    def find(self, pattern: str) -> dict[str, str]:
        """搜索匹配 ``pattern`` 的资产路径，返回 ``{path: hash}``。

        支持 shell 风格通配符（``*`` / ``?``），或精确前缀匹配。
        """
        import fnmatch

        results: dict[str, str] = {}
        for path, sha in self._paths.items():
            if fnmatch.fnmatch(path, pattern):
                results[path] = sha
        return results

    def find_exact(self, path: str) -> tuple[str, str] | None:
        """精确查找一条资产路径，返回 ``(path, hash)`` 或 ``None``。"""
        sha = self._paths.get(path)
        if sha:
            return (path, sha)
        return None

    def find_event_story(self, event_id: int) -> tuple[str, str] | None:
        """查找活动故事的场景文件。

        等价于 ``find_exact(f"scenario/eventstory/event{event_id}")``。
        """
        return self.find_exact(f"scenario/eventstory/event{event_id}")
