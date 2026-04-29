# KepApi

KepApi 是 KepCs 体系里的数据源服务，基于 FastAPI 提供服务器列表、白名单和后台服务器目录管理接口。

当前正式使用的开水服 `mode` 标识为：

- `ze_xl`：训练服
- `ze_pt`：跑图服

## 当前职责

- 对外提供开水服服务器列表接口
- 对外提供白名单缓存接口
- 使用 A2S 补充地图、人数、在线状态等实时信息
- 提供后台开水服目录的增删改查接口
- 启动时自动预热缓存并按固定间隔后台刷新
- 提供 API Key 鉴权、限流、可信代理校验和基础安全响应头

## 接口

公开接口：

- `GET /health`
- `GET /api/kepcs/serverlist`
- `GET /api/kepcs/whitelist`

后台目录接口：

- `GET /api/admin/kepcs/servers`
- `POST /api/admin/kepcs/servers`
- `PATCH /api/admin/kepcs/servers/{server_id}`
- `DELETE /api/admin/kepcs/servers/{server_id}`

## 鉴权

受保护接口支持以下请求头：

- `X-API-Key: <api_key>`
- `Authorization: Bearer <api_key>`

建议分开配置：

- `KEPAPI_API_KEY`：公开读取接口
- `KEPAPI_ADMIN_API_KEY`：后台管理接口

## 配置

项目配置分成两部分：

- `.env`：敏感信息
- `app_config.json`：运行参数

准备方式：

```powershell
Copy-Item .env.example .env
Copy-Item app_config.example.json app_config.json
```

常用环境变量：

- `KEPAPI_API_KEY`
- `KEPAPI_ADMIN_API_KEY`
- `KEPAPI_DB_HOST`
- `KEPAPI_DB_PORT`
- `KEPAPI_DB_USER`
- `KEPAPI_DB_PASS`
- `KEPAPI_DB_CHARSET`

## 启动

安装依赖：

```powershell
python -m pip install -r requirements.txt
```

启动服务：

```powershell
python main.py
```

默认监听：

- `http://127.0.0.1:8001`

## 测试

```powershell
py -3 -m unittest discover -s tests
```

## 运行说明

- 开水服目录直接使用当前 `mode` 值 `ze_xl` / `ze_pt`
- 缓存启动时会立即预热，随后按配置定时刷新
- `/api/*` 默认返回 `Cache-Control: no-store`
- 文档接口默认关闭，只有启用 `enable_docs` 后才开放
