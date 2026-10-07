# 素材与第三方依赖

## 本项目

代码与文档适用根目录 MIT 许可证。随包原创视觉设计、音乐与参考声线在许可方有权授权范围内采用 CC BY 4.0，具体范围与署名见 [LICENSE-ASSETS.md](LICENSE-ASSETS.md)。本许可不替第三方素材授权，也不要求所有未来生成作品采用同一许可。

## 随包音频

- `assets/voice/reference.wav`、`approved_voice_prompt.pt`、`reference.txt`：原创 AI 声线，使用 Qwen3-TTS VoiceDesign 从文字描述生成，无真人或第三方参考录音。这些资源在许可方有权授权范围内采用 CC BY 4.0。`provenance.json` 记录模型来源、生成参数和原件 SHA-256。
- `assets/music/observation-deck.mp3`：项目所有者提供，说明由 Gemini 生成，并明确授权随本项目以 CC BY 4.0 公开。授权限于许可方有权授予的范围，不构成第三方服务条款或排他权利保证。该说明不表示来自 Gemini 官方曲库，不主张排他版权；文件 SHA-256 与来源说明在同目录 `provenance.json`。如替换为其他音乐，使用者需拥有相应使用权。

## 字体（首次制作自动下载）

Source Han Sans SC Regular / Bold 2.005，Adobe / Google，SIL Open Font License 1.1。完整许可随包放在 `assets/fonts/OFL.txt`；`assets/fonts/downloads.json` 固定官方版本、原文件长度和 SHA-256。字体不属于 MIT 授权范围。上游：https://github.com/adobe-fonts/source-han-sans 。

本包不含 Nimbus Sans，避免与其 AGPL / 字体嵌入例外许可混淆。

## 外部运行依赖（不打包程序或模型权重）

- Qwen3-TTS 与 Qwen3-TTS Base / VoiceDesign 模型：官方 Apache-2.0；https://github.com/QwenLM/Qwen3-TTS 、https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-Base 。下载保留上游 LICENSE 与模型卡。
- PyTorch：BSD-style；https://github.com/pytorch/pytorch/blob/main/LICENSE 。
- Transformers / Hugging Face Hub：Apache-2.0；https://github.com/huggingface/transformers 、https://github.com/huggingface/huggingface_hub 。
- NumPy / SciPy：BSD；Pillow：HPND；SoundFile：BSD；psutil：BSD；这些依赖由 Python 包管理器安装，保留各自许可。
- faster-whisper：MIT；CTranslate2：MIT；Whisper 模型：MIT。https://github.com/SYSTRAN/faster-whisper 、https://github.com/OpenNMT/CTranslate2 、https://github.com/openai/whisper 。
- FFmpeg：所装构建可为 LGPL/GPL，取决于启用选项；本项目使用其命令行，不随包分发二进制。https://ffmpeg.org/legal.html 。
