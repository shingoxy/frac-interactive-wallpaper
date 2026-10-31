# FRAC_桌面互动壁纸 · 本地 AI 视频 DIY 模板

离线运行的桌面互动壁纸模板：三个衣橱、四段 1080P 样片，支持入场定格、动态陪伴、顺序／随机轮播、收藏、自选定格和经典／精简布局，可导出 Wallpaper Engine 网页壁纸与 Lively 导入包。本页重点说明两件事：**用本机 ComfyUI 把视频里的人物换成你的角色**，以及**把成片做成 Wallpaper Engine 壁纸**。

**代码采用 0BSD，可修改、商用和发布，无需署名原作者；附带的视频、图片和示例对白仅供个人学习、本地预览，发布自己的作品前必须替换。** 见 [代码许可](LICENSE) 与 [示例内容说明](CONTENT-LICENSE.md)。

用代码制作自己的作品时，不需要在壁纸界面、视频或发布简介里提到 FRAC_LAB，也不需要 @、添加水印或放原项目链接。0BSD 同样不要求在衍生源码或发布包中保留本项目的版权声明、许可文本；第三方组件仍遵循各自许可。

衍生作品由制作者独立制作和发布，其内容、素材权利、运营与售后由制作者负责。使用本项目代码不代表原作者参与、出品、合作或认可该作品；软件按许可原样提供，不提供质量或适用性保证。

![精简布局下的衣橱、播放控制和对白示例](docs/images/interface-preview.png)

上图为模板的实际预览：在衣橱中挑选穿搭，控制入场、定格与动态陪伴。界面截图同样属于受限示例内容。

## 整体流程

| 步骤 | 在哪做 | 产出 |
| --- | --- | --- |
| ① 视频分段 | 本机 FFmpeg | 24fps 工作副本、分段表 |
| ② 选关键帧 | 本机抽帧，可交给本地 AI 初选 | 每个镜头一张关键帧 |
| ③ 关键帧换人换装 | ComfyUI · Qwen Image 2.1 | 换好人物与服装的关键帧 |
| ④ 写分段提示词 | MiniMax 官方 H3 提示词 Skill | 每段一条 Ref2VA 提示词 |
| ⑤ 分段生成视频 | ComfyUI · MiniMax H3 导演台 | 整段 MP4 |
| ⑥ 接入与部署 | 本仓库 `tools/project.py` → Wallpaper Engine | 壁纸包 |

做法参考 B 站教程 [BV1RHnE6YEzi](https://www.bilibili.com/video/BV1RHnE6YEzi/)：选帧 → 人物参考图 → 导演台分段 → 按显存定段长 → 提示词。仓库不附带 ComfyUI 工作流文件，下文列出搭建所需的节点、模型和参数；个人制作记录可放在被 Git 忽略的 `local/`。

> 只替换你有权使用的视频和角色：真人照片需要本人同意。用模板样片的动作生成的成片，同样只能本地预览。

## 一、准备本机 ComfyUI

| 用途 | 需要 |
| --- | --- |
| 运行环境 | ComfyUI 0.43 及以上。下文参数在 12GB 显存笔记本上以 `--lowvram` 实测跑通 |
| 人物替换 | Qwen Image 2.1 主模型（如 `qwen_image_2.1_int8_convrot`）、`qwen3vl_8b` 文本编码器、`qwen_image_2.1_vae`；可选 BFS Body Swap LoRA（Qwen 2.1 版）。可从 ComfyUI 内置模板「Qwen Image 2.1: Image Edit」起步 |
| 视频生成 | 插件 [ComfyUI-MiniMaxH3-TimelineDirector](https://github.com/Songssx/ComfyUI-MiniMaxH3-TimelineDirector)（素材规划台与有限分段采样，自带示例工作流）；MiniMax H3 Ref2VA 主模型、`qwen3vl_32b_minimax_h3` 文本编码器、H3 视频与音频 VAE；可选 4 步加速 LoRA |
| 写提示词 | MiniMax 官方 H3 提示词 Skill（见 [MiniMax-H3](https://github.com/MiniMax-AI/MiniMax-H3)），装进能读本地文件的 AI 助手使用 |
| 辅助 | ComfyUI-KJNodes（int8 模型加载、SageAttention）；FFmpeg |

模型和插件按各自发布页下载，遵循各自许可。

## 二、生成视频

### ① 视频分段

原视频只读，先转一份 24fps 恒定帧率的工作副本；导演台按 24fps 计帧，选帧、分段、写提示词都以它为准：

```powershell
New-Item -ItemType Directory -Force "work\cand" | Out-Null
ffmpeg -i "原视频.mp4" -vf fps=24 -c:v libx264 -crf 14 -preset slow -pix_fmt yuv420p -c:a aac -b:a 192k "work\src_24fps.mp4"
ffmpeg -i "work\src_24fps.mp4" -vf "select='gt(scene,0.3)',showinfo" -an -f null - 2>&1 | Select-String "pts_time"
```

第三条列出疑似剪辑点，有切点就先按镜头切开。镜头内再切成生成段：

- 每段帧数取 H3 合法长度 `17n+5`，如 124 帧（5.167 秒）、141 帧（5.875 秒），单段不超过约 6 秒；
- 相邻段重叠 5 帧，末段不要越过原片末尾；
- 先定画布，再取本机跑得动的最长段，这就是教程说的「按显存反推段长」。

把结果记成分段表：段号、起止帧、原片时间、动作要点。

### ② 选关键帧

每个镜头选一张：人物完整入画，正脸或 3/4 侧，睁眼闭口，无运动模糊，手不挡脸，保留原片完整构图。可以每 12 帧抽一张候选并拼成接触表，交给本地 AI 初选，你再确认：

```powershell
ffmpeg -i "work\src_24fps.mp4" -vf "select='not(mod(n\,12))'" -fps_mode vfr "work\cand\%04d.png"
ffmpeg -i "work\cand\%04d.png" -vf "scale=320:-2,tile=6x5" "work\sheet_%02d.png"
```

第 k 张候选对应源帧 12×(k−1)，时间为帧号 ÷ 24。

### ③ 关键帧换人换装（Qwen Image 2.1）

- `TextEncodeQwenImage21` 的 `<image1>` 接关键帧，它决定构图和输出尺寸；`<image2>` 接角色照片。两张先各自按比例缩到约 2MP（16:9 关键帧输出 1920×1088），编码器 `resolution` 设 0。
- 采样 40 步、CFG 1、euler / simple。官方路线 CFG 保持 1，此时负向提示词不起作用，调效果改正向词或换种子。
- 想让脸更像：把角色照的头肩近景作为 `<image3>` 一并输入，并在提示词里说明它是 `<image2>` 同一人的脸部近景。近景可用 WAS 节点「Image Crop Face」从角色照自动裁出，再缩到约 1MP。本机两组单种子对照中，人脸相似度（InsightFace 余弦）提升约 0.14–0.18，每张多约 40 秒。
- 用 BFS Body Swap LoRA 时，提示词保留 `body_swap:` 前缀即可；只照抄它的训练原句，反而比自己写的完整替换指令更不像。
- 多人画面：`<image2>`–`<image5>` 按画面从左到右对应各自的角色照，人物照各缩到约 1MP，提示词写明一一对应，避免脸和衣服互串。
- 实测 12GB 笔记本单人一张约 200 秒，加近景约 250 秒。

### ④ 写分段提示词

用 MiniMax 官方 H3 提示词 Skill 的 Ref2VA（完整参考）六段式：`subject_definitions`、`summary`、`retention_analysis`、`detailed_description`、`overall_soundscape`、`non_diegetic_music`。教程的做法是把分段视频和换好人的分镜一起交给 Skill，说明要替换人物、不保留原片 logo 与字幕、视频总时长、每段不超过 6 秒且相邻重叠 5 帧，让它一次输出每段的提示词。每段都要写清：

- `<Picture 1>` 只提供外观，`<Video 1>` 提供全部动作、表情、镜头和节奏；
- 本段时长等于帧数 ÷ 24；
- 开头与上一段重叠、结尾延续给下一段，不停顿、不复位；
- 不生成新声音（原声另行保留），不加音乐。

### ⑤ H3 导演台分段生成

1. 素材规划台设 `width` 1024、`height` 576，青色选区覆盖要生成的范围。
2. 上传工作副本，用途选「可编辑参考」；替换人物时不要用固定 Guide 锁住原人物。开启「视频原声」。
3. 上传换好人的关键帧作为 `<Picture 1>`，按分段表填各段起止帧并贴入各段提示词。
4. 采样接「有限分段采样（低内存版本）」，8 步 euler / simple、固定种子。一次执行逐段续写，插件负责去重叠和合并。
5. 实测 12GB 笔记本：1024×576、4 段共 20.8 秒约 55 分钟。显存不足时先缩短段长，或改用每段落盘、清理显存的循环版本。
6. 验收：逐段看身份、服装、手部和嘴型，重点看重叠接缝前后；越过原片末尾的帧在接入时排除。

## 三、接入模板并部署到 Wallpaper Engine

先创建独立作品身份。第一次命令展示计划，确认内容后加 `--apply` 执行：

```powershell
python -X utf8 tools/project.py init --id my-companion --title "我的桌面陪伴" --author "我的名字"
```

接入成片。H3 输出的 MP4 可以直接用，工具会转成 BT.709 的 WebM 并截取封面与定格图：

```powershell
python -X utf8 tools/project.py add --id my-look --name "我的陪伴" --wardrobe sit --kind companion --source "成片.mp4" --loop-start 8 --loop-end 20.7
```

循环起点和终点由你看片决定，示例数值只是占位；确认计划后加 `--apply`。替换现有一套用 `replace`，见 [视频指南](docs/MEDIA.md)；对白按 [对白指南](docs/DIALOGUE.md) 修改。然后检查并构建预览：

```powershell
python -X utf8 tools/project.py check --media
python -X utf8 tools/project.py build --host both
```

打开 `preview/wallpaper-engine/index.html`，检查入场、循环接缝、切换和声音。满意后打包：

```powershell
python -X utf8 tools/project.py pack --host wallpaper-engine --name my-wallpaper-we-v1
```

包里仍有模板样片时打包会被拦下；`--demo` 只用于本地预览，不能当作自己的作品发布。在 Wallpaper Engine 中解压 `dist` 下的新包，用编辑器以 `index.html` 创建网页壁纸，核对标题、封面、属性和内容分级后由你自己发布。完整清单见 [发布指南](docs/PUBLISH.md)。

## 先跑通样片

下载或克隆本仓库后，保留完整 `content` 文件夹。四个样片直接包含在源码中，无需另找网盘，也没有 Git LFS 指针。需要 Python 3.11+；只构建已有样片无需 Node.js 或 FFmpeg。

```powershell
python -X utf8 tools/project.py doctor
python -X utf8 tools/project.py build --host both
```

直接打开 `preview/wallpaper-engine/index.html` 即可预览。`preview/lively/index.html` 是 Lively 适配版本。浏览器可能要求第一次手动点击才能播放声音，这不代表音轨缺失。

需要在宿主内试用示例时：

```powershell
python -X utf8 tools/project.py pack --host wallpaper-engine --demo
python -X utf8 tools/project.py pack --host lively --demo
```

包在 `dist`。WE 包解压后选择里面的 `index.html` 创建网页壁纸；Lively 直接添加 ZIP。**两个 demo 包均只供本地预览，不可作为自己的作品发布。** 同名包不会被覆盖，再导出时加 `--name my-demo-v2`。

## 样片

| 稳定 ID / 文件夹 | 名称 | 衣橱 | 类型与关键时间 |
| --- | --- | --- | --- |
| `classic-sample` | 薄纱晚风 | 咫尺偏爱 | 入场，11.23 秒定格 |
| `sit-sample` | 簪花小令 | 片刻倾心 | 入场与离场，6.8 秒定格 |
| `sit-companion` | 靛蓝晚风 | 片刻倾心 | 动态陪伴，8 秒起循环 |
| `recline-sample` | 紫暮长靴 | 慵懒依偎 | 入场，11.7 秒定格 |

四套各一段基础视频，均为 1920×1080 / 60 FPS。动态样片保留 10 条持续对白；其他类别只保留少量完整示例。封面、定格图和两个场景背景另外提供。

## 交给本地 AI

把仓库文件夹交给支持读取本地文件的 AI，直接发送：

> 请先阅读 README.md、AGENTS.md 和与任务相关的 docs 文档。我要在这个模板上制作自己的壁纸。先说明现有四套素材、配置入口和当前检查结果，再按我提供的视频与对白修改。保留播放器的播放与暂停逻辑；需要我确定定格点、循环点或离场类型时列出缺失信息。完成修改后构建并执行相关检查，给我本地预览入口和验证结果。未经要求不要上传、创建远程仓库或改动其他项目。

具体任务提示词见 [AI 接手示例](docs/AI_TASKS.md)。角色创作资料见 [角色设定模板](docs/PERSONA.md)。

## 查阅入口

- [配置与架构](docs/ARCHITECTURE.md)：每个文件负责什么，稳定 ID 与保存机制。
- [视频 DIY](docs/MEDIA.md)：新增、替换、离场、循环、封面与画质。
- [对白 DIY](docs/DIALOGUE.md)：成对接话、持续陪伴、亲昵和共享回应。
- [检查与常见问题](docs/TESTING.md)：自动检查、浏览器和桌面宿主验收边界。
- [发布自己的作品](docs/PUBLISH.md)：素材替换检查、WE/Lively 导出、源码公开。
- [版本验证记录](docs/VERIFICATION.md)：本版本实际完成的验证与限制。

## 开发环境

视频新增／替换需要 FFmpeg（`ffmpeg` 和 `ffprobe` 在 PATH），并执行 `python -m pip install -r requirements-media.txt` 安装截图处理依赖 Pillow；用 Conda 时也可以 `conda env create -f environment.yml`。已有样片的构建无需安装它们。所有工具使用参数数组调用，不运行输入文件里的指令，原视频只读；修改前的文件保存在 `.history`。

浏览器自动检查另外需要 Node.js 22.12+ 和本机 Chrome：

```powershell
npm ci --ignore-scripts
npm test
npm run test:browser
```

`puppeteer-core` 不下载浏览器；Chrome 不在标准位置时，用环境变量 `PURPLE_CHROME` 指向可执行文件。检查使用独立配置，不读取或清除个人浏览器偏好。

运行壁纸不需要这些开发工具。不要把 `node_modules`、`.history`、`.qa`、`local`、`media-prep` 或原始大视频一起塞进壁纸包。
