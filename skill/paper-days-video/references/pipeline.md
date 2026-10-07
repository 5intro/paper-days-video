# 从选题到成片

本页供执行制作的 Codex 使用。用户只提供选题；下面的稿件、JSON、脚本适配和运行步骤由 Codex 完成，不转交给用户当作准备作业。

## 1. 建立项目与依赖

把 `<skill>` 解析为当前 `SKILL.md` 所在目录，选择新的 `<project>`，不要依赖此前机器上的绝对路径或其他项目模块。

```sh
python <skill>/scripts/init_project.py --project <project> --topic "本次选题" --mode research
```

产品片使用 `--mode product`。初始化会把工具、原创绘图、参考声线、音乐和许可证复制到独立项目；字体使用固定官方清单自动下载。不要在安装的 skill 目录产生成片或改写默认资产。

在项目中建立 Python 3.11 / 3.12 虚拟环境。下例中的 `python` 换成实际虚拟环境解释器：macOS/Linux 通常是 `.venv/bin/python`，Windows 是 `.venv\Scripts\python.exe`。

```sh
python -m venv .venv
python tools/doctor.py --project .
```

根据 doctor 结果安装缺失依赖：从 [PyTorch 官方](https://pytorch.org/get-started/locally/) 选择 CPU 或适合驱动的 CUDA 构建，之后安装 `requirements.txt`、`requirements-voice.txt`、`requirements-asr.txt`。FFmpeg / FFprobe 通过官方来源或可信包管理器准备；不要静默安装未知分发包。安装遵循当前执行环境的权限。

```sh
python -m pip install -r requirements.txt -r requirements-voice.txt -r requirements-asr.txt
python tools/setup_assets.py --project .
python tools/setup_model.py --config config.json
python tools/doctor.py --project .
```

`setup_assets.py` 只从 `assets/fonts/downloads.json` 的固定官方来源下载并核对字节数与 SHA-256。已有相符文件则复用。模型下载器固定 Qwen 修订并核对上游文件身份；既有模型可通过配置复用，模型权重不放入源码包。`FFMPEG` / `FFPROBE` 环境变量可指定可执行文件；工具参数也支持路径。

若缺网络、内存或必须授权的操作，报告具体缺项并继续不依赖它的研究/稿件工作。不要假装已合成声音或静默改用另一 TTS。完整 CPU 模型常驻需要数 GiB；约 8 GiB 可用内存为规划参考，实际依机器与软件而异。

## 2. 写稿、锁定与分镜

研究一手来源，写 `sources.md`；按对应模式写完整中英稿。已有稿件审阅要求时先提交。没有审阅关卡的直接制片请求，完成内容检查后继续。

Codex 编辑项目 `episode.json`：

```json
{
  "title": "本片标题",
  "topic": "用户选题",
  "mode": "research",
  "cover_title": "短而有画面的标题",
  "cover_subtitle": "Short supporting line",
  "description": "简介，含与实际一致的AI/研究/演示说明。",
  "segments": [
    {
      "id": "01",
      "zh": "锁定的完整中文语义段。",
      "en": "The corresponding natural English paragraph.",
      "visual": {"kind": "author-a-scene-for-this-topic"},
      "visual_notes": "生活物件、动作因果、相机与回扣。"
    }
  ]
}
```

每个 `id` 唯一，使用字母/数字开头及字母数字下划线短横线。自然短段落生成 TTS；字幕小块稍后按真实语音切分。确有多音字问题时加 `tts_text` 作为读音副本，例如把特定“弹”的发音改写为同音提示；不得改 `zh` 和最终字幕的原文。

## 3. 配音与真实对齐

```sh
python tools/generate_voice.py --config config.json --episode episode.json
python tools/observe_asr.py --project . --model small
```

具体运行、续跑和 guard 见 [voice-runtime.md](voice-runtime.md)。最终 `voice/manifest.json` 必须是 `status=complete`，每段有实际采样时长、活动区间、哈希及与锁稿相同的中文文本。原速音频与单次 1.1× 成品分别保留。

`qa/asr/` 是原始识别结果，不自动改成正确文稿。对照锁稿审查漏词、重复、多音字、时码。中文同音字形不同先判断是识别拼写还是发音错误；必要时仅对相应段做一次交叉识别，例如 `--segment 04 --model base`。不能不断换模型直至碰巧得到想要的字。

Codex 根据原始词时码、波形停顿和必要的实际听审，写 `alignment.json`。所有时间都针对最终已加速 WAV 的局部秒数，不再次除以 1.1：

```json
{
  "segments": {
    "01": {
      "cues": [
        {"start": 0.12, "end": 3.8, "zh": "锁定的完整中文语义段。", "en": "The corresponding natural English paragraph.", "evidence": "qa/asr/01-small.json；记录实际审核依据"}
      ],
      "events": {
        "place_paper": {"time": 1.4, "evidence": "对应原始词时码/波形或实际听审的依据"}
      }
    }
  }
}
```

这里的数值仅解释字段。实际片必须使用自己的观测。cue 中文按顺序拼回该段原文，保留标点；一个 cue 不够放下中英两行时按完整语义继续拆分。无法直接观测到的字符时码只可标记为插值，不伪装成 ASR 观测；重要动画事件尽量落在可核对的词锚点。

## 4. 编写本选题的动画

项目 `paper_art.py` 是可复用的原创生活道具库，`scenes.py` 是工作示例接口；不要把所有选题套成同一个桌面。按分镜添加本片的场景函数、动作和前后状态。`visual.kind` 由 Codex 定义并实现；初始 `desk-example` 仅演示 API。

- `frame(segment, local_seconds, duration, events, context)` 返回 1080×1920 RGB Pillow 图像，不自行再画字幕。
- `events` 是词锚点对应的局部秒数；用事件后的局部进展驱动动作，而非硬套画面时长百分比。
- `context` 含项目路径、配置和字体路径；项目资产放在 `assets/` 下。
- `cover(size, episode, context)` 分别支持 1080×1440 与 1440×1080；按比例独立构图。

可用 `art.C` 的可缩放绘图 API 和 `paper`、`mug`、`plant`、`person`、`room` 等物件。新增场景自行定义；原始源图形不含某次旧选题文本。产品模式按用户范围选择实际应用采集、可交互原型或原创 UI 动画。实际采集的画面放 `assets/ui/`；纯动画可直接在 `scenes.py` 绘制精致独立 UI。各模式都保持可信操作逻辑、设备框、局部放大和连续状态变化，简介准确披露其实际形态。

```sh
python tools/render_episode.py --project . prepare
python tools/render_episode.py --project . samples
python tools/render_episode.py --project . covers
```

`prepare` 使用真实音频时长构建 `timeline.json`，目标段间停顿约 0.42 秒，扣除已有句尾/下一段前静音；最后留约 2 秒余韵，再对齐 24 fps 帧格。时长不由字数估算。检查 `frames/` 和双封面，修复遮挡、文字、姿态和节奏后渲染。

## 5. 配乐、音效与渲染

音效用目的明确的纸声、轻触、柔和动作声，创建的合成源或有权使用的素材都记录来源。事件由时间轴落位；不要给每次转场都加刺耳 ding。可将带绝对时间的 SFX 写为 `sfx/events.json`，结构见 [audio-mix.md](audio-mix.md)。

```sh
python tools/mix_audio.py --project . --timeline timeline.json --music assets/music/observation-deck.mp3 --out mix.wav
python tools/render_episode.py --project . render
python tools/render_episode.py --project . mux
python tools/audit_media.py delivery/main.mp4 --out qa/final-media.json
```

如果配置里 `music_path` 被替换，命令使用该路径。音乐不足时 Codex 根据实际音乐找乐句边界与结尾，提交 cue 给 `--music-cues` / `--music-end-policy crossfade_extend`；不把音乐加速或悄悄留下静音。示例混音器拒绝覆盖已有输出；修订时输出 `mix-v2.wav` 等新版本，并更新配置 `mix_path` 后重新 mux。

`render_episode.py` 按输入、场景代码和资产哈希复用已完成镜头。字幕、文字或资产改动会使缓存失效。重新生成一段配音后必须重新 prepare、对齐相关字幕/事件、重混音和渲染受影响镜头。不要把旧混音搭配新的时间轴。

## 6. 交付

按 [quality.md](quality.md) 做实际画面、对齐和音频检查；按实际复用的素材把署名、许可链接和修改说明写入简介或素材说明。填 `qa/review.json`：每项记完成方式、证据与问题；未进行的环节不写通过。修复明显错误后运行：

```sh
python tools/package_delivery.py --project .
```

这会核对标准文件存在、MP4 元数据与封面尺寸，复制来源和说明，生成包含哈希和实际检查记录的 `delivery/manifest.json`。把 delivery 文件与可编辑项目交给用户。是否将模型、渲染缓存或环境打包由用途决定，默认只带源码和必要合法素材；不要带密钥、浏览器资料或机器私有路径。
