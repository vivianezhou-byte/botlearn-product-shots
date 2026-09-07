# 浏览器模式走查手册

浏览器模式检查学员实际看到的渲染、交互反馈、可访问性和平台界面集成。它既能检查仓库构建的本地预览，也能检查普通用户提供的线上课程地址；主流程都是按课程顺序逐页走完。

## 目录

- [工具能力](#工具能力)
- [独立测试浏览器](#独立测试浏览器)
- [选择目标](#选择目标)
- [线上课程寻址](#线上课程寻址)
- [静态页面阅读门](#静态页面阅读门)
- [逐页流程](#逐页流程)
- [页面检查脚本](#页面检查脚本)
- [交互与可访问性](#交互与可访问性)
- [视口矩阵](#视口矩阵)
- [平台界面集成](#平台界面集成)
- [证据与收尾](#证据与收尾)

## 工具能力

按当前环境选择工具，不依赖特定 Agent 或产品名称。完整浏览器走查需要以下能力：

| 能力 | 用途 |
|---|---|
| 导航和读取页面结构 | 打开课程、展开目录、逐页前进并确认当前位置 |
| 执行页面 JavaScript | 检查溢出、坏图、可访问性和 DOM 状态 |
| 点击、输入和键盘操作 | 验证完整交互与焦点路径 |
| 调整视口 | 验证桌面、平板、手机布局 |
| 读取控制台和网络请求 | 发现运行时错误、404 和外部依赖 |
| 截图 | 为 finding 留证 |

缺少任一关键能力时继续完成可执行部分，并在报告中列出未验证项；不要把源码推断写成实机结论。

## 独立测试浏览器

浏览器走查默认不复用用户日常 Chrome、工具自带 profile 或其他 worker 的会话。在首次导航前启动一个专属测试浏览器：

```bash
python3 <skill-dir>/scripts/browser_session.py start <run-dir> \
  --session-id worker-01 --entry-url <course-url>
```

脚本默认用 `--port 0` 自动分配本地 CDP 端口，并在 `<run-dir>/browser-sessions/worker-01/` 下保存 `browser.json`、`browser.log` 和该 worker 独占的 `profile/`。

1. 先执行 `browser_session.py status <browser.json>`；只有 `processMatches`、`devtoolsReady` 和 `isolationValid` 全为 `true` 才继续。
2. 默认只用 `cdp_control.py <browser.json> ...` 控制它。该脚本先核对清单、进程、端口、新 Profile 路径和 `launchId`，再用 Playwright-over-CDP 连接；不接受硬编码端口。
3. 其他浏览器工具只有能显式 attach `browser.json.cdpUrl` 并核对同一 `launchId` 时才可使用。无法连接时把实机链路标为 blocked，不得回退到日常 Chrome、已有扩展会话、应用内浏览器或其他 worker。
4. 禁止向新 `profile/` 复制 `Default`、`Local State`、`First Run`、Cookie、`Login Data` 或任何旧 Profile 文件。登录必须由用户在这个新窗口里完成。
5. 并行 worker 必须使用不同 `--session-id`；仓库预览还要使用不同 `<preview-port>`，并在 `preview_course.py` 和 `walkthrough_urls.py` 中传入同一端口。
6. 线上走查会写入进度时，每个并行 worker 还必须使用不同测试账号。不得共用同一 profile、`browser.json` 或可写账号。
7. 结束后用 `browser_session.py stop <browser.json>` 停止本次进程，保留 profile 和日志，不登出、不清数据。

先按 `requirements.txt` 安装 Playwright Python 包；这里只连接已启动的 Chrome，不运行 `playwright install`。固定控制脚本的最小用法：

```bash
python3 <skill-dir>/scripts/cdp_control.py <browser.json> status
python3 <skill-dir>/scripts/cdp_control.py <browser.json> read
python3 <skill-dir>/scripts/cdp_control.py <browser.json> snapshot
python3 <skill-dir>/scripts/cdp_control.py <browser.json> navigate <url>
python3 <skill-dir>/scripts/cdp_control.py <browser.json> click 'role=button[name="提交"]'
python3 <skill-dir>/scripts/cdp_control.py <browser.json> type 'label=邮箱' '<text>'
python3 <skill-dir>/scripts/cdp_control.py <browser.json> wait-for 'text=已完成'
python3 <skill-dir>/scripts/cdp_control.py <browser.json> --frame 'iframe' click 'text=下一页'
python3 <skill-dir>/scripts/cdp_control.py <browser.json> press Enter
python3 <skill-dir>/scripts/cdp_control.py <browser.json> resize 375 812
python3 <skill-dir>/scripts/cdp_control.py <browser.json> screenshot <output.png>
```

元素定位默认按 CSS 解释，也支持 `css=`、`text=`、`label=`、`placeholder=`、`testid=`、`title=`、`alt=` 和 `role=button[name="..."]`。优先使用 role、label 或可见文本，只在缺少稳定语义时使用 CSS。`--frame <css>` 可重复以进入嵌套 iframe；`tabs`、`--page-index` 和 `--target-id` 用于明确选择标签页。

`hover`、`check`、`uncheck`、`select`、`download`、`open-tab` 和 `close-tab` 只在走查步骤需要时调用。每次 CLI 调用结束只断开 Playwright 客户端，不关闭 Chrome；Chrome 生命周期只归 `browser_session.py stop` 所有。

只有用户明确要求复用已有浏览器，并接受会话隔离和并行能力不可验证时，才可转入非隔离模式。非隔离模式不生成或伪造 `browser.json`，Agent 仿真不得建档，页面走查必须把缺口写入 `unverifiedItems`。

## 选择目标

### 仓库预览

```bash
python3 scripts/preview_course.py courses/<slug> --build-only --port <preview-port>
python3 <skill-dir>/scripts/walkthrough_urls.py courses/<slug> --port <preview-port>
```

单 worker 预览默认使用 `127.0.0.1:4173`。并行时每个 worker 分配独立 `<preview-port>`；启动服务后先确认根地址返回成功，再开始逐页导航。

| 地址 | 用途 | 限制 |
|---|---|---|
| 完整预览页面 `http://127.0.0.1:<port>/?node=<index>` | 判断目录、导航、进度、Coach、iframe 高度和实际内容宽度 | sandbox iframe 通常无法从平台页面直接读取 Node DOM |
| 课件直连页 `http://127.0.0.1:<port>/nodes/<id>/index.html` | 检查 Node 内 DOM、样式、脚本和交互 | 只呈现课件内容，布局结论需回到完整预览页面确认 |

`?node=` 是全课全局顺序（课程导学 → 主线 → 课程总结），不要手工计算；始终以 `walkthrough_urls.py` 输出为准。清单每行的 `display`（`第 N 课「课程标题」第 M 页：页面标题`）就是报告 finding 的 `location.display` 取值，记录问题时一并抄下。

### 线上课程

用户只给 `http(s)` 课程地址时，不查找仓库、不运行合规脚本，也不启动本地预览。直接使用本次独立测试浏览器打开该地址，并保留该 profile 内的测试会话。

- 页面要求登录、验证码或组织权限时，让用户在浏览器里亲自处理；不要要求用户发送密码、验证码、Cookie 或令牌。
- 先确认课程名称、账号身份、可见范围和起始页。若用户只能看到部分课节，把可见范围写进报告，不能声称走完了全课。
- 线上课程会保存进度或提交答案时，优先使用测试账号。若操作可能消耗次数、发消息、产生付费、提交不可撤销答案或覆盖正式进度，则跳过该状态并记录未验证项。
- 不调用或猜测生产内部 API 来批量获取课程数据；评估对象是普通学员通过界面能看到和能操作的内容。

## 线上课程寻址

线上单页应用经常在翻页后保持同一个 URL。`location.url` 只能帮助打开课程，不能单独定位问题页。首次走查先建立一份页面清单：

1. 展开课程目录，按界面顺序记录课程导学、课、单元和页面标题；目录只加载当前分组时，边走边补清单。
2. 从课程入口或用户指定起点开始，用页面提供的“下一页”前进。每次前进后核对目录高亮、页码、标题和正文首个稳定标题。
3. 给每页记录一个普通用户可复现的位置：`第 N 课「课标题」第 M 页：页面标题`。没有课序或页序时，使用完整面包屑，例如 `课程目录 > 品牌商单 > 定价方法 > 报价指令`。
4. 记录进入该页的界面操作，例如“展开第 12 课 → 点击第 17 页「报价指令」”。如果页面支持稳定的分享链接，再把该链接写入 `location.url`；不要把临时签名地址当永久定位。
5. 若课程不显示页标题，用正文第一个稳定标题或控件名称代替，并在 display 末尾标注，例如 `第 4 页：正文标题「先问需求」`。

定位字段分工如下：

| 字段 | 线上模式写法 |
|---|---|
| `location.display` | 目录层级 + 课序/页序 + 页面标题，供普通用户翻页查找 |
| `location.url` | 课程入口或该页稳定分享链接；SPA 全程同址也照实记录 |
| `location.path` | 留空；没有仓库时不得猜源码路径 |
| `location.line` | 写 `0` |
| `nodeId` | 页面可见或 URL 明示 ID 时照实写；否则写 `online-page-<序号>`，只作报告内部稳定键 |
| 复现步骤 | 从课程入口开始写界面点击路径，不能只写“打开 Node” |

同名页面必须带上父级课或单元；跨页问题用目录范围描述。平台界面问题写 `平台界面：目录`、`平台界面：Coach` 等，不塞进某个课件页。

## 静态页面阅读门

首次开始逐页学习前读取 `page-learning-protocol.md`。每页点击「下一步」或等价前进控件前，必须先完成并记录：

- 页面标题和人类可读位置。
- 一句话内容总结。
- 2–4 个核心知识点。
- 一个案例、公式、判断规则或行动方法。
- 内容疑点；没有时明确写「未发现问题」。
- Quiz 页记录题目、Persona 实际选择、正文依据和提交反馈。

记录完成后立即写入 `page_read` 动作，然后才能前进。任一语义字段缺失、Quiz 证据不全或点击「下一步」前没有 `page_read` 时，该页只能标记为 `partial`，不计入已读。页面停留时间只作为快速翻页异常线索，不能替代上述语义证据。

## 逐页流程

从页面清单第一页走到最后一页，每页执行：

1. 导航到目标页，核对目录高亮、课序、页序、标题和导航状态。
2. 以学员视角通读：文字是否自然准确、信息层级是否清楚、图文是否对应、附件形态是否正常；完成本页语义记录并写入 `page_read`。
3. 仓库模式复核本页静态 finding；线上模式直接记录页面现象。
4. 操作全部可交互控件，覆盖成功、失败、重置和边界状态。
5. 用键盘重走主要路径，检查焦点顺序、焦点可见、Enter/Space/Escape 行为和焦点陷阱。
6. 仓库模式可打开 Node 直连地址执行页面检查脚本；线上模式只能在当前生产页面和可访问的同源 frame 内检查。浏览器无法读取跨域 iframe 时，以视觉和操作结果为准，并把 DOM 检查记为未验证。
7. 读取控制台与网络记录；错误消息、失败请求和非预期外部请求都记录 finding。

只有出现 finding 时才截图。截图优先包含课程目录高亮、页面标题和问题区域；一张图放不下时，补一张定位图和一张问题细节图。每完成一课，记录已走页数、未走页数和窄屏复核范围。

## 页面检查脚本

在仓库 Node 直连页，或线上页面当前可访问的文档上下文中执行：

```js
(() => {
  const d = document;
  const controls = [...d.querySelectorAll("button,input,select,textarea,[role='button'],[role='checkbox'],[role='radio']")];
  const nameOf = (el) => (
    el.getAttribute("aria-label") ||
    (el.getAttribute("aria-labelledby") || "").split(/\s+/).map(id => d.getElementById(id)?.textContent || "").join(" ") ||
    el.labels?.[0]?.textContent ||
    el.textContent ||
    el.getAttribute("title") ||
    el.getAttribute("alt") ||
    el.getAttribute("value") ||
    ""
  ).trim();
  const ids = [...d.querySelectorAll("[id]")].map(el => el.id).filter(Boolean);
  const duplicateIds = [...new Set(ids.filter((id, i) => ids.indexOf(id) !== i))];
  return {
    title: d.title,
    lang: d.documentElement.lang || null,
    hasViewport: !!d.querySelector('meta[name="viewport"]'),
    overflowX: d.documentElement.scrollWidth - window.innerWidth,
    heading: d.querySelector("h1,h2")?.textContent?.trim() || null,
    brokenImgs: [...d.images].filter(img => img.complete && img.naturalWidth === 0).map(img => img.currentSrc || img.src),
    missingAlt: [...d.images].filter(img => !img.hasAttribute("alt")).length,
    unlabeledControls: controls.filter(el => !nameOf(el)).map(el => el.outerHTML.slice(0, 120)),
    duplicateIds,
    smallControls: controls.filter(el => {
      const r = el.getBoundingClientRect();
      return r.width > 0 && r.height > 0 && (r.width < 40 || r.height < 40);
    }).map(el => ({name: nameOf(el).slice(0, 30), width: Math.round(el.getBoundingClientRect().width), height: Math.round(el.getBoundingClientRect().height)})),
  };
})()
```

脚本结果是线索：例如文字链接不必强制 40px 高；是否构成 finding 要结合控件类型和实际可操作性判断。

## 交互与可访问性

- **通用控件**：操作后必须出现可观察状态变化；禁用态不可触发；重复操作结果稳定。
- **Quiz**：选中 → 提交 → 反馈 → 正误状态 → 清除或重置；多选、无标准答案和错误分支分别验证。
- **Dialog/lightbox**：能打开，初始焦点合理；关闭按钮、Escape 和 backdrop 按设计生效；关闭后焦点回到触发控件。
- **键盘**：所有操作无需鼠标也能完成；Tab 顺序符合视觉顺序；自定义控件具有语义、名称和键盘行为。
- **焦点**：焦点样式清晰且不被裁切；不可把 `outline` 去掉却不给等价替代。
- **动效**：减少动态效果偏好下停用非必要动画，内容不能依赖动画结束后才可读或可操作。
- **媒体**：图片替代文本传达同等信息；视频有可理解的名称、控制方式和必要的字幕或文字替代。
- **表单**：输入控件有可访问名称；错误信息与字段关联，并说明如何修正。

## 视口矩阵

| 档位 | 建议尺寸 | 必查 |
|---|---|---|
| 桌面 | 1280×800 | 全量逐页、基线布局、多列结构 |
| 平板 | 768×1024 | 断点切换、侧栏和卡片降列 |
| 手机 | 375×812 | 单列、无主体横向溢出、可读字号、可操作控件 |

桌面档全量走。平板和手机档至少覆盖：已有 finding 的页、表格/多列/宽媒体页、静态扫描标记响应式风险的页，以及每种交互模式的代表页。切换视口后重新执行页面检查脚本。

完整预览页面有屏外收起组件时，不要只看 `scrollWidth` 差值；以学员能否实际拖动主体、内容是否被截断为准。

## 平台界面集成

每课至少抽查首页、一个中间页和末页：

- 目录高亮、页码和当前 Node 一致；跨 unit 前后导航正确。
- 首尾按钮禁用逻辑正确，键盘操作与可访问状态一致。
- iframe 高度完整，无双滚动条、截断或明显布局跳动。
- Coach 展开/收起不遮挡内容，焦点不会落入不可见区域。
- 系统任务或生产任务展示正确内容和状态，无控制台或网络错误。

平台界面问题由平台界面负责人修复，不在课程 Node 内打补丁。

## 证据与收尾

- 截图命名 `<finding-id>-<page-key>-<viewport>.png`，放在报告同目录的 `evidence/`；线上模式不要把姓名、手机号、邮箱、组织信息、Cookie 或令牌带进截图和日志。
- 在报告 JSON 的 `findings[].reproduction` 写明“操作前提 → 操作 → 预期 → 实际”，动态问题在 `evidence[]` 补充控制台或网络信息。
- 在 `coverage` 分别记录 `scopePages`、`visitedPages`、`readPages`、交互页和 Quiz 页的分母/分子，再记录各视口复核数和能力状态；仓库模式同时记录静态扫描数。线上模式把合规预检和静态扫描标为 `not_run`，原因写“用户未提供课程仓库”，不因此把浏览器结论降为未完成。
- 回归时重走受影响 Node、相邻导航路径和同类组件代表页，并把结果写入 `regressions`。
- 最后按需读取 `report-schema.md`，校验 JSON 并由固定 Jinja2 模板生成同名 HTML，不手写 Markdown 或 HTML 报告。
- 仓库模式结束后停止本次启动的预览服务。线上模式不要登出测试账号、清空独立 profile 或改动课程权限；若测试产生了可恢复的草稿或临时状态，只在用户授权且能确定目标时恢复。
