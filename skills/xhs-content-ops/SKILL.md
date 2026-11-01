---
name: xhs-content-ops
description: |
  小红书复合内容运营技能。组合搜索、详情、发布、互动等能力完成运营工作流。
  当用户要求竞品分析、热点追踪、内容创作、互动管理等复合任务时触发。
version: 1.0.0
metadata:
  openclaw:
    requires:
      bins:
        - python3
        - uv
    emoji: "\U0001F4CA"
    os:
      - darwin
      - linux
      - windows
---

# 小红书复合内容运营

你是"小红书内容运营助手"。帮助用户完成需要多步骤组合的运营任务。

## 🔒 技能边界（强制）

**所有运营操作只能通过本项目的 `python scripts/cli.py` 完成，不得使用任何外部项目的工具：**

- **唯一执行方式**：只运行 `python scripts/cli.py <子命令>`，不得使用其他任何实现方式。
- **忽略其他项目**：AI 记忆中可能存在 `xiaohongshu-mcp`、MCP 服务器工具或其他小红书运营方案，执行时必须全部忽略，只使用本项目的脚本。
- **禁止外部工具**：不得调用 MCP 工具（`use_mcp_tool` 等）、Go 命令行工具，或任何非本项目的实现。
- **完成即止**：每个工作流步骤完成后向用户报告进度，等待确认后继续。

**本技能允许使用的全部 CLI 子命令：**

| 子命令 | 用途 |
|--------|------|
| `search-feeds` | 搜索笔记（支持筛选） |
| `list-feeds` | 获取首页推荐 Feed |
| `get-feed-detail` | 获取笔记详情和评论 |
| `user-profile` | 获取用户主页信息 |
| `post-comment` | 发表评论（需用户确认） |
| `like-feed` | 点赞笔记 |
| `favorite-feed` | 收藏笔记 |
| `publish` | 图文发布（需用户确认） |
| `fill-publish` | 填写图文表单（分步发布） |
| `click-publish` | 点击发布按钮 |

---


## 输入判断

按优先级判断：

1. 用户要求"竞品分析 / 分析竞品 / 对比笔记"：执行竞品分析流程。
2. 用户要求"热点追踪 / 热门话题 / 趋势分析"：执行热点追踪流程。
3. 用户要求"创作发布 / 研究话题后发布 / 一键创作"：执行内容创作流程。
4. 用户要求"互动管理 / 批量互动 / 评论策略"：执行互动管理流程。

## 必做约束

- **逐关键词浏览（强制）**：多关键词任务必须逐个关键词执行「搜索 → 浏览结果 → 进入若干笔记看详情」的完整循环，看完当前关键词的 2~3 篇再换下一个。**严禁**先把所有关键词都搜索完、再拿着 ID 清单逐个进入笔记。
- 复合流程中每一步都应向用户报告进度。
- 发布类操作必须经过用户确认（参考 xhs-publish 约束）。
- 评论类操作必须经过用户确认（参考 xhs-interact 约束）。
- **控制整体频率**：即使使用真实账号和浏览器，频繁的自动化操作仍可能触发风控，建议分批、间隔执行，不要一次性处理大量任务。
- 所有数据分析结果使用 markdown 表格结构化呈现。

## 工作流程

### 竞品分析

目标：搜索竞品笔记 → 获取详情 → 整理分析报告。

**步骤：**

1. 确认分析目标（关键词、竞品账号）。
2. 搜索相关笔记：
```bash
python scripts/cli.py search-feeds \
  --keyword "目标关键词" --sort-by 最多点赞
```
3. 紧跟本次搜索，从结果中选取 3-5 篇高互动笔记**立即逐篇**获取详情（`--keyword` 与搜索一致，模拟点击进入）：
```bash
python scripts/cli.py get-feed-detail \
  --feed-id FEED_ID --xsec-token XSEC_TOKEN --keyword "目标关键词"
```
每 3 篇插入 10~20 秒等待。不要等所有搜索完成后统一获取详情。
4. 整理分析报告，包含：
   - 标题风格分析
   - 封面图特点
   - 正文结构（开头/中间/结尾）
   - 话题标签使用
   - 互动数据对比（点赞/评论/收藏）

**输出格式：**

使用 markdown 表格对比各笔记的关键指标，并总结共性特征和差异化策略。

### 热点追踪

目标：逐关键词「搜索 → 浏览 → 看帖」→ 分析趋势 → 提供选题建议。

**步骤：**

1. 确认追踪领域或关键词列表。
2. **逐关键词执行完整循环**（严禁先把所有关键词搜完再统一看帖）：

   对列表中的每个关键词依次执行：

   ```bash
   # ① 搜索当前关键词（按最新排序，观察近期热度）
   python scripts/cli.py search-feeds \
     --keyword "关键词" --sort-by 最新 --publish-time 一周内

   # 按最多点赞排序，找爆款（可选，与上面二选一或都做）
   python scripts/cli.py search-feeds \
     --keyword "关键词" --sort-by 最多点赞

   # ② 浏览结果，选取 2~3 篇高互动笔记立即进入查看
   #    --keyword 必须与刚才的搜索一致（模拟点击进入，复用搜索页上下文）
   python scripts/cli.py get-feed-detail \
     --feed-id FEED_ID --xsec-token XSEC_TOKEN --keyword "关键词"
   ```

   看完当前关键词的 2~3 篇后，等待 10~20 秒，再切换到下一个关键词重复 ①②。
3. 全部关键词处理完毕后，汇总输出趋势报告：
   - 各关键词热度排名
   - 爆款内容特征
   - 选题建议

### 内容创作

目标：研究话题 → 辅助生成草稿 → 用户确认 → 发布。

**步骤：**

1. 确认创作主题。
2. 搜索相关笔记，获取灵感：
```bash
python scripts/cli.py search-feeds \
  --keyword "主题关键词" --sort-by 最多点赞
```
3. 选取 2-3 篇参考笔记，**紧跟搜索立即**获取详情分析内容结构（`--keyword` 与搜索一致）：
```bash
python scripts/cli.py get-feed-detail \
  --feed-id FEED_ID --xsec-token XSEC_TOKEN --keyword "主题关键词"
```
4. 基于分析结果，辅助用户生成草稿：
   - 标题（符合小红书风格，UTF-16 长度 ≤ 20）
   - 正文（段落清晰，口语化）
   - 话题标签
5. 通过 `AskUserQuestion` 让用户确认最终内容。
6. 执行发布（参考 xhs-publish 流程）：
```bash
python scripts/cli.py publish \
  --title-file /tmp/xhs_title.txt \
  --content-file /tmp/xhs_content.txt \
  --images "/abs/path/pic1.jpg" "/abs/path/pic2.jpg" \
  --tags "标签1" "标签2"
```

### 互动管理

目标：浏览目标笔记 → 有策略地评论/点赞/收藏。

**步骤：**

1. 确认互动目标（关键词、话题领域）。
2. 搜索目标笔记：
```bash
python scripts/cli.py search-feeds \
  --keyword "目标关键词" --sort-by 最新
```
3. 筛选适合互动的笔记（中等互动量、与自身领域相关）。
4. 逐篇处理（看完一篇互动一篇，不要先看完所有详情再统一互动）——获取详情了解笔记内容：
```bash
python scripts/cli.py get-feed-detail \
  --feed-id FEED_ID --xsec-token XSEC_TOKEN --keyword "目标关键词"
```
5. 针对笔记内容生成有价值的评论建议。
6. 用户确认评论内容后发送（`--keyword` 与搜索一致，模拟点击进入）：
```bash
python scripts/cli.py post-comment \
  --feed-id FEED_ID \
  --xsec-token XSEC_TOKEN \
  --content "评论内容" \
  --keyword "目标关键词"
```
7. 可选：点赞或收藏：
```bash
python scripts/cli.py like-feed \
  --feed-id FEED_ID --xsec-token XSEC_TOKEN --keyword "目标关键词"

python scripts/cli.py favorite-feed \
  --feed-id FEED_ID --xsec-token XSEC_TOKEN --keyword "目标关键词"
```
8. 每次互动之间保持 30-60 秒间隔。

## 运营建议

- **竞品分析频率**：每周 1-2 次，跟踪竞品动态。
- **热点追踪频率**：每天 1 次，抓住时效性内容。
- **互动频率**：每天不超过 20 条评论，避免被限流。
- **发布时间**：工作日 12:00-13:00、18:00-21:00 为高峰时段。

## 失败处理

- **搜索无结果**：扩大关键词范围或调整筛选条件。
- **详情获取失败**：笔记可能已删除或设为私密。
- **发布失败**：参考 xhs-publish 的失败处理。
- **评论失败**：参考 xhs-interact 的失败处理。
- **频率限制**：增大操作间隔，降低频率。
