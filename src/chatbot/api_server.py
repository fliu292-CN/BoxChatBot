import asyncio
import os
import sys
import json
import tempfile
import uuid
import re
import io # 导入io模块
from typing import List, Dict, Any, Optional
from pathlib import Path
from pydantic import BaseModel

import uvicorn
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, BackgroundTasks
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.responses import StreamingResponse
from starlette.background import BackgroundTask

# 导入Playwright相关类型和函数 (不再需要直接在这里导入Playwright, Browser等)
# from playwright.async_api import async_playwright, Playwright, Browser, BrowserContext, Page

# 导入agent_1.py中的核心功能
from dotenv import load_dotenv
# 使用相对路径导入模块
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from agent_1 import (
    generate_sql_query, 
    _analyze_excel_file_with_gemini,
    _perform_browser_action,
    fill_form_and_submit,
    _find_status_and_download_if_ready,
    close_browser_session, # 导入新的关闭会话函数
    invoke_agent_with_message # 导入新的Agent调用函数
)

# 加载环境变量
load_dotenv()

app = FastAPI(
    title="Veeva pegasus数据查询分析助手API",
    description="用于Veeva数据查询、状态查询和数据分析的API接口",
    version="1.0.0",
)

# 配置CORS，允许前端访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境应该指定具体的前端域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 创建临时文件保存目录
TEMP_DIR = Path("./temp_files")
TEMP_DIR.mkdir(exist_ok=True)

# 获取项目根目录路径
ROOT_DIR = Path(os.path.dirname(os.path.abspath(__file__))) / "../.."
FRONTEND_DIR = ROOT_DIR / "frontend"

# 如果frontend目录不存在，则创建一个提示信息
if not FRONTEND_DIR.exists():
    print(f"警告: 未找到前端目录: {FRONTEND_DIR}，服务器将只提供API服务。")

# 数据模型
class DataQueryRequest(BaseModel):
    jira_ticket: str
    approver: str
    query_description: str
    
class StatusQueryRequest(BaseModel):
    jira_ticket: str
    
class AnalysisResult(BaseModel):
    success: bool
    message: str
    data: Optional[List[Dict[str, Any]]] = None

# 用于存储进行中的任务状态
tasks_status = {}

# 用于存储每个任务的事件流 (SSE)
task_event_streams: Dict[str, asyncio.Queue] = {}

# Playwright 全局实例，用于保持登录会话 (这些变量不再需要，因为会话管理已移至agent_1.py)
# _global_playwright: Optional[Playwright] = None
# _global_browser: Optional[Browser] = None
# _global_context: Optional[BrowserContext] = None
# _global_page: Optional[Page] = None

# 辅助函数：更新任务状态并发送SSE事件
def update_task_status(task_id: str, status: str, message: str, data: dict = None):
    tasks_status[task_id] = {
        "status": status,  # 可能的值: pending, processing, completed, failed
        "message": message,
        "data": data or {}
    }
    # 将消息推送到对应的事件流
    if task_id in task_event_streams:
        # 使用put_nowait以避免阻塞，如果队列已满则会报错，但对于日志流通常不会发生
        try:
            task_event_streams[task_id].put_nowait(json.dumps({"status": status, "message": message, "data": data}))
        except asyncio.QueueFull:
            print(f"警告: 任务 {task_id} 的事件队列已满，消息丢失。")

# 辅助函数：获取任务状态
def get_task_status(task_id: str):
    return tasks_status.get(task_id, {
        "status": "unknown",
        "message": "未找到任务信息",
        "data": {}
    })

# 定义一个自定义的stdout类，用于捕获print输出并推送到SSE
class StdoutRedirector(io.StringIO):
    def __init__(self, task_id: str):
        super().__init__()
        self.task_id = task_id
        self.buffer = []

    def write(self, s):
        # 阻止写入控制台，只捕获到内部buffer
        self.buffer.append(s)
        if '\n' in s:
            self.flush()

    def flush(self):
        if self.buffer:
            line = ''.join(self.buffer).strip()
            if line:
                # 调用update_task_status将捕获到的日志发送到SSE
                update_task_status(self.task_id, "processing", f"后端日志: {line}")
            self.buffer = []

# SSE 异步生成器函数
async def event_generator(task_id: str):
    if task_id not in task_event_streams:
        task_event_streams[task_id] = asyncio.Queue()
    
    try:
        while True:
            # 等待新消息，并发送给客户端
            message = await task_event_streams[task_id].get()
            yield f"data: {message}\n\n"
            # 当任务完成或失败时，可以考虑关闭流，这里简单判断completed或failed状态
            current_status = tasks_status.get(task_id, {}).get("status")
            if current_status in ["completed", "failed"]:
                # 可以在这里发送一个结束信号，例如一个特殊的事件类型，然后break
                # yield "event: end\ndata: {}\n\n"
                break
    except asyncio.CancelledError:
        print(f"任务 {task_id} 的事件流已取消。")
    finally:
        # 当客户端断开连接时，清理队列（可选，取决于需求）
        if task_id in task_event_streams:
            # 清理队列，防止内存泄漏，但要确保所有消息都已发送
            pass # 暂时不做清理，让消息可以被其他监听者获取

# FastAPI 启动事件：执行一次性登录 (此段代码将被移除，登录逻辑已移至agent_1.py)
# @app.on_event("startup")
# async def startup_event():
#     global _global_playwright, _global_browser, _global_context, _global_page
#     print("🚀 FastAPI 启动中... 正在尝试登录 Veeva 系统以建立持久化会话。")
#     try:
#         _global_playwright = await async_playwright().start()
#         username = os.getenv("VEEVA_USERNAME")
#         password = os.getenv("VEEVA_PASSWORD")
#         okta_push = os.getenv("OKTA_PUSH")

#         if not username or not password:
#             print("❌ 登录失败: VEEVA_USERNAME 或 VEEVA_PASSWORD 环境变量未设置。")
#             # 如果无法登录，仍然允许API服务启动，但浏览器相关功能会受限
#             return

#         # 执行登录并获取持久化的 page, context, browser
#         _global_page, _global_context, _global_browser = await _login_pegasus(_global_playwright, okta_push, username, password)
#         print("✅ Veeva 系统登录成功，持久化浏览器会话已建立。")
#     except Exception as e:
#         import traceback
#         traceback.print_exc()
#         print(f"❌ FastAPI 启动登录过程中发生错误: {e}")
#         # 确保在失败时清理资源
#         if _global_browser:
#             await _global_browser.close()
#         if _global_playwright:
#             await _global_playwright.stop()
#         _global_playwright = None
#         _global_browser = None
#         _global_context = None
#         _global_page = None

# FastAPI 关闭事件：关闭浏览器
@app.on_event("shutdown")
async def shutdown_event():
    print("👋 FastAPI 关闭中... 正在关闭浏览器会话。")
    await close_browser_session()
    print("🚪 浏览器已关闭。")

# API路由

@app.get("/", response_class=HTMLResponse)
async def root():
    # 如果前端目录存在，则提供index.html
    index_path = FRONTEND_DIR / "index.html"
    if index_path.exists():
        with open(index_path, "r") as file:
            return file.read()
    else:
        # 否则返回API信息页面
        return """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Veeva pegasus数据查询分析助手API</title>
            <meta charset="utf-8">
            <style>
                body { font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }
                h1 { color: #1f5dd3; }
                a { color: #1f5dd3; text-decoration: none; }
                a:hover { text-decoration: underline; }
                .container { background: #f5f7fa; padding: 20px; border-radius: 8px; }
                .api-link { margin-top: 20px; background: #e3f2fd; padding: 10px; border-radius: 4px; }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>Veeva pegasus数据查询分析助手API</h1>
                <p>API服务已成功启动！但未找到前端文件。</p>
                <p>请确保前端文件位于正确的路径: <code>frontend/index.html</code></p>
                <div class="api-link">
                    <p>您可以访问以下链接了解更多:</p>
                    <ul>
                        <li><a href="/api/docs">API文档</a></li>
                        <li><a href="/openapi.json">OpenAPI规范</a></li>
                    </ul>
                </div>
            </div>
        </body>
        </html>
        """

@app.post("/api/submit-query", summary="提交数据查询申请")
async def submit_query(data: DataQueryRequest, background_tasks: BackgroundTasks):
    try:
        # 生成唯一任务ID
        task_id = str(uuid.uuid4())
        
        # 更新任务状态为处理中
        update_task_status(task_id, "processing", "正在处理数据查询请求")
        
        # 生成SQL查询（不需要使用后台任务，这一步很快）
        sql_query = generate_sql_query(data.query_description)
        
        # 在后台执行浏览器操作（这步耗时较长）
        background_tasks.add_task(
            process_query_submission,
            task_id=task_id,
            jira_ticket=data.jira_ticket,
            approver=data.approver,
            sql_query=sql_query,
            query_description=data.query_description
        )
        
        return {
            "success": True,
            "message": "数据查询请求已接收，正在处理",
            "task_id": task_id,
            "sql_query": sql_query
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "message": f"提交失败: {str(e)}"
        }

# 后台处理提交查询的任务
def process_query_submission(task_id: str, jira_ticket: str, approver: str, sql_query: str, query_description: str):
    # 重定向stdout，捕获print输出
    old_stdout = sys.stdout
    sys.stdout = StdoutRedirector(task_id)
    
    try:
        update_task_status(task_id, "processing", "SQL已生成，正在执行表单提交...")
        
        # 执行表单提交操作，传入全局的浏览器会话  <- 这行注释是旧的，即将被移除或修改
        result = _perform_browser_action(
            fill_form_and_submit,
            # page=_global_page,      # 传入全局page  <- 这些行将被移除
            # context=_global_context, # 传入全局context
            # browser=_global_browser,  # 传入全局browser
            approver=approver,
            jira_ticket=jira_ticket,
            reason=f"为Jira工单 {jira_ticket} 查询数据",
            sql_query=sql_query
        )
        
        update_task_status(
            task_id, 
            "completed", 
            "数据查询请求已成功提交", 
            {"result": result}
        )
    except Exception as e:
        update_task_status(task_id, "failed", f"提交失败: {str(e)}")
    finally:
        # 恢复stdout
        sys.stdout = old_stdout

@app.get("/api/task-status/{task_id}", summary="获取任务状态")
async def check_task_status(task_id: str):
    status = get_task_status(task_id)
    return status

# 新增SSE端点用于实时推送任务日志
@app.get("/api/task-stream/{task_id}", summary="获取任务实时日志流 (SSE)")
async def task_stream(task_id: str):
    return StreamingResponse(event_generator(task_id), media_type="text/event-stream")

@app.post("/api/check-jira-status", summary="查询工单状态并下载结果")
async def check_jira_status(data: StatusQueryRequest, background_tasks: BackgroundTasks):
    try:
        # 生成唯一任务ID
        task_id = str(uuid.uuid4())
        
        # 更新任务状态为处理中
        update_task_status(task_id, "processing", f"正在查询工单 {data.jira_ticket} 的状态")
        
        # 在后台执行状态查询和下载操作
        background_tasks.add_task(
            process_jira_status_check,
            task_id=task_id,
            jira_ticket=data.jira_ticket
        )
        
        return {
            "success": True,
            "message": "状态查询请求已接收，正在处理",
            "task_id": task_id
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"success": False, "message": f"查询失败: {str(e)}"}, status_code=500)

# 后台处理工单状态查询的任务
def process_jira_status_check(task_id: str, jira_ticket: str):
    # 重定向stdout，捕获print输出
    old_stdout = sys.stdout
    sys.stdout = StdoutRedirector(task_id)

    try:
        update_task_status(task_id, "processing", "正在查询工单状态并尝试下载...")
        
        # 执行状态查询和下载操作，不再传入全局的浏览器会话，由_perform_browser_action自行管理
        result = _perform_browser_action(
            _find_status_and_download_if_ready,
            jira_ticket=jira_ticket
        )
        
        # 检查结果中是否包含错误信息
        if "错误:" in result or "发生严重错误" in result or "ValueError:" in result:
            update_task_status(task_id, "failed", f"查询失败: {result}")
        elif "成功下载" in result:
            # 尝试提取文件名
            file_match = re.search(r"'([^']+\.xlsx)'", result)
            downloaded_file = file_match.group(1) if file_match else None
            
            update_task_status(
                task_id, 
                "completed", 
                "工单状态查询完成，文件已下载", 
                {
                    "result": result,
                    "file": downloaded_file,
                    "status": "executed",
                    "download_url": f"/api/download/{downloaded_file}" if downloaded_file else None
                }
            )
        else:
            update_task_status(
                task_id, 
                "completed", 
                "工单状态查询完成，但文件未准备好或未下载", 
                {"result": result, "status": "no_file"}
            )
    except Exception as e:
        update_task_status(task_id, "failed", f"查询失败: {str(e)}")
    finally:
        # 恢复stdout
        sys.stdout = old_stdout

@app.get("/api/download/{filename}", summary="下载文件")
async def download_file(filename: str):
    try:
        file_path = Path(f"./{filename}")
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="文件未找到")
        
        return FileResponse(
            path=file_path, 
            filename=filename,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"下载失败: {str(e)}")

@app.post("/api/analyze-file", summary="分析Excel数据文件")
async def analyze_file(file: UploadFile = File(...)):
    try:
        # 保存上传的文件
        temp_file = TEMP_DIR / f"{uuid.uuid4()}_{file.filename}"
        with open(temp_file, "wb") as f:
            content = await file.read()
            f.write(content)
        
        # 分析文件
        analysis_result = _analyze_excel_file_with_gemini(str(temp_file))
        
        # 提取分析结果中的表格数据
        import re
        data = []
        
        # 尝试解析表格数据
        table_pattern = r"\|\s*(\d+)\s*\|\s*([^|]+)\s*\|\s*(\d+)\s*\|"
        matches = re.findall(table_pattern, analysis_result)
        
        for match in matches:
            try:
                rank = int(match[0].strip())
                name = match[1].strip()
                count = int(match[2].strip())
                data.append({"rank": rank, "name": name, "count": count})
            except:
                continue
        
        return {
            "success": True,
            "message": "文件分析完成",
            "result": analysis_result,
            "data": data
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"分析失败: {str(e)}"
        }
    finally:
        # 清理临时文件
        try:
            if temp_file.exists():
                temp_file.unlink()
        except:
            pass

@app.post("/api/chat", summary="与聊天机器人对话")
async def chat_with_bot(background_tasks: BackgroundTasks, message: str = Form(...)):
    task_id = str(uuid.uuid4())
    
    try:
        update_task_status(task_id, "processing", "正在处理您的消息...")
        
        # 使用BackgroundTasks来异步调用Agent，避免阻塞主线程
        background_tasks.add_task(
            _process_chat_message_with_agent, 
            task_id=task_id, 
            message=message
        )
        
        return JSONResponse({
            "success": True,
            "response": "您的请求已收到，正在处理中，请稍候。",
            "task_id": task_id,
            "action": "agent_process"
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        update_task_status(task_id, "failed", f"消息处理失败: {str(e)}")
        return JSONResponse({"success": False, "message": f"处理失败: {str(e)}"})

async def _process_chat_message_with_agent(task_id: str, message: str):
    # 重定向stdout，捕获print输出
    old_stdout = sys.stdout
    sys.stdout = StdoutRedirector(task_id)
    try:
        print(f"🤖 正在通过 LangChain Agent 处理消息: {message}")
        agent_response = await invoke_agent_with_message(message)
        
        if "错误:" in agent_response or "发生严重错误" in agent_response:
            update_task_status(task_id, "failed", f"Agent 处理失败: {agent_response}")
        else:
            update_task_status(task_id, "completed", "Agent 处理完成", {"response": agent_response})
    except Exception as e:
        update_task_status(task_id, "failed", f"Agent 处理过程中发生异常: {str(e)}")
    finally:
        # 恢复stdout
        sys.stdout = old_stdout

# API文档自定义
@app.get("/api/docs", include_in_schema=False)
async def custom_swagger_ui_html():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Veeva pegasus数据查询分析助手API文档</title>
        <meta charset="utf-8">
        <script type="module" src="https://unpkg.com/rapidoc/dist/rapidoc-min.js"></script>
    </head>
    <body>
        <rapi-doc 
            spec-url="/openapi.json"
            theme="light"
            primary-color="#1f5dd3"
            render-style="view"
            heading-text="Veeva pegasus数据查询分析助手API文档"
        ></rapi-doc>
    </body>
    </html>
    """

# 创建一个自定义的StaticFiles类，添加禁用缓存的响应头
from starlette.responses import Response
from starlette.types import Scope

class NoCacheStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        # 添加禁用缓存的响应头
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

# 最后挂载静态文件，这样它不会覆盖上面定义的路由
if FRONTEND_DIR.exists():
    app.mount("/", NoCacheStaticFiles(directory=FRONTEND_DIR, html=True), name="static")
    print(f"前端静态文件已挂载，路径: {FRONTEND_DIR}，已禁用缓存")

# 添加文件下载端点
@app.get("/download-report/{filename}")
async def download_report(filename: str):
    file_path = os.path.join("./src/chatbot", filename)  # 假设文件在 src/chatbot 目录下
    if os.path.exists(file_path):
        return FileResponse(path=file_path, filename=filename, media_type="application/octet-stream")
    else:
        raise HTTPException(status_code=404, detail="File not found")

if __name__ == "__main__":
    # 确保不使用uvicorn的热重载，以维持Playwright会话的持久性
    print("🚀 API服务器启动中... 访问 http://localhost:8000/ 查看前端界面")
    uvicorn.run(app, host="0.0.0.0", port=8000) 