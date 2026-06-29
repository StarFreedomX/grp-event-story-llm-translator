"""通用文件下载器

支持断点续传、自动重试、进度回调。
"""

import time
import logging
from pathlib import Path

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

# 默认 User-Agent，模拟 Unity 客户端
_UNITY_UA = "UnityPlayer/2022.3.62f1 (UnityWebRequest/1.0, libcurl/8.10.1-DEV)"

# 各 HTTP 错误的重试等待秒数
_RETRY_DELAYS = {
    403: 20,   # Forbidden — 等 CDN 生效
    429: 60,   # Rate limit
}


def download_file(
    url: str,
    dest: Path,
    *,
    timeout: int = 30,
    retries: int = 3,
    chunk_size: int = 1024 * 1024,  # 1 MiB
    on_progress=None,
) -> bool:
    """下载单个文件到 ``dest``。

    Parameters
    ----------
    url:
        下载地址。
    dest:
        目标路径（含文件名）。父目录不存在会自动创建。
    timeout:
        单次请求超时秒数。
    retries:
        最大重试次数。403/404 不重试。
    chunk_size:
        流式下载的块大小（字节）。
    on_progress:
        可选回调 ``on_progress(downloaded_bytes, total_bytes)``。

    Returns
    -------
    bool
        ``True`` 表示下载成功，``False`` 表示跳过（404 / 不可重试错误）。
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    headers = {"User-Agent": _UNITY_UA}

    for attempt in range(retries + 1):
        try:
            logger.debug("下载 %s (第 %d/%d 次)", url, attempt + 1, retries + 1)
            resp = requests.get(url, headers=headers, stream=True, timeout=timeout, verify=False)
            status = resp.status_code

            # 不可重试
            if status == 404:
                logger.warning("文件不存在 (404): %s", url)
                return False
            if status == 403:
                logger.warning("CDN 拒绝访问 (403)，等待 %ds …", _RETRY_DELAYS[403])
                time.sleep(_RETRY_DELAYS[403])
                continue  # 重试

            if status == 429:
                logger.warning("频率限制 (429)，等待 %ds …", _RETRY_DELAYS[429])
                time.sleep(_RETRY_DELAYS[429])
                continue

            if status >= 500:
                logger.warning("服务端错误 (%d)，等待 10s …", status)
                time.sleep(10)
                continue

            resp.raise_for_status()

            # 流式写入
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            with open(dest, "wb") as f:
                for chunk in resp.iter_content(chunk_size=chunk_size):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if on_progress:
                            on_progress(downloaded, total)

            logger.info("下载完成: %s → %s (%.1f KiB)", url, dest, downloaded / 1024)
            return True

        except requests.Timeout:
            logger.warning("下载超时 (%ds): %s", timeout, url)
            if attempt < retries:
                time.sleep(5)
        except requests.RequestException as e:
            logger.warning("下载出错: %s — %s", url, e)
            if attempt < retries:
                time.sleep(5)

    logger.error("下载失败（已重试 %d 次）: %s", retries, url)
    return False
