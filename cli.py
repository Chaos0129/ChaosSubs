#!/usr/bin/env python3
"""ChaosSubs CLI — Video subtitle extraction & Chinese translation."""
import os
import shutil
import signal
import subprocess
import sys
import webbrowser

PID_FILE = os.path.expanduser("~/.chaossubs/chaossubs.pid")
VERSION = "0.1.0"


def check_dependency(name, check_cmd):
    """Check if a system dependency is available."""
    try:
        subprocess.run(check_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def check_ollama_model(model_name):
    """Check if an Ollama model is pulled."""
    try:
        result = subprocess.run(["ollama", "list"], capture_output=True, text=True)
        return model_name in result.stdout
    except FileNotFoundError:
        return False


def check_environment():
    """Check all dependencies and print status."""
    print("ChaosSubs - 环境检查\n")

    checks = [
        ("FFmpeg", check_dependency("ffmpeg", ["ffmpeg", "-version"])),
        ("Ollama", check_dependency("ollama", ["ollama", "--version"])),
    ]

    # Check Ollama model
    ollama_ok = checks[1][1]
    if ollama_ok:
        model_ok = check_ollama_model("qwen2.5:14b")
        checks.append(("翻译模型 (qwen2.5:14b)", model_ok))
    else:
        checks.append(("翻译模型 (qwen2.5:14b)", False))

    # Check Whisper model
    try:
        from faster_whisper import WhisperModel
        cache_dir = os.path.expanduser("~/.cache/huggingface/hub")
        whisper_ok = any("whisper-large-v3" in d for d in os.listdir(cache_dir)) if os.path.exists(cache_dir) else False
    except ImportError:
        whisper_ok = False
    checks.append(("Whisper 模型 (large-v3)", whisper_ok))

    all_ok = True
    for name, ok in checks:
        status = "OK" if ok else "未安装"
        symbol = "+" if ok else "-"
        print(f"  [{symbol}] {name:30s} {status}")
        if not ok:
            all_ok = False

    print()

    if not all_ok:
        print("缺少依赖，请按以下步骤安装：\n")
        if not checks[0][1]:
            print("  brew install ffmpeg")
        if not checks[1][1]:
            print("  brew install ollama")
            print("  brew services start ollama")
        if ollama_ok and not checks[2][1]:
            print("  ollama pull qwen2.5:14b")
        if not checks[3][1]:
            print('  chaossubs start  # 首次启动会自动下载 Whisper 模型')
        print()
    else:
        print("所有依赖已就绪！\n")

    return all_ok


def _save_pid():
    os.makedirs(os.path.dirname(PID_FILE), exist_ok=True)
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))


def _read_pid():
    if not os.path.exists(PID_FILE):
        return None
    try:
        with open(PID_FILE) as f:
            pid = int(f.read().strip())
        # Check if process is running
        os.kill(pid, 0)
        return pid
    except (ValueError, ProcessLookupError, PermissionError):
        os.remove(PID_FILE)
        return None


def _remove_pid():
    if os.path.exists(PID_FILE):
        os.remove(PID_FILE)


def cmd_start(host="0.0.0.0", port=8000):
    """Start the web server."""
    existing = _read_pid()
    if existing:
        print(f"ChaosSubs 已在运行中 (PID: {existing})")
        print(f"访问 http://localhost:{port}")
        print("如需停止，运行: chaossubs stop")
        return

    print("ChaosSubs 启动中...\n")

    if not check_environment():
        print("请先安装缺少的依赖。")
        sys.exit(1)

    _save_pid()
    print(f"服务地址: http://localhost:{port}\n")
    webbrowser.open(f"http://localhost:{port}")

    try:
        import uvicorn
        uvicorn.run("app.main:app", host=host, port=port)
    finally:
        _remove_pid()


def cmd_stop():
    """Stop the running server."""
    pid = _read_pid()
    if not pid:
        print("ChaosSubs 未在运行")
        return

    try:
        os.kill(pid, signal.SIGTERM)
        print(f"ChaosSubs 已停止 (PID: {pid})")
    except ProcessLookupError:
        print("ChaosSubs 未在运行")
    finally:
        _remove_pid()


def cmd_clean():
    """Clean all historical job data."""
    from app.config import UPLOAD_DIR
    if not UPLOAD_DIR.exists():
        print("没有需要清理的数据")
        return

    items = list(UPLOAD_DIR.iterdir())
    if not items:
        print("没有需要清理的数据")
        return

    total_size = sum(
        f.stat().st_size for item in items for f in item.rglob("*") if f.is_file()
    )
    size_mb = total_size / (1024 * 1024)

    print(f"发现 {len(items)} 个任务，共占用 {size_mb:.1f} MB")
    confirm = input("确认清理？(y/N) ").strip().lower()
    if confirm == "y":
        for item in items:
            shutil.rmtree(item)
        print("清理完成")
    else:
        print("已取消")


def cmd_version():
    print(f"ChaosSubs v{VERSION}")


def main():
    args = sys.argv[1:]

    if not args or args[0] in ("-h", "--help", "help"):
        print(f"ChaosSubs v{VERSION} - 视频字幕提取 & 中文翻译\n")
        print("用法:")
        print("  chaossubs start            启动 Web 服务并打开浏览器")
        print("  chaossubs start -p 9000    指定端口启动")
        print("  chaossubs stop             停止服务")
        print("  chaossubs check            检查环境依赖")
        print("  chaossubs clean            清理历史任务数据")
        print("  chaossubs version          查看版本")
        return

    cmd = args[0]

    if cmd == "start":
        port = 8000
        if "-p" in args:
            idx = args.index("-p")
            if idx + 1 < len(args):
                port = int(args[idx + 1])
        cmd_start(port=port)
    elif cmd == "stop":
        cmd_stop()
    elif cmd == "check":
        check_environment()
    elif cmd == "clean":
        cmd_clean()
    elif cmd == "version":
        cmd_version()
    else:
        print(f"未知命令: {cmd}")
        print("运行 chaossubs help 查看帮助")
        sys.exit(1)


if __name__ == "__main__":
    main()
