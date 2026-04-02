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
from DrissionPage import ChromiumPage, ChromiumOptions

import utils
# ================== 配置区域（选择器、关键字等） ==================
class PageConfig:
    """页面元素选择器和请求关键字配置"""
    # 课程树根元素
    COURSE_TREE = "#coursetree"
    # 章节容器
    CHAPTER_CONTAINER = "#coursetree .cells"
    # 章节标题（用于展开）
    CHAPTER_TITLE = "#coursetree .cells > h3"
    # 视频链接容器
    VIDEO_LINK_CONTAINER = ".ncells a"
    # 已完成图标（视频页面）
    COMPLETED_ICON = "#ext-gen1051"  # 或 '.ans-job-icon.ans-job-icon-clear'
    # 播放按钮（初始播放）
    PLAY_BUTTON = "#video > button"  # 可改为 '.vjs-big-play-button'
    # 播放/暂停控制按钮（用于恢复播放）
    PLAY_PAUSE_CONTROL = ".vjs-play-control"
    # 任务完成图片请求关键字
    COMPLETE_IMAGE_KEYWORD = "job-status-new-complete"

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
    def launch_incognito(cls, browser_type='edge', login_callback=None):
        """
        模式2: 无痕模式启动, 等待登录完成信号\n
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
        co = ChromiumOptions()
        co.set_local_port(9445)
        co.set_argument('--new-window')
        co.incognito(True)
        """for arg in incognito_args:
            co.set_argument(arg)"""

        page = ChromiumPage(co)

        print("已启动无痕模式浏览器，请手动登录...")
        if login_callback:
            # 等待登录完成信号（如用户输入或事件）
            login_callback()
        else:
            input("登录完成后按回车继续...")

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
class CoursePageHandler:
    """封装所有与课程页面相关的操作"""
    def __init__(self, page: ChromiumPage, config: PageConfig):
        self.page = page
        self.config = config
        self.listen_thread = None
        self.stop_event = None

    def expand_all_chapters(self):
        """展开所有章节"""
        js = f"""
            var chapters = document.querySelectorAll('{self.config.CHAPTER_TITLE}');
            for (var i = 0; i < chapters.length; i++) {{
                chapters[i].click();
            }}
            return chapters.length;
        """
        count = self.page.run_js(js)
        print(f"已尝试展开 {count} 个章节")
        time.sleep(0.5)

    def get_chapter_video_counts(self) -> list:
        """获取每个章节下的视频数量，返回列表"""
        js = f"""
            var cellsList = document.querySelectorAll('{self.config.CHAPTER_CONTAINER}');
            var counts = [];
            for (var i = 0; i < cellsList.length; i++) {{
                var videoLinks = cellsList[i].querySelectorAll('{self.config.VIDEO_LINK_CONTAINER}');
                counts.push(videoLinks.length);
            }}
            return counts;
        """
        return self.page.run_js(js)

    def click_video_by_index(self, chap_index, video_index):
        """点击指定章节下的指定视频"""
        js = f"""
            var cellsList = document.querySelectorAll('{self.config.CHAPTER_CONTAINER}');
            if (cellsList.length < {chap_index}) return false;
            var targetCells = cellsList[{chap_index - 1}];
            var videoLinks = targetCells.querySelectorAll('{self.config.VIDEO_LINK_CONTAINER}');
            if (videoLinks.length < {video_index}) return false;
            var targetLink = videoLinks[{video_index - 1}];
            targetLink.click();
            return true;
        """
        return self.page.run_js(js)

    def is_video_completed(self) -> bool:
        """
        判断当前视频是否已完成\n
        方法为检查是否存在“任务点已完成字样”
        """
        icon = self.page.ele(self.config.COMPLETED_ICON, timeout=2)
        if icon:
            aria_label = icon.attr('aria-label')
            return aria_label == "任务点已完成"
        return False

    def click_play_button(self):
        """点击初始播放按钮"""
        try:
            play_button = self.page.ele(f"css:{self.config.PLAY_BUTTON}")
            if play_button:
                play_button.click()
                print("已点击播放按钮")
                return True
            else:
                print("未找到播放按钮，可能已自动播放")
                return False
        except Exception as e:
            print(f"点击播放按钮异常: {e}")
            return False

    def start_playback_monitor(self):
        """启动监控线程，检测视频暂停并恢复播放"""
        self.stop_event = threading.Event()
        def monitor():
            while not self.stop_event.is_set():
                try:
                    play_btn = self.page.ele(f"css:{self.config.PLAY_PAUSE_CONTROL}", timeout=2)
                    if play_btn:
                        title = play_btn.attr('title')
                        if title == "播放":
                            play_btn.click()
                            print("检测到视频暂停，已重新播放")
                except Exception:
                    pass
                # 分段睡眠以便及时响应停止事件
                for _ in range(50):
                    if self.stop_event.is_set():
                        break
                    time.sleep(0.1)
        self.listen_thread = threading.Thread(target=monitor, daemon=True)
        self.listen_thread.start()

    def stop_playback_monitor(self):
        """停止监控线程"""
        if self.stop_event:
            self.stop_event.set()
            if self.listen_thread:
                self.listen_thread.join(timeout=1)

    def wait_for_complete_image(self, timeout=3600):
        """监听任务完成图片，返回是否成功"""
        print("等待视频完成图片...")
        self.page.listen.start(self.config.COMPLETE_IMAGE_KEYWORD)
        packet = self.page.listen.wait(count=1, timeout=timeout)
        self.page.listen.stop()
        if packet and self.config.COMPLETE_IMAGE_KEYWORD in packet.url:
            print(f"检测到视频完成图片: {packet.url}")
            return True
        else:
            print("等待超时，未收到完成图片")
            return False

# ================== 主业务函数 ==================
def run_video_task(launch_func: function, course_url):
    """
    执行挂课任务的主函数\n
    :param launch_func: 可调用对象,返回ChromiumPage实例,应为BrowserLauncher下的launch_with_user_data或者launch_incognito
    :param course_url: 课程视频页面url,为None则提示用户输入
    """
    page = launch_func()

    if course_url is None:
        raise ValueError("错误：课程链接为空")
    
    # 打开课程页面
    #course_url = input("请输入课程页面链接：").strip()
    #if not course_url:
    #    course_url = "http://mooc.mooc.ucas.edu.cn/mooc-ans/mycourse/studentstudy?chapterId=577476&courseId=350140000037227&clazzid=350140000031973&enc=f1220c4fcaa1db6d27eefea233837606"
    
    page.get(course_url)
    time.sleep(3)

    # 创建页面处理器
    handler = CoursePageHandler(page, PageConfig)

    # 展开章节
    # handler.expand_all_chapters()  # 可选，根据页面是否需要展开

    # 获取视频数量
    video_counts = handler.get_chapter_video_counts()
    total_chapters = len(video_counts)
    print(f"检测到 {total_chapters} 章")

    if total_chapters == 0:
        print("未检测到章节，请检查页面结构")
        return

    # 构建任务队列
    tasks = deque()
    for chap_idx in range(1, total_chapters + 1):
        video_num = video_counts[chap_idx - 1]
        print(f"第 {chap_idx} 章共有 {video_num} 个视频")
        for vid_idx in range(1, video_num + 1):
            tasks.append((chap_idx, vid_idx))

    print(f"总任务数: {len(tasks)}")
    print("开始处理任务队列...\n")

    # 处理任务
    while tasks:
        chap_idx, vid_idx = tasks.popleft()
        print(f"\n正在处理第 {chap_idx} 章第 {vid_idx} 个视频...")

        # 点击视频
        if not handler.click_video_by_index(chap_idx, vid_idx):
            print(f"点击视频失败，将重新加入队列")
            tasks.append((chap_idx, vid_idx))
            time.sleep(2)
            continue

        time.sleep(4)  # 等待页面刷新

        # 检查是否已完成
        if handler.is_video_completed():
            print("该视频已完成，跳过")
            continue

        # 点击播放按钮
        handler.click_play_button()

        # 启动监控线程
        handler.start_playback_monitor()

        # 等待完成图片
        success = handler.wait_for_complete_image(timeout=3600)

        # 停止监控
        handler.stop_playback_monitor()

        if not success:
            print("视频播放超时，等待进行重试")
            tasks.append((chap_idx, vid_idx))

        time.sleep(1)

    print("\n所有视频已处理完毕")
    input("按回车退出...")

if __name__ == "__main__":
    def default_launch():
        return BrowserLauncher.launch_with_user_data(browser_type='edge')

    run_video_task(default_launch)