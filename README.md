# BiliCollector
B站收藏夹数据采集 + 本地 AI 分析 + 成分文案生成。
全本地运行，数据不经过第三方服务器。
## 流程
web_gui.py  (http://127.0.0.1:18234)
     │
     ├─ 1. Login Bilibili  ← 扫码登录
     │
     ├─ 2. Start Collection
     │      └─ Playwright 爬收藏夹 → JSON
     │
     ├─ 3. Generate Report
     │      └─ Ollama (qwen2.5:7b) → 兴趣画像 JSON
     │
     └─ 4. Generate Copy
            └─ Ollama → 成分分析文案 + 视频侧边栏
## 快速开始

```bash
# 一键启动（自动处理依赖）
python web_gui.py

# 如果采集完成后同时发送原始数据到另一台机器
python web_gui.py --send-url http://192.168.1.100:18236/

restart(linux):kill 7714 2>/dev/null; sleep 1; source venv/bin/activate && setsid python3 web_gui.py > /tmp/bili_webgui.log 2>&1 & disown

```

打开 `http://127.0.0.1:18234/`，三步操作：

1. **Login Bilibili** — 扫码登录
2. **Start Collection** — 爬取收藏夹视频
3. **Generate Report** → **Generate Copy** — Ollama 分析 + 生成文案

## 环境要求

- Python 3.10+
- Chrome / Chromium / Edge 浏览器（用于登录和采集）
- Ollama + 模型（用于 AI 分析，可选）

### Ollama 安装

```bash
# 安装 https://ollama.com
# 拉取模型
ollama pull qwen2.5:7b
# 启动
ollama serve
```

可通过环境变量配置：
我们希望你可以通过自己的ollama运行，当然也可以接上云端大模型api.
```bash
export OLLAMA_HOST=http://localhost:11434
export OLLAMA_MODEL=qwen2.5:7b
```

## 输出格式

### 分析报告 (`analysis_report_{uid}.json`)

```json
{
  "uid": "用户ID",
  "generated_at": "ISO时间",
  "data_scope": {"videos": 88, "favorites": 5, "dynamics": 0},
  "videos": [
    {"title": "视频标题", "author": "UP主", "plays": "播放量",
     "link": "BV链接", "favorite": "所属收藏夹"}
  ],
  "user_profile": {
    "domains": ["偏好领域"],
    "keywords": ["关键词"],
    "summary": "兴趣画像总结"
  }
}
```

### 成分文案 (`copy_{uid}.json`)

```json
{
  "labels": ["CS2爱好者", "游戏开发与优化"],
  "summary": "一句话分类概括",
  "content": "完整成分分析文案"
}
```

## 发送到另一台机器（可选）

爬虫机采集 + 分析完成后，可将原始报告 JSON 发送到文案生成机：

**接收端（文案机）:**

```bash
python recv.py --port 18236 --dir "C:/path/to/inbox"
```

**发送端（本机）:**

```bash
python web_gui.py --send-url http://192.168.1.100:18236/
```

## 文件结构

```
bili-collector/
├── web_gui.py                   # 主界面（登录 → 采集 → 分析 → 文案）
├── analyze.py                   # Ollama 兴趣分析 + 成分文案生成
├── bilbil.py                    # 收藏夹爬虫
├── bili_dynamic_crawler_simple.py  # 转发动态爬虫
├── bili_common.py               # 共享库（登录、浏览器、收藏夹API）
├── submit_client.py             # HTTP 传输客户端
├── recv.py                      # 接收端（文案机用）
├── recv_back.py                 # 回传接收端
├── analyze_server.py            # （备用）FastAPI 分析服务器
├── start.py / start.sh / start.bat  # 启动器
├── requirements.txt
└── README.md
```

## 手动安装依赖

```bash
pip install -r requirements.txt
playwright install chromium
```

## 清除数据 / 切换账号

网页左上角 **Clear All Data** 按钮，或删除本地目录：

```bash
rm -rf user_data_* data_* dynamics_* bili_uid.txt
```
