# Dashboard 站点壳

这个分支只包含看板的前端代码：`index.html`、`app.css`、`js/`、`build-info.json`。

- **这里没有任何职位数据**，也没有任何个人信息。数据留在私有仓 `job_pipeline` 的
  `dashboard-data` 分支，需要一把只读 fine-grained PAT 才能通过页面读取。
- 代码由私有仓 `job_pipeline` 的 `dashboard/` 目录生成并推送（`.github/scripts/publish_dashboard.sh`），
  请勿在此直接修改，下一次发布会覆盖。
- 零第三方脚本、零 CDN、零外部字体；内容安全策略是 `script-src 'self'`。
- 打开方式与令牌权限说明见看板页面的「数据与隐私」页签。
