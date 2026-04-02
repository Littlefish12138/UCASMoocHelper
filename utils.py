"""
读取注册表，找用户安装的edge和chrome的位置
"""
import os
import winreg
import sys

def _expand_and_validate(path):
    """展开环境变量并验证路径是否存在"""
    if not path:
        return None
    expanded = os.path.expandvars(path)
    if os.path.isfile(expanded):
        return expanded
    return None

def _get_from_app_paths(exe_name, use_wow64_views=False):
    """
    从 App Paths 注册表项读取程序路径
    exe_name: 可执行文件名，如 'chrome.exe'
    use_wow64_views: 若为 True，依次尝试 64位、32位视图；否则仅尝试默认视图
    """
    subkey = f"SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths\\{exe_name}"
    hives = [winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER]
    views = []
    if use_wow64_views:
        # 优先使用 64位视图，再使用 32位视图
        views = [winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY]
    else:
        views = [0]  # 默认视图（不指定标志）

    for hive in hives:
        for view in views:
            try:
                access = winreg.KEY_READ | view if view != 0 else winreg.KEY_READ
                with winreg.OpenKey(hive, subkey, 0, access) as key:
                    path, _ = winreg.QueryValueEx(key, None)  # 默认值
                    valid = _expand_and_validate(path)
                    if valid:
                        return valid
            except WindowsError:
                continue
    return None

def _get_from_install_key(hive, subkey, value_name, view=0):
    """从指定注册表键读取安装路径"""
    try:
        access = winreg.KEY_READ | view if view != 0 else winreg.KEY_READ
        with winreg.OpenKey(hive, subkey, 0, access) as key:
            path, _ = winreg.QueryValueEx(key, value_name)
            return _expand_and_validate(path)
    except WindowsError:
        return None

def get_chrome_path():
    """
    获取 Google Chrome 的可执行文件路径
    依次尝试：
      1. App Paths 中的 chrome.exe(尝试两个 hive 和两个视图)
      2. HKEY_LOCAL_MACHINE\\SOFTWARE\\Google\\Chrome 下的 "ProgramPath"
      3. HKEY_CURRENT_USER\\SOFTWARE\\Google\\Chrome 下的 "ProgramPath"
      4. 备用：HKEY_LOCAL_MACHINE\\SOFTWARE\\Google\\Update\\Clients 下的安装路径（较少用）
    返回有效路径字符串，若未找到则返回 None
    """
    # 1. App Paths
    path = _get_from_app_paths("chrome.exe", use_wow64_views=True)
    if path:
        return path

    # 2. 标准注册表键
    for hive, subkey, value in [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Google\Chrome", "ProgramPath"),
        (winreg.HKEY_CURRENT_USER,  r"SOFTWARE\Google\Chrome", "ProgramPath"),
    ]:
        # 尝试 64位视图
        path = _get_from_install_key(hive, subkey, value, winreg.KEY_WOW64_64KEY)
        if path:
            return path
        # 尝试 32位视图
        path = _get_from_install_key(hive, subkey, value, winreg.KEY_WOW64_32KEY)
        if path:
            return path

    # 3. 备用：通过 Google Update 客户端查找（可选）
    #    部分安装会在 Clients 键下存储安装路径，但并非所有版本都包含，此处仅作扩展
    try:
        subkey = r"SOFTWARE\Google\Update\Clients\{8A69D345-D564-463C-AFF1-A69D9E530F96}"  # Chrome 的 GUID
        path = _get_from_install_key(winreg.HKEY_LOCAL_MACHINE, subkey, "InstalledPath",
                                     winreg.KEY_WOW64_64KEY)
        if path:
            return path
        path = _get_from_install_key(winreg.HKEY_LOCAL_MACHINE, subkey, "InstalledPath",
                                     winreg.KEY_WOW64_32KEY)
        if path:
            return path
    except Exception:
        pass

    return None

def get_edge_path():
    """
    获取 Microsoft Edge 的可执行文件路径
    依次尝试：
      1. App Paths 中的 msedge.exe（尝试两个 hive 和两个视图）
      2. HKEY_LOCAL_MACHINE\\SOFTWARE\\Microsoft\\Edge 下的 "InstallPath"
      3. HKEY_CURRENT_USER\\SOFTWARE\\Microsoft\\Edge 下的 "InstallPath"
    返回有效路径字符串，若未找到则返回 None
    """
    # 1. App Paths
    path = _get_from_app_paths("msedge.exe", use_wow64_views=True)
    if path:
        return path

    # 2. 标准注册表键
    for hive, subkey, value in [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Edge", "InstallPath"),
        (winreg.HKEY_CURRENT_USER,  r"SOFTWARE\Microsoft\Edge", "InstallPath"),
    ]:
        # 尝试 64位视图
        path = _get_from_install_key(hive, subkey, value, winreg.KEY_WOW64_64KEY)
        if path:
            return path
        # 尝试 32位视图
        path = _get_from_install_key(hive, subkey, value, winreg.KEY_WOW64_32KEY)
        if path:
            return path

    return None

def get_edge_user_data_dir():
    """
    获取 Edge 的用户数据目录
    1. 优先检查注册表策略：UserDataDir
       - HKEY_LOCAL_MACHINE\\SOFTWARE\\Policies\\Microsoft\\Edge
       - HKEY_CURRENT_USER\\SOFTWARE\\Policies\\Microsoft\\Edge
    2. 若未设置，返回默认路径：%LOCALAPPDATA%\\Microsoft\\Edge\\User Data
    """
    subkey = r"SOFTWARE\Policies\Microsoft\Edge"
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(hive, subkey, 0, winreg.KEY_READ) as key:
                value, _ = winreg.QueryValueEx(key, "UserDataDir")
                expanded = _expand_and_validate(value)
                if expanded:
                    return expanded
        except WindowsError:
            continue

    return os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\User Data")


# 简单测试（仅当脚本直接运行时执行）
if __name__ == "__main__":
    chrome = get_chrome_path()
    edge = get_edge_path()
    edge_data_dir = get_edge_user_data_dir()
    print(f"Chrome: {chrome}")
    print(f"Edge: {edge}")
    print(f"Edge数据目录: {edge_data_dir}")