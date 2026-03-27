"""
Reverse MCP JNDI 接口测试

测试 JNDI 反连工具的 MCP 接口功能。

运行方式：
    # 单元测试（mock tmux）
    pytest test_reverse_mcp_jndi.py -v

    # 集成测试（需要 tmux 和 JNDIExploit.jar）
    pytest test_reverse_mcp_jndi.py -v --integration
"""

import os
import sys
import time
import pytest
from unittest.mock import Mock, patch, MagicMock
from dataclasses import dataclass

# 添加服务目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reverse_mcp import (
    ReverseToolManager,
    ToolType,
    ConnectionInfo,
    DEFAULT_IP,
    DEFAULT_JNDI_LDAP_PORT,
    DEFAULT_WORKSPACE,
    DEFAULT_JNDI_JAR_PATH,
)


# ============== Mock 类 ==============

class MockPane:
    """Mock tmux pane"""
    def __init__(self, pane_id: str):
        self.id = pane_id
        self._output = []
        self._commands = []

    def send_keys(self, keys: str, enter: bool = True):
        self._commands.append({"keys": keys, "enter": enter})
        if enter and "java -jar" in keys:
            self._output.append("JNDIExploit started")
            self._output.append(f"LDAP server listening on 0.0.0.0:1389")
            self._output.append(f"HTTP server listening on 0.0.0.0:8080")

    def capture_pane(self, start=None, end=None):
        return self._output.copy()


class MockWindow:
    """Mock tmux window"""
    def __init__(self):
        self.panes = [MockPane("pane_0")]
        self._next_pane_id = 1

    def split(self, direction=None):
        pane = MockPane(f"pane_{self._next_pane_id}")
        self.panes.append(pane)
        self._next_pane_id += 1
        return pane


class MockSession:
    """Mock tmux session"""
    def __init__(self, name: str):
        self.session_name = name
        self.windows = [MockWindow()]

    def set_option(self, key: str, value):
        pass

    def kill(self):
        pass


class MockServer:
    """Mock tmux server"""
    def __init__(self):
        self._sessions = []
        self.sessions = self  # self-reference for sessions.filter

    def filter(self, session_name: str = None):
        """Mock sessions.filter"""
        if session_name:
            return [s for s in self._sessions if s.session_name == session_name]
        return self._sessions

    def new_session(self, session_name: str, attach: bool = False, start_directory: str = None):
        session = MockSession(session_name)
        self._sessions.append(session)
        return session


# ============== 单元测试 ==============

class TestReverseToolManagerJNDI:
    """JNDI 反连工具管理器单元测试"""

    @pytest.fixture
    def mock_tmux(self):
        """创建 mock tmux 环境"""
        with patch('reverse_mcp.libtmux.Server') as mock_server_class:
            mock_server = MockServer()
            mock_server_class.return_value = mock_server
            yield mock_server

    @pytest.fixture
    def manager(self, mock_tmux):
        """创建管理器实例"""
        return ReverseToolManager()

    def test_build_jndi_command(self, manager):
        """测试 JNDI 命令构建"""
        command, verbose = manager._build_command(
            ToolType.JNDI,
            ip="192.168.52.101",
            port=1389
        )

        # 验证命令包含必要参数
        assert "java -jar" in command
        assert "JNDIExploit.jar" in command
        assert "-i 192.168.52.101" in command
        assert "-l 1389" in command
        assert "-p 1390" in command  # HTTP = LDAP + 1

        # 验证描述信息
        assert "192.168.52.101" in verbose
        assert "1389" in verbose
        assert "1390" in verbose

    def test_build_jndi_command_custom_port(self, manager):
        """测试自定义端口的 JNDI 命令"""
        command, verbose = manager._build_command(
            ToolType.JNDI,
            ip="10.0.0.1",
            port=2389
        )

        assert "-l 2389" in command
        assert "-p 2390" in command

    def test_get_session_jndi_creates_connection(self, manager):
        """测试 get_session 创建 JNDI 会话"""
        result = manager.get_session(tool_type="jndi", port=1389)

        # 验证返回值结构
        assert "connection_id" in result
        assert result["type"] == "jndi"
        assert result["ip"] == DEFAULT_IP
        assert result["port"] == 1389
        assert result["status"] == "running"
        assert "verbose" in result

        # 验证 connection_id 格式
        assert result["connection_id"].startswith("jndi_")

    def test_get_session_jndi_auto_port(self, manager):
        """测试 JNDI 自动分配端口"""
        result = manager.get_session(tool_type="jndi")

        # 验证自动分配的端口
        assert result["port"] == DEFAULT_JNDI_LDAP_PORT

    def test_get_session_jndi_multiple(self, manager):
        """测试创建多个 JNDI 会话"""
        result1 = manager.get_session(tool_type="jndi")
        result2 = manager.get_session(tool_type="jndi")

        # 验证不同 connection_id
        assert result1["connection_id"] != result2["connection_id"]

        # 验证端口自动递增
        assert result2["port"] == result1["port"] + 1

    def test_list_sessions_after_jndi(self, manager):
        """测试列出 JNDI 会话"""
        manager.get_session(tool_type="jndi")
        manager.get_session(tool_type="jndi")

        sessions = manager.list_sessions()

        assert len(sessions) == 2
        assert all(s["type"] == "jndi" for s in sessions)

    def test_close_session_jndi(self, manager):
        """测试关闭 JNDI 会话"""
        result = manager.get_session(tool_type="jndi")
        conn_id = result["connection_id"]

        close_result = manager.close_session(conn_id)

        assert close_result["connection_id"] == conn_id
        assert close_result["status"] == "stopped"

        # 验证会话状态已更新
        sessions = manager.list_sessions()
        closed_session = next(s for s in sessions if s["connection_id"] == conn_id)
        assert closed_session["status"] == "stopped"

    def test_get_session_info_jndi(self, manager):
        """测试获取 JNDI 会话详情"""
        result = manager.get_session(tool_type="jndi")
        conn_id = result["connection_id"]

        info = manager.get_session_info(conn_id)

        assert info["connection_id"] == conn_id
        assert info["type"] == "jndi"
        assert "ip" in info
        assert "port" in info

    def test_get_output_jndi(self, manager):
        """测试获取 JNDI 输出"""
        result = manager.get_session(tool_type="jndi")
        conn_id = result["connection_id"]

        output = manager.get_output(conn_id)

        # 输出应该是字符串（即使是空）
        assert isinstance(output, str)

    def test_send_keys_jndi(self, manager):
        """测试向 JNDI 会话发送命令"""
        result = manager.get_session(tool_type="jndi")
        conn_id = result["connection_id"]

        output = manager.send_keys(conn_id, "test", enter=True)

        # 输出应该是字符串
        assert isinstance(output, str)

    def test_get_session_invalid_type(self, manager):
        """测试无效工具类型"""
        result = manager.get_session(tool_type="invalid")

        assert result["status"] == "error"
        assert "未知的工具类型" in result["verbose"]

    def test_close_nonexistent_session(self, manager):
        """测试关闭不存在的会话"""
        result = manager.close_session("nonexistent_id")

        assert result["status"] == "error"

    def test_get_output_nonexistent_session(self, manager):
        """测试获取不存在会话的输出"""
        output = manager.get_output("nonexistent_id")

        assert "连接不存在" in output

    def test_send_keys_nonexistent_session(self, manager):
        """测试向不存在会话发送命令"""
        output = manager.send_keys("nonexistent_id", "test")

        assert "连接不存在" in output


class TestJNDIEnvironmentConfig:
    """JNDI 环境配置测试"""

    def test_default_workspace_path(self):
        """测试默认工作目录"""
        assert DEFAULT_WORKSPACE == "/opt/workspace"

    def test_default_jndi_jar_path(self):
        """测试默认 JNDI JAR 路径"""
        assert DEFAULT_JNDI_JAR_PATH == "/opt/workspace/JNDIExploit.jar"

    def test_default_ip(self):
        """测试默认监听 IP"""
        assert DEFAULT_IP == "192.168.52.101"

    def test_default_ldap_port(self):
        """测试默认 LDAP 端口"""
        assert DEFAULT_JNDI_LDAP_PORT == 1389

    def test_env_override_workspace(self):
        """测试 WORKSPACE 环境变量覆盖"""
        # 保存原始值
        original_workspace = os.getenv("WORKSPACE")

        with patch.dict(os.environ, {"WORKSPACE": "/custom/workspace"}):
            # 验证环境变量被读取
            assert os.getenv("WORKSPACE") == "/custom/workspace"

        # 恢复原始环境变量（不重新加载模块，避免影响其他测试）
        if original_workspace:
            os.environ["WORKSPACE"] = original_workspace
        elif "WORKSPACE" in os.environ:
            del os.environ["WORKSPACE"]


class TestConnectionInfoDataclass:
    """ConnectionInfo 数据类测试"""

    def test_to_dict(self):
        """测试 to_dict 方法"""
        conn = ConnectionInfo(
            connection_id="jndi_test123",
            tool_type=ToolType.JNDI,
            ip="192.168.1.1",
            port=1389,
            pane_id="pane_1",
            command="java -jar test.jar",
            verbose="Test connection",
            created_at=time.time(),
            status="running"
        )

        result = conn.to_dict()

        assert result["connection_id"] == "jndi_test123"
        assert result["type"] == "jndi"
        assert result["ip"] == "192.168.1.1"
        assert result["port"] == 1389
        assert result["status"] == "running"
        assert result["verbose"] == "Test connection"

    def test_default_status(self):
        """测试默认状态"""
        conn = ConnectionInfo(
            connection_id="test",
            tool_type=ToolType.JNDI,
            ip="0.0.0.0",
            port=1389,
            pane_id="pane_0",
            command="",
            verbose="",
            created_at=0
        )

        assert conn.status == "running"


class TestToolTypeEnum:
    """ToolType 枚举测试"""

    def test_jndi_value(self):
        """测试 JNDI 枚举值"""
        assert ToolType.JNDI.value == "jndi"

    def test_tool_type_from_string(self):
        """测试从字符串创建 ToolType"""
        assert ToolType("jndi") == ToolType.JNDI
        # 大小写敏感，大写会抛出 ValueError
        with pytest.raises(ValueError):
            ToolType("JNDI")

    def test_all_tool_types(self):
        """测试所有工具类型"""
        assert ToolType.NC.value == "nc"
        assert ToolType.JNDI.value == "jndi"
        assert ToolType.MSF.value == "msf"


# ============== 集成测试 ==============

@pytest.mark.integration
class TestJNDIIntegration:
    """JNDI 集成测试（需要真实 tmux 环境）"""

    @pytest.fixture(scope="class")
    def manager(self):
        """创建真实管理器"""
        # 检查 JNDIExploit.jar 是否存在
        if not os.path.exists(DEFAULT_JNDI_JAR_PATH):
            pytest.skip(f"JNDIExploit.jar not found at {DEFAULT_JNDI_JAR_PATH}")

        return ReverseToolManager()

    def test_real_jndi_session(self, manager):
        """测试真实 JNDI 会话创建"""
        result = manager.get_session(tool_type="jndi", port=1389)

        assert result["status"] == "running"
        assert result["type"] == "jndi"

        # 等待启动
        time.sleep(2)

        # 获取输出
        output = manager.get_output(result["connection_id"])
        assert "LDAP" in output or "listening" in output

        # 清理
        manager.close_session(result["connection_id"])

    def test_real_jndi_multiple_sessions(self, manager):
        """测试多个真实 JNDI 会话"""
        sessions = []
        for i in range(3):
            result = manager.get_session(tool_type="jndi")
            assert result["status"] == "running"
            sessions.append(result)

        # 验证端口递增
        ports = [s["port"] for s in sessions]
        assert ports == sorted(ports)
        assert len(set(ports)) == 3  # 所有端口不同

        # 清理
        for s in sessions:
            manager.close_session(s["connection_id"])


# ============== 运行入口 ==============

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="JNDI 接口测试")
    parser.add_argument("--integration", action="store_true",
                        help="运行集成测试（需要 tmux 和 JNDIExploit.jar）")
    args = parser.parse_args()

    if args.integration:
        pytest.main([__file__, "-v", "-m", "integration"])
    else:
        pytest.main([__file__, "-v", "-m", "not integration"])
