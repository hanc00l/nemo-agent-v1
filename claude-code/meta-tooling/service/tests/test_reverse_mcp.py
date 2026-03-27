"""
Reverse Tool MCP 测试用例

测试 nc 工具的全部功能:
- get_session: 创建监听
- get_output: 获取输出
- send_keys: 发送命令
- close_session: 关闭监听
- list_sessions: 列出所有会话

注意: jndi 和 msf 需要安装相应工具，测试跳过
"""

import pytest
import time
import sys
import os

# 添加父目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from reverse_mcp import (
    ReverseToolManager,
    ToolType,
    TMUX_SESSION_NAME,
    DEFAULT_IP,
    DEFAULT_NC_PORT
)


class TestNCtool:
    """NC 工具测试"""

    @pytest.fixture(autouse=True)
    def setup(self):
        """每个测试前初始化管理器"""
        self.manager = ReverseToolManager()
        yield
        # 清理：关闭所有会话
        self.manager.close_all_sessions()

    def test_get_session_nc(self):
        """测试创建 nc 监听"""
        result = self.manager.get_session("nc")

        print(f"\n[TEST] get_session('nc') result:")
        print(f"  connection_id: {result.get('connection_id')}")
        print(f"  type: {result.get('type')}")
        print(f"  ip: {result.get('ip')}")
        print(f"  port: {result.get('port')}")
        print(f"  status: {result.get('status')}")

        assert result["status"] == "running", f"Expected running, got: {result}"
        assert result["type"] == "nc"
        assert result["connection_id"].startswith("nc_")
        assert result["port"] >= DEFAULT_NC_PORT

        # 保存 connection_id 供后续测试使用
        self.nc_conn_id = result["connection_id"]

    def test_get_session_nc_multiple(self):
        """测试创建多个 nc 监听（端口自动递增）"""
        result1 = self.manager.get_session("nc")
        result2 = self.manager.get_session("nc")
        result3 = self.manager.get_session("nc")

        print(f"\n[TEST] Multiple nc sessions:")
        print(f"  Session 1: port {result1['port']}")
        print(f"  Session 2: port {result2['port']}")
        print(f"  Session 3: port {result3['port']}")

        assert result1["status"] == "running"
        assert result2["status"] == "running"
        assert result3["status"] == "running"

        # 端口应该不同
        assert result1["port"] != result2["port"]
        assert result2["port"] != result3["port"]

        # connection_id 应该不同
        assert result1["connection_id"] != result2["connection_id"]
        assert result2["connection_id"] != result3["connection_id"]

    def test_get_session_nc_custom_port(self):
        """测试指定端口的 nc 监听"""
        custom_port = 19999
        result = self.manager.get_session("nc", port=custom_port)

        print(f"\n[TEST] Custom port nc session:")
        print(f"  port: {result['port']}")

        assert result["status"] == "running"
        assert result["port"] == custom_port

    def test_get_output(self):
        """测试获取 nc 输出"""
        # 先创建一个监听
        session = self.manager.get_session("nc")
        conn_id = session["connection_id"]

        # 等待 nc 启动
        time.sleep(1)

        # 获取输出
        output = self.manager.get_output(conn_id)

        print(f"\n[TEST] get_output result:")
        print(f"  Output length: {len(output)}")
        print(f"  Output preview: {output[:200] if output else '(empty)'}")

        # nc 启动后应该有输出
        assert output is not None
        assert isinstance(output, str)

    def test_send_keys(self):
        """测试向 nc 发送命令"""
        # 创建监听
        session = self.manager.get_session("nc")
        conn_id = session["connection_id"]

        time.sleep(1)

        # 发送命令（nc 在等待连接，发送的内容会显示）
        output = self.manager.send_keys(conn_id, "test_command", enter=True)

        print(f"\n[TEST] send_keys result:")
        print(f"  Output length: {len(output)}")

        assert output is not None
        assert isinstance(output, str)

    def test_list_sessions(self):
        """测试列出所有会话"""
        # 创建几个会话
        self.manager.get_session("nc")
        self.manager.get_session("nc")

        sessions = self.manager.list_sessions()

        print(f"\n[TEST] list_sessions result:")
        print(f"  Session count: {len(sessions)}")
        for s in sessions:
            print(f"  - {s['connection_id']}: {s['type']} on {s['ip']}:{s['port']}")

        assert len(sessions) >= 2
        for s in sessions:
            assert "connection_id" in s
            assert "type" in s
            assert "ip" in s
            assert "port" in s
            assert "status" in s

    def test_get_session_info(self):
        """测试获取会话详情"""
        session = self.manager.get_session("nc")
        conn_id = session["connection_id"]

        info = self.manager.get_session_info(conn_id)

        print(f"\n[TEST] get_session_info result:")
        print(f"  {info}")

        assert info["connection_id"] == conn_id
        assert info["type"] == "nc"
        assert info["status"] == "running"

    def test_close_session(self):
        """测试关闭会话"""
        session = self.manager.get_session("nc")
        conn_id = session["connection_id"]

        # 关闭会话
        result = self.manager.close_session(conn_id)

        print(f"\n[TEST] close_session result:")
        print(f"  {result}")

        assert result["connection_id"] == conn_id
        assert result["status"] == "stopped"

        # 再次关闭应该返回已关闭状态
        result2 = self.manager.close_session(conn_id)
        assert result2["status"] == "stopped"

    def test_get_output_closed_session(self):
        """测试获取已关闭会话的输出"""
        session = self.manager.get_session("nc")
        conn_id = session["connection_id"]

        # 关闭会话
        self.manager.close_session(conn_id)

        # 获取输出应该返回错误消息
        output = self.manager.get_output(conn_id)

        print(f"\n[TEST] get_output on closed session:")
        print(f"  Output: {output}")

        assert "已关闭" in output or "stopped" in output.lower()

    def test_send_keys_closed_session(self):
        """测试向已关闭会话发送命令"""
        session = self.manager.get_session("nc")
        conn_id = session["connection_id"]

        # 关闭会话
        self.manager.close_session(conn_id)

        # 发送命令应该返回错误消息
        output = self.manager.send_keys(conn_id, "test")

        print(f"\n[TEST] send_keys on closed session:")
        print(f"  Output: {output}")

        assert "已关闭" in output or "stopped" in output.lower()

    def test_get_session_invalid_type(self):
        """测试无效的工具类型"""
        result = self.manager.get_session("invalid_tool")

        print(f"\n[TEST] get_session('invalid_tool') result:")
        print(f"  status: {result['status']}")
        print(f"  verbose: {result['verbose']}")

        assert result["status"] == "error"
        assert "未知" in result["verbose"]

    def test_get_session_info_invalid_id(self):
        """测试无效的 connection_id"""
        info = self.manager.get_session_info("invalid_id_12345")

        print(f"\n[TEST] get_session_info('invalid_id') result:")
        print(f"  status: {info['status']}")

        assert info["status"] == "error"
        assert "不存在" in info.get("verbose", "")

    def test_close_all_sessions(self):
        """测试关闭所有会话"""
        # 创建多个会话
        self.manager.get_session("nc")
        self.manager.get_session("nc")
        self.manager.get_session("nc")

        # 关闭所有
        results = self.manager.close_all_sessions()

        print(f"\n[TEST] close_all_sessions result:")
        print(f"  Closed sessions: {len(results)}")
        for conn_id, result in results.items():
            print(f"  - {conn_id}: {result['status']}")

        # 验证所有会话都已关闭
        sessions = self.manager.list_sessions()
        for s in sessions:
            assert s["status"] in ["stopped", "error"]


class TestNCtoolIntegration:
    """NC 工具集成测试（模拟反弹 shell）"""

    @pytest.fixture(autouse=True)
    def setup(self):
        """每个测试前初始化管理器"""
        self.manager = ReverseToolManager()
        yield
        self.manager.close_all_sessions()

    def test_nc_listen_and_connect(self):
        """测试 nc 监听并模拟连接"""
        import subprocess

        # 创建监听
        session = self.manager.get_session("nc")
        conn_id = session["connection_id"]
        port = session["port"]

        print(f"\n[TEST] nc listening on port {port}")

        time.sleep(1)

        # 模拟反弹连接（使用 timeout 限制时间）
        try:
            # 发送测试数据
            subprocess.run(
                ["timeout", "2", "bash", "-c",
                 f"echo 'TEST_CONNECTION_DATA' | nc -w 1 {DEFAULT_IP} {port}"],
                capture_output=True,
                text=True,
                timeout=5
            )
        except Exception as e:
            print(f"  Connection attempt: {e}")

        time.sleep(1)

        # 获取 nc 输出
        output = self.manager.get_output(conn_id)

        print(f"\n[TEST] nc output after connection:")
        print(f"  {output[:500] if output else '(empty)'}")

        # 输出中应该有连接信息或测试数据
        assert output is not None


class TestJNDIandMSF:
    """JNDI 和 MSF 测试（需要安装相应工具）"""

    def test_jndi_skipped_if_not_installed(self):
        """JNDI 测试 - 如果未安装则跳过"""
        # 检查 JNDIExploit.jar 是否存在
        jar_path = os.getenv("JNDI_JAR_PATH", "/opt/JNDIExploit.jar")
        if not os.path.exists(jar_path):
            pytest.skip(f"JNDIExploit.jar not found at {jar_path}")

        manager = ReverseToolManager()
        try:
            result = manager.get_session("jndi")
            print(f"\n[TEST] JNDI session: {result}")

            if result["status"] == "running":
                assert result["type"] == "jndi"
                manager.close_session(result["connection_id"])
            else:
                print(f"  JNDI failed to start: {result['verbose']}")
        finally:
            manager.close_all_sessions()

    def test_msf_skipped_if_not_installed(self):
        """MSF 测试 - 如果未安装则跳过"""
        # 检查 msfconsole 是否存在
        import shutil
        if not shutil.which("msfconsole"):
            pytest.skip("msfconsole not found in PATH")

        manager = ReverseToolManager()
        try:
            result = manager.get_session("msf")
            print(f"\n[TEST] MSF session: {result}")

            if result["status"] == "running":
                assert result["type"] == "msf"
                manager.close_session(result["connection_id"])
            else:
                print(f"  MSF failed to start: {result['verbose']}")
        finally:
            manager.close_all_sessions()


if __name__ == "__main__":
    # 运行测试
    pytest.main([__file__, "-v", "-s", "--tb=short"])
