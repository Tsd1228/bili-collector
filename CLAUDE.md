# B站收藏夹数据分析项目

## 项目简介

爬取 B站 用户收藏夹数据 → Ollama/云端 LLM 分析兴趣画像 → 生成成分分析文案。支持 Web GUI 展示。

## 核心规则（必须遵守）

### 开发流程
1. **最小代码修改** — 每次改动用最少的代码量完成功能
2. **即时测试** — 改完一个功能必须马上测试能否跑通，不累积
3. **一步一步来** — 不跳步，完成一步再下一步
4. **沙盒优先** — 所有改动先在沙盒测试，通过后再同步主项目
5. **启动脚本同步** — 改动代码后必须同步更新 start.sh / start.py / requirements.txt

### 自主边界（必须先问用户）
- 删除文件、目录或 git 历史
- 修改 .env、密钥、token、CI/CD 配置
- 数据库 schema 变更或数据迁移
- git push、git rebase、git reset --hard
- 安装新的全局依赖或修改系统配置
- 公开发布

## 项目结构

```
bili_getdata/
├── bilbil.py          # 爬虫：扫码登录 → 采集收藏夹 → 提取fav_time
├── analyze.py         # 分析：读取JSON → LLM兴趣画像 → 加权分析 → 导出
├── bili_common.py     # 通用工具：登录、UID管理、浏览器管理、API调用
├── llm_config.py      # LLM统一配置：Ollama/DeepSeek/SiliconFlow/OpenAI切换
├── web_gui.py         # Web界面展示报告
├── start.py           # 启动入口
├── start.sh           # Shell启动脚本
├── requirements.txt   # Python依赖
└── llm_config.json    # LLM配置（用户选择后生成）
```

## 数据流

```
扫码登录 → 获取UID → 采集收藏夹(fav_time) → JSON(data_{uid}/)
  → analyze.py → JSON报告(analysis_report_{uid}.json)
    → --copy 生成文案(copy_{uid}.json)
    → --export 导出可读文本
```

## 关键文件说明

### bilbil.py — 爬虫
- `collect_favorites()`: 主入口，参数 uid/visible/manual/reset/fav_name/incremental
- `fetch_fav_times()`: 通过 API 获取每个视频的收藏时间戳
- `extract_bvid()`: 从链接提取 BV id
- 数据输出: `data_{uid}/{收藏夹名}.json`，每个视频含 fav_time 字段
- 增量模式: `--incremental` 按 link 去重合并

### analyze.py — 分析
- `build_report(uid)`: 生成完整 JSON 报告
- 加权字段: play_stats / favorite_breakdown / monthly_breakdown / weighted_domains
- `plays_weight(plays_num)`: 对数权重 `log10(plays + 1)`
- `parse_plays(plays_str)`: B站播放量文本解析（"623.8万" → 6238000）
- 兴趣分析: 分 batch 送入 LLM，播放量加权汇总
- `generate_copy(uid)`: 基于报告生成成分分析文案
- `export_report(uid, output_path)`: 导出人类可读文本报告
- CLI: `--copy` `--export` `--output` `--uid`

### bili_common.py — 通用
- `do_login()` / `get_uid()`: 扫码登录或读取已有 UID
- `fetch_favorites()`: 获取收藏夹列表（创建+收藏）
- `is_folder_private()`: 判断收藏夹是否私密（attr & 1）
- `scroll_to_bottom()`: 滚动加载全部内容
- `create_browser_context()`: 浏览器上下文（优先本地浏览器）

### llm_config.py — LLM统一模块
- `llm_chat(messages, temperature)`: 统一调用入口
- `resolve_config()`: 环境变量覆盖配置
- `check_llm()`: 检测当前配置可用性
- 支持 provider: ollama / deepseek / siliconflow / openai / custom / auto
- 环境变量: LLM_PROVIDER / LLM_API_KEY / LLM_MODEL / LLM_API_BASE / OLLAMA_HOST
- 配置保存在 llm_config.json

## 测试命令

```bash
# 完整流程
python bilbil.py                      # 爬取（首次需扫码）
python bilbil.py --incremental        # 增量更新
python analyze.py                     # 分析
python analyze.py --copy              # 生成文案
python analyze.py --export            # 导出可读报告
python llm_config.py --status         # 查看LLM状态
python llm_config.py --config         # 配置LLM
python web_gui.py                     # 启动Web界面

# 数据目录按UID隔离: data_{uid}/
```

## 已知限制
- web_gui.py 未完全适配加权分析新字段
- 无单元测试框架
- 扫码登录的 QR 扫描 loop 无超时
