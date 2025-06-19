
import os
import json
import pandas as pd

# --- LangGraph & LangChain Imports ---
from langgraph.graph import StateGraph, END
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_google_genai import ChatGoogleGenerativeAI


def analyze_data(csv_path: str):
    """
    将excel文件的数据转换为json格式, 调用Gemini API做数据分析
    """
    print("\n--- 调用 Gemini API 分析数据 ---")
    if not csv_path or not os.path.exists(csv_path):
        print(f"错误: 分析节点未找到 CSV 文件 at {csv_path}")
        return

    print(f"读取文件: {csv_path}")
    # df = pd.read_excel(csv_path)
    all_sheets_dict = pd.read_excel(csv_path, sheet_name=None)
    
    # 2. 创建一个新的字典，用于存放可以被 JSON 序列化的数据
    json_compatible_dict = {}

    # 3. 遍历每个工作表，将其从 DataFrame 转换为 JSON 格式
    for sheet_name, df in all_sheets_dict.items():
        # df.to_json(orient='split') 是一个很好的格式，它保留了列名和数据
        # 如果工作表为空，则导出一个空的数据结构
        if df.empty:
            json_compatible_dict[sheet_name] = {'columns': [], 'index': [], 'data': []}
        else:
            json_compatible_dict[sheet_name] = df.to_json(orient='split')
            # to_json 返回的是字符串，我们需要再把它解析回字典，以便最终整体转换
            json_compatible_dict[sheet_name] = json.loads(json_compatible_dict[sheet_name])


    # 4. 将包含所有工作表数据的 Python 字典，转换为一个格式化的 JSON 字符串
    #    indent=2 让输出格式更美观，易于阅读
    #    ensure_ascii=False 确保中文字符能正确显示
    data_string = json.dumps(json_compatible_dict, indent=2, ensure_ascii=False)

    # 5. 打印最终的、可用于 Prompt 的完整 JSON 字符串
    print(data_string)

    try:
        llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash")

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

        print("正在将数据发送给 Gemini 进行分析...")
        analysis_result = chain.invoke({"data_as_string": data_string})
        print("--- Gemini 分析结果 ---\n" + analysis_result + "\n------------------------")

        # 格式问题，直接写入txt文本文件了
        output_excel_path = 'gemini_analysis_report.txt'

        # 使用 'w' 模式（写入）和 'utf-8' 编码来保存文件
        with open(output_excel_path, 'w', encoding='utf-8') as f:
            f.write(analysis_result)

        # output_excel_path = "/Users/LucyJin/gemini_analysis_report.xlsx"
        # print(f"正在生成包含 Gemini 分析的 Excel 报告: {output_excel_path}")
        # analysis_df = pd.DataFrame({'Gemini 分析报告': [analysis_result]})
        # with pd.ExcelWriter(output_excel_path) as writer:
        #     df.to_excel(writer, sheet_name='原始数据', index=False)
        #     analysis_df.to_excel(writer, sheet_name='Gemini分析结果', index=False)

    except Exception as e:
        print(f"数据分析或 API 调用失败: {e}")


if __name__ == "__main__":
    analyze_data("test_case_1.xlsx")