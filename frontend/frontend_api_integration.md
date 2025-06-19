# Veeva pegasus 数据查询分析助手 - 前端API集成指南

本文档提供了如何将前端页面与后端API集成的详细说明。

## API客户端

我们提供了一个完整的API客户端类 `VeevaAPIClient`，可以在 `src/chatbot/api_client.js` 中找到。这个类封装了与后端API交互的所有方法。

## 安装指南

1. **复制API客户端文件**

   将 `src/chatbot/api_client.js` 文件复制到前端项目的适当位置，例如 `frontend/assets/js/` 目录。

2. **导入API客户端**

   在HTML文件中引入API客户端:

   ```html
   <script type="module">
     import apiClient from './assets/js/api_client.js';
     // 使用apiClient...
   </script>
   ```

   或者在你的JS模块中:

   ```javascript
   import apiClient from '../assets/js/api_client.js';
   ```

3. **配置API端点**

   默认情况下，API客户端连接到 `http://localhost:8000`。你可以在初始化时自定义API端点:

   ```javascript
   // 创建自定义API客户端实例
   const customApiClient = new VeevaAPIClient('https://your-api-endpoint.com');
   ```

## 集成示例

### 聊天组件集成

```javascript
// 在chat.js中集成API
import apiClient from '../assets/js/api_client.js';

// 发送消息时调用API
async function sendMessage() {
    const message = userInput.value;
    if (!message) return;
    
    // 显示用户消息
    addMessage(message, 'user');
    userInput.value = '';
    
    // 显示"正在输入"状态
    showTypingIndicator();
    
    try {
        // 发送消息到API
        const response = await apiClient.sendChatMessage(message);
        
        // 隐藏"正在输入"状态
        hideTypingIndicator();
        
        // 处理响应
        if (response.success) {
            // 显示机器人回复
            addMessage(response.message, 'bot');
        } else {
            addMessage("抱歉，处理您的请求时出现问题。请再试一次。", 'bot');
        }
    } catch (error) {
        hideTypingIndicator();
        addMessage("网络错误，无法连接到服务器。", 'bot');
    }
    
    // 滚动到最新消息
    scrollToBottom();
}
```

### 表单组件集成

```javascript
// 在form.js中集成API
import apiClient from '../assets/js/api_client.js';

// 处理表单提交
async function handleFormSubmit(e) {
    e.preventDefault();
    
    // 获取表单数据
    const jiraTicket = document.getElementById('jiraTicket').value;
    const approver = document.getElementById('approver').value;
    const queryDescription = document.getElementById('queryDescription').value;
    
    // 表单验证
    if (!jiraTicket || !approver || !queryDescription) {
        showFormMessage('请填写所有必填字段', 'error');
        return;
    }
    
    // 显示加载状态
    showLoading();
    showFormMessage('正在提交请求...', 'info');
    
    try {
        // 提交数据到API
        const response = await apiClient.submitQuery({
            jira_ticket: jiraTicket,
            approver: approver,
            query_description: queryDescription
        });
        
        // 处理响应
        if (response.success) {
            hideLoading();
            showFormMessage(`提交成功！任务ID: ${response.task_id}`, 'success');
            
            // 保存任务ID以便后续查询
            localStorage.setItem('lastTaskId', response.task_id);
            localStorage.setItem('lastJiraTicket', jiraTicket);
            
            // 轮询任务状态
            apiClient.pollTaskStatus(
                response.task_id,
                (statusResult) => {
                    showFormMessage(`状态更新: ${statusResult.message}`, 'info');
                },
                (finalResult) => {
                    if (finalResult.status === 'completed') {
                        showFormMessage('任务完成！', 'success');
                        // 显示重定向选项
                        showRedirectOption(jiraTicket);
                    } else {
                        showFormMessage(`任务失败: ${finalResult.message}`, 'error');
                    }
                }
            );
            
            // 重置表单
            dataRequestForm.reset();
            
        } else {
            hideLoading();
            showFormMessage(`提交失败: ${response.message}`, 'error');
        }
    } catch (error) {
        hideLoading();
        showFormMessage(`网络错误: ${error.message}`, 'error');
    }
}
```

### 结果组件集成

```javascript
// 在results.js中集成API
import apiClient from '../assets/js/api_client.js';

// 查询工单状态
async function checkStatus() {
    const jiraTicket = statusJiraTicket.value.trim();
    if (!jiraTicket) {
        showResultMessage('请输入Jira工单号', 'error');
        return;
    }
    
    // 显示加载效果
    showStatusLoading();
    
    try {
        // 调用API查询状态
        const response = await apiClient.checkJiraStatus(jiraTicket);
        
        // 处理响应
        if (response.success) {
            const taskId = response.task_id;
            showResultMessage(`状态查询请求已提交，任务ID: ${taskId}`, 'info');
            
            // 轮询任务状态
            apiClient.pollTaskStatus(
                taskId,
                (statusResult) => {
                    // 状态更新回调
                    if (statusResult.status === 'processing') {
                        showResultMessage(`处理中: ${statusResult.message}`, 'info');
                    }
                },
                (finalResult) => {
                    // 任务完成回调
                    hideStatusLoading();
                    
                    if (finalResult.status === 'completed') {
                        // 更新状态卡片
                        updateStatusCardFromAPI(jiraTicket, finalResult.data);
                        
                        // 显示状态结果
                        statusResult.classList.remove('hidden');
                        
                        // 如果文件已下载就显示下载按钮
                        if (finalResult.data.download_ready) {
                            downloadSection.classList.remove('hidden');
                            const downloadBtn = downloadSection.querySelector('.download-btn');
                            const fileName = finalResult.data.file;
                            
                            downloadBtn.addEventListener('click', () => {
                                apiClient.downloadFile(fileName);
                                showResultMessage(`文件 ${fileName} 下载中...`, 'success');
                            });
                        }
                    } else {
                        showResultMessage(`查询失败: ${finalResult.message}`, 'error');
                    }
                }
            );
            
        } else {
            hideStatusLoading();
            showResultMessage(`查询失败: ${response.message}`, 'error');
        }
    } catch (error) {
        hideStatusLoading();
        showResultMessage(`网络错误: ${error.message}`, 'error');
    }
}

// 分析文件
async function analyzeFile() {
    const file = fileToAnalyze.files[0];
    
    if (!file) {
        showResultMessage('请先选择要分析的Excel文件', 'error');
        return;
    }
    
    if (!file.name.endsWith('.xlsx') && !file.name.endsWith('.xls')) {
        showResultMessage('请选择有效的Excel文件 (.xlsx 或 .xls)', 'error');
        return;
    }
    
    // 显示加载效果
    showAnalysisLoading();
    
    try {
        // 上传文件到API进行分析
        const response = await apiClient.analyzeFile(file);
        
        // 隐藏加载效果
        hideAnalysisLoading();
        
        // 处理响应
        if (response.success) {
            // 显示分析结果
            if (response.data && response.data.length > 0) {
                displayAnalysisResultsFromAPI(response.data);
            } else {
                // 使用文本结果创建表格数据
                displayAnalysisResultsFromText(response.result);
            }
            
            // 显示成功消息
            showResultMessage(`文件 ${file.name} 分析完成！`, 'success');
        } else {
            showResultMessage(`分析失败: ${response.message}`, 'error');
        }
    } catch (error) {
        hideAnalysisLoading();
        showResultMessage(`网络错误: ${error.message}`, 'error');
    }
}
```

## API端点参考

| 端点 | 方法 | 描述 | 请求体/参数 | 响应 |
|------|------|------|------------|------|
| `/api/submit-query` | POST | 提交数据查询申请 | `{jira_ticket, approver, query_description}` | `{success, message, task_id, sql_query}` |
| `/api/task-status/{task_id}` | GET | 获取任务状态 | `task_id` (路径参数) | `{status, message, data}` |
| `/api/check-jira-status` | POST | 查询工单状态 | `{jira_ticket}` | `{success, message, task_id}` |
| `/api/download/{filename}` | GET | 下载文件 | `filename` (路径参数) | 文件内容 |
| `/api/analyze-file` | POST | 分析Excel文件 | `file` (FormData) | `{success, message, result, data}` |
| `/api/chat` | POST | 发送聊天消息 | `message` (FormData) | `{success, message}` |

## 启动后端API服务器

在集成前端之前，请确保启动后端API服务器:

```bash
# 安装依赖项
pip install -r src/chatbot/requirements_api.txt
c'd
# 启动API服务器
cd src/chatbot
python api_server.py
```

默认情况下，API服务器在 `http://localhost:8000` 上运行。你可以在浏览器中访问 `http://localhost:8000/api/docs` 查看API文档。 