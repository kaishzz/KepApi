# KepApi

KepApi 是 KepCs 的数据源服务，基于 FastAPI 提供服务器列表、白名单和后台服务器目录管理接口。

## 当前功能

- 提供开水服服务器列表缓存接口
- 提供社区服服务器列表缓存接口
- 提供白名单缓存接口
- 通过 A2S 探测补充服务器在线状态、地图和人数信息
- 提供后台管理接口，直接维护开水服与社区服目录
- 启动时自动建表、预热缓存，并在后台按固定间隔刷新
- 提供 API Key 鉴权、限流、可信代理校验和基础安全响应头

## 接口概览

### 公开接口

- `GET /health`
- `GET /api/kepcs/serverlist`
- `GET /api/kepcs/whitelist`
- `GET /api/community/serverlist`

### 后台管理接口

开水服目录：

- `GET /api/admin/kepcs/servers`
- `POST /api/admin/kepcs/servers`
- `PATCH /api/admin/kepcs/servers/{server_id}`
- `DELETE /api/admin/kepcs/servers/{server_id}`

社区服目录：

- `GET /api/admin/community/servers`
- `POST /api/admin/community/servers`
- `PATCH /api/admin/community/servers/{server_id}`
- `DELETE /api/admin/community/servers/{server_id}`

## 鉴权

受保护接口支持以下请求头：

- `X-API-Key: <api_key>`
- `Authorization: Bearer <api_key>`

建议将公开读取 key 和后台管理 key 分开配置：

- `KEPAPI_API_KEY` 用于公开读取接口
- `KEPAPI_ADMIN_API_KEY` 用于后台管理接口

如果未单独设置 `KEPAPI_ADMIN_API_KEY`，运行时会回退到 `KEPAPI_API_KEY`。

## 配置方式

项目把配置拆成两部分：

- 敏感信息放在 `.env`
- 非敏感运行参数放在 `app_config.json`

### `.env`

`.env` 里的值不会进入 Git。请先复制 `.env.example` 为 `.env`，再填写真实值。

必填项：

- `KEPAPI_API_KEY`
- `KEPAPI_ADMIN_API_KEY`
- `KEPAPI_DB_HOST`
- `KEPAPI_DB_PORT`
- `KEPAPI_DB_USER`
- `KEPAPI_DB_PASS`
- `KEPAPI_DB_CHARSET`

### `app_config.json`

`app_config.json` 同样不会进入 Git。请先复制 `app_config.example.json` 为 `app_config.json`，再按需调整。

常用配置项：

- `api_key_header_names`
- `enable_docs`
- `trust_proxy_headers`
- `trusted_proxy_cidrs`
- `a2s_timeout`
- `serverlist_a2s_total_timeout`
- `serverlist_refresh_interval`
- `community_serverlist_refresh_interval`
- `whitelist_refresh_interval`
- `serverlist_limit_per_minute`
- `serverlist_burst_limit`
- `whitelist_limit_per_minute`
- `whitelist_burst_limit`
- `auth_fail_limit_per_minute`
- `auth_ban_seconds`

说明：

- 代码会先读取环境变量，再回退到 `app_config.json`
- 如果你更习惯全放环境变量，也可以直接通过 `KEPAPI_*` 覆盖同名配置

## 安装与启动

安装依赖：

```powershell
python -m pip install -r requirements.txt
```

准备配置：

```powershell
Copy-Item .env.example .env
Copy-Item app_config.example.json app_config.json
```

启动服务：

```powershell
python main.py
```

默认监听地址：

- `http://127.0.0.1:8001`

## 运行行为

- 启动时会先检查后台目录表是否存在
- 启动后会立即预热开水服、社区服和白名单缓存
- 服务运行期间会按配置间隔持续刷新缓存
- 默认关闭 `/docs`、`/redoc` 和 `/openapi.json`，只有启用 `enable_docs` 后才会开放

## 安全说明

- `.env` 已在 `.gitignore` 中忽略，不会默认上传
- `app_config.json` 已在 `.gitignore` 中忽略，只保留 `app_config.example.json`
- 所有 `/api/*` 响应默认返回 `Cache-Control: no-store`
- API Key 使用常量时间比较
- 启用代理头信任时，必须同时配置可信代理网段
