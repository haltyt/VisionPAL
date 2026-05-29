"""Vision PAL 共有環境変数ローダー (Python 3.6+)

優先順位: 環境変数 > 隣の .env > 引数の default

使い方:
    from vp_env import env, env_int, env_float
    MQTT_HOST = env("MQTT_HOST", "192.168.3.12")
    MQTT_PORT = env_int("MQTT_PORT", 1883)

`.env` 探索順:
    1. 現在の作業ディレクトリ ./.env
    2. このファイル (vp_env.py) と同じディレクトリの .env
    3. このファイルの親ディレクトリの .env (リポジトリルート想定)
"""
import os
from pathlib import Path


def _load_dotenv(path):
    """`.env` 形式ファイルを読み、既存環境変数を上書きしない形で適用"""
    if not path.exists():
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:
        print("[vp_env] failed to read {}: {}".format(path, e))
        return False
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        # quoted value を剥がす
        if (value.startswith('"') and value.endswith('"')) or \
           (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value
    print("[vp_env] loaded: {}".format(path))
    return True


_here = Path(__file__).resolve().parent
for _candidate in [Path.cwd() / ".env", _here / ".env", _here.parent / ".env"]:
    if _load_dotenv(_candidate):
        break


def env(key, default=None):
    """文字列として環境変数を取得"""
    return os.environ.get(key, default)


def env_int(key, default):
    """整数として取得、失敗時は default"""
    try:
        return int(os.environ[key])
    except (KeyError, ValueError):
        return default


def env_float(key, default):
    """浮動小数点として取得、失敗時は default"""
    try:
        return float(os.environ[key])
    except (KeyError, ValueError):
        return default
