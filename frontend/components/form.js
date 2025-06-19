// 表单组件
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
(function() {
    // DOM元素
    const dataRequestForm = document.getElementById('dataRequestForm');
    
    // 初始化
    function init() {
        if (dataRequestForm) {
            dataRequestForm.addEventListener('submit', handleFormSubmit);
        }
    }
    
    // 处理表单提交
    function handleFormSubmit(e) {
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
        
        // 模拟处理流程
        setTimeout(() => {
            // 模拟SQL生成
            showFormMessage('正在根据描述生成SQL查询...', 'info');
            
            setTimeout(() => {
                // 模拟表单提交
                showFormMessage('SQL生成完成，正在提交表单...', 'info');
                
                setTimeout(() => {
                    // 模拟提交完成
                    hideLoading();
                    showFormMessage(`提交成功！Jira工单 ${jiraTicket} 的申请已发送给 ${approver} 审批。`, 'success');
                    
                    // 重置表单
                    dataRequestForm.reset();
                    
                    // 添加一个自动跳转到结果页的选项
                    showRedirectOption(jiraTicket);
                    
                }, 1500);
            }, 1500);
        }, 1500);
    }
    
    // 显示表单消息
    function showFormMessage(message, type = 'info') {
        // 移除旧消息
        removeFormMessage();
        
        // 创建新消息元素
        const messageDiv = document.createElement('div');
        messageDiv.className = `form-message ${type}`;
        messageDiv.id = 'formMessage';
        messageDiv.textContent = message;
        
        // 添加到表单前面
        dataRequestForm.insertAdjacentElement('beforebegin', messageDiv);
        
        // 如果是成功或错误消息，添加动画
        if (type === 'success' || type === 'error') {
            messageDiv.classList.add('animated');
        }
    }
    
    // 移除表单消息
    function removeFormMessage() {
        const oldMessage = document.getElementById('formMessage');
        if (oldMessage) {
            oldMessage.remove();
        }
    }
    
    // 显示加载状态
    function showLoading() {
        // 禁用表单
        Array.from(dataRequestForm.elements).forEach(element => {
            element.disabled = true;
        });
        
        // 创建加载指示器
        const submitBtn = dataRequestForm.querySelector('.submit-btn');
        submitBtn.innerHTML = '<span class="loading-spinner"></span> 处理中...';
    }
    
    // 隐藏加载状态
    function hideLoading() {
        // 启用表单
        Array.from(dataRequestForm.elements).forEach(element => {
            element.disabled = false;
        });
        
        // 恢复按钮文本
        const submitBtn = dataRequestForm.querySelector('.submit-btn');
        submitBtn.textContent = '提交申请';
    }
    
    // 显示重定向选项
    function showRedirectOption(jiraTicket) {
        const redirectDiv = document.createElement('div');
        redirectDiv.className = 'redirect-option';
        redirectDiv.id = 'redirectOption';
        
        redirectDiv.innerHTML = `
            <p>你想现在查询这个工单的状态吗？</p>
            <div class="redirect-buttons">
                <button class="redirect-btn yes">是的，查询状态</button>
                <button class="redirect-btn no">稍后再查</button>
            </div>
        `;
        
        // 添加到表单后面
        dataRequestForm.insertAdjacentElement('afterend', redirectDiv);
        
        // 添加事件监听
        const yesBtn = redirectDiv.querySelector('.redirect-btn.yes');
        const noBtn = redirectDiv.querySelector('.redirect-btn.no');
        
        yesBtn.addEventListener('click', () => {
            // 切换到结果页面
            const resultsTab = document.querySelector('nav a[data-tab="results"]');
            resultsTab.click();
            
            // 填写工单号
            const statusJiraTicket = document.getElementById('statusJiraTicket');
            statusJiraTicket.value = jiraTicket;
            
            // 自动触发查询
            const checkStatusBtn = document.getElementById('checkStatusBtn');
            checkStatusBtn.click();
            
            // 移除重定向选项
            redirectDiv.remove();
        });
        
        noBtn.addEventListener('click', () => {
            redirectDiv.remove();
        });
    }
    
    // 添加CSS
    function addStyles() {
        const style = document.createElement('style');
        style.textContent = `
            .form-message {
                padding: 15px;
                margin-bottom: 20px;
                border-radius: 6px;
                font-weight: 500;
            }
            
            .form-message.info {
                background-color: #e3f2fd;
                color: #0288d1;
            }
            
            .form-message.success {
                background-color: #e8f5e9;
                color: #2e7d32;
            }
            
            .form-message.error {
                background-color: #ffebee;
                color: #c62828;
            }
            
            .form-message.animated {
                animation: fadeInSlide 0.3s ease;
            }
            
            .loading-spinner {
                display: inline-block;
                width: 18px;
                height: 18px;
                border: 2px solid rgba(255,255,255,0.3);
                border-radius: 50%;
                border-top-color: #fff;
                animation: spin 1s ease-in-out infinite;
                margin-right: 8px;
                vertical-align: middle;
            }
            
            .redirect-option {
                margin-top: 20px;
                padding: 15px;
                background-color: #f5f5f5;
                border-radius: 6px;
                text-align: center;
                animation: fadeIn 0.3s ease;
            }
            
            .redirect-buttons {
                margin-top: 15px;
                display: flex;
                justify-content: center;
                gap: 10px;
            }
            
            .redirect-btn {
                padding: 8px 16px;
                border-radius: 4px;
                border: none;
                cursor: pointer;
                font-weight: 500;
            }
            
            .redirect-btn.yes {
                background-color: #1f5dd3;
                color: white;
            }
            
            .redirect-btn.no {
                background-color: #f5f5f5;
                border: 1px solid #ddd;
                color: #666;
            }
            
            @keyframes fadeInSlide {
                from { 
                    opacity: 0;
                    transform: translateY(-10px);
                }
                to { 
                    opacity: 1;
                    transform: translateY(0);
                }
            }
            
            @keyframes spin {
                to { transform: rotate(360deg); }
            }
        `;
        
        document.head.appendChild(style);
    }
    
    // 添加样式
    addStyles();
    
    // 初始化
    init();
})(); 