from jira import JIRA
import os

# 使用现有的配置
jira_token = os.getenv("JIRA_TOKEN")
jiraOptions = {'server': "https://jira.veevadev.com/"}
jira = JIRA(options=jiraOptions, token_auth=jira_token)

def add_attachment(issue_key: str, file_path: str, replace_existing: bool = True) -> bool:
    """
    为指定的Jira issue添加附件

    Args:
        issue_key (str): Jira issue的key，例如 'ORI-120579'
        file_path (str): 要上传的文件路径
        replace_existing (bool): 如果存在同名附件是否替换，默认True

    Returns:
        bool: 上传成功返回True，失败返回False

    Example:
        add_attachment('ORI-120579', 'test.csv')
    """
    try:
        # 获取issue
        issue = jira.issue(issue_key)
        print(f"找到issue: {issue.key}")
        print(f"Issue标题: {issue.fields.summary}")

        # 检查文件是否存在
        if not os.path.exists(file_path):
            print(f"错误: 文件不存在 - {file_path}")
            return False

        filename = os.path.basename(file_path)

        # 如果需要替换且存在同名附件，先删除
        if replace_existing:
            existing_attachment = None
            if hasattr(issue.fields, 'attachment') and issue.fields.attachment:
                for attachment in issue.fields.attachment:
                    if attachment.filename == filename:
                        existing_attachment = attachment
                        break

                if existing_attachment:
                    print(f"发现同名附件，正在删除: {filename}")
                    jira.delete_attachment(existing_attachment.id)

        # 上传新附件
        attachment = jira.add_attachment(issue, file_path)
        print(f"附件上传成功: {attachment.filename}")
        return True

    except Exception as e:
        print(f"上传附件时出错: {e}")
        return False

def delete_attachment(issue_key: str, filename: str) -> bool:
    """
    删除指定Jira issue上的指定附件

    Args:
        issue_key (str): Jira issue的key，例如 'ORI-120579'
        filename (str): 要删除的附件文件名

    Returns:
        bool: 删除成功返回True，失败返回False

    Example:
        delete_attachment('ORI-120579', 'test.csv')
    """
    try:
        # 获取issue
        issue = jira.issue(issue_key)
        print(f"找到issue: {issue.key}")
        print(f"Issue标题: {issue.fields.summary}")

        # 查找指定附件
        target_attachment = None
        if hasattr(issue.fields, 'attachment') and issue.fields.attachment:
            print(f"\n{issue.key} 的现有附件:")
            for attachment in issue.fields.attachment:
                print(f"  - {attachment.filename} (ID: {attachment.id}, 大小: {attachment.size} bytes)")
                if attachment.filename == filename:
                    target_attachment = attachment
                    print(f"    找到目标附件: {attachment.filename}")

        # 删除指定附件
        if target_attachment:
            jira.delete_attachment(target_attachment.id)
            print(f"已删除附件: {target_attachment.filename}")
            return True
        else:
            print(f"未找到名为 '{filename}' 的附件")
            return False

    except Exception as e:
        print(f"删除附件时出错: {e}")
        return False

def list_attachments(issue_key: str) -> None:
    """
    列出指定Jira issue的所有附件

    Args:
        issue_key (str): Jira issue的key，例如 'ORI-120579'

    Example:
        list_attachments('ORI-120579')
    """
    try:
        issue = jira.issue(issue_key)
        print(f"找到issue: {issue.key}")
        print(f"Issue标题: {issue.fields.summary}")

        if hasattr(issue.fields, 'attachment') and issue.fields.attachment:
            print(f"\n{issue.key} 的附件列表:")
            for attachment in issue.fields.attachment:
                print(f"  - {attachment.filename} (ID: {attachment.id}, 大小: {attachment.size} bytes)")
        else:
            print(f"\n{issue.key} 暂无附件")

    except Exception as e:
        print(f"获取附件列表时出错: {e}")

# 使用示例
if __name__ == "__main__":
    # 只测试ORI-120579
    issue_key = 'ORI-120579'
    print("=== 列出附件 ===")
    list_attachments(issue_key)

    print("\n=== 上传附件 ===")
    test_content = """Issue Key,Summary,Status,Priority,Description\nORI-120579,测试CSV附件功能,Open,High,这是一个用于测试Jira附件上传功能的CSV文件\n"""
    test_filename = "test_upload.csv"
    with open(test_filename, "w", encoding="utf-8") as f:
        f.write(test_content)
    add_attachment(issue_key, test_filename)

    print("\n=== 删除附件 ===")
    delete_attachment(issue_key, test_filename)

    if os.path.exists(test_filename):
        os.remove(test_filename)
