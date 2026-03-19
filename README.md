# ChaosSubs

本地部署的视频字幕提取 & 中文翻译工具。上传视频，自动提取语音、生成字幕、翻译成中文。

## 功能

- 支持多种视频格式（MP4、MKV、AVI、MOV 等）
- 语音识别：Whisper large-v3（本地运行，免费）
- 字幕翻译：Ollama + qwen2.5:14b（本地运行，免费）
- 支持日语、英语、韩语及自动检测
- 生成原始语言 SRT + 中文 SRT 字幕文件
- 可选：将中文字幕烧录进视频
- Web 界面，实时进度显示

## 安装

### 方式一：Homebrew（推荐）

```bash
brew tap Chaos0129/tap
brew install chaossubs
```

### 方式二：手动安装

```bash
git clone https://github.com/Chaos0129/ChaosSubs.git
cd ChaosSubs
python3.12 -m venv venv
source venv/bin/activate
pip install setuptools
pip install -r requirements.txt
```

#### 前置依赖

```bash
brew install ffmpeg ollama
brew services start ollama
ollama pull qwen2.5:14b
```

## 使用

### 命令行

```bash
chaossubs start            # 启动服务并打开浏览器
chaossubs start -p 9000    # 指定端口
chaossubs stop             # 停止服务
chaossubs check            # 检查环境依赖是否就绪
chaossubs clean            # 清理历史任务数据
chaossubs version          # 查看版本
```

### 手动启动（未通过 Homebrew 安装）

```bash
cd ChaosSubs
source venv/bin/activate
python run.py
```

打开浏览器访问 `http://localhost:8000`

### 使用流程

1. 打开网页，选择源语言（默认日语），上传视频
2. 等待处理：提取音频 → 语音识别 → 翻译字幕
3. 下载字幕文件（原始语言 SRT / 中文 SRT）
4. 用播放器加载 SRT 预览效果
5. 确认无误后，可选择"合成带字幕视频"

## 系统要求

- macOS（Apple Silicon 或 Intel）
- Python 3.10+
- 约 16GB 内存（运行 Whisper large-v3 + qwen2.5:14b）
- 约 12GB 磁盘空间（模型文件）

## License

MIT
