# 贡献指南

<p><a href="../../CONTRIBUTING.md">English</a> | <b>简体中文</b></p>

感谢你对 Groundcast 的关注。这是一个代码公开、范围以维护者设计为准的个人项目；本指南说明如何提出改动，以及改动合并前必须满足的要求。

参与本项目即表示你同意遵守[行为准则](../../CODE_OF_CONDUCT.md)。安全问题请按 [SECURITY.md](../../SECURITY.md) 所述私下报告，切勿发到公开 issue。

## 参与方式

- **报告缺陷**：提交 issue，写明你运行了什么、预期结果、实际结果，以及操作系统、Python 版本和 LLM 后端（Claude Code CLI 版本，或 API）。
- **提出建议**：比小修复更大的改动请先开 issue，在动手前商定方案。
- **提交拉取请求**：欢迎对代码、提示词和文档的修复与改进。

## 开发环境

1. 安装 git 与 conda（例如 Miniforge）。
2. 创建并激活环境：
   ```bash
   conda env create -f environment.yml
   conda activate groundcast_env_py312
   ```
3. 修改 `environment.yml` 后，用 `conda env update -f environment.yml` 同步到环境。
4. 运行测试：`python -m pytest`。测试使用模拟的 LLM 后端和静音的语音引擎，因此既不需要 Claude，也不需要 Kokoro 模型。
5. 如果改动涉及 Verifier 或其提示词，还要运行预埋错误测试 `groundcast eval`（会调用已配置的 LLM 后端），并把检出率与误报率同上一次的结果比较。如果这些比率未达到 `[evaluation]` 设置中的通过线，该命令以非零状态退出。

## 工作流程

1. Fork 本仓库并克隆你的 fork。
2. 配置提交模板：`git config commit.template .gitmessage`。
3. 从 `main` 创建短期分支，按 `.gitmessage` 的 Branch Naming 一节命名为 `<type>/<scope>/<short-desc>`（例如 `feature/tts/kokoro-render`）；`git-branch-create` 技能可以代为完成。
4. 按 `.gitmessage` 的格式 `<type>(<scope>): <subject>` 提交，每个提交只做一件事；`git-commit` 技能可以代为起草。
5. 推送到你的 fork，向 `main` 发起拉取请求。说明改了什么、为什么改，并关联对应的 issue。

## 改动规则

- **工件**：代码、注释、日志和仓库内文档一律使用英文且仅限 ASCII。README 与 CONTRIBUTING 文件及其译文例外，见 `AGENTS.md`（Conventions）。
- **不提交用户数据**：切勿提交上传的资料、提取的文本、个人档案数据库、生成的脚本或音频、模型权重、API key 或 token。
- **测试资料**：测试中的示例资料须为自行撰写或采用开放许可，绝不使用课程资料。
- **GPL 程序**：Piper 与 espeak-ng 只作为独立进程运行；MIT 代码从不导入它们。
- **不写死数值**：路径和设置从配置文件、命令行参数或环境变量读取。
- **文档随改动更新**：改动导致文档不准确时，在同一个拉取请求中修正，包括 `README.md` 和 `docs/i18n/` 中的每份译文。

## 发起拉取请求前

- [ ] 测试通过：`python -m pytest`。
- [ ] 改动中没有用户数据、模型权重或密钥。
- [ ] README 与 CONTRIBUTING 文件之外没有非 ASCII 文本：`LC_ALL=C git grep -nI --untracked '[^[:print:][:space:]]' -- . ':!README.md' ':!CONTRIBUTING.md' ':!docs/i18n'` 没有输出。
- [ ] README、CONTRIBUTING 与各自译文内容一致。
- [ ] 提交信息符合 `.gitmessage`。

## 许可证

贡献内容按本仓库的 [MIT 许可证](../../LICENSE)接收。
