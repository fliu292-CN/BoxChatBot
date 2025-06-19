import os
import re
import json
import requests
import pandas as pd
from urllib.parse import urljoin
from dotenv import load_dotenv
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain.tools import tool
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from playwright.sync_api import (Browser, BrowserContext, Locator, Page,
                                  expect, sync_playwright, Playwright)

# --- 模块 1: 核心业务逻辑 ---

# --- 模块 1.1: 浏览器和认证 (无改动) ---
def _login_and_get_app_page(p: Playwright, username: str, password: str) -> tuple[Page, BrowserContext, Browser]:
    """
    (内部辅助函数) 封装了完整的Web登录流程，并返回成功登录后的应用程序页面对象。
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

# --- 模块 1.2: SQL 和表单逻辑 ---
def _load_all_schemas(file_path: str = "schemas.json") -> dict:
    """
    (内部辅助函数) 从指定的JSON文件中加载所有表结构。
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
    table_selection_llm = ChatGoogleGenerativeAI(model="gemini-1.5-flash-latest", temperature=0,
                                                 google_api_key=os.getenv("GOOGLE_API_KEY")
)
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
    generated_sql = chain.invoke({"schema": dynamic_schema_prompt_part, "query": natural_language_query})
    cleaned_sql = re.sub(r"```sql\n|```", "", generated_sql).strip()
    if "SELECT" not in cleaned_sql.upper():
         print(f"❌ SQL生成失败，返回的不是有效的查询语句。")
         return f"错误: 未能生成有效的SQL查询。LLM返回: {cleaned_sql}"
    print(f"✅ 内部SQL生成成功:\n---\n{cleaned_sql}\n---")
    return cleaned_sql

def fill_form_and_submit(page: Page, approver: str, jira_ticket: str, reason: str, sql_query: str, **kwargs) -> str:
    """
    (内部函数) 在已登录的应用页面上，找到、填写并提交数据查询表单。
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

# --- 模块 1.3: 下载和状态检查逻辑 ---
def download_file_from_veeva(url: str, headers: dict, output_filename: str) -> str:
    """
    (内部辅助函数) 使用requests库下载文件, 成功后返回最终文件名。
    """
    print(f"\n--- 正在使用 Requests 库直接下载文件：{url} ---")
    try:
        response = requests.get(url, headers=headers, stream=True, allow_redirects=True, timeout=120)
        response.raise_for_status()
        if 'Content-Disposition' in response.headers:
            content_disposition = response.headers['Content-Disposition']
            filename_match = re.search(r'filename\*?=(?:UTF-8\'\')?\"?([^\";]+)\"?', content_disposition)
            if filename_match:
                suggested_filename_raw = filename_match.group(1).strip()
                try:
                    suggested_filename = requests.utils.unquote(suggested_filename_raw)
                    if suggested_filename:
                        output_filename = suggested_filename
                        print(f"ℹ️  根据服务器建议，文件将保存为: {output_filename}")
                except Exception:
                    pass
        with open(output_filename, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        print(f"✅ 文件 '{output_filename}' 下载成功！")
        return output_filename
    except requests.exceptions.RequestException as e:
        error_msg = f"❌ 文件下载失败: {e}"
        print(error_msg)
        return error_msg

def _find_status_and_download_if_ready(page: Page, context: BrowserContext, jira_ticket: str, **kwargs) -> str:
    """
    (内部函数) 在“操作记录”页面整合了状态检查和文件下载的完整流程。
    """
    print("\n🔍 开始查询审批状态与执行下载流程...")
    try:
        page.locator("li.el-menu-item", has_text="操作记录").click()
        page.wait_for_load_state('networkidle', timeout=60000)
        print(f"✅ 已导航到操作记录页面: {page.url}")
    except Exception as e:
        return f"❌ 导航到'操作记录'页面失败: {e}."
    
    print(f"📄 正在操作记录中定位 Jira: {jira_ticket}...")
    item_container_base_selector = 'div.el-card.is-always-shadow.custom-card'
    specific_item_container_locator = page.locator(item_container_base_selector).filter(
        has=page.locator(f'span.el-text.custom-text:has-text("相关Jira: {jira_ticket}")')
    )
    
    try:
        specific_item_container_locator.first.wait_for(state='visible', timeout=30000)
        print(f"✅ 已找到包含 '{jira_ticket}' 的记录卡片。")
    except Exception:
        return f"❌ 未能找到 Jira 工单 {jira_ticket} 对应的卡片。"
    
    try:
        application_status_locator = specific_item_container_locator.locator('span.custom-text:has-text("申请状态:")')
        application_status = application_status_locator.inner_text().strip().split(':')[1].strip()
        execution_status_locator = specific_item_container_locator.locator('span.custom-text:has-text("执行状态:")')
        execution_status = execution_status_locator.inner_text().strip().split(':')[1].strip()
    except Exception as e:
        print(f"❗️ 解析状态时出错: {e}")
        return f"✅ 找到了Jira工单 {jira_ticket} 的卡片，但无法确定其完整状态。"

    if "executed" in application_status.lower() and "success" in execution_status.lower():
        print(f"✅ 条件满足 (申请状态: {application_status}, 执行状态: {execution_status})。继续执行下载流程...")
    else:
        return f"✅ 查询成功！Jira 工单 {jira_ticket} 的申请状态是: '{application_status}', 执行状态是: '{execution_status}' (不满足下载条件)。"
    
    try:
        detail_button_locator = specific_item_container_locator.locator('button.el-button.is-circle.el-tooltip__trigger')
        detail_button_locator.first.click(timeout=30000)
        page.locator('b.el-text--large:has-text("操作申请详情页")').wait_for(state='visible', timeout=60000)
        
        download_link_locator = page.locator('a.el-link:has-text("点击下载到Excel")')
        relative_download_url = download_link_locator.get_attribute('href')
        if not relative_download_url:
            return "❌ 找到了下载链接，但无法获取其地址(href)。"
        
        download_api_url = urljoin(page.url, relative_download_url)
        cookies_list = context.cookies()
        cookie_string = "; ".join([f"{c['name']}={c['value']}" for c in cookies_list])
        user_agent = page.evaluate('navigator.userAgent')
        auth_headers = {'User-Agent': user_agent, 'Cookie': cookie_string}
        
        jira_match = re.search(r"ORI-\d+", jira_ticket)
        file_jira_id = jira_match.group(0) if jira_match else jira_ticket
        
        output_filename = download_file_from_veeva(download_api_url, auth_headers, f'Veeva_Report_{file_jira_id}.xlsx')
        
        if "失败" in output_filename or "Error" in output_filename:
            return f"Jira {jira_ticket} 状态为 executed/success, 但下载失败: {output_filename}"
        
        return f"🎉 操作完成！Jira 工单 {jira_ticket} 的文件已成功下载为 '{output_filename}'。你可以通过新指令要求我分析这个文件。"
    
    except Exception as e:
        return f"❌ 在点击详情或下载过程中发生错误: {e}"

# --- 模块 1.4: 数据分析逻辑 ---
def _analyze_excel_file_with_gemini(excel_path: str) -> str:
    """
    (内部辅助函数) 读取Excel文件，将其转换为JSON，然后调用Gemini API进行分析。
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

        llm = ChatGoogleGenerativeAI(model="gemini-1.5-flash-latest")
        prompt = ChatPromptTemplate.from_messages([
            ("system", """
## 任务目标
你是一名资深数据分析师。你的任务是分析给定的数据，并提供简洁、专业的摘要报告。
你将收到一个 **JSON 格式的字符串**。这个 JSON 对象中，**每个键（key）代表一个客户（即工作表名称）**，其对应的值（value）是该客户的表格数据，该数据本身也是一个 JSON 对象，通常包含了 "columns" (列名) 和 "data" (数据行) 这两个键。
你的任务是解析这个顶层 JSON 对象，遍历其中的每一个客户，并生成一个统一的客户数据量排名。

## 核心分析逻辑与规则
你需要**遍历顶层 JSON 对象的每一个键值对（即每一个客户）**，并对每个客户的数据执行以下操作：
1.  **读取工作表**：JSON 对象的键本身就是“客户名称”，并加载其数据内容。
2.  **判断统计方式**：检查该工作表的数据表头中是否存在包含 "count" 关键字的列（例如 `count(*)`）。
3.  **执行数据统计**：
    * **如果存在 "count" 列**：请从该列的第一行提取其数值，并将此数值作为该客户的最终“数据量”。
    * **如果不存在 "count" 列**：请计算该工作表数据内容的总行数，并将此行数作为该客户的最终“数据量”。
4.  **处理异常情况**：如果在处理任何工作表时遇到错误，或者无法按上述规则提取有效数据，则该客户的“数据量”计为 0。

## 输出要求
1.  **生成单一表格**：将所有客户（即所有工作表）的分析结果汇总到一个最终的排名表格中。
2.  **包含所有客户**：排名表格必须包含所有被分析的客户，**即使其“数据量”为 0**。
3.  **降序排名**：所有客户需按照“数据量”从高到低进行排序。
4.  **指定格式**：表格需包含以下三列，并严格按照此命名：
    * 第一列：“排名”
    * 第二列：“客户名称”
    * 第三列：“数据量”
5. 只显示输出结果排名，不要输出程序代码。
"""),
            ("human", "你好，请帮我分析以下业务数据。\n\n数据如下:\n---\n{data_as_string}\n---\n\n")
        ])
        
        chain = prompt | llm | StrOutputParser()
        print("🤖 正在将数据发送给 Gemini 进行分析...")
        analysis_result = chain.invoke({"data_as_string": data_string})
        
        report_filename = f"Gemini分析报告_{os.path.basename(excel_path).replace('.xlsx', '.txt')}"
        with open(report_filename, 'w', encoding='utf-8') as f:
            f.write(analysis_result)
        print(f"✅ Gemini 分析结果已保存到 '{report_filename}'")
        
        return f"📊 分析完成！结果如下：\n\n{analysis_result}\n\n报告也已保存到文件 '{report_filename}'。"
    except Exception as e:
        error_message = f"❌ 数据分析或API调用过程中发生错误: {e}"
        print(error_message)
        return error_message


# --- 模块 1.5: 浏览器操作协调器 ---
def _perform_browser_action(action_callable: callable, **action_kwargs) -> str:
    """
    (内部协调器) 管理整个浏览器操作生命周期。
    """
    username = os.getenv("VEEVA_USERNAME")
    password = os.getenv("VEEVA_PASSWORD")
    if not username or not password:
        return "错误：VEEVA_USERNAME 或 VEEVA_PASSWORD 环境变量未设置。"
    
    result = ""
    browser = None
    try:
        with sync_playwright() as p:
            try:
                app_page, context, browser = _login_and_get_app_page(p, username, password)
                result = action_callable(page=app_page, context=context, **action_kwargs)
            except Exception as e:
                return f"😭 操作执行过程中发生严重错误: {e}"
            finally:
                if browser and browser.is_connected():
                    print("🚪 正在关闭浏览器...")
                    browser.close()
    except Exception as e:
        return f"😭 浏览器生命周期管理中发生严重错误: {e}"
    
    return result

# --- 步骤 2: 定义 LangChain 工具 (已更新为中文) ---
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
    if "错误:" in sql_query:
        return f"处理失败：无法生成SQL查询。内部错误: {sql_query}"
    
    print("\n[步骤 2/3] 正在准备表单数据...")
    reason = f"为Jira工单 {jira_ticket} 查询数据"
    
    print("\n[步骤 3/3] 正在执行浏览器操作 (登录和表单填写)...")
    result = _perform_browser_action(
        fill_form_and_submit,
        approver=approver,
        jira_ticket=jira_ticket,
        reason=reason,
        sql_query=sql_query
    )
    return result

@tool
def check_jira_status_and_download(jira_ticket: str) -> str:
    """
    当你需要【查询】一个已经提交的Jira工单的【审批状态】时，使用此工具。
    这个工具会查找工单并返回其状态。如果工单状态为“已执行”，此工具会【自动尝试下载】结果文件。
    下载成功后，它会返回文件的本地路径，并告知你可以请求进行分析。
    只需要提供Jira工单号。
    参数:
        jira_ticket (str): 要查询状态的Jira工单号。
    """
    print(f"🚀 开始执行Jira工单状态【查询和下载】流程，工单号: {jira_ticket}...")
    result = _perform_browser_action(
        _find_status_and_download_if_ready,
        jira_ticket=jira_ticket
    )
    return result

@tool
def analyze_report_file(file_path: str) -> str:
    """
    使用此工具来【分析】一个已经通过 'check_jira_status_and_download' 工具下载到本地的数据报告文件。
    你需要提供要分析的文件的【完整文件名】或【路径】。
    参数:
        file_path (str): 本地数据文件的路径 (例如 'Veeva_Report_ORI-12345.xlsx')。
    """
    print(f"🚀 开始执行文件【分析】流程，文件: {file_path}...")
    result = _analyze_excel_file_with_gemini(file_path)
    return result

# --- 步骤 3: 设置并运行 Agent (已更新为中文) ---
def main():
    """主执行函数，以交互式聊天机器人模式运行。"""
    load_dotenv()
    llm = ChatGoogleGenerativeAI(model="gemini-1.5-flash-latest", temperature=0, model_kwargs={"response_mime_type": "application/json"})
    
    tools = [process_data_request, check_jira_status_and_download, analyze_report_file]

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", """你是一个高效的助理。你的任务是根据用户的请求调用合适的工具来完成任务。

你有三个可用的工具:
1.  `process_data_request`: 用于【提交新的数据查询申请】。需要 `jira_ticket`, `approver`, 和 `data_query_description`。
2.  `check_jira_status_and_download`: 用于【查询已提交工单的状态】并【自动下载】结果文件（如果准备就绪）。只需要 `jira_ticket`。下载成功后，务必告知用户文件名，并提醒他们可以请求分析。
3.  `analyze_report_file`: 用于【分析已下载的文件】。需要 `file_path`。

请仔细识别用户的意图：
-   如果用户想【提交】或【发起】新请求 -> 使用 `process_data_request`。
-   如果用户想【查询状态】或【检查进度】 -> 使用 `check_jira_status_and_download`。
-   如果用户在下载文件后想【分析】或【查看报告】 -> 使用 `analyze_report_file`。"""),
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
我想查所有记录类型为“会议随访”的协访记录。'

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
