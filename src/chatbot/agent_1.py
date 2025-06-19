import os
import re
import json
from typing import Tuple, Optional
from pathlib import Path

import httpx
import pandas as pd
import matplotlib
matplotlib.use('Agg') # Use the Agg backend for non-interactive plotting
import matplotlib.pyplot as plt
import io
from urllib.parse import urljoin
from dotenv import load_dotenv
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain.tools import tool
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from playwright.async_api import (Browser, BrowserContext, Locator, Page,
                                  expect, async_playwright, Playwright)
import asyncio # 新增或确保存在

# Global variables to hold the Playwright instances
_playwright_instance: Optional[Playwright] = None
_browser_instance: Optional[Browser] = None
_context_instance: Optional[BrowserContext] = None
_app_page_instance: Optional[Page] = None

# 定义会话状态文件路径
SESSION_STATE_PATH = Path("./playwright_session_state.json")

from jira import JIRA

# --- 模块 0: Jira 功能集成 ---
# 初始化 Jira 客户端
try:
    jira_token = os.getenv("JIRA_TOKEN")
    jira_server = os.getenv("JIRA_SERVER", "https://jira.veevadev.com/")
    jiraOptions = {'server': jira_server}
    if jira_token:
        jira = JIRA(options=jiraOptions, token_auth=jira_token)
        print("✅ Jira 客户端初始化成功。")
    else:
        jira = None
        print("⚠️ 警告: JIRA_TOKEN 环境变量未设置。Jira 相关功能将不可用。")
except Exception as e:
    jira = None
    print(f"❌ 错误: Jira 客户端初始化失败: {e}")

def add_attachment(issue_key: str, file_path: str, replace_existing: bool = True) -> bool:
    """
    为指定的Jira issue添加附件。

    Args:
        issue_key (str): Jira issue的key，例如 'ORI-120579'
        file_path (str): 要上传的文件路径
        replace_existing (bool): 如果存在同名附件是否替换，默认True

    Returns:
        bool: 上传成功返回True，失败返回False
    """
    if not jira:
        print("❌ Jira 功能不可用，无法上传附件。")
        return False
    try:
        issue = jira.issue(issue_key)
        print(f"   -> 找到Jira issue: {issue.key} ({issue.fields.summary})")

        if not os.path.exists(file_path):
            print(f"   -> ❌ 错误: 文件不存在 - {file_path}")
            return False

        filename = os.path.basename(file_path)

        if replace_existing:
            for attachment in issue.fields.attachment or []:
                if attachment.filename == filename:
                    print(f"   -> 发现同名附件，正在删除: {filename}")
                    jira.delete_attachment(attachment.id)
                    break

        print(f"   -> 正在上传新附件: {filename}...")
        attachment = jira.add_attachment(issue=issue, attachment=file_path)
        print(f"   -> ✅ 附件上传成功: {attachment.filename}")
        return True

    except Exception as e:
        print(f"   -> ❌ 上传附件到Jira时出错: {e}")
        return False

async def get_browser_session() -> Tuple[Page, BrowserContext, Browser]:
    global _playwright_instance, _browser_instance, _context_instance, _app_page_instance

    async def is_session_truly_connected() -> bool:
        try:
            # Check if all global instances are not None
            if not all([_playwright_instance, _browser_instance, _context_instance, _app_page_instance]):
                print("DEBUG: One or more global Playwright instances are None. Cannot reuse session.")
                # Log which specific instance is None
                if _playwright_instance is None: print("DEBUG: _playwright_instance is None")
                if _browser_instance is None: print("DEBUG: _browser_instance is None")
                if _context_instance is None: print("DEBUG: _context_instance is None")
                if _app_page_instance is None: print("DEBUG: _app_page_instance is None")
                return False

            # Check if they are indeed Playwright objects and are connected
            is_playwright_instance = isinstance(_playwright_instance, Playwright)
            is_browser_instance = isinstance(_browser_instance, Browser)
            is_context_instance = isinstance(_context_instance, BrowserContext)
            is_page_instance = isinstance(_app_page_instance, Page)

            browser_connected = False
            page_connected = False
            page_functional = False # New flag for page functionality

            if is_browser_instance: 
                try:
                    browser_connected = _browser_instance.is_connected()
                    print(f"DEBUG: _browser_instance.is_connected() returned: {browser_connected}")
                except Exception as e:
                    print(f"❌ Error calling _browser_instance.is_connected(): {e}")
                    browser_connected = False
            else:
                print(f"DEBUG: _browser_instance is not a Browser instance (Type: {type(_browser_instance)}).")

            if is_page_instance: 
                try:
                    # Removed direct call to _app_page_instance.is_connected() due to AttributeError
                    # Relying on page_functional check below for actual page health
                    page_connected = True # Assume connected if it's a Page instance

                    # Additional check: Try a simple operation to ensure the page is functional
                    try:
                        await _app_page_instance.evaluate("1 + 1") # Simple JS evaluation to check functionality
                        page_functional = True
                        print("DEBUG: _app_page_instance is functional.")
                    except Exception as e:
                        print(f"❌ Error evaluating simple JS on _app_page_instance: {e}. Page not functional.")
                        page_functional = False
                except Exception as e:
                    # This block now primarily catches errors from the evaluate call itself, not is_connected()
                    print(f"❌ Error during page functionality check (evaluating 1+1): {e}")
                    page_functional = False # Mark as not functional if any error occurs here
            else:
                print(f"DEBUG: _app_page_instance is not a Page instance (Type: {type(_app_page_instance)}). Marking as not functional.")
                page_functional = False

            if (is_playwright_instance and
                is_browser_instance and
                is_context_instance and
                is_page_instance and
                browser_connected and
                page_functional): # Rely solely on page_functional for page's validity
                print("DEBUG: All Playwright instances are valid and connected.")
                return True
            else:
                print("DEBUG: Playwright instances are not of expected types or reported as not connected (Detail above). Force re-initialization.")
                return False
        except Exception as e:
            # Catch any exception during the connection check, including AttributeError
            print(f"❌ Error during browser session validation (is_session_truly_connected): {e}")
            return False

    if await is_session_truly_connected():
        print("💡 Reusing existing browser session.")
        return _app_page_instance, _context_instance, _browser_instance
    else:
        print("⚠️ Existing browser session is invalid or not fully connected, re-initializing.")
        # Ensure full cleanup before re-initialization
        await close_browser_session()

    # Re-initialization logic
    # 尝试从保存的状态加载，而不是重新登录
    if SESSION_STATE_PATH.exists():
        print("Attempting to load browser session from saved state...")
        try:
            _playwright_instance = await async_playwright().start()
            _browser_instance = await _playwright_instance.chromium.launch(headless=False)
            _context_instance = await _browser_instance.new_context(storage_state=SESSION_STATE_PATH)
            _app_page_instance = await _context_instance.new_page()
            
            # NEW: Navigate to the expected application URL to ensure the page is active and ready
            veeva_initial_logged_in_page_url = 'https://pegasus-prod.veevasfa.com/environment/list'
            print(f"DEBUG: Navigating to {veeva_initial_logged_in_page_url} after loading session state.")
            await _app_page_instance.goto(veeva_initial_logged_in_page_url, timeout=60000)
            await _app_page_instance.wait_for_load_state('networkidle', timeout=60000)
            
            # After loading, immediately validate the session
            if await is_session_truly_connected(): # Re-validate loaded session
                print("✅ Browser session loaded from saved state and validated.")
                return _app_page_instance, _context_instance, _browser_instance
            else:
                print("❌ Loaded browser session is invalid or not functional, falling back to full login.")
                await close_browser_session() # Clean up invalid loaded session
                # Fall through to full login
        except Exception as e:
            print(f"❌ Failed to load browser session from saved state: {e}. Falling back to full login.")
            # Clean up potentially partially initialized instances
            await close_browser_session()
            # Do not re-raise here, let it fall through to full login

    username = os.getenv("VEEVA_USERNAME")
    password = os.getenv("VEEVA_PASSWORD")
    okta_push = os.getenv("OKTA_PUSH")

    if not username or not password:
        raise ValueError("错误：VEEVA_USERNAME 或 VEEVA_PASSWORD 环境变量未设置。")

    print("🚀 Initializing new browser session and logging in...")
    try:
        _playwright_instance = await async_playwright().start()
        _app_page_instance, _context_instance, _browser_instance = await _login_pegasus(_playwright_instance, okta_push, username, password)
        
        # 在成功登录后保存会话状态
        await _context_instance.storage_state(path=SESSION_STATE_PATH)
        print(f"✅ New browser session initialized and logged in. Session state saved to {SESSION_STATE_PATH}.")
        
        return _app_page_instance, _context_instance, _browser_instance
    except Exception as e:
        print(f"❌ Failed to initialize new browser session or login: {e}")
        # Ensure cleanup if login fails
        await close_browser_session() # This is critical to reset globals on failed login
        raise # Re-raise the exception after cleanup

async def close_browser_session():
    global _playwright_instance, _browser_instance, _context_instance, _app_page_instance
    print("🚪 Closing browser session...")
    try:
        if _browser_instance and _browser_instance.is_connected():
            print("   -> Browser is connected, closing.")
            await _browser_instance.close()
        elif _browser_instance:
            print("   -> Browser instance exists but not connected, no explicit close needed.")
        if _playwright_instance:
            print("   -> Stopping Playwright instance.")
            await _playwright_instance.stop()
    except Exception as e:
        print(f"❌ Error during browser session close: {e}")
    finally:
        # Always ensure global instances are nulled out
        _playwright_instance = None
        _browser_instance = None
        _context_instance = None
        _app_page_instance = None
        print("🚪 Browser session globals cleared.")

# --- 模块 1: 核心业务逻辑 ---
async def _login_pegasus(p: Playwright, okta_push: str, username: str, password: str):
    if okta_push and okta_push.lower() == 'true':
       return await _login_and_get_app_page(p,username,password)
    else:
        return await _login_and_get_app_page_no_okta_push(p,username,password)


async def _login_and_get_app_page_no_okta_push(p: Playwright, username: str, password: str) -> Tuple[Page, BrowserContext, Browser]:
    """
    使用 Playwright 登录 Veeva 系统并返回页面、上下文和浏览器实例。
    此函数处理通过 Okta 的登录流程，并假定用户名已预先填充或由 SSO 处理。
    它会填写密码并处理后续的验证步骤。
    Returns: 一个元组，包含成功登录后的 Page, BrowserContext, 和 Browser 对象。
    """
    print("🚀 开始登录流程...")
    # 以非无头模式启动浏览器，便于调试
    browser = await p.chromium.launch(headless=False, timeout=60000)
    context: BrowserContext = await browser.new_context()
    app_page: Page = await context.new_page()

    veeva_initial_login_url = 'https://pegasus-prod.veevasfa.com/login'
    veeva_initial_logged_in_page_url = 'https://pegasus-prod.veevasfa.com/environment/list'

    try:
        await app_page.goto(veeva_initial_login_url, timeout=60000)
        okta_login_button_selector = 'text="Okta登陆CSMC系统"'
        # 等待按钮可见
        await app_page.wait_for_selector(okta_login_button_selector, state='visible', timeout=30000)
        await app_page.click(okta_login_button_selector)
        try:
            # 最佳实践：先显式检查元素是否可见，再执行操作。
            # 这比直接尝试 .fill() 更能避免复杂的等待问题。
            username_locator = app_page.locator('input[name="identifier"]')
            if await username_locator.is_visible(timeout=1000):
                await username_locator.fill(username)

        except TimeoutError:
            print("   -> 未在5秒内找到用户名输入框，跳过此步骤继续执行。")

        # 定位密码输入框并填充
        password_input_locator = app_page.locator('input[name="credentials.passcode"]')
        await password_input_locator.wait_for(state="visible", timeout=60000)
        await password_input_locator.fill(password)

        # 定位并点击"验证"按钮
        verify_button_locator = app_page.get_by_role("button", name="Verify").or_(app_page.get_by_role("button", name="验证"))
        await verify_button_locator.click(timeout=30000)

        # 等待登录后跳转到目标 URL
        await app_page.wait_for_url(veeva_initial_logged_in_page_url, timeout=60000)

        print(f"✅ 登录成功! 当前页面 URL: {app_page.url}")
        await app_page.wait_for_load_state("networkidle", timeout=60000)

        # 成功后返回所需的对象
        return app_page, context, browser

    except Exception as e:
        # 错误处理
        print(f"登录过程中发生严重错误: {e}")
        # 保存截图以供调试
        screenshot_path = "playwright_login_error.png"
        await app_page.screenshot(path=screenshot_path)
        print(f"已保存错误截图至: {screenshot_path}")
        # 关闭浏览器以释放资源
        await browser.close()
        # 重新抛出异常，以便上层调用者知道登录失败
        raise


async def _login_and_get_app_page(p: Playwright, username: str, password: str) -> tuple[Page, BrowserContext, Browser]:
    """
    (内部辅助函数) 封装了完整的Web登录流程，并返回成功登录后的应用程序页面对象。
    """
    print("🚀 开始登录流程...")
    browser = await p.chromium.launch(headless=False, timeout=60000)
    context: BrowserContext = await browser.new_context()
    page: Page = await context.new_page()

    login_url = "https://veevasys.okta.com/"
    await page.goto(login_url, timeout=60000)

    await page.locator('input[name="identifier"]').fill(username)

    password_input = page.locator('input[name="credentials.passcode"]')
    await password_input.wait_for(state="visible", timeout=10000)
    await password_input.fill(password)

    await page.locator('input[type="submit"]').click()

    print("📱 正在等待 Okta Verify Push 选项...")
    push_button = page.locator('[data-se="okta_verify-push"]').get_by_role("link", name="Select")
    await push_button.wait_for(state="visible", timeout=30000)
    await push_button.click()

    print("⏳ 请在您的设备上进行认证。正在等待应用仪表板加载...")

    async with context.expect_page(timeout=180000) as new_page_info:
        await page.get_by_label("launch app Pegasus").click()

    app_page: Page = new_page_info.value
    print(f"✅ 登录成功! 当前页面 URL: {app_page.url}")
    await app_page.wait_for_load_state("networkidle", timeout=60000)

    return app_page, context, browser

# --- 模块 1.2: SQL 和表单逻辑 ---
def _load_all_schemas(file_path: str = "schemas.json") -> dict:
    """
    (内部辅助函数) 从指定的JSON文件中加载所有表结构。
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    absolute_file_path = os.path.join(script_dir, file_path)
    
    try:
        with open(absolute_file_path, 'r', encoding='utf-8') as f:
            schemas = json.load(f)
            return schemas
    except FileNotFoundError:
        print(f"❌ 错误: Schema文件 '{absolute_file_path}' 未找到。")
        return {}
    except json.JSONDecodeError:
        print(f"❌ 错误: Schema文件 '{absolute_file_path}' 不是一个有效的JSON格式。")
        return {}

ALL_SCHEMAS = _load_all_schemas()

def _select_relevant_tables(natural_language_query: str) -> list[str]:
    """
    (内部辅助函数) 使用LLM根据自然语言问题，从所有可用表中选择相关的表。
    """
    print("🤖 正在进行第一步: 选择相关表...")
    table_selection_prompt = ChatPromptTemplate.from_messages([
        ("system", f"""
# 角色和目标
你是一个高效的数据库架构师。你的任务是分析一个自然语言问题，并从可用表列表中确定哪些表是回答该问题所必需的。

# 可用表
{', '.join(ALL_SCHEMAS.keys())}

# 指示
1. 阅读用户的问题。
2. 识别问题中提到的关键实体（如 "协访记录(coachings)", "用户(users)", "记录类型(record_types)"）。
3. 将这些实体映射到上面列出的最相关的表名。
4. 仅返回一个由逗号分隔的所需表名的列表。不要包含任何其他文本、解释或代码块。

# 示例
用户问题: "查找用户'张三'的所有协访记录。"
你的回答: coachings,users
"""),
        ("user", "{query}")
    ])

    table_selection_llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0,
                                                 google_api_key=os.getenv("GOOGLE_API_KEY"))
    chain = table_selection_prompt | table_selection_llm | StrOutputParser()
    response = chain.invoke({"query": natural_language_query})
    selected_tables = [table.strip() for table in response.split(',') if table.strip() in ALL_SCHEMAS]
    if not selected_tables:
        print("⚠️ 未能识别出任何相关表，将默认使用所有表。")
        return list(ALL_SCHEMAS.keys())
    print(f"✅ 第一步完成. 选择的表: {selected_tables}")
    return selected_tables

def generate_sql_query(natural_language_query: str) -> str:
    """
    (内部函数) 根据用户提供的自然语言问题，动态选择相关表结构，然后生成精确的SQL查询语句。
    """
    print(f"🤖 调用SQL生成流程，自然语言问题: '{natural_language_query}'")
    relevant_tables = _select_relevant_tables(natural_language_query)
    dynamic_schema_prompt_part = "\n".join([ALL_SCHEMAS[table] for table in relevant_tables])
    print(f"📋 正在为SQL生成构建动态Schema:\n---\n{dynamic_schema_prompt_part}\n---")

    # --- Start of Updated Prompt ---
    sql_generation_prompt = ChatPromptTemplate.from_messages([
        ("system", """# 角色和目标
你是一名顶级的SQL数据库专家。你的核心任务是根据我提供的【数据库表结构】和【上下文约束】，将我的【自然语言问题】精准地翻译成一个可以直接在数据库中执行的SQL查询语句。

---

# 上下文约束
1.  **单一客户环境**: 所有查询都默认在"一个"客户的环境中执行。因此，你生成的SQL不应包含任何试图查询、筛选或遍历多个客户的代码（例如 `customer_id IN (...)` 或 `GROUP BY customer_name`）。请将问题中的"客户"理解为当前操作的隐式环境。
2.  **严格基于Schema**: 你的所有查询都必须严格使用下面【数据库表结构】中定义的表和列。绝不能虚构不存在的表名或列名。如果问题无法通过给定的Schema解答，请明确指出。

---

# 数据库表结构 (Schema)
-- 注意: 这里只提供了与用户问题最相关的表 --
{schema}

---

# 工作流程与规则
1.  **理解意图**: 首先，仔细分析【自然语言问题】，识别出查询的核心意图（例如：查询数据、计数、聚合、查找关联信息等）。
2.  **识别实体与关联**:
    * 从问题中定位关键实体，并映射到对应的数据库表。
    * 识别表与表之间的关联，确定需要使用的 `JOIN` 类型（通常是 `INNER JOIN` 或 `LEFT JOIN`）。
3.  **构建查询逻辑**:
    * **选择列 (`SELECT`)**: 确定需要返回哪些列。
    * **数据源 (`FROM`/`JOIN`)**: 基于第2步确定要查询的表和连接关系。
    * **过滤条件 (`WHERE`)**: 将问题中的条件（如"最近一个月"、"状态为'已完成'"）转换成 `WHERE` 子句。
    * **聚合与分组 (`GROUP BY`/`HAVING`)**: 如果问题涉及聚合（如"总数"、"平均值"），则使用 `GROUP BY` 和聚合函数。
4.  **关键转换规则**:
    * **人类可读的文本**: 当问题中提到需要"显示"或"筛选"用户可见的文本（如记录类型、状态、用户名、部门名）时，必须通过 `JOIN` 关联到对应的维度表，如果查询内容为中文，优先使用 label 字段进行筛选和显示。如果为英文，则优先使用 name 字段。
    * **时间处理**: 对日期和时间的描述（如"今天"、"本周"、"上个月"）要转换成精确的SQL日期函数和区间比较。

---

# 输出格式
* 直接返回最终的SQL查询语句。
* **不要**添加任何额外的解释、注释或代码块标记（如 ```sql ... ```）。"""),
        ("user", "{query}")
    ])
    # --- End of Updated Prompt ---

    sql_llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0)
    chain = sql_generation_prompt | sql_llm | StrOutputParser()
    generated_sql = chain.invoke({"schema": dynamic_schema_prompt_part, "query": natural_language_query})
    cleaned_sql = re.sub(r"```sql\n|```", "", generated_sql).strip()
    if "SELECT" not in cleaned_sql.upper():
         print(f"❌ SQL生成失败，返回的不是有效的查询语句。")
         return f"错误: 未能生成有效的SQL查询。LLM返回: {cleaned_sql}"
    print(f"✅ 内部SQL生成成功:\n---\n{cleaned_sql}\n---")
    return cleaned_sql

async def fill_form_and_submit(page: Page, approver: str, jira_ticket: str, reason: str, sql_query: str, **kwargs) -> str:
    """
    (内部函数) 在已登录的应用页面上，找到、填写并提交数据查询表单。
    """
    print("\n🔍 开始在应用页面上执行表单填写操作...")
    expected_url = 'https://pegasus-prod.veevasfa.com/environment/list'
    if page.url != expected_url:
        print(f"⚠️ 当前页面URL不是期望的 {expected_url}，正在导航到该页面...")
        await page.goto(expected_url, timeout=60000)
        await page.wait_for_load_state('networkidle', timeout=60000)
    await page.get_by_role("button", name="批量读取").click()
    dialog_locator: Locator = page.locator('div[role="dialog"]').first
    await expect(dialog_locator).to_be_visible(timeout=10000)
    await dialog_locator.get_by_text("全选prod", exact=True).click()
    await dialog_locator.get_by_role("button", name="Confirm").click()
    print("📝 表单页面已加载，开始填写详细信息...")
    approver_input_locator = page.locator(".el-form-item:has-text('评审人')").locator("input.el-select__input")
    await approver_input_locator.fill(approver)
    option_locator = page.locator(f"li.el-select-dropdown__item:has-text('{re.escape(approver)}')")
    await option_locator.click()
    print(f"✅ 审批人 '{approver}' 已成功选择。")
    await page.get_by_label("Story Jira").fill(jira_ticket)
    print(f"✅ Story Jira '{jira_ticket}' 已填写。")
    await page.get_by_label("申请原因").fill(reason)
    print("✅ 申请原因已填写。")
    await page.get_by_label("SQL内容").fill(sql_query)
    print("✅ SQL 内容已填写。")
    print("\n" + "="*50)
    print("✋ 表单已填写完毕，正在自动提交！")
    await page.get_by_role("button", name="提交").click()
    print("✅ 表单已提交。")
    return {"success": True, "message": "表单提交成功！"}

# --- 模块 1.3: 下载和状态检查逻辑 ---
async def download_file_from_veeva(url: str, headers: dict, output_filename: str) -> str:
    """
    (内部辅助函数) 使用httpx库下载文件, 成功后返回最终文件名。
    """
    print(f"\n--- 正在使用 httpx 库直接下载文件：{url} ---")
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.get(url, headers=headers, follow_redirects=True)
        response.raise_for_status()
        if 'Content-Disposition' in response.headers:
            content_disposition = response.headers['Content-Disposition']
            filename_match = re.search(r'filename\*?=(?:UTF-8\'\')?\"?([^\";]+)\"?', content_disposition)
            if filename_match:
                suggested_filename_raw = filename_match.group(1).strip()
                # httpx 不需要 requests.utils.unquote，可以直接使用
                suggested_filename = suggested_filename_raw # httpx会自动处理url编码，这里不再需要requests.utils.unquote
                if suggested_filename:
                    output_filename = suggested_filename # Override if a suggested filename is found
                    print(f"ℹ️  根据服务器建议，文件将保存为: {output_filename}")
        with open(output_filename, 'wb') as f:
            async for chunk in response.aiter_bytes():
                f.write(chunk)
        print(f"✅ 文件 '{output_filename}' 下载成功！")
        return output_filename
    except httpx.RequestError as e:
        error_msg = f"❌ 文件下载失败: {e}"
        print(error_msg)
        return error_msg

async def _find_status_and_download_if_ready(page: Page, context: BrowserContext, jira_ticket: str, **kwargs) -> str:
    """
    (内部函数) 在"操作记录"页面整合了状态检查和文件下载的完整流程。
    """
    print("\n🔍 开始查询审批状态与执行下载流程...")
    try:
        await page.locator("li.el-menu-item", has_text="操作记录").click()
        await page.wait_for_load_state('networkidle', timeout=60000)
        print(f"✅ 已导航到操作记录页面: {page.url}")
    except Exception as e:
        return f"❌ 导航到'操作记录'页面失败: {e}."
    
    print(f"📄 正在操作记录中定位 Jira: {jira_ticket}...")
    item_container_base_selector = 'div.el-card.is-always-shadow.custom-card'
    specific_item_container_locator = page.locator(item_container_base_selector).filter(
        has=page.locator(f'span.el-text.custom-text:has-text("相关Jira: {jira_ticket}")')
    )
    
    try:
        await specific_item_container_locator.first.wait_for(state='visible', timeout=30000)
        print(f"✅ 已找到包含 '{jira_ticket}' 的记录卡片。")
    except Exception:
        return f"❌ 未能找到 Jira 工单 {jira_ticket} 对应的卡片。"
    
    try:
        application_status_locator = specific_item_container_locator.first.locator('span.custom-text:has-text("申请状态:")').first
        application_status = await application_status_locator.inner_text()
        try:
            execution_status_locator = specific_item_container_locator.first.locator('span.custom-text:has-text("执行状态:")').first
            if await execution_status_locator.is_visible(timeout=1000):
                execution_status = await execution_status_locator.inner_text()
            else:
                execution_status = "pagesus未执行，无执行状态"
        except TimeoutError:
            execution_status = "pagesus未执行，无执行状态"
    except Exception as e:
        print(f"❗️ 解析状态时出错: {e}")
        return f"✅ 找到了Jira工单 {jira_ticket} 的卡片，但无法确定其完整状态。"

    if "executed" in application_status.lower() and "success" in execution_status.lower():
        print(f"✅ 条件满足 (申请状态: {application_status}, 执行状态: {execution_status})。继续执行下载流程...")
    else:
        return f"✅ 查询成功！Jira 工单 {jira_ticket} 的申请状态是: '{application_status}', 执行状态是: '{execution_status}' (不满足下载条件)。"
    
    try:
        detail_button_locator = specific_item_container_locator.locator('button.el-button.is-circle.el-tooltip__trigger')
        await detail_button_locator.first.click(timeout=30000)
        await page.locator('b.el-text--large:has-text("操作申请详情页")').wait_for(state='visible', timeout=60000)
        
        download_link_locator = page.locator('a.el-link:has-text("点击下载到Excel")')
        relative_download_url = await download_link_locator.get_attribute('href')
        if not relative_download_url:
            return "❌ 找到了下载链接，但无法获取其地址(href)。"
        
        download_api_url = urljoin(page.url, relative_download_url)
        cookies_list = await context.cookies()
        cookie_string = "; ".join([f"{c['name']}={c['value']}" for c in cookies_list])
        user_agent = await page.evaluate('navigator.userAgent')
        auth_headers = {'User-Agent': user_agent, 'Cookie': cookie_string}
        
        jira_match = re.search(r"ORI-\d+", jira_ticket)
        file_jira_id = jira_match.group(0) if jira_match else jira_ticket
        
        output_filename = await download_file_from_veeva(download_api_url, auth_headers, f'Veeva_Report_{file_jira_id}.xlsx')
        
        if "失败" in output_filename or "Error" in output_filename:
            return f"Jira {jira_ticket} 状态为 executed/success, 但下载失败: {output_filename}"
        
        return f"🎉 操作完成！Jira 工单 {jira_ticket} 的文件已成功下载为 '{output_filename}'。你可以通过新指令要求我分析这个文件。"
    
    except Exception as e:
        return f"❌ 在点击详情或下载过程中发生错误: {e}"


def _get_prompt_detail_by_user_requirement(user_requirement: str) -> str:
    count_prompt = """
2.  **判断统计方式**：检查该工作表的数据表头中是否存在包含 "count" 关键字的列（例如 `count(*)`）。
3.  **执行数据统计**：
    * **如果存在 "count" 列**：请从该列的第一行提取其数值，并将此数值作为该客户的最终"数据量"。
    * **如果不存在 "count" 列**：请计算该工作表数据内容的总行数，并将此行数作为该客户的最终"数据量"。
4.  **处理异常情况**：如果在处理任何工作表时遇到错误，或者无法按上述规则提取有效数据，则该客户的"数据量"计为 0。

## 输出要求
1.  **生成单一表格**：将所有客户（即所有工作表）的分析结果汇总到一个最终的排名表格中。
2.  **包含所有客户**：排名表格必须包含所有被分析的客户，**即使其"数据量"为 0**。
3.  **降序排名**：所有客户需按照"数据量"从高到低进行排序。
4.  **指定格式**：表格需包含以下三列，并严格按照此命名：
    * 第一列："排名"
    * 第二列："客户名称"
    * 第三列："数据量"
5. 只显示输出结果排名，不要输出程序代码。
6. 将结果格式化为标准的 CSV 字符串。**不要**在 CSV 内容之外添加任何解释、标题、注释或 Markdown 代码块标记。
    """

    prompt_detail = count_prompt

    if user_requirement and '统计' in user_requirement:        
        prompt_detail = count_prompt
    return prompt_detail


def generate_report_from_data(data_string, chart_filename):
    """
    根据输入的字符串数据生成报告。

    Args:
        data_string (str): 包含客户数据的多行字符串。
    """
    # --- 1. 读取数据并创建DataFrame ---
    # 使用io.StringIO将字符串模拟成一个文件
    data = io.StringIO(data_string)
    df = pd.read_csv(data)
    
    print("成功读取数据。")
    
    # --- 2. 将完整数据保存到CSV文件 ---
    csv_filename = 'customer_data.csv'
    # 使用 encoding='utf-8-sig' 确保在Windows Excel中打开CSV文件时中文不乱码
    df.to_csv(csv_filename, index=False, encoding='utf-8-sig')
    print(f"完整数据已保存到文件: {csv_filename}")
    
    # --- 3. 准备绘图数据 ---
    # 筛选出数据量大于0的客户，使图表更清晰
    df_to_plot = df[df['数据量'] > 0].copy()
    
    # 如果没有数据可供绘图，则退出
    if df_to_plot.empty:
        print("没有数据量大于0的客户，无法生成图表。")
        return

    # 对数据进行排序，确保柱状图从高到低显示
    df_to_plot.sort_values(by='数据量', ascending=False, inplace=True)
        
    # --- 4. 生成柱状图 ---
    # 设置matplotlib以正确显示中文
    plt.rcParams['font.sans-serif'] = ['STHeiti']  # 'SimHei' 是一个常用的支持中文的字体
    plt.rcParams['axes.unicode_minus'] = False  # 修正负号显示问题
    
    # 创建图表
    plt.figure(figsize=(12, 7)) # 设置画布大小
    bars = plt.bar(df_to_plot['客户名称'], df_to_plot['数据量'], color='skyblue')
    
    # 在柱子顶端添加数据标签
    for bar in bars:
        yval = bar.get_height()
        plt.text(bar.get_x() + bar.get_width()/2.0, yval, int(yval), va='bottom', ha='center', fontsize=10)
    
    # 设置图表标题和坐标轴标签
    plt.title('客户数据量对比分析', fontsize=16)
    plt.xlabel('客户名称', fontsize=12)
    plt.ylabel('数据量', fontsize=12)
    
    # 旋转X轴标签以防重叠
    plt.xticks(rotation=45, ha='right')
    
    # 添加网格线
    plt.grid(axis='y', linestyle='--', alpha=0.6)
    
    # 自动调整布局，防止标签被截断
    plt.tight_layout()
    
    # --- 5. 保存图表到文件 ---
    # chart_filename = 'customer_volume_chart.png'
    plt.savefig(chart_filename)
    print(f"柱状图已保存到文件: {chart_filename}")


# --- 模块 1.4: 数据分析逻辑 ---
def _analyze_excel_file_with_gemini(excel_path: str, jira_ticket: str, user_requirement: str) -> str:
   """
   (内部辅助函数) 读取Excel文件，调用Gemini分析，然后将源文件和分析报告上传到Jira。
   """
   print(f"\n--- 正在使用 Gemini API 分析数据: {excel_path} ---")
   if not excel_path or not os.path.exists(excel_path):
       return f"❌ 错误: 分析失败，因为找不到文件: {excel_path}"
  
   try:
       print(f"📖 正在读取Excel文件: {excel_path}")
       all_sheets_dict = pd.read_excel(excel_path, sheet_name=None)
       json_compatible_dict = {}
      
       for sheet_name, df in all_sheets_dict.items():
           if df.empty:
               json_compatible_dict[sheet_name] = {'columns': [], 'index': [], 'data': []}
           else:
               json_compatible_dict[sheet_name] = json.loads(df.to_json(orient='split'))
      
       data_string = json.dumps(json_compatible_dict, indent=2, ensure_ascii=False)
       print("✅ 数据已成功转换为JSON格式。")


       prompt_detail = _get_prompt_detail_by_user_requirement(user_requirement)


       llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash")
       prompt = ChatPromptTemplate.from_messages([
           ("system", """
## 任务目标
你是一名资深数据分析师。你的任务是分析给定的数据，并提供简洁、专业的摘要报告。
你将收到一个 **JSON 格式的字符串**。这个 JSON 对象中，**每个键（key）代表一个客户（即工作表名称）**，其对应的值（value）是该客户的表格数据，该数据本身也是一个 JSON 对象，通常包含了 "columns" (列名) 和 "data" (数据行) 这两个键。
你的任务是解析这个顶层 JSON 对象，遍历其中的每一个客户，并生成一个统一的客户数据分析结果。


## 核心分析逻辑与规则
你需要**遍历顶层 JSON 对象的每一个键值对（即每一个客户）**，并对每个客户的数据执行以下操作：
1.  **读取工作表**：JSON 对象的键本身就是"客户名称"，并加载其数据内容。
{dynamic_prompt}
"""),
           ("human", "你好，请帮我分析以下业务数据。\n\n数据如下:\n---\n{data_as_string}\n---\n\n")
       ])
      
       chain = prompt | llm | StrOutputParser()
       print("🤖 正在将数据发送给 Gemini 进行分析...")
       analysis_result = chain.invoke({"dynamic_prompt": prompt_detail, "data_as_string": data_string})
       print("--- Gemini 分析结果 ---\n" + analysis_result + "\n------------------------")
      
       report_filename = f"Gemini分析报告_{os.path.basename(excel_path).replace('.xlsx', '.csv')}"
       with open(report_filename, 'w', encoding='utf-8-sig') as f:
           f.write(analysis_result)
       print(f"✅ Gemini 分析结果已保存到 '{report_filename}'")
      
       image_filename = f"Gemini分析报告_{os.path.basename(excel_path).replace('.xlsx', '.png')}"
       generate_report_from_data(analysis_result, image_filename)


       # --- 新增: 上传到 Jira ---
       print(f"\n📎 开始将文件上传到 Jira 工单: {jira_ticket}")
       source_uploaded = add_attachment(jira_ticket, excel_path)
       report_uploaded = add_attachment(jira_ticket, report_filename)
       image_uploaded = add_attachment(jira_ticket, image_filename)
      
       upload_summary = []
       if source_uploaded:
           upload_summary.append(f"源数据文件 '{os.path.basename(excel_path)}'")
       else:
           upload_summary.append(f"源数据文件上传失败")
      
       if report_uploaded:
           upload_summary.append(f"分析报告 '{report_filename}'")
       else:
           upload_summary.append(f"分析报告上传失败")


       if image_uploaded:
           upload_summary.append(f"分析图表 '{image_filename}'")
       else:
           upload_summary.append(f"分析图表上传失败")


       final_message = (
           f"📊 分析完成！结果如下：\n\n{analysis_result}\n\n"
           f"Jira 上传状态: { ' 和 '.join(upload_summary) } 已上传至工单 {jira_ticket}。"
       )
       return final_message


   except Exception as e:
       error_message = f"❌ 数据分析或API调用过程中发生错误: {e}"
       print(error_message)
       return error_message




# --- 模块 1.5: 浏览器操作协调器 ---
async def _perform_browser_action(action_callable: callable, **action_kwargs) -> str:
    """
    (内部协调器) 管理整个浏览器操作生命周期。
    """
    result = ""
    browser = None # This browser variable is local to this function and will be reassigned
    try:
        # Get or create the shared browser session
        app_page, context, browser = await get_browser_session()
        result = await action_callable(page=app_page, context=context, browser=browser, **action_kwargs)
    except Exception as e:
        return f"😭 操作执行过程中发生严重错误: {e}"
    # Do not close the browser here. It will be closed on application shutdown.
    
    return result

# --- 步骤 2: 定义 LangChain 工具 (已更新为中文) ---
@tool
async def process_data_request(jira_ticket: str, approver: str, data_query_description: str) -> str:
    """
    处理一个完整的数据查询【提交】请求。此工具会先根据用户的数据查询描述生成SQL，
    然后自动登录并填写包含所有信息的表单以【提交新申请】。
    当用户想要【发起】或【提交】一个新的数据查询申请，并提供了Jira号、审批人和数据查询需求时，应调用此工具。
    参数:
        jira_ticket (str): 需要填写的 Jira Story 编号。
        approver (str): 需要在表单中选择的审批人姓名。
        data_query_description (str): 用户想要查询什么数据的自然语言描述。
    """
    print("🚀 开始执行端到端数据【提交】流程...")
    print("\n[步骤 1/3] 正在生成SQL查询...")
    sql_query = generate_sql_query(data_query_description)
    if "错误:" in sql_query:
        return f"处理失败：无法生成SQL查询。内部错误: {sql_query}"
    
    print("\n[步骤 2/3] 正在准备表单数据...")
    reason = f"为Jira工单 {jira_ticket} 查询数据"
    
    print("\n[步骤 3/3] 正在执行浏览器操作 (登录和表单填写)...")
    result = await _perform_browser_action(
        fill_form_and_submit,
        approver=approver,
        jira_ticket=jira_ticket,
        reason=reason,
        sql_query=sql_query
    )
    return result

@tool
async def check_jira_status_and_download(jira_ticket: str) -> str:
    """
    当你需要【查询】一个已经提交的Jira工单的【审批状态】时，使用此工具。
    这个工具会查找工单并返回其状态。如果工单状态为"已执行"，此工具会【自动尝试下载】结果文件。
    下载成功后，它会返回文件的本地路径，并告知你可以请求进行分析。
    只需要提供Jira工单号。
    参数:
        jira_ticket (str): 要查询状态的Jira工单号。
    """
    print(f"🚀 开始执行Jira工单状态【查询和下载】流程，工单号: {jira_ticket}...")
    result = await _perform_browser_action(
        _find_status_and_download_if_ready,
        jira_ticket=jira_ticket
    )
    return result

@tool
async def analyze_report_file(file_path: str) -> str:
    """
    使用此工具来【分析】一个已经通过 'check_jira_status_and_download' 工具下载到本地的数据报告文件。
    你需要提供要分析的文件的【完整文件名】或【路径】。
    参数:
        file_path (str): 本地数据文件的路径 (例如 'Veeva_Report_ORI-12345.xlsx')。
    """
    print(f"🚀 开始执行文件【分析】流程，文件: {file_path}...")
    # 将同步的分析操作放到单独的线程中执行，避免阻塞事件循环
    result = await asyncio.to_thread(_analyze_excel_file_with_gemini, file_path, '统计结果')
    return result

@tool
def analyze_report_file_and_upload(file_path: str, jira_ticket: str) -> str:
    """
    使用此工具来【分析】一个已下载的数据报告文件，并将【源文件和分析报告】上传到关联的Jira工单。
    你需要提供要分析的文件的【路径】和对应的【Jira工单号】。
    参数:
        file_path (str): 本地数据文件的路径 (例如 'Veeva_Report_ORI-12345.xlsx')。
        jira_ticket (str): 与此报告关联的Jira工单号 (例如 'ORI-12345')。
    """
    print(f"🚀 开始执行文件【分析与上传】流程，文件: {file_path}, Jira工单: {jira_ticket}...")
    result = _analyze_excel_file_with_gemini(excel_path=file_path, jira_ticket=jira_ticket, user_requirement='统计结果')
    return result

# --- 步骤 3: 设置并运行 Agent (已更新为中文) ---
def main():
    """主执行函数，以交互式聊天机器人模式运行。"""
    load_dotenv()
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0, model_kwargs={"response_mime_type": "application/json"})
    
    tools = [process_data_request, check_jira_status_and_download, analyze_report_file_and_upload]

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", """你是一个高效的助理。你的任务是根据用户的请求调用合适的工具来完成任务。

你有三个可用的工具:
1.  `process_data_request`: 用于【提交新的数据查询申请】。需要 `jira_ticket`, `approver`, 和 `data_query_description`。
2.  `check_jira_status_and_download`: 用于【查询已提交工单的状态】并【自动下载】结果文件（如果准备就绪）。只需要 `jira_ticket`。下载成功后，务必告知用户文件名，并提醒他们可以请求分析。
3.  `analyze_report_file_and_upload`: 用于【分析已下载的文件】并将结果【上传到Jira】。需要 `file_path` 和 `jira_ticket`。

请仔细识别用户的意图：
-   如果用户想【提交】或【发起】新请求 -> 使用 `process_data_request`。
-   如果用户想【查询状态】或【检查进度】 -> 使用 `check_jira_status_and_download`。
-   如果用户在下载文件后想【分析】或【查看报告】 -> 使用 `analyze_report_file_and_upload`。分析时必须提供文件名和它所属的Jira单号。"""),
            ("user", "{input}"),
            ("placeholder", "{agent_scratchpad}"),
        ]
    )

    agent = create_tool_calling_agent(llm, tools, prompt)
    agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True)

    print("👋 你好！我是你的数据查询与分析助手。")
    print("="*60)
    
    example = """你可以这样告诉我:

--- 1. 提交新申请 ---
'帮我提交一个数据查询，Jira号是 ORI-120470，找 lucy.jin 审批。
我想查所有记录类型为"会议随访"的协访记录。'

--- 2. 查询状态与下载 ---
'嘿，帮我查一下 ORI-120624 这个单子的状态。'

--- 3. 分析已下载的文件 ---
'好的，请帮我分析一下刚才下载的 Veeva_Report_ORI-120624.xlsx 文件。'
"""
    print(example)
    print("="*60)

    while True:
        print("\n请输入你的请求 (输入 'quit' 或 'exit' 退出):")
        lines = []
        while True:
            line = input()
            if line:
                lines.append(line)
            else:
                break
        user_input = "\n".join(lines)

        if not user_input.strip():
            print("看起来你没有输入任何内容，请重新输入。")
            continue

        if user_input.lower() in ['quit', 'exit']:
            print("👋 感谢使用，再见！")
            break

        print("\n--- Agent 执行 ---")
        try:
            result = agent_executor.invoke({"input": user_input})
            print("\n--- 最终结果 ---")
            print(result['output'])
        except Exception as e:
            print(f"❌ 执行过程中出现顶层错误: {e}")
            import traceback
            traceback.print_exc()

        print("\n" + "="*60)
        print("我可以为你处理下一个请求。")


if __name__ == "__main__":
    main()

# 定义 LangChain Agent 的全局实例
_global_agent_executor: Optional[AgentExecutor] = None

async def get_agent_executor() -> AgentExecutor:
    global _global_agent_executor
    if _global_agent_executor is None:
        print("🤖 正在初始化 LangChain Agent...")
        load_dotenv()
        llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0, model_kwargs={"response_mime_type": "application/json"})
        
        tools = [process_data_request, check_jira_status_and_download, analyze_report_file_and_upload]

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", """你是一个高效的助理。你的任务是根据用户的请求调用合适的工具来完成任务。

你有三个可用的工具:
1.  `process_data_request`: 用于【提交新的数据查询申请】。需要 `jira_ticket`, `approver`, 和 `data_query_description`。
2.  `check_jira_status_and_download`: 用于【查询已提交工单的状态】并【自动下载】结果文件（如果准备就绪）。只需要 `jira_ticket`。下载成功后，务必告知用户文件名，并提醒他们可以请求分析。
3.  `analyze_report_file_and_upload`: 用于【分析已下载的文件】并将结果【上传到Jira】。需要 `file_path` 和 `jira_ticket`。

请仔细识别用户的意图：
-   如果用户想【提交】或【发起】新请求 -> 使用 `process_data_request`。
-   如果用户想【查询状态】或【检查进度】 -> 使用 `check_jira_status_and_download`。
-   如果用户在下载文件后想【分析】或【查看报告】 -> 使用 `analyze_report_file_and_upload`。分析时必须提供文件名和它所属的Jira单号。"""),
                ("user", "{input}"),
                ("placeholder", "{agent_scratchpad}"),
            ]
        )

        _global_agent_executor = AgentExecutor(agent=create_tool_calling_agent(llm, tools, prompt), tools=tools, verbose=True)
        print("✅ LangChain Agent 初始化完成。")
    return _global_agent_executor

async def invoke_agent_with_message(message: str) -> str:
    """
    使用LangChain Agent处理聊天消息并返回结果。
    """
    print(f"🤖 正在调用 LangChain Agent 处理消息: {message}")
    try:
        agent_executor = await get_agent_executor()
        result = await agent_executor.ainvoke({"input": message})
        return result.get('output', "Agent 没有返回明确的输出。")
    except Exception as e:
        error_message = f"Agent 处理消息时发生错误: {str(e)}"
        print(f"❌ {error_message}")
        import traceback
        traceback.print_exc()
        return error_message