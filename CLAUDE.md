# 邦邦剧情翻译流水线

从 BanG Dream! Girls Band Party! 游戏 CDN 获取活动故事文本，提取为 Excel。

## 快速开始

```bash
# 1. 下载活动 335 的故事（中间文件 → tmp/335_story/）
python fetch_event_stories.py 335

# 2. 提取为 Excel（输出 → out/335机翻剧情/，中间文件自动清理）
python extract_story.py -d tmp/335_story
```

设 `.env` 中 `KEEP_TEMP=true` 可保留中间 JSON 文件调试。

## 配置（.env）

所有配置集中在项目根目录 `.env` 文件中。

### CDN / 游戏资源

```
UNITY_VERSION=2022.3.62f1       # Unity 版本
AES_KEY=（.env 中配置）          # API 解密密钥
AES_IV=（.env 中配置）           # API 解密 IV
CLIENT_VERSION=10.1.2           # 客户端版本（游戏更新后需同步）
```

### 机翻

```
MT_ENABLED=false                # 是否启用（true/false）
MT_API_FORMAT=openai            # openai 或 anthropic
MT_BASE_URL=https://api.openai.com/v1
MT_API_KEY=sk-your-key-here
MT_MODEL=gpt-4o-mini
MT_THINKING=false
MT_TEMPERATURE=0.3
```

### 翻译提示词

提示词在 `prompt.md` 中，可自行修改翻译风格。

## 项目结构

```
e:\TEMP\story\
  src/
    __init__.py
    config.py                 # .env 加载 → 类型化配置对象
    api.py                    # 官方 API → dataVersion（AES+protobuf）
    asset_info.py             # AssetBundleInfo 下载/解析/搜索
    downloader.py             # 通用下载器
    extractor.py              # UnityPy 解包 AssetBundle → JSON
    translator.py             # 机翻客户端（OpenAI/Anthropic）
  res/                        # 参考脚本
    req_script.py             # Reqable 代理脚本
    nga_bangdream.py          # NGA 论坛爬虫（旧方案）
    335机翻剧情/              # 参考输出样例
  fetch_event_stories.py      # CLI：下载活动故事
  extract_story.py            # CLI：JSON → 4列 Excel（可选机翻）
  prompt.md                   # 翻译提示词
  version_hash.json           # 大版本 → CDN hash 映射
  .env                        # 配置文件
  .cache/                     # AssetBundleInfo 缓存
  event_stories/              # 下载的 JSON
  {id}机翻剧情/               # 输出的 Excel
```

## fetch_event_stories.py 流程

1. 调 `api.garupa.jp/api/application` → AES 解密 → protobuf 解析 → `dataVersion`
2. `version_hash.json` 查 CDN hash → 拼 URL
3. 下载 `AssetBundleInfo`（~5.7MB）→ 解析 ~34k 路径
4. 搜索 `scenario/eventstory/event{id}` → 下载 AssetBundle
5. UnityPy 解包 → `read_typetree()` → 写出 JSON

## extract_story.py 流程

1. 解析 `Scenarioevent*-*.json` → 提取台词 + 章节标题
2. （可选）批量调用 LLM 翻译
3. 输出 `{event_id}机翻剧情/{event_id}{chapter_index:02d}.xlsx`
   - 4 列：人名 | 原文 | 人名 | 机翻
   - 每话一个文件（如 `33500.xlsx` ~ `33506.xlsx`）

## 关键技术细节

### AssetBundleInfo 格式

- protobuf 编码的二进制文本
- 解析：先找 `@<64-hex>`，向前搜最近合法路径（同 garupa-getAssets）

### Unity 版本

- 游戏用 Unity 2022.3.62f1
- UnityPy 需 `config.FALLBACK_UNITY_VERSION`

### 官方 API

- `https://api.garupa.jp/api/application`
- AES-CBC 解密（key/iv 从 .env 读取）
- 返回 protobuf，field 2 = dataVersion

### 数据格式

- `actionType`: 1=台词 2=隐藏窗口 4=特效 6=角色动作 7=章节标题
- `effectType`: 1=淡入 2=淡出 3=黑屏 4=等待 5=白屏 7=背景 8=章节标题

## 依赖

| 包             | 用途                   |
| -------------- | ---------------------- |
| `requests`     | HTTP                   |
| `cryptography` | AES 解密               |
| `UnityPy`      | Unity AssetBundle 解包 |
| `openpyxl`     | Excel 读写             |

## TODO

- [ ] 从 APK 自动提取 CDN hash
