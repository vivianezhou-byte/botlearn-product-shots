# botlearn-product-shots

BotLearn 课程平台真实截图 → 运营物料（学员上手手册/长图/海报）的 Claude Code skill。
模拟新用户实机走课程平台，采集真实截图，按品牌规范排版成成品。

## 安装（3 步）

前置：macOS + Chrome + [Claude Code](https://claude.com/claude-code) + Python 3。

```bash
# 1. 克隆到 Claude Code 的 skills 目录
git clone https://github.com/vivianezhou-byte/botlearn-product-shots.git ~/.claude/skills/botlearn-product-shots

# 2. 装 Python 依赖
pip3 install -r ~/.claude/skills/botlearn-product-shots/requirements.txt

# 3. 重启 Claude Code 会话即生效
```

## 怎么用

打开 Claude Code，直接说需求，例如：

- 「用测试站给 AI 领导力课程拍一套新用户截图」
- 「做一张课程上手长图」
- 「手册里的截图是旧界面了，换成新版」

Claude 会自动加载本 skill：弹出一个独立测试浏览器 → 你在窗口里用手机号登录（兑换码找 Susan 现要，**生产/测试两环境的码不通用**）→ 之后采集、归档、排版、渲染检查全自动。

## 三条铁律

1. 产品能力只用真截图呈现，不 AI 生图伪造界面。
2. 成品里不得出现真实用户信息、¥ 符号、「10 倍」等极限词。
3. 任何对外成品，首发前先给 Susan 过目。

## 更新

```bash
cd ~/.claude/skills/botlearn-product-shots && git pull
```
