# 固定声线运行说明

## 环境与文件

使用 Python 3.11 或 3.12、FFmpeg，以及可完整驻留模型的内存。先从 [PyTorch 官方安装入口](https://pytorch.org/get-started/locally/) 安装对应平台的 PyTorch，再安装技能目录内的 `requirements-voice.txt`。源制作环境使用 `torch==2.14.1+cpu`；依赖文件其余版本来自同一环境的记录。CUDA 用户选择匹配驱动的 PyTorch CUDA 构建。

项目根目录放 `config.json` 和 `episode.json`。配置内所有相对路径均以 `config.json` 所在目录为基准；命令行的这两个文件路径则以当前工作目录为基准。固定声音素材放在：

- `assets/voice/reference.wav`
- `assets/voice/reference.txt`，UTF-8 逐字参考稿
- `assets/voice/approved_voice_prompt.pt`，可选的原始固定声音 prompt

仅对本人有权使用的声音素材执行合成。内置参考声线为原创 AI 设计声线。

## 配置

```json
{
  "voice_reference": "assets/voice/reference.wav",
  "voice_transcript": "assets/voice/reference.txt",
  "voice_prompt": "assets/voice/approved_voice_prompt.pt",
  "model_path": "models/Qwen3-TTS-12Hz-1.7B-Base",
  "device": "cpu",
  "dtype": "bfloat16",
  "seed": 21,
  "cpu_threads": 4,
  "speed": 1.1,
  "max_new_tokens": 500,
  "trim_threshold": 0.001,
  "boundary_padding_seconds": 0.1,
  "timeout_seconds": 900,
  "no_progress_timeout_seconds": 60,
  "output_dir": "voice",
  "ffmpeg": "ffmpeg"
}
```

默认全 CPU、BF16、4 线程，模型和 codec 完整驻留内存。可显式改为 `cuda:0`，需要支持 BF16 的 GPU。不会自动转成磁盘卸载、MPS、其他 TTS 或低配替代声线。`voice_prompt` 可设为 `null`，改由参考 WAV 与文字生成 prompt；指定的 prompt 文件必须存在。读取 `.pt` 始终使用 `weights_only=True`，不放宽 pickle 安全限制；若数据格式或参考稿不匹配，则从 WAV 重建并记录来源。

`episode.json` 格式：

```json
{
  "segments": [
    {"id": "01", "zh": "中文旁白。", "en": "English subtitle.", "tts_text": "中文旁白。"}
  ]
}
```

`tts_text` 可省略，届时用 `zh` 合成；它只处理读音，屏幕文字继续使用 `zh` 与 `en`。一段用完整、自然的短段落，避免把字幕小块直接作为 TTS 输入。ID 必须唯一，只含字母、数字、下划线或短横线，且以字母或数字开头。

## 下载与合成

下列命令中的 `<skill>` 是技能目录路径，`<project>` 是项目路径：

```sh
python <skill>/scripts/setup_model.py --config <project>/config.json
python <skill>/scripts/generate_voice.py --config <project>/config.json --episode <project>/episode.json
```

下载器固定使用 `Qwen/Qwen3-TTS-12Hz-1.7B-Base` 的 `fd4b254389122332181a7c3db7f27e918eec64e3` 修订，完成后把本地路径写回配置。可用 `--cache-dir <目录>` 放入共享 Hugging Face 缓存，也可把已有完整快照路径直接填写为 `model_path`。合成阶段只读本地权重，禁止自动联网下载。运行时核对固定修订的权重与配置文件哈希，并对本地模型文件做指纹；损坏或不匹配的模型会停止处理，改动权重不会误复用旧音频。

`FFMPEG` 环境变量可覆盖配置中的 `ffmpeg` 命令。

原始波形只裁去两端低于阈值的静音，并留 0.1 秒保护边；每段从原速裁切文件执行一次 `atempo=1.1`。重跑不对已加速文件再加速。

## 输出与续跑

- `voice/raw/<id>.wav`：原始音频
- `voice/trimmed/<id>.wav`：原速、边界裁切后音频
- `voice/segments/<id>.wav`：一次 1.1× 后的最终旁白段
- `voice/checkpoints/<id>.json`：逐段提交记录
- `voice/manifest.json`：当前有效片段及实测时长
- `voice/model-identity.json`：本地模型文件指纹
- `voice/runs/<run>/worker.jsonl`、`resources.jsonl`、`result.json`：事件、公共进程指标、结束原因

重复相同命令即可续跑。只有源文字、配置、参考 WAV、参考文字、prompt、模型文件和运行依赖身份都一致，且三份音频哈希及最终时长一致时，才复用片段。变更会使相关检查点失效；旧文件只有在新段完整生成后才被替换。中途中断会保留已提交片段，不提交半段结果。

清单的 `segments` 提供 `id`、`zh`、`en`、`tts_text`、`path`、`duration`、`first_activity_s`、`last_activity_s`、`sha256`。`path` 相对项目根目录。时长以最终 WAV 的真实采样数计算，清单总时长仅为旁白段时长之和，段间留白与片尾停留由画面渲染器配置；活动区间只按波形阈值估算，不能当作逐字字幕对齐。仅 `status=complete` 表示所有段已完成，内容审听/字幕校对仍是独立工序。

## 看护与停止

直接运行 `generate_voice.py` 会启动受监督子进程。默认每个合成段以及每个准备阶段最多 15 分钟；合成中连续 60 秒没有 talker forward 进度即停止。每次 forward 都写入进度，未发生 forward 时不会伪造心跳。整集没有固定总时长上限，已完成段越多不会挤占后续段的时间。

`Ctrl+C` 会取消子进程及其子进程。POSIX 平台按整个独立进程组终止；原生 Windows 使用进程组启动与 psutil 子进程树清理，需要严格 POSIX 进程组语义时使用 WSL。RSS 与可用内存通过 psutil 公共 API 采样，不依赖私有系统路径。退出码 137 或 SIGKILL 只说明被强制终止，不能单凭退出码判定内存不足。

需要更长的单段计算时间时可在配置中调整两项超时；接近 token 上限的片段须拆成自然段，不应通过换声音或二次提速规避。

接口来源：[Qwen3-TTS 官方项目](https://github.com/QwenLM/Qwen3-TTS)、[固定 Base 模型修订](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-Base/tree/fd4b254389122332181a7c3db7f27e918eec64e3)。
