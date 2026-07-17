#!/usr/bin/env python3
"""
LLM 统一配置与调用模块

支持：
  - 本地 Ollama（自动检测）
  - OpenAI 兼容 API（DeepSeek / SiliconFlow / OpenAI / 等）

用法：
  python llm_config.py              # 交互式配置
  python llm_config.py --status     # 查看当前配置
  python llm_config.py --test       # 测试当前配置的连通性

环境变量（优先级高于配置文件）：
  LLM_PROVIDER    auto / ollama / openai / deepseek / siliconflow
  LLM_API_KEY     API Key
  LLM_MODEL       模型名称
  LLM_API_BASE    API 地址（仅云端）
  OLLAMA_HOST     Ollama 地址（默认 http://localhost:11434）

配置保存位置：llm_config.json（项目根目录）
"""

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

# ============================================================
#  路径与默认配置
# ============================================================

BASE_DIR = Path(__file__).parent.resolve()
CONFIG_FILE = BASE_DIR / "llm_config.json"

DEFAULT_CONFIG = {
    "provider": "auto",
    "ollama": {
        "host": "http://localhost:11434",
        "model": "qwen2.5:7b",
    },
    "openai": {
        "api_key": "",
        "api_base": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
    },
    "deepseek": {
        "api_key": "",
        "api_base": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
    },
    "siliconflow": {
        "api_key": "",
        "api_base": "https://api.siliconflow.cn/v1",
        "model": "Qwen/Qwen2.5-7B-Instruct",
    },
}

# 可读的中文名称
PROVIDER_NAMES = {
    "ollama": "本地 Ollama",
    "openai": "OpenAI",
    "deepseek": "DeepSeek",
    "siliconflow": "SiliconFlow",
}

# ============================================================
#  配置管理
# ============================================================


def load_config() -> dict:
    """加载配置文件，缺失字段用默认值补充"""
    config = DEFAULT_CONFIG.copy()
    if CONFIG_FILE.exists():
        try:
            saved = json.loads(CONFIG_FILE.read_text("utf-8"))
            for k, v in saved.items():
                if k in config and isinstance(v, dict) and isinstance(config[k], dict):
                    config[k].update(v)
                else:
                    config[k] = v
        except Exception:
            pass
    return config


def save_config(config: dict):
    """保存配置文件"""
    CONFIG_FILE.write_text(json.dumps(config, ensure_ascii=False, indent=2), "utf-8")
    print(f"[OK] 配置已保存: {CONFIG_FILE}")


def resolve_config() -> dict:
    """解析最终生效的配置（配置 + 环境变量覆盖）"""
    cfg = load_config()
    provider = os.environ.get("LLM_PROVIDER", cfg.get("provider", "auto"))
    cfg["provider"] = provider

    if provider == "ollama" or provider == "auto":
        ollama_host = os.environ.get("OLLAMA_HOST", cfg["ollama"]["host"])
        ollama_model = os.environ.get("LLM_MODEL", cfg["ollama"]["model"])
        cfg["ollama"]["host"] = ollama_host
        cfg["ollama"]["model"] = ollama_model

    if provider != "ollama" and provider != "auto":
        # 云端：都用 OpenAI 兼容接口
        provider_cfg = cfg.get(provider, {})
        cfg["_cloud"] = {
            "api_key": os.environ.get("LLM_API_KEY", provider_cfg.get("api_key", "")),
            "api_base": os.environ.get("LLM_API_BASE", provider_cfg.get("api_base", "")),
            "model": os.environ.get("LLM_MODEL", provider_cfg.get("model", "")),
        }

    return cfg


# ============================================================
#  Ollama 检测
# ============================================================


def check_ollama(host: str = None) -> tuple[bool, str]:
    """检测 Ollama 是否运行，返回 (是否可用, 信息)"""
    host = host or load_config()["ollama"]["host"]
    try:
        url = f"{host}/api/tags"
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read())
        models = [m["name"] for m in data.get("models", [])]
        if models:
            return True, f"Ollama 运行中（模型: {', '.join(models[:3])}）"
        return True, f"Ollama 运行中（无模型）"
    except Exception as e:
        return False, f"Ollama 未连接（{host}）: {e}"


def get_ollama_model(host: str = None) -> str | None:
    """获取 Ollama 中可用的最佳模型"""
    host = host or load_config()["ollama"]["host"]
    try:
        url = f"{host}/api/tags"
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read())
        models = [m["name"] for m in data.get("models", [])]
        if not models:
            return None
        # 优先用配置的模型
        preferred = load_config()["ollama"]["model"]
        for m in models:
            if preferred in m:
                return m
        return models[0]
    except Exception:
        return None


# ============================================================
#  统一调用接口
# ============================================================


class LLMError(Exception):
    pass


def check_llm() -> bool:
    """检测当前配置的 LLM 是否可用（返回 True/False）"""
    cfg = resolve_config()
    provider = cfg["provider"]
    if provider == "auto":
        ok, _ = check_ollama()
        if ok:
            return True
        # auto 且无 Ollama：不自动尝试云端，留用户选择
        return False
    elif provider == "ollama":
        ok, _ = check_ollama(cfg["ollama"]["host"])
        return ok
    else:
        # 云端：短调用测试
        try:
            llm_chat([{"role": "user", "content": "ok"}], temperature=0)
            return True
        except Exception:
            return False


def current_model_name() -> str:
    """获取当前生效的模型名称（用于报告/显示）"""
    cfg = resolve_config()
    p = cfg.get("provider", "auto")
    if p == "auto":
        ok, _ = check_ollama()
        if ok:
            p = "ollama"
        else:
            cloud = cfg.get("_cloud", {})
            return cloud.get("model", "unknown")
    if p == "ollama":
        return cfg.get("ollama", {}).get("model", "qwen2.5:7b")
    cloud = cfg.get("_cloud", {})
    return cloud.get("model", p)


def llm_chat(messages: list[dict], temperature: float = 0.1) -> str:
    """统一 LLM 调用入口，根据配置选择后端。

    Args:
        messages: [{"role": "user"/"system", "content": "..."}]
        temperature: 温度参数

    Returns:
        模型返回的文本内容

    Raises:
        LLMError: 调用失败时抛出
    """
    cfg = resolve_config()
    provider = cfg["provider"]

    # auto 模式：优先 Ollama，不可用时报错让用户选择
    if provider == "auto":
        ollama_ok, _ = check_ollama(cfg["ollama"]["host"])
        if ollama_ok:
            provider = "ollama"
        else:
            raise LLMError(
                "Ollama 未运行，且 provider 设为 auto。\n"
                "请选择:\n"
                "  1. 启动本地 Ollama: ollama serve\n"
                "  2. 切换为云端: python llm_config.py"
            )

    if provider == "ollama":
        return _ollama_chat(messages, temperature, cfg)
    else:
        return _cloud_chat(messages, temperature, cfg)


def _ollama_chat(messages: list[dict], temperature: float, cfg: dict) -> str:
    """调用本地 Ollama"""
    host = cfg["ollama"]["host"]
    model = cfg["ollama"]["model"]
    url = f"{host}/api/chat"
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": temperature},
    }
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=300) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        content = result.get("message", {}).get("content", "")
        if not content:
            raise LLMError("Ollama 返回空内容")
        return content
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:200]
        raise LLMError(f"Ollama HTTP {e.code}: {body}")
    except urllib.error.URLError as e:
        raise LLMError(f"Ollama 连接失败 ({host}): {e.reason}")


def _cloud_chat(messages: list[dict], temperature: float, cfg: dict) -> str:
    """调用 OpenAI 兼容接口（支持 DeepSeek / SiliconFlow / OpenAI 等）"""
    cloud = cfg.get("_cloud", {})
    api_key = cloud.get("api_key", "")
    api_base = cloud.get("api_base", "")
    model = cloud.get("model", "")

    if not api_key:
        raise LLMError(f"API Key 未设置，请配置或设环境变量 LLM_API_KEY")
    if not api_base:
        raise LLMError(f"API 地址未设置")
    if not model:
        raise LLMError(f"模型未设置")

    url = f"{api_base.rstrip('/')}/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=300) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
        if not content:
            raise LLMError("云端 API 返回空内容")
        return content
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:300]
        raise LLMError(f"API HTTP {e.code}: {body}")
    except urllib.error.URLError as e:
        raise LLMError(f"API 连接失败 ({api_base}): {e.reason}")


# ============================================================
#  CLI 交互配置 & 状态查看
# ============================================================


def cmd_status():
    """查看当前配置和运行状态"""
    cfg = resolve_config()
    provider = cfg["provider"]

    print("=" * 50)
    print("  LLM 配置状态")
    print("=" * 50)
    print(f"  当前选择: {PROVIDER_NAMES.get(provider, provider)} ({provider})")

    if provider == "auto":
        ollama_ok, msg = check_ollama()
        print(f"  Ollama: {'✅' if ollama_ok else '❌'} {msg}")
        if not ollama_ok:
            print()
            print("  auto 模式下未检测到 Ollama，请选择:")
            print("    1. 启动 Ollama: ollama serve")
            print("    2. 切换云端:   python llm_config.py")
    elif provider == "ollama":
        ollama_ok, msg = check_ollama(cfg["ollama"]["host"])
        print(f"  Ollama: {'✅' if ollama_ok else '❌'} {msg}")
        print(f"  地址: {cfg['ollama']['host']}")
        print(f"  模型: {cfg['ollama']['model']}")
    else:
        cloud = cfg.get("_cloud", {})
        print(f"  提供商: {PROVIDER_NAMES.get(provider, provider)}")
        print(f"  接口地址: {cloud.get('api_base', '未设置')}")
        print(f"  模型: {cloud.get('model', '未设置')}")
        print(f"  API Key: {'已设置' if cloud.get('api_key') else '❌ 未设置'}")

    print()
    print(f"  配置文件: {CONFIG_FILE}")
    print("  环境变量可覆盖: LLM_PROVIDER, LLM_API_KEY, LLM_MODEL, LLM_API_BASE")
    print("=" * 50)


def cmd_test():
    """测试当前配置的连通性"""
    print("测试 LLM 连通性...")
    try:
        resp = llm_chat([
            {"role": "user", "content": "回复「OK」两个字即可"}
        ], temperature=0)
        print(f"✅ 调用成功")
        print(f"   回复: {resp[:100]}")
    except LLMError as e:
        print(f"❌ 调用失败: {e}")


def cmd_configure():
    """交互式配置"""
    cfg = load_config()

    print("=" * 50)
    print("  LLM 配置")
    print("=" * 50)
    print()

    # 检测 Ollama
    ollama_ok, ollama_msg = check_ollama()
    print(f"  [1] 本地 Ollama {'(✅ 运行中)' if ollama_ok else '(❌ 未运行)'}")
    if ollama_ok:
        model = get_ollama_model()
        if model:
            print(f"      检测到模型: {model}")
    print(f"  [2] DeepSeek（deepseek-chat）")
    print(f"  [3] SiliconFlow（国内多模型）")
    print(f"  [4] OpenAI（GPT 系列）")
    print(f"  [5] 其他 OpenAI 兼容接口")
    print(f"  [6] 自动模式（优先 Ollama，不可用则报错）")
    print()

    choices = {
        "1": "ollama",
        "2": "deepseek",
        "3": "siliconflow",
        "4": "openai",
        "5": "custom",
        "6": "auto",
    }

    sel = input("请选择 (1-6): ").strip()
    provider = choices.get(sel)
    if not provider:
        print("无效选择")
        return

    cfg["provider"] = provider

    if provider == "ollama":
        host = input(f"  Ollama 地址 [{cfg['ollama']['host']}]: ").strip()
        if host:
            cfg["ollama"]["host"] = host
        model = input(f"  模型名 [{cfg['ollama']['model']}]: ").strip()
        if model:
            cfg["ollama"]["model"] = model

    elif provider in ("deepseek", "siliconflow", "openai"):
        defaults = cfg[provider]
        key = input(f"  API Key: ").strip()
        if key:
            cfg[provider]["api_key"] = key
        model = input(f"  模型 [{defaults['model']}]: ").strip()
        if model:
            cfg[provider]["model"] = model
        base = input(f"  API 地址 [{defaults['api_base']}]: ").strip()
        if base:
            cfg[provider]["api_base"] = base

    elif provider == "custom":
        key = input(f"  API Key: ").strip()
        base = input(f"  API 地址 (完整 URL，如 https://xxx.com/v1): ").strip()
        model = input(f"  模型名: ").strip()
        # 存到 custom 字段
        cfg["custom"] = {
            "api_key": key,
            "api_base": base,
            "model": model,
        }
        cfg["provider"] = "custom"
        # 确保 PROVIDER_NAMES 里有
        PROVIDER_NAMES["custom"] = "自定义"

    elif provider == "auto":
        # auto 模式不需要额外配置
        pass

    save_config(cfg)
    print()
    cmd_status()


# ============================================================
#  入口
# ============================================================


def main():
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg == "--status":
            cmd_status()
        elif arg == "--test":
            cmd_test()
        elif arg == "--config":
            cmd_configure()
        else:
            print(f"用法: python llm_config.py [--status|--test|--config]")
    else:
        cmd_configure()


if __name__ == "__main__":
    main()
