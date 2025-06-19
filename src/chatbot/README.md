# Veeva pegasus数据查询分析助手 - 后端API服务

该项目提供了一个API服务，集成了Veeva pegasus数据查询分析助手的核心功能，包括数据查询提交、工单状态查询和数据分析。

## 项目结构

```
/src/chatbot/
  ├── agent_1.py         # 核心功能实现
  ├── api_server.py      # FastAPI服务器
  ├── api_client.js      # 前端API客户端
  ├── requirements_api.txt # API服务器依赖项
  └── README.md          # 本文件
```

## 功能特点

1. **RESTful API接口**：使用FastAPI构建的现代化API服务
2. **异步任务处理**：使用后台任务处理长时间运行的操作
3. **实时状态更新**：通过轮询机制获取任务最新状态
4. **文件上传和下载**：支持Excel文件的上传和分析结果下载
5. **跨域资源共享**：配置CORS，支持前端跨域访问

## 安装与运行

### 环境要求

- Python 3.8+
- Node.js 14+ (如果需要使用前端客户端)

### 安装依赖

```bash
# 安装Python依赖
pip install -r requirements_api.txt

# 安装Playwright相关依赖（用于浏览器自动化）
playwright install chromium
```

### 环境变量配置

创建`.env`文件在项目根目录：

```
VEEVA_USERNAME=your_username
VEEVA_PASSWORD=your_password
OKTA_PUSH=True/False
GOOGLE_API_KEY=your_google_api_key  # 用于Gemini API
```

### 启动服务器

```bash
# 从src/chatbot目录启动
cd src/chatbot
python api_server.py

# 或者使用uvicorn直接启动
uvicorn api_server:app --host 0.0.0.0 --port 8000 --reload
```

服务器将在`http://localhost:8000`上运行。

## API端点

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/submit-query` | POST | 提交数据查询申请 |
| `/api/task-status/{task_id}` | GET | 获取任务状态 |
| `/api/check-jira-status` | POST | 查询工单状态 |
| `/api/download/{filename}` | GET | 下载文件 |
| `/api/analyze-file` | POST | 分析Excel文件 |
| `/api/chat` | POST | 发送聊天消息 |

详细的API文档可以在服务器运行后访问：`http://localhost:8000/api/docs`

## 前端集成

对于前端开发者，我们提供了一个JavaScript客户端库`api_client.js`，可以轻松集成到前端应用中。详细的集成指南可以在`frontend/frontend_api_integration.md`中找到。

### 基本使用示例

```javascript
// 导入API客户端
import apiClient from './api_client.js';

// 提交查询
const response = await apiClient.submitQuery({
    jira_ticket: "ORI-12345",
    approver: "john.doe",
    query_description: "查询所有客户的协访记录"
});

// 查询任务状态
const status = await apiClient.checkTaskStatus(response.task_id);

// 查询工单状态
const jiraStatus = await apiClient.checkJiraStatus("ORI-12345");

// 分析文件
const fileInput = document.getElementById('fileInput');
const analysis = await apiClient.analyzeFile(fileInput.files[0]);
```

## 错误处理

API服务返回的错误格式统一为：

```json
{
  "success": false,
  "message": "错误描述"
}
```

在前端代码中应该检查`success`字段以确定请求是否成功。

## 安全性考虑

本API服务器包含以下安全功能：

- CORS配置（当前设置为允许所有来源，生产环境应该限制）
- 异步任务处理以避免阻塞
- 临时文件自动清理

**注意**：在生产环境中部署时，应该进一步加强安全性措施：

1. 配置HTTPS
2. 添加适当的认证机制
3. 限制CORS到指定域名
4. 添加速率限制
5. 优化错误处理和日志记录

## 贡献指南

1. 创建分支
2. 提交变更
3. 创建Pull Request
4. 代码审查
5. 合并

## 许可证

参见项目根目录的LICENSE文件。 