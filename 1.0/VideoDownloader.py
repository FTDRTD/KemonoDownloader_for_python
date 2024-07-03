import requests  
import keyboard  
import os  
import threading  
import concurrent.futures 
from tqdm import tqdm  
from requests_html import HTMLSession  
from win10toast import ToastNotifier  # 导入ToastNotifier类

# 创建ToastNotifier实例
toaster = ToastNotifier()

# 定义一个函数，用于设置下载目录
def set_download_directory():
    while True:
        download_dir = input("输入下载目录的路径: ").strip()  
        if os.path.isdir(download_dir):  
            os.chdir(download_dir)  
            print(f"下载目录已设置为: {download_dir}")
            break
        else:
            print("无效的目录路径，请输入有效的目录路径.")

# 设置下载目录
set_download_directory()

# 用于控制是否应停止下载的全局变量
should_stop = False  

# 定义一个函数，当按下Esc键时，将should_stop设置为True
def should_stop_download():  
    global should_stop  
    should_stop = True  
    print("用户停止了下载.")  

# 设置Esc键的监听事件，当按下Esc时，调用should_stop_download函数
keyboard.add_hotkey('esc', should_stop_download)  

# 定义一个函数，用于下载单个视频的线程函数
def download_video(video_url, new_video_name, proxies=None):  # 添加proxies参数
    global should_stop  
    
    try:
        # 发送GET请求以下载视频
        video_response = requests.get(video_url, stream=True, proxies=proxies)  # 使用代理
        
        # 检查请求是否成功
        if video_response.status_code == 200:
            # 获取文件总大小（字节）
            total_size = int(video_response.headers.get('content-length', 0))
            
            # 初始化进度条
            with tqdm(total=total_size, unit='B', unit_scale=True, desc=new_video_name, ascii=True) as pbar:
                # 打开文件以写入新文件名的视频
                with open(new_video_name, "wb") as video_file:
                    # 遍历视频响应内容并将其写入文件
                    for chunk in video_response.iter_content(chunk_size=1024):
                        if should_stop:
                            print(f"下载已停止: {new_video_name}")
                            return
                        if chunk:  
                            video_file.write(chunk)
                            # 更新进度条
                            pbar.update(len(chunk))
            print(f"已下载: {new_video_name}")
            # 发送通知
            toaster.show_toast("下载完成", f"已下载视频: {new_video_name}", duration=5)  # 5秒显示时间
        else:
            print(f"无法下载视频: {new_video_name}, 状态码: {video_response.status_code}")

    except Exception as e:
        print(f"下载视频时出错: {new_video_name}, 错误: {str(e)}")
        # 发送异常通知
        toaster.show_toast("下载出错", f"下载视频时出错: {new_video_name}, 错误: {str(e)}", duration=5)

# 定义一个函数，用于设置代理服务器
def set_proxy():
    use_proxy = input("是否使用代理服务器？(y/n): ").lower()
    if use_proxy == 'y':
        proxy_address = input("输入代理服务器地址: ")
        return {'http': proxy_address, 'https': proxy_address}
    else:
        return None

# 下载视频的函数
def download_videos_from_website(max_workers, proxies):  
    while True:
        # 获取用户输入的URL
        url = input("输入要下载视频的网站的URL: ")  

        # 创建HTMLSession实例
        session = HTMLSession()  

        try:
            # 发送GET请求到指定网站
            response = session.get(url)

            # 检查请求是否成功
            if response.status_code == 200:
                # 从具有"class post__attachment-link"的HTML元素中提取视频链接
                video_links = response.html.find(".post__attachment-link")  

                # 初始化下载视频的计数器为0
                download_counter = 0  

                # 遍历视频链接并下载，使用多线程
                threads = []
                with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                    for link in video_links:
                        if should_stop:
                            print("用户停止了下载.")
                            break

                        # 获取视频链接的'href'属性
                        video_url = link.attrs['href']  

                        # 提取原始视频文件名（不包含查询参数）
                        original_video_name = video_url.split("?")[0].split("/")[-1] 

                        # 根据原始文件名或自定义逻辑创建新文件名，此处使用"downloaded_video_{index}.mp4"的命名方式
                        new_video_name = f"downloaded_video_{download_counter}.mp4"
                        #检测是否已存在同名文件，如果存在，则自动重命名
                        while os.path.exists(new_video_name):
                            new_video_name = f"downloaded_video_{download_counter}_{original_video_name}"
                            download_counter += 1  
                        
                        # 创建线程并提交下载任务
                        thread = executor.submit(download_video, video_url, new_video_name, proxies)
                        threads.append(thread)

                # 等待所有线程完成
                for thread in threads:
                    thread.result()

            else:
                print(f"无法获取网站内容，状态码: {response.status_code}")

        except Exception as e:
            print(f"获取网站内容时出错: {url}, 错误: {str(e)}")
            # 发送异常通知
            toaster.show_toast("获取网站内容出错", f"获取网站内容时出错: {url}, 错误: {str(e)}", duration=5)

# 获取代理设置
proxies = set_proxy()

# 允许用户选择多线程的max_workers大小
max_workers = int(input("输入多线程的最大工作线程数: "))

# 不断调用下载视频的函数,直到用户按下Esc键
while not should_stop:  
    download_videos_from_website(max_workers, proxies)

