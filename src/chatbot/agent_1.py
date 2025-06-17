import os
import re
from dotenv import load_dotenv
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain.tools import tool
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from playwright.sync_api import (Browser, BrowserContext, Locator, Page,
                                  expect, sync_playwright, Playwright)

# --- 步骤 1: 定义独立的逻辑模块 ---

# --- 模块 1.1: 浏览器和认证 ---

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

    # test commit
    return app_page, context, browser

# --- 模块 1.2: 核心业务操作 ---

def generate_sql_query(natural_language_query: str) -> str:
    """
    (内部函数) 根据用户提供的自然语言问题和预定义的数据库结构，生成精确的SQL查询语句。
    """
    print(f"🤖 调用内部SQL生成函数，自然语言问题: '{natural_language_query}'")

    sql_generation_prompt = ChatPromptTemplate.from_messages([
        ("system", """
# 角色和目标
你是一名顶级的SQL数据库专家。你的任务是根据我提供的数据库表结构，将我的自然语言问题精准地翻译成可以直接执行的SQL查询语句。

# 数据库表结构 (Schema)
```sql
CREATE TABLE `coachings` ( `id` INT, `record_type_id` VARCHAR(36), `state` VARCHAR(36), `coaching_rep_id` INT, `coaching_manager_id` INT, ... );
CREATE TABLE `object_record_types` ( `id` VARCHAR(36), `name` VARCHAR(255), `label` VARCHAR(255) );
CREATE TABLE `picklist_values` ( `id` VARCHAR(36), `label` VARCHAR(255) );
CREATE TABLE `users` ( `id` INT, `name` VARCHAR(255) );
CREATE TABLE `object_states` ( `id` VARCHAR(36), `label` VARCHAR(255) );
```
(为简洁起见，此处省略了完整的CREATE TABLE语句，但实际逻辑中包含所有细节)

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
    generated_sql = chain.invoke({"query": natural_language_query})

    cleaned_sql = re.sub(r"```sql\n|```", "", generated_sql).strip()

    if "SELECT" not in cleaned_sql.upper():
         print(f"❌ SQL生成失败，返回的不是有效的查询语句。")
         return f"Error: Failed to generate a valid SQL query. LLM returned: {cleaned_sql}"

    print(f"✅ 内部SQL生成成功:\n---\n{cleaned_sql}\n---")
    return cleaned_sql


def fill_form_and_submit(
    page: Page, approver: str, jira_ticket: str, reason: str, sql_query: str
) -> str:
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


# --- 新功能 ---
def _find_and_get_status(page: Page, jira_ticket: str) -> str:
    """
    (内部函数) 在已登录的应用页面上，导航到“我提交的”列表，
    查找指定的Jira工单并返回其审批状态。
    """
    print("\n🔍 开始查询审批状态...")

    # 假设通过点击名为“我提交的”的菜单项来导航
    print("➡️  正在导航至'我提交的'页面...")
    page.get_by_role("menuitem", name="我提交的").click()
    page.wait_for_load_state("networkidle", timeout=30000)
    print("✅ 已进入'我提交的'页面。")

    print(f"📄 正在搜索 Jira 工单: {jira_ticket}...")

    # 在表格中定位包含特定Jira工单号的行
    # 这是一个健壮的选择器，可以找到包含该文本的 <tr> 元素
    row_locator = page.locator(f"tr:has-text('{re.escape(jira_ticket)}')").first

    try:
        expect(row_locator).to_be_visible(timeout=15000)
        print(f"✅ 已在页面上找到工单 {jira_ticket} 所在的行。")
    except Exception:
        error_msg = f"❌ 未能找到 Jira 工单 {jira_ticket}。请确认工单号是否正确或是否已提交。"
        print(error_msg)
        return error_msg

    # 假设状态在第五列 (td)。请根据实际页面结构调整索引（0-based）。
    status_locator = row_locator.locator("td").nth(4)
    status = status_locator.inner_text()

    print(f"ℹ️  提取到的状态为: '{status}'")

    return f"✅ 查询成功！Jira 工单 {jira_ticket} 的当前审批状态是: {status}"


# --- 模块 1.3: 浏览器操作协调器 (重构) ---

def _perform_browser_action(action_callable: callable, **action_kwargs) -> str:
    """
    (内部协调器) 管理整个浏览器操作生命周期。
    它负责：加载凭据、启动Playwright、登录、执行指定的操作函数、最后关闭浏览器。
    这避免了在每个工具中重复相同的设置和清理代码。

    参数:
        action_callable (callable): 要在登录后的页面上执行的函数。
                                    (例如: `fill_form_and_submit` 或 `_find_and_get_status`)
        **action_kwargs: 传递给 action_callable 的关键字参数。
    """
    username = os.getenv("VEEVA_USERNAME")
    password = os.getenv("VEEVA_PASSWORD")

    if not username or not password:
        return "错误：VEEVA_USERNAME 或 VEEVA_PASSWORD 环境变量未设置。请先设置它们。"
    print("🔑 凭据加载成功。")

    result = ""
    try:
        with sync_playwright() as p:
            browser = None
            try:
                app_page, _, browser = _login_and_get_app_page(p, username, password)

                # 执行传入的具体操作，并将页面对象和其他参数传递进去
                result = action_callable(page=app_page, **action_kwargs)

            finally:
                if browser and browser.is_connected():
                    print("🚪 正在关闭浏览器...")
                    browser.close()
                    print("✅ 浏览器已关闭。")
    except Exception as e:
        error_message = f"😭 操作过程中发生严重错误: {e}"
        print(error_message)
        return error_message

    print("\n✅ 浏览器操作流程执行完毕。")
    return result


# --- 步骤 2: 定义 LangChain 工具 ---

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

# --- 新工具 ---
@tool
def check_jira_status(jira_ticket: str) -> str:
    """
    当你需要【查询】一个已经提交的Jira工单的【审批状态】时，使用此工具。
    这个工具只会【查找和返回状态】，不会提交任何新内容。
    只需要提供Jira工单号。

    参数:
        jira_ticket (str): 要查询状态的Jira工单号。
    """
    print(f"🚀 开始执行Jira工单状态【查询】流程，工单号: {jira_ticket}...")

    # 使用重构后的协调器来执行查询操作
    result = _perform_browser_action(
        _find_and_get_status,
        jira_ticket=jira_ticket
    )

    return result


# --- 步骤 3: 设置并运行 Agent ---

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
- 如果用户想要【查询一个已存在工单的审批状态】，你应该从用户输入中提取 `jira_ticket`，然后调用 `check_jira_status` 工具。
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

--- 查询审批状态 ---
'嘿，帮我查一下 ORI-120470 这个单子的审批状态怎么样了？'
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
