# 管理员登录

`seekitx-term-admin` GitHub App 只安装到 `seekitx/new-term-radar-free-data`，配置为读写 `free-config.json` 并只读仓库元数据。用户通过 GitHub 的设备验证码登录，页面核对 GitHub 账号身份后才能管理名单；令牌只保存在当前页面内存，刷新或关闭后清除。

`device-login-worker.js` 是运行在 Cloudflare `term-admin-login` 的登录中转，只允许 `https://terms.aifluxor.com` 通过浏览器调用，转发到 GitHub 的两个设备登录接口，不记录或保存 GitHub 令牌。Client ID 是公开的应用标识，不是密钥。程序不需要 GitHub App 私钥、客户端密钥或长期刷新令牌。

首次安装和首次登录需要用户在 GitHub 确认授权。此 App 的单文件权限是否足以使用 GitHub 文件更新接口，需要管理员真实登录并验证；不得在未确认时把单文件权限悄悄扩大为整个仓库内容写入权限。页面也保留 GitHub 直接编辑配置的入口。

Cloudflare 临时部署授权在部署后通过 Wrangler logout 退出。Worker 使用 `--no-bundle` 直接上传，不执行构建。
