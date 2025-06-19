// 结果组件
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
(function() {
    // DOM元素
    const statusJiraTicket = document.getElementById('statusJiraTicket');
    const checkStatusBtn = document.getElementById('checkStatusBtn');
    const statusResult = document.getElementById('statusResult');
    const downloadSection = document.getElementById('downloadSection');
    
    const fileToAnalyze = document.getElementById('fileToAnalyze');
    const analyzeFileBtn = document.getElementById('analyzeFileBtn');
    const analysisResult = document.getElementById('analysisResult');
    
    // 初始化
    function init() {
        if (checkStatusBtn) {
            checkStatusBtn.addEventListener('click', checkStatus);
        }
        
        if (analyzeFileBtn) {
            analyzeFileBtn.addEventListener('click', analyzeFile);
        }
        
        // 添加样式
        addStyles();
    }
    
    // 检查工单状态
    function checkStatus() {
        const jiraTicket = statusJiraTicket.value.trim();
        if (!jiraTicket) {
            showResultMessage('请输入Jira工单号', 'error');
            return;
        }
        
        // 显示加载效果
        showStatusLoading();
        
        // 模拟API调用
        setTimeout(() => {
            // 隐藏加载效果
            hideStatusLoading();
            
            // 更新状态卡片信息
            updateStatusCard(jiraTicket);
            
            // 显示状态结果
            statusResult.classList.remove('hidden');
            
            // 根据状态决定是否显示下载按钮
            const statusBadge = statusResult.querySelector('.status-badge');
            const statusValue = statusResult.querySelector('.item-value');
            
            if (statusValue && statusValue.textContent.includes('执行成功')) {
                downloadSection.classList.remove('hidden');
                statusBadge.textContent = '执行成功';
                statusBadge.classList.add('approved');
                
                // 添加下载事件
                const downloadBtn = downloadSection.querySelector('.download-btn');
                downloadBtn.addEventListener('click', downloadResults);
            } else {
                downloadSection.classList.add('hidden');
            }
            
        }, 1500);
    }
    
    // 显示状态加载效果
    function showStatusLoading() {
        checkStatusBtn.disabled = true;
        checkStatusBtn.innerHTML = '<span class="loading-spinner"></span> 查询中...';
        
        // 隐藏之前的结果
        statusResult.classList.add('hidden');
    }
    
    // 隐藏状态加载效果
    function hideStatusLoading() {
        checkStatusBtn.disabled = false;
        checkStatusBtn.textContent = '查询状态';
    }
    
    // 更新状态卡片信息
    function updateStatusCard(jiraTicket) {
        // 更新Jira ID
        const jiraIdEl = statusResult.querySelector('.jira-id');
        if (jiraIdEl) {
            jiraIdEl.textContent = jiraTicket;
        }
        
        // 模拟生成随机状态
        const statusTypes = ['等待审批', '已审批', '执行成功', '执行失败'];
        const randomIndex = Math.floor(Math.random() * statusTypes.length);
        const selectedStatus = statusTypes[randomIndex];
        
        // 更新状态信息
        const statusValueEls = statusResult.querySelectorAll('.item-value');
        if (statusValueEls && statusValueEls.length >= 2) {
            // 第一个是申请状态
            if (randomIndex >= 1) {
                statusValueEls[0].textContent = '已审批';
            } else {
                statusValueEls[0].textContent = '等待审批';
            }
            
            // 第二个是执行状态
            if (randomIndex >= 2) {
                statusValueEls[1].textContent = selectedStatus === '执行成功' ? '执行成功' : '执行失败';
            } else {
                statusValueEls[1].textContent = '待执行';
            }
        }
        
        // 更新状态徽章
        const statusBadge = statusResult.querySelector('.status-badge');
        if (statusBadge) {
            statusBadge.textContent = selectedStatus;
            statusBadge.className = 'status-badge';
            
            if (selectedStatus === '执行成功') {
                statusBadge.classList.add('approved');
            } else if (selectedStatus === '执行失败') {
                statusBadge.classList.add('rejected');
            }
        }
    }
    
    // 下载结果文件
    function downloadResults() {
        const jiraId = statusResult.querySelector('.jira-id').textContent;
        showResultMessage(`正在下载 ${jiraId} 的结果文件...`, 'info');
        
        // 模拟下载延迟
        setTimeout(() => {
            showResultMessage(`文件 Veeva_Report_${jiraId}.xlsx 下载成功！`, 'success');
            
            // 提示用户进行分析
            setTimeout(() => {
                showResultMessage('你可以上传文件进行数据分析', 'info');
                
                // 滚动到分析区域
                scrollToAnalysisSection();
            }, 2000);
        }, 1500);
    }
    
    // 分析文件
    function analyzeFile() {
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
        
        // 模拟文件分析过程
        setTimeout(() => {
            // 隐藏加载效果
            hideAnalysisLoading();
            
            // 显示分析结果
            displayAnalysisResults(file.name);
            
            // 显示成功消息
            showResultMessage(`文件 ${file.name} 分析完成！`, 'success');
        }, 2000);
    }
    
    // 显示分析加载效果
    function showAnalysisLoading() {
        analyzeFileBtn.disabled = true;
        analyzeFileBtn.innerHTML = '<span class="loading-spinner"></span> 分析中...';
    }
    
    // 隐藏分析加载效果
    function hideAnalysisLoading() {
        analyzeFileBtn.disabled = false;
        analyzeFileBtn.textContent = '分析文件';
    }
    
    // 展示分析结果
    function displayAnalysisResults(filename) {
        // 生成示例数据
        const sampleData = generateSampleData();
        
        // 获取表格主体
        const resultTable = analysisResult.querySelector('.result-table tbody');
        
        // 清空旧数据
        resultTable.innerHTML = '';
        
        // 填充新数据
        sampleData.forEach(item => {
            const row = document.createElement('tr');
            
            row.innerHTML = `
                <td>${item.rank}</td>
                <td>${item.name}</td>
                <td>${item.count}</td>
            `;
            
            resultTable.appendChild(row);
        });
        
        // 更新结果标题
        const resultTitle = analysisResult.querySelector('h4');
        if (resultTitle) {
            resultTitle.textContent = `"${filename}" 的分析结果`;
        }
        
        // 显示结果区域
        analysisResult.classList.remove('hidden');
    }
    
    // 生成示例数据
    function generateSampleData() {
        // 生成8-15个随机客户数据
        const numItems = Math.floor(Math.random() * 8) + 8;
        const data = [];
        
        for (let i = 1; i <= numItems; i++) {
            const customerName = getRandomCustomerName();
            const count = Math.floor(Math.random() * 1500) + 100;
            
            data.push({
                rank: i,
                name: customerName,
                count: count
            });
        }
        
        // 按数据量排序
        return data.sort((a, b) => b.count - a.count)
            .map((item, index) => ({...item, rank: index + 1}));
    }
    
    // 获取随机客户名称
    function getRandomCustomerName() {
        const prefixes = ['北京', '上海', '广州', '深圳', '南京', '杭州', '成都', '重庆', '武汉'];
        const types = ['制药', '医疗', '健康', '生物', '科技', '药业'];
        const suffixes = ['有限公司', '股份公司', '集团', '企业', '国际'];
        
        const prefix = prefixes[Math.floor(Math.random() * prefixes.length)];
        const type = types[Math.floor(Math.random() * types.length)];
        const suffix = suffixes[Math.floor(Math.random() * suffixes.length)];
        
        return `${prefix}${type}${suffix}`;
    }
    
    // 显示结果消息
    function showResultMessage(message, type = 'info') {
        // 创建消息元素
        const messageDiv = document.createElement('div');
        messageDiv.className = `result-message ${type}`;
        messageDiv.textContent = message;
        
        // 添加到页面
        const resultsContainer = document.querySelector('.results-container');
        resultsContainer.insertAdjacentElement('afterbegin', messageDiv);
        
        // 显示动画
        setTimeout(() => {
            messageDiv.classList.add('show');
        }, 10);
        
        // 3秒后移除
        setTimeout(() => {
            messageDiv.classList.remove('show');
            setTimeout(() => {
                messageDiv.remove();
            }, 300);
        }, 3000);
    }
    
    // 滚动到分析区域
    function scrollToAnalysisSection() {
        const analysisSection = document.querySelector('.analysis-section');
        if (analysisSection) {
            analysisSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
    }
    
    // 添加样式
    function addStyles() {
        const style = document.createElement('style');
        style.textContent = `
            .loading-spinner {
                display: inline-block;
                width: 16px;
                height: 16px;
                border: 2px solid rgba(255,255,255,0.3);
                border-radius: 50%;
                border-top-color: #fff;
                animation: spin 1s ease-in-out infinite;
                margin-right: 8px;
                vertical-align: middle;
            }
            
            .result-message {
                padding: 12px 15px;
                margin-bottom: 15px;
                border-radius: 6px;
                font-weight: 500;
                position: fixed;
                top: 20px;
                right: 20px;
                z-index: 1000;
                box-shadow: 0 4px 12px rgba(0,0,0,0.1);
                transform: translateX(120%);
                transition: transform 0.3s ease;
                min-width: 250px;
            }
            
            .result-message.show {
                transform: translateX(0);
            }
            
            .result-message.info {
                background-color: #e3f2fd;
                color: #0288d1;
            }
            
            .result-message.success {
                background-color: #e8f5e9;
                color: #2e7d32;
            }
            
            .result-message.error {
                background-color: #ffebee;
                color: #c62828;
            }
            
            .chat-table {
                width: 100%;
                border-collapse: collapse;
                margin: 15px 0;
            }
            
            .chat-table th, .chat-table td {
                padding: 8px;
                border: 1px solid #ddd;
                text-align: left;
            }
            
            .chat-table th {
                background-color: #f5f5f5;
            }
            
            @keyframes spin {
                to { transform: rotate(360deg); }
            }
        `;
        
        document.head.appendChild(style);
    }
    
    // 初始化
    init();
})(); 