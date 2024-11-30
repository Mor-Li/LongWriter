import os
import json
import sys

def escape_text(text):
    """
    将文本中的特殊字符转义（如换行符、制表符等）。
    """
    return text

def txt_to_single_jsonl(input_txt_path):
    """
    将TXT文件内容读取并转化为JSONL文件。
    输入文件路径必须存在，输出文件路径为默认修改后缀名为`.jsonl`的文件。
    """
    if not os.path.exists(input_txt_path):
        print(f"Error: 输入文件 '{input_txt_path}' 不存在。")
        return

    # 自动生成输出路径，修改后缀名为`.jsonl`
    output_jsonl_path = os.path.splitext(input_txt_path)[0] + ".jsonl"

    with open(input_txt_path, "r", encoding="utf-8") as txt_file:
        # 读取整个TXT文件内容并转义
        content = txt_file.read()
        escaped_content = escape_text(content.strip())

        # 将转义后的内容存储到JSONL文件中
        json_object = {"prompt": escaped_content}
        with open(output_jsonl_path, "w", encoding="utf-8") as jsonl_file:
            jsonl_file.write(json.dumps(json_object, ensure_ascii=False) + "\n")

    print(f"转换完成！JSONL文件已保存为: {output_jsonl_path}")

def main():
    # 检查命令行参数
    if len(sys.argv) < 2:
        print("使用方法: python txt2instructions <输入文件路径>")
        return

    input_txt_path = sys.argv[1]  # 从命令行读取文件路径

    # 转换TXT为JSONL
    txt_to_single_jsonl(input_txt_path)

if __name__ == "__main__":
    main()
