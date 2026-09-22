# 石家庄博物馆 · 公告实时看（PWA + 实时后端）

实时汇聚石家庄各大博物馆最新公告 + 人社局/考试招聘公告。

## 文件
- `server.py` —— 自动实时后端（每30分钟抓取河北博物院官网 + 实时搜索石家庄人社局等招聘公告），提供 `/api/news` JSON 接口
- `index.html` —— PWA 前端（移动端适配、分类清晰、招聘高亮），后端在线自动实时拉取，离线用内置快照
- `manifest.json` / `sw.js` / `icon.svg` —— PWA 安装能力（可"添加到主屏幕"变成 App）

## 本地/服务器运行
```
pip install requests beautifulsoup4
python3 server.py --port 8000
```
浏览器打开 `http://服务器IP:8000` 即可，手机可"添加到主屏幕"当 App 使用。
可用 systemd 或 Docker 保持常驻（见下）。

## Docker
```dockerfile
FROM python:3.11-slim
RUN pip install requests beautifulsoup4
WORKDIR /app
COPY . .
EXPOSE 8000
CMD ["python3","server.py","--port","8000"]
```

## systemd 常驻示例
```ini
[Unit]
Description=Museum News
After=network.target
[Service]
WorkingDirectory=/opt/museums_app
ExecStart=/usr/bin/python3 server.py --port 8000
Restart=always
[Install]
WantedBy=multi-user.target
```

## 说明
- 实时数据通道：河北博物院官网直抓 + 人社系统实时检索（石家庄人社局等官方原文）。
- 生产部署建议配合 Nginx + HTTPS + 域名，让手机"添加到主屏幕"体验最佳。

## 方案B：免费长期部署（GitHub Pages + Actions 定时刷新）
1. 注册 GitHub 账号（github.com），点击 New repository 新建一个公开仓库。
2. 把本项目所有文件上传到该仓库根目录（.github 文件夹也要）。
3. 仓库 Settings → Pages → Source 选 "GitHub Actions"。
4. Actions 标签页可看到刷新任务自动运行（每6小时抓取一次并部署 www 页面）。
5. 部署完成后拿到形如 `https://用户名.github.io/仓库名/` 的网址，手机浏览器打开。
6. 点「添加到主屏幕」→ 像 App 一样使用，长期免费用。

> 说明：GitHub 云端环境不含小艺检索密钥，实时数据以「河北博物院官网直抓」为主；
> 若需全馆实时检索，推荐使用云服务器跑 `server.py`（方案A），或在该仓库设置 Secrets 配置检索密钥。
