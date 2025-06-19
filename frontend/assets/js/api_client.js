/**
 * Veeva pegasus数据查询分析助手API客户端
 * 用于前端与后端API交互
 */

class VeevaAPIClient {
    constructor(baseURL = '') {
        // 当使用相对路径时，会使用当前域名作为基础
        this.baseURL = baseURL;
        console.log('VeevaAPIClient 已初始化, baseURL:', this.baseURL);
    }

    /**
     * 提交数据查询申请
     * @param {Object} data 包含jira_ticket、approver和query_description的对象
     * @returns {Promise} API响应
     */
    async submitQuery(data) {
        try {
            const response = await fetch(`${this.baseURL}/api/submit-query`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(data)
            });
            
            return await response.json();
        } catch (error) {
            console.error('提交查询请求失败:', error);
            return {
                success: false,
                message: `提交失败: ${error.message}`
            };
        }
    }

    /**
     * 获取任务状态
     * @param {string} taskId 任务ID
     * @returns {Promise} API响应
     */
    async checkTaskStatus(taskId) {
        try {
            const response = await fetch(`${this.baseURL}/api/task-status/${taskId}`);
            return await response.json();
        } catch (error) {
            console.error('获取任务状态失败:', error);
            return {
                status: 'error',
                message: `获取状态失败: ${error.message}`
            };
        }
    }

    /**
     * 查询工单状态
     * @param {string} jiraTicket Jira工单号
     * @returns {Promise} API响应
     */
    async checkJiraStatus(jiraTicket) {
        try {
            const response = await fetch(`${this.baseURL}/api/check-jira-status`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ jira_ticket: jiraTicket })
            });
            
            return await response.json();
        } catch (error) {
            console.error('查询工单状态失败:', error);
            return {
                success: false,
                message: `查询失败: ${error.message}`
            };
        }
    }

    /**
     * 下载文件
     * @param {string} filename 文件名
     */
    downloadFile(filename) {
        // 创建下载链接
        const downloadUrl = `${this.baseURL}/api/download/${filename}`;
        
        // 创建一个隐藏的a标签
        const link = document.createElement('a');
        link.href = downloadUrl;
        link.download = filename;
        
        // 添加到页面并触发点击
        document.body.appendChild(link);
        link.click();
        
        // 清理
        document.body.removeChild(link);
    }

    /**
     * 分析Excel文件
     * @param {File} file 要分析的Excel文件
     * @returns {Promise} API响应
     */
    async analyzeFile(file) {
        try {
            const formData = new FormData();
            formData.append('file', file);
            
            const response = await fetch(`${this.baseURL}/api/analyze-file`, {
                method: 'POST',
                body: formData
            });
            
            return await response.json();
        } catch (error) {
            console.error('分析文件失败:', error);
            return {
                success: false,
                message: `分析失败: ${error.message}`
            };
        }
    }

    /**
     * 发送聊天消息
     * @param {string} message 聊天消息内容
     * @returns {Promise} API响应
     */
    async sendChatMessage(message) {
        console.log('发送聊天消息到API:', message);
        try {
            const formData = new FormData();
            formData.append('message', message);
            
            const response = await fetch(`${this.baseURL}/api/chat`, {
                method: 'POST',
                body: formData
            });
            
            const result = await response.json();
            console.log('API响应:', result);
            return result;
        } catch (error) {
            console.error('发送聊天消息失败:', error);
            return {
                success: false,
                message: `发送失败: ${error.message}`
            };
        }
    }

    /**
     * 轮询任务状态直到完成
     * @param {string} taskId 任务ID
     * @param {function} onUpdate 状态更新回调
     * @param {function} onComplete 完成回调
     * @param {number} interval 轮询间隔(毫秒)
     */
    async pollTaskStatus(taskId, onUpdate, onComplete, interval = 2000) {
        const poll = async () => {
            const result = await this.checkTaskStatus(taskId);
            
            if (onUpdate) {
                onUpdate(result);
            }
            
            if (['completed', 'failed'].includes(result.status)) {
                if (onComplete) {
                    onComplete(result);
                }
            } else {
                // 继续轮询
                setTimeout(poll, interval);
            }
        };
        
        // 开始轮询
        poll();
    }
}

// 创建API客户端实例并将其暴露在全局作用域中
window.apiClient = new VeevaAPIClient();

// 向控制台输出确认信息
console.log('API客户端已加载并绑定到全局window.apiClient'); 