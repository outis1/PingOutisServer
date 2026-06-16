#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
功能：固定频率 ping 目标 IP，控制台实时输出 ping 结果。
      通过连续失败/成功阈值判断真实网络状态变化，避免瞬时波动误报。
      状态变化时通过 QQ 邮箱发送通知到指定收件人，同类型通知 5 分钟内仅发送一次。
依赖：ping3 (pip install ping3)
配置文件：config.json (与脚本放在同一目录)
"""

import smtplib
import time
import json
import os
from email.mime.text import MIMEText
from email.header import Header
from datetime import datetime
from typing import List, Union
import ping3

# ==================== 加载配置文件 ====================
def load_config(config_path="config.json"):
    """从 JSON 文件加载配置"""
    if not os.path.exists(config_path):
        print(f"错误：配置文件 {config_path} 不存在！")
        print("请创建配置文件，格式参考：")
        print('''{
    "SMTP_SERVER": "smtp.qq.com",
    "SMTP_PORT": 465,
    "SENDER_EMAIL": "your_email@qq.com",
    "AUTH_CODE": "your_auth_code",
    "RECEIVER_EMAILS": ["receiver@example.com"],
    "TARGET_HOST": "8.8.8.8",
    "PING_TIMEOUT_SEC": 5,
    "PING_INTERVAL_SECONDS": 5,
    "CONSECUTIVE_FAILURES_THRESHOLD": 5,
    "CONSECUTIVE_SUCCESSES_THRESHOLD": 3,
    "RATE_LIMIT_SECONDS": 300
}''')
        exit(1)
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
    return config

config = load_config()

# ==================== 配置赋值 ====================
SMTP_SERVER = config["SMTP_SERVER"]
SMTP_PORT = config["SMTP_PORT"]
SENDER_EMAIL = config["SENDER_EMAIL"]
AUTH_CODE = config["AUTH_CODE"]
RECEIVER_EMAILS = config["RECEIVER_EMAILS"]
TARGET_HOST = config["TARGET_HOST"]
PING_TIMEOUT_SEC = config["PING_TIMEOUT_SEC"]
PING_INTERVAL_SECONDS = config["PING_INTERVAL_SECONDS"]
CONSECUTIVE_FAILURES_THRESHOLD = config["CONSECUTIVE_FAILURES_THRESHOLD"]
CONSECUTIVE_SUCCESSES_THRESHOLD = config["CONSECUTIVE_SUCCESSES_THRESHOLD"]
RATE_LIMIT_SECONDS = config["RATE_LIMIT_SECONDS"]

# ==================== 以下代码与之前完全相同 ====================

class QQMailSender:
    """预连接 SMTP 邮件发送器，支持多收件人"""
    def __init__(self, server, port, sender, auth_code):
        self.server = server
        self.port = port
        self.sender = sender
        self.auth_code = auth_code
        self.smtp = None
        self._connect()

    def _connect(self):
        try:
            self.smtp = smtplib.SMTP_SSL(self.server, self.port, timeout=5)
            self.smtp.login(self.sender, self.auth_code)
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] SMTP 连接已建立")
        except Exception as e:
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] SMTP 连接失败: {e}")
            self.smtp = None

    def send(self, to_emails: Union[str, List[str]], subject: str, body: str) -> bool:
        if self.smtp is None:
            self._connect()
            if self.smtp is None:
                return False

        if isinstance(to_emails, str):
            to_list = [to_emails]
        else:
            to_list = to_emails

        msg = MIMEText(body, 'plain', 'utf-8')
        msg['From'] = Header(self.sender)
        msg['To'] = Header(','.join(to_list))
        msg['Subject'] = Header(subject, 'utf-8')

        try:
            self.smtp.sendmail(self.sender, to_list, msg.as_string())
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 邮件已发送至 {len(to_list)} 个收件人")
            return True
        except Exception as e:
            print(f"发送失败: {e}")
            self._connect()
            if self.smtp:
                try:
                    self.smtp.sendmail(self.sender, to_list, msg.as_string())
                    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 重连后发送成功")
                    return True
                except Exception as e2:
                    print(f"重连后仍失败: {e2}")
            return False

    def close(self):
        if self.smtp:
            self.smtp.quit()

def send_rate_limited(mailer, last_send_time, change_type, host):
    """限频发送，返回 (是否发送, 新的last_send_time)"""
    now = time.time()
    if last_send_time is not None and (now - last_send_time) < RATE_LIMIT_SECONDS:
        print(f"[限频] {change_type} 通知在 {RATE_LIMIT_SECONDS//60} 分钟内已发送过，本次跳过")
        return False, last_send_time

    if change_type == "up":
        subject = f"【上线通知】OS"
        body = f"OS服务器已于 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} 恢复连接。"
    else:
        subject = f"【离线告警】OS"
        body = f"OS服务器已于 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} 连接中断。"

    if mailer.send(RECEIVER_EMAILS, subject, body):
        return True, now
    else:
        return False, last_send_time

def main():
    mailer = QQMailSender(SMTP_SERVER, SMTP_PORT, SENDER_EMAIL, AUTH_CODE)

    print(f"固定频率 ping 监控目标: {TARGET_HOST}")
    print(f"Ping 超时: {PING_TIMEOUT_SEC} 秒，每次 ping 间隔: {PING_INTERVAL_SECONDS} 秒")
    print(f"离线判断: 连续 {CONSECUTIVE_FAILURES_THRESHOLD} 次失败")
    print(f"上线判断: 连续 {CONSECUTIVE_SUCCESSES_THRESHOLD} 次成功")
    print(f"通知将发送至: {RECEIVER_EMAILS}")
    print("-" * 70)

    # 首次探测，初始化状态（不发送邮件）
    print("正在进行首次探测，确定初始状态（不发送通知）...")
    try:
        first_delay = ping3.ping(TARGET_HOST, timeout=PING_TIMEOUT_SEC)
        first_reachable = first_delay is not None
    except Exception as e:
        print(f"首次探测异常: {e}")
        first_reachable = False

    if first_reachable:
        print(f"首次探测结果: {TARGET_HOST} 可达")
        stable_offline = False
        consecutive_successes = 1
        consecutive_failures = 0
    else:
        print(f"首次探测结果: {TARGET_HOST} 不可达")
        stable_offline = True
        consecutive_failures = 1
        consecutive_successes = 0

    print(f"初始稳定状态: {'离线' if stable_offline else '在线'}")
    print("开始正式监控，只有状态变化并满足阈值时才发送邮件...")
    print("-" * 70)

    last_up_time = None
    last_down_time = None

    try:
        while True:
            start_time = time.time()
            try:
                delay = ping3.ping(TARGET_HOST, timeout=PING_TIMEOUT_SEC)
                reachable = delay is not None
                if reachable:
                    delay_ms = int(delay * 1000)
                    print(f"来自 {TARGET_HOST} 的回复: 字节=32 时间={delay_ms}ms TTL=??")
                else:
                    print("请求超时。")
            except Exception as e:
                print(f"Ping 异常: {e}")
                reachable = False

            if reachable:
                consecutive_successes += 1
                consecutive_failures = 0
            else:
                consecutive_failures += 1
                consecutive_successes = 0

            need_change = False
            new_stable_offline = stable_offline

            if not stable_offline and consecutive_failures >= CONSECUTIVE_FAILURES_THRESHOLD:
                need_change = True
                new_stable_offline = True
            elif stable_offline and consecutive_successes >= CONSECUTIVE_SUCCESSES_THRESHOLD:
                need_change = True
                new_stable_offline = False

            if need_change:
                stable_offline = new_stable_offline
                if stable_offline:
                    print(f"\n--- 网络中断（连续 {consecutive_failures} 次失败）---")
                    sent, new_time = send_rate_limited(mailer, last_down_time, "down", TARGET_HOST)
                    if sent:
                        last_down_time = new_time
                else:
                    print(f"\n+++ 网络恢复（连续 {consecutive_successes} 次成功）+++")
                    sent, new_time = send_rate_limited(mailer, last_up_time, "up", TARGET_HOST)
                    if sent:
                        last_up_time = new_time

            elapsed = time.time() - start_time
            sleep_time = max(0, PING_INTERVAL_SECONDS - elapsed)
            if sleep_time > 0:
                time.sleep(sleep_time)

    except KeyboardInterrupt:
        print("\n用户终止监控")
    finally:
        mailer.close()

if __name__ == "__main__":
    main()