import requests
from requests_html import HTMLSession
from tqdm import tqdm
from win10toast import ToastNotifier
import concurrent.futures
import os
import keyboard

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
keyboard.add_hotkey("esc", should_stop_download)


# 定义一个函数，用于下载单个视频的线程函数
def download_video(video_url, new_video_name, proxies=None):
    global should_stop
    try:
        video_response = requests.get(video_url, stream=True, proxies=proxies)
        if video_response.status_code == 200:
            total_size = int(video_response.headers.get("content-length", 0))
            with tqdm(
                total=total_size,
                unit="B",
                unit_scale=True,
                desc=new_video_name,
                ascii=True,
            ) as pbar:
                with open(new_video_name, "wb") as video_file:
                    for chunk in video_response.iter_content(chunk_size=1024):
                        if should_stop:
                            print(f"下载已停止: {new_video_name}")
                            return
                        if chunk:
                            video_file.write(chunk)
                            pbar.update(len(chunk))
            print(f"已下载: {new_video_name}")
            toaster.show_toast("下载完成", f"已下载视频: {new_video_name}", duration=5)
        else:
            print(
                f"无法下载视频: {new_video_name}, 状态码: {video_response.status_code}"
            )
    except Exception as e:
        print(f"下载视频时出错: {new_video_name}, 错误: {str(e)}")
        toaster.show_toast(
            "下载出错", f"下载视频时出错: {new_video_name}, 错误: {str(e)}", duration=5
        )


# 定义一个函数，用于设置代理服务器
def set_proxy():
    use_proxy = input("是否使用代理服务器？(y/n): ").lower()
    if use_proxy == "y":
        proxy_address = input("输入代理服务器地址: ")
        return {"http": proxy_address, "https": proxy_address}
    else:
        return None


# 定义一个函数，用于提取链接并保存到文件
def extract_and_save_links(start_url, proxies=None):
    session = HTMLSession()
    links = []
    page_url = start_url
    while len(links) < 50:
        response = session.get(page_url, proxies=proxies)
        if response.status_code == 200:
            image_links = response.html.find(".image-link")
            for link in image_links:
                if len(links) >= 50:
                    break
                links.append(link.attrs["href"])
            next_page = response.html.find(".next", first=True)
            if next_page:
                page_url = next_page.attrs["href"]
            else:
                break
        else:
            print(f"无法获取网站内容，状态码: {response.status_code}")
            break
    with open("links.txt", "w") as f:
        f.write(" ".join(links))
    return links


# 定义一个函数，用于从文件中读取链接并异步下载
def download_from_file(proxies=None):
    with open("links.txt", "r") as f:
        links = f.read().split()
    download_counter = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        for link in links:
            if should_stop:
                print("用户停止了下载.")
                break
            original_video_name = link.split("?")[0].split("/")[-1]
            new_video_name = f"downloaded_video_{download_counter}.mp4"
            while os.path.exists(new_video_name):
                new_video_name = (
                    f"downloaded_video_{download_counter}_{original_video_name}"
                )
                download_counter += 1
            executor.submit(download_video, link, new_video_name, proxies)


# 获取代理设置
proxies = set_proxy()

# 允许用户选择多线程的max_workers大小
max_workers = int(input("输入多线程的最大工作线程数: "))

# 获取用户输入的URL
start_url = input("输入要下载视频的网站的URL: ")

# 提取链接并保存到文件
extract_and_save_links(start_url, proxies)

# 从文件中读取链接并异步下载
download_from_file(proxies)
