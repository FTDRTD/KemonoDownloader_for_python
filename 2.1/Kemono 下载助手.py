import sys
import asyncio
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QVBoxLayout,
    QWidget,
    QLabel,
    QLineEdit,
    QFileDialog,
    QPushButton,
    QTextEdit,
    QCheckBox,
    QSpinBox,
    QHBoxLayout,
    QMessageBox,
    QComboBox,
)
from PySide6.QtCore import QThread, Signal

import os
import re
import aiohttp
from aiohttp import ClientSession
from bs4 import BeautifulSoup

# 定义全局变量，用于标记是否收到中断信号和重试次数
interrupted = False


# 清理文件名的函数
def sanitize_filename(filename):
    filename = re.sub(r"[^\w\-\.]", "_", filename)
    filename = re.sub(r"[_\s]+", "_", filename).strip("_")
    return filename


# 异步获取页面 HTML 的函数
async def get_page_html(url, session, proxy=None, max_retries=60, request_timeout=60):
    retries = 0
    while retries < max_retries:
        try:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=request_timeout), proxy=proxy
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
async def download_file(
    url,
    file_name,
    session,
    save_path,  # 添加 save_path 参数
    proxy=None,
    max_retries=60,
    request_timeout=60,
):
    retries = 0
    while retries < max_retries:
        try:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=request_timeout), proxy=proxy
            ) as response:
                response.raise_for_status()
                total_size = int(response.headers.get("content-length", 0))
                block_size = 4096

                if not os.path.exists(save_path):
                    os.makedirs(save_path)

                file_path = os.path.join(save_path, file_name)
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
                        print(f"\r下载进度: {progress:.2f}%", end="")

                os.rename(temp_path, file_path)  # 下载完成后重命名为最终文件名
                return
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            print(f"下载失败: {e}")
            retries += 1
            await asyncio.sleep(10)

            # 删除部分下载的文件和最终文件
            if os.path.exists(temp_path):
                os.remove(temp_path)
            if os.path.exists(file_path):
                os.remove(file_path)

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
async def main(
    url,
    use_proxy,
    proxy_type,
    proxy_address,
    proxy_port,
    max_retries,
    request_delay,
    request_timeout,
    max_concurrent_requests,
    save_path,
):
    global interrupted
    links = []
    base_url = "https://kemono.su"

    proxy = None
    if use_proxy:
        proxy = f"{proxy_type}://{proxy_address}:{proxy_port}"

    async with ClientSession() as session:
        html = await get_page_html(
            url,
            session,
            proxy,
            max_retries,
            request_timeout,
        )
        if html:
            soup = BeautifulSoup(html, "html.parser")
            if not os.path.exists(save_path):
                os.makedirs(save_path)
            print(f"保存路径: {save_path}")

            while url:
                html = await get_page_html(
                    url,
                    session,
                    proxy,
                    max_retries,
                    request_timeout,
                )
                if html:
                    page_links = await extract_links(html)
                    links.extend(page_links)
                    url = await get_next_page_url(html, base_url)
                    await asyncio.sleep(request_delay)  # 添加请求之间的延迟
                else:
                    break

            semaphore = asyncio.Semaphore(max_concurrent_requests)

            async def download_with_semaphore(url, file_name, session):
                async with semaphore:
                    await download_file(
                        url,
                        file_name,
                        session,
                        save_path,  # 传递 save_path 参数
                        proxy,
                        max_retries,
                        request_timeout,
                    )

            tasks = []
            for link in links:
                if interrupted:
                    print("\n任务已中断")
                    break
                html = await get_page_html(
                    link,
                    session,
                    proxy,
                    max_retries,
                    request_timeout,
                )
                if html:
                    soup = BeautifulSoup(html, "html.parser")
                    for attachment_link in soup.find_all(
                        "a", class_="post__attachment-link"
                    ):
                        href = attachment_link.get("href")
                        if href:
                            file_name = sanitize_filename(attachment_link.text)
                            if file_name.endswith(".mp4") or file_name.endswith(".zip"):
                                task = asyncio.create_task(
                                    download_with_semaphore(href, file_name, session)
                                )
                                tasks.append(task)
                                await asyncio.sleep(request_delay)  # 添加请求之间的延迟

            await asyncio.gather(*tasks)

    print("下载完成！")


# 下载线程类
class DownloadThread(QThread):
    finished = Signal()
    progress = Signal(str)

    def __init__(
        self,
        url,
        use_proxy,
        proxy_type,
        proxy_address,
        proxy_port,
        max_retries,
        request_delay,
        request_timeout,
        max_concurrent_requests,
        save_path,
    ):
        super().__init__()
        self.url = url
        self.use_proxy = use_proxy
        self.proxy_type = proxy_type
        self.proxy_address = proxy_address
        self.proxy_port = proxy_port
        self.max_retries = max_retries
        self.request_delay = request_delay
        self.request_timeout = request_timeout
        self.max_concurrent_requests = max_concurrent_requests
        self.save_path = save_path

    def run(self):
        asyncio.run(
            main(
                self.url,
                self.use_proxy,
                self.proxy_type,
                self.proxy_address,
                self.proxy_port,
                self.max_retries,
                self.request_delay,
                self.request_timeout,
                self.max_concurrent_requests,
                self.save_path,
            )
        )
        self.finished.emit()


# 主窗口类
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Kemono Downloader")
        self.setGeometry(100, 100, 600, 400)

        layout = QVBoxLayout()

        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("请输入目标URL")
        layout.addWidget(QLabel("目标URL:"))
        layout.addWidget(self.url_input)

        self.use_proxy_checkbox = QCheckBox("使用代理")
        layout.addWidget(self.use_proxy_checkbox)

        self.proxy_type_combo = QComboBox()
        self.proxy_type_combo.addItems(["http", "https"])
        layout.addWidget(QLabel("代理类型:"))
        layout.addWidget(self.proxy_type_combo)

        self.proxy_address_input = QLineEdit()
        self.proxy_address_input.setPlaceholderText("代理地址")
        layout.addWidget(QLabel("代理地址:"))
        layout.addWidget(self.proxy_address_input)

        self.proxy_port_input = QLineEdit()
        self.proxy_port_input.setPlaceholderText("代理端口")
        layout.addWidget(QLabel("代理端口:"))
        layout.addWidget(self.proxy_port_input)

        self.max_retries_input = QSpinBox()
        self.max_retries_input.setRange(1, 100)
        self.max_retries_input.setValue(60)
        layout.addWidget(QLabel("最大重试次数:"))
        layout.addWidget(self.max_retries_input)

        self.request_delay_input = QSpinBox()
        self.request_delay_input.setRange(1, 60)
        self.request_delay_input.setValue(5)
        layout.addWidget(QLabel("请求之间的延迟 (秒):"))
        layout.addWidget(self.request_delay_input)

        self.request_timeout_input = QSpinBox()
        self.request_timeout_input.setRange(10, 300)
        self.request_timeout_input.setValue(60)
        layout.addWidget(QLabel("请求超时时间 (秒):"))
        layout.addWidget(self.request_timeout_input)

        self.max_concurrent_requests_input = QSpinBox()
        self.max_concurrent_requests_input.setRange(1, 50)
        self.max_concurrent_requests_input.setValue(10)
        layout.addWidget(QLabel("最大并发请求数:"))
        layout.addWidget(self.max_concurrent_requests_input)

        self.save_path_input = QLineEdit()
        self.save_path_input.setPlaceholderText("保存路径")
        self.save_path_input.setReadOnly(True)  # 设置为只读
        layout.addWidget(QLabel("保存路径:"))
        layout.addWidget(self.save_path_input)

        self.select_folder_button = QPushButton("选择下载目录路径")
        self.select_folder_button.clicked.connect(self.select_folder)
        layout.addWidget(self.select_folder_button)

        self.start_button = QPushButton("开始下载")
        self.start_button.clicked.connect(self.start_download)
        layout.addWidget(self.start_button)

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        layout.addWidget(QLabel("日志输出:"))
        layout.addWidget(self.log_output)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

    def select_folder(self):
        folder_path = QFileDialog.getExistingDirectory(self, "选择下载目录")
        if folder_path:
            self.save_path_input.setText(folder_path)

    def start_download(self):
        url = self.url_input.text()
        use_proxy = self.use_proxy_checkbox.isChecked()
        proxy_type = self.proxy_type_combo.currentText()
        proxy_address = self.proxy_address_input.text()
        proxy_port = self.proxy_port_input.text()
        max_retries = self.max_retries_input.value()
        request_delay = self.request_delay_input.value()
        request_timeout = self.request_timeout_input.value()
        max_concurrent_requests = self.max_concurrent_requests_input.value()
        save_path = self.save_path_input.text()

        if not url or not save_path:
            QMessageBox.warning(self, "警告", "请填写所有必填字段")
        return

        self.download_thread = DownloadThread(
            url,
            use_proxy,
            proxy_type,
            proxy_address,
            proxy_port,
            max_retries,
            request_delay,
            request_timeout,
            max_concurrent_requests,
            save_path,
        )
        self.download_thread.finished.connect(self.download_finished)
        self.download_thread.progress.connect(self.update_log)
        self.download_thread.start()

    def download_finished(self):
        QMessageBox.information(self, "完成", "下载完成！")

    def update_log(self, message):
        self.log_output.append(message)

    def set_read_only(self, read_only):
        self.line_edit.setEnabled(not read_only)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
