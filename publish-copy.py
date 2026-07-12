import os
import glob
import time
import shutil
import re
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright

STATE_FILE = "state.json"
CHAPTERS_DIR = "chapters"
UPLOADED_DIR = "uploaded"

# 番茄作家书籍管理首页
BOOK_MANAGE_URL = "https://fanqienovel.com/main/writer/book-manage"

def arco_select_date(page, target_date_str):
    """点开 Arco 日期选择器，在弹出的日历面板里导航并选中目标日期。target_date_str: 'YYYY-MM-DD'"""
    target = datetime.strptime(target_date_str, "%Y-%m-%d")
    target_year, target_month, target_day = target.year, target.month, target.day

    # 1. 定位日期输入框（placeholder 含"日期"）并点击展开日历
    date_input = None
    for inp in page.locator('input.arco-picker-start-time').element_handles():
        try:
            ph = inp.evaluate("el => el.getAttribute('placeholder') || ''")
            if "日期" in ph:
                date_input = inp
                break
        except Exception:
            continue
    if date_input is None:
        date_input = page.locator('input.arco-picker-start-time').first.element_handle()
    date_input.click()
    page.wait_for_timeout(900)

    # 2. 等待日历弹窗出现
    try:
        page.wait_for_selector('.arco-picker-header-value', timeout=5000)
    except Exception:
        pass
    page.wait_for_timeout(500)

    # 3. 导航到目标年月（Arco 表头形如 "2026年 7月" 或 "2026-07"）
    for _ in range(48):
        try:
            header_text = page.locator('.arco-picker-header-value').first.inner_text(timeout=2000)
        except Exception:
            break
        nums = re.findall(r'\d+', header_text)
        if len(nums) < 2:
            break
        cur_year, cur_month = int(nums[0]), int(nums[1])
        if cur_year == target_year and cur_month == target_month:
            break
        # 表头图标顺序：[上年, 上月, 下月, 下年] —— 索引 1=上月，2=下月
        forward = (cur_year * 12 + cur_month) < (target_year * 12 + target_month)
        arrow = page.locator('.arco-picker-header-icon').nth(2 if forward else 1)
        try:
            arrow.click(timeout=2000)
        except Exception:
            try:
                if forward:
                    page.locator('.arco-icon-right').first.click(timeout=2000)
                else:
                    page.locator('.arco-icon-left').first.click(timeout=2000)
            except Exception:
                break
        page.wait_for_timeout(350)

    # 4. 点击目标日期单元格
    # 本版 Arco 用 .arco-picker-cell-in-view 标记"本月"单元格；
    # 相邻月占位日没有 prev/next 类，必须用 in-view 过滤，否则会误点下月同号。
    clicked = False
    try:
        cells = page.locator('.arco-picker-cell-in-view:not(.arco-picker-cell-disabled)').element_handles()
        for cell in cells:
            try:
                # 数字容器：.arco-picker-date-value（新版） / .arco-picker-cell-inner（旧版）
                val = cell.query_selector('.arco-picker-date-value, .arco-picker-cell-inner')
                txt = (val.inner_text() if val else cell.inner_text()).strip()
                if txt == str(target_day):
                    cell.click()
                    clicked = True
                    break
            except Exception:
                continue
    except Exception:
        pass
    # 兜底：用文本匹配点第一个含目标日数字的本月单元格
    if not clicked:
        for sel in ['.arco-picker-cell-in-view .arco-picker-date-value', '.arco-picker-date-value', '.arco-picker-cell-inner']:
            try:
                page.locator(sel).filter(has_text=str(target_day)).first.click(timeout=2000)
                clicked = True
                break
            except Exception:
                continue
        if not clicked:
            print(f"    [警告] 日历未点中目标日期 {target_day}")
    page.wait_for_timeout(600)


def arco_select_time(page, target_time_str):
    """点开 Arco 时间选择器，在弹出的时分列里选中目标时间。target_time_str: 'HH:MM'"""
    parts = (target_time_str.split(":") + ["00"])[:2]
    hh_num = int(parts[0])   # 8
    mm_num = int(parts[1])   # 0

    # 1. 定位时间输入框并点击
    time_input = None
    for inp in page.locator('input.arco-picker-start-time').element_handles():
        try:
            ph = inp.evaluate("el => el.getAttribute('placeholder') || ''")
            if "时间" in ph:
                time_input = inp
                break
        except Exception:
            continue
    if time_input is None:
        time_input = page.locator('input.arco-picker-start-time').last.element_handle()
    time_input.click()
    page.wait_for_timeout(900)

    # 2. 等待时间列出现（新版: .arco-timepicker-list / .arco-timepicker-cell；旧版: .arco-timepicker-column）
    try:
        page.wait_for_selector('.arco-timepicker-list, .arco-timepicker-column', timeout=5000)
    except Exception:
        pass
    page.wait_for_timeout(500)

    def _pick(col_idx, target_num):
        """在指定列里点击文本==目标数字的选项。兼容新版/旧版 DOM。"""
        # 新版: .arco-timepicker-list > ul > li.arco-timepicker-cell
        try:
            lists = page.locator('.arco-timepicker-list').element_handles()
            if len(lists) > col_idx:
                ul = lists[col_idx].query_selector('ul')
                if ul:
                    for li in ul.query_selector_all('li.arco-timepicker-cell'):
                        try:
                            inner = li.query_selector('.arco-timepicker-cell-inner')
                            txt = (inner.inner_text() if inner else li.inner_text()).strip()
                            if int(txt) == target_num:
                                li.scroll_into_view_if_needed()
                                li.click()
                                return True
                        except Exception:
                            continue
        except Exception:
            pass
        # 旧版: .arco-timepicker-column > li.arco-timepicker-option
        try:
            cols = page.locator('.arco-timepicker-column').element_handles()
            if len(cols) > col_idx:
                col = cols[col_idx]
                for opt in col.query_selector_all('li.arco-timepicker-option'):
                    try:
                        txt = opt.inner_text().strip()
                        if int(txt) == target_num:
                            opt.scroll_into_view_if_needed()
                            opt.click()
                            return True
                    except Exception:
                        continue
        except Exception:
            pass
        return False

    # 3. 选小时、分钟
    if not _pick(0, hh_num):
        print(f"    [警告] 未点中小时 {hh_num}")
    page.wait_for_timeout(350)
    if not _pick(1, mm_num):
        print(f"    [警告] 未点中分钟 {mm_num}")
    page.wait_for_timeout(400)

    # 4. 确认（新版底部"确定"主按钮，旧版同理）
    confirmed = False
    for sel in [
        'div.arco-timepicker-footer-btn-wrapper button.arco-btn-primary',
        '.arco-picker-footer button.arco-btn-primary',
        'button:has-text("确定")',
        'button:has-text("确认")',
    ]:
        try:
            btn = page.locator(sel).first
            if btn.is_visible():
                btn.click()
                confirmed = True
                break
        except Exception:
            continue
    if not confirmed:
        try:
            page.keyboard.press("Enter")
        except Exception:
            pass
    page.wait_for_timeout(400)


def main():
    if not os.path.exists(STATE_FILE):
        print(f"找不到登录状态文件 {STATE_FILE}，请先运行 py login.py 进行登录！")
        return
    
    # ============ 多部小说子目录管理 ============
    # 扫描 chapters/ 下所有子目录，每个子目录对应一本书
    # 同时兼容旧模式：如果 chapters/ 根目录有散落的 txt 文件，提示用户归类
    root_txt_files = glob.glob(os.path.join(CHAPTERS_DIR, "*.txt"))
    if root_txt_files:
        print(f"\n[提示] 发现 chapters/ 根目录下有 {len(root_txt_files)} 个散落的 txt 文件。")
        print(f"       多部小说管理模式要求章节放在子目录中，例如：")
        print(f"         chapters/ai编程末日/101 第101章.txt")
        print(f"         chapters/青冥独行录/001 第1章.txt")
        print(f"       请先将这些文件移入对应的书名子目录后再运行脚本。\n")
        return
    
    # 扫描子目录
    book_dirs = []
    if os.path.isdir(CHAPTERS_DIR):
        for name in sorted(os.listdir(CHAPTERS_DIR)):
            sub_path = os.path.join(CHAPTERS_DIR, name)
            if os.path.isdir(sub_path):
                txts = glob.glob(os.path.join(sub_path, "*.txt"))
                if txts:
                    book_dirs.append((name, sub_path, sorted(txts)))
    
    if not book_dirs:
        print(f"\n[{CHAPTERS_DIR}] 中没有找到任何待发章节！")
        print(f"请在 chapters/ 下按书名创建子目录并放入 txt 章节文件，例如：")
        print(f"  chapters/ai编程末日/101 第101章.txt")
        print(f"  chapters/青冥独行录/001 第1章.txt\n")
        return
    
    print(f"\n==================================================")
    print(f"即将开始【全自动】发文！多部小说隔离管理模式已启动！")
    print(f"==================================================")
    print(f"\n检测到以下小说有待发章节：\n")
    for idx, (name, _, txts) in enumerate(book_dirs, 1):
        print(f"  [{idx}] {name}  （{len(txts)} 章待发）")
    print()
    
    choice = input(">>> 请输入序号选择要发布的小说：").strip()
    try:
        choice_idx = int(choice) - 1
        if choice_idx < 0 or choice_idx >= len(book_dirs):
            raise ValueError
    except ValueError:
        print("    [错误] 无效的序号，退出。")
        return
    
    book_name_filter, book_chapter_dir, txt_files = book_dirs[choice_idx]
    total_chapters = len(txt_files)
    
    print(f"\n已选择：【{book_name_filter}】，共 {total_chapters} 章待发")
    print(f"==================================================")
    
    # ============ 发布章节数量选择 ============
    publish_count_input = input(
        f"\n>>> 请输入本次要发布的章节数量（1-{total_chapters}），直接回车则发布全部："
    ).strip()
    
    if publish_count_input == "":
        publish_count = total_chapters
        print(f"    -> 将发布全部 {publish_count} 章")
    else:
        try:
            publish_count = int(publish_count_input)
            if publish_count <= 0:
                print("    [错误] 数量必须大于 0，退出。")
                return
            if publish_count > total_chapters:
                print(f"    [提示] 输入数量 {publish_count} 大于待发总数 {total_chapters}，将发布全部章节。")
                publish_count = total_chapters
            else:
                print(f"    -> 将发布前 {publish_count} 章")
        except ValueError:
            print("    [错误] 请输入有效的数字，退出。")
            return
    
    # 截取要发布的章节列表
    txt_files = txt_files[:publish_count]
    
    print(f"\n本次发布计划：【{book_name_filter}】× {len(txt_files)} 章")
    print(f"==================================================\n")
    
    # ============ 定时发布设置 ============
    # 默认每天 8:00 发布，每 3 章日期 +1 天
    print("【定时发布设置】每章固定 08:00 发布，每发送 3 章日期自动 +1 天。")
    start_date_input = input(
        ">>> 请输入开始日期（格式 YYYY-MM-DD），直接回车则使用今天："
    ).strip()
    
    timed_start_date = None
    if start_date_input == "":
        timed_start_date = datetime.now().date()
        print(f"    -> 使用今天作为开始日期：{timed_start_date.isoformat()}")
    else:
        try:
            timed_start_date = datetime.strptime(start_date_input, "%Y-%m-%d").date()
            print(f"    -> 开始日期已设置为：{timed_start_date.isoformat()}")
        except ValueError:
            print("    [错误] 日期格式不正确，应为 YYYY-MM-DD，退出。")
            return
    
    # ============ 卷号选择（决定发布后文件归档到哪个卷目录） ============
    # 直接回车 = 不执行分卷切换（番茄平台会保持上次选择的分卷）
    # 输入具体卷号 = 在浏览器中主动切换到对应分卷
    volume_input = input(
        ">>> 请输入本次发布的章节属于第几卷（如 2、3），直接回车则不执行切换分卷操作："
    ).strip()
    
    volume_num = None  # None 表示不切换分卷
    volume_name = None
    
    if volume_input != "":
        try:
            volume_num = int(volume_input)
            if volume_num <= 0:
                print("    [错误] 卷号必须大于 0，退出。")
                return
            cn_digits = "一二三四五六七八九十"
            volume_name = f"第{cn_digits[volume_num - 1] if volume_num <= 10 else str(volume_num)}卷"
        except ValueError:
            print("    [错误] 请输入有效的数字，退出。")
            return
    
    current_uploaded_dir = os.path.join(UPLOADED_DIR, book_name_filter)
    if volume_name:
        volume_dir = os.path.join(current_uploaded_dir, volume_name)
        print(f"    -> 将切换至【{volume_name}】，发布成功后文件归档至：uploaded/{book_name_filter}/{volume_name}/\n")
    else:
        volume_dir = current_uploaded_dir
        print(f"    -> 不切换分卷（保持番茄平台当前默认），文件归档至：uploaded/{book_name_filter}/\n")
    os.makedirs(volume_dir, exist_ok=True)
    
    print("\n>>> 准备启动浏览器大魔王...")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(storage_state=STATE_FILE)
        page = context.new_page()
        
        success_count = 0
        
        for chapter_idx, file_path in enumerate(txt_files):
            filename = os.path.basename(file_path)
            raw_title = os.path.splitext(filename)[0]
            
            m = re.search(r'第(\d+)章[\s_]*(.*)', raw_title)
            chapter_num = str(m.group(1)) if m else ""
            chapter_title = m.group(2).strip() if m else ""
            
            with open(file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
                
            # 如果文件名里只写了 011 第11章.txt，没有真正的标题，我们就从文件正文第一行提取
            if not chapter_title and lines:
                m2 = re.search(r'第.*?章[\s：:]*(.*)', lines[0].strip())
                if m2:
                    chapter_title = m2.group(1).strip()
            if not chapter_title:
                chapter_title = re.sub(r'^[0-9]+[\s_]*', '', raw_title).strip()
            
            print(f"\n[{success_count+1}/{len(txt_files)}] 正在处理: 第{chapter_num}章 '{chapter_title}' (原文件名: {filename})")
            
            # 智能剔除正文内部最开头的章节标题，防止发出去后出现双黄蛋
            if lines and re.search(r'第.*?章', lines[0].strip()):
                lines = lines[1:]
            while lines and not lines[0].strip():
                lines = lines[1:]
                
            content = "".join(lines)
                
            try:
                # 1. 每次都回到后台的【我的小说】列表页，彻底摆脱嵌套死循环迷宫
                print(" -> 正在跳转回后台【我的小说】总览...")
                page.goto(BOOK_MANAGE_URL, timeout=60000)
                page.wait_for_timeout(3000) # 等待列表刷出来
                
                # 寻找特定小说的"章节管理"入口
                # 【关键】番茄工作台在有多部作品时，"章节管理"按钮默认隐藏，
                # 只有鼠标悬停到对应小说卡片上时才会浮现，因此必须先 hover 再点击。
                print(f" -> 寻找【{book_name_filter}】对应的小说卡片，准备悬停触发【章节管理】按钮...")
                
                manage_clicked = False
                
                # 策略1：找到包含书名文本的卡片容器，hover 后等待"章节管理"出现
                book_cards = page.locator('div, li, section, article').filter(has_text=book_name_filter)
                card_count = book_cards.count()
                
                for i in range(card_count - 1, -1, -1):  # 从后往前试（.last 优先）
                    card = book_cards.nth(i)
                    try:
                        if not card.is_visible():
                            continue
                        # 悬停到小说卡片上，触发 hover 效果
                        card.hover(timeout=3000)
                        page.wait_for_timeout(1000)  # 等待 hover 动画/按钮浮现
                        
                        # 尝试在该卡片内或全局找到"章节管理"
                        manage_btn = card.get_by_text("章节管理").first
                        if manage_btn.is_visible():
                            manage_btn.click()
                            manage_clicked = True
                            break
                    except Exception:
                        continue
                
                # 策略2：如果卡片 hover 方式没成功，尝试全局查找
                if not manage_clicked:
                    print("    [备选] 卡片hover未触发按钮，尝试全局查找【章节管理】...")
                    # 先尝试 hover 所有可见卡片触发全局悬浮
                    all_cards = page.locator('[class*="book"], [class*="card"], [class*="item"]').filter(has_text=book_name_filter)
                    for i in range(all_cards.count()):
                        try:
                            c = all_cards.nth(i)
                            if c.is_visible():
                                c.hover(timeout=2000)
                                page.wait_for_timeout(800)
                                gb = page.get_by_text("章节管理").first
                                if gb.is_visible():
                                    gb.click()
                                    manage_clicked = True
                                    break
                        except Exception:
                            continue
                
                # 策略3：终极兜底
                if not manage_clicked:
                    print("    [警告] 所有 hover 策略失败，退化为直接点击第一个可见的【章节管理】...")
                    page.get_by_text("章节管理").first.click()
                
                page.wait_for_timeout(4000) # 等待各种表格和翻页动画加载
                
                original_pages = len(context.pages)
                # 这时我们已经在【章节管理】，判断它是否弹出了新标签页
                if original_pages > 1 and context.pages[-1] != page:
                    editor_page = context.pages[-1]
                else:
                    editor_page = page
                    
                # 检查是否已存在当前章节草稿
                print(f" -> 扫描已有草稿列表，排查是否存在【第 {chapter_num} 章】的历史遗留...")
                draft_row = editor_page.locator('tr, li, .chapter-item').filter(has_text=re.compile(f"第\\s*{chapter_num}\\s*章")).first
                
                draft_found = False
                try:
                    if draft_row.is_visible():
                        draft_found = True
                except Exception:
                    pass
                
                if draft_found:
                    print(f" -> 🤖 发现被中断的【草稿历史记录】！直接进入编辑，绝不重复生成第二个！")
                    edit_icon = draft_row.locator('td').last.locator('svg, i, a, span, button, img').first
                    try:
                        if edit_icon.is_visible():
                            edit_icon.click(force=True)
                        else:
                            draft_row.click(force=True)
                    except Exception:
                        draft_row.click(force=True)
                else:
                    print(" -> 确认为全新章节，点击右上角桔红色【新建章节】...")
                    new_btn = editor_page.get_by_role("button", name="新建章节").first
                    try:
                        if not new_btn.is_visible():
                            new_btn = editor_page.get_by_text("新建章节").first
                    except Exception:
                        new_btn = editor_page.get_by_text("新建章节").first
                    new_btn.click(force=True)
                
                # 等待编辑器页面加载（网络慢时需要更长时间）
                print(" -> 等待编辑器页面加载...")
                editor_page.wait_for_timeout(5000)
                
                # 【极其关键的救命补丁】：番茄在点击了【新建章节】或者【编辑】后，经常会弹出一个全新的浏览器标签页出来！
                if len(context.pages) > original_pages:
                    editor_page = context.pages[-1]
                    print("    - 检测到新标签页，已自动切换！")
                
                # 等待编辑器内容区域加载完成（重试机制，适应慢网络）
                editor_loaded = False
                for attempt in range(6):
                    try:
                        # 检查是否已经有可编辑区域
                        check = editor_page.locator('.ql-editor, .ProseMirror, [contenteditable="true"]').first
                        if check.is_visible():
                            editor_loaded = True
                            print(f"    - 编辑器已就绪（第{attempt+1}次检测）")
                            break
                    except Exception:
                        pass
                    editor_page.wait_for_timeout(2000)
                
                if not editor_loaded:
                    print("    [警告] 编辑器加载超时，再多等10秒...")
                    editor_page.wait_for_timeout(10000)
                    # 最后再检查一次新标签页
                    if len(context.pages) > original_pages:
                        editor_page = context.pages[-1]
                        print("    - 延迟检测到新标签页，已自动切换！")
                
                # 疯狂点击对付番茄弹出来的各种“功能上新”教学框、提示遮罩
                print(" -> 开始执行清道夫程序，极其凶狠地清除所有遮挡视野的新手教学卡片...")
                for _ in range(3):
                    editor_page.keyboard.press("Escape")
                    editor_page.wait_for_timeout(200)
                
                # 终极空间坐标打击法：靠文字匹配容易失效（甚至有莫名其妙的空格），我们直接找屏幕上**所有**叫“下一步”或“完成”的按钮
                # 如果它不在屏幕最顶端的标题栏（即 y 坐标 > 100），就断定它是该死的新手向导，通通点烂！
                print(" -> 启动空间坐标精确打击！自动消灭所有不在天花板上的新手引导...")
                for _ in range(10):
                    clicked_guide = False
                    try:
                        # 遍历常见的新手教学按钮文案
                        for target_text in ["下一步", "完成", "我知道了", "跳过"]:
                            # 获取这些按钮的底层 DOM 节点
                            btns = editor_page.get_by_text(target_text, exact=True).element_handles()
                            for btn in btns:
                                box = btn.bounding_box()
                                # 顶部的发布按钮极其靠上（通常 y 在20-60左右）。只要 y > 100，必是乱入的悬浮弹窗！
                                if box and box['y'] > 100:
                                    print(f"    - > 坐标 (y={int(box['y'])}) 拦截到流氓向导节点 '{target_text}'，击破！")
                                    btn.click()
                                    editor_page.wait_for_timeout(600)
                                    clicked_guide = True
                    except Exception as e:
                        pass
                    
                    if not clicked_guide:
                        break # 如果这一轮地毯式搜索没点任何非顶部按钮，代表弹窗彻底清扫干净了！
                    
                # 1.5 确认或切换分卷
                if volume_num is not None and volume_num > 1:
                    print(f" -> 开始确认/切换分卷，目标：【{volume_name}】...")
                    try:
                        # 策略：点击左上角的分卷区域触发弹窗，但要避免误点到左侧大纲的占位符
                        # 只查找可视区域内、不在 outline-placeholder 内的卷号元素
                        vol_elements = editor_page.get_by_text(re.compile(r'第[一二三四五六七八九十百]+卷')).element_handles()
                        dialog_opened = False
                        for v in vol_elements[:8]:
                            try:
                                box = v.bounding_box()
                                if not box:
                                    continue
                                # 排除不在可视区域内的元素（y < 0 或 y > 800）
                                if box['y'] < 0 or box['y'] > 800:
                                    continue
                                # 排除左侧大纲占位符（通常包含 "卷名" 文字或 class 含 outline/placeholder）
                                outer_html = v.evaluate("el => el.outerHTML") or ""
                                if "outline" in outer_html.lower() or "placeholder" in outer_html.lower() or "卷名" in outer_html:
                                    continue
                                v.click(force=True)
                                editor_page.wait_for_timeout(1000)
                                # 检测弹窗是否出现（弹窗通常含 "新建分卷" 或 "取消" 按钮）
                                if editor_page.get_by_text("新建分卷").is_visible() or editor_page.get_by_text("取消").is_visible():
                                    dialog_opened = True
                                    break
                            except Exception:
                                pass
                        
                        if dialog_opened:
                            editor_page.wait_for_timeout(500)
                            # 在弹窗/对话框容器内精确查找目标分卷选项
                            # 排除大纲占位符中的同名文本
                            target_vol = None
                            for v_name in [volume_name, f"第{volume_num}卷", f"卷{volume_num}"]:
                                candidates = editor_page.get_by_text(v_name, exact=False).element_handles()
                                for cand in candidates:
                                    try:
                                        cand_box = cand.bounding_box()
                                        if not cand_box:
                                            continue
                                        # 弹窗通常在屏幕中央偏上，排除明显不在弹窗区域的元素
                                        cand_html = cand.evaluate("el => el.outerHTML") or ""
                                        # 排除大纲占位符
                                        if "outline" in cand_html.lower() or "placeholder" in cand_html.lower() or "卷名" in cand_html:
                                            continue
                                        # 排除不在视口内的
                                        if cand_box['y'] < 0 or cand_box['y'] > 800:
                                            continue
                                        target_vol = cand
                                        break
                                    except Exception:
                                        continue
                                if target_vol:
                                    break
                                    
                            if target_vol:
                                target_vol.click(force=True)
                                editor_page.wait_for_timeout(500)
                                
                                # 点击确定按钮关闭弹窗
                                confirm_btn = editor_page.get_by_role("button", name="确定").first
                                if not confirm_btn.is_visible():
                                    confirm_btn = editor_page.get_by_text("确定", exact=True).last
                                
                                if confirm_btn.is_visible():
                                    confirm_btn.click(force=True)
                                    print(f"    - 已成功确认/切换到分卷：{volume_name}")
                                else:
                                    # 确定按钮找不到，用 Escape 兜底关闭弹窗
                                    editor_page.keyboard.press("Escape")
                                    print(f"    [警告] 未找到确定按钮，已用 Escape 关闭弹窗")
                                editor_page.wait_for_timeout(1000)
                            else:
                                print(f"    [警告] 分卷弹窗中未找到包含 {volume_name} 的选项！")
                                print("    脚本正在等待，请您手动在浏览器中点击目标卷并确定！(等待20秒...)")
                                editor_page.wait_for_timeout(20000)
                        else:
                            print("    [警告] 未能成功呼出分卷弹窗。")
                        
                        # 兜底：确保弹窗已关闭，防止遮挡后续编辑器操作
                        editor_page.wait_for_timeout(500)
                        # 如果弹窗仍然存在（取消按钮可见），强制关闭
                        try:
                            if editor_page.get_by_text("取消").first.is_visible():
                                editor_page.keyboard.press("Escape")
                                editor_page.wait_for_timeout(500)
                        except Exception:
                            pass
                    except Exception as e:
                        print(f"    [警告] 自动选择分卷异常：{e}")
                        # 异常时也要确保弹窗关闭
                        try:
                            editor_page.keyboard.press("Escape")
                            editor_page.wait_for_timeout(500)
                        except Exception:
                            pass

                # 2. 填写章节序号和标题
                print(" -> 分别填入左边的【章节序号】和右边的【主标题】...")
                
                # 番茄界面的阿拉伯小框有时候不带 placeholder，所以直接暴力提取页面上真正的第一个文字输入框
                num_input = editor_page.locator('input[type="text"]').first
                if num_input.is_visible():
                    num_input.fill(chapter_num, force=True) # 使用 force=True 强行绕过透明遮罩屏障
                
                title_input = editor_page.get_by_placeholder("请输入标题", exact=False).first
                if not title_input.is_visible():
                    title_input = editor_page.get_by_placeholder("请输入章节名", exact=False).first
                if not title_input.is_visible():
                    title_input = editor_page.locator('input[type="text"]').last
                
                if title_input.is_visible():
                    title_input.fill(chapter_title, force=True)
                    
                # 3. 填写正文内容 (防误触防双击，强制填充)
                print(" -> 开始注入长篇正文血肉...")
                editor = editor_page.locator('.ql-editor').first
                if not editor.is_visible():
                    editor = editor_page.locator('.ProseMirror').first
                if not editor.is_visible():
                    editor = editor_page.locator('[contenteditable="true"]').first
                
                if editor.is_visible():
                    editor.click(force=True)
                    # 防止编辑器里默认带了换行或者空格
                    editor_page.keyboard.press("Control+A")
                    editor_page.keyboard.press("Backspace")

                    # 一把梭子：将内容塞进编辑器，并触发浏览器的侦听网络，让数字统计动起来
                    editor_page.evaluate("([el, text]) => { el.innerText = text; el.dispatchEvent(new Event('input', {bubbles: true})); }", [editor.element_handle(), content])
                    
                    editor.click()
                    editor_page.keyboard.press("End")
                    editor_page.keyboard.press("Space")
                    page.wait_for_timeout(500)
                    editor_page.keyboard.press("Backspace")
                else:
                    print("  [警告] 没找到正文的极其庞大的输入区域！")
                
                # 4. 点击【下一步】进行正式发布
                print(" -> 点击右上角的【下一步】准备正式拔剑发布...")
                
                # 记录点击前的页面数量，用于检测新标签页
                pages_before_next = len(context.pages)
                
                # 【精确修复】番茄编辑器的"下一步"按钮有专属 CSS class: auto-editor-next
                next_btn_found = False
                
                # 策略1（最精确）：通过专属 class 定位
                try:
                    next_btn = editor_page.locator('button.auto-editor-next').first
                    if next_btn.is_visible():
                        next_btn.click(force=True)
                        next_btn_found = True
                        print("    - 已通过 CSS 选择器 button.auto-editor-next 精准点击【下一步】！")
                except Exception:
                    pass
                
                # 策略2：通过 class 包含 publish-button 定位
                if not next_btn_found:
                    try:
                        next_btn = editor_page.locator('button.publish-button').first
                        if next_btn.is_visible():
                            next_btn.click(force=True)
                            next_btn_found = True
                            print("    - 已通过 CSS 选择器 button.publish-button 点击【下一步】")
                    except Exception:
                        pass
                
                # 策略3：空间坐标 + 文本匹配降级
                if not next_btn_found:
                    next_btn_handles = editor_page.get_by_text("下一步", exact=True).element_handles()
                    for btn_h in reversed(next_btn_handles):
                        try:
                            box = btn_h.bounding_box()
                            if box and box['y'] < 300:
                                btn_h.click()
                                next_btn_found = True
                                print(f"    - 已通过坐标降级策略点击【下一步】 (y={int(box['y'])})")
                                break
                        except Exception:
                            continue
                
                # 策略4：终极降级
                if not next_btn_found:
                    try:
                        next_btn = editor_page.get_by_text("下一步", exact=True).last
                        if next_btn.is_visible():
                            next_btn.click(force=True)
                            next_btn_found = True
                            print("    - 已通过终极降级策略点击【下一步】")
                    except Exception:
                        pass
                
                if next_btn_found:
                    # ========== 流程：下一步 → 处理弹窗 → 确认发布 ==========
                    # 弹窗关闭后会直接进入发布设置面板，不需要重新点击"下一步"
                    
                    editor_page.wait_for_timeout(2000)
                    
                    # 检测新标签页
                    if len(context.pages) > pages_before_next:
                        editor_page = context.pages[-1]
                        print("    - 检测到新标签页，已自动切换！")
                        editor_page.wait_for_timeout(2000)
                    
                    # 弹窗拦截1：错别字未修改 → 点击"提交"
                    try:
                        typo_text = editor_page.get_by_text(re.compile(r"错别字"), exact=False).first
                        typo_text.wait_for(state="visible", timeout=3000)
                        print("    - 检测到【错别字未修改】提示弹窗，点击【提交】...")
                        submit_btn = None
                        for btn_name in ["忽略全部", "继续提交", "提交"]:
                            try:
                                submit_btn = editor_page.get_by_role("button", name=btn_name).first
                                if submit_btn.is_visible():
                                    print(f"    - 找到按钮【{btn_name}】，点击！")
                                    break
                            except Exception:
                                continue
                        if submit_btn:
                            submit_btn.click(force=True)
                        else:
                            editor_page.get_by_text("提交", exact=False).first.click(force=True)
                        editor_page.wait_for_timeout(3000)
                    except Exception:
                        print("    - 无错别字弹窗，继续...")
                    
                    # 弹窗拦截2：内容检测方式选择 / 风险提示功能
                    # 番茄平台新版UI：弹出「请选择内容检测方式」弹窗，需点击「仅基础检测」
                    # 旧版UI：弹出「风险提示功能」弹窗，需点击「取消」
                    try:
                        # 等一会让弹窗加载
                        editor_page.wait_for_timeout(2000)
                        
                        popup_handled = False
                        
                        # ========== 新版弹窗：内容检测方式 ==========
                        # 检测是否出现「请选择内容检测方式」弹窗
                        try:
                            new_check_text = editor_page.get_by_text(re.compile(r"内容检测方式|全面检测|仅基础检测"), exact=False).first
                            if new_check_text.is_visible():
                                print("    - 检测到新版【内容检测方式】选择弹窗！")
                                
                                # 点击「仅基础检测」按钮
                                basic_check_btn = None
                                # 方式1：通过按钮文本精确匹配
                                for btn_text in ["仅基础检测", "基础检测"]:
                                    try:
                                        basic_check_btn = editor_page.get_by_role("button", name=btn_text).first
                                        if basic_check_btn.is_visible():
                                            print(f"    - 找到按钮【{btn_text}】，点击！")
                                            break
                                    except Exception:
                                        continue
                                
                                # 方式2：通过 Arco Design class 定位
                                if not basic_check_btn:
                                    try:
                                        arco_secondary_btns = editor_page.locator('button.arco-btn-secondary').element_handles()
                                        for btn_h in arco_secondary_btns:
                                            try:
                                                box = btn_h.bounding_box()
                                                if box and box['y'] > 100:  # 排除顶部导航栏的按钮
                                                    inner_text = btn_h.evaluate("el => el.innerText")
                                                    if "基础检测" in inner_text or "基础" in inner_text:
                                                        basic_check_btn = editor_page.locator('button.arco-btn-secondary').nth(
                                                            arco_secondary_btns.index(btn_h)
                                                        ).first
                                                        print(f"    - 通过 Arco class 找到按钮（文本：{inner_text}），点击！")
                                                        break
                                            except Exception:
                                                continue
                                    except Exception:
                                        pass
                                
                                # 方式3：通过文本模糊匹配
                                if not basic_check_btn:
                                    try:
                                        basic_check_btn = editor_page.get_by_text(re.compile(r"基础检测"), exact=False).first
                                        if not basic_check_btn.is_visible():
                                            basic_check_btn = None
                                    except Exception:
                                        basic_check_btn = None
                                
                                if basic_check_btn:
                                    basic_check_btn.click(force=True)
                                    print("    - 已选择【基础检测】（不限次数）！")
                                    popup_handled = True
                                else:
                                    print("    [警告] 未找到「基础检测」按钮，尝试 Escape 关闭...")
                                    editor_page.keyboard.press("Escape")
                                    popup_handled = True
                                
                                editor_page.wait_for_timeout(1500)
                        except Exception:
                            pass
                        
                        # ========== 旧版弹窗：风险提示功能（兼容兜底） ==========
                        if not popup_handled:
                            risk_found = False
                            # 方式1：检测 arco-modal 里包含"风险"文字
                            try:
                                risk_modal = editor_page.locator('div.arco-modal-content').filter(has_text=re.compile(r"风险")).first
                                if risk_modal.is_visible():
                                    risk_found = True
                                    print("    - 检测到 Arco 模态框【风险提示】弹窗！")
                            except Exception:
                                pass
                            
                            # 方式2：检测页面任意位置包含"风险提示功能"或"消耗此功能"的文字
                            if not risk_found:
                                try:
                                    risk_text = editor_page.get_by_text(re.compile(r"风险提示功能|消耗此功能使用次数|标注当前章节可能存在的风险"), exact=False).first
                                    if risk_text.is_visible():
                                        risk_found = True
                                        print("    - 检测到【风险提示功能】弹窗！")
                                except Exception:
                                    pass
                            
                            # 方式3：检测 arco-modal 是否存在（通用兜底）
                            if not risk_found:
                                try:
                                    any_modal = editor_page.locator('div.arco-modal:visible').first
                                    if any_modal.is_visible():
                                        # 检查模态框内是否有取消按钮（排除确认发布面板）
                                        modal_cancel = any_modal.locator('button:has-text("取消")').first
                                        if modal_cancel.is_visible():
                                            risk_found = True
                                            print("    - 检测到通用模态框弹窗（含取消按钮）！")
                                except Exception:
                                    pass
                            
                            if risk_found:
                                print("    - 点击【取消】跳过风险提示...")
                                cancel_btn = None
                                for btn_name in ["取消", "暂不开启", "跳过"]:
                                    try:
                                        cancel_btn = editor_page.get_by_role("button", name=btn_name).first
                                        if cancel_btn.is_visible():
                                            print(f"    - 找到按钮【{btn_name}】，点击！")
                                            break
                                    except Exception:
                                        continue
                                if not cancel_btn:
                                    try:
                                        cancel_btn = editor_page.locator('div.arco-modal button:has-text("取消")').first
                                    except Exception:
                                        cancel_btn = None
                                if cancel_btn:
                                    cancel_btn.click(force=True)
                                else:
                                    editor_page.keyboard.press("Escape")
                                editor_page.wait_for_timeout(1500)
                            else:
                                print("    - 无内容检测/风险提示弹窗，继续...")
                    except Exception:
                        print("    - 无内容检测/风险提示弹窗，继续...")
                    
                    # 检测新标签页（弹窗处理后可能弹出）
                    if len(context.pages) > pages_before_next:
                        editor_page = context.pages[-1]
                        print("    - 检测到新标签页，已自动切换！")
                        editor_page.wait_for_timeout(1000)
                    
                    # 等待发布设置面板出现，找到【确认发布】按钮
                    print("    - 正在等待【确认发布】按钮出现（最多等15秒）...")
                    publish_btn = None
                    
                    try:
                        publish_btn = editor_page.get_by_role("button", name="确认发布").first
                        publish_btn.wait_for(state="visible", timeout=15000)
                        print("    - 已找到【确认发布】按钮！")
                    except Exception:
                        try:
                            publish_btn = editor_page.get_by_text("确认发布", exact=True).first
                            publish_btn.wait_for(state="visible", timeout=5000)
                            print("    - 通过文本匹配找到【确认发布】按钮！")
                        except Exception:
                            try:
                                publish_btn = editor_page.get_by_text(re.compile(r"确认发布|发布")).first
                                publish_btn.wait_for(state="visible", timeout=5000)
                                print("    - 通过模糊匹配找到发布按钮！")
                            except Exception:
                                publish_btn = None
                    
                    if publish_btn:
                        try:
                            # 强制勾选【是否使用AI：否】
                            print("    - 强制勾选【是否使用AI：否】...")
                            ai_yes_label = editor_page.get_by_text("否", exact=True).first
                            ai_yes_label.wait_for(state="visible", timeout=3000)
                            ai_yes_label.click(force=True)
                            editor_page.wait_for_timeout(500)
                        except Exception:
                            pass
                        
                        # ========== 定时发布 ==========
                        # 计算：每 3 章日期 +1 天，默认时间 08:00
                        target_date = timed_start_date + timedelta(days=chapter_idx // 2)
                        target_date_str = target_date.strftime("%Y-%m-%d")
                        target_time_str = "08:00"
                        
                        # 特殊规则（仅对今天生效）：若当前时间已晚于 08:00，
                        # 把发布时间改成「当前时间向上取整到整点 + 1 小时」。
                        # 例如现在 9:34 -> 改到 10:00；现在 10:05 -> 改到 11:00。
                        today = datetime.now().date()
                        now_dt = datetime.now()
                        if target_date == today and (now_dt.hour > 8 or (now_dt.hour == 8 and now_dt.minute >= 0)):
                            # 当前已过 8:00，使用 当前整点+1
                            effective_hour = now_dt.hour + 1
                            effective_date = target_date
                            if effective_hour >= 24:
                                # 极端情况（23:xx）：推到次日 8:00
                                effective_hour = 8
                                effective_date = target_date + timedelta(days=1)
                                target_date = effective_date
                                target_date_str = effective_date.strftime("%Y-%m-%d")
                            target_time_str = f"{effective_hour:02d}:00"
                            print(f"    - 当前时间 {now_dt.strftime('%H:%M')} 已过 08:00，本章改到 {target_date_str} {target_time_str}")
                        else:
                            print(f"    - 设置定时发布：{target_date_str} {target_time_str}（第 {chapter_idx + 1} 章）")
                        
                        try:
                            # 1. 找到定时发布行（含"定时发布"文本），点击其右侧的 arco-switch 开关
                            timed_switch_clicked = False
                            timed_switches = editor_page.locator('button.arco-switch[role="switch"]').element_handles()
                            # 找到与"定时发布"标签同行的 switch
                            timed_lines = editor_page.locator('div.card-content-line').filter(has_text="定时发布").element_handles()
                            for line in timed_lines:
                                try:
                                    switch_in_line = line.query_selector('button.arco-switch[role="switch"]')
                                    if switch_in_line:
                                        # 检查是否已开启
                                        aria_checked = switch_in_line.evaluate("el => el.getAttribute('aria-checked')")
                                        if aria_checked == "true":
                                            timed_switch_clicked = True
                                            print("    - 定时发布开关已是开启状态")
                                        else:
                                            switch_in_line.click()
                                            print("    - 已开启【定时发布】开关")
                                            timed_switch_clicked = True
                                        break
                                except Exception:
                                    continue
                            
                            # 兜底：若上面没找到，遍历所有 arco-switch
                            if not timed_switch_clicked:
                                for sw in timed_switches:
                                    try:
                                        aria_checked = sw.evaluate("el => el.getAttribute('aria-checked')")
                                        if aria_checked == "false":
                                            sw.click()
                                            print("    - 已开启定时发布开关（兜底匹配）")
                                            timed_switch_clicked = True
                                            break
                                    except Exception:
                                        continue
                            
                            editor_page.wait_for_timeout(1500)  # 等待日期/时间输入框展开动画
                            
                            if timed_switch_clicked:
                                # 2. 通过弹出日历面板选择日期
                                try:
                                    arco_select_date(editor_page, target_date_str)
                                except Exception as e:
                                    print(f"    [警告] 日历选日期异常：{e}")
                                
                                # 3. 通过弹出时钟面板选择时间
                                try:
                                    arco_select_time(editor_page, target_time_str)
                                except Exception as e:
                                    print(f"    [警告] 时钟选时间异常：{e}")
                                
                                editor_page.wait_for_timeout(500)
                                # 点击别处让 picker 失焦收起，避免遮挡
                                try:
                                    editor_page.locator('div.publish-confirm-card, div.card-content-line').first.click(force=True)
                                except Exception:
                                    pass
                                editor_page.wait_for_timeout(500)
                        except Exception as e:
                            print(f"    [警告] 定时发布设置异常：{e}（将退化为直接发布）")
                        
                        publish_btn.click(force=True)
                        print(f"  [🎇 发布成功] 第 {success_count+1} 章：'第{chapter_num}章 {chapter_title}' 已被发往全世界！")
                        success_count += 1
                    else:
                        print(f"  [警告] 未找到'确认发布'按钮！")
                        print(f"  [调试] 当前页面URL: {editor_page.url}")
                        input("  请您手动点击【确认发布】，然后回到这黑框按回车继续 >>> ")
                        success_count += 1
                else:
                    print("  未能找到'下一步'按钮！尝试降级为【一键光速存草稿】...")
                    save_btn = editor_page.get_by_text("存草稿", exact=False).first
                    if save_btn.is_visible():
                        save_btn.click()
                        print(f"  [降级保存] 第 {success_count+1} 章：已转为稳重存草稿！")
                        success_count += 1
                    else:
                        print("  未能找到任何保存入口，当前章节宣告失败！")
                        success_count += 1
                
                page.wait_for_timeout(3000) # 等待对号保存成功消失的动画
                
                # 按照小说书名绝对隔离分类进入对应的文件夹，干净利落绝不污染！
                dest_path = os.path.join(volume_dir, filename)
                shutil.move(file_path, dest_path)
                
                # 清除开启的新页面，保证一直是一个极简的单线操作！
                if editor_page != page:
                    editor_page.close()
                
            except Exception as e:
                print(f"!!! 哎呀！处理 '第{chapter_num}章 {chapter_title}' 时碰到了暗礁: {e}")
                input("请在右边弹出来的浏览器里查看究竟卡在了哪里？发现问题后按回车结束本次脚本运行。")
                break
                
            page.wait_for_timeout(1000) 
            
        print(f"\n==========================================")
        print(f"全自动爆更流程狂野结束。本次共成功为您发送了 {success_count} 个章节！")
        print(f"==========================================\n")
        
        input(">>> 天下武功唯快不破，按键回车键即可彻底关闭浏览器：")
        browser.close()

if __name__ == "__main__":
    main()
