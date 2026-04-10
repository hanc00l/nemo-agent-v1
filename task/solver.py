"""
Solver - 自动化CTF Web Agent (支持多LLM并行解题)

基于 core 模块实现的多 LLM 并行解题框架。
适配第二届腾讯云黑客松智能渗透挑战赛 API。
"""
import os
import argparse
import re
import threading
from typing import Optional

# 导入核心模块
from core import (
    # LLM 配置
    load_llm_configs,
    to_dict_list,
    # 容器
    create_challenge_container,
    get_vnc_port,
    get_vnc_base_port,
    build_task_prompt,
    # Runner 基础功能
    TaskResult,
    get_log_prefix,
    get_docker_image,
    create_docker_client,
    verify_docker_image,
    verify_container_running,
    execute_task_with_stop_check,
    cleanup_container,
    # 并行执行
    ParallelExecutor,
)

# 加载 .env 文件
from dotenv import load_dotenv
load_dotenv()
print(f"[+] 已加载环境变量配置文件")


def extract_flag(text: str) -> Optional[str]:
    """
    从文本中提取 FLAG

    Args:
        text: 待搜索的文本

    Returns:
        找到的 FLAG 或 None
    """
    patterns = [
        r'flag\{[^}]+\}',
        r'ctf\{[^}]+\}',
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(0)
    return None


def submit_flag_to_platform(challenge_code: str, flag: str) -> bool:
    """
    向竞赛平台提交 FLAG（通过 PlatformClient，含频率控制）

    Args:
        challenge_code: 题目代码
        flag: FLAG 字符串

    Returns:
        提交是否成功
    """
    try:
        from core.platform import PlatformClient
        # 复用模块级实例，保证跨调用的频率控制
        if not hasattr(submit_flag_to_platform, '_client'):
            submit_flag_to_platform._client = PlatformClient()
        client = submit_flag_to_platform._client
        result = client.submit_flag(challenge_code, flag)
        if result is None:
            print(f"[-] 提交请求失败")
            return False

        correct = result.get("correct", False)
        if correct:
            message = result.get("message", "")
            print(f"[+] 提交成功! {message}")
            return True
        else:
            print(f"[-] 提交失败: FLAG 不正确")
            return False

    except Exception as e:
        print(f"[-] 提交出错: {e}")
        return False


class CTFSolveRunner:
    """CTF 解题 Runner - 在安全的容器边界内为 AI 提供最大自由度"""

    def __init__(self, llm_config: dict, llm_id: int, target: str, challenge_code: str, competition_mode: bool = False):
        self.llm_id = llm_id
        self.llm_config = llm_config
        self.target = target
        self.challenge_code = challenge_code
        self.competition_mode = competition_mode
        self.log_prefix = get_log_prefix(llm_id)

        # 从环境变量读取配置
        self.image = get_docker_image()

        # 检查是否禁用 VNC
        self.no_vision = os.getenv("NO_VISION", "false").lower() == "true"

        # VNC 端口 (仅在启用 VNC 时分配)
        self.vnc_port = None
        vnc_base_port = get_vnc_base_port()
        if not self.no_vision:
            self.vnc_port = get_vnc_port(llm_id, vnc_base_port, challenge_code)

        # 打印配置信息
        print(f"{self.log_prefix} [+] Docker 镜像: {self.image}")
        print(f"{self.log_prefix} [+] 环境变量: ANTHROPIC_MODEL={llm_config['model']}")
        print(f"{self.log_prefix} [+] 环境变量: ANTHROPIC_BASE_URL={llm_config['base_url']}")
        if self.no_vision:
            print(f"{self.log_prefix} [+] VNC 模式: 禁用 (NO_VISION=true)")
        else:
            print(f"{self.log_prefix} [+] VNC 端口: {self.vnc_port}")
        if competition_mode:
            print(f"{self.log_prefix} [+] 竞赛模式: 启用")

        # 创建 Docker 客户端
        self.docker_client = create_docker_client()

        # 验证镜像存在
        verify_docker_image(self.docker_client, self.image, self.log_prefix)

        # 创建容器
        self.container = create_challenge_container(
            docker_client=self.docker_client,
            challenge_code=self.challenge_code,
            llm_id=self.llm_id,
            llm_config=self.llm_config,
            docker_image=self.image,
            vnc_base_port=vnc_base_port,
            competition_mode=competition_mode,
        )
        print(f"{self.log_prefix} [+] 容器已启动: {self.container.name}")

        # 验证容器运行
        verify_container_running(self.container, self.log_prefix)

    def cleanup(self):
        """清理容器资源"""
        cleanup_container(self.container, self.log_prefix)

    def __del__(self):
        """析构函数，安全清理资源"""
        try:
            import sys
            if sys is not None and sys.meta_path is not None:
                self.cleanup()
        except Exception:
            pass

    def run_task(self, task: str, stop_event: threading.Event) -> dict:
        """执行任务，支持外部停止信号"""
        result = execute_task_with_stop_check(
            container=self.container,
            task=task,
            stop_event=stop_event,
            log_prefix=self.log_prefix,
        )
        return result.to_dict()


# Runner 工厂函数
def create_runner(llm_config: dict, llm_id: int, target: str, challenge_code: str, competition_mode: bool = False) -> CTFSolveRunner:
    """创建 CTFSolveRunner 的工厂函数"""
    return CTFSolveRunner(
        llm_config=llm_config,
        llm_id=llm_id,
        target=target,
        challenge_code=challenge_code,
        competition_mode=competition_mode
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='CTF Web Agent (多LLM并行)',
        epilog='仅用于授权的安全测试和 CTF 竞赛'
    )

    # 目标相关参数
    parser.add_argument('--target', required=True, type=str, help='单个目标 URL 或 IP:端口')
    parser.add_argument('--challenge_code', required=True,type=str, help='题目代码 (code)，用于关联笔记和记录')
    parser.add_argument('--competition', action='store_true', help='启用竞赛模式（解题成功后自动提交答案）')
    parser.add_argument('--zone', type=int, default=1, choices=[1, 2, 3, 4], help='赛区编号 (1-4)，默认 1')
    parser.add_argument('--description', type=str, default='', help='赛题描述')
    parser.add_argument('--hint', type=str, default='', help='提示信息')

    args = parser.parse_args()

    # 1. 解析 MAX_LLM 参数
    max_llm = int(os.getenv("MAX_LLM", "1"))
    max_llm = min(max_llm, 3)
    print(f"[+] 配置的 MAX_LLM: {max_llm}")

    # 2. 加载 LLM 配置 (使用 core 模块)
    llm_configs = load_llm_configs(max_llm)
    if not llm_configs:
        print("[-] 错误: 没有可用的 LLM 配置")
        print("[-] 请在 .env 文件中配置 LLM-1/2/3-ANTHROPIC_AUTH_TOKEN")
        exit(1)

    # 转换为字典列表
    configs = to_dict_list(llm_configs)

    print(f"[+] 成功加载 {len(configs)} 个 LLM 配置")
    for config in configs:
        print(f"    - LLM-{config['id']}: {config['model']}")

    # 3. 创建并行执行器
    competition_mode = args.competition
    print(f"[+] 竞赛模式: {'启用' if competition_mode else '禁用'}")

    executor = ParallelExecutor(
        configs=configs,
        target=args.target,
        challenge_code=args.challenge_code,
        runner_factory=create_runner,
        competition_mode=competition_mode,
    )

    try:
        # 4. 创建所有 Runner
        executor.runners = executor.create_runners()
        if not executor.runners:
            print("[-] 错误: 没有成功创建任何 Runner")
            exit(1)

        print(f"[+] 成功创建 {len(executor.runners)} 个 Runner")

        # 5. 构建任务
        task = build_task_prompt(args.target, args.challenge_code, args.competition,
                                description=args.description, hint=args.hint, zone=args.zone)

        # 6. 并行执行任务
        result = executor.execute_tasks(
            task=task,
            execute_method="run_task",
            get_log_prefix=lambda r: r.log_prefix
        )

        # 7. 处理结果
        if result.success:
            print("[+] ====================")
            print("[+] 解题成功!")
            print("[+] ====================")

            # 提取 FLAG
            all_output = ""
            for r in result.results:
                if r:
                    output = r.get("output", "")
                    all_output += output + "\n"

            flag = extract_flag(all_output)
            if flag:
                print(f"[+] 发现 FLAG: {flag}")

                # 竞赛模式：自动提交
                if args.competition:
                    print(f"[+] 正在向竞赛平台提交答案...")
                    submit_success = submit_flag_to_platform(args.challenge_code, flag)
                    if submit_success:
                        print(f"[+] 答案提交成功!")
                    else:
                        print(f"[-] 答案提交失败，请手动提交")
        else:
            print("[-] 所有 Runner 均未成功")

    except KeyboardInterrupt:
        print("\n[+] 用户中断，正在清理...")
    except Exception as e:
        print(f"[-] 执行出错: {e}")
    finally:
        # 8. 清理所有资源
        executor.cleanup_all()
        print("[+] 资源已清理")
