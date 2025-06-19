// 等待DOM加载完成
document.addEventListener('DOMContentLoaded', function() {
    // 获取所有标签和内容区域
    const tabLinks = document.querySelectorAll('nav a.tab-link');
    const tabContents = document.querySelectorAll('.tab-content');
    
    console.log('找到', tabLinks.length, '个标签按钮和', tabContents.length, '个内容区域');
    
    // 为每个标签添加点击事件
    tabLinks.forEach(link => {
        const targetId = link.getAttribute('data-tab');
        console.log('为标签绑定事件:', targetId);
        
        // 添加新的事件监听器
        link.addEventListener('click', handleTabClick);
    });
    
    // Tab点击处理函数
    function handleTabClick(e) {
        e.preventDefault();
        e.stopPropagation(); // 阻止事件冒泡
        
        // 获取目标标签ID
        const targetId = this.getAttribute('data-tab');
        console.log('点击了标签:', targetId);
        
        // 移除所有tab的active类
        tabLinks.forEach(tab => tab.classList.remove('active'));
        tabContents.forEach(content => content.classList.remove('active'));
        
        // 为当前点击的tab和对应内容添加active类
        this.classList.add('active');
        const targetContent = document.getElementById(targetId);
        if (targetContent) {
            targetContent.classList.add('active');
            console.log('激活内容区域:', targetId);
        } else {
            console.error('找不到对应的内容区域:', targetId);
        }
    }
    
    // 添加示例头像
    addPlaceholderImages();
    
    // 初始调整高度
    adjustChatContainerHeight();
});

// 添加占位图片
function addPlaceholderImages() {
    // 如果图片不存在则使用占位图
    const botAvatar = document.querySelector('.message.bot .avatar img');
    if (botAvatar && !imageExists(botAvatar.src)) {
        botAvatar.src = 'https://via.placeholder.com/40?text=Bot';
    }
    
    // 为logo添加占位图
    const logoImg = document.querySelector('.logo img');
    if (logoImg && !imageExists(logoImg.src)) {
        logoImg.src = 'https://via.placeholder.com/40?text=V';
    }
}

// 检查图片是否存在
function imageExists(url) {
    const http = new XMLHttpRequest();
    http.open('HEAD', url, false);
    try {
        http.send();
        return http.status !== 404;
    } catch(e) {
        return false;
    }
}

// 显示通知消息
function showNotification(message, type = 'info') {
    // 创建通知元素
    const notification = document.createElement('div');
    notification.className = `notification ${type}`;
    notification.textContent = message;
    
    // 添加到页面
    document.body.appendChild(notification);
    
    // 动画显示
    setTimeout(() => {
        notification.classList.add('show');
    }, 10);
    
    // 3秒后隐藏并移除
    setTimeout(() => {
        notification.classList.remove('show');
        setTimeout(() => {
            document.body.removeChild(notification);
        }, 300);
    }, 3000);
}

// 在窗口大小改变时调整聊天容器高度
window.addEventListener('resize', function() {
    adjustChatContainerHeight();
});

// 调整聊天容器高度
function adjustChatContainerHeight() {
    const chatContainer = document.querySelector('.chat-container');
    if (chatContainer) {
        // 根据窗口高度动态调整
        const windowHeight = window.innerHeight;
        const headerHeight = document.querySelector('header').offsetHeight;
        const footerHeight = document.querySelector('footer').offsetHeight;
        const padding = 40; // 页面padding总和
        
        const availableHeight = windowHeight - headerHeight - footerHeight - padding;
        const minHeight = 400; // 最小高度
        
        chatContainer.style.height = Math.max(availableHeight, minHeight) + 'px';
    }
}

// 导出一些公共方法供其他模块使用
window.appUtils = {
    showNotification,
    adjustChatContainerHeight
}; 