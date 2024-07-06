import sys
import asyncio
import httpx
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
    QProgressBar,
    QMessageBox,
    QComboBox,
)
from PySide6.QtCore import QThread, Signal, Slot
from collections import deque
import os
import re
import aiofiles
from bs4 import BeautifulSoup


# 清理文件名的函数
def sanitize_filename(filename):
    filename = re.sub(r"[^\w\-\.]", "_", filename)
    filename = re.sub(r"[_\s]+", "_", filename).strip("_")
    return filename


# 异步获取页面 HTML 的函数
async def get_page_html(url, client, proxy=None, max_retries=3, request_timeout=30):
    retries = 0
    while retries < max_retries:
        try:
            response = await client.get(url, timeout=request_timeout)
            response.raise_for_status()
            return response.text
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 403:
                return None
            elif e.response.status_code == 429:
                wait_time = min(5 * (2**retries), 60)  # 指数回退
                retries += 1
                await asyncio.sleep(wait_time)
            else:
                return None
        except (httpx.RequestError, asyncio.TimeoutError) as e:
            retries += 1
            await asyncio.sleep(5)
    return None


# 异步下载文件的函数
async def download_file(
    url,
    file_name,
    client,
    save_path,
    progress_signal,
    log_signal,
    interrupted,
    proxy=None,
    max_retries=3,
    request_timeout=30,
    retry_queue=None,
):
    retries = 0
    while retries < max_retries:
        try:
            response = await client.get(url, timeout=request_timeout)
            response.raise_for_status()
            total_size = int(response.headers.get("content-length", 0))
            block_size = 4096

            if not os.path.exists(save_path):
                os.makedirs(save_path)

            file_path = os.path.join(save_path, file_name)
            temp_path = file_path + ".part"

            async with aiofiles.open(temp_path, "wb") as f:
                downloaded_size = 0
                async for data in response.aiter_bytes(block_size):
                    if interrupted[0]:
                        log_signal.emit("下载已中断")
                        return
                    await f.write(data)
                    downloaded_size += len(data)
                    progress = (downloaded_size / total_size) * 100 if total_size else 0
                    progress_signal.emit(progress)

            # 检查最终文件是否已经存在
            if os.path.exists(file_path):
                log_signal.emit(f"文件已存在: {file_path}")
                os.remove(temp_path)  # 如果存在则删除临时文件
            else:
                os.rename(temp_path, file_path)  # 将临时文件重命名为最终文件名
            return
        except (httpx.RequestError, asyncio.TimeoutError) as e:
            log_signal.emit(f"下载失败: {e}")
            retries += 1
            await asyncio.sleep(10)

            # 删除部分下载的文件和最终文件
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                if os.path.exists(file_path) and not os.path.exists(temp_path):
                    os.remove(file_path)
            except PermissionError:
                log_signal.emit(
                    f"无法删除文件: {temp_path} 或 {file_path}，可能正在被使用。"
                )

    log_signal.emit("达到最大重试次数，放弃下载，将任务加入重试队列。")
    if retry_queue is not None:
        retry_queue.append((url, file_name))


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


# 处理重试队列中的任务
async def handle_retry_queue(
    client,
    retry_queue,
    user_save_path,
    progress_signal,
    log_signal,
    interrupted,
    proxy,
    max_retries,
    request_timeout,
):
    while retry_queue:
        url, file_name = retry_queue.popleft()
        await download_file(
            url,
            file_name,
            client,
            user_save_path,
            progress_signal,
            log_signal,
            interrupted,
            proxy,
            max_retries,
            request_timeout,
            retry_queue,
        )


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
    progress_signal,
    log_signal,
    interrupted,
):
    links = []
    base_url = "https://kemono.su"
    retry_queue = deque()

    proxy = None
    if use_proxy:
        proxy = f"{proxy_type}://{proxy_address}:{proxy_port}"

    limits = httpx.Limits(
        max_keepalive_connections=max_concurrent_requests,
        max_connections=max_concurrent_requests,
    )
    async with httpx.AsyncClient(limits=limits, proxies=proxy) as client:
        html = await get_page_html(
            url,
            client,
            proxy,
            max_retries,
            request_timeout,
        )
        if html:
            soup = BeautifulSoup(html, "html.parser")
            user_name_tag = soup.find("fix_name")
            if user_name_tag:
                user_name = sanitize_filename(user_name_tag.get_text())
                user_save_path = os.path.join(save_path, user_name)
                if not os.path.exists(user_save_path):
                    os.makedirs(user_save_path)
                log_signal.emit(f"保存路径: {user_save_path}")
            else:
                log_signal.emit("无法找到用户名，使用默认保存路径")
                user_save_path = save_path

            while url:
                html = await get_page_html(
                    url,
                    client,
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

            async def download_with_semaphore(url, file_name, client):
                async with semaphore:
                    await download_file(
                        url,
                        file_name,
                        client,
                        user_save_path,  # 传递 user_save_path 参数
                        progress_signal,
                        log_signal,
                        interrupted,
                        proxy,
                        max_retries,
                        request_timeout,
                        retry_queue,
                    )

            tasks = []
            for link in links:
                if interrupted[0]:
                    log_signal.emit("任务已中断")
                    break
                html = await get_page_html(
                    link,
                    client,
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
                                    download_with_semaphore(href, file_name, client)
                                )
                                tasks.append(task)
                                await asyncio.sleep(request_delay)  # 添加请求之间的延迟

            await asyncio.gather(*tasks)

            # 处理重试队列中的任务
            if retry_queue:
                log_signal.emit("开始处理重试队列中的任务")
                await handle_retry_queue(
                    client,
                    retry_queue,
                    user_save_path,
                    progress_signal,
                    log_signal,
                    interrupted,
                    proxy,
                    max_retries,
                    request_timeout,
                )

    log_signal.emit("所有下载任务完成！")


# 下载线程类
class DownloadThread(QThread):
    finished = Signal()
    progress = Signal(float)
    log = Signal(str)

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
        self.interrupted = [False]

    def run(self):
        self.log.emit(f"Starting download from {self.url}")  # 发射日志信号
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
                self.progress,
                self.log,
                self.interrupted,
            )
        )
        self.finished.emit()

    def stop(self):
        self.interrupted[0] = True
        self.log.emit("下载任务已中止")  # 发射日志信号


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
        self.max_retries_input.setValue(10)
        layout.addWidget(QLabel("最大重试次数:"))
        layout.addWidget(self.max_retries_input)

        self.request_delay_input = QSpinBox()
        self.request_delay_input.setRange(1, 60)
        self.request_delay_input.setValue(30)
        layout.addWidget(QLabel("请求之间的延迟 (秒):"))
        layout.addWidget(self.request_delay_input)

        self.request_timeout_input = QSpinBox()
        self.request_timeout_input.setRange(10, 300)
        self.request_timeout_input.setValue(30)
        layout.addWidget(QLabel("请求超时时间 (秒):"))
        layout.addWidget(self.request_timeout_input)

        self.max_concurrent_requests_input = QSpinBox()
        self.max_concurrent_requests_input.setRange(1, 50)
        self.max_concurrent_requests_input.setValue(3)
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

        self.stop_button = QPushButton("停止下载")
        self.stop_button.clicked.connect(self.stop_download)
        self.stop_button.setEnabled(False)  # 初始状态下禁用停止按钮
        layout.addWidget(self.stop_button)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        layout.addWidget(QLabel("下载进度:"))
        layout.addWidget(self.progress_bar)

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
        self.download_thread.progress.connect(self.update_progress)
        self.download_thread.log.connect(self.update_log)
        self.download_thread.start()

        # 禁用开始按钮，启用停止按钮
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)

    def stop_download(self):
        if self.download_thread:
            self.download_thread.stop()
            self.log_output.append("停止下载请求已发送")

    def download_finished(self):
        QMessageBox.information(self, "完成", "下载完成！")

        # 启用开始按钮，禁用停止按钮
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)

    @Slot(float)
    def update_progress(self, value):
        self.progress_bar.setValue(value)

    @Slot(str)
    def update_log(self, message):
        print(f"Log received: {message}")  # 调试信息
        self.log_output.append(message)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
