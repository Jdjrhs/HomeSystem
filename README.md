# HomeSystem

基于 Docker 的模块化智能家庭自动化系统，集成本地和云端大模型，提供文档管理、论文收集和工作流自动化功能。

## ✨ 核心功能

- 🐳 **模块化部署**: 三大独立模块，支持分布式跨机器部署
- 📚 **智能论文分析**: 基于ArXiv的自动论文收集、分析和管理
- 🔍 **高级OCR处理**: 远程GPU加速的PaddleOCR文档识别服务
- 🗄️ **企业级数据库**: PostgreSQL + Redis 双数据库架构
- 🌐 **多LLM支持**: DeepSeek V3、Qwen、Doubao等多种大模型
- 📊 **可视化分析**: 论文数据的智能统计和趋势分析
- 🔄 **工作流自动化**: 定时任务调度和批处理功能

## 🏗️ 系统架构

HomeSystem 采用模块化设计，由三个独立的 Docker 服务组成，可在不同机器上部署：

```
┌─────────────────────┐    ┌─────────────────────┐    ┌─────────────────────┐
│     数据库服务        │    │    远程OCR服务       │    │   PaperAnalysis    │
│  (Database Module)  │    │ (Remote OCR Module) │    │   (Web Module)     │
├─────────────────────┤    ├─────────────────────┤    ├─────────────────────┤
│ • PostgreSQL:15432  │    │ • OCR Service:5001  │    │ • Web App:5002     │
│ • Redis:16379       │◄───┼─• GPU加速处理        │◄───┼─• 论文管理界面      │
│ • pgAdmin:8080      │    │ • PaddleOCR引擎     │    │ • API接口          │
│ • Redis Web:8081    │    │ • 批量文档处理       │    │ • 任务调度          │
└─────────────────────┘    └─────────────────────┘    └─────────────────────┘
        │                           │                           │
        └───────────────────────────┼───────────────────────────┘
                                   │
                            网络连接支持
                          跨主机LAN部署
```

## 🔌 端口配置指南

### 默认端口映射表

| 服务 | 容器端口 | 主机端口 | 环境变量 | 描述 |
|------|---------|---------|----------|------|
| **数据库模块** |
| PostgreSQL | 5432 | 15432 | `DB_PORT` | 主数据库 |
| Redis | 6379 | 16379 | `REDIS_PORT` | 缓存数据库 |
| pgAdmin | 80 | 8080 | - | 数据库管理界面 (可选) |
| Redis Commander | 8081 | 8081 | - | Redis管理界面 (可选) |
| **OCR模块** |
| OCR Service | 5001 | 5001 | `OCR_SERVICE_PORT` | OCR处理API |
| Nginx Proxy | 80 | 80 | `NGINX_PORT` | 负载均衡器 (可选) |
| Prometheus | 9090 | 9090 | `PROMETHEUS_PORT` | 监控服务 (可选) |
| Grafana | 3000 | 3000 | `GRAFANA_PORT` | 指标仪表板 (可选) |
| **Web模块** |
| PaperAnalysis | 5002 | 5002 | `FLASK_PORT` | Web应用程序 |

### 自定义端口配置

**所有端口都可通过环境变量配置**。在各模块目录创建 `.env` 文件：

```bash
# 示例：修改OCR服务端口为8080
OCR_SERVICE_PORT=8080

# 示例：修改数据库端口
DB_PORT=25432
REDIS_PORT=26379

# 示例：修改Web应用端口
FLASK_PORT=8002
```

### 端口优先级 (以OCR服务为例)

端口选择优先级：`OCR_SERVICE_PORT` > `PORT` > `5001` (默认)

### 检查端口可用性

部署前，建议检查端口是否被占用：

```bash
# 检查特定端口
netstat -tulpn | grep :15432
lsof -i :15432
ss -tulpn | grep :15432

# 批量检查所有默认端口
for port in 15432 16379 8080 8081 5001 5002; do
  echo "检查端口 $port..."
  if lsof -i :$port > /dev/null 2>&1; then
    echo "⚠️  端口 $port 已被占用"
    lsof -i :$port
  else
    echo "✅ 端口 $port 可用"
  fi
done
```

### 端口冲突解决方案

如遇端口冲突，有三种解决方式：

1. **修改环境变量** (推荐)
   ```bash
   echo "DB_PORT=25432" >> database/.env
   echo "OCR_SERVICE_PORT=8080" >> remote_app/.env
   ```

2. **修改docker-compose.yml端口映射**
   ```yaml
   ports:
     - "25432:5432"  # 修改主机端口
   ```

3. **停止占用端口的服务** (谨慎使用)
   ```bash
   # 查找占用进程
   lsof -i :15432
   # 终止进程
   sudo kill -9 <PID>
   ```

## 🌐 网络拓扑与通信

### 服务间通信方式

1. **容器内部通信**: 使用容器名和内部端口
   - 例: `postgres:5432` (Docker网络内)
   - 例: `redis:6379` (Docker网络内)

2. **跨主机通信**: 使用IP和映射端口
   - 例: `192.168.1.100:15432` (跨主机访问数据库)
   - 例: `192.168.1.101:5001` (跨主机访问OCR服务)

3. **本地开发**: 使用localhost和映射端口
   - 例: `localhost:15432` (本机访问数据库)
   - 例: `localhost:5002` (本机访问Web界面)

### 网络架构说明

```
主机A (数据库)          主机B (OCR)           主机C (Web)
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│ PostgreSQL:15432│◄───┼─OCR Service:5001│◄───┼─PaperAnalysis   │
│ Redis:16379     │    │                 │    │ :5002           │
│ pgAdmin:8080    │    │ Nginx:80        │    │                 │
│ Redis-UI:8081   │    │ Grafana:3000    │    │ 配置远程服务地址  │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

## 🚀 快速开始

### 前置要求

- Docker 20.10+
- Docker Compose 2.0+
- 各模块可部署在不同主机上（支持LAN网络连接）
- 确保以下默认端口未被占用：15432, 16379, 5001, 5002
  ```bash
  # 快速检查所有必需端口
  ./check-ports.sh
  
  # 检查所有端口（包括可选服务）
  ./check-ports.sh -a
  
  # 查看端口解决建议
  ./check-ports.sh -f
  
  # 或手动检查核心端口
  for port in 15432 16379 5001 5002; do lsof -i :$port && echo "端口 $port 被占用"; done
  ```

### 1. 数据库服务部署

**在数据库主机上：**

```bash
cd /path/to/homesystem/database

# 启动数据库服务
./start.sh

# 检查服务状态
docker compose ps
./check-tables.sh
```

**默认端口配置：**
- PostgreSQL: 15432 (可通过 `DB_PORT` 修改)
- Redis: 16379 (可通过 `REDIS_PORT` 修改)
- pgAdmin: 8080 (可选管理界面)
- Redis Commander: 8081 (可选管理界面)

**自定义端口示例：**
```bash
# 创建环境变量文件
cd database
cat > .env << EOF
DB_PASSWORD=your_secure_password_here
DB_PORT=25432
REDIS_PORT=26379
PGADMIN_PASSWORD=your_secure_pgadmin_password
EOF

# 启动服务
./start.sh
```

**服务端点：**
- PostgreSQL: `localhost:15432` (或自定义端口)
- Redis: `localhost:16379` (或自定义端口)
- pgAdmin: `http://localhost:8080` (admin@homesystem.local / admin123)
- Redis Commander: `http://localhost:8081`

### 2. 远程OCR服务部署

**在GPU主机上：**

```bash
cd /path/to/homesystem/remote_app

# 构建并启动OCR服务
./deploy.sh 

# 检查GPU支持
docker compose logs ocr-service
```

**默认端口配置：**
- OCR Service: 5001 (可通过 `OCR_SERVICE_PORT` 修改)
- Nginx Proxy: 80 (可选，通过 `NGINX_PORT` 修改)
- Prometheus: 9090 (可选监控，通过 `PROMETHEUS_PORT` 修改)
- Grafana: 3000 (可选仪表板，通过 `GRAFANA_PORT` 修改)

**自定义端口示例：**
```bash
# 创建环境变量文件
cd remote_app
cat > .env << EOF
OCR_SERVICE_PORT=8080
NGINX_PORT=8000
PROMETHEUS_PORT=9091
GRAFANA_PORT=3001
PADDLEOCR_USE_GPU=true
EOF

# 启动服务
./deploy.sh --build
```

**端口优先级：** `OCR_SERVICE_PORT` > `PORT` > `5001` (默认)

**服务端点：**
- OCR API: `http://gpu-host:5001` (或自定义端口)
- 健康检查: `http://gpu-host:5001/api/health`
- Nginx代理: `http://gpu-host:80` (如果启用)
- Grafana监控: `http://gpu-host:3000` (如果启用)

### 3. PaperAnalysis Web服务部署

**在Web主机上：**

```bash
cd /path/to/homesystem/Web/PaperAnalysis

# 第一步：配置环境变量（必需！）
cp .env.example .env
vim .env  # 配置数据库和OCR服务地址

# 注意：deploy.sh 会自动验证 .env 文件中的关键配置
# 必需变量：DB_HOST, DB_PORT, REDIS_HOST, REDIS_PORT

# 部署Web服务
./deploy.sh --build

# 检查服务状态
docker compose ps
```

**默认端口配置：**
- PaperAnalysis: 5002 (可通过 `FLASK_PORT` 修改)
- Nginx代理: 80/443 (可选，通过 `NGINX_PORT`/`NGINX_SSL_PORT` 修改)

**自定义端口和远程服务示例：**
```bash
# 创建环境变量文件
cd Web/PaperAnalysis
cat > .env << EOF
# Flask应用配置
FLASK_PORT=8002
SECRET_KEY=your_flask_secret_key_here

# 远程数据库配置
DB_HOST=192.168.1.100
DB_PORT=25432
REDIS_HOST=192.168.1.100
REDIS_PORT=26379

# 远程OCR服务配置
REMOTE_OCR_ENDPOINT=http://192.168.1.101:8080

# LLM API配置
DEEPSEEK_API_KEY=your_api_key_here
SILICONFLOW_API_KEY=your_api_key_here
EOF

# 部署Web服务
./deploy.sh --build
```

**服务端点：**
- Web界面: `http://web-host:5002` (或自定义端口)
- API接口: `http://web-host:5002/api/`

## 📦 模块详细部署

### 数据库模块 (Database Module)

```bash
# 进入数据库目录
cd database/

# 启动服务
./start.sh

# 管理命令
./stop.sh           # 停止服务
./backup.sh         # 备份数据库
./restore.sh        # 恢复数据库
./check-tables.sh   # 检查表结构

# Web管理界面（可选）
docker compose --profile tools up -d
```

### 远程OCR模块 (Remote OCR Module)

```bash
# 进入远程应用目录
cd remote_app/

# 部署服务
./deploy.sh --build

# 管理命令
./deploy.sh --status    # 检查状态
./deploy.sh --logs      # 查看日志
./deploy.sh --down      # 停止服务

# 配置选项
export OCR_SERVICE_PORT=5001
export PADDLEOCR_USE_GPU=true
```

### PaperAnalysis模块 (Web Module)

```bash
# 进入Web应用目录
cd Web/PaperAnalysis/

# 配置环境变量
cat > .env << EOF
# 数据库配置（远程）
DB_HOST=192.168.1.100
DB_PORT=15432
REDIS_HOST=192.168.1.100
REDIS_PORT=16379

# OCR服务配置（远程）
REMOTE_OCR_ENDPOINT=http://192.168.1.101:5001

# LLM API配置
DEEPSEEK_API_KEY=your_api_key
SILICONFLOW_API_KEY=your_api_key
EOF

# 部署服务
./deploy.sh --build

# 管理命令
./deploy.sh --status    # 检查状态
./deploy.sh --logs      # 查看日志
```

## 🔧 配置指南

### 网络连接配置

**跨主机部署配置示例：**

```bash
# 在PaperAnalysis模块的.env文件中配置远程服务
DB_HOST=192.168.5.118        # 数据库主机IP
DB_PORT=15432
REDIS_HOST=192.168.5.118     # Redis主机IP
REDIS_PORT=16379
REMOTE_OCR_ENDPOINT=http://192.168.5.118:5001  # OCR服务地址
```

### LLM模型配置

支持多种大语言模型提供商：

```bash
# DeepSeek
DEEPSEEK_API_KEY=sk-xxx
DEEPSEEK_BASE_URL=https://api.deepseek.com

# 硅基流动
SILICONFLOW_API_KEY=sk-xxx
SILICONFLOW_BASE_URL=https://api.siliconflow.cn/v1

# 阿里云DashScope
DASHSCOPE_API_KEY=sk-xxx
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1

# 本地Ollama（必须）
OLLAMA_BASE_URL=http://192.168.5.217:11434
```

### 权限配置

确保Docker容器有正确的文件权限：

```bash
# 在各模块目录下运行权限设置脚本
./setup-permissions.sh --fix
```

## 🔌 可选集成服务

### SiYuan 笔记系统

```bash
# 配置SiYuan API连接
SIYUAN_API_URL=http://192.168.5.54:6806
SIYUAN_API_TOKEN=your_token
```

### Dify 知识库

```bash
# 配置Dify服务
DIFY_BASE_URL=http://192.168.5.54:5001
DIFY_KB_API_KEY=your_api_key
```

## 🐳 Docker 管理命令

### 查看所有服务状态

```bash
# 数据库服务
cd database && docker compose ps

# OCR服务
cd remote_app && docker compose ps

# Web服务
cd Web/PaperAnalysis && docker compose ps
```

### 日志管理

```bash
# 查看实时日志
docker compose logs -f [service_name]

# 查看错误日志
docker compose logs --tail=100 [service_name]
```

### 资源监控

```bash
# 容器资源使用情况
docker stats

# 磁盘使用情况
docker system df
```

## 📚 详细文档

- **数据库部署**: `database/README.md` - 完整的数据库部署指南
- **OCR服务**: `remote_app/README.md` - OCR服务配置和使用
- **Web应用**: `Web/PaperAnalysis/README.md` - PaperAnalysis详细功能
- **开发指南**: `docs/` - 各组件开发文档

## 🧪 功能测试

### 数据库连接测试

```bash
# 测试PostgreSQL连接
docker exec homesystem-postgres psql -U homesystem -d homesystem -c "\l"

# 测试Redis连接
docker exec homesystem-redis redis-cli ping
```

### OCR服务测试

```bash
# 健康检查
curl http://your-ocr-host:5001/api/health

# OCR功能测试
curl -X POST http://your-ocr-host:5001/api/ocr \
  -F "file=@test.pdf" \
  -F "options={\"use_gpu\": true}"
```

### Web应用测试

```bash
# 访问Web界面
http://your-web-host:5002

# API测试
curl http://your-web-host:5002/api/health
curl http://your-web-host:5002/api/about/llm_models
```

## 💡 故障排除

### 常见问题

**1. 端口冲突问题**
```bash
# 检查端口占用详情
lsof -i :15432
netstat -tlnp | grep :15432
ss -tulpn | grep :15432

# 批量检查所有默认端口
for port in 15432 16379 8080 8081 5001 5002; do
  echo "=== 检查端口 $port ==="
  lsof -i :$port 2>/dev/null || echo "端口 $port 可用"
done

# 解决方案：修改端口配置
echo "DB_PORT=25432" >> database/.env
echo "OCR_SERVICE_PORT=8080" >> remote_app/.env
echo "FLASK_PORT=8002" >> Web/PaperAnalysis/.env
```

**2. 跨主机连接失败**
```bash
# 测试网络连通性
ping 192.168.1.100
telnet 192.168.1.100 15432
nc -zv 192.168.1.100 15432

# 检查防火墙设置
sudo ufw status
sudo ufw allow 15432/tcp
sudo ufw allow 16379/tcp
sudo ufw allow 5001/tcp
sudo ufw allow 5002/tcp

# 检查服务监听状态（在服务器上）
ss -tulpn | grep -E ":(15432|16379|5001|5002)"
```

**3. 容器无法启动**
```bash
# 检查Docker守护进程
systemctl status docker

# 检查容器启动日志
docker compose logs postgres
docker compose logs redis
docker compose logs ocr-service
docker compose logs paper-analysis

# 检查docker-compose文件语法
docker compose config

# 强制重新创建容器
docker compose down
docker compose up -d --force-recreate
```

**4. 服务无法访问**
```bash
# 检查容器内部网络
docker compose exec postgres netstat -tlnp
docker compose exec paper-analysis curl -f localhost:5002/api/health

# 检查Docker网络
docker network ls
docker network inspect homesystem-network

# 测试服务连接
curl -f http://localhost:15432/api/health 2>/dev/null || echo "数据库端口无法访问"
curl -f http://localhost:5001/api/health 2>/dev/null || echo "OCR服务无法访问"
curl -f http://localhost:5002/api/health 2>/dev/null || echo "Web服务无法访问"
```

**5. 权限问题**
```bash
# 修复目录权限
./setup-permissions.sh --fix

# 检查Docker用户组
groups $USER | grep docker
sudo usermod -aG docker $USER  # 添加用户到docker组

# 检查数据目录权限
ls -la database/postgres/data/
ls -la remote_app/volumes/
```

**6. 资源不足**
```bash
# 检查系统资源
free -h
df -h
docker stats

# 清理Docker资源
docker system prune -f
docker volume prune -f
docker image prune -f

# 检查特定服务资源使用
docker stats homesystem-postgres homesystem-redis
```

### 服务健康检查

```bash
# 数据库健康检查
cd database && ./check-tables.sh

# OCR服务健康检查
curl http://ocr-host:5001/api/health

# Web服务健康检查
curl http://web-host:5002/api/health
```

## 📈 性能优化

### 资源配置建议

**数据库主机：**
- 内存: 8GB+
- 存储: SSD 100GB+
- CPU: 4核+

**OCR主机：**
- GPU: NVIDIA显卡 (建议)
- 内存: 8GB+
- 存储: 50GB+

**Web主机：**
- 内存: 4GB+
- 存储: 20GB+
- CPU: 2核+

## 🔒 安全建议

- 修改默认密码
- 配置防火墙规则
- 使用强API密钥
- 定期备份数据
- 监控访问日志


## 常见问题解决

### 1. ls: can't open '/docker-entrypoint-initdb.d/': Permission denied

权限问题，使用 ```sudo chmod -R 777 *``` 解决。



## 📄 许可证

MIT License - 详见 LICENSE 文件