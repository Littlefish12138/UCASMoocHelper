from DrissionPage import ChromiumPage
import copy
from functools import partial
from typing import Any
from dataclasses import dataclass


@dataclass
class StackFrame:
    name: str        # 容器键名(如 "questions", "options" 或 "$root")
    ref: dict        # 指向实际数据容器（dict 或 list）

class ContainerStack:
    def __init__(self, root_dict: dict):
        # 初始化时，栈底永远有 $root 帧
        self._stack = [StackFrame(name="$root", ref=root_dict)]

    def push(self, name: str, ref):
        """压入新的容器帧"""
        self._stack.append(StackFrame(name=name, ref=ref))

    def pop(self) -> StackFrame:
        """弹出栈顶帧（不允许弹出 $root）"""
        if len(self._stack) == 1:
            raise RuntimeError("错误使用：禁止弹出根栈")
        return self._stack.pop()

    @property
    def top(self) -> StackFrame:
        """查看栈顶帧"""
        return self._stack[-1]

    def resolve(self, container: str) -> Any:
        """根据 container 字段解析目标容器"""
        if container == "$root":
            return self._stack[0].ref          # 栈底
        if container == "$parent":
            return self.top.ref                # 栈顶

        # 按名称从栈顶向下查找
        for frame in reversed(self._stack):
            if frame.name == container:
                return frame.ref
        raise KeyError(f"Container '{container}' not found in context stack")

class ElementStack:
    def __init__(self, root: ChromiumPage):
        # 初始化时，栈底永远有 $root 帧
        self._stack = [root]

    def push(self, element):
        """压入新的容器帧"""
        self._stack.append(element)

    def pop(self):
        """弹出栈顶帧（不允许弹出 $root）"""
        if len(self._stack) == 1:
            raise RuntimeError("错误使用：禁止弹出根栈")
        return self._stack.pop()
    
    def top(self):
        """查看栈顶帧"""
        return self._stack[-1]

class ElementLocator:
    """
    元素定位、获取信息\n
    """
    def __init__(self, page: ChromiumPage, config: dict, required_set: set = None, timeout = 1):
        self.page = page
        self._config = copy.deepcopy(config)
        self._required_set = copy.deepcopy(required_set) if required_set is not None else None
        self._result = {}
        self._container_stack = ContainerStack(self._result)
        self._element_stack = ElementStack(page)
        self._timeout = timeout
    
    @staticmethod
    def prune_subtree(node: dict, required_set: set = None) -> bool:
        """
        对输入的 字典/子字典 剪枝(不进行备份)包括
         - 剪去不含目标 target 的subelement
         - 剪去 targets 中不需要的 target\n
        :param node: 输入需要处理的字典，或者再递归过程中输入某个子字典
        :param required_set: 目标集合，不输则把所有带有 targets 的剪出来
        :return: 该节点是否保留(bool值)
        """
        # 1. 当前节点自身的 targets 是否有需要的键
        targets: dict = node.get('targets')
        self_needed = False
        
        if targets:
            pruned_targets = copy.deepcopy(targets)
            if required_set is not None:
                # 去除没用的键
                delete_keys = [target_key for target_key in targets if target_key not in required_set]
                for key in delete_keys:
                    del pruned_targets[key]
                
                if pruned_targets:
                    self_needed = True
                    node['targets'] = pruned_targets
                else:
                    del node['targets']
            else:
                self_needed = True
        
        # 2. 递归剪枝子节点，只保留需要的分支
        sub_elements = node.get('sub_elements', [])
        kept_subs = []
        for sub in sub_elements: # 不必处理没有子元素的情况
            if ElementLocator.prune_subtree(sub, required_set):
                kept_subs.append(sub)
        node['sub_elements'] = kept_subs
        
        # 3. 只要自己需要，或者有子节点被保留，该节点就需要保留
        return self_needed or bool(kept_subs)
    
    @staticmethod
    def get_target(element, target: dict):
        """
        根据 target 字典(不是targets字典)从对应的 ChromiumElement 元素中提取对应的信息或者方法\n
        :return: 字符串或者回调函数
        """
        if target['type'] == 'method':
                method_name = target['method']
                args = target.get('args')
                try:
                    method = getattr(element, method_name)
                    if args:
                        return partial(method, args)
                    else:
                        return method
                except Exception as e:
                    print(f"尝试调用 ChromiumElement 内方法时出现错误：{e}")
        elif target['type'] == 'information':
            val: dict = target['value']
            method_name = val['method']
            args = val.get('args')
            try:
                method = getattr(element, method_name)
                # 针对配置中的 method 是属性或者方法采取不同处理
                if callable(method):
                    if args:
                        target_info = method(args)
                    else:
                        target_info = method()
                else:
                    target_info = method
                return target_info
            except Exception as e:
                print(f"尝试调用 ChromiumElement 内方法时出现错误：{e}")
                # TODO 设计报错
                pass

    @staticmethod
    def locate_elements(element, locator_method: dict, timeout) -> list:
        """
        使用 locator_method 字典中的查找方法，从 element 的子元素中找出目标元素\n
        返回符合目标的元素列表，没有返回空列表
        """
        
        method_types: list = locator_method['type']
        locators: list = locator_method['locator']

        is_repeatable = ('children' in method_types) or ('eles' in method_types) or ('s_eles' in method_types)
        is_exist = False

        for method_type in method_types:
            if not is_exist:
                try:
                    method = getattr(element, method_type)
                    for locator in locators:
                        child_elements = method(locator, timeout = timeout)
                        if child_elements:
                            is_exist = True
                            break
                except Exception as e:
                    pass # TODO 加报错
                
            else:
                break
        
        if is_exist:
            # 按照查找方式的不同，child_elements可能是列表或者元素，只用eles/children会返回列表
            if is_repeatable:
                return child_elements
            else:
                return [child_elements]
        else:
            # TODO 按照不同的presence处理，报错，或者其他逻辑
            return []

    def process_node(self, node: dict):
        """
        递归处理单个节点\n
        """
        parent_element = self._element_stack.top()

        # ================1================ 找出满足条件的元素列表
        locator_method: dict = node['locator_method']
        child_elements: list = ElementLocator.locate_elements(parent_element, locator_method, self._timeout)

        if child_elements:
            
            # 正常查找到的情况
            for child_element in child_elements:

                self._element_stack.push(child_element) # 压入元素栈中
                is_container_pushed = False
                try:
                    # ================2================ 若有 virtual_dict 则创建空字典并压入栈顶
                    virtual_dict = node.get('virtual_dict')
                    if virtual_dict:
                        key = virtual_dict['key']
                        node_virtual_dict = {}
                        
                        # 更新result，在result_dict下指定位置 **新增** node_virtual_dict
                        container_name = virtual_dict['container']
                        virtual_container: dict = self._container_stack.resolve(container_name)
                        # 处理新增：字典列表追加
                        if virtual_container.get(key) is None:
                            # 更新结果
                            virtual_container[key] = [node_virtual_dict]
                            # 压入栈中
                            self._container_stack.push(name=key, ref=node_virtual_dict)
                            is_container_pushed = True
                        elif isinstance(virtual_container.get(key), list):
                            # 更新结果
                            virtual_container_list: list = virtual_container.get(key)
                            virtual_container_list.append(node_virtual_dict)
                            # 压入栈中
                            self._container_stack.push(name=key, ref=node_virtual_dict)
                            is_container_pushed = True
                        else:
                            # TODO 报错，不允许将原来的信息/方法键覆盖成容器
                            pass

                    # ================3================ 若有 targets 则逐个调用get_targets获取信息
                    targets: dict = node.get('targets')

                    if targets:
                        for target_name in targets:
                            target: dict = targets.get(target_name) # 剪枝后其不会是 None
                            target_object = ElementLocator.get_target(child_element, target) # 获取到目标，字符串或者回调函数
                            if target_object is not None:
                                # 目标存在
                                container_name = target['container']
                                
                                target_container: dict = self._container_stack.resolve(container_name) #使用键名从栈中找出对应的容器
                                target_key = target['key']
                                if target_container.get(target_key) is None:
                                    target_container[target_key] = target_object
                                else:
                                    # TODO 设计报错，不允许(1)覆盖已有的信息/方法键，(2)覆盖已经存了虚拟容器或者虚拟容器列表的键
                                    pass
                    # ================4================ 若有 sub_elements 则逐个处理sub_elements

                    sub_elements: list = node.get('sub_elements')
                    if sub_elements:
                        for sub_element in sub_elements:
                            self.process_node(sub_element)
                    
                    
                finally:
                    # ================5================ sub_elements全部处理完后弹出虚拟容器栈和元素栈

                    if is_container_pushed:
                        self._container_stack.pop()    
                    self._element_stack.pop()

        else:
            # TODO 未找到的情况，按照不同的presence处理
            presence = node.get('presence')
            if presence:
                if presence == 'required':
                    pass
                elif presence == 'optional':
                    return
                elif presence == 'unknown':
                    pass
            else:
                # TODO 设计这一步所的逻辑
                pass

    def extract_info(self) -> dict:
        """
        根据层级配置从 ChromiumPage 中提取信息。\n
        先对配置树剪枝，仅保留 required_fields 需要的数据路径。\n
        """

        # 从根节点开始剪枝
        ElementLocator.prune_subtree(self._config, self._required_set)
        # 启动递归
        self.process_node(self._config)
        #result = copy.copy(self._result)
        return self._result
