import os
import re
import json
import requests
from urllib.parse import urljoin 
from dotenv import load_dotenv
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain.tools import tool
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from playwright.sync_api import (Browser, BrowserContext, Locator, Page,
                                  expect, sync_playwright, Playwright)

# --- 步骤 1: 定义独立的逻辑模块 ---

# --- 模块 1.1: 浏览器和认证 (无改动) ---
def _login_and_get_app_page(p: Playwright, username: str, password: str) -> tuple[Page, BrowserContext, Browser]:
    """
    (内部辅助函数) 封装了完整的Web登录流程，包括处理MFA（多因素认证），
    并最终返回成功登录后的应用程序页面对象。
    """
    print("🚀 开始登录流程...")
    browser = p.chromium.launch(headless=False, timeout=60000)
    context: BrowserContext = browser.new_context()
    page: Page = context.new_page()

    login_url = "https://veevasys.okta.com/"
    print(f"➡️  正在导航至登录页面: {login_url}")
    page.goto(login_url, timeout=60000)

    print("📝 正在填写用户名...")
    page.locator('input[name="identifier"]').fill(username)

    print("📝 正在填写密码...")
    password_input = page.locator('input[name="credentials.passcode"]')
    password_input.wait_for(state="visible", timeout=10000)
    password_input.fill(password)

    print("🖱️  正在点击登录按钮...")
    page.locator('input[type="submit"]').click()

    print("📱 正在等待 Okta Verify Push 选项...")
    push_button = page.locator('[data-se="okta_verify-push"]').get_by_role("link", name="Select")
    push_button.wait_for(state="visible", timeout=30000)
    push_button.click()

    print("⏳ 请在您的设备上进行认证。正在等待应用仪表板加载...")

    with context.expect_page(timeout=180000) as new_page_info:
        page.get_by_label("launch app Pegasus").click()

    app_page: Page = new_page_info.value
    print(f"✅ 成功切换到新的应用页面! URL: {app_page.url}")
    app_page.wait_for_load_state("networkidle", timeout=60000)
    print("✅ 应用页面已完全加载。")

    return app_page, context, browser

# --- 模块 1.2: 核心业务操作 ---

def _load_all_schemas(file_path: str = "schemas.json") -> dict:
    """
    (内部辅助函数) 从指定的JSON文件中加载所有表结构。
    这允许我们将Schema定义与主应用程序代码分离。
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    absolute_file_path = os.path.join(script_dir, file_path)
    
    print(f"📄 正在从 {absolute_file_path} 加载表结构...")
    try:
        with open(absolute_file_path, 'r', encoding='utf-8') as f:
            schemas = json.load(f)
            print(f"✅ 成功加载 {len(schemas)} 个表结构。")
            return schemas
    except FileNotFoundError:
        print(f"❌ 错误: Schema文件 '{absolute_file_path}' 未找到。请确保 'schemas.json' 与您的主脚本位于同一目录下。")
        return {}
    except json.JSONDecodeError:
        print(f"❌ 错误: Schema文件 '{absolute_file_path}' 不是一个有效的JSON格式。")
        return {}

# 在全局范围加载一次，以便所有函数都可以使用它
ALL_SCHEMAS = _load_all_schemas()

def _select_relevant_tables(natural_language_query: str) -> list[str]:
    """
    (内部辅助函数) 使用LLM根据自然语言问题，从所有可用表中选择相关的表。
    这是一个预处理步骤，用于减少主SQL生成提示的大小。
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
2. 识别问题中提到的关键实体（如 "coaching records", "users", "record types"）。
3. 将这些实体映射到上面列出的最相关的表名。
4. 仅返回一个由逗号分隔的所需表名的列表。不要包含任何其他文本、解释或代码块。

# 示例
用户问题: "Find all coaching records for the user 'John Doe'."
你的回答: coachings,users
"""),
        ("user", "{query}")
    ])

    # 使用一个快速且成本效益高的模型进行此分类任务
    table_selection_llm = ChatGoogleGenerativeAI(model="gemini-1.5-flash-latest", temperature=0)
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

    # 步骤 1: 动态选择相关的表
    relevant_tables = _select_relevant_tables(natural_language_query)

    # 步骤 2: 根据选择的表构建动态的Schema提示
    dynamic_schema_prompt_part = "\n".join([ALL_SCHEMAS[table] for table in relevant_tables])
    print(f"📋 正在为SQL生成构建动态Schema:\n---\n{dynamic_schema_prompt_part}\n---")


    # 步骤 3: 使用动态Schema生成SQL
    sql_generation_prompt = ChatPromptTemplate.from_messages([
        ("system", """
# 角色和目标
你是一名顶级的SQL数据库专家。你的任务是根据我提供的【相关】数据库表结构，将我的自然语言问题精准地翻译成可以直接执行的SQL查询语句。

# 数据库表结构 (Schema)
-- 注意: 这里只提供了与用户问题最相关的表 --
{schema}

# 指示
1.  严格使用上面定义的表名和列名。
2.  仔细分析我的自然语言问题，理解其核心意图。
3.  当需要匹配或显示用户可见的文本（如记录类型、状态、用户名）时，必须使用 `label` 或 `name` 字段进行 `JOIN` 查询。
4.  将最终的SQL查询语句直接返回，不要添加任何额外的解释或代码块标记。
"""),
        ("user", "{query}")
    ])

    sql_llm = ChatGoogleGenerativeAI(model="gemini-1.5-flash-latest", temperature=0)
    chain = sql_generation_prompt | sql_llm | StrOutputParser()

    # 将动态Schema和用户问题一起传入
    generated_sql = chain.invoke({
        "schema": dynamic_schema_prompt_part,
        "query": natural_language_query
    })

    cleaned_sql = re.sub(r"```sql\n|```", "", generated_sql).strip()

    if "SELECT" not in cleaned_sql.upper():
         print(f"❌ SQL生成失败，返回的不是有效的查询语句。")
         return f"Error: Failed to generate a valid SQL query. LLM returned: {cleaned_sql}"

    print(f"✅ 内部SQL生成成功:\n---\n{cleaned_sql}\n---")
    return cleaned_sql


def fill_form_and_submit(
    page: Page, approver: str, jira_ticket: str, reason: str, sql_query: str, **kwargs
) -> str:
    """
    (内部函数) 在已登录的应用页面上，找到、填写并提交数据查询表单。
    **kwargs用于接收来自协调器的额外参数（如context），以保持签名兼容性。
    """
    print("\n🔍 开始在应用页面上执行表单填写操作...")
    page.get_by_role("button", name="批量读取").click()

    dialog_locator: Locator = page.locator('div[role="dialog"]').first
    expect(dialog_locator).to_be_visible(timeout=10000)

    dialog_locator.get_by_text("全选prod", exact=True).click()
    dialog_locator.get_by_role("button", name="Confirm").click()

    print("📝 表单页面已加载，开始填写详细信息...")

    approver_input_locator = page.locator(".el-form-item:has-text('评审人')").locator("input.el-select__input")
    approver_input_locator.fill(approver)
    option_locator = page.locator(f"li.el-select-dropdown__item:has-text('{re.escape(approver)}')")
    option_locator.click()
    print(f"✅ 审批人 '{approver}' 已成功选择。")

    page.get_by_label("Story Jira").fill(jira_ticket)
    print(f"✅ Story Jira '{jira_ticket}' 已填写。")

    page.get_by_label("申请原因").fill(reason)
    print("✅ 申请原因已填写。")

    page.get_by_label("SQL内容").fill(sql_query)
    print("✅ SQL 内容已填写。")

    print("\n" + "="*50)
    print("✋ 表单已填写完毕，等待人工审核！")
    print("   请检查浏览器窗口中的表单内容是否正确。")

    confirmation = input("   确认无误并提交申请吗？请输入 'yes' 或 'y' 继续: ")

    if confirmation.lower() in ['yes', 'y']:
        print("✅ 用户确认提交，正在点击提交按钮...")
        submit_button = page.get_by_role("button", name="提交")
        expect(submit_button).to_be_enabled(timeout=10000)
        submit_button.click()
        page.wait_for_load_state("networkidle", timeout=30000)
        return_message = f"🎉 操作成功！已为 Jira {jira_ticket} 提交申请。"
    else:
        return_message = f"🟡 操作已取消。用户在审核后未确认提交 Jira {jira_ticket} 的申请。"

    print(f"\n{return_message}")
    return return_message


# --- 新增的下载辅助函数 ---
def download_file_from_veeva(url: str, headers: dict, output_filename: str):
    """
    使用requests库下载文件。
    """
    print(f"\n--- 正在使用 Requests 库直接下载文件：{url} ---")
    try:
        response = requests.get(url, headers=headers, stream=True, allow_redirects=True, timeout=120)
        response.raise_for_status()

        # 尝试从响应头中获取服务器建议的文件名
        suggested_filename = output_filename
        if 'Content-Disposition' in response.headers:
            content_disposition = response.headers['Content-Disposition']
            filename_match = re.search(r'filename\*?=(?:UTF-8\'\')?\"?([^\";]+)\"?', content_disposition)
            if filename_match:
                suggested_filename_raw = filename_match.group(1).strip()
                try:
                    suggested_filename = requests.utils.unquote(suggested_filename_raw)
                except Exception:
                    suggested_filename = suggested_filename_raw

        if suggested_filename and suggested_filename != output_filename:
            output_filename = suggested_filename
            print(f"ℹ️  根据服务器建议，文件将保存为: {output_filename}")
        else:
            print(f"ℹ️  文件将保存为默认名: {output_filename}")

        with open(output_filename, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        print(f"✅ 文件 '{output_filename}' 下载成功！")
        return f"文件 '{output_filename}' 已成功下载到本地。"

    except requests.exceptions.RequestException as e:
        error_msg = f"❌ 文件下载失败: {e}"
        print(error_msg)
        return error_msg


# ---寻找对应jira号的申请，查看状态，如果已执行则下载 ---
def _find_status_and_download_if_ready(page: Page, context: BrowserContext, jira_ticket: str, **kwargs) -> str:
    """
    (内部函数) 在“操作记录”页面整合了状态检查和文件下载的完整流程。
    1. 导航到“操作记录”列表。
    2. 查找指定的Jira工单卡片，并检查其“申请状态”和“执行状态”。
    3. 如果“申请状态”为 'executed' 且“执行状态”为 'success'，则点击详情按钮并下载文件。
    4. 如果不满足下载条件，则仅返回当前状态。
    """
    print("\n🔍 开始查询审批状态与执行下载流程...")

    print("➡️  [步骤 1/1] 正在导航至'操作记录'页面进行查找、状态检查和下载...")
    try:
        page.locator("li.el-menu-item", has_text="操作记录").click()
        page.wait_for_load_state('networkidle', timeout=60000)
        print(f"✅ 已导航到操作记录页面: {page.url}")
    except Exception as e:
        error_msg = f"❌ 导航到'操作记录'页面失败: {e}."
        print(error_msg)
        return error_msg

    print(f"📄 正在操作记录中定位 Jira: {jira_ticket}...")
    
    # 定位包含Jira ID的卡片容器
    item_container_base_selector = 'div.el-card.is-always-shadow.custom-card'
    specific_item_container_locator = page.locator(item_container_base_selector).filter(
        has=page.locator(f'span.el-text.custom-text:has-text("相关Jira: {jira_ticket}")')
    )
    
    try:
        specific_item_container_locator.first.wait_for(state='visible', timeout=30000)
        print(f"✅ 已找到包含 '{jira_ticket}' 的记录卡片。")
    except Exception:
        error_msg = f"❌ 未能找到 Jira 工单 {jira_ticket} 对应的卡片。请确认工单号是否正确或申请是否已在'操作记录'中。"
        print(error_msg)
        return error_msg

    # 在卡片内同时查找“申请状态”和“执行状态”
    try:
        # 定位“申请状态”
        application_status_locator = specific_item_container_locator.locator('span.custom-text:has-text("申请状态:")')
        full_app_status_text = application_status_locator.inner_text().strip()
        application_status = full_app_status_text.split(':')[1].strip()
        print(f"ℹ️  提取到的申请状态为: '{application_status}'")

        # 定位“执行状态”
        execution_status_locator = specific_item_container_locator.locator('span.custom-text:has-text("执行状态:")')
        full_exec_status_text = execution_status_locator.inner_text().strip()
        execution_status = full_exec_status_text.split(':')[1].strip()
        print(f"ℹ️  提取到的执行状态为: '{execution_status}'")

    except Exception as e:
        # 如果任一状态找不到或解析失败，提供一个回退消息
        print(f"❗️ 解析状态时出错: {e}")
        return f"✅ 找到了Jira工单 {jira_ticket} 的卡片，但无法确定其完整状态。请在浏览器中手动检查。"

    # 检查下载条件：申请状态为executed且执行状态为success
    if "executed" in application_status.lower() and "success" in execution_status.lower():
        print(f"✅ 条件满足 (申请状态: {application_status}, 执行状态: {execution_status})。继续执行下载流程...")
    else:
        return f"✅ 查询成功！Jira 工单 {jira_ticket} 的申请状态是: '{application_status}', 执行状态是: '{execution_status}' (不满足下载条件)。"

    # 在卡片内定位详情/下载按钮
    detail_icon_button_selector = 'button.el-button.is-circle.el-tooltip__trigger'
    
    try:
        detail_button_locator = specific_item_container_locator.locator(detail_icon_button_selector)
        detail_button_locator.first.wait_for(state='visible', timeout=30000)
        print("✅ 已找到卡片内的详情图标按钮。")

        # 导航在同一页面发生
        detail_button_locator.first.click(timeout=30000)
        print("🖱️  已点击详情图标按钮，等待详情页内容加载...")
        
        # 等待详情页的标志性元素出现
        detail_page_header_locator = page.locator('b.el-text--large:has-text("操作申请详情页")')
        detail_page_header_locator.wait_for(state='visible', timeout=60000)
        print(f"✅ 已在同一页面加载详情内容。URL: {page.url}")

        # 直接从页面中找到下载链接并提取href
        download_link_locator = page.locator('a.el-link:has-text("点击下载到Excel")')
        download_link_locator.wait_for(state='visible', timeout=10000)
        
        relative_download_url = download_link_locator.get_attribute('href')
        if not relative_download_url:
            return "❌ 找到了下载链接，但无法获取其地址(href)。"
            
        # 使用当前页面URL构建完整的下载URL
        base_url = page.url
        download_api_url = urljoin(base_url, relative_download_url)
        
        print(f"✅ 成功提取到下载链接: {download_api_url}")
        
        # 提取下载所需认证信息
        cookies_list = context.cookies()
        cookie_string = "; ".join([f"{c['name']}={c['value']}" for c in cookies_list])
        user_agent = page.evaluate('navigator.userAgent')

        auth_headers = {
            'User-Agent': user_agent,
            'Cookie': cookie_string,
        }
        print("✅ 成功捕获下载所需的会话认证信息。")
        
        # 提取Jira号用于文件名
        jira_match = re.search(r"ORI-\d+", jira_ticket)
        file_jira_id = jira_match.group(0) if jira_match else jira_ticket

        # 构建下载URL并执行下载
        download_result = download_file_from_veeva(
            download_api_url, 
            auth_headers, 
            f'Veeva_Report_{file_jira_id}.xlsx'
        )
        return f"🎉 操作完成！Jira 工单 {jira_ticket} 的申请状态为 {application_status}，执行状态为 {execution_status}。{download_result}"

    except Exception as e:
        error_message = f"❌ 在点击详情或下载过程中发生错误: {e}"
        print(error_message)
        import traceback
        traceback.print_exc()
        # 调试时可以取消注释以下行来保存截图
        # page.screenshot(path=f"playwright_download_error_{jira_ticket}.png")
        # print(f"已保存错误截图 playwright_download_error_{jira_ticket}.png")
        return error_message


# --- 模块 1.3: 浏览器操作协调器 (已修改以传递context) ---
def _perform_browser_action(action_callable: callable, **action_kwargs) -> str:
    """
    (内部协调器) 管理整个浏览器操作生命周期。
    它负责：加载凭据、启动Playwright、登录、执行指定的操作函数、最后关闭浏览器。
    此版本已更新，会将 `context` 对象传递给 `action_callable`。
    """
    username = os.getenv("VEEVA_USERNAME")
    password = os.getenv("VEEVA_PASSWORD")

    if not username or not password:
        return "错误：VEEVA_USERNAME 或 VEEVA_PASSWORD 环境变量未设置。请先设置它们。"
    print("🔑 凭据加载成功。")

    result = ""
    browser = None # 确保 browser 在 try 块外被定义
    try:
        with sync_playwright() as p:
            try:
                app_page, context, browser = _login_and_get_app_page(p, username, password)

                # 执行传入的具体操作，并将页面和上下文对象以及其他参数传递进去
                result = action_callable(page=app_page, context=context, **action_kwargs)

            except Exception as e:
                # 捕获在 action_callable 中发生的异常
                error_message = f"😭 操作执行过程中发生严重错误: {e}"
                print(error_message)
                import traceback
                traceback.print_exc()
                return error_message
            finally:
                if browser and browser.is_connected():
                    print("🚪 正在关闭浏览器...")
                    browser.close()
                    print("✅ 浏览器已关闭。")
    except Exception as e:
        # 捕获 Playwright 启动或登录过程中的异常
        error_message = f"😭 浏览器生命周期管理中发生严重错误: {e}"
        print(error_message)
        import traceback
        traceback.print_exc()
        return error_message

    print("\n✅ 浏览器操作流程执行完毕。")
    return result


# --- 步骤 2: 定义 LangChain 工具 (check_jira_status的描述已更新) ---
@tool
def process_data_request(jira_ticket: str, approver: str, data_query_description: str) -> str:
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
    if "Error:" in sql_query:
        return f"处理失败：无法生成SQL查询。内部错误: {sql_query}"

    print("\n[步骤 2/3] 正在准备表单数据...")
    reason = f"为Jira工单 {jira_ticket} 查询数据"
    print(f"  - 申请原因已生成: '{reason}'")

    print("\n[步骤 3/3] 正在执行浏览器操作 (登录和表单填写)...")

    # 使用重构后的协调器来执行操作
    result = _perform_browser_action(
        fill_form_and_submit,
        approver=approver,
        jira_ticket=jira_ticket,
        reason=reason,
        sql_query=sql_query
    )
    return result

@tool
def check_jira_status(jira_ticket: str) -> str:
    """
    当你需要【查询】一个已经提交的Jira工单的【审批状态】时，使用此工具。
    这个工具会查找工单并返回其状态。如果工单状态为“已执行”，此工具会【自动尝试下载】结果文件。
    只需要提供Jira工单号。

    参数:
        jira_ticket (str): 要查询状态的Jira工单号。
    """
    print(f"🚀 开始执行Jira工单状态【查询和下载】流程，工单号: {jira_ticket}...")

    # 使用重构后的协调器来执行查询和下载操作
    result = _perform_browser_action(
        _find_status_and_download_if_ready,
        jira_ticket=jira_ticket
    )
    return result


# --- 步骤 3: 设置并运行 Agent (无改动) ---
def main():
    """主执行函数，以交互式聊天机器人模式运行。"""
    load_dotenv()
    llm = ChatGoogleGenerativeAI(model="gemini-1.5-flash-latest", temperature=0, model_kwargs={"response_mime_type": "application/json"})

    # 将新工具添加到工具列表中
    tools = [process_data_request, check_jira_status]

    # 更新系统提示，让Agent了解新工具的能力
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", """你是一个高效的助理。你的任务是根据用户的请求调用合适的工具。
- 如果用户想要【提交一个新的数据查询申请】，你应该从用户输入中提取 `jira_ticket`, `approver`, 和 `data_query_description`，然后调用 `process_data_request` 工具。
- 如果用户想要【查询一个已存在工单的审批状态】，你应该从用户输入中提取 `jira_ticket`，然后调用 `check_jira_status` 工具。此工具在工单执行完毕后会自动下载文件。
- 准确地识别用户的意图是提交新请求还是查询旧请求。"""),
            ("user", "{input}"),
            ("placeholder", "{agent_scratchpad}"),
        ]
    )

    agent = create_tool_calling_agent(llm, tools, prompt)
    agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True)

    print("👋 你好！我是你的数据查询助手。")
    print("="*60)

    # 更新引导示例，包含新功能
    example = """例如，你可以这样告诉我:

--- 提交新申请 ---
'你好，请帮我处理一个数据查询申请。
 工单号是 ORI-120470。
 我需要查询所有记录类型为“会议随访”的协访记录。
 这个申请需要 lucy.jin 来审批。'

--- 查询审批状态 (如果已执行会自动下载) ---
'嘿，帮我查一下 ORI-120624 这个单子的审批状态怎么样了？'
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
            print(f"❌ 执行过程中出现错误: {e}")

        print("\n" + "="*60)
        print("我可以为你处理下一个请求。")


if __name__ == "__main__":
    # 在运行前，请确保你的 .env 文件或环境变量中已设置 VEEVA_USERNAME 和 VEEVA_PASSWORD
    main()
