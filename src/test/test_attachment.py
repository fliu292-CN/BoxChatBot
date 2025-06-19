from jira_attachment_handler import list_attachments, add_attachment, delete_attachment
import os

def test_list_attachments():
    """测试用例1: 列出附件功能"""
    
    # 测试用的Jira issue - 固定使用ORI-120579
    issue_key = "ORI-120579"
    
    print("=" * 60)
    print("测试用例1: 列出附件功能")
    print(f"测试目标: {issue_key}")
    print("=" * 60)
    
    # 列出当前附件
    print("\n列出当前附件:")
    print("-" * 30)
    list_attachments(issue_key)
    
    print("\n" + "=" * 60)
    print("测试用例1完成！")
    print("=" * 60)

def test_upload_attachment():
    """测试用例2: 上传附件功能"""
    
    # 测试用的Jira issue - 固定使用ORI-120579
    issue_key = "ORI-120579"
    
    print("=" * 60)
    print("测试用例2: 上传附件功能")
    print(f"测试目标: {issue_key}")
    print("=" * 60)
    
    # 创建CSV测试文件 - 只包含ORI-120579的数据
    csv_content = """Issue Key,Summary,Status,Priority,Description
ORI-120579,测试CSV附件上传功能,Open,High,这是一个用于测试Jira附件上传功能的CSV文件
"""
    
    test_filename = "test_data.csv"
    print(f"\n创建并上传文件: {test_filename}")
    
    # 创建CSV文件
    with open(test_filename, "w", encoding="utf-8") as f:
        f.write(csv_content)
    
    # 上传附件
    success = add_attachment(issue_key, test_filename)
    if success:
        print(f"✅ {test_filename} 上传成功")
    else:
        print(f"❌ {test_filename} 上传失败")
    
    # 查看上传后的附件列表
    print("\n查看上传后的附件列表:")
    print("-" * 30)
    list_attachments(issue_key)
    
    # 清理本地测试文件
    print("\n清理本地测试文件:")
    print("-" * 30)
    if os.path.exists(test_filename):
        os.remove(test_filename)
        print(f"已删除本地文件: {test_filename}")
    
    print("\n" + "=" * 60)
    print("测试用例2完成！")
    print("=" * 60)

def test_delete_attachment():
    """测试用例3: 删除附件功能"""
    
    # 测试用的Jira issue - 固定使用ORI-120579
    issue_key = "ORI-120579"
    test_filename = "test_data.csv"
    
    print("=" * 60)
    print("测试用例3: 删除附件功能")
    print(f"测试目标: {issue_key}")
    print("=" * 60)
    
    # 先查看当前附件列表
    print("\n删除前的附件列表:")
    print("-" * 30)
    list_attachments(issue_key)
    
    # 删除指定附件
    print(f"\n删除附件: {test_filename}")
    print("-" * 30)
    success = delete_attachment(issue_key, test_filename)
    if success:
        print(f"✅ {test_filename} 删除成功")
    else:
        print(f"❌ {test_filename} 删除失败")
    
    # 查看删除后的附件列表
    print("\n删除后的附件列表:")
    print("-" * 30)
    list_attachments(issue_key)
    
    print("\n" + "=" * 60)
    print("测试用例3完成！")
    print("=" * 60)

def run_all_tests():
    """运行所有测试用例"""
    print("开始运行所有测试用例...")
    print("=" * 80)
    
    # 运行测试用例1
    test_list_attachments()
    
    # 运行测试用例2
    test_upload_attachment()
    
    # 运行测试用例3
    test_delete_attachment()
    
    print("\n" + "=" * 80)
    print("所有测试用例运行完成！")
    print("=" * 80)

if __name__ == "__main__":
    # 可以选择运行单个测试用例或所有测试用例
    print("请选择要运行的测试用例:")
    print("1. 列出附件")
    print("2. 上传附件")
    print("3. 删除附件")
    print("4. 运行所有测试")
    
    # 默认运行所有测试
    run_all_tests() 