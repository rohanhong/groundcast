<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../../.github/assets/banner-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="../../.github/assets/banner-light.svg">
  <img alt="Groundcast" src="../../.github/assets/banner-light.svg" width="440">
</picture>

<h1>🎧 Groundcast</h1>

<p><b>把你自己的学习资料变成播客式音频，每一句陈述都有资料依据。</b></p>

<p>
  <a href="../../LICENSE"><img alt="License" src="https://img.shields.io/github/license/rohanhong/groundcast"></a>
  <a href="https://www.python.org"><img alt="Python" src="https://img.shields.io/badge/python-3.12-3776AB?logo=python&logoColor=white"></a>
  <a href="https://github.com/rohanhong/groundcast/commits/main"><img alt="Last commit" src="https://img.shields.io/github/last-commit/rohanhong/groundcast"></a>
  <a href="https://github.com/rohanhong/groundcast/stargazers"><img alt="Stars" src="https://img.shields.io/github/stars/rohanhong/groundcast?style=flat"></a>
  <a href="https://agents.md"><img alt="AGENTS.md" src="https://img.shields.io/badge/AGENTS.md-ready-24292f"></a>
  <a href="https://agentskills.io"><img alt="Agent Skills" src="https://img.shields.io/badge/Agent%20Skills-open%20format-8250df"></a>
  <!-- Reserved badges: uncomment when the service exists.
  <a href="https://github.com/rohanhong/groundcast/actions/workflows/ci.yml"><img alt="CI" src="https://img.shields.io/github/actions/workflow/status/rohanhong/groundcast/ci.yml?branch=main"></a>
  <a href="https://github.com/rohanhong/groundcast/releases"><img alt="Release" src="https://img.shields.io/github/v/release/rohanhong/groundcast"></a>
  -->
</p>

<p>🌐 <a href="../../README.md">English</a> | <b>简体中文</b></p>

</div>

Groundcast 是一个个人使用的本地 Web 应用，把你手头已有的学习资料（PDF、幻灯片、笔记、网页、视频）变成播客式的学习音频，适合通勤、运动或考前复习时收听。一条固定的 LLM 角色流水线先撰写脚本，再逐条核对每个事实陈述是否有资料依据，最后才润色文风；本地语音合成把结果渲染成 MP3，可在任意手机播放器中收听。

> [!NOTE]
> 第 1 版：五个里程碑均已实现；少数检查还需要实际使用才能完成，例如手机播放器中的章节，以及你自己的手写稿能识别得多好。可以添加 PDF（带文字层或扫描件）、PowerPoint、Word、Markdown 或纯文本文件，按网址添加网页，也可以添加笔记照片、视频和音频；识别出的语音和扫描文字经你核对后才会使用。用自己的话描述想要的会话，再确认它提出的简报，就能得到经过核对、带章节标记的 MP3（单人旁白或双主持人），以及一份文稿，其中的链接会在对应的页码、幻灯片或时间点打开每个来源。会话完成后，打字提问的回答和选择题测验都来自你的资料。会话结尾还可以加入回忆提问，每题后留出停顿。资料中的概念汇总到一张概念表里，附带你在每个概念上的测验结果，可以重命名与合并。偏好设置决定默认的声音、语速和简报，档案的每次改动都有记录，并可导出。开始会话时，排序的建议会说明为何适合你；Groundcast 从你过去的会话和反馈中推断出的内容都会展示给你，从不悄悄使用。

## ✨ 亮点

- 🔎 **以资料为依据**：脚本中的每条陈述都标注其所依据的资料片段，并由独立的 Verifier 核对；不来自你资料的内容会明确标出。
- 🧭 **先写、再核、后润色**：由代码驱动的流水线在各角色之间传递有类型的 JSON；文风润色不得引入新的事实陈述，改动部分会再次核对。
- 🏠 **本地优先**：解析、OCR、语音识别与语音合成都在本机运行；只有 LLM 调用会离开本机，发往你选择的提供方。
- 🎧 **随处收听**：导出带章节标记的 MP3，以及一份 HTML 文稿，其中的链接可回溯到资料的页码、幻灯片或时间点。在应用内，带波形和章节标记的播放器在切换页面时继续播放，文稿逐句跟随朗读位置高亮；点击任一句子即从该处播放。
- 🧠 **看得见的个人档案**：偏好与测验结果保存在本地 SQLite 档案中，附带变更日志，你可以查看、编辑、导出或删除。

## 🚀 快速开始

> [!NOTE]
> 需要 git、conda（例如 [Miniforge](https://conda-forge.org/download/)），以及默认 LLM 后端所需的、已安装并登录的 Claude Code CLI（也可使用 API key）。开发环境为 Windows 11 与 8 GB NVIDIA GPU；默认的语音合成模型也可在 CPU 上运行。

1. 克隆仓库：
   ```bash
   git clone https://github.com/rohanhong/groundcast.git
   cd groundcast
   ```
2. 运行安装程序。它会创建 conda 环境（Python 3.12、ffmpeg、poppler、用于扫描件的 Tesseract，并以可编辑模式安装 Groundcast 本身），然后询问要添加哪些部分：语音合成所用的 PyTorch 版本（它读取 `nvidia-smi`，推荐你的显卡和驱动能运行的最新版本，没有可用显卡时推荐 CPU 版）、视频和音频的语音识别、Piper 备用语音，以及 API 后端。按回车即采用推荐项；最后它会检查安装结果，在桌面和开始菜单（Linux 上是应用程序菜单，macOS 上是 `~/Applications`）创建 Groundcast 快捷方式，并询问是否立即启动 Groundcast。
   - Windows：双击 `install.cmd`，或在终端中运行 `.\install.cmd`。
   - Linux 或 macOS：`./install.sh`

   加上 `--yes` 可不经询问采用全部推荐项，加上 `--dry-run` 只打印 pip 命令，也可直接指定选择，例如 `--torch cpu --no-asr`。模型权重在首次使用时下载（Kokoro 约 330 MB，语音识别模型约 1.6 GB）。
3. 双击 Groundcast 快捷方式。不会打开终端：服务在后台启动，Groundcast 在自己的窗口中打开（Edge 或 Chrome 的应用窗口，没有时使用默认浏览器的标签页），地址是 <http://127.0.0.1:8765/>，只在 `127.0.0.1` 上提供服务。再次双击会把已打开的窗口切到最前面，没有窗口时才打开一个。所有 Groundcast 窗口都关闭、且没有正在生成的会话或正在进行的识别时，服务会自行停止；侧栏中的“Quit Groundcast”会关闭窗口并立即停止服务。由于没有控制台，它的输出写入数据目录中的 `logs/launcher.log`。

   在终端里，`groundcast launch` 的效果相同，`groundcast serve` 在前台运行服务；`groundcast shortcut` 会重新创建快捷方式（加 `--remove` 则删除）。`[launcher]` 设置决定使用哪种窗口以及服务何时停止。

在环境中，`groundcast setup` 会再次给出同样的选择（例如在更新驱动之后），`groundcast doctor` 会检查每个部分，并为缺失的部分打印修复命令；应用的偏好设置里也能看到同样的检查。

<details>
<summary>手动安装</summary>

1. 创建并激活环境：
   ```bash
   conda env create -f environment.yml
   conda activate groundcast_env_py312
   ```
2. 安装语音合成（Kokoro-82M 与 CPU 版 PyTorch）：
   ```bash
   pip install -e ".[tts]"
   ```
   如有 NVIDIA 显卡，把 PyTorch 换成 CUDA 版。请按 [PyTorch 兼容性矩阵](https://github.com/pytorch/pytorch/blob/main/RELEASE.md) 选择你的驱动所支持的版本（`nvidia-smi` 会显示驱动支持的最高 CUDA 版本）；例如 PyTorch 2.14.1 的 CUDA 13.0 版：
   ```bash
   pip install "torch==2.14.1+cu130" --index-url https://download.pytorch.org/whl/cu130
   ```
   在默认设置 `tts.device = "auto"` 下，Groundcast 随后会自动使用 GPU。
3. 可选：为视频和音频安装语音识别（faster-whisper）：
   ```bash
   pip install -e ".[asr]"
   ```
   默认在 CPU 上运行。若要使用 GPU，再安装 CTranslate2 所需的 CUDA 12 库（PyTorch 自带的 CUDA 库版本不同）：
   ```bash
   pip install nvidia-cublas-cu12 "nvidia-cudnn-cu12>=9,<10"
   ```
   在 Linux 上，还需把它们的 `lib` 目录加入 `LD_LIBRARY_PATH`。
4. 可选：Piper 备用语音（`pip install piper-tts`）与 API 后端（`pip install -e ".[api]"`）。

</details>

同一条流水线也可以在命令行运行：先 `groundcast ingest <files>`（网页用 `--url <网址>`；用 `groundcast review <material id>` 核对识别出的语音或扫描文字），再 `groundcast session -m <material id> --focus "<要讲的内容>"`（加上 `--format two_hosts` 即为双主持人，加上 `--recall` 则在结尾加入回忆提问）。用 `groundcast ask <session id> "<问题>"` 就已完成的会话提问，或用 `groundcast quiz <session id>` 打印一套经过核查的测验；用 `groundcast concepts` 查看概念表；用 `groundcast prefs --set speed=1.1` 设置偏好；用 `groundcast feedback <session id> --rating 4 --length too_long` 为会话打分；用 `groundcast suggest` 查看排序的建议。运行 `groundcast --help` 查看全部命令。

## 🗺️ 路线图

五个里程碑全部完成即为 v1；每个阶段完成后都可单独使用。

| 阶段 | 新增内容 |
|---|---|
| M1 | 带文字层的 PDF、Markdown、纯文本；简要设置表单；经由 Claude 的 Writer、Verifier、Editor；Kokoro 单人旁白；MP3 与 HTML 文稿 |
| M2 | 对话式设置；双主持人；章节；文字问答；测验；离线回忆提问；偏好与变更日志 |
| M3 | PPTX、DOCX、网页；通过本地语音识别处理视频 |
| M4 | 基于已学习偏好的排序建议；按评分细则迭代提示词；本地声明核查器评估 |
| M5 | 通过本地 OCR 处理扫描件与手写稿，使用前须经你确认 |

## ⚙️ 配置

- **数据目录**：资料、文本片段、个人档案与会话都存放在仓库之外，默认位于操作系统的用户数据目录，可用 `GROUNDCAST_DATA_DIR` 覆盖。
- **模型权重**：首次使用时下载到操作系统的用户缓存目录，可用 `GROUNDCAST_MODEL_DIR` 覆盖；从不放进仓库。
- **设置**：一个可选的、位于仓库之外的 TOML 文件（用户配置文件，或 `GROUNDCAST_CONFIG` 指定的文件），加上形如 `GROUNDCAST_<SECTION>_<KEY>` 的环境变量，两者冲突时以环境变量为准。[`config/groundcast.example.toml`](../../config/groundcast.example.toml) 列出了全部配置项及其默认值；`groundcast paths` 显示当前使用的路径。API key 只从环境变量读取，从不来自文件。

## 🧩 模型与许可证

MIT 只覆盖本仓库的代码。下列各模型与程序保留各自的许可证；权重在安装时下载，从不提交。

| 组件 | 用途 | 代码 / 权重许可证 | Groundcast 的运行方式 |
|---|---|---|---|
| [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) | 语音合成（M1） | Apache-2.0 / Apache-2.0 | Python 包；其进程内加载 espeak-ng 的部分已被屏蔽 |
| [spaCy `en_core_web_sm`](https://github.com/explosion/spacy-models) | 为 Kokoro 的发音做英语文本分析 | MIT / MIT | Python 包 |
| [Piper](https://github.com/OHF-Voice/piper1-gpl) | 备用语音合成（`tts.engine = "piper"`；见示例配置） | GPL-3.0 / 按音色而定 | 仅作为独立进程（`pip install piper-tts`） |
| espeak-ng | 可选的发音回退，用于 Kokoro 不认识的词 | GPL | 仅作为独立程序（`tts.espeak_bin`） |
| ffmpeg、poppler | 音频编码、PDF 文本提取 | LGPL 构建、GPL | 独立程序（conda-forge） |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) 与 [Whisper large-v3-turbo](https://huggingface.co/mobiuslabsgmbh/faster-whisper-large-v3-turbo) | 视频与音频的语音识别（M3） | MIT / MIT | Python 包（`asr` 附加依赖） |
| [Tesseract](https://github.com/tesseract-ocr/tesseract) 及其英语数据 | 扫描件与手写稿的文字识别（M5） | Apache-2.0 / Apache-2.0 | 独立程序（conda-forge） |

## ⚠️ 负责任地使用

- **订阅模式**只会启动你自己安装的 CLI。遵守所用提供方的条款是你自己的责任；不支持多人共用一个订阅。
- **数据归你所有**：资料、提取的文本、个人档案、脚本与音频都留在数据目录中。请勿传播由课程资料生成的音频。
- **合成语音**：每个音频文件都会声明其为 AI 生成，Groundcast 从不克隆真实人物的声音。
- **局限**：LLM 核对能减少错误但无法完全消除，也无法发现资料本身就存在的错误。

## 📚 文档

| 主题 | 位置 |
|---|---|
| 智能体指令、命令、目录布局 | [`AGENTS.md`](../../AGENTS.md) |
| 提交格式、工作流、分支命名 | [`.gitmessage`](../../.gitmessage) |
| 环境定义 | [`environment.yml`](../../environment.yml)、[`pyproject.toml`](../../pyproject.toml) |
| 配置项参考 | [`config/groundcast.example.toml`](../../config/groundcast.example.toml) |
| Verifier 评估集（`groundcast eval`） | [`evals/seeded/`](../../evals/seeded/) |
| 脚本质量评估用的简报（`groundcast eval-quality`） | [`evals/quality/`](../../evals/quality/) |
| 提示词提炼所用来源的登记表（原件只留在本地） | [`references/`](../../references/README.md) |
| 提炼出的规则及其来源 | [`docs/distillation/`](../distillation/README.md) |

## 🤝 参与贡献

欢迎提交 issue 和拉取请求。Groundcast 是个人项目，范围以维护者的设计为准；动手前请先阅读[贡献指南](CONTRIBUTING.zh-CN.md)。

## 🔗 相关资源

- [Claude Code](https://github.com/anthropics/claude-code)：默认的 LLM 后端，以无界面模式调用。
- [FastAPI](https://fastapi.tiangolo.com)：本地服务框架。
- [FActScore](https://doi.org/10.18653/v1/2023.emnlp-main.741)：把长文本拆分为原子陈述。
- [MiniCheck](https://doi.org/10.18653/v1/2024.emnlp-main.499)：低成本地依据源文档核查陈述。
- [Dunlosky et al. 2013](https://doi.org/10.1177/1529100612453266)：练习测试与间隔学习的证据，是测验与回顾设计的依据。

## ⚖️ 法律信息

- **许可证**：[MIT](../../LICENSE)
- **行为准则**：[Contributor Covenant 3.0](../../CODE_OF_CONDUCT.md)
- **安全**：请按 [SECURITY.md](../../SECURITY.md) 私下报告漏洞
<!-- - **Terms of Service**: [TERMS.md](../../TERMS.md) (add when the project runs a hosted service) -->

## ⭐ Star History

<a href="https://www.star-history.com/#rohanhong/groundcast&Date">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=rohanhong/groundcast&type=Date&theme=dark">
    <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=rohanhong/groundcast&type=Date">
    <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=rohanhong/groundcast&type=Date" width="600">
  </picture>
</a>
