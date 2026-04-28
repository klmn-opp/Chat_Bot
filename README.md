# 智护夜巡实时语音对话系统（Chat_Bot）

一个基于 Tkinter 的实时语音对话原型工程，默认使用 Doubao Live S2S（语音输入直连语音输出），并在收到 AI 最终文本后执行动作语义匹配与 ROS2 动作下发。

## 当前默认运行链路

`main.py` -> `ui/medical_robot_stream_ui.py` -> `core/stream_controller.py` -> `core/doubao_live_s2s.py` -> `core/motion_analyzer.py`

说明：
- 默认是实时链路（`USE_GEMINI_LIVE_S2S=1`），变量名沿用历史命名，但当前实际使用的是 Doubao Live。
- 旧链路仍保留为回退方案：`audio_stream.py` + `chat.py` + `tts.py`。

## 功能概览

- 实时语音对话：麦克风采集、WebSocket 双向流、扬声器播放。
- 文本回调与界面联动：用户中间识别、最终文本、AI 最终回复同步到 UI。
- 动作匹配：对 AI 文本按句拆分，计算 embedding 相似度并匹配动作标签。
- 指令下发：匹配成功后发送 ROS2 topic 指令。
- 旧链路回退：可切为本地 Whisper + Chat API + Edge TTS 串行流程。

## 目录与文件说明

### 根目录

- `main.py`：应用入口，加载 `.env`，启动 Tk 主窗口。
- `requirements.txt`：Python 依赖清单。
- `README.md`：本说明文档。
- `.env`：运行时环境变量（本地私有，不应提交密钥）。

### `configs/`

- `configs/languages.json`：语言映射配置。
- `configs/system_prompt.txt`：系统提示词模板，`StreamController` 会加载并注入对话上下文。

### `core/`

- `core/stream_controller.py`：全链路控制器，统一管理状态、回调、日志、链路选择和动作下发。
- `core/doubao_live_s2s.py`：Doubao 实时语音桥接，负责协议封包、音频收发、事件解析与文本回调。
- `core/motion_analyzer.py`：动作 embedding 匹配核心，基于预置向量与在线 embedding 计算相似度。
- `core/audio_stream.py`：旧链路录音与 Whisper 识别模块。
- `core/chat.py`：旧链路文本对话模块（当前走 SiliconFlow chat completions）。
- `core/tts.py`：旧链路 TTS 模块（Edge TTS 合成、格式转换、播放协调）。

### `ui/`

- `ui/medical_robot_stream_ui.py`：主界面与交互事件入口。
- `ui/components/conversation_manager.py`：会话状态与历史管理。
- `ui/components/realtime_display.py`：实时识别文本与正式消息显示逻辑。
- `ui/components/audio_player.py`：独立音频播放器，负责 WAV 播放与设备切换。

### `tool/`

- `tool/check_audio_devices.py`：列出可用输入设备（麦克风）。
- `tool/terminal_input.py`：命令行直输文本测试入口（绕过 UI，复用控制器逻辑）。
- `tool/get_vectors.py`：离线生成动作 embedding 向量的小工具脚本。

### 运行产物目录

- `conversation_logs/reply.txt`：对话结果日志。
- `temp/`：TTS/音频转换临时文件（`.mp3`、`.wav`）。

## 模块协作关系

### 1. 启动阶段

- `main.py` 通过 `load_dotenv()` 加载环境变量。
- 初始化 `MedicalRobotStreamUI`，UI 内部创建 `StreamController`。

### 2. 实时对话阶段（默认）

- `StreamController` 读取 `DOUBAO_APP_ID`、`DOUBAO_ACCESS_KEY`、`DOUBAO_MODEL` 创建 `DoubaoLiveS2SBridge`。
- `DoubaoLiveS2SBridge` 持续处理麦克风帧与服务端音频帧。
- 文本事件回调到 `StreamController`，再转发给 UI 显示。

### 3. 动作执行阶段

- AI 最终文本进入 `_dispatch_motion_for_response()`。
- 逐句调用 `MotionAnalyzer.analyze_text()` 匹配动作。
- 匹配成功后执行 `ros2 topic pub` 发送动作指令。

### 4. 回退链路（可选）

- 当 `USE_GEMINI_LIVE_S2S=0` 时，走 `AudioStreamProcessor` -> `ChatBot` -> `TextToSpeech`。

## 环境要求

- Python：建议 `3.10` 到 `3.12`。
- 系统组件：
- `PortAudio`（`pyaudio` 依赖）。
- `ffmpeg`（`pydub` 音频转换依赖）。
- `Tk/Tcl`（`tkinter` 依赖，通常系统 Python 自带）。

Linux 常用安装示例：

```bash
sudo apt-get update
sudo apt-get install -y portaudio19-dev ffmpeg python3-tk
```

## 安装与运行

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
python main.py
```

## 依赖说明

`requirements.txt` 当前包含：

- `requests`
- `python-dotenv`
- `edge-tts`
- `pyaudio`
- `numpy<2.0`
- `openai-whisper`
- `pydub`
- `torch`
- `google-genai`
- `websockets`

额外注意：

- `core/motion_analyzer.py` 使用了 `deep_translator`，但该包目前未写入 `requirements.txt`。

## 环境变量

### 实时链路（默认）

- `DOUBAO_APP_ID`：必填。
- `DOUBAO_ACCESS_KEY`：必填。
- `DOUBAO_MODEL`：可选，默认 `1.2.1.1`。
- `USE_GEMINI_LIVE_S2S`：可选，默认 `1`。设为 `0` 走旧链路。

### 动作匹配

- `OPENAI_API_KEY`：`MotionAnalyzer` 在线 embedding 请求使用。

### 旧链路回退

- `DEEPSEEK_API_KEY`：`core/chat.py` 读取。

## 待优化项

- `tool/get_vectors.py` 中有硬编码 API Key 字符串，不建议保留在仓库中。
- `USE_GEMINI_LIVE_S2S` 命名与实际服务不一致，仅为历史兼容开关。
- `temp/` 与 `conversation_logs/` 会持续增长，建议定期清理。
- `core/audio_stream.py` 对输入设备索引和采样参数有较强耦合，旧链路下跨设备兼容性需实机验证。

## 快速排查

- 无法录音/播放：先运行 `python tool/check_audio_devices.py` 检查设备索引与权限。
- 启动时报 `DOUBAO_*` 缺失：检查 `.env` 是否加载成功。
- 动作匹配异常：确认 `OPENAI_API_KEY` 已设置，且可访问 embedding 服务。
- 回退链路异常：确认 `DEEPSEEK_API_KEY` 与 `ffmpeg`、`pyaudio` 可用。

## 许可

仓库未内置 `LICENSE` 文件。若需开源发布，请补充许可证（如 MIT 或 Apache-2.0）。

**设备兼容性与可调参数**

- **输入设备索引 (`input_device_index`)**: 在 [core/audio_stream.py](core/audio_stream.py) 和 [core/stream_controller.py](core/stream_controller.py) 中使用；不要硬编码索引（当前代码中有 `input_device_index = 2` 的示例），推荐先自动探测 `p.get_default_input_device_info()` 或遍历 `p.get_device_info_by_index()` 并在 UI/`.env` 中暴露供选择。
- **采样率 (`RATE`)**: 采集时优先使用设备的 `defaultSampleRate`（见 [core/audio_stream.py](core/audio_stream.py)）；若目标服务期望 16000Hz，需在发送前重采样到 16000（实时可用 `audioop.ratecv()` 或外部库如 `samplerate`/`resampy`）。
- **声道数 (`CHANNELS`)**: 读取设备 `maxInputChannels`，一般将多声道转为单声道再送入模型（可用 `audioop.tomono()`）。
- **帧长度 / 缓冲 (`CHUNK`)**: 以时间窗定义为佳，例如 20ms 帧 -> `frames = int(0.02 * sample_rate)`；对于 16kHz 即 320 帧（Doubao 推荐），设定为 `CHUNK = frames` 或使用能整除帧的缓冲大小。
- **采样格式 (`FORMAT`)**: 使用 `pyaudio.paInt16` 保持与大多数服务与 `audioop` 兼容。
- **样本宽度 / 字节序 (`sample_width`)**: 计算自 `bits_per_sample // 8`，确保 `audioop` 和写 WAV/播放时一致。
- **输出设备索引 (`output_device_index`)**: 在 [ui/components/audio_player.py](ui/components/audio_player.py) 使用，避免硬编码，允许 UI 切换并校验 `maxOutputChannels`。
- **系统/运行时参数**: 在 Linux 可通过环境变量 `PYAUDIO_INPUT_DEVICE` / `PYAUDIO_OUTPUT_DEVICE` 指定后端（例如 `pulse`），并在导入 `pyaudio` 前确保 `PY_SSIZE_T_CLEAN` 已设置以避免兼容问题（当前 `core/tts.py` 有示例）。

简短示例（计算 20ms 帧与必要重采样）：

```python
# device_rate = int(device_info['defaultSampleRate'])
frames = int(0.02 * device_rate)
if device_rate != 16000:
	# 使用 audioop.ratecv 在发送前把 int16 bytes 从 device_rate -> 16000
	converted, state = audioop.ratecv(raw_bytes, 2, 1, device_rate, 16000, None)
	# 然后把 converted 按 320 字节块发送
```

参考文件： [core/audio_stream.py](core/audio_stream.py), [core/doubao_live_s2s.py](core/doubao_live_s2s.py), [ui/components/audio_player.py](ui/components/audio_player.py)

