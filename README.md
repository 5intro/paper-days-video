# 纸间日常 · Paper Days

一个从**选题到完整视频**的 Codex skill。用暖纸质感、柔灰绿和原创生活动画，把一个具体困扰讲清楚；也支持从真实生活痛点出发，展示精致的 vibecoding 产品故事。

你只需给选题，Codex 负责研究、叙事、中英稿、分镜、配音、原创场景、时间轴、混音、封面与成片。`episode.json` 是 Codex 的中间工作文件，不需要你先填写。

## 安装到另一台电脑

下载并解压 [GitHub 仓库](https://github.com/5intro/paper-days-video)，然后在 Codex 对话中告诉它：

> 请把这个文件夹里的 `skill/paper-days-video` 安装为我的个人 skill。然后使用 `$paper-days-video`，选题是：为什么休息也会有负罪感？

也可在支持 `$skill-installer` 的 Codex 中直接安装：

```text
$skill-installer install https://github.com/5intro/paper-days-video/tree/main/skill/paper-days-video
```

或在下载后的仓库目录执行：

```sh
python install.py
```

Windows 可用 `py install.py`。安装程序只复制 skill，不安装依赖、不修改授权设置；已有同名 skill 时会停止，可指定新的 `--dest`。默认安装至 `~/.agents/skills/paper-days-video`。只想对某个项目启用时，将 skill 文件夹复制到该项目的 `.agents/skills/`。

Codex 会自动发现新 skill；未出现时重启会话。在支持 skill 选择的界面，输入 `$paper-days-video` 或通过 skills 列表选择。目录与调用方式见 [Codex 官方文档](https://developers.openai.com/codex/skills/)。

## 使用

```text
$paper-days-video
选题：为什么休息也会有负罪感？
```

```text
$paper-days-video
做一个帮合租室友安排冰箱食材、减少浪费的小工具，用真实操作展示它怎样解决问题。
```

可以加时长、目标观众、已经确认的文字稿、自有 BGM 或产品地址；不填时，Codex 先据选题判断模式，再完成整条制作链。若你明确要求先审稿，制作会停在该阶段等待你的决定。

### 两种模式

- **科普 / 心理 / 哲学**：原创生活场景串起问题、解释与可选尝试；研究和推测分开，不把隐喻画成真实实验数据。
- **Vibecoding 产品**：痛点有来由，操作逻辑可信；可用真实应用、可交互原型或原创 UI 动画。产品 UI 有独立视觉系统，关键操作局部放大，前后对照保留同一位置，并准确说明演示形态。

共同输出：1080×1920 / 24 fps MP4、3:4 与 4:3 双封面、中英 SRT、简介、来源及素材说明，以及可继续编辑的项目源码。

## 第一次制作时

Codex 会检查机器、建立独立项目和 Python 虚拟环境，按机器情况准备以下公开依赖：

- Python 3.11 或 3.12，FFmpeg / FFprobe（命令路径可配置）
- Qwen3-TTS 1.7B Base 固定版本及音频依赖；模型首次下载约数 GB
- 完整 Source Han Sans SC Regular / Bold 字体，按官方版本和 SHA-256 自动下载，不裁中文字符
- 本地 ASR，用于保存原始观测和辅助逐句对齐

CPU 默认完整模型常驻 BF16、4 线程。为模型与渲染留出约 8 GiB 可用内存更稳妥；实际峰值取决于系统、Torch 与运行方式。内存不足时先释放资源或选择受支持的 CUDA 设备，不静默换声线。macOS 默认 CPU 路线，不强制使用 MPS；CUDA 需选择适合驱动的 PyTorch 构建。无需把模型、虚拟环境或机器绝对路径搬到另一台电脑。

## 声音与素材

默认配音使用随包的原创 AI 参考声线 `bright_warm_steady`，通过固定 Qwen3-TTS 模型复现，生成后仅做一次 1.1 倍速处理。参考声音由 VoiceDesign 从文字描述生成，没有使用真人参考录音。

默认 BGM 为 `Observation Deck`：项目所有者提供、说明由 Gemini 生成，并确认可随本项目公开。可通过项目 `config.json` 的 `music_path` 换成自己有权使用的音乐。音乐采用轻动态压缩、平滑浅避让，保持可听见的底色，不逐字抽吸或压成近乎静音。

默认中文及标题层次使用 OFL 的 Source Han Sans；可配置其他合法字体。Nimbus Sans 不随包分发，也不是默认必需依赖。

代码与文档采用 MIT；随包原创视觉设计、音乐和 AI 参考声线采用 CC BY 4.0，使用时保留署名并注明修改。字体保留 OFL；模型与外部工具沿用各自许可。素材来源与范围见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。本 skill 只制作交付物；发布到社交平台、付费或授予外部访问需要另行明确请求。

### 可直接使用的素材署名

```text
部分音画素材：5intro / Paper Days（https://github.com/5intro/paper-days-video），CC BY 4.0（https://creativecommons.org/licenses/by/4.0/）。已作剪辑与改编。
```

按实际使用的素材与修改调整最后一句。完整范围见 [素材许可](LICENSE-ASSETS.md)；本许可不要求你的其他原创内容或整部未来作品采用同一许可，也不承诺 AI 生成内容的排他版权。

## 仓库结构

```text
install.py
skill/paper-days-video/
  SKILL.md
  agents/openai.yaml
  scripts/             # 建项目、配音、对齐、渲染、混音、客观检查
  references/          # 风格、研究、两种模式、运行方式与交付标准
  assets/              # 原创声音、授权音乐、字体清单、绘图模板
```

安装后的入口是 `SKILL.md`；手动维护或扩展流水线时，从 `references/pipeline.md` 开始。
