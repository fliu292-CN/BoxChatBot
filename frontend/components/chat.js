// 聊天组件
(function() {
    // DOM元素
    const chatMessages = document.getElementById('chatMessages');
    const userInput = document.getElementById('userInput');
    const sendBtn = document.getElementById('sendBtn');
    
    // 配置常量
    const MAX_MESSAGES = 100; // 聊天窗口最大显示的消息数量
    const SCROLL_DEBOUNCE_TIME = 100; // 滚动防抖时间 (毫秒)

    let scrollTimeout = null; // 用于滚动防抖的计时器

    // 初始化
    function init() {
        // 添加发送按钮点击事件
        sendBtn.addEventListener('click', sendMessage);
        
        // 添加输入框Enter键发送
        userInput.addEventListener('keypress', function(e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
        });
        
        // 调试信息
        console.log('聊天组件已初始化');
        console.log('apiClient是否可用:', typeof window.apiClient !== 'undefined');
    }
    
    // 发送消息
    async function sendMessage() {
        const message = userInput.value.trim();
        if (!message) return;
        
        console.log('发送消息:', message);
        
        // 添加用户消息到聊天区域
        addMessage(message, 'user');
        
        // 清空输入框
        userInput.value = '';
        
        // 显示"正在输入"状态
        showTypingIndicator();
        
        try {
            // 检查apiClient是否在全局作用域可用
            if (typeof window.apiClient !== 'undefined') {
                console.log('使用API客户端发送消息');
                const response = await window.apiClient.sendChatMessage(message);
                
                // 隐藏"正在输入"状态
                hideTypingIndicator();
                
                if (response.success) {
                    // 如果后端返回了task_id，则建立SSE连接
                    if (response.task_id) {
                        addMessage(response.response, 'bot'); // 显示初始的确认消息
                        listenForTaskUpdates(response.task_id);
                    } else {
                        addMessage(response.response, 'bot'); // 如果没有task_id，直接显示消息
                    }
                } else {
                    addMessage(`抱歉，处理您的请求时出现问题: ${response.message}`, 'bot');
                }
            } else {
                console.log('API客户端不可用，使用模拟响应');
                // 如果API客户端不可用，回退到模拟响应
                setTimeout(() => {
                    hideTypingIndicator();
                    const response = generateResponse(message);
                    addMessage(response, 'bot');
                }, 1000);
            }
        } catch (error) {
            console.error('发送消息时出错:', error);
            hideTypingIndicator();
            addMessage("网络错误，无法连接到服务器。", 'bot');
        }
        
        // 滚动到最新消息
        debouncedScrollToBottom();
    }
    
    // 添加消息到聊天区域
    function addMessage(text, sender) {
        // 创建消息容器
        const messageDiv = document.createElement('div');
        messageDiv.className = `message ${sender}`;
        
        // 创建头像容器
        const avatarDiv = document.createElement('div');
        avatarDiv.className = 'avatar';
        
        // 创建头像图片
        const avatarImg = document.createElement('img');
        avatarImg.src = sender === 'bot' ? 
            'assets/img/bot-avatar.png' : 
            'assets/img/user-avatar.png';
        avatarDiv.appendChild(avatarImg);
        
        // 创建消息内容容器
        const contentDiv = document.createElement('div');
        contentDiv.className = 'message-content';
        
        // 处理消息内容（支持简单的markdown格式）
        const formattedText = formatMessageText(text);
        contentDiv.innerHTML = formattedText;
        
        // 组装消息
        messageDiv.appendChild(avatarDiv);
        messageDiv.appendChild(contentDiv);
        
        // 添加到聊天区域
        chatMessages.appendChild(messageDiv);
        
        // 限制消息数量，移除旧消息
        while (chatMessages.children.length > MAX_MESSAGES) {
            chatMessages.removeChild(chatMessages.firstChild);
        }

        // 滚动到最新消息
        debouncedScrollToBottom();
    }
    
    // 格式化消息文本（支持简单的markdown）
    function formatMessageText(text) {
        // 将换行符转换为<br>，这是为了后续方便按行处理HTML
        let formatted = text.replace(/\n/g, '<br>');
        
        // 支持简单的markdown表格
        if (formatted.includes('|')) {
            const lines = formatted.split('<br>');
            const tableHtmlParts = [];
            let inTable = false;
            
            for (let i = 0; i < lines.length; i++) {
                const line = lines[i];
                const trimmedLine = line.trim();

                // 检查是否看起来像表格行 (以|开头和结尾，并且中间包含|) - 更严格的判断
                if (trimmedLine.startsWith('|') && trimmedLine.endsWith('|') && trimmedLine.slice(1, -1).includes('|')) {
                    const cells = trimmedLine.split('|').filter(cell => cell.trim() !== '');

                    // 检查是否是分隔行 (例如：|---|---|)
                    const isSeparator = cells.every(cell => cell.replace(/-/g, '').trim() === '');

                    if (isSeparator) {
                        // 如果我们在表格中并且这是一个分隔符，则跳过它。
                        // 它表示表头的结束或行之间的分隔。
                        continue; 
                    }

                    if (!inTable) {
                        tableHtmlParts.push('<table class="chat-table">');
                        inTable = true;
                    }
                    
                    let rowHtml = '<tr>';
                    // 通过检查下一行是否为分隔符来判断是否为表头行
                    const isHeaderRow = (i + 1 < lines.length && lines[i+1].trim().match(/^\\|[:-]+\\|(?:[:-]+\\|)*$/));

                    for (const cell of cells) {
                        const tag = isHeaderRow ? 'th' : 'td';
                        rowHtml += `<${tag}>${cell.trim()}</${tag}>`;
                    }
                    rowHtml += '</tr>';
                    tableHtmlParts.push(rowHtml);
                } else {
                    if (inTable) {
                        tableHtmlParts.push('</table>');
                        inTable = false;
                    }
                    // 对于非表格行，直接添加（它们已经从第一步获得了<br>）
                    tableHtmlParts.push(line);
                }
            }
            
            if (inTable) {
                tableHtmlParts.push('</table>');
            }
            
            // 重新组合所有处理过的行，注意这里不再简单地用<br>连接所有，
            // 而是确保表格结构和非表格内容正确混合。
            formatted = tableHtmlParts.join(''); // 临时使用空字符串连接，因为<br>已经在行中
            
            // 再次将<br>替换回换行符，因为后续处理如加粗斜体不需要HTML换行符
            formatted = formatted.replace(/<br>/g, '\n');

            // 处理加粗文本 (使用非贪婪匹配)
            formatted = formatted.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
            
            // 处理斜体文本 (使用非贪婪匹配)
            formatted = formatted.replace(/\*(.*?)\*/g, '<em>$1</em>');
            
            // 最后，将所有换行符转换为<p>标签或<br>标签，确保文本的块级显示和换行
            // 更复杂的处理可以考虑将段落包裹在<p>中，这里简单转换为<br>
            formatted = formatted.split('\n').map(p => `<p>${p}</p>`).join('');
            formatted = formatted.replace(/<p><\/p>/g, '<br>'); // 将空段落转换回换行
        }
        
        // 新增：处理下载成功消息并生成下载链接
        const downloadSuccessPattern = /🎉 操作完成！Jira 工单 (.*?) 的文件已成功下载为 '(.*?)'。你可以通过新指令要求我分析这个文件。/;
        const match = formatted.match(downloadSuccessPattern);

        if (match) {
            const jiraTicket = match[1];
            const filename = match[2];
            const downloadUrl = `/api/download/${filename}`;
            const downloadLink = `<a href="${downloadUrl}" target="_blank" rel="noopener noreferrer" class="download-link">${filename}</a>`;
            formatted = `🎉 操作完成！Jira 工单 ${jiraTicket} 的文件已成功下载为 ${downloadLink}。你可以通过新指令要求我分析这个文件。`;
        }

        return formatted;
    }
    
    // 模拟的机器人预设回复（当API不可用时使用）
    const botResponses = {
        'submit': {
            trigger: ['提交', '申请', '发起', '创建'],
            response: '✅ 已收到你的提交请求。我将为你处理以下操作：\n1. 根据你的描述生成SQL\n2. 填写提交表单\n3. 使用提供的Jira和审批人信息提交申请\n\n请在浏览器窗口中确认操作。'
        },
        'status': {
            trigger: ['状态', '进度', 'status', '查询'],
            response: '📊 正在查询工单状态...\n\n已找到工单信息：\n- 申请状态: 已审批\n- 执行状态: 执行成功\n\n✅ 数据查询结果文件已准备就绪，正在下载到本地。'
        },
        'analyze': {
            trigger: ['分析', '报告', 'analyze', '查看'],
            response: '📈 数据分析完成！结果如下：\n\n| 排名 | 客户名称 | 数据量 |\n|------|----------|--------|\n| 1    | 客户A    | 1280   |\n| 2    | 客户B    | 940    |\n| 3    | 客户C    | 730    |\n| 4    | 客户D    | 450    |\n| 5    | 客户E    | 320    |\n\n报告已保存到文件。'
        },
        'help': {
            trigger: ['帮助', 'help', '怎么用', '如何'],
            response: '我是Veeva pegasus数据查询分析助手，可以帮你：\n\n1. 提交数据查询申请\n   - 需要提供：Jira工单号、审批人、查询描述\n\n2. 查询工单状态并下载结果\n   - 只需提供Jira工单号\n\n3. 分析已下载的数据文件\n   - 提供文件路径即可\n\n你可以直接在聊天框中输入请求，或使用顶部导航切换到表单和结果页面。'
        }
    };
    
    // 生成回复（当API不可用时使用）
    function generateResponse(message) {
        // 检测消息类型并给出相应回复
        for (const [type, config] of Object.entries(botResponses)) {
            if (config.trigger.some(keyword => message.toLowerCase().includes(keyword))) {
                // 对于提交请求，添加自定义数据（从消息中提取）
                if (type === 'submit') {
                    // 尝试提取Jira号
                    const jiraMatch = message.match(/[A-Z]+-\d+/);
                    const jiraNumber = jiraMatch ? jiraMatch[0] : 'ORI-XXXXX';
                    
                    // 尝试提取审批人
                    const approverMatch = message.match(/找\s*([a-zA-Z.]+)/);
                    const approver = approverMatch ? approverMatch[1] : 'unknown';
                    
                    return config.response.replace('你的提交请求', 
                        `你的提交请求 (Jira: ${jiraNumber}, 审批人: ${approver})`);
                }
                
                return config.response;
            }
        }
        
        // 默认回复
        return '我理解你的意思了。请问你需要我帮你提交数据查询申请、查询工单状态，还是分析数据文件？';
    }
    
    // 显示"正在输入"状态
    function showTypingIndicator() {
        const typingDiv = document.createElement('div');
        typingDiv.className = 'message bot typing-indicator';
        typingDiv.id = 'typingIndicator';
        
        const avatarDiv = document.createElement('div');
        avatarDiv.className = 'avatar';
        
        const avatarImg = document.createElement('img');
        avatarImg.src = 'assets/img/bot-avatar.png';
        avatarDiv.appendChild(avatarImg);
        
        const contentDiv = document.createElement('div');
        contentDiv.className = 'message-content';
        contentDiv.innerHTML = '<div class="typing-dots"><span></span><span></span><span></span></div>';
        
        typingDiv.appendChild(avatarDiv);
        typingDiv.appendChild(contentDiv);
        
        chatMessages.appendChild(typingDiv);
        scrollToBottom();
    }
    
    // 隐藏"正在输入"状态
    function hideTypingIndicator() {
        const indicator = document.getElementById('typingIndicator');
        if (indicator) {
            indicator.remove();
        }
    }
    
    // 滚动到最新消息
    function scrollToBottom() {
        // 检查用户是否已经滚动到接近底部 (+10像素的容差)
        const isScrolledToBottom = chatMessages.scrollHeight - chatMessages.clientHeight <= chatMessages.scrollTop + 10;
        if (isScrolledToBottom) {
            chatMessages.scrollTop = chatMessages.scrollHeight;
        }
    }

    function debouncedScrollToBottom() {
        if (scrollTimeout) {
            clearTimeout(scrollTimeout);
        }
        scrollTimeout = setTimeout(() => {
            scrollToBottom();
        }, SCROLL_DEBOUNCE_TIME);
    }
    
    // 监听任务更新（SSE）
    function listenForTaskUpdates(taskId) {
        console.log(`正在监听任务 ${taskId} 的实时更新...`);
        // 使用相对路径连接SSE端点
        const eventSource = new EventSource(`/api/task-stream/${taskId}`);

        eventSource.onmessage = function(event) {
            const data = JSON.parse(event.data);
            console.log('接收到SSE消息:', data);
            
            // 移除"正在输入"状态
            hideTypingIndicator();
            
            // 将实时消息添加到聊天窗口
            // 根据SSE消息的结构，我们可能需要调整如何显示消息
            let displayMessage = data.message;
            if (data.status === 'completed' && data.data && data.data.result) {
                displayMessage += `\n\n最终结果: ${data.data.result}`;
                if (data.data.file) {
                    displayMessage += `\n文件: ${data.data.file}`;
                }
            } else if (data.status === 'failed') {
                displayMessage += `\n\n处理失败: ${data.message}`;
            }

            addMessage(`🤖 ${displayMessage}`, 'bot');
            
            // 如果任务完成或失败，关闭SSE连接
            if (data.status === 'completed' || data.status === 'failed') {
                eventSource.close();
                console.log(`任务 ${taskId} 已完成或失败，SSE连接已关闭。`);
            }
        };

        eventSource.onerror = function(error) {
            console.error('SSE连接出错:', error);
            eventSource.close();
            hideTypingIndicator();
            addMessage("与服务器的实时连接已中断。", 'bot');
        };

        eventSource.onopen = function() {
            console.log(`已成功连接到任务 ${taskId} 的SSE流。`);
        };
    }
    
    // 初始化
    init();
})(); 