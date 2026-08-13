# DeepHarness 租户控制平面

[English](README.md) | 中文

租户控制平面为每个租户创建一个受资源限制的 Harness 容器和一个持久化 Docker 数据卷。它独立于 Harness 包图，只通过已发布镜像和环境变量与 Harness 通信。

## 功能

- 通过 HTTP Basic Auth 保护的管理看板
- 使用 WAL 模式的 SQLite 持久化
- 租户创建、启动、停止、重启和移除
- 只展示一次的自动生成租户密码
- 每个租户独立的数据卷和主机端口
- 主机 CPU、负载、内存和磁盘看板
- 各容器 CPU 和内存用量
- 根据实时压力和资源配额执行容量准入
- 不可变的生命周期操作日志

移除租户时默认保留其数据卷。API 支持明确清理数据卷，但管理看板不会提供这一破坏性选项。

## 使用 Docker Compose 运行

仓库根目录的 `docker-compose.yml` 会同时启动原始 Harness 实例和控制平面。把 `.env.example` 复制为 `.env`，替换两套管理员密码，然后运行：

```bash
docker compose up -d
```

默认地址：

- Harness：`http://SERVER:8080`
- 租户控制平面：`http://SERVER:8090`
- 新建租户：`http://SERVER:8100` 到 `http://SERVER:8199`

生产环境防火墙必须只开放实际需要的端口。把控制平面交给更多管理员之前，应将它放在私有网络或 TLS 反向代理之后。

自动化首次部署会让控制平面复用现有 Harness 管理员密码，管理员可以直接登录。后续可在服务器 `.env` 中将两个密码分开。

## 安全模型

挂载 `/var/run/docker.sock` 会给控制平面进程主机级容器管理权限。因此服务只允许使用固定 Harness 镜像，从配置的端口范围分配端口，根据已校验 slug 生成容器和数据卷名称，并拒绝操作没有控制平面管理标签的容器。

控制平面不会持久化租户明文密码。成功创建实例后只返回一次生成的密码；Docker 会在托管容器配置中保留该值，供 Harness 入口执行 Basic Auth。

## 验证

领域逻辑和 SQLite 测试只使用 Python 标准库：

```bash
cd tenant-control-plane
PYTHONPATH=. python -m unittest discover -s tests -v
python -m compileall -q app tests
```
