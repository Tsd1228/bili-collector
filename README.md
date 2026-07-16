# B站数据采集工具

采集 B站收藏夹和动态数据。

## 文件结构

```
bili-collector/
├── README.md           # 说明文档
├── requirements.txt    # 依赖列表
├── run.py              # 命令行入口
├── web_gui.py          # 图形界面入口（推荐）
├── bili_common.py      # 核心模块
├── bilbil.py           # 收藏夹采集
├── bili_dynamic_crawler_simple.py  # 动态采集
└── data_interface.py   # 数据接口
```

## 环境要求

- Python 3.10+
- Chrome 或 Edge 浏览器

## 安装步骤

### 1. 安装 Python

下载：https://www.python.org/downloads/

安装时勾选 **"Add Python to PATH"**，点 "Install Now"。

验证：打开命令行（Win+R 输入 cmd），输入：
```
python --version
```
显示 `Python 3.x.x` 即成功。

### 2. 安装依赖

```
pip install -r requirements.txt
```

或手动安装：
```
pip install playwright aiohttp
```

### 3. 运行

#### 图形界面版（推荐）
```
python web_gui.py
```
浏览器会自动打开，按提示操作。

#### 命令行版
```
python run.py
```

## 使用说明

1. 首次运行会弹出浏览器，用 B站 APP 扫码登录
2. 登录成功后，点击「开始采集」
3. 数据保存在程序目录的 `data_{UID}/` 文件夹下

## 数据说明

| 目录 | 说明 |
|------|------|
| `data_{UID}/` | 收藏夹视频数据（JSON） |
| `dynamics_{UID}/` | 动态数据（JSON） |
| `user_data_{UID}/` | 浏览器登录态 |

## 常见问题

| 问题 | 解决 |
|------|------|
| No module named 'playwright' | 运行 `pip install playwright` |
| 浏览器打不开 | 确保已安装 Chrome 或 Edge |
| 扫码登录后没反应 | 等页面完全加载，看到头像后再操作 |
| 想换号 | 运行 `python run.py --login` |
| 下载 Chromium 失败 | 设置镜像：`set PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright` |
