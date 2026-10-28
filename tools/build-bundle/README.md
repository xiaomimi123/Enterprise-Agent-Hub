# 底座包构建（tools/build-bundle）

底座包 = 固定版本的 **Node.js 22 LTS + uv + Python 3.12 + 接入器依赖的 wheel**（Windows x64），由中枢托管，员工装机时优先从中枢下载并校验 SHA-256，不再依赖员工电脑访问 nodejs.org / GitHub / PyPI 的 Python 下载。**不含** 工作台、接入器（它们继续「打开即最新」）、WorkBuddy、Edge 扩展、Playwright、CodeBuddy CLI。

## 构建（在有外网的 Windows 机器上，一般就是部署机）

```bash
node tools/build-bundle/build.mjs                # 底座版本默认 1.0.1
node tools/build-bundle/build.mjs --base 1.0.2   # 升级底座：改了任何组件或接入器依赖就要升底座版本号（构建机需要 python + pip）
```

产物在 `bundle/`（`.gitignore` 里，不进 git）：`manifest.json` + 三个 zip。`hub/docker-compose.yml` 已把它挂载成 `/data/bundle`，**构建完不用重启中枢**。

## 员工端怎么用

`install.ps1` 第 0 步（自检）之后读 `/api/agent/bundle/manifest.json`：
- 本机 `runtime/BASE_VERSION` 等于清单的 `base` → 跳过；不同 → 逐个下载、校验、装进 `runtime/node|uv|python`，旧的留为 `<目录>.prev`；全部成功才写 `BASE_VERSION`。
- 校验失败 / 下载失败 → 记 `BUNDLE_FAILED`，退回原来的联网安装；中枢没有底座包（404）→ 直接联网安装。
- 装了 Python 后设置用户环境变量 `UV_PYTHON_INSTALL_DIR` 指向 `runtime/python`，uv 不再联网取 Python。
- 开关：`HUB_BUNDLE=off` 不用底座包；`HUB_INSTALL_BASE_ONLY=1` 装完底座就停（测试用）。

## 应用要求最低底座版本

`app.json` 的 `requires.base_min`（如 `"1.0.0"`）。员工机底座低于它，打开应用时接入器提示「底座运行环境」过旧、让重新运行安装命令；**不拦打开**。没有 `BASE_VERSION` 文件（早期安装）按最老版本算。不写 `base_min` 就不检查。目前**还没有任何应用声明它**，等有应用真的依赖新运行时再加。

## 测试

`node agent/tests/bundle-install.mjs`（Windows，本机假中枢：校验和对 / 错 / 中枢没有底座包）。
