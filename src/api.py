"""官方 API 客户端

- 从 iTunes API 自动获取最新客户端版本
- 从 ``api.garupa.jp/api/application`` 获取数据版本
"""

import struct
import logging

import requests
import urllib3
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

from .config import cdn

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

_API_URL = "https://api.garupa.jp/api/application"
_ITUNES_URL = "https://itunes.apple.com/jp/lookup?bundleId=jp.co.craftegg.band"
_REQUEST_TIMEOUT = 15
_ITUNES_TIMEOUT = 10


def _decrypt_aes(ciphertext: bytes) -> bytes:
    """AES-CBC 解密（无 padding）"""
    backend = default_backend()
    cipher = Cipher(algorithms.AES(cdn.aes_key), modes.CBC(cdn.aes_iv), backend=backend)
    decryptor = cipher.decryptor()
    return decryptor.update(ciphertext) + decryptor.finalize()


def _read_varint(buffer: bytes, offset: int) -> tuple:
    """读取 protobuf varint，返回 (value, new_offset)"""
    value = 0
    shift = 0
    while offset < len(buffer):
        byte = buffer[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if (byte & 0x80) == 0:
            return value, offset
        shift += 7
    raise ValueError("Varint 溢出或缓冲区不完整")


def _parse_protobuf_simple(buffer: bytes) -> dict:
    """仅提取顶层字符串字段的轻量 protobuf 解析器

    不做深度 Message 嵌套解析——只够从 AppGetResponse 中拿到
    dataVersion, clientVersion 等顶层标量字段。
    """
    result = {}
    offset = 0
    buflen = len(buffer)

    while offset < buflen:
        try:
            key_val, offset = _read_varint(buffer, offset)
        except (ValueError, IndexError):
            break

        if key_val == 0:
            break

        field_num = key_val >> 3
        wire_type = key_val & 0x07

        if wire_type == 0:  # Varint
            try:
                val, offset = _read_varint(buffer, offset)
            except (ValueError, IndexError):
                break
            result[field_num] = val

        elif wire_type == 2:  # Length-delimited
            try:
                length, offset = _read_varint(buffer, offset)
            except (ValueError, IndexError):
                break
            if length < 0 or offset + length > buflen:
                break
            inner = buffer[offset : offset + length]
            offset += length
            try:
                result[field_num] = inner.decode("utf-8")
            except UnicodeDecodeError:
                result[field_num] = inner

        elif wire_type == 1:  # 64-bit
            if offset + 8 > buflen:
                break
            result[field_num] = struct.unpack("<d", buffer[offset : offset + 8])[0]
            offset += 8

        elif wire_type == 5:  # 32-bit
            if offset + 4 > buflen:
                break
            result[field_num] = struct.unpack("<f", buffer[offset : offset + 4])[0]
            offset += 4

        else:
            break

    return result


# ---------- 公开 API ----------

def get_latest_client_version() -> str:
    """从 iTunes API 自动获取日服最新客户端版本号，如 ``"10.1.2"``。

    失败时回退到 ``.env`` 中的 ``CLIENT_VERSION_FALLBACK``。
    """
    try:
        logger.info("从 iTunes 获取最新客户端版本 …")
        resp = requests.get(
            _ITUNES_URL,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            timeout=_ITUNES_TIMEOUT,
            verify=False,
        )
        resp.raise_for_status()
        data = resp.json()
        version = data.get("results", [{}])[0].get("version", "")
        if version:
            logger.info("iTunes 客户端版本: %s", version)
            return version
    except Exception as e:
        logger.warning("iTunes 查询失败: %s，使用 fallback", e)

    fallback = cdn.client_version_fallback
    logger.info("使用 fallback 客户端版本: %s", fallback)
    return fallback


def get_data_version(client_version: str | None = None) -> str:
    """获取最新 ``dataVersion``，如 ``"10.1.0.190"``。

    先尝试官方 API，失败则回退到 ``.env`` 中的 ``DATA_VERSION_FALLBACK``。

    Parameters
    ----------
    client_version:
        客户端版本号（``X-ClientVersion`` 头）。默认自动从 iTunes 获取。

    Returns
    -------
    str
        数据版本号。
    """
    if client_version is None:
        client_version = get_latest_client_version()

    headers = {
        "User-Agent": "UnityPlayer/2022.3.62f1 (UnityWebRequest/1.0, libcurl/8.10.1-DEV)",
        "Accept": "application/octet-stream",
        "Content-Type": "application/octet-stream",
        "X-ClientVersion": client_version,
        "X-ClientPlatform": "Android",
        "X-Unity-Version": "2022.3.62f1",
    }

    try:
        logger.info("正在请求官方 API 获取 dataVersion …")
        resp = requests.get(_API_URL, headers=headers, timeout=_REQUEST_TIMEOUT, verify=False)
        resp.raise_for_status()
        plaintext = _decrypt_aes(resp.content)
        parsed = _parse_protobuf_simple(plaintext)
        logger.debug("API 响应字段: %s", parsed)

        data_ver = parsed.get(2)
        if data_ver:
            logger.info("当前 dataVersion: %s", data_ver)
            return data_ver
    except Exception as e:
        logger.warning("官方 API 获取 dataVersion 失败: %s", e)

    fallback = cdn.data_version_fallback
    if fallback:
        logger.info("使用 fallback dataVersion: %s", fallback)
        return fallback
    raise RuntimeError("无法获取 dataVersion，且未配置 DATA_VERSION_FALLBACK")


def get_full_application_response(client_version: str | None = None) -> dict:
    """获取并解密完整的 API 响应（所有顶层字段）。

    调试用，一般只需 ``get_data_version()``。
    """
    headers = {
        "User-Agent": "UnityPlayer/2022.3.62f1 (UnityWebRequest/1.0, libcurl/8.10.1-DEV)",
        "Accept": "application/octet-stream",
        "Content-Type": "application/octet-stream",
        "X-ClientVersion": client_version,
        "X-ClientPlatform": "Android",
        "X-Unity-Version": "2022.3.62f1",
    }

    resp = requests.get(_API_URL, headers=headers, timeout=_REQUEST_TIMEOUT, verify=False)
    resp.raise_for_status()
    plaintext = _decrypt_aes(resp.content)
    return _parse_protobuf_simple(plaintext)
