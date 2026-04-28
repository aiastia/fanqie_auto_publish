#!/usr/bin/env python3
"""
小说章节拆分脚本
将完整的小说 txt 文件按章节拆分为单独的文件，适配 fanqie_auto_publish 工具。

用法: python3 split_novel.py <小说文件路径> [书名]
"""

import re
import sys
import os


def split_novel(filepath, book_name=None):
    """将小说文件按章节拆分到 chapters/书名/ 目录下"""

    if not os.path.exists(filepath):
        print(f"❌ 文件不存在: {filepath}")
        sys.exit(1)

    # 读取文件
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # 如果没有指定书名，用文件名（去掉扩展名）
    if not book_name:
        book_name = os.path.splitext(os.path.basename(filepath))[0]

    # 章节正则：匹配 "第X章" 开头的行（X 可以是数字或中文数字）
    chapter_pattern = re.compile(r'^(第\d+章\s+.+)$', re.MULTILINE)

    # 找到所有章节标题的位置
    matches = list(chapter_pattern.finditer(content))

    if not matches:
        print("❌ 未找到任何章节（格式应为 '第X章 标题'），请检查文件内容。")
        sys.exit(1)

    print(f"📚 书名: {book_name}")
    print(f"📖 共找到 {len(matches)} 个章节\n")

    # 创建输出目录
    output_dir = os.path.join(os.path.dirname(filepath), 'chapters', book_name)
    os.makedirs(output_dir, exist_ok=True)

    # 拆分并保存每一章
    for i, match in enumerate(matches):
        chapter_title = match.group(1).strip()
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)

        # 提取章节内容（包含标题行）
        chapter_content = content[start:end].strip()

        # 生成序号（三位数）
        seq = f"{i + 1:03d}"

        # 提取章节号用于文件名
        num_match = re.search(r'第(\d+)章', chapter_title)
        chapter_num = num_match.group(1) if num_match else str(i + 1)

        # 文件名格式: 001 第1章 标题.txt
        filename = f"{seq} {chapter_title}.txt"

        # 清理文件名中的非法字符
        filename = re.sub(r'[/\\:*?"<>|]', '', filename)

        filepath_out = os.path.join(output_dir, filename)

        with open(filepath_out, 'w', encoding='utf-8') as f:
            f.write(chapter_content)

        print(f"  ✅ {filename}")

    print(f"\n🎉 拆分完成！文件保存在: {output_dir}")
    print(f"   共 {len(matches)} 个章节文件，可直接用于 fanqie_auto_publish。")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("用法: python3 split_novel.py <小说文件路径> [书名]")
        print("示例: python3 split_novel.py 我在大秦改命.txt")
        sys.exit(1)

    filepath = sys.argv[1]
    book_name = sys.argv[2] if len(sys.argv) > 2 else None
    split_novel(filepath, book_name)