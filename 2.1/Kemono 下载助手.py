import sys
import os
import re
import asyncio
import aiohttp
from aiohttp import ClientSession
from bs4 import BeautifulSoup
from tqdm.asyncio import tqdm
from PyQt5.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QLabel,
    QProgressBar,
)
from PyQt5.QtCore import QThread, pyqtSignal

# 定义全局变量，用于标记是否收到中断信号和重试次数
interrupted = False
max_retries = 60  # 最大重试次数
request_delay = 5  # 请求之间的延迟时间（秒）
request_timeout = 60  # 请求超时时间（秒）
max_concurrent_requests = 10  # 最大并发请求数


# 清理文件名的函数
def sanitize_filename(filename):
    filename = re.sub(r"[^\w\-\.]", "_", filename)
    filename = re.sub(r"[_\s]+", "_", filename).strip("_")
    return filename


# 异步获取页面 HTML 的函数
async def get_page_html(url, session):
    retries = 0
    while retries < max_retries:
        try:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=request_timeout)
            ) as response:
                if response.status == 200:
                    return await response.text()
                elif response.status == 403:
                    print("请求失败，状态码：403 Forbidden")
                    return None
                elif response.status == 429:
                    wait_time = min(5 * (2**retries), 60)  # 指数回退
                    print(
                        f"请求频率过高，暂时被服务器拒绝访问。重试中 ({retries + 1}/{max_retries})...等待 {wait_time} 秒"
                    )
                    retries += 1
                    await asyncio.sleep(wait_time)
                else:
                    print(f"请求失败，状态码：{response.status}")
                    return None
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            print(f"请求失败: {e}")
            retries += 1
            await asyncio.sleep(5)
    print("达到最大重试次数，放弃请求。")
    return None


# 异步下载文件的函数
async def download_file(url, file_name, session, progress_signal):
    retries = 0
    while retries < max_retries:
        try:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=request_timeout)
            ) as response:
                response.raise_for_status()
                total_size = int(response.headers.get("content-length", 0))
                block_size = 4096

                if not os.path.exists("downloads"):
                    os.makedirs("downloads")

                file_path = os.path.join("downloads", file_name)
                temp_path = file_path + ".part"

                with open(temp_path, "wb") as f:
                    downloaded_size = 0
                    async for data in response.content.iter_chunked(block_size):
                        if interrupted:
                            print("\n下载已中断")
                            return
                        f.write(data)
                        downloaded_size += len(data)
                        progress = (
                            (downloaded_size / total_size) * 100 if total_size else 0
                        )
                        progress_signal.emit(progress)

                os.rename(temp_path, file_path)  # 下载完成后重命名为最终文件名
                return
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            print(f"下载失败: {e}")
            retries += 1
            await asyncio.sleep(10)
    print("达到最大重试次数，放弃下载。")


# 异步提取链接的函数
async def extract_links(html):
    soup = BeautifulSoup(html, "html.parser")
    pattern = r"/.*/user/\d+/post/.*"
    links = []
    for link in soup.find_all("a"):
        href = link.get("href")
        if href and re.search(pattern, href):
            links.append("https://kemono.su" + href)
    return links


# 异步获取下一页 URL 的函数
async def get_next_page_url(html, base_url):
    soup = BeautifulSoup(html, "html.parser")
    next_page_link = soup.find("a", class_="next")
    if next_page_link:
        next_page_url = base_url + next_page_link.get("href")
        return next_page_url
    return None


# 主函数
async def main(url, update_signal, progress_signal):
    global interrupted
    links = []
    base_url = "https://kemono.su"

    async with ClientSession() as session:
        while url:
            html = await get_page_html(url, session)
            if html:
                page_links = await extract_links(html)
                links.extend(page_links)
                url = await get_next_page_url(html, base_url)
                await asyncio.sleep(request_delay)  # 添加请求之间的延迟
            else:
                break

        with open("links.txt", "w") as f:
            for link in links:
                f.write(link + "\n")

        update_signal.emit("所有链接已保存到 links.txt")

        with open("links.txt", "r") as file:
            urls = [line.strip() for line in file]

        if not os.path.exists("downloads"):
            os.makedirs("downloads")

        semaphore = asyncio.Semaphore(max_concurrent_requests)

        async def download_with_semaphore(url, file_name, session):
            async with semaphore:
                await download_file(url, file_name, session, progress_signal)

        tasks = []
        for url in urls:
            if interrupted:
                update_signal.emit("\n任务已中断")
                break
            html = await get_page_html(url, session)
            if html:
                soup = BeautifulSoup(html, "html.parser")
                for link in soup.find_all("a", class_="post__attachment-link"):
                    href = link.get("href")
                    if href:
                        file_name = sanitize_filename(link.text)
                        if file_name.endswith(".mp4") or file_name.endswith(".zip"):
                            task = asyncio.create_task(
                                download_with_semaphore(href, file_name, session)
                            )
                            tasks.append(task)
                            await asyncio.sleep(request_delay)  # 添加请求之间的延迟

        await asyncio.gather(*tasks)


class DownloadThread(QThread):
    update_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(float)

    def __init__(self, url):
        super().__init__()
        self.url = url

    def run(self):
        asyncio.run(main(self.url, self.update_signal, self.progress_signal))


class KemonoDownloaderGUI(QWidget):
    def __init__(self):
        super().__init__()
        self.initUI()

    def initUI(self):
        self.setWindowTitle("Kemono Downloader")
        self.setGeometry(100, 100, 600, 400)

        layout = QVBoxLayout()

        self.url_label = QLabel("请输入网站首页链接:", self)
        layout.addWidget(self.url_label)

        self.url_input = QLineEdit(self)
        layout.addWidget(self.url_input)

        self.start_button = QPushButton("开始下载", self)
        self.start_button.clicked.connect(self.start_download)
        layout.addWidget(self.start_button)

        self.output_text = QTextEdit(self)
        self.output_text.setReadOnly(True)
        layout.addWidget(self.output_text)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 100)
        layout.addWidget(self.progress_bar)

        self.setLayout(layout)

    def start_download(self):
        url = self.url_input.text()
        if url:
            self.output_text.append(f"开始下载: {url}")
            self.download_thread = DownloadThread(url)
            self.download_thread.update_signal.connect(self.update_output)
            self.download_thread.progress_signal.connect(self.update_progress)
            self.download_thread.start()

    def update_output(self, text):
        self.output_text.append(text)

    def update_progress(self, progress):
        self.progress_bar.setValue(progress)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    ex = KemonoDownloaderGUI()
    ex.show()
    sys.exit(app.exec_())
