# 等待MCP就绪
while ! curl -s --head http://localhost:8000/ >/dev/null; do
    sleep 1
done