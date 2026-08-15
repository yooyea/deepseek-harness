# DeepHarness 租户控制平面

[English](README.md) | 中文

租户控制平面创建可随时替换且受资源限制的 Harness 容器。PostgreSQL 是租户、凭据、插件、健康状态和操作记录的权威数据源；私有阿里云 OSS 保存不可变插件版本和数据库逻辑备份。

## 功能

- 通过 HTTP Basic Auth 保护的管理看板
- PostgreSQL 租户与插件期望状态
- 私有、加密且开启版本控制的 OSS 插件产物
- 租户创建、启动、停止、重启、重建、安全恢复和移除
- 只展示一次并加密保存以支持重建的租户密码
- 主机与容器资源监控和容量准入
- 插件期望版本、实际版本和最后健康版本
- 租户级运行令牌和短期对象下载地址
- 每日压缩数据库逻辑备份到 OSS

租户容器的 `/data` 使用内存文件系统，容器内没有阿里云凭据。Harness 启动前，镜像通过控制平面恢复期望插件，校验每个 SHA-256，禁用包生命周期脚本完成安装；Harness HTTP 进程就绪后才会上报实际状态。

`重建` 会根据 PostgreSQL 和 OSS 删除并重新创建容器。`安全恢复` 执行相同替换，但设置 `DSH_PLUGIN_SAFE_MODE=1`，只启动基础镜像而不加载租户插件。

## 使用 Docker Compose 运行

把 `.env.example` 复制为 `.env`，替换全部占位值，然后运行：

```bash
docker compose up -d
```

Compose 会启动 PostgreSQL、原始 Harness 实例、租户控制平面和备份进程。PostgreSQL 只在 Compose 内部网络开放，并使用 `deepharness-postgres-data` 数据卷；新建租户容器没有持久化 Docker 数据卷。

默认地址：

- Harness：`http://SERVER:8080`
- 租户控制平面：`http://SERVER:8090`
- 新建租户：`http://SERVER:8100` 到 `http://SERVER:8199`

未配置 `OSS_BUCKET` 时，GitHub Actions 会创建私有 Bucket，开启版本控制、默认 AES-256 加密、未完成上传清理和非当前版本 90 天过期，并把最终 OSS 配置写入服务器部署。

`OSS_ENDPOINT` 必须使用阿里云 S3 兼容格式，例如 `https://s3.oss-cn-shanghai.aliyuncs.com`。boto3 客户端使用 OSS 兼容的 V2 签名模式。

## 插件产物协议

租户运行时先申请上传地址，上传一个 npm 包 tarball，再提交元数据。只有对象路径属于当前租户且下载后的产物符合声明的 SHA-256，控制平面才会提交记录，并在 PostgreSQL 中把该版本标记为期望版本。

容器替换时，镜像使用租户 Bearer Token 查询期望版本，通过短期 URL 下载产物，再次校验摘要，并以 `--ignore-scripts` 和精确文件引用运行 profile 插件安装器。单个插件失败会被上报并跳过，不会阻止基础 Harness 进程启动。

受管租户还提供 `deepharness-plugin-publish`。模型或开发者可把生成的代码整理成可安装 DSH bundle、设置新的包版本，然后运行 `deepharness-plugin-publish /path/to/plugin --rebuild`。命令会先打包并上传，在不暴露云凭据的情况下提交期望状态，持久化成功后才调度容器替换。注入工作区的 `AGENTS.md` 会说明这套流程，并警告不要直接重启一次性容器。

上游 `cordis_define` 创建的进程内临时 Package 仍然是临时状态。若需在替换后保留并进入控制面插件清单，应将其整理为预构建、可安装的 bundle，再用上述命令发布。

## 安全

Docker Socket 赋予控制平面主机级容器权限，因此该服务必须作为受认证保护的管理组件。Docker 操作只接受配置的镜像、端口范围、生成名称和带管理标签的容器。

阿里云 AccessKey 只进入控制平面和备份容器。生产环境应使用权限限定在单个 OSS Bucket 的专用 RAM 身份。租户密码和运行令牌使用 `CONTROL_PLANE_SECRET_KEY` 加密；鉴权查询只使用运行令牌哈希。

PostgreSQL 数据卷保护数据库重启，OSS 备份用于 Docker 主机丢失后的恢复。恢复自动化与日常部署分离，避免损坏或不完整备份覆盖存活数据库。

## 验证

```bash
cd tenant-control-plane
python -m pip install -r requirements.txt
PYTHONPATH=. python -m unittest discover -s tests -v
python -m compileall -q app tests scripts
node --check ../docker/plugin-bootstrap.mjs
node --check ../docker/plugin-report.mjs
```
