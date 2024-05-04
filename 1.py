import requests  # 导入requests库
from tqdm import tqdm  # 从tqdm库导入tqdm类
from requests_html import HTMLSession  # 从requests_html库导入HTMLSession类
import keyboard  # 导入keyboard库
import os  # 导入os库

# 定义下载目录
download_dir = "D:\Downloads"  # 下载目录为D:\Downloads

# 如果下载目录不存在，则创建它
if not os.path.exists(download_dir):  
    os.makedirs(download_dir)  # 创建下载目录

# 设置下载目录的路径
os.chdir(download_dir)  # 设置当前工作目录为下载目录

# 用于控制是否应停止下载的全局变量
should_stop = False  # 初始化should_stop变量为False，用于控制是否停止下载

# 定义Kemono网站的URL
url = "https://kemono.su/fanbox/user/85202718/post/4970887"  

# 创建HTMLSession实例
session = HTMLSession()  

# 发送GET请求到指定网站
response = session.get(url)

# 检查请求是否成功
if response.status_code == 200: 
    # 从具有"class post__attachment-link"的HTML元素中提取视频链接
    video_links = response.html.find(".post__attachment-link")  

    # 初始化下载视频的计数器为0
    download_counter = 0  

    # 定义一个函数，当按下Esc键时，将should_stop设置为True
    def should_stop_download():  # 定义函数should_stop_download，用于按下Esc键时设置should_stop为True
        global should_stop  # 声明should_stop为全局变量
        should_stop = True  # 设置should_stop为True，表示停止下载
        print("Downloads stopped by user.")  # 打印提示信息，下载被用户停止

    # 设置Esc键的监听事件，当按下Esc时，调用should_stop_download函数
    keyboard.add_hotkey('esc', should_stop_download)  # 设置监听事件，当按下Esc键时调用should_stop_download函数

    # 遍历视频链接并下载，使用tqdm显示下载进度
    for link in tqdm(video_links, desc="Downloading videos", unit="video"):  

        # 获取视频链接的'href'属性
        video_url = link.attrs['href']  

        # 提取原始视频文件名（不包含查询参数）
        original_video_name = video_url.split("?")[0].split("/")[-1] 

        # 根据原始文件名或自定义逻辑创建新文件名，此处使用"downloaded_video_{index}.mp4"的命名方式
        new_video_name = f"downloaded_video_{download_counter}.mp4"  
        download_counter += 1  # 下载计数器递增

        # 发送GET请求以下载视频
        video_response = requests.get(video_url, stream=True)  

        # 检查请求是否成功
        if video_response.status_code == 200:  

           # 打开文件以写入新文件名的视频
            with open(new_video_name, "wb") as video_file:  

                # 遍历视频响应内容并将其写入文件
                for chunk in video_response.iter_content(chunk_size=1024):  
                    if should_stop:  # 检查是否应该停止下载
                        break  # 如果应该停止下载，则跳出循环
                    video_file.write(chunk)  # 将内容写入


        else:
            print(f"Failed to download video: {original_video_name}")  # 打印提示信息，下载视频失败
else:
    print("Failed to fetch website content")  # 打印提示信息，获取网站内容失败

# 当程序结束时，移除Esc键的监听事件
keyboard.unhook_all()  # 移除所有监听事件