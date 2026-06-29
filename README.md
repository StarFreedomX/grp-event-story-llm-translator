# 邦邦剧情翻译流水线

从 BanG Dream! Girls Band Party! 游戏 CDN 获取活动故事，可选 AI 机翻，输出 Excel。

## 快速开始

```bash
# 1. 配置（交互式 TUI，自动检测/安装依赖）
python setup.py

# 2. 下载故事（自动获取最新游戏版本）
python fetch_event_stories.py 335

# 3. 生成 Excel（带机翻需先在 .env 配置 API Key）
python extract_story.py 335
```

也可双击运行 `.bat`（Windows）或 `.sh`（Linux/Mac）：

- `配置.bat` / `配置.sh`
- `获取.bat 335` / `获取.sh 335`
- `翻译.bat 335` / `翻译.sh 335`

## 常用用法

```bash
# 不传参，运行后输入
python fetch_event_stories.py          # 提示输入活动 ID
python extract_story.py                # 提示输入活动 ID（可带话）

# 指定话（从 0 开始）
python extract_story.py 335 2          # 仅第 2 话
python extract_story.py 335 2 3 4      # 第 2、3、4 话

# 只提取原文不机翻（机翻栏留空）
python extract_story.py 335 --no-mt
```

## 配置

`.env` 中必填：

```bash
AES_KEY=（Garupa的密钥）
AES_IV=（Garupa的IV）
```

机翻（可选）：

```bash
MT_ENABLED=true
MT_PROVIDER=deepseek
MT_API_KEY=sk-xxx
MT_MODEL=deepseek-v4-flash
```

翻译提示词：`prompt.md`（主提示词），`.env` 中 `MT_FURTHER_PROMPT_FILE` 可指定额外提示词文件名，留空则不追加。

## `version_hash.json`

大版本 → CDN hash 的映射，用于拼接 AssetBundleInfo 下载地址。游戏大版本更新时 hash 可能会刷新，目前需通过抓包等方式自行获取新的 hash 后手动更新此文件。

> 注意，这个版本号是看的游戏里"选项-支持-游戏运行-划到底的端末情报"中，`10.1.2-10.1.0.190`的数据版本号`10.1.0.190`的前两组数字

## 输出

```
out/{id}机翻剧情/
  {id}00.xlsx    # 第 0 话（Opening）
  {id}01.xlsx    # 第 1 话
  ...
```

Excel 四列：`人名 | 原文 | 人名 | 机翻`。

## 项目结构

```
src/
  api.py          iTunes 自动获取客户端版本 + 官方 API 获取 dataVersion
  asset_info.py   CDN AssetBundleInfo 下载/解析/搜索
  downloader.py   通用文件下载器
  extractor.py    UnityPy 解包 AssetBundle → JSON
  config.py       .env 配置加载
  translator.py   AI 机翻客户端
fetch_event_stories.py   下载活动故事
extract_story.py         JSON → Excel（可选机翻、可选话）
setup.py                 配置向导（TUI）
prompt.md                翻译提示词
.env.example             配置模板
version_hash.json        大版本 → CDN hash 映射
```
