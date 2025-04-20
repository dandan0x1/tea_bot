import os
import time
from web3 import Web3
from web3.exceptions import Web3Exception
import colorama
from colorama import Fore, Back, Style
import re
from datetime import datetime, timedelta

# 初始化 colorama 用于彩色控制台输出
colorama.init()

def show_copyright():
    """展示版权信息"""
    copyright_info = f"""{Fore.CYAN}
    *****************************************************
    *           X:https://x.com/ariel_sands_dan         *
    *           Tg:https://t.me/sands0x1                *
    *           Tea Bot Version 1.0                     *
    *           Copyright (c) 2025                      *
    *           All Rights Reserved                     *
    *****************************************************
    """
    {Style.RESET_ALL}
    print(copyright_info)
    print('=' * 50)
    print(f"{Fore.GREEN}申请key: https://661100.xyz/ {Style.RESET_ALL}")
    print(f"{Fore.RED}联系Dandan: \n QQ:712987787 QQ群:1036105927 \n 电报:sands0x1 电报群:https://t.me/+fjDjBiKrzOw2NmJl \n 微信: dandan0x1{Style.RESET_ALL}")
    print('=' * 50)
    
# 常量
TEA_RPC_URL = "https://tea-sepolia.g.alchemy.com/public"
ADDRESSES_FILE = os.path.join(os.path.dirname(__file__), "address.txt")
CURRENT_LINE_FILE = os.path.join(os.path.dirname(__file__), "current_line.txt")
AMOUNT_TO_SEND = "0.01"
ADDRESSES_TO_SELECT = 200
INTERVAL_HOURS = 24

BATCH_SIZE = 10  # 减少批次大小以降低 API 调用频率
DELAY_BETWEEN_TXS_MS = 5  # 增加交易间延迟（秒）
DELAY_BETWEEN_BATCHES_MS = 60  # 增加批次间延迟（秒）
MAX_RETRIES = 5
RETRY_DELAY_MS = 10  # 初始重试延迟（秒）

# 全局变量
current_line_index = 0
provider = None
total_address_lines = 0

def get_private_key():
    """提示用户输入私钥并确保格式正确"""
    key = input(Fore.CYAN + "请输入您的私钥: " + Style.RESET_ALL).strip()
    if not key.startswith("0x"):
        key = "0x" + key
    return key

def read_addresses_from_file():
    """从 address.txt 读取并解析地址"""
    global total_address_lines
    try:
        with open(ADDRESSES_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
        
        entries = [line.strip() for line in lines if line.strip() and "," in line]
        parsed_entries = []
        
        for entry in entries:
            username, address = entry.split(",", 1)
            username = username.strip()
            address = address.strip()
            if address and address.startswith("0x") and len(address) == 42 and Web3.is_address(address):
                parsed_entries.append({"username": username, "address": address})
        
        if not parsed_entries:
            print(Back.RED + Fore.WHITE + " 错误 " + Style.RESET_ALL + " 在 address.txt 中未找到有效地址条目")
            exit(1)
        
        total_address_lines = len(parsed_entries)
        return parsed_entries
    except Exception as e:
        print(Back.RED + Fore.WHITE + " 错误 " + Style.RESET_ALL + f" 读取地址文件出错: {str(e)}")
        exit(1)

def select_sequential_addresses(address_entries, count, wallet_address, start_index):
    """选择连续的地址子集，排除钱包自己的地址"""
    global current_line_index
    filtered_entries = [entry for entry in address_entries if entry["address"].lower() != wallet_address.lower()]
    
    if not filtered_entries:
        print(Back.RED + Fore.WHITE + " 错误 " + Style.RESET_ALL + " 过滤掉自己的地址后，没有可发送的有效地址")
        exit(1)
    
    selected = []
    current_index = start_index % len(filtered_entries)
    
    for _ in range(count):
        selected.append(filtered_entries[current_index])
        current_index = (current_index + 1) % len(filtered_entries)
        if current_index == start_index % len(filtered_entries) and len(selected) < count:
            print(Fore.YELLOW + "⚠️  地址列表已到末尾，将从头开始循环。" + Style.RESET_ALL)
    
    current_line_index = current_index
    return selected

def retry_operation(operation, max_retries=MAX_RETRIES):
    """对特定错误进行重试操作，使用指数退避"""
    last_error = None
    for attempt in range(max_retries):
        try:
            return operation()
        except Exception as e:
            last_error = e
            error_msg = str(e).lower()
            print(Fore.YELLOW + f"\n⚠️ 第 {attempt + 1}/{max_retries} 次尝试出错: {str(e)}" + Style.RESET_ALL)
            
            if "capacity exceeded" in error_msg or "rate limit" in error_msg or "too many requests" in error_msg:
                if attempt < max_retries - 1:
                    delay = RETRY_DELAY_MS * (2 ** attempt)  # 指数退避：10s, 20s, 40s, 80s, 160s
                    print(Fore.YELLOW + f"{delay} 秒后重试..." + Style.RESET_ALL)
                    time.sleep(delay)
            else:
                raise e
    raise last_error

def process_in_batches(address_entries, wallet):
    """分批处理地址"""
    total_batches = (len(address_entries) + BATCH_SIZE - 1) // BATCH_SIZE
    print(Fore.BLUE + f"\n📦 将 {len(address_entries)} 个地址分为 {total_batches} 批，每批 {BATCH_SIZE} 个" + Style.RESET_ALL)
    
    for batch_idx in range(total_batches):
        start_idx = batch_idx * BATCH_SIZE
        end_idx = min(start_idx + BATCH_SIZE, len(address_entries))
        batch_entries = address_entries[start_idx:end_idx]
        
        print(Back.CYAN + Fore.BLACK + f"\n 🚀 处理第 {batch_idx + 1}/{total_batches} 批 " + Style.RESET_ALL)
        
        send_tea_batch(wallet, batch_entries, start_idx)
        
        if batch_idx < total_batches - 1:
            print(Fore.MAGENTA + f"\n😴 在下一批之前休眠 {DELAY_BETWEEN_BATCHES_MS} 秒..." + Style.RESET_ALL)
            time.sleep(DELAY_BETWEEN_BATCHES_MS)

def send_tea_batch(wallet, address_entries, start_idx):
    """向一批地址发送交易"""
    global current_line_index, total_address_lines
    w3 = provider
    
    # 缓存 gas_price 和 chain_id 以减少 API 调用
    gas_price = w3.eth.gas_price
    chain_id = w3.eth.chain_id
    
    for i, entry in enumerate(address_entries):
        global_index = start_idx + i
        username = entry["username"]
        address = entry["address"]
        
        try:
            original_start_index = current_line_index - len(address_entries)
            address_line_number = (original_start_index + global_index + 1) % total_address_lines
            display_line_number = total_address_lines if address_line_number == 0 else address_line_number
            
            print(
                Fore.CYAN + f"[{display_line_number}/{total_address_lines}]" +
                Fore.WHITE + f" 正在发送 {Fore.YELLOW + AMOUNT_TO_SEND + Style.RESET_ALL} TEA 至 " +
                Fore.BLUE + f"{username}" +
                Fore.WHITE + " 的地址 " +
                Fore.GREEN + address + Fore.WHITE + "..." + Style.RESET_ALL
            )
            
            def send_transaction():
                nonce = w3.eth.get_transaction_count(wallet.address, "pending")
                tx = {
                    "to": address,
                    "value": w3.to_wei(AMOUNT_TO_SEND, "ether"),
                    "gas": 21000,
                    "gasPrice": gas_price,  # 使用缓存的 gas_price
                    "nonce": nonce,
                    "chainId": chain_id  # 使用缓存的 chain_id
                }
                signed_tx = w3.eth.account.sign_transaction(tx, wallet.key)
                tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
                print(Fore.LIGHTBLACK_EX + "⛓️  交易已发送: " + Fore.MAGENTA + w3.to_hex(tx_hash) + Style.RESET_ALL)
                receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
                print(Fore.GREEN + "✅ 交易已在区块 " + Fore.WHITE + Style.BRIGHT + str(receipt.blockNumber) + Style.RESET_ALL + " 中确认")
            
            retry_operation(send_transaction)
            
            if i < len(address_entries) - 1:
                time.sleep(DELAY_BETWEEN_TXS_MS)
        except Exception as e:
            print(
                Back.RED + Fore.WHITE + " 失败 " + Style.RESET_ALL +
                Fore.RED + f" 无法发送至 {username} ({address}): {str(e)}" + Style.RESET_ALL
            )

def check_wallet_balance(wallet, number_of_addresses):
    """检查钱包余额是否足够"""
    try:
        def check_balance():
            balance = provider.eth.get_balance(wallet.address)
            balance_in_tea = Web3.from_wei(balance, "ether")
            print(
                Fore.WHITE + "💰 当前钱包余额: " +
                Fore.YELLOW + str(balance_in_tea) +
                Fore.YELLOW + " TEA" + Style.RESET_ALL
            )
            
            min_required = Web3.to_wei(float(AMOUNT_TO_SEND) * number_of_addresses, "ether")
            
            if balance < min_required:
                print(
                    Back.RED + Fore.WHITE + " 余额不足 " + Style.RESET_ALL +
                    Fore.RED + f" 余额不足以发送至 {number_of_addresses} 个地址。至少需要 {Web3.from_wei(min_required, 'ether')} TEA（不含燃气费）。" + Style.RESET_ALL
                )
                return False
            return True
        
        return retry_operation(check_balance)
    except Exception as e:
        print(Back.RED + Fore.WHITE + " 错误 " + Style.RESET_ALL + f" 检查余额失败: {str(e)}")
        return False

def save_current_line_index():
    """保存当前行索引到文件"""
    try:
        with open(CURRENT_LINE_FILE, "w", encoding="utf-8") as f:
            f.write(str(current_line_index))
        print(Fore.LIGHTBLACK_EX + f"📝 已保存当前行 ({current_line_index}) 至 {CURRENT_LINE_FILE}" + Style.RESET_ALL)
    except Exception as e:
        print(Fore.YELLOW + f"⚠️ 无法保存当前行: {str(e)}" + Style.RESET_ALL)

def load_current_line_index():
    """从文件加载当前行索引"""
    global current_line_index
    try:
        if os.path.exists(CURRENT_LINE_FILE):
            with open(CURRENT_LINE_FILE, "r", encoding="utf-8") as f:
                saved_index = f.read().strip()
                if saved_index.isdigit():
                    current_line_index = int(saved_index)
                    return current_line_index
    except Exception as e:
        print(Fore.YELLOW + f"⚠️ 无法加载当前行: {str(e)}" + Style.RESET_ALL)
    return 0

def scheduled_run(private_key):
    """运行定时交易流程"""
    global provider, current_line_index
    provider = Web3(Web3.HTTPProvider(TEA_RPC_URL))
    
    if not provider.is_connected():
        print(Back.RED + Fore.WHITE + " 错误 " + Style.RESET_ALL + " 无法连接到以太坊节点")
        exit(1)
    
    wallet = provider.eth.account.from_key(private_key)
    
    print(
        Back.YELLOW + Fore.BLACK + f"\n ⏱️  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} " +
        Fore.YELLOW + " 开始定时运行" + Style.RESET_ALL
    )
    
    refreshed_address_entries = read_addresses_from_file()
    print(Fore.WHITE + "📍 从行号继续: " + Fore.YELLOW + str(current_line_index) + Style.RESET_ALL)
    
    new_selected_entries = select_sequential_addresses(refreshed_address_entries, ADDRESSES_TO_SELECT, wallet.address, current_line_index)
    
    has_enough_balance = check_wallet_balance(wallet, len(new_selected_entries))
    if not has_enough_balance:
        print(Fore.RED + "❌ 余额不足以进行定时运行！请领取测试币！1 分钟后重试" + Style.RESET_ALL)
        time.sleep(60)
        scheduled_run(private_key)
        return
    
    print(Fore.WHITE + f"已选择 {Fore.GREEN + str(len(new_selected_entries)) + Style.RESET_ALL} 个地址用于发送:" + Style.RESET_ALL)
    
    for i, entry in enumerate(new_selected_entries[:10]):
        print(Fore.LIGHTBLACK_EX + f"{i+1}." + Fore.BLUE + f" {entry['username']}" + Fore.LIGHTBLACK_EX + f" ({entry['address']})" + Style.RESET_ALL)
    if len(new_selected_entries) > 10:
        print(Fore.LIGHTBLACK_EX + f"... 以及 {len(new_selected_entries) - 10} 个其他地址" + Style.RESET_ALL)
    
    process_in_batches(new_selected_entries, wallet)
    
    save_current_line_index()
    
    print(
        Back.GREEN + Fore.BLACK + "\n ✅ 完成 " + Style.RESET_ALL +
        Fore.GREEN + f" 所有转账于 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} 完成" + Style.RESET_ALL
    )
    
    next_run_time = (datetime.now() + timedelta(hours=INTERVAL_HOURS)).strftime('%Y-%m-%d %H:%M:%S')
    print(Fore.BLUE + f"\n⏭️  下次运行计划于 {Style.BRIGHT + next_run_time + Style.RESET_ALL}" + Style.RESET_ALL)
    
    time.sleep(INTERVAL_HOURS * 60 * 60)
    scheduled_run(private_key)

def main():
    """主函数运行脚本"""
    show_copyright()
    try:        
        start_index = load_current_line_index()
        print(Fore.WHITE + "📍 从行号开始: " + Fore.YELLOW + str(start_index) + Style.RESET_ALL)
        
        private_key = get_private_key()
        
        if not private_key or len(private_key) < 64:
            print(Back.RED + Fore.WHITE + " 错误 " + Style.RESET_ALL + " 私钥格式无效。请提供有效的以太坊私钥。")
            exit(1)
        
        global provider
        provider = Web3(Web3.HTTPProvider(TEA_RPC_URL))
        
        if not provider.is_connected():
            print(Back.RED + Fore.WHITE + " 错误 " + Style.RESET_ALL + " 无法连接到以太坊节点")
            exit(1)
        
        wallet = provider.eth.account.from_key(private_key)
        
        print(Fore.WHITE + "\n🔑 钱包地址: " + Fore.GREEN + wallet.address + Style.RESET_ALL)
        
        all_address_entries = read_addresses_from_file()
        print(
            Fore.WHITE + "📋 从 address.txt 加载了 " +
            Fore.GREEN + str(len(all_address_entries)) +
            Fore.WHITE + " 个地址条目" + Style.RESET_ALL
        )
        
        print(Back.CYAN + Fore.BLACK + "\n 🚀 首次运行 " + Style.RESET_ALL)
        selected_entries = select_sequential_addresses(all_address_entries, ADDRESSES_TO_SELECT, wallet.address, start_index)
        print(
            Fore.WHITE + f"已选择 {Fore.GREEN + str(len(selected_entries)) + Style.RESET_ALL} 个地址用于发送:" + Style.RESET_ALL
        )
        
        has_enough_balance = check_wallet_balance(wallet, len(selected_entries))
        if not has_enough_balance:
            print(Fore.RED + "❌ 余额不足！请领取测试币！1 分钟后重试" + Style.RESET_ALL)
            time.sleep(60)
            scheduled_run(private_key)
            return
        
        for i, entry in enumerate(selected_entries[:10]):
            print(Fore.LIGHTBLACK_EX + f"{i+1}." + Fore.BLUE + f" {entry['username']}" + Fore.LIGHTBLACK_EX + f" ({entry['address']})" + Style.RESET_ALL)
        if len(selected_entries) > 10:
            print(Fore.LIGHTBLACK_EX + f"... 以及 {len(selected_entries) - 10} 个其他地址" + Style.RESET_ALL)
        
        process_in_batches(selected_entries, wallet)
        
        save_current_line_index()
        
        print(
            Back.GREEN + Fore.BLACK + "\n ✅ 完成 " + Style.RESET_ALL +
            Fore.GREEN + f" 所有转账于 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} 完成" + Style.RESET_ALL
        )
        
        print(
            Back.MAGENTA + Fore.WHITE + f"\n ⏰ 计划在 {INTERVAL_HOURS} 小时后进行下次运行 " + Style.RESET_ALL
        )
        
        next_run_time = (datetime.now() + timedelta(hours=INTERVAL_HOURS)).strftime('%Y-%m-%d %H:%M:%S')
        print(Fore.BLUE + f"\n⏭️  下次运行计划于 {Style.BRIGHT + next_run_time + Style.RESET_ALL}" + Style.RESET_ALL)
        
        time.sleep(INTERVAL_HOURS * 60 * 60)
        scheduled_run(private_key)
    
    except Exception as e:
        print(
            Back.RED + Fore.WHITE + "\n ❌ 致命错误 " + Style.RESET_ALL +
            Fore.RED + f" {str(e)}" + Style.RESET_ALL
        )
        exit(1)

if __name__ == "__main__":
    main()
