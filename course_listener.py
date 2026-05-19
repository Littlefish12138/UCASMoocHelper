"""
视频自动播放与翻页脚本（重构版）
功能：
1. 支持多种浏览器启动模式（Edge/Chrome，普通/无痕，或连接已启动的调试端口）
2. 封装页面操作，便于维护
3. 使用双端队列管理任务，失败自动重试
4. 监控视频暂停并自动恢复播放
"""

import time
import subprocess
import threading
from collections import deque
import os
import json
from DrissionPage import ChromiumPage, ChromiumOptions
from copy import deepcopy
from _locator import ElementLocator

import utils

# ================== 报错类 ==================
class AnswerNotFoundError(Exception):
    def __init__(self, data):
        self.data = data
        super().__init__(f"答案中没有 data 为{data}的试题")

class AnswerMisMatchError(Exception):
    def __init__(self, data, is_stem_match=True, is_option_match=True):
        self.data = data
        self.stem_match = "题干不匹配" if not is_stem_match else ""
        self.option_match = "选项不匹配" if not is_option_match else ""
        super().__init__(f"data: {data}的试题",self.stem_match,self.option_match)

class ElementNotFoundError(Exception):
    def __init__(self, locator):
        self.locator = locator
        super().__init__(f"locator: {locator}的元素未找到")

# ================== 配置区域（选择器、关键字等） ==================
class PageConfig:
    """页面元素选择器和请求关键字配置"""
    # 视频元素 selector
    VIDEO = "tag:video"

    # 视频区域按钮的locator
    VIDEO_BUTTON = '#dct1'
    # 章节测验区域按钮的locator
    QUESTION_BUTTON = '#dct2'
    # 章节测验区域对应 iframe的locator
    QUESTION_IFRAME = '#frame_content'

    # 任务点是否完成，对应元素的 locator
    IS_JOB_FINISHED = '.^ans-job-icon'

    # 任务完成图片请求关键字
    COMPLETE_IMAGE_KEYWORD = "job-status-new-complete"

    # 提交答案按钮的 locator
    SUBMIT_BUTTON = 'css:#RightCon > div.radiusBG > div > div.ZY_sub.clearfix > a.Btn_blue_1.marleft10.workBtnIndex'
    # 确定提交答案按钮的 locator
    CONFIRM_BUTTON = 'css:#confirmSubWin > div > div > a.bluebtn'

    TIMEOUT = 0.5 # 查找页面固定元素的超时时间
    LOAD_TIMEOUT = 10 # 等待页面元素加载的超时时间

# ================== 浏览器启动器 ==================
class BrowserLauncher:
    """浏览器启动器，支持多种启动模式"""
    # 默认浏览器路径和用户数据目录
    DEFAULT_PATHS = {
        'edge': {
            'browser_path': r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        },
        'chrome': {
            'browser_path': r"C:\Program Files\Google\Chrome\Application\chrome.exe",  
        }
    }

    @staticmethod
    def kill_browser_process(browser_type='edge'):
        """强制结束浏览器进程"""
        if browser_type == 'edge':
            subprocess.run(['taskkill', '/F', '/IM', 'msedge.exe'], capture_output=True)
        elif browser_type == 'chrome':
            subprocess.run(['taskkill', '/F', '/IM', 'chrome.exe'], capture_output=True)

    @classmethod
    def launch_with_user_data(cls, browser_type='edge', browser_path=None, user_data_dir=None):
        """模式1: 自动启动浏览器, 使用指定用户数据目录"""
        # 如果未传入浏览器路径，尝试使用默认路径
        if browser_path is None:
            browser_path = cls.DEFAULT_PATHS[browser_type]['browser_path']
        if user_data_dir is None:
            raise ValueError("错误: 未输入用户数据目录")

        # 如果用户使用默认数据目录，终止当前正在运行的 Edge 实例以避免冲突
        if user_data_dir == utils.get_edge_user_data_dir():
            print("尝试结束当前 Edge 实例")
            cls.kill_browser_process(browser_type)
        time.sleep(2)

        print(f"正在启动 {browser_type.capitalize()} 浏览器...")
        co = ChromiumOptions()
        co.set_local_port(9444)
        co.set_user_data_path(user_data_dir)
        co.set_browser_path(browser_path)
        page = ChromiumPage(co)
        print(f"{browser_type.capitalize()} 浏览器已启动")
        return page

    @classmethod
    def launch_incognito(cls, browser_path: str):
        """
        模式2: 无痕模式启动浏览器\n
        :param browser_type: 浏览器类型
        :param login_callback: 登录回调函数
        """
        #incognito_args = []
        # edge 和 chrome 的无痕启动参数是不同的
        """if browser_type == 'edge':
            incognito_args = ['--inprivate']
        elif browser_type == 'chrome':
            incognito_args = ['--incognito']"""

        # 使用临时用户数据目录（无痕模式会自动创建临时目录）
        if browser_path is None:
            raise ValueError("错误：浏览器路径为空")
        co = ChromiumOptions()
        co.set_local_port(9445)
        co.set_browser_path(browser_path)
        co.set_argument('--new-window')
        co.incognito(True)
        """for arg in incognito_args:
            co.set_argument(arg)"""

        page = ChromiumPage(co)
        return page

    @classmethod
    def connect_to_existing(cls, port=9222):
        """模式3: 连接到已启动的调试端口浏览器"""
        print(f"正在连接到调试端口为 {port} 的浏览器...")
        co = ChromiumOptions()
        co.set_local_port(port)
        page = ChromiumPage(co)
        return page

# ================== 课程页面操作处理器 ==================
class CourseHandler:
    def __init__(self, page: ChromiumPage, course_tree_config: dict, *,log_callback = print, video_needed = True, question_needed = False, question_config: dict = {}, answers: dict = {}):
        self.page = page
        self.course_tree_config = deepcopy(course_tree_config)
        self.log_callback = log_callback
        self._course_tree = CourseHandler.get_course_tree(page, course_tree_config)
        self.video_needed = video_needed
        self.question_needed = question_needed
        self._question_config = deepcopy(question_config) if question_config else {}
        self._answers = deepcopy(answers) if answers else {}
    
    @staticmethod
    def get_course_tree(page: ChromiumPage, course_tree_config: dict):
        """读取课程树，返回字典"""
        locator = ElementLocator(page, course_tree_config)
        return locator.extract_info()

    def is_video(self):
        """等待加载，判断当前页面中是否有视频"""
        is_exist = self.page.wait.eles_loaded(PageConfig.VIDEO,timeout=PageConfig.LOAD_TIMEOUT,any_one=True)
        return is_exist

    def is_completed(self):
        """等待加载，查找任务点已完成元素是否存在，如果存在返回True/False，不存在返回报错"""
        is_exist = self.page.wait.eles_loaded(PageConfig.IS_JOB_FINISHED,timeout=PageConfig.LOAD_TIMEOUT,any_one=True)
        if is_exist:
            job_element = self.page.ele(PageConfig.IS_JOB_FINISHED,timeout=PageConfig.TIMEOUT)
            if job_element:
                return job_element.attr("aria-label") == '任务点已完成'
            else:
                return ElementNotFoundError(PageConfig.IS_JOB_FINISHED)
        else:
            raise ElementNotFoundError(PageConfig.IS_JOB_FINISHED)

    def keep_video_play(self):
        """
        确保视频开始播放。如果已播放则无操作，否则点击播放按钮。
        返回 True 表示视频已可播放，False 表示无法处理。
        """
        try:
            video_element = self.page.ele(PageConfig.VIDEO)
            video_element.run_js("this.play()")
        except Exception as e:
            self.log_callback(f"执行视频播放异常: {e}")
            return False
    
    def listen_complete_image(self, timeout=3600) -> bool:
        """监听器：监听任务完成图片，成功截获则返回True"""
        self.log_callback("开始等待视频完成图片...")
        self.page.listen.start(PageConfig.COMPLETE_IMAGE_KEYWORD)
        packet = self.page.listen.wait(count=1, timeout=timeout)
        self.page.listen.stop()
        if packet and PageConfig.COMPLETE_IMAGE_KEYWORD in packet.url:
            self.log_callback(f"检测到视频完成图片: {packet.url}")
            return True
        else:
            self.log_callback(f"等待{timeout}未收到完成图片，认定为超时")
            return False
    
    def get_to_questions(self):
        """
        通过点击，切换到章节测试的部分，等待页面上出现章节测试对应的iframe元素时返回。
        """
        is_exist = self.page.wait.eles_loaded(PageConfig.QUESTION_BUTTON,timeout=PageConfig.LOAD_TIMEOUT,any_one=True)
        if is_exist:
            ques_btn = self.page.ele(PageConfig.QUESTION_BUTTON,timeout=PageConfig.TIMEOUT)
            ques_btn.click()
            page.wait.eles_loaded(PageConfig.QUESTION_IFRAME,timeout=PageConfig.LOAD_TIMEOUT,any_one=True)
            return True
        else:
            self.log_callback(f"错误：等待{PageConfig.LOAD_TIMEOUT}仍未出现章节测试按钮")
            return False
    
    def get_to_video(self):
        """
        通过点击，切换到视频播放的部分，等待视频出现之后返回
        """
        is_exist = self.page.wait.eles_loaded(PageConfig.VIDEO_BUTTON,timeout=PageConfig.LOAD_TIMEOUT,any_one=True)
        if is_exist:
            video_btn = self.page.ele(PageConfig.VIDEO_BUTTON,timeout=PageConfig.TIMEOUT)
            video_btn.click()
            self.page.wait.eles_loaded(PageConfig.VIDEO,timeout=PageConfig.LOAD_TIMEOUT,any_one=True)
            return True
        else:
            self.log_callback("错误：未找到视频区域对应的按钮")
            return False

    def generate_task(self) -> deque:
        """
        生成一个队列，将所有课程任务添加到队列中，每个课程任务是一个字典，内部键'click_callback'存有点击回调
        """
        tasks = deque()
        chapters: list[dict] = self._course_tree.get('chapters')
        if chapters:
            for chapter in chapters:
                sections: list[dict] = chapter.get('sections')
                if sections:
                    for section in sections:
                        click_callback_js = section.get('click_callback_js')
                        title = section.get('title')
                        tasks.append({'click_callback':click_callback_js,
                                      'title':title})
        return tasks

    # ================== 主业务函数 ==================
    def finish_video(self):
        """
        挂完一个视频，无论是超时完成还是正常完成\n
        """
        success = False
        def listen_complete_image(finish_event: threading.Event):
            nonlocal success
            success = self.listen_complete_image()
            finish_event.set()
        
        def keep_video_play(finish_event: threading.Event):
            while not finish_event.is_set():
                self.keep_video_play()
                time.sleep(10)
        
        finish_event = threading.Event()
        listen_thread = threading.Thread(target=listen_complete_image, args=(finish_event,))
        keep_thread = threading.Thread(target=keep_video_play, args=(finish_event,))

        listen_thread.start()
        keep_thread.start()

        listen_thread.join()
        keep_thread.join()

        return success

    def finish_questions(self):
        """
        完成一个视频的章节测试题，出问题则中断并返回False，正常则返回True
        """
        locator = ElementLocator(self.page, self._question_config, {'data','stem','option_content','click_callback','judgement'})
        try:
            questions: dict = locator.extract_info()

            question_list = questions.get('questions')
            for question in question_list:
                data = question['data']
                answer: dict = self._answers.get(data)
                if answer is not None:
                    options: list = question['options']
                    # ===================== 检查逻辑 =====================
                    # 题干是否一致
                    stem: str = question['stem']
                    if answer.get('question') and stem != answer['question']:
                        self.log_callback(f"完成课程链接{self.page.url}的章节测试题时出错：data为{data}的试题，题干为{stem}\n与答案中不一致")
                        raise AnswerMisMatchError(data,is_option_match=False)
                    # 选项是否一致
                    if stem.startswith(('【单选题】','【多选题】')):
                        contents = set()
                        for option in options:
                            contents.add(option['content'])
                        if answer.get('options') and set(answer['options']) != contents:
                            self.log_callback(f"完成课程链接{self.page.url}的章节测试题：data为{data}的试题，选项为{options}与答案中不一致")
                            raise AnswerMisMatchError(data,is_option_match=False)
                    
                    # ===================== 通过点击以做题 =====================
                    if stem.startswith(('【单选题】','【多选题】')):
                        for option in options:
                            if option['content'] in answer['answer']:
                                click_callback = option['click_callback']
                                click_callback()
                    elif stem.startswith('【判断题】'):
                        for option in options:
                            if option['judgement'] == answer['answer']:
                                click_callback = option['click_callback']
                                click_callback()
                else:
                    self.log_callback(f"完成课程链接{self.page.url}的章节测试题时出错：答案中没有data为{data}的试题")
                    raise AnswerNotFoundError(data)
            return True
        except Exception as e:
            self.log_callback(f"在尝试完成课程链接为{self.page.url}的章节测试题时出错{e}")
            return False

    def submit_answers(self):
        try:
            submit_button = self.page.ele(PageConfig.SUBMIT_BUTTON)
            if submit_button:
                submit_button.click()
                time.sleep(2)
                confirm_button = self.page.ele(PageConfig.CONFIRM_BUTTON)
                if confirm_button:
                    confirm_button.click()
                    return True
                else:
                    self.log_callback(f"尝试提交时出错：确认提交按钮未找到")
                    return False
            else:
                self.log_callback(f"尝试提交时出错：提交按钮未找到")
                return False
        except Exception as e:
            self.log_callback(f"尝试提交时出错：{e}")
            return False
        
    def run_course_task(self) -> list:
        """
        按照要求完成全部任务，返回不可正常完成的列表\n
        """
        
        tasks = self.generate_task()
        failed_list = []

        task_index = 1
        task_length = len(tasks)

        self.log_callback(f"总任务数: {task_length}")
        self.log_callback("开始处理任务队列...\n")
        # 处理任务
        while tasks:
            task: dict = tasks.popleft()

            self.log_callback(f"\n正在处理第 {task_index} / {task_length} 个视频...")

            try:
                # 点击视频，跳转到对应页面
                task.get('click_callback')()

                # 检查是否为视频
                if not self.is_video():
                    self.log_callback("当前章节不是视频，跳过")
                    task_index += 1
                    continue

                if self.video_needed and (not self.is_completed()):
                    success = self.finish_video()
                    if success:
                        self.log_callback(f"课程链接{self.page.url}视频播放完成")
                    else:
                        self.log_callback(f"播放课程链接{self.page.url}时出现错误，未完成，重新添加到队列中")
                        tasks.append(task)

                time.sleep(2)
                if self.question_needed:
                    self.get_to_questions()
                    time.sleep(2)
                    if not self.is_completed():
                        try:
                            self.finish_questions()
                            self.submit_answers()
                        except (AnswerMisMatchError, AnswerNotFoundError) as e:
                            self.log_callback(f"\n完成课程{task['title']}的章节测试题时出错: {e}, 不可恢复错误")
                            failed_list.append(task['title'])
                            continue
                        except Exception as e:
                            self.log_callback(f"\n完成课程{task['title']}的章节测试题时出错: {e}, 重新添加到队列中")
                            tasks.append(task)
            except Exception as e:
                self.log_callback(f"完成课程{task['title']}时出现错误{e}，重新添加到队列中")
                tasks.append(task)
            
            task_index += 1

        self.log_callback("\n所有视频已处理完毕")

    def get_all_questions(self) -> dict:
        tasks = self.generate_task()

        task_index = 1
        task_length = len(tasks)
        question_dict = {}
        while tasks:
            task: dict = tasks.popleft()

            self.log_callback(f"\n正在处理第 {task_index} / {task_length} 个视频...")

            try:
                # 点击视频，跳转到对应页面
                task.get('click_callback')()

                # 检查是否为视频
                if not self.is_video():
                    self.log_callback("当前章节不是视频，跳过")
                    task_index += 1
                    continue
                
                self.get_to_questions()
                
                locator = ElementLocator(self.page, self._question_config, {'data','stem','options','name_and_content','my_answer','is_answer_correct'})
                result = locator.extract_info()
                self.log_callback("提取结果\n",result)

                for question in result.get('questions'):
                    data = question['data']
                    question_dict[data] = question
                
                task_index += 1

            except Exception as e:
                self.log_callback(f"处理视频{task['title']}时出错: {e}，回到队列等待重试")
                tasks.append(task)

        self.log_callback("\n所有视频的章节测试题读取完成")

        return question_dict

if __name__ == "__main__":
    page = BrowserLauncher.launch_with_user_data(user_data_dir=utils.get_edge_user_data_dir())

    with open("_pageconfig/question_element.json", 'r', encoding='utf-8') as f:
        question_config = json.load(f)
    
    with open(r"F:\coding\UCAS_Mooc_Helper\_pageconfig\course_tree_element.json",'r',encoding='utf-8') as f:
        course_tree_config = json.load(f)
    
    #with open("_course/军事理论/军事理论_2025-2026秋季.json",'r',encoding='utf-8') as f:
    #    answers = json.load(f)

    page = ChromiumPage(9444)

    page.get('https://mooc.mooc.ucas.edu.cn/mooc-ans/mycourse/studentstudy?chapterId=577472&courseId=350140000037227&clazzid=350140000031973&enc=f1220c4fcaa1db6d27eefea233837606')
    #time.sleep(10)
    print("开始")
    ch = CourseHandler(page, course_tree_config, log_callback=print,video_needed=True,question_needed=True,question_config=question_config)

    questions = ch.get_all_questions()
    

    with open(r"F:\coding\UCAS_Mooc_Helper\_course\军事理论\军事理论_2025-2026学期5月.json", 'w', encoding='utf-8') as f:
        json.dump(questions, f, ensure_ascii=False, indent=4)
    
    r"""page = ChromiumPage(9444)
    input("回车以开始")
    while True:
        print("找到iframe元素\n") if page.ele("#frame_content",timeout=0.1) else print("未找到iframe\n")
        print("找到ZyBottom元素\n") if page.ele(".ZyBottom",timeout=0.1) else print("未找到ZyBottom\n")
        
        page.wait.eles_loaded()

        time.sleep(0.5)"""