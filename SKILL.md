---
name: botlearn-product-shots
description: |
  模拟新用户实机走 BotLearn 课程平台（course.botlearn.com.cn / course.test.botlearn.ai），采集真实产品截图，并排版成对外运营物料——学员上手手册/长图、产品功能海报、发群指导图。只要用户想要「课程平台的真实截图」或「基于真实截图的物料」，即使没说"截图"二字也应触发：做上手手册、上手长图、新学员指引、把产品界面做成海报、更新手册里的截图、给某功能拍个图。
  ROUTING PRIORITY — do NOT use this skill when:
  - 找课程的问题/QA/巡检/错别字/坏按钮（产出是问题报告）→ botlearn-course-walkthrough
  - 只要品牌规范/CSS tokens 本身 → botlearn-brand（本 skill 在排版阶段会自动调它）
  - AI 生成的图（封面/插画/小红书图卡，不含真实截图）→ baoyu-cover-image / baoyu-xhs-images / baoyu-image-gen
  - 做课程内容本身 → botlearn-course
  USE this skill when: 产出物是「真实产品截图」或「以真实截图为素材的成品物料」。
---

# BotLearn 产品截图 → 运营物料

像一个真正的新学员那样走一遍课程平台，把关键画面拍下来，再排成手册或海报。核心原则：**产品能力只能用真截图呈现，不从文案推、不 AI 生图伪造界面**（Susan 定的核验红线）。

## 流程总览

```
① 准备环境与账号 → ② 实机采集截图 → ③ 归档+索引 → ④ 排版产出物料 → ⑤ 渲染亲眼检查 → 交 Susan 审
```

## ① 准备

1. **先和 Susan 确认目标环境**——两套环境是两个独立网站，账号体系和兑换码互不通用，每次任务开始时明确用哪个，不要默认沿用上次的：

| 环境 | 地址 | 用途 | 兑换码 |
|---|---|---|---|
| 生产 | `https://course.botlearn.com.cn/` | 对外物料的截图优先来源 | 每次现向 Susan 要生产码 |
| 测试 | `https://course.test.botlearn.ai/` | 新功能抢先拍、可随意折腾 | 每次现向 Susan 要测试码 |

   环境地址若有变更以 Susan 当次给的为准（本表随之更新）。兑换码**一律运行时索取、不落盘不写进任何文件**；测试码在生产站无效，反之亦然——兑换失败先怀疑「码和环境不匹配」再怀疑产品。成品里的图若来自测试站，交付时必须注明。
2. **确认账号状态**：拍「新用户第一眼」需要进度为 0 的账号（每个环境各自独立）；拍功能细节可用已有进度的号。账号登录一律由 Susan 在弹出的浏览器窗口里完成（手机验证码），**不索取密码/验证码**。
3. **启动独立测试浏览器**（脚本随本 skill 附带，在 `scripts/` 下）：

```bash
S=<本skill目录>/scripts
python3 $S/browser_session.py start <run-dir> --session-id shots-01 --entry-url <课程地址>
# status 三项全 true 才继续；之后只用 cdp_control.py 操作
python3 $S/cdp_control.py <browser.json> resize 1280 800
```

首次导航前先读 `references/browser-mode.md`（浏览器前置门、隔离规则照它执行）。依赖按 `requirements.txt` 安装（playwright 只连已启动的 Chrome，无需 playwright install）。

## ② 采集

- 打开 `references/journey-checklist.md`，按「新学员旅程 10 站」清单采集；每次调用可只采子集（用户指哪拍哪）。
- 命名：`{两位序号}-{画面内容}-{desktop|mobile}.png`，序号按手册叙事顺序。
- 视口：桌面 1280×800 为主。**学习页不支持手机端**（16:9 画布，会提示"请使用桌面端"），不要试图截手机端学习页——那张提示图本身倒是手册素材。
- 涉及 Agent 对话的画面：用预设演示人设现跑一遍真对话（默认：跟练汇报 PPT 方向 / 验收人上级两周 / 3M 短板=思维），**绝不截真实用户的对话或昵称**。
- 每采一张，同步记一句「这张图在讲什么」——归档 README 直接用。

## ③ 归档

- 截图进 `16-服务/<课程名>/产品截图_<YYYYMMDD>/`（服务交付权威目录），关键画面与逐页留底分开放。
- 写 README.md 索引：每张图一行「内容 + 手册对应步骤 + ⚠️红线标注」。参考已有样例 `16-服务/AI领导力/产品截图_20260903/README.md`。
- 采集完 `browser_session.py stop`（保留 profile 不登出）。

## ④ 排版产出

- **先调 `botlearn-brand`** 拿 v5 Grid Ink tokens——所有对外 BotLearn 物料的唯一视觉规范。
- 手册/长图：从 `assets/manual-template.html` 起稿（750px 微信长图，已内嵌 tokens 与版式组件：步骤章节/截图卡/三区说明/流程轨/贴士卡），替换内容与图片。
- 渲染：`python3 scripts/render_longimg.py <html> <out.png> 2`（headless Chrome 全页截图，2 倍导出）。

## ⑤ 检查与交付

渲染后**必须亲眼分段看图**（PIL 切 2000px 高的段逐段 Read），文字溢出/图片糊/配色越界都要抓。检查过再交。

### 验收 checklist（交付前逐条过）

- [ ] 成品里没有真实用户昵称/头像/手机号/邮箱
- [ ] 没有 ¥ 符号入图（微信类目禁令）、没有「10 倍」等极限词素材（旧主图带「10倍」不能用）
- [ ] 测试站截图已注明环境；正式站改版后关键图已重截
- [ ] 视觉走 botlearn-brand（红色只做 CTA/强调，不铺底）
- [ ] 渲染成品已逐段亲眼检查
- [ ] **首发前先把成品给 Susan 过目**（机制获批 ≠ 首发获批）
- [ ] 归档：截图库+物料进 `16-服务/<课程名>/`，git 提交；定稿件才走 KB 一键三连（默认 P2）

## 已知陷阱表

| 陷阱 | 具体表现 | 应对 |
|---|---|---|
| 课程顺序解锁 | 节与节、节内页与页都锁；目录项灰色点不动 | 只能逐页点「下一步」推进；「去练习」在交付页出现 |
| 选项点了没发出去 | 测试环境偶发；界面看着点了 | 点完核对出现「已选择」标记；报「暂时无法确认」就点「刷新状态」再重点 |
| 环境抖动 | 「暂时无法连接服务器」 | 刷新页面重试，不是必现 bug，别写进物料 |
| 点「课程首页」弹退出确认 | 学习页内点侧栏顶部会弹「退出这次学习？」 | 正常行为（进度自动保存）；这张弹窗本身是手册素材 |
| 结束练习按钮重名 | 页面上有两个「结束练习」，strict 定位报错 | 聊天内 chip 用 `css=.studyChat_finishActionChip__l8246`，面板按钮用 `get_by_label("学习步骤")` 域内定位 |
| 手机端学习页 | 375 宽直接提示用桌面端 | 别浪费时间截手机学习页；提示页可作「请用电脑学」素材 |
| 长图渲染没看就交 | 计数全绿也可能是坏图 | PIL 分段裁切逐段 Read 亲眼看 |

## 按需加载

- `references/journey-checklist.md` — 新学员旅程 10 站清单 + 每站采集要点（②阶段读）
- `references/browser-mode.md` — 浏览器隔离与操作规范（①阶段首次导航前读）
- 品牌 tokens 已内嵌在 `assets/manual-template.html`；若本机装有 botlearn-brand skill 则以它为准
