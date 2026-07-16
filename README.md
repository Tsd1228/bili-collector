# B站数据采集工具

采集 B站收藏夹和动态数据。

## 环境要求

- Python 3.10+
- Chrome 或 Edge 浏览器（已安装在电脑上）

## 安装步骤

### 1. 安装 Python

下载地址：https://www.python.org/downloads/

安装时勾选 **"Add Python to PATH"**，然后点 "Install Now"。

安装完成后打开命令行（Win+R 输入 cmd），输入：
```
python --version
```
显示 `Python 3.x.x` 即成功。

### 2. 安装依赖

在命令行中运行：
```
pip install playwright aiohttp
```

### 3. 运行

#### 图形界面版（推荐）
```
python web_gui.py
```
浏览器会自动打开，按提示操作即可。

#### 命令行版
```
python run.py
```

## 使用说明

1. 首次运行会弹出浏览器，请用 B站 APP 扫码登录
2. 登录成功后，点击「开始采集」
3. 等待采集完成，数据保存在程序同级目录的 `data_你的UID/` 文件夹下

## 数据说明

采集的数据以 JSON 格式保存，包含：
- 收藏夹列表和视频信息
- 动态内容

数据存储位置：程序所在目录下的 `data_{UID}/` 文件夹

## 常见问题

### Q: 提示 "No module named 'playwright'"
A: 请运行 `pip install playwright`

### Q: 浏览器打不开
A: 请确保电脑上已安装 Chrome 或 Edge 浏览器

### Q: 扫码登录后没反应
A: 请等待页面完全加载，看到头像出现后再操作

### Q: 想换号采集
A: 运行 `python run.py --login` 可重新登录其他账号
