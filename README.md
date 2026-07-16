# B站数据采集工具

采集 B站收藏夹和动态数据。

## 快速开始

### Windows
双击 `start.bat`

### Linux / macOS
```bash
./start.sh
```

首次运行会自动安装依赖，之后直接启动图形界面。

## 环境要求

- Python 3.10+
- Chrome 或 Edge 浏览器

## 手动安装

如果自动安装失败：

```bash
pip install playwright aiohttp
```

## 文件结构

```
bili-collector/
├── start.bat              # Windows 启动器
├── start.sh               # Linux/macOS 启动器
├── start.py               # 通用启动器
├── web_gui.py             # 图形界面
├── run.py                 # 命令行版
├── README.md
├── requirements.txt
├── bili_common.py         # 核心模块
├── bilbil.py              # 收藏夹采集
├── bili_dynamic_crawler_simple.py  # 动态采集
└── data_interface.py      # 数据接口
```

## 数据说明

| 目录 | 说明 |
|------|------|
| `data_{UID}/` | 收藏夹视频数据 |
| `dynamics_{UID}/` | 动态数据 |
| `user_data_{UID}/` | 浏览器登录态 |

数据默认保存在程序所在目录，不会污染用户目录。

## 常见问题

| 问题 | 解决 |
|------|------|
| Python not found | 安装 Python 并勾选 Add to PATH |
| 浏览器打不开 | 确保已安装 Chrome 或 Edge |
| 下载 Chromium 失败 | 设置镜像：`set PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright` |
| 换号采集 | 运行 `python run.py --login` |
