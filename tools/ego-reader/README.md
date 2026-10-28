# ego-reader（原型）

把 [ego lite](https://github.com/citrolabs/ego-lite) 浏览器包成一个**只读**的 MCP 小服务（stdio，零依赖），给 CodeBuddy 等 agent 读小红书。**原型：还没接入工作台，也没接到 CodeBuddy。**

## 为什么要封装

`ego-browser nodejs` 执行的是任意 JavaScript，能访问本机文件系统。所以不能把 agent 写的脚本直接交给它。这里脚本是固定模板，agent 只能传校验过的参数：

| 工具 | 参数 | 做什么 |
|---|---|---|
| `xhs_check_login` | 无 | 检查是否**真的登录**（页面状态 `loggedIn` / `guest`），不读内容 |
| `xhs_read_feed` | `scrolls`（0-3，默认 0） | 读首页信息流当前整张可见的卡片（id、标题、作者、点赞）；可先用鼠标滚轮向下滚动（每次 700 像素、间隔 3 秒，固定值） |
| `xhs_read_note` | `id`（24 位小写十六进制，必须来自刚读的信息流）、`scroll_note`（0-3） | 点开那张卡片，读标题、正文、话题、作者、日期、图片数、是否视频、点赞 / 收藏 / 评论数，按 Esc 关闭 |

没有点赞、收藏、关注、评论、分享、发布、输入文字、打开任意网址的能力。

## 保护（纵深防御）

真正的节奏、额度、总开关仍由工作台服务端（`pace.mjs`）管；封装自己再加一层：

- 两次读笔记至少间隔 `EGO_READER_MIN_GAP_MS`（默认 20000）；失败的尝试也计一次
- 每小时最多 `EGO_READER_MAX_PER_HOUR`（默认 12）篇
- 存在文件 `EGO_READER_STOP_FILE`（默认 `%TEMP%\hub-ego-reader.STOP`）时全部拒绝

**不做**随机停顿、鼠标轨迹抖动等伪装成真人的处理（项目规则见根目录 CLAUDE.md）。

## 登录状态怎么判断

只认页面自己的状态：`window.__INITIAL_STATE__.user.loggedIn` 与 `userInfo.guest`。**不能**用「找不到登录按钮」判断：小红书游客也能看信息流和笔记（2026-10-28 我就因此把游客误判成已登录）。`xhs_read_feed`、`xhs_read_note` 的结果都带 `loggedIn`；`loggedIn` 为 false 时，读到的是公开内容。

## 任务空间：只用一个

固定使用专用空间 `hub-xhs-reader`（用户规定：一个任务空间完成所有读取，不为恢复或并行多开）。每次调用都 `taskSpace(名字)` 恢复同一个，不新建。

## 前提

员工在 **ego lite 里自己登录小红书**（扫码、验证码由本人操作）。专用任务空间 `hub-xhs-reader`（`EGO_READER_SPACE` 可改）是否沿用登录态**没有验证过**：2026-10-28 发现之前的「已登录」判断是错的（见下面「登录状态怎么判断」）。用户在浏览器里接管该空间时，工具返回 `user_has_control`，不会强行夺回。

## 测试

```bash
node tools/ego-reader/test.mjs          # 参数校验、注入、间隔 / 每小时 / 停止文件保护（不需要浏览器）
node tools/ego-reader/test.mjs --live   # 用真实 ego lite 读信息流和 2 篇笔记（需已登录；约 1 分钟）
```

## 踩过的坑（都已处理）

- 笔记链接直接打开（`goto`）会被拦（「你访问的页面不见了」）：必须像读者一样点开卡片
- 信息流每次回到首页都会刷新、是虚拟列表（滚出视口的卡片被回收）：读「当前可见」，不要累计，也不要保存旧链接
- 卡片链接有时带 `?xsec_token=…`：用「以 id 开头」匹配，不要完全相等
- 固定导航栏会盖住上方的卡片（点击被拦）：只认整张都在导航栏下方、视口内的卡片
- 同一链接有一个不可见的零尺寸元素：点封面 `a.cover`
- 笔记弹窗里真正滚动的是 `#noteContainer`，鼠标要先移到弹窗上再滚
- `ego-browser` 把 `console.log` 写到 **stderr**；`spawn` 时必须不给标准输入（`stdio: ignore`），否则它一直等输入
- 页面选择器（`#detail-desc`、`a.cover` 等）是小红书前端的内部命名，改版会失效，需要维护
