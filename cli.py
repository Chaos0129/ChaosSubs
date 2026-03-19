#!/usr/bin/env python3
"""ChaosSubs CLI — Video subtitle extraction & Chinese translation."""
import subprocess
import sys
import webbrowser


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
        import os
        # Check if model is cached
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
            print('  python -c "from faster_whisper import WhisperModel; WhisperModel(\'large-v3\', compute_type=\'int8\')"')
        print()

    return all_ok


def cmd_start(host="0.0.0.0", port=8000):
    """Start the web server."""
    print(f"ChaosSubs 启动中...\n")

    if not check_environment():
        print("请先安装缺少的依赖。")
        sys.exit(1)

    print(f"服务地址: http://localhost:{port}\n")
    webbrowser.open(f"http://localhost:{port}")

    import uvicorn
    uvicorn.run("app.main:app", host=host, port=port)


def cmd_version():
    print("ChaosSubs v0.1.0")


def main():
    args = sys.argv[1:]

    if not args or args[0] in ("-h", "--help", "help"):
        print("ChaosSubs - 视频字幕提取 & 中文翻译\n")
        print("用法:")
        print("  chaossubs start          启动 Web 服务")
        print("  chaossubs start -p 9000  指定端口")
        print("  chaossubs check          检查环境依赖")
        print("  chaossubs version        查看版本")
        return

    cmd = args[0]

    if cmd == "start":
        port = 8000
        if "-p" in args:
            idx = args.index("-p")
            if idx + 1 < len(args):
                port = int(args[idx + 1])
        cmd_start(port=port)
    elif cmd == "check":
        check_environment()
    elif cmd == "version":
        cmd_version()
    else:
        print(f"未知命令: {cmd}")
        print("运行 chaossubs help 查看帮助")
        sys.exit(1)


if __name__ == "__main__":
    main()
